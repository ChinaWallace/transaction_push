"""Causal signal and cash-backed pyramiding checks for the offline v8 replay."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import replay_core_growth as replay
from app.quant.core_growth import growth_notional


START = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
END = START + 24 * 3_600_000
FOUR_HOURS = 4 * 3_600_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "ZECUSDT")


def four_hour_bar(index, *, high=100, close=90):
    return [START + index * FOUR_HOURS, 0, high, 0, close]


def synthetic_holds():
    opened = START + FOUR_HOURS
    closed = END - replay.STEP
    trades = []
    data = {}
    for symbol in SYMBOLS:
        funding_payment = 1.2 if symbol == "BTCUSDT" else 0
        trades.append({"pair": symbol.removesuffix("USDT") + "/USDT:USDT",
            "open_timestamp": opened, "close_timestamp": closed,
            "open_rate": 100, "close_rate": 120, "amount": 10,
            "stake_amount": 1000, "profit_abs": 200 - 1 - 1.2 - funding_payment,
            "orders": [{"ft_is_entry": True}, {"ft_is_entry": False}]})
        prices = {at: 100 if at < START + 8 * 3_600_000 else 120
                  for at in range(START, END, replay.STEP)}
        data[symbol] = {"price": prices,
            "marks": {at: (price, price) for at, price in prices.items()},
            "signals": {START + 8 * 3_600_000} if symbol == "BTCUSDT" else set(),
            "funding": {START + 8 * 3_600_000: (.001, 120)} if symbol == "BTCUSDT" else {}}
    return trades, data


class CoreGrowthTimingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for field, value in (("ROOT", self.root), ("OUT", self.root / "reports/quant_v8")):
            changed = patch.object(replay, field, value)
            changed.start()
            self.addCleanup(changed.stop)

    def test_breakout_becomes_usable_only_after_four_hour_close_and_is_causal(self):
        rows = [four_hour_bar(i) for i in range(56)]
        rows[55] = four_hour_bar(55, high=131, close=130)
        signal_at = START + 56 * FOUR_HOURS
        original = replay.breakout_times(rows)
        self.assertIn(signal_at, original)
        self.assertNotIn(START + 55 * FOUR_HOURS, original)
        changed_future = rows + [four_hour_bar(56, high=500, close=10),
                                 four_hour_bar(57, high=50, close=500)]
        altered = replay.breakout_times(changed_future)
        self.assertEqual({at for at in original if at <= signal_at},
                         {at for at in altered if at <= signal_at})

    def test_cashflows_rebuild_closed_equity_and_funding_without_profit_credit(self):
        trades, data = synthetic_holds()
        row = replay.run_arm("DriftHold", "fixture", trades, data, .001,
                             ("2026-01-01", "2026-01-02"))
        metrics = row["mark_metrics"]
        self.assertAlmostEqual(metrics["final_equity"], 10592.2)
        self.assertAlmostEqual(metrics["fee_cost_usdt"], 6.6)
        self.assertAlmostEqual(metrics["funding_net_income_usdt"], -1.2)
        self.assertAlmostEqual(metrics["cashflow_error_usdt"], 0)
        self.assertAlmostEqual(metrics["freqtrade_baseline_difference_usdt"], 0)
        events = json.loads((replay.OUT / "runs/fixture/DriftHold/events.json").read_text())
        cashflow = sum((-1 if e["side"] == "buy" else 1) * e["quantity"] * e["price"] - e["fee"]
                       if e["side"] != "funding" else -e["payment"] for e in events)
        self.assertAlmostEqual(replay.CAPITAL + cashflow, metrics["final_equity"])
        self.assertEqual({e["side"] for e in events}, {"buy", "sell", "funding"})

    def test_profitable_signal_can_spend_only_free_cash_and_keeps_reserve(self):
        # A large paper gain cannot fund an order if no collateral remains.
        self.assertEqual(growth_notional(initial_quantity=10, initial_price=100,
            current_price=200, added_cost=0, last_add_price=100,
            profit_fraction=1, free_collateral=1000, equity=11000,
            reserve_cash=1000, breakout=True), 0)
        trades, data = synthetic_holds()
        hold = replay.run_arm("DriftHold", "fixture", trades, data, .001,
                              ("2026-01-01", "2026-01-02"))["mark_metrics"]
        add = replay.run_arm("ProfitAdd100", "fixture", trades, data, .001,
                             ("2026-01-01", "2026-01-02"))["mark_metrics"]
        self.assertEqual(add["add_fills"], 1)
        self.assertGreater(add["added_notional_including_fees_usdt"], 100)
        self.assertLessEqual(add["added_notional_including_fees_usdt"], 200)
        self.assertGreaterEqual(add["min_free_collateral_usdt"], 1000)
        self.assertLess(add["min_free_collateral_usdt"], hold["min_free_collateral_usdt"])
        # An add at 120 that is also closed at 120 produces only extra fees;
        # unrealized seed profit is permission, not spendable minted cash.
        self.assertLess(add["final_equity"], hold["final_equity"])
        self.assertGreater(add["final_equity"], hold["final_equity"] - 1)
        self.assertAlmostEqual(add["cashflow_error_usdt"], 0)


if __name__ == "__main__":
    unittest.main()
