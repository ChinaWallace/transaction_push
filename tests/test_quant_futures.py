"""Contract-universe and paper-futures invariants using synthetic public data."""

import unittest

from app.quant.futures_book import FuturesBook
from app.quant.universe import (
    contract_features,
    discover,
    rank_contracts,
    target_portfolio,
)


DAY = 86_400_000
START = 1_704_067_200_000  # 2024-01-01 UTC


def daily_rows(count=45, *, start=START, daily_gain=0.005):
    rows = []
    for index in range(count):
        opened = start + index * DAY
        close = 100 * (1 + daily_gain) ** index
        rows.append(
            [
                opened,
                str(close * 0.995),
                str(close * 1.015),
                str(close * 0.985),
                str(close),
                "100000",
                opened + DAY - 1,
                str(close * 100000),
            ]
        )
    return rows


def market_payload(symbols, *, onboard=START, quote_time=START):
    info = {
        "symbols": [
            {
                "symbol": symbol,
                "baseAsset": symbol.removesuffix("USDT"),
                "status": "TRADING",
                "quoteAsset": "USDT",
                "contractType": kind,
                "underlyingType": "COIN" if kind == "PERPETUAL" else "EQUITY",
                "onboardDate": onboard,
            }
            for symbol, kind in symbols
        ]
    }
    tickers = [
        {"symbol": symbol, "quoteVolume": "100000000", "closeTime": quote_time}
        for symbol, _ in symbols
    ]
    books = [
        {"symbol": symbol, "bidPrice": "99.9", "askPrice": "100.1", "time": quote_time}
        for symbol, _ in symbols
    ]
    marks = [
        {
            "symbol": symbol,
            "markPrice": "100",
            "indexPrice": "100",
            "lastFundingRate": "0.0001",
            "time": quote_time,
        }
        for symbol, _ in symbols
    ]
    return info, tickers, books, marks


def target(symbol="ZECUSDT", *, weight=0.3, leverage=3):
    return {
        "symbol": symbol,
        "weight": weight,
        "leverage": leverage,
        "stop_price": 80,
        "entry_zone": [99, 101],
    }


def quote(price=100):
    return {"bid": price, "ask": price, "mark": price}


class ContractUniverseTests(unittest.TestCase):
    def test_missing_book_keeps_contract_visible_but_cannot_rank_as_buy(self):
        as_of = START + 45 * DAY
        info, tickers, _, marks = market_payload(
            [("BTCUSDT", "PERPETUAL")], quote_time=as_of
        )
        universe = discover(info, tickers, [], marks, as_of)
        ranked = rank_contracts(universe, {"BTCUSDT": daily_rows()}, [], as_of)
        self.assertEqual(ranked[0]["action"], "excluded")
        self.assertIn("missing_or_invalid_quote", ranked[0]["rejections"])
        self.assertFalse(ranked[0]["hold_eligible"])
        self.assertEqual(target_portfolio(ranked)["targets"], [])

    def test_discover_includes_every_tradifi_perpetual_alongside_crypto(self):
        contracts = [
            ("BTCUSDT", "PERPETUAL"),
            ("SKHYUSDT", "TRADIFI_PERPETUAL"),
            ("TSLAUSDT", "TRADIFI_PERPETUAL"),
            ("XAUUSDT", "TRADIFI_PERPETUAL"),
        ]
        universe = discover(
            *market_payload(contracts, quote_time=START + 45 * DAY),
            as_of=START + 45 * DAY,
        )
        by_symbol = {row["symbol"]: row for row in universe}
        self.assertEqual(set(by_symbol), {symbol for symbol, _ in contracts})
        for symbol, kind in contracts:
            self.assertEqual(by_symbol[symbol]["contract_type"], kind)
        self.assertEqual(by_symbol["TSLAUSDT"]["asset_class"], "EQUITY")

    def test_thirty_day_history_can_be_ranked_as_young_with_one_x_leverage(self):
        symbol = "SKHYUSDT"
        as_of = START + 30 * DAY
        universe = discover(
            *market_payload([(symbol, "TRADIFI_PERPETUAL")], quote_time=as_of),
            as_of=as_of,
        )
        ranked = rank_contracts(
            universe,
            {symbol: daily_rows(30)},
            [],
            as_of=as_of,
        )
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["history_class"], "young")
        self.assertEqual(ranked[0]["leverage"], 1)

    def test_missing_daily_bar_rejected_and_future_bar_cannot_change_past(self):
        rows = daily_rows()
        as_of = START + 45 * DAY
        baseline = contract_features(rows, as_of=as_of)
        future = daily_rows(46)
        future[-1][4] = "999999"
        self.assertEqual(contract_features(future, as_of=as_of), baseline)
        with self.assertRaisesRegex(ValueError, "gapped"):
            contract_features(rows[:20] + rows[21:], as_of=as_of)

    def test_leverage_above_three_rejected_at_research_and_execution(self):
        with self.assertRaises(ValueError):
            rank_contracts({}, {}, {}, as_of=START, max_leverage=4)
        with self.assertRaises(ValueError):
            FuturesBook().add(target(leverage=4), bid=100, ask=100, now=START)

    def test_portfolio_target_separates_weight_notional_and_margin(self):
        ranked = [
            {
                "symbol": "BTCUSDT",
                "base_asset": "BTC",
                "action": "candidate",
                "score": 90,
                "asset_class": "COIN",
                "history_class": "seasoned",
                "leverage": 3,
                "stop_price": 80,
                "ask": 100,
                "market_cap": {"value_usd": 1_000_000_000},
                "features": {"returns30": [0.0] * 30, "atr": 5, "close": 100},
                "entry_zone": [95, 105],
                "selection_score": 90,
            }
        ]
        plan = target_portfolio(ranked, capital=10_000)
        item = plan["targets"][0]
        self.assertLessEqual(item["leverage"], 3)
        self.assertAlmostEqual(item["notional_usdt"], 10_000 * item["weight"])
        self.assertAlmostEqual(
            item["margin_usdt"], item["notional_usdt"] / item["leverage"]
        )


