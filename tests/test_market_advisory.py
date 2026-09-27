"""Deterministic safety and chronology tests; no network or application startup."""

from dataclasses import replace
from math import nan
import unittest
from unittest.mock import patch

from app.advisory.engine import (
    Candle, DAY, Policy, analyze, analyze_daily, closed_candles, features,
    iso, normalize_symbol, plan, select_universe,
)
from app.advisory.replay import exit_fill, replay_symbol
from app.advisory.market import BinancePublicClient, MarketDataError, refresh_quotes
from app.advisory.replay import replay_ranking

START = 1704067200000


def candles(count=300, step=DAY, start=START, growth=0.001):
    result = []
    for i in range(count):
        price = 100 * (1 + growth) ** i
        result.append(Candle(start+i*step, price, price*1.01, price*0.99,
                             price, 100_000, start+(i+1)*step-1, 30_000_000))
    return result


def bullish_features():
    return dict(close=105, ema20=105, ema50=100, ema50_rising=True,
                extension_atr=0, atr=1, low10=102, prior_high20=104,
                prior_high60=100, volume_ratio=1.5)


class AdvisoryTests(unittest.TestCase):
    def test_symbol_scope_is_spot_and_not_execution_whitelist(self):
        self.assertEqual(normalize_symbol("zec/usdt"), "ZECUSDT")
        self.assertEqual(normalize_symbol("ZEC"), "ZECUSDT")
        for symbol in ("ZEC-USDT-SWAP", "ETH/USDT:USDT", "../secrets"):
            with self.assertRaises(ValueError):
                normalize_symbol(symbol)

    def test_policy_rejects_invalid_risk_and_nonfinite_values(self):
        for kwargs in ({"risk_budget_pct": 20}, {"fee_bps": nan}, {"max_candidates": 1.5}):
            with self.assertRaises(ValueError):
                Policy(**kwargs)

    def test_unclosed_candle_cannot_change_signal(self):
        daily, btc = candles(), candles(growth=0.0002)
        four = candles(300, DAY//6, START+250*DAY, growth=0.0003)
        as_of = START+300*DAY
        original = analyze("ZEC", daily, four, btc, as_of)
        future = replace(daily[-1], open_time=as_of, close_time=as_of+DAY-1,
                         high=10_000, close=10_000)
        self.assertEqual(original, analyze("ZEC", daily+[future], four, btc, as_of))

    def test_missing_just_closed_bar_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            closed_candles(candles(220), "1d", START+221*DAY+60_000, 220)

    def test_missing_duplicate_and_unsorted_bars_fail_closed(self):
        bars = candles()
        for bad in (bars[:250]+bars[251:], bars+[bars[-1]], list(reversed(bars))):
            with self.assertRaises(ValueError):
                closed_candles(bad, "1d", START+300*DAY, 220)

    def test_nonfinite_and_invalid_ohlc_fail_closed(self):
        for bad_bar in (replace(candles()[-1], close=nan), replace(candles()[-1], low=2000)):
            with self.assertRaises(ValueError):
                closed_candles(candles()[:-1]+[bad_bar], "1d", START+300*DAY, 220)

    def test_relative_strength_is_ratio_not_difference(self):
        d, b = candles(growth=.003), candles(growth=.001)
        result = analyze_daily("ZEC", d, b, START+300*DAY)
        expected = ((1.003 / 1.001) ** 30 - 1) * 100
        self.assertAlmostEqual(result["metrics"]["rs30_btc_pct"], expected)
        self.assertIsNone(result["win_probability"])

    def test_persistence_uses_each_days_ema(self):
        bars = candles(220, growth=0)
        for i in range(210, 219):
            bars[i] = replace(bars[i], close=101, high=102)
        bars[-1] = replace(bars[-1], close=220, high=221)
        self.assertEqual(features(bars)["trend_persistence10"], 1)

    def test_watchlist_cannot_override_filters(self):
        now = START+300*DAY
        info = {"symbols": [dict(symbol=s, baseAsset=s[:-4], quoteAsset="USDT",
                                  status="TRADING", isSpotTradingAllowed=True)
                            for s in ("BTCUSDT", "ZECUSDT", "USDCUSDT")]}
        ticker = dict(lastPrice="100", bidPrice="99.99", askPrice="100.01",
                      quoteVolume="30000000", closeTime=now)
        tickers = [dict(ticker, symbol=s) for s in ("BTCUSDT", "ZECUSDT", "USDCUSDT")]
        selected, rejected = select_universe(info, tickers, now, ["ZEC"], Policy(max_candidates=1))
        self.assertEqual(selected, ["BTCUSDT", "ZECUSDT"])
        self.assertIn("USDCUSDT", rejected)
        tickers[1]["quoteVolume"] = "5"
        selected, rejected = select_universe(info, tickers, now, ["ZEC"])
        self.assertNotIn("ZECUSDT", selected)
        self.assertIn("ZECUSDT", rejected)

    def test_overextended_trend_waits_instead_of_shorting(self):
        f = bullish_features()
        f["extension_atr"] = 5
        p = plan("short_term", f, f, 20, "normal", 90, START, Policy())
        self.assertEqual(p["action"], "wait_pullback")
        self.assertEqual(p["max_position_pct"], 0)

    def test_risk_off_market_does_not_open_new_positions(self):
        f = bullish_features()
        p = plan("long_term", f, f, 20, "risk_off", 90, START, Policy())
        self.assertEqual(p["action"], "watch")

    def test_costs_can_block_marginal_trade_and_position_is_capped(self):
        f = bullish_features()
        p = plan("short_term", f, f, 20, "normal", 90, START, Policy())
        self.assertEqual(p["action"], "buy_candidate")
        self.assertLessEqual(p["max_position_pct"], 10)
        self.assertLess(p["stop_loss"], p["entry_zone"][0])
        expensive = plan("short_term", f, f, 20, "normal", 90, START, Policy(fee_bps=200))
        self.assertEqual(expensive["action"], "watch")

    def test_weakening_trend_avoids_instead_of_inventing_long(self):
        f = bullish_features()
        f.update(close=95, ema50_rising=False)
        self.assertEqual(plan("short_term", f, f, 20, "normal", 90, START, Policy())["action"], "avoid")

    def test_replay_long_term_does_not_require_four_hour_history(self):
        bars = candles(250)
        r = replay_symbol("ZECUSDT", bars, [], bars, START+250*DAY, "long_term")
        self.assertEqual(r["start"], iso(START+220*DAY))
        self.assertEqual(len(r["signal_history"]), 30)

    def test_stop_priority_and_gap_loss(self):
        bar = Candle(START, 80, 130, 70, 100, 1, START+DAY-1, 100)
        self.assertEqual(exit_fill(bar, 90, 120), (80, "stop"))

    @staticmethod
    def fake_analysis(symbol, daily, btc, as_of, policy):
        return {"selection_score": 90, "daily_close_time": iso(daily[-1].close_time),
                "metrics": {"close": daily[-1].close}, "long_term": {
                    "action": "buy_candidate", "entry_zone": [99, 102], "stop_loss": 90,
                    "take_profit_reference": 120, "trailing_stop_reference": 80}}

    def test_replay_signals_before_fill_and_costs_on_entry_and_exit(self):
        bars = candles(221, growth=0)
        bars[-1] = replace(bars[-1], low=80, high=130)
        with patch("app.advisory.replay.analyze_daily", self.fake_analysis):
            paid = replay_symbol("ZECUSDT", bars, [], bars, START+221*DAY, "long_term")
            free = replay_symbol("ZECUSDT", bars, [], bars, START+221*DAY, "long_term", Policy(fee_bps=0, slippage_bps=0))
        self.assertEqual(paid["trade_count"], 1)
        trade = paid["trades"][0]
        self.assertLess(trade["signal_time"], trade["entry_time"])
        self.assertGreater(trade["entry_price"], 100)
        self.assertLess(trade["fills"][0]["price"], 90)
        # Compare per-unit trade return, because risk sizing also changes with cost.
        self.assertLess(trade["net_return_pct"], free["trades"][0]["net_return_pct"])

    def test_next_open_outside_zone_cannot_retroactively_fill(self):
        bars = candles(221, growth=0)
        bars[-1] = replace(bars[-1], open=150, high=160)
        with patch("app.advisory.replay.analyze_daily", self.fake_analysis):
            result = replay_symbol("ZECUSDT", bars, [], bars, START+221*DAY, "long_term")
        self.assertEqual(result["trade_count"], 0)

    def test_delivery_rechecks_price_staleness_spread_and_expiry(self):
        from copy import deepcopy
        from unittest.mock import Mock
        now = START+300*DAY
        p = {"action": "buy_candidate", "entry_zone": [99, 102], "valid_until": iso(now+DAY),
             "max_position_pct": 10, "account_risk_budget_pct": .5}
        template = {"ranking": [{"symbol": "ZECUSDT", "short_term": dict(p), "long_term": dict(p)}],
                    "data_errors": {}, "policy": {"max_spread_bps": 25}}
        good = {"symbol": "ZECUSDT", "lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01", "closeTime": now}
        for change in ({"lastPrice": "150"}, {"closeTime": now-300_000}, {"askPrice": "110"}):
            client = Mock(); client.get.return_value = [dict(good, **change)]
            with patch("app.advisory.market.time.time", return_value=now/1000):
                result = refresh_quotes(deepcopy(template), client)
            self.assertEqual(result["ranking"][0]["short_term"]["action"], "watch")
            self.assertEqual(result["ranking"][0]["short_term"]["max_position_pct"], 0)
        expired = deepcopy(template)
        expired["ranking"][0]["short_term"]["valid_until"] = iso(now)
        client.get.return_value = [good]
        with patch("app.advisory.market.time.time", return_value=now/1000):
            result = refresh_quotes(expired, client)
        self.assertEqual(result["ranking"][0]["short_term"]["action"], "watch")

    def test_network_deadline_fails_before_request(self):
        with patch("app.advisory.market.time.monotonic", return_value=10), patch("app.advisory.market.urlopen") as request:
            with self.assertRaisesRegex(MarketDataError, "deadline"):
                BinancePublicClient(deadline=9).get("time")
            request.assert_not_called()

    def test_ranking_is_fixed_before_future_outcomes_are_joined(self):
        def rows(bars):
            return [[b.open_time,b.open,b.high,b.low,b.close,b.volume,b.close_time,b.quote_volume] for b in bars]
        snapshot = {"as_of": START+300*DAY, "symbols": {
            "BTCUSDT": {"1d": rows(candles(growth=.0005))},
            "ZECUSDT": {"1d": rows(candles(growth=.002))}}}
        first = replay_ranking(snapshot, ["BTCUSDT", "ZECUSDT"], top_k=1)["observations"][0]
        # Change only bars after the first research time; its ranking must persist.
        for b in snapshot["symbols"]["ZECUSDT"]["1d"][221:]:
            for i in (1,2,3,4): b[i] *= 0.25
        later = replay_ranking(snapshot, ["BTCUSDT", "ZECUSDT"], top_k=1)["observations"][0]
        self.assertEqual([(r["symbol"],r["score"]) for r in first["ranking"]],
                         [(r["symbol"],r["score"]) for r in later["ranking"]])
        self.assertNotEqual(first["top_k_mean_forward_net_pct"], later["top_k_mean_forward_net_pct"])


if __name__ == "__main__":
    unittest.main()
