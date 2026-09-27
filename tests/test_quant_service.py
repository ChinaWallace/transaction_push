"""Transactional futures ledger and local-only research API invariants."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx

from app.quant.api import app
from app.quant.futures_book import FuturesBook
from app.quant.service import FuturesLedger


T = 1_780_000_000_000
MINUTE = 60_000


def target(symbol="ZECUSDT", weight=0.2):
    return {
        "symbol": symbol,
        "weight": weight,
        "leverage": 3,
        "stop_price": 90,
        "entry_zone": [95, 105],
        "atr": 4,
    }


def report(now, signal, targets=(), quotes=None, *, complete=True, quote_time=None, book_time=None):
    quotes = quotes if quotes is not None else {t["symbol"]: 100 for t in targets}
    return {
        "plan": {
            "created_at": now,
            "valid_until": now + 30 * MINUTE,
            "signal_id": signal,
            "complete": complete,
            "targets": list(targets),
        },
        "ranking": [
            {
                "symbol": symbol,
                "bid": price,
                "ask": price,
                "mark": price,
                "quote_time": now if quote_time is None else quote_time,
                "book_time": now if book_time is None else book_time,
                "rejections": [],
            }
            for symbol, price in quotes.items()
        ],
    }


def funding(start, end, *events):
    return {
        "ZECUSDT": {
            "start": start,
            "end": end,
            "complete": True,
            "events": [
                {"fundingTime": at, "fundingRate": rate, "markPrice": mark}
                for at, rate, mark in events
            ],
        }
    }


class FuturesLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "paper.sqlite3"
        self.ledger = FuturesLedger(self.db, 10_000)

    def book(self):
        with closing(sqlite3.connect(self.db)) as conn:
            state = json.loads(conn.execute("SELECT state FROM account WHERE id=1").fetchone()[0])
        return FuturesBook.restore(state)

    def test_invalid_funding_mark_is_unsettled_and_cannot_silently_charge_zero(self):
        self.ledger.step(report(T, "open", [target()]), now=T)
        now = T + 10 * MINUTE
        result = self.ledger.step(
            report(now, "stop", [], {"ZECUSDT": 85}), now=now,
            funding=funding(T, now, (T + MINUTE, 0.001, 0)),
        )
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["missing_funding"], ["ZECUSDT"])
        self.assertEqual(len(result["pending_funding_debts"]), 1)
        self.assertFalse(any(e["side"] == "funding" for e in self.book().events))

    def test_funding_settles_old_quantity_before_add_and_new_quantity_before_reduce(self):
        first = self.ledger.step(report(T, "one", [target()]), now=T)
        self.assertEqual(first["status"], "applied")
        original_qty = first["positions"]["ZECUSDT"]["quantity"]

        at_add = T + 10 * MINUTE
        event_one = (T + 5 * MINUTE, 0.001, 100)
        second = self.ledger.step(
            report(at_add, "two", [target(weight=0.35)]),
            now=at_add,
            funding=funding(T, at_add, event_one),
        )
        increased_qty = second["positions"]["ZECUSDT"]["quantity"]
        self.assertGreater(increased_qty, original_qty)
        first_payment = [e for e in self.book().events if e["side"] == "funding"][0]["payment"]
        self.assertAlmostEqual(first_payment, original_qty * 100 * 0.001)

        at_reduce = T + 20 * MINUTE
        event_two = (T + 15 * MINUTE, -0.002, 100)
        third = self.ledger.step(
            report(at_reduce, "three", [target(weight=0.1)]),
            now=at_reduce,
            funding=funding(T, at_reduce, event_one, event_two),
        )
        self.assertLess(third["positions"]["ZECUSDT"]["quantity"], increased_qty)
        book = self.book()
        payments = [e["payment"] for e in book.events if e["side"] == "funding"]
        self.assertEqual(len(payments), 2)
        self.assertAlmostEqual(payments[1], increased_qty * 100 * -0.002)
        self.assertEqual(book.funding_cursor["ZECUSDT"], at_reduce)

    def test_missing_funding_allows_stop_records_debt_and_blocks_new_entry_until_settled(self):
        opened = self.ledger.step(report(T, "open", [target()]), now=T)
        original_qty = opened["positions"]["ZECUSDT"]["quantity"]
        stopped_at = T + 10 * MINUTE
        stopped = self.ledger.step(
            report(stopped_at, "stop", [target("ETHUSDT")], {"ZECUSDT": 85, "ETHUSDT": 100}),
            now=stopped_at,
            funding=None,
        )
        self.assertEqual(stopped["status"], "incomplete_research")
        self.assertEqual(stopped["positions"], {})
        self.assertEqual(stopped["missing_funding"], ["ZECUSDT"])
        self.assertEqual(len(stopped["pending_funding_debts"]), 1)
        self.assertEqual(stopped["pending_funding_debts"][0]["quantity"], original_qty)
        self.assertEqual(self.book().closed[-1]["reason"], "gap_stop")

        still_pending = self.ledger.step(
            report(T + 11 * MINUTE, "blocked", [target("ETHUSDT")]),
            now=T + 11 * MINUTE,
        )
        self.assertEqual(still_pending["status"], "incomplete_research")
        self.assertEqual(still_pending["positions"], {})

        event = (T + 5 * MINUTE, 0.001, 100)
        settled = self.ledger.step(
            report(T + 12 * MINUTE, "settle", []),
            now=T + 12 * MINUTE,
            funding=funding(T, T + 12 * MINUTE, event),
        )
        self.assertEqual(settled["pending_funding_debts"], [])
        book = self.book()
        self.assertAlmostEqual(
            book.closed[-1]["pnl"],
            book.events[1]["pnl"] - book.events[0]["fee"] - original_qty * 100 * 0.001,
        )
        self.assertEqual(len([e for e in book.events if e["side"] == "funding"]), 1)

        reopened = self.ledger.step(
            report(T + 13 * MINUTE, "reopen", [target("ETHUSDT")]),
            now=T + 13 * MINUTE,
        )
        self.assertEqual(set(reopened["positions"]), {"ETHUSDT"})
        repeated = self.ledger.step(
            report(T + 14 * MINUTE, "again", []),
            now=T + 14 * MINUTE,
            funding=funding(T, T + 14 * MINUTE, event),
        )
        self.assertEqual(repeated["pending_funding_debts"], [])
        self.assertEqual(len([e for e in self.book().events if e["side"] == "funding"]), 1)

    def test_stale_book_or_mark_prevents_fill(self):
        for stale_field in ("quote_time", "book_time"):
            with self.subTest(stale_field=stale_field):
                ledger = FuturesLedger(Path(self.temp.name) / f"{stale_field}.sqlite3")
                kwargs = {stale_field: T - 181_000}
                result = ledger.step(report(T, stale_field, [target()], **kwargs), now=T)
                self.assertEqual(result["positions"], {})
                self.assertEqual(result["fills_total"], 0)

    def test_expired_plan_does_not_enter_even_with_fresh_quotes(self):
        old = report(T - 31 * MINUTE, "expired", [target()])
        old["ranking"] = report(T, "quotes", [target()])["ranking"]
        result = self.ledger.step(old, now=T)
        self.assertFalse(result["fresh_plan"])
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["status"], "incomplete_research")

    def test_recent_imported_funding_uses_its_captured_cutoff(self):
        self.ledger.step(report(T, "open", [target()]), now=T)
        captured = T + MINUTE
        with patch("app.quant.service.time.time", return_value=(captured + 2000) / 1000):
            result = self.ledger.step(
                report(captured, "open", [target()]),
                funding=funding(T, captured, (T + 30_000, 0.001, 100)),
            )
        self.assertEqual(result["missing_funding"], [])
        self.assertEqual(result["status"], "duplicate_signal")
        self.assertEqual(self.book().last_time, captured)

    def test_future_quote_is_not_executable_at_an_earlier_cutoff(self):
        result = self.ledger.step(
            report(T, "future", [target()], quote_time=T+1, book_time=T+1), now=T
        )
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["status"], "missing_target_quote")


class QuantApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_contracts_recomputes_staleness_at_read_time(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "latest.json").write_text(json.dumps({
                "snapshot_time": T,
                "snapshot_fresh": True,
                "quote_age_seconds": 0,
                "plan": {"complete": True},
            }))
            with patch.object(app.state.settings, "quant_output_dir", output):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    with patch("app.quant.api.time.time", return_value=T / 1000 + 100):
                        fresh = (await client.get("/api/quant/contracts")).json()
                    with patch("app.quant.api.time.time", return_value=T / 1000 + 181):
                        stale = (await client.get("/api/quant/contracts")).json()
            self.assertTrue(fresh["snapshot_fresh"])
            self.assertTrue(fresh["executable_now"])
            self.assertFalse(stale["snapshot_fresh"])
            self.assertFalse(stale["executable_now"])
            self.assertGreater(stale["quote_age_seconds"], 180)

    async def test_paper_post_rejects_remote_and_browser_origin(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app.state.settings, "quant_output_dir", Path(directory)), \
             patch.object(app.state.settings, "quant_data_dir", Path(directory) / "data"), \
             patch.object(app.state.settings, "quant_initial_capital", 12_345), \
             patch("app.quant.api.scan", return_value={"plan": {}}) as scan, \
             patch("app.quant.api.FuturesLedger") as ledger_type:
            ledger_type.return_value.step.return_value = {"mode": "paper", "live": False}
            local = httpx.ASGITransport(app=app, client=("127.0.0.1", 123))
            remote = httpx.ASGITransport(app=app, client=("10.0.0.2", 123))
            async with httpx.AsyncClient(transport=remote, base_url="http://test") as client:
                self.assertEqual((await client.post("/api/quant/paper/step")).status_code, 403)
            async with httpx.AsyncClient(transport=local, base_url="http://test") as client:
                self.assertEqual((await client.post("/api/quant/paper/step", headers={"Origin": "https://example.org"})).status_code, 403)
                accepted = await client.post("/api/quant/paper/step")
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json(), {"mode": "paper", "live": False})
            scan.assert_called_once_with(Path(directory) / "data", Path(directory), 12_345)
            ledger_type.assert_called_once_with(Path(directory) / "paper.sqlite3", 12_345)
            ledger_type.return_value.step.assert_called_once()

    async def test_app_settings_custom_output_is_used_by_status_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "latest.json").write_text(json.dumps({
                "snapshot_time": T,
                "plan": {"complete": True},
                "marker": "custom-output",
            }))
            (output / "runtime.json").write_text(json.dumps({"state": "stopped", "marker": "custom-runtime"}))
            with patch.object(app.state.settings, "quant_output_dir", output), \
                 patch.object(app.state.settings, "quant_initial_capital", 12_345), \
                 patch("app.quant.api.report_markdown", return_value="custom report") as render:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    with patch("app.quant.api.time.time", return_value=T / 1000 + 1):
                        contracts_response = await client.get("/api/quant/contracts")
                        report_response = await client.get("/api/quant/report")
                    paper_response = await client.get("/api/quant/paper")
                    runtime_response = await client.get("/api/quant/runtime")
                    strategy_response = await client.get("/api/quant/strategy")
            self.assertEqual(contracts_response.status_code, 200)
            self.assertEqual(contracts_response.json()["marker"], "custom-output")
            self.assertEqual(report_response.text, "custom report")
            self.assertEqual(render.call_args.args[0]["marker"], "custom-output")
            self.assertEqual(paper_response.status_code, 200)
            self.assertEqual(paper_response.json()["initial_capital"], 12_345)
            self.assertEqual(runtime_response.status_code, 200)
            self.assertEqual(runtime_response.json()["marker"], "custom-runtime")
            self.assertEqual(strategy_response.status_code, 200)
            self.assertNotIn("binance_api_key", strategy_response.json()["configuration"])
            self.assertNotIn("binance_secret_key", strategy_response.json()["configuration"])


if __name__ == "__main__":
    unittest.main()
