"""v3.2 intraday paper execution and local runtime invariants."""

import json
import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.quant.futures_book import FuturesBook
from app.quant.runtime import PaperWorker, runtime_status, writer_lock
from app.quant.service import FuturesLedger, build_report
from app.quant.universe import target_portfolio


T = 1_800_000_000_000
MINUTE = 60_000


def target(symbol="ZECUSDT", weight=0.2, stop=90):
    return {"symbol": symbol, "weight": weight, "leverage": 3,
            "stop_price": stop, "entry_zone": [95, 105], "atr": 4}


def plan(signal="day-one", targets=()):
    targets = list(targets)
    return {"execution_policy": "daily_rebalance_intraday_entry",
            "version": "contracts-v3.2", "signal_id": signal,
            "max_positions": 10, "targets": targets,
            "entry_allowed_symbols": [item["symbol"] for item in targets],
            "invalidated_symbols": []}


def quote(price=100, *, mark=None):
    return {"bid": price, "ask": price, "mark": price if mark is None else mark}


def report(now, active_plan, prices):
    return {"plan": {**active_plan, "created_at": now,
                     "valid_until": now + 30 * MINUTE, "complete": True},
            "ranking": [{"symbol": symbol, "bid": price, "ask": price, "mark": price,
                         "quote_time": now, "book_time": now, "rejections": []}
                        for symbol, price in prices.items()]}


class IntradayBookTests(unittest.TestCase):
    def book(self):
        return FuturesBook(cash=10_000, fee_bps=0, slippage_bps=0)

    def test_outside_zone_waits_then_fills_once_even_after_restore(self):
        book = self.book()
        active = plan(targets=[target()])
        self.assertEqual(book.apply(active, {"ZECUSDT": quote(110)}, T, "day-one"), "applied")
        self.assertEqual(book.positions, {})
        self.assertEqual(book.last_decisions[0]["status"], "outside_entry_zone")
        self.assertEqual(book.apply(active, {"ZECUSDT": quote()}, T + MINUTE, "day-one"),
                         "pending_entry_filled")
        self.assertEqual(len([e for e in book.events if e["side"] == "buy"]), 1)
        restored = FuturesBook.restore(json.loads(json.dumps(book.dump())))
        self.assertEqual(restored.apply(active, {"ZECUSDT": quote()}, T + 2 * MINUTE,
                                        "day-one"), "monitoring")
        self.assertEqual(len([e for e in restored.events if e["side"] == "buy"]), 1)
        self.assertEqual(restored.last_decisions[0]["status"], "already_filled_today")

    def test_plan_stop_breach_cancels_waiting_entry_for_day(self):
        book = self.book()
        active = plan(targets=[target()])
        book.apply(active, {"ZECUSDT": quote(110)}, T, "day-one")
        self.assertEqual(book.apply(active, {"ZECUSDT": quote(88, mark=89)},
                                    T + MINUTE, "day-one"), "monitoring")
        self.assertEqual(book.cancelled_entries["ZECUSDT"], "plan_stop_breached")
        self.assertEqual(book.apply(active, {"ZECUSDT": quote()}, T + 2 * MINUTE,
                                    "day-one"), "monitoring")
        self.assertEqual(book.positions, {})
        self.assertEqual(book.last_decisions[0]["status"], "plan_stop_breached")

    def test_missing_unheld_quote_does_not_block_other_exit_or_entry(self):
        book = self.book()
        book.apply(plan(targets=[target()]), {"ZECUSDT": quote()}, T, "day-one")
        next_plan = plan("day-two", [target("ETHUSDT"), target("BTCUSDT")])
        result = book.apply(next_plan, {"ZECUSDT": quote(), "ETHUSDT": quote()},
                            T + MINUTE, "day-two")
        self.assertEqual(result, "applied")
        self.assertEqual(set(book.positions), {"ETHUSDT"})
        self.assertEqual(book.last_decisions[1]["status"], "missing_quote")
        self.assertTrue(any(e["symbol"] == "ZECUSDT" and e["side"] == "sell"
                            for e in book.events))

    def test_ten_actual_fills_obey_portfolio_stop_risk_budget(self):
        targets = [target(f"S{index}USDT", weight=0.18, stop=85)
                   for index in range(10)]
        for mark in (100, 102):
            with self.subTest(mark=mark):
                book = self.book()
                prices = {item["symbol"]: quote(mark=mark) for item in targets}
                self.assertEqual(book.apply(plan(targets=targets), prices, T, "day-one"), "applied")
                if mark == 100:
                    self.assertEqual(len(book.positions), 10)
                risk = sum(position["quantity"] * max(0, book.marks[symbol] - position["stop"])
                           for symbol, position in book.positions.items())
                self.assertLessEqual(risk, 0.25 * book.equity() + 1e-7)
                self.assertLessEqual(book.gross(), 1.8 * book.equity() + 1e-7)
                self.assertLessEqual(book.margin(), 0.65 * book.equity() + 1e-7)

    def test_ten_target_plan_caps_each_stop_risk_at_two_point_five_percent(self):
        randomizer = random.Random(20260924)
        ranked = []
        for index in range(10):
            symbol = f"S{index}USDT"
            ranked.append({"symbol": symbol, "base_asset": f"S{index}",
                           "action": "candidate", "selection_score": 100-index,
                           "asset_class": "COIN", "history_class": "seasoned",
                           "leverage": 3, "stop_price": 80, "ask": 100,
                           "entry_zone": [95, 105],
                           "market_cap": {"value_usd": 1_000_000_000},
                           "features": {"returns30": [randomizer.uniform(-.01, .01)
                                                       for _ in range(30)],
                                        "annual_vol": .5, "atr": 5, "close": 100}})
        result = target_portfolio(ranked, capital=10_000, max_positions=10,
                                  position_risk=.025, allow_waiting=True)
        self.assertEqual(len(result["targets"]), 10)
        self.assertLessEqual(result["planned_stop_risk"], .25 + 1e-9)
        for item in result["targets"]:
            stop_fraction = (100-item["stop_price"])/100
            self.assertLessEqual(item["weight"]*stop_fraction, .025 + 1e-9)


