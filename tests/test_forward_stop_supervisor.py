"""Offline ledger and snapshot checks for the three-account forward observer."""

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import forward_stop_study as study


PARENT = "M4Structure"
PAIR = "ZEC/USDT:USDT"
COLUMNS = ("id", "pair", "is_open", "open_date", "close_date", "open_rate",
           "close_rate", "amount", "stake_amount", "leverage", "stop_loss",
           "initial_stop_loss", "close_profit_abs", "funding_fees", "fee_open",
           "fee_close", "enter_tag", "exit_reason")


class ForwardObserverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "reports/quant_v6/forward"
        self.directory = self.out / PARENT
        self.directory.mkdir(parents=True)
        (self.out / "protocol.json").write_text(json.dumps({"started_ms": 1_700_000_000_000}))
        for attr, value in (("ROOT", self.root), ("OUT", self.out), ("PARENTS", [PARENT])):
            changed = patch.object(study, attr, value)
            changed.start()
            self.addCleanup(changed.stop)
        self.owned = patch.object(study, "owned_pid", return_value=True)
        self.owned.start()
        self.addCleanup(self.owned.stop)
        self.now = int(time.time() * 1000)
        self.write("heartbeat.json", {"at_ms": self.now, "candle_close_ms": {
            "BTCUSDT": self.now - 60_000,
            "ETHUSDT": self.now - 60_000,
            "ZECUSDT": self.now - 60_000,
        }})

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def trades(self, rows):
        with closing(sqlite3.connect(self.directory / "trades.sqlite")) as db:
            db.execute("CREATE TABLE trades (" + ",".join(
                f"{column} {'TEXT' if column in ('pair', 'open_date', 'close_date', 'enter_tag', 'exit_reason') else 'REAL'}"
                for column in COLUMNS) + ")")
            db.executemany("INSERT INTO trades VALUES (" + ",".join("?" for _ in COLUMNS) + ")",
                           [[row.get(column) for column in COLUMNS] for row in rows])
            db.commit()

    def position(self, trade_id, *, is_open=True, profit=None):
        return {"id": trade_id, "pair": PAIR, "is_open": int(is_open),
                "open_date": "2026-09-25 00:00:00", "close_date": None if is_open else "2026-09-25 01:00:00",
                "open_rate": 100, "close_rate": None if is_open else 110,
                "amount": 2, "stake_amount": 200, "leverage": 1,
                "stop_loss": 90, "initial_stop_loss": 90,
                "close_profit_abs": profit, "funding_fees": -1.5 if is_open else 0,
                "fee_open": .001, "fee_close": .002,
                "enter_tag": "fixture", "exit_reason": None if is_open else "exit_signal"}

    def observe(self, marks=None):
        return study.snapshot({PARENT: 12345}, marks or {}, self.now)["accounts"][0]

    def test_open_position_with_stale_server_mark_is_degraded_and_unvalued(self):
        self.trades([self.position(1)])
        account = self.observe({"ZECUSDT": {"price": 110, "time": self.now - 181_000}})
        self.assertEqual(account["state"], "market_data_degraded")
        self.assertTrue(account["data_fresh"])
        self.assertIsNone(account["estimated_liquidation_equity"])
        self.assertEqual(account["open_positions"], 1)
        self.assertEqual(account["closed_trades"], 0)

    def test_closed_profit_funding_and_both_open_position_fees_value_equity(self):
        self.trades([self.position(1, is_open=False, profit=150), self.position(2)])
        account = self.observe({"ZECUSDT": {"price": 110, "time": self.now - 10_000}})
        self.assertEqual(account["state"], "observing")
        self.assertEqual(account["closed_trades"], 1)
        self.assertEqual(account["closed_profit_usdt"], 150)
        # 10000 + realized 150 + 2*(110-100) - funding 1.5
        # less 2*(100*0.001 + 110*0.002) liquidation fee estimate.
        self.assertAlmostEqual(account["estimated_liquidation_equity"], 10167.86)

    def test_market_failure_is_visible_even_without_filled_trades(self):
        self.write("market_events.json", {"failed_entry_attempts": 3,
                                          "last_error_ms": self.now - 20_000,
                                          "reason": "simulated orderbook timeout"})
        account = self.observe()
        self.assertEqual(account["state"], "market_data_degraded")
        self.assertEqual(account["market_events"]["failed_entry_attempts"], 3)
        self.assertEqual(account["open_positions"], 0)
        self.assertEqual(account["closed_trades"], 0)
        self.assertEqual(account["estimated_liquidation_equity"], 10000)

    def test_closed_count_is_all_history_and_old_open_positions_are_retained(self):
        rows = [self.position(1), self.position(2)]
        rows += [self.position(i, is_open=False, profit=1) for i in range(3, 254)]
        self.trades(rows)
        ledger_rows, realized, closed = study.ledger(PARENT)
        self.assertEqual(closed, 251)
        self.assertEqual(realized, 251)
        self.assertEqual({row["id"] for row in ledger_rows if row["is_open"]}, {1, 2})
        self.assertLessEqual(len(ledger_rows), 202)
        account = self.observe({"ZECUSDT": {"price": 100, "time": self.now - 10_000}})
        self.assertEqual(account["closed_trades"], 251)
        self.assertEqual(account["open_positions"], 2)
        self.assertEqual({row["id"] for row in account["recent_trades"] if row["is_open"]}, {1, 2})


if __name__ == "__main__":
    unittest.main()