class FuturesBookTests(unittest.TestCase):
    def open_book(self):
        book = FuturesBook(cash=10_000, fee_bps=0, slippage_bps=0)
        self.assertEqual(
            book.apply(
                {"targets": [target()]},
                {"ZECUSDT": quote()},
                now=START,
                signal_id="first",
            ),
            "applied",
        )
        return book

    def test_notional_margin_wallet_and_equity_have_distinct_meanings(self):
        book = self.open_book()
        self.assertAlmostEqual(book.gross(), 3_000)
        self.assertAlmostEqual(book.margin(), 1_000)
        self.assertAlmostEqual(book.wallet, 10_000)
        self.assertAlmostEqual(book.equity(), 10_000)
        book.observe(START + 1, {"ZECUSDT": quote(110)})
        self.assertAlmostEqual(book.gross(), 3_300)
        self.assertAlmostEqual(book.margin(), 1_000)
        self.assertAlmostEqual(book.equity(), 10_300)

    def test_positive_negative_funding_and_replay_idempotence(self):
        book = self.open_book()
        book.funding("ZECUSDT", START + 1, 0.01, 100)
        self.assertAlmostEqual(book.wallet, 9_970)
        book.funding("ZECUSDT", START + 1, 0.01, 100)
        self.assertAlmostEqual(book.wallet, 9_970)
        book.funding("ZECUSDT", START + 2, -0.02, 100)
        self.assertAlmostEqual(book.wallet, 10_030)
        restored = FuturesBook.restore(book.dump())
        restored.funding("ZECUSDT", START + 2, -0.02, 100)
        self.assertAlmostEqual(restored.wallet, 10_030)
        self.assertEqual(
            sum(event["side"] == "funding" for event in restored.events), 2
        )

    def test_duplicate_signal_does_not_trade_twice(self):
        book = self.open_book()
        original_quantity = book.positions["ZECUSDT"]["quantity"]
        original_events = len(book.events)
        self.assertEqual(
            book.apply(
                {"targets": [target()]},
                {"ZECUSDT": quote()},
                now=START + 1,
                signal_id="first",
            ),
            "duplicate_signal",
        )
        self.assertEqual(book.positions["ZECUSDT"]["quantity"], original_quantity)
        self.assertEqual(len(book.events), original_events)

    def test_missing_held_quote_freezes_rebalance_and_new_entries(self):
        book = self.open_book()
        original = book.dump()
        self.assertEqual(
            book.apply(
                {"targets": [target("ETHUSDT")]},
                {"ETHUSDT": quote()},
                now=START + 1,
                signal_id="second",
            ),
            "missing_position_quote",
        )
        self.assertEqual(set(book.positions), {"ZECUSDT"})
        self.assertEqual(book.last_plan, original["last_plan"])
        self.assertEqual(book.wallet, original["wallet"])


if __name__ == "__main__":
    unittest.main()
