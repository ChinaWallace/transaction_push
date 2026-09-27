"""Causal and cash-flow checks for the offline cross-margin replay."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import replay_cross_margin as replay


START = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
END = START + 24 * 3_600_000
FOUR_HOURS = 4 * 3_600_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "ZECUSDT")
DATES = ("2026-01-01", "2026-01-02")
TIERS = {symbol: [dict(minNotional=0, maxNotional=1_000_000,
                       maintenanceMarginRate=.01, info={"cum": 0})]
         for symbol in SYMBOLS}


def synthetic_seed(quantity=20, *, signal_at=None, low_at=None,
                   low_value=0, execution_at_seed=100):
    opened, closed = START + FOUR_HOURS, END - replay.STEP
    move = START + 8 * 3_600_000
    trades, data = [], {}
    for symbol in SYMBOLS:
        funding = quantity * 120 * .001 if symbol == "BTCUSDT" else 0
        trades.append({"pair": symbol.removesuffix("USDT") + "/USDT:USDT",
                       "open_timestamp": opened, "close_timestamp": closed,
                       "open_rate": 100, "close_rate": 120, "amount": quantity,
                       "profit_abs": quantity * 20 - quantity * 100 * .001
                                     - quantity * 120 * .001 - funding,
                       "orders": [{"ft_is_entry": True}, {"ft_is_entry": False}]})
        prices, marks = {}, {}
        for at in range(START, END, replay.STEP):
            mark = 100 if at < move else 120
            prices[at] = execution_at_seed if at == opened else mark
            low = low_value if at == low_at else mark
            marks[at] = (mark, mark, low)
        data[symbol] = {"price": prices, "marks": marks,
                        "signals": {signal_at} if symbol == "BTCUSDT" and signal_at else set(),
                        "funding": {move: (.001, 120)} if symbol == "BTCUSDT" else {}}
    return trades, data


class CrossMarginReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for field, value in (("ROOT", self.root),
                             ("OUT", self.root / "reports/quant_v10")):
            changed = patch.object(replay, field, value)
            changed.start()
            self.addCleanup(changed.stop)

    def read(self, arm, filename, window="fixture"):
        return json.loads((replay.OUT / "runs" / window / arm / filename).read_text())

    def test_same_seed_baseline_cashflow_reconciles_funding_and_fees(self):
        trades, data = synthetic_seed()
        row = replay.run_arm("CrossNotional70", "fixture", trades, data, TIERS,
                             .001, DATES)
        metrics = row["mark_metrics"]
        self.assertAlmostEqual(metrics["fee_cost_usdt"], 13.2)
        self.assertAlmostEqual(metrics["funding_net_income_usdt"], -2.4)
        self.assertAlmostEqual(metrics["final_equity"], 11184.4)
        self.assertAlmostEqual(metrics["cashflow_error_usdt"], 0)
        self.assertAlmostEqual(metrics["freqtrade_baseline_difference_usdt"], 0)
        self.assertTrue(metrics["risk_model_passed"])
        events = self.read("CrossNotional70", "events.json")
        self.assertEqual(sum(e["side"] == "funding" for e in events), 1)

    def test_reduction_fills_at_known_open_and_ignores_current_bar_low(self):
        trades, data = synthetic_seed(quantity=30, execution_at_seed=98)
        row = replay.run_arm("CrossFlex", "fixture", trades, data, TIERS,
                             .001, DATES)
        self.assertGreaterEqual(row["mark_metrics"]["risk_reduction_rounds"], 1)
        orders = self.read("CrossFlex", "orders.json")
        reductions = [o for o in orders if o["reason"] == "cross_reduce_to_cash_floor"]
        self.assertEqual(len(reductions), 3)
        self.assertEqual({o["timestamp"] for o in reductions}, {START + FOUR_HOURS})
        self.assertEqual({o["price"] for o in reductions}, {98})
        snapshots = self.read("CrossFlex", "risk_snapshots.json")
        after = next(s for s in snapshots if s["reason"] == "after_reduce")
        self.assertAlmostEqual(after["effective_leverage"], .9)
        self.assertGreater(after["all_zero_cash_floor"], 0)

    def test_revising_only_current_future_low_changes_risk_not_prior_fills(self):
        trades, clean = synthetic_seed(quantity=30)
        good = replay.run_arm("CrossMargin70", "clean", trades, clean, TIERS,
                              .001, DATES)
        trades, stressed = synthetic_seed(quantity=30,
                                          low_at=START + 8 * 3_600_000,
                                          low_value=0)
        bad = replay.run_arm("CrossMargin70", "stressed", trades, stressed,
                             TIERS, .001, DATES)
        self.assertTrue(good["mark_metrics"]["risk_model_passed"])
        self.assertFalse(bad["mark_metrics"]["risk_model_passed"])
        self.assertEqual(bad["mark_metrics"]["first_risk_breach"]["stage"],
                         "joint_intrabar_lows_bound")
        self.assertEqual(self.read("CrossMargin70", "orders.json", "clean"),
                         self.read("CrossMargin70", "orders.json", "stressed"))

    def test_breakout_only_usable_after_completed_four_hour_candle(self):
        bars = [[START + i * FOUR_HOURS, 0, 100, 0, 90] for i in range(56)]
        bars[55] = [START + 55 * FOUR_HOURS, 0, 131, 0, 130]
        signal = START + 56 * FOUR_HOURS
        original = replay.breakout_times(bars)
        self.assertIn(signal, original)
        self.assertNotIn(START + 55 * FOUR_HOURS, original)
        extended = bars + [[signal, 0, 500, 0, 10]]
        self.assertEqual({t for t in original if t <= signal},
                         {t for t in replay.breakout_times(extended) if t <= signal})

    def test_profit_add_uses_unrealized_gain_only_as_budget_and_caps_postfill(self):
        trades, data = synthetic_seed(signal_at=START + 8 * 3_600_000)
        row = replay.run_arm("CrossFlexAdd", "fixture", trades, data, TIERS,
                             .001, DATES)
        metrics = row["mark_metrics"]
        self.assertEqual(metrics["add_fills"], 1)
        events = self.read("CrossFlexAdd", "events.json")
        added = next(e for e in events if e.get("reason") == "cross_profit_breakout_add")
        self.assertEqual(added["timestamp"], START + 8 * 3_600_000)
        self.assertEqual(added["symbol"], "BTCUSDT")
        initial_fees = sum(e["fee"] for e in events if e.get("reason") == "same_hold_seed")
        funding = sum(e["payment"] for e in events if e["side"] == "funding")
        snapshot = next(s for s in self.read("CrossFlexAdd", "risk_snapshots.json")
                        if s["timestamp"] == added["timestamp"]
                        and s["reason"] == "known_open_after_actions")
        self.assertAlmostEqual(snapshot["wallet"],
                               replay.CAPITAL - initial_fees - funding - added["fee"])
        self.assertLessEqual(snapshot["gross"] / snapshot["equity"], 1.4 + 1e-9)
        self.assertAlmostEqual(metrics["cashflow_error_usdt"], 0)


if __name__ == "__main__":
    unittest.main()
