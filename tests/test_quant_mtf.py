"""Deterministic boundaries for the closed-bar multiframe paper strategy."""

import math
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.quant.futures_book import FuturesBook
from app.quant.multiframe import PERIODS, VERSION, features
from app.quant.service import FuturesLedger, build_report


FOUR_HOURS = PERIODS["4h"]
T = (1_800_000_000_000 // FOUR_HOURS) * FOUR_HOURS


def bars(timeframe, *, as_of=T, count=80):
    period = PERIODS[timeframe]
    last_open = (as_of // period - 1) * period
    result = []
    for i in range(count):
        opened = last_open - (count - 1 - i) * period
        close = 100 * math.exp(0.025 * math.sin(i * 1.7) + 0.002 * i)
        result.append([opened, str(close * .99), str(close * 1.02),
                       str(close * .98), str(close), "100000", opened + period - 1,
                       str(5_000_000 + i * 1000)])
    return result


def target(symbol="ZECUSDT", *, stop=90, weight=.2):
    return {"symbol": symbol, "weight": weight, "leverage": 2,
            "stop_price": stop, "entry_zone": [95, 105], "atr": 4}


def quote(price=100):
    return {"bid": price, "ask": price, "mark": price}


def mtf_plan(now, signal, targets, *, exits=None, complete=True, evidence_closed_at=None):
    closed_at = (now // PERIODS["15m"] * PERIODS["15m"] - 1
                 if evidence_closed_at is None else evidence_closed_at)
    return {"version": VERSION, "execution_policy": "multiframe_rotation",
            "strategy_schema": 4, "signal_id": signal, "created_at": now,
            "valid_until": now + 30 * 60_000, "signal_expires_at": ((now // FOUR_HOURS) + 1) * FOUR_HOURS,
            "complete": complete, "targets": targets,
            "position_risk_budget": .025,
            "entry_allowed_symbols": [t["symbol"] for t in targets],
            "exit_signals": exits or {}, "cooldown_ms": 3_600_000,
            "max_hold_ms": 72 * 3_600_000, "trailing_atr_multiplier": 3,
            "signal_evidence": {t["symbol"]: {"execution_closed_at": closed_at}
                                for t in targets},
            "protective_updates": {t["symbol"]: {"atr": t["atr"],
                                                   "stop_price": t["stop_price"],
                                                   "closed_at": closed_at} for t in targets}}


def paper_report(plan, now, prices):
    return {"plan": plan, "ranking": [
        {"symbol": symbol, "bid": price, "ask": price, "mark": price,
         "quote_time": now, "book_time": now, "rejections": []}
        for symbol, price in prices.items()]}


class ClosedBarTests(unittest.TestCase):
    def test_incomplete_and_future_bars_cannot_change_a_past_signal(self):
        for tf, period in PERIODS.items():
            with self.subTest(timeframe=tf):
                history = bars(tf)
                baseline = features(history, tf, T)
                future = [T, "100", "1000000", "1", "999999", "100000",
                          T + period - 1, "999999999"]
                self.assertEqual(features(history + [future], tf, T), baseline)
                self.assertEqual(baseline["closed_at"], T - 1)

    def test_each_timeframe_rejects_stale_and_gapped_closed_bars(self):
        for tf in PERIODS:
            with self.subTest(timeframe=tf):
                history = bars(tf)
                with self.assertRaisesRegex(ValueError, f"stale_{tf}_bars"):
                    features(history[:-1], tf, T)
                with self.assertRaisesRegex(ValueError, f"invalid_or_gapped_{tf}_bars"):
                    features(history[:30] + history[31:], tf, T)

    def test_four_hour_volatility_has_2190_periods_per_year(self):
        history = bars("4h")
        close = [float(row[4]) for row in history]
        observed = features(history, "4h", T)
        returns = [math.log(b / a) for a, b in zip(close[-61:-1], close[-60:])]
        self.assertEqual(observed["annualization_periods"], 365 * 6)
        self.assertAlmostEqual(observed["annual_vol"],
                               max(.1, statistics.pstdev(returns) * math.sqrt(365 * 6)))


class PlanCadenceTests(unittest.TestCase):
    @staticmethod
    def ranking(symbol, closed_at, trigger, zone):
        return {"symbol": symbol, "action": "candidate" if trigger else "wait_15m_trigger",
                "contract_type": "PERPETUAL", "asset_class": "COIN",
                "signal": {"selection_closed_at": closed_at, "confirmation_closed_at": closed_at,
                           "execution_closed_at": closed_at, "exit_1h": False, "exit_15m": False,
                           "trigger_15m": trigger},
                "features": {"atr": 4}, "entry_zone": zone, "stop_price": 90,
                "ask": 100,
                "market_cap": {"value_usd": None}, "rejections": []}

    def test_four_hour_target_freezes_while_fifteen_minute_signals_refresh(self):
        def build(now, ranked, active=None):
            snapshot = {"as_of": now, "exchange_info": {}, "tickers": [],
                        "book_tickers": [], "premium_index": [], "funding_info": [],
                        "multiframe_histories": {"ZECUSDT": {}, "ETHUSDT": {}},
                        "market_caps": []}

            def select(rows, *_args, **_kwargs):
                first = rows[0]["symbol"]
                return {"targets": [target(first, weight=.2 if first == "ZECUSDT" else .3)],
                        "max_positions": 10}

            with patch("app.quant.service.discover", return_value=ranked), \
                 patch("app.quant.multiframe.rank_multiframe", return_value=ranked), \
                 patch("app.quant.service.target_portfolio", side_effect=select):
                return build_report(snapshot, active_plan=active)["plan"]

        first = build(T, [self.ranking("ZECUSDT", T - 1, "breakout_15m", [95, 105])])
        later = build(T + PERIODS["15m"],
                      [self.ranking("ETHUSDT", T - 1, "breakout_15m", [95, 105]),
                       self.ranking("ZECUSDT", T - 1, "pullback_reclaim_15m", [97, 103])], first)
        self.assertEqual(first["signal_id"], later["signal_id"])
        self.assertEqual([(t["symbol"], t["weight"]) for t in later["targets"]],
                         [("ZECUSDT", .2)])
        self.assertEqual(later["targets"][0]["entry_zone"], [97, 103])
        self.assertEqual(later["signal_evidence"]["ZECUSDT"]["trigger_15m"],
                         "pullback_reclaim_15m")
        next_cycle = build(T + FOUR_HOURS,
                           [self.ranking("ETHUSDT", T + FOUR_HOURS - 1,
                                         "breakout_15m", [95, 105])], later)
        self.assertNotEqual(next_cycle["signal_id"], first["signal_id"])
        self.assertEqual(next_cycle["targets"][0]["symbol"], "ETHUSDT")

    def test_frozen_weight_reports_risk_at_refreshed_stop_and_ask(self):
        snapshot = {"as_of": T + PERIODS["15m"], "exchange_info": {},
                    "tickers": [], "book_tickers": [], "premium_index": [],
                    "funding_info": [], "multiframe_histories": {"ZECUSDT": {}},
                    "market_caps": []}
        row = self.ranking("ZECUSDT", T - 1, "breakout_15m", [95, 105])
        row["stop_price"] = 90
        active = mtf_plan(T, f"{VERSION}:{T // FOUR_HOURS}:3",
                          [target(stop=98, weight=.35)])
        active["planned_stop_risk"] = .007
        with patch("app.quant.service.discover", return_value=[row]), \
             patch("app.quant.multiframe.rank_multiframe", return_value=[row]), \
             patch("app.quant.service.target_portfolio", return_value={"targets": []}):
            refreshed = build_report(snapshot, active_plan=active)["plan"]
        self.assertEqual(refreshed["targets"][0]["weight"], .35)
        self.assertEqual(refreshed["targets"][0]["stop_price"], 90)
        self.assertAlmostEqual(refreshed["planned_stop_risk"], .035)


class PaperLifecycleTests(unittest.TestCase):
    def test_actual_fill_enforces_single_position_risk_after_stop_drift(self):
        book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
        book.apply(mtf_plan(T, "cycle", [target(stop=90, weight=.35)]),
                   {"ZECUSDT": quote()}, T, "cycle")
        position = book.positions["ZECUSDT"]
        actual_stop_risk = position["quantity"] * (position["entry"] - position["stop"])
        self.assertLessEqual(actual_stop_risk, .025 * book.equity() + 1e-8)
        self.assertAlmostEqual(actual_stop_risk / book.equity(), .025)

    def test_same_cycle_protective_stop_only_rises_for_existing_lot(self):
        book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
        first = target(stop=90)
        first["atr"] = 20
        book.apply(mtf_plan(T, "cycle", [first]), {"ZECUSDT": quote()}, T, "cycle")
        raised = target(stop=97)
        raised["atr"] = 20
        book.apply(mtf_plan(T + 1, "cycle", [raised]),
                   {"ZECUSDT": quote()}, T + 1, "cycle")
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 97)
        lower = target(stop=95)
        lower["atr"] = 20
        book.apply(mtf_plan(T + 2, "cycle", [lower]),
                   {"ZECUSDT": quote()}, T + 2, "cycle")
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 97)

    def test_old_fifteen_minute_exit_evidence_cannot_exit_on_fresh_quote(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = FuturesLedger(Path(folder) / "paper.sqlite3", 10_000)
            opened = ledger.step(paper_report(mtf_plan(T, "cycle", [target()]),
                                              T, {"ZECUSDT": 100}), now=T)
            self.assertIn("ZECUSDT", opened["positions"])
            later = T + PERIODS["15m"]
            stale = mtf_plan(later, "cycle", [target()],
                             exits={"ZECUSDT": "15m_structure_exit"},
                             evidence_closed_at=T - 1)
            result = ledger.step(paper_report(stale, later, {"ZECUSDT": 100}),
                                 now=later,
                                 funding={"ZECUSDT": {"start": T, "end": later,
                                                      "complete": True, "events": []}})
            self.assertFalse(result["fresh_plan"])
            self.assertEqual(result["status"], "incomplete_research")
            self.assertIn("ZECUSDT", result["positions"])
            self.assertEqual(ledger.history()["closed_trades"], [])

    def test_hourly_and_fifteen_minute_exits_survive_missing_funding(self):
        for exit_reason in ("hourly_trend_exit", "15m_structure_exit"):
            with self.subTest(reason=exit_reason), tempfile.TemporaryDirectory() as folder:
                ledger = FuturesLedger(Path(folder) / "paper.sqlite3", 10_000)
                opened = ledger.step(paper_report(mtf_plan(T, "cycle", [target()]),
                                                  T, {"ZECUSDT": 100}), now=T)
                self.assertIn("ZECUSDT", opened["positions"])
                later = T + PERIODS["15m"]
                plan = mtf_plan(later, "cycle", [target()], exits={"ZECUSDT": exit_reason})
                exited = ledger.step(paper_report(plan, later, {"ZECUSDT": 100}),
                                     now=later, funding=None)
                self.assertEqual(exited["status"], "incomplete_research")
                self.assertEqual(exited["positions"], {})
                self.assertEqual(exited["missing_funding"], ["ZECUSDT"])
                self.assertEqual(ledger.history()["closed_trades"][0]["reason"], exit_reason)

    def test_one_entry_per_four_hour_cycle_persists_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "paper.sqlite3"
            ledger = FuturesLedger(db, 10_000)
            opened = ledger.step(paper_report(mtf_plan(T, "cycle", [target()]),
                                              T, {"ZECUSDT": 100}), now=T)
            self.assertEqual(opened["fills_total"], 1)
            second_at = T + PERIODS["15m"]
            restarted = FuturesLedger(db, 10_000)
            repeated = restarted.step(paper_report(mtf_plan(second_at, "cycle", [target()]),
                                                   second_at, {"ZECUSDT": 100}), now=second_at,
                                      funding={"ZECUSDT": {"start": T, "end": second_at,
                                                           "complete": True, "events": []}})
            self.assertEqual(repeated["fills_total"], 1)
            self.assertEqual(repeated["decisions"][0]["status"], "already_filled_cycle")

    def test_legacy_lot_exits_explicitly_without_relabeling_or_resetting_wallet(self):
        book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
        legacy = {"version": "contracts-v3.2", "targets": [target()],
                  "execution_policy": "daily_rebalance_intraday_entry"}
        self.assertEqual(book.apply(legacy, {"ZECUSDT": quote()}, T, "old"), "applied")
        old_quantity = book.positions["ZECUSDT"]["quantity"]
        old_events = len(book.events)
        old_wallet = book.wallet
        book.apply(mtf_plan(T + 1, "new", [target("ETHUSDT")]),
                   {"ZECUSDT": quote(), "ETHUSDT": quote()}, T + 1, "new")
        self.assertEqual(book.closed[-1]["reason"], "strategy_migration_exit")
        self.assertEqual(book.events[old_events]["strategy"], "contracts-v3.2")
        self.assertEqual(book.events[old_events]["quantity"], old_quantity)
        self.assertEqual(book.wallet, old_wallet)
        self.assertNotIn("ZECUSDT", book.positions)
        self.assertEqual(book.positions["ETHUSDT"]["strategy"], VERSION)


if __name__ == "__main__":
    unittest.main()
