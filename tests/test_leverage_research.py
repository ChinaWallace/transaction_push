"""Offline 2x study checks: margin budgets and unlevered cash-flow identity."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import leverage_accounting as accounting
from research.strategies.LeverageComparisonStrategies import (
    D55Margin2x, D55Notional2x, HoldMargin2x, HoldNotional2x,
)


START = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
PAIR = "BTC/USDT:USDT"


def load_runner_without_runtime_settings():
    """Load runner functions without importing the credential-aware config module."""
    compatibility = types.ModuleType("run_strategy_comparison")
    compatibility.config = lambda *_: None
    compatibility.load_result = lambda *_: None
    compatibility.write = lambda path, value: (
        path.parent.mkdir(parents=True, exist_ok=True),
        path.write_text(json.dumps(value)),
    )
    provenance = types.ModuleType("stop_provenance")
    provenance.verify_seal = lambda **_: None
    provenance.verify_hashes = lambda *_: None
    provenance.sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    provenance.economic_config = lambda value: value
    provenance.engine_version = lambda: "2026.8"
    path = Path(__file__).resolve().parents[1] / "scripts/run_leverage_comparison.py"
    spec = importlib.util.spec_from_file_location("isolated_leverage_runner", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"run_strategy_comparison": compatibility,
                                  "stop_provenance": provenance}):
        spec.loader.exec_module(module)
    return module


class LeverageResearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_two_x_strategy_still_refuses_live_and_is_long_only(self):
        for cls in (HoldMargin2x, HoldNotional2x, D55Margin2x, D55Notional2x):
            with self.subTest(strategy=cls.__name__):
                with self.assertRaisesRegex(ValueError, "offline research only"):
                    cls({"runmode": "live", "dry_run": True})
                strategy = cls({"runmode": "backtest", "dry_run": True})
                self.assertFalse(strategy.can_short)
                self.assertEqual(strategy.leverage(), 2)
                self.assertFalse(strategy.use_custom_stoploss)

    def test_runner_selects_seventy_percent_margin_or_notional_budget(self):
        class StopBeforeProcess(Exception):
            pass

        root = self.root
        out = root / "reports/quant_v9"
        manifest = root / "reports/quant_v5/freqtrade_data/manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({}))

        def base_config(_strategy, _directory, fee):
            return {"fee": fee, "tradable_balance_ratio": .7,
                    "max_open_trades": 3, "stake_amount": "unlimited",
                    "exchange": {"ccxt_config": {}, "ccxt_async_config": {}}}

        protocol = {"sources": {}, "engine_version": "2026.8", "tier_sha256": "fixture"}
        runner = load_runner_without_runtime_settings()
        with patch.object(runner, "ROOT", root), patch.object(runner, "OUT", out), \
             patch.object(runner, "config", side_effect=base_config), \
             patch.object(runner.subprocess, "run", side_effect=StopBeforeProcess):
            for name, ratio in (("HoldMargin2x", .7), ("HoldNotional2x", .35),
                                ("D55Margin2x", .7), ("D55Notional2x", .35)):
                with self.subTest(strategy=name), self.assertRaises(StopBeforeProcess):
                    runner.run(name, "full", .001, protocol)
                saved = json.loads((out / "runs/full" / name / "config.json").read_text())
                self.assertEqual(saved["tradable_balance_ratio"], ratio)
                self.assertEqual(saved["max_open_trades"], 3)
                # At 2x, stake is margin; available 7000/3500 USDT funds
                # approximately 14000/7000 USDT notional respectively.
                self.assertEqual(10000 * ratio * 2, 14000 if ratio == .7 else 7000)

    def test_two_x_mark_to_market_uses_contract_quantity_once(self):
        run = self.root / "run"
        run.mkdir()
        window = {"full": ("2026-01-01", "2026-01-01 02:00:00")}
        (run / "summary.json").write_text(json.dumps({"window": "full", "profit_total_abs": 18.58}))
        orders = [
            {"order_filled_timestamp": START, "amount": 2, "safe_price": 100,
             "ft_is_entry": True},
            {"order_filled_timestamp": START + 3_600_000, "amount": 2, "safe_price": 110,
             "ft_is_entry": False},
        ]
        trade = {"pair": PAIR, "is_short": False, "leverage": 2,
                 "stake_amount": 100, "orders": orders,
                 "fee_open": .001, "fee_close": .001, "funding_fees": -1,
                 "exit_reason": "exit_signal", "trade_duration": 60}
        (run / "trades.json").write_text(json.dumps([trade]))
        marks = {START + index * accounting.STEP: 100.0 for index in range(25)}
        marks[START + 6 * accounting.STEP] = 105
        marks[START + 12 * accounting.STEP] = 110
        data = {pair: (marks.copy(), [(START + 3_600_000, .5)] if pair == PAIR else [])
                for pair in accounting.PAIRS}
        with patch.object(accounting, "WINDOWS", window):
            metrics = accounting.analyze(run, data)["mark_metrics"]
        self.assertTrue(metrics["reconciled"])
        self.assertAlmostEqual(metrics["final_equity"], 10018.58)
        self.assertAlmostEqual(metrics["fee_cost_usdt"], .42)
        self.assertAlmostEqual(metrics["funding_net_income_usdt"], -1)
        self.assertAlmostEqual(metrics["engine_profit_difference_usdt"], 0)
        curve = pd.read_feather(run / "equity_5m.feather")
        # 2 contracts * $5 rise = $10, not $20 after multiplying 2x again.
        self.assertAlmostEqual(curve.loc[curve.timestamp.eq(START + 6 * accounting.STEP),
                                         "equity"].iloc[0], 10009.8)


if __name__ == "__main__":
    unittest.main()