class HistoryAndLockTests(unittest.TestCase):
    def test_history_paginates_without_overlap_and_uses_real_closed_trades(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = FuturesLedger(Path(temporary)/"paper.sqlite3")
            assets = [target("ZECUSDT"), target("ETHUSDT")]
            ledger.step(report(T, plan(targets=assets),
                               {"ZECUSDT": 100, "ETHUSDT": 100}), now=T)
            coverage = {symbol: {"start": T, "end": T+MINUTE,
                                 "complete": True, "events": []}
                        for symbol in ("ZECUSDT", "ETHUSDT")}
            ledger.step(report(T+MINUTE, plan(targets=assets),
                               {"ZECUSDT": 85, "ETHUSDT": 85}),
                        now=T+MINUTE, funding=coverage)
            first = ledger.history(limit=2)
            second = ledger.history(limit=2, before=first["next_before"])
            self.assertEqual(first["total_events"], 4)
            self.assertEqual([event["id"] for event in first["events"]], [4, 3])
            self.assertEqual([event["id"] for event in second["events"]], [2, 1])
            self.assertIsNone(second["next_before"])
            self.assertEqual({trade["symbol"] for trade in first["closed_trades"]},
                             {"ZECUSDT", "ETHUSDT"})
            self.assertTrue(all(trade["reason"] == "gap_stop"
                                for trade in first["closed_trades"]))

    def test_writer_lock_rejects_competing_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            acquired = threading.Event()
            release = threading.Event()
            failures = []

            def holder():
                with writer_lock(output):
                    acquired.set()
                    release.wait(timeout=5)

            thread = threading.Thread(target=holder)
            thread.start()
            try:
                self.assertTrue(acquired.wait(timeout=5))
                with self.assertRaisesRegex(RuntimeError, "Another paper cycle is running"):
                    with writer_lock(output):
                        failures.append("duplicate writer entered")
                self.assertEqual(failures, [])
            finally:
                release.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            with writer_lock(output):
                pass

    def test_daily_target_weights_freeze_across_scans_then_refresh_next_day(self):
        snapshot = {"as_of": T, "exchange_info": {}, "tickers": [],
                    "book_tickers": [], "premium_index": [], "funding_info": [],
                    "histories": {}, "market_caps": []}
        zec = target("ZECUSDT", weight=.12)
        eth = target("ETHUSDT", weight=.25)
        research = {"targets": [zec], "gross_exposure": .12,
                    "margin_fraction": .04, "planned_stop_risk": .012}
        changed_research = {"targets": [eth], "gross_exposure": .25,
                            "margin_fraction": .0833, "planned_stop_risk": .025}
        with patch("app.quant.service.discover", return_value=[]), \
             patch("app.quant.service.rank_contracts", return_value=[]), \
             patch("app.quant.service.target_portfolio",
                   side_effect=[research, changed_research, changed_research]):
            first = build_report(snapshot)["plan"]
            rescanned = build_report(snapshot, active_plan=first)["plan"]
            next_day = build_report({**snapshot, "as_of": T + 86_400_000},
                                    active_plan=first)["plan"]
        self.assertEqual(rescanned["signal_id"], first["signal_id"])
        self.assertEqual(rescanned["targets"], [zec])
        self.assertEqual(rescanned["gross_exposure"], .12)
        self.assertNotEqual(next_day["signal_id"], first["signal_id"])
        self.assertEqual(next_day["targets"], [eth])


class PaperWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_cycle_is_visible_then_next_cycle_recovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            worker = PaperWorker(interval=10, refresh=10)
            observed = []
            calls = 0

            async def fake_to_thread(_function, _full):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("synthetic collector failure")
                worker.stop_event.set()
                return {"collection": {"source": "synthetic"},
                        "paper": {"valuation_complete": True, "status": "applied",
                                  "at": "2026-09-24T00:00:00+00:00",
                                  "positions": {}, "equity": 10_000}}

            async def fake_wait_for(awaitable, timeout):
                del timeout
                observed.append(runtime_status())
                if calls == 1:
                    awaitable.close()
                    raise TimeoutError
                return await awaitable

            with patch("app.quant.runtime.OUTPUT", output), \
                 patch("app.quant.runtime.asyncio.to_thread", side_effect=fake_to_thread), \
                 patch("app.quant.runtime.asyncio.wait_for", side_effect=fake_wait_for), \
                 patch("app.quant.runtime.LOG.exception") as error_log:
                await worker.run()
                final = runtime_status()
            self.assertEqual(calls, 2)
            self.assertEqual(observed[0]["state"], "error")
            self.assertIn("synthetic collector failure", observed[0]["last_error"])
            self.assertEqual(observed[0]["consecutive_errors"], 1)
            self.assertEqual(observed[1]["state"], "running")
            self.assertEqual(observed[1]["cycles_completed"], 1)
            self.assertEqual(observed[1]["consecutive_errors"], 0)
            self.assertIsNone(observed[1]["last_error"])
            self.assertEqual(final["state"], "stopped")
            error_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
