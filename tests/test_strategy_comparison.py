"""Small accounting fixtures for the read-only strategy comparison report."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import analyze_strategy_comparison as comparison


START = comparison.timestamp("2026-01-01")
STEP = comparison.STEP


def order(at, amount, price, *, entry):
    return {"order_filled_timestamp": START + at * STEP, "amount": amount,
            "safe_price": price, "ft_is_entry": entry}


def trade(orders, *, funding=0, short=False, leverage=1):
    return {"pair": comparison.PAIRS[0], "orders": orders, "fee_open": 0.001,
            "fee_close": 0.001, "funding_fees": funding, "is_short": short,
            "leverage": leverage, "exit_reason": "exit_signal", "trade_duration": 20}


def market(*, missing=None, dip=False):
    result = {}
    for pair in comparison.PAIRS:
        marks = {START + slot * STEP: 100.0 for slot in range(25)}
        if dip and pair == comparison.PAIRS[0]:
            marks[START + STEP] = 70.0
            marks[START + 2 * STEP] = 110.0
            marks[START + 4 * STEP] = 120.0
        if missing == pair:
            del marks[START + STEP]
        result[pair] = (marks, [])
    return result


class FundingConventionTests(unittest.TestCase):
    def test_entry_and_exit_settlement_boundaries_are_inclusive(self):
        orders = [order(0, 2, 100, entry=True),
                  order(12, 2, 100, entry=False)]
        events = [(START, 1.5), (START + 12 * STEP, 2.0),
                  (START + 24 * STEP, 9.0)]
        expected = {START: -3.0, START + 12 * STEP: -4.0}
        self.assertEqual(comparison.funding_flows(orders, events, parity=True), expected)
        self.assertEqual(comparison.funding_flows(orders, events, parity=False), expected)

    def test_settlement_at_adjustment_has_engine_double_count_sensitivity(self):
        event = [(START + 12 * STEP, 1.0)]
        for orders in (
            [order(0, 1, 100, entry=True), order(12, 1, 100, entry=True),
             order(24, 2, 100, entry=False)],
            [order(0, 2, 100, entry=True), order(12, 1, 100, entry=False),
             order(24, 1, 100, entry=False)],
        ):
            with self.subTest(orders=orders):
                self.assertEqual(sum(comparison.funding_flows(orders, event, parity=True).values()), -3)
                self.assertEqual(sum(comparison.funding_flows(orders, event, parity=False).values()), -2)


class EquityReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.window = patch.object(comparison, "WINDOWS", {
            "full": ("2026-01-01", "2026-01-01 02:00:00"),
        })
        self.window.start()
        self.addCleanup(self.window.stop)

    def save(self, trades, profit):
        (self.run / "summary.json").write_text(json.dumps({"window": "full",
                                                        "profit_total_abs": profit}))
        (self.run / "trades.json").write_text(json.dumps(trades))

    def test_partial_sale_fees_marked_drawdown_and_final_profit_reconcile(self):
        # Buy 100 @100, sell 40 @110, then 60 @120. Both sale fees matter.
        orders = [order(0, 100, 100, entry=True),
                  order(2, 40, 110, entry=False),
                  order(4, 60, 120, entry=False)]
        expected_profit = 1578.4
        self.save([trade(orders)], expected_profit)
        result = comparison.analyze(self.run, market(dip=True))
        metrics = result["mark_metrics"]
        self.assertTrue(metrics["reconciled"])
        self.assertAlmostEqual(metrics["final_equity"], 11578.4)
        self.assertAlmostEqual(metrics["fee_cost_usdt"], 21.6)
        self.assertAlmostEqual(metrics["engine_profit_difference_usdt"], 0)
        self.assertAlmostEqual(metrics["sampled_mark_drawdown_pct"], 30.1)
        self.assertAlmostEqual(metrics["pnl_by_pair"][comparison.PAIRS[0]], expected_profit)
        self.assertEqual([item["side"] for item in json.loads((self.run / "orders.json").read_text())],
                         ["buy", "sell", "sell"])

    def test_hourly_dca_reports_engine_parity_and_single_event_difference(self):
        orders = [order(0, 1, 100, entry=True),
                  order(12, 1, 100, entry=True),
                  order(24, 2, 100, entry=False)]
        self.save([trade(orders, funding=-3)], -3.4)
        data = market()
        data[comparison.PAIRS[0]] = (data[comparison.PAIRS[0]][0],
                                      [(START + 12 * STEP, 1.0)])
        metrics = comparison.analyze(self.run, data)["mark_metrics"]
        self.assertTrue(metrics["reconciled"])
        self.assertAlmostEqual(metrics["funding_net_income_usdt"], -3)
        self.assertAlmostEqual(metrics["max_trade_funding_difference_usdt"], 0)
        self.assertAlmostEqual(metrics["final_equity"], 9996.6)
        self.assertAlmostEqual(metrics["engine_funding_vs_single_event_difference_usdt"], 1)
        self.assertAlmostEqual(metrics["economic_single_settlement_return_pct"], -0.024)

    def test_missing_mark_is_rejected_even_when_asset_is_unheld(self):
        self.save([], 0)
        with self.assertRaisesRegex(ValueError, "Missing mark price"):
            comparison.analyze(self.run, market(missing=comparison.PAIRS[1]))

    def test_short_and_leveraged_trades_are_rejected(self):
        orders = [order(0, 1, 100, entry=True), order(4, 1, 100, entry=False)]
        for changes in ({"short": True}, {"leverage": 2}):
            with self.subTest(changes=changes):
                self.save([trade(orders, **changes)], 0)
                with self.assertRaisesRegex(ValueError, "Only long 1x"):
                    comparison.analyze(self.run, market())


if __name__ == "__main__":
    unittest.main()
