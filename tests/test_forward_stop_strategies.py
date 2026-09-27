"""Offline contract tests for the isolated Freqtrade forward-only wrappers."""

import inspect
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from freqtrade.enums import RunMode


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research/strategies"))
from ComparisonStrategies import ComparisonBase, ResearchBudget  # noqa: E402
from ForwardStopStrategies import (  # noqa: E402
    ForwardA1Fixed, ForwardD55ClosedTrail, ForwardM4Structure,
)
from StopComparisonStrategies import StopAblation  # noqa: E402


CLASSES = (ForwardM4Structure, ForwardA1Fixed, ForwardD55ClosedTrail)
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "ZEC/USDT:USDT"]


class ForwardStopStrategyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.closed_at = datetime(2026, 9, 25, 4, 5, tzinfo=timezone.utc)

    def config(self, **changes):
        value = {
            "runmode": RunMode.DRY_RUN,
            "dry_run": True,
            "exchange": {"name": "binance", "key": "", "secret": "",
                         "pair_whitelist": PAIRS.copy()},
            "trading_mode": "futures",
            "max_open_trades": 3,
            "tradable_balance_ratio": .7,
            "fee": .001,
            "candle_type_def": "futures",
            "forward_study": {
                "output_dir": str(self.directory),
                "started_ms": int(self.closed_at.timestamp() * 1000),
            },
        }
        value.update(changes)
        return value

    def instance_with_candle(self, cls=ForwardM4Structure, *, close_at=None, start_ms=None):
        config = self.config()
        if start_ms is not None:
            config["forward_study"]["started_ms"] = start_ms
        instance = cls(config)
        candle_open = (close_at or self.closed_at) - timedelta(minutes=5)
        frame = pd.DataFrame([{"date": pd.Timestamp(candle_open)}])
        instance.dp = SimpleNamespace(get_analyzed_dataframe=Mock(return_value=(frame, None)))
        return instance

    def confirm(self, instance, at, side="long"):
        return instance.confirm_trade_entry(
            pair="ZEC/USDT:USDT", order_type="market", amount=1, rate=100,
            time_in_force="GTC", current_time=at, entry_tag="test", side=side,
        )

    def test_live_nondryrun_and_exchange_credentials_are_rejected(self):
        for cls in CLASSES:
            with self.subTest(strategy=cls.__name__, reason="live"):
                with self.assertRaises(ValueError):
                    cls(self.config(runmode=RunMode.LIVE))
            with self.subTest(strategy=cls.__name__, reason="not_dry_run"):
                with self.assertRaises(ValueError):
                    cls(self.config(dry_run=False))
            for secret_field in ("key", "secret", "password", "uid", "privateKey", "walletAddress"):
                with self.subTest(strategy=cls.__name__, credential=secret_field):
                    config = self.config()
                    config["exchange"][secret_field] = "nonempty-test-value"
                    with self.assertRaises(ValueError):
                        cls(config)

    def test_selected_signal_families_and_one_x_leverage_are_unchanged(self):
        expected = (
            (ForwardM4Structure, "mtf", "4h", "structure", "4h"),
            (ForwardA1Fixed, "adx", "hourly", "fixed", "1h"),
            (ForwardD55ClosedTrail, "donchian", "channel", "closed_trail", "4h"),
        )
        for cls, entry, exit_rule, stop, atr_frame in expected:
            with self.subTest(strategy=cls.__name__):
                instance = cls(self.config())
                self.assertFalse(instance.can_short)
                self.assertEqual(instance.timeframe, "5m")
                self.assertEqual((instance.entry_family, instance.exit_family,
                                  instance.stop_profile, instance.atr_frame),
                                 (entry, exit_rule, stop, atr_frame))
                self.assertEqual(instance.leverage(pair=PAIRS[0], current_time=self.closed_at,
                                                   current_rate=100, proposed_leverage=3,
                                                   max_leverage=3, entry_tag=None, side="long"), 1.0)

    def test_only_fresh_post_start_closed_candle_can_enter(self):
        earlier = self.instance_with_candle(start_ms=int(self.closed_at.timestamp() * 1000) + 1)
        stale = self.instance_with_candle()
        future = self.instance_with_candle()
        fresh = self.instance_with_candle()
        with patch.object(ResearchBudget, "confirm_trade_entry", return_value=True) as parent:
            self.assertFalse(self.confirm(earlier, self.closed_at + timedelta(seconds=10)))
            self.assertFalse(self.confirm(stale, self.closed_at + timedelta(seconds=91)))
            self.assertFalse(self.confirm(future, self.closed_at - timedelta(seconds=1)))
            self.assertFalse(self.confirm(fresh, self.closed_at + timedelta(seconds=10), side="short"))
            parent.assert_not_called()
            self.assertTrue(self.confirm(fresh, self.closed_at + timedelta(seconds=10)))
            parent.assert_called_once()

    def test_stoploss_exception_persists_fault_and_blocks_restart_entries(self):
        instance = self.instance_with_candle()
        with patch.object(StopAblation, "custom_stoploss", side_effect=RuntimeError("test callback failure")):
            with self.assertRaisesRegex(RuntimeError, "test callback failure"):
                instance.custom_stoploss(pair=PAIRS[2], trade=Mock(), current_time=self.closed_at,
                                         current_rate=100, current_profit=0, after_fill=False)
        fault = json.loads((self.directory / "callback_fault.json").read_text())
        self.assertEqual(fault["callback"], "custom_stoploss")
        self.assertTrue(fault["new_entries_blocked"])
        self.assertFalse(fault["observation_valid"])
        restarted = self.instance_with_candle()
        self.assertTrue(restarted.forward_fault)
        with patch.object(ResearchBudget, "confirm_trade_entry", return_value=True) as parent:
            self.assertFalse(self.confirm(restarted, self.closed_at + timedelta(seconds=10)))
            parent.assert_not_called()

    def test_engine_can_detect_after_fill_callback_signature(self):
        # StrategyResolver checks named arguments, not **kwargs, before it calls
        # the post-fill stop update in dry-run mode.
        for cls in CLASSES:
            with self.subTest(strategy=cls.__name__):
                self.assertIn("after_fill", inspect.getfullargspec(cls.custom_stoploss).args)

    def test_closed_bar_signal_is_recorded_before_entry_approval(self):
        instance = self.instance_with_candle()
        frame = pd.DataFrame([{
            "date": pd.Timestamp(self.closed_at - timedelta(minutes=5)),
            "close": 100.0, "enter_long": 1, "enter_tag": "mtf",
        }])
        with patch.object(ComparisonBase, "populate_entry_trend", return_value=frame), \
             patch.object(ResearchBudget, "confirm_trade_entry", return_value=True):
            result = instance.populate_entry_trend(frame, {"pair": PAIRS[2]})
            self.assertEqual(int(result.iloc[-1]["enter_long"]), 1)
            self.assertTrue(self.confirm(instance, self.closed_at + timedelta(seconds=10)))
        decisions = [json.loads(line) for line in
                     (self.directory / "decisions.jsonl").read_text().splitlines()]
        self.assertEqual([item["kind"] for item in decisions],
                         ["entry_signal", "entry_approved"])
        self.assertEqual([item["candle_close_ms"] for item in decisions],
                         [int(self.closed_at.timestamp() * 1000)] * 2)
        self.assertEqual(decisions[1]["rate"], 100)

    def test_entry_evidence_write_failure_rejects_new_position(self):
        instance = self.instance_with_candle()
        with patch.object(ResearchBudget, "confirm_trade_entry", return_value=True), \
             patch.object(instance, "_decision", side_effect=OSError("cannot write evidence")):
            self.assertFalse(self.confirm(instance, self.closed_at + timedelta(seconds=10)))
        self.assertTrue(instance.forward_fault)
        fault = json.loads((self.directory / "callback_fault.json").read_text())
        self.assertEqual(fault["callback"], "entry_approval_evidence")
        self.assertTrue(ForwardM4Structure(self.config()).forward_fault)

    def test_signal_evidence_write_failure_clears_entry_and_latches(self):
        instance = self.instance_with_candle()
        frame = pd.DataFrame([{
            "date": pd.Timestamp(self.closed_at - timedelta(minutes=5)),
            "close": 100.0, "enter_long": 1, "enter_tag": "mtf",
        }])
        with patch.object(ComparisonBase, "populate_entry_trend", return_value=frame), \
             patch.object(instance, "_decision", side_effect=OSError("cannot write signal")):
            result = instance.populate_entry_trend(frame, {"pair": PAIRS[2]})
        self.assertEqual(int(result.iloc[-1]["enter_long"]), 0)
        self.assertTrue(instance.forward_fault)
        self.assertEqual(json.loads((self.directory / "callback_fault.json").read_text())["callback"],
                         "entry_evidence")

    def test_heartbeat_failure_latches_and_blocks_new_entries(self):
        instance = self.instance_with_candle()
        with patch.object(instance, "_observe_loop", side_effect=OSError("heartbeat unavailable")):
            with self.assertRaisesRegex(OSError, "heartbeat unavailable"):
                instance.bot_loop_start(current_time=self.closed_at)
        self.assertTrue(instance.forward_fault)
        self.assertEqual(json.loads((self.directory / "callback_fault.json").read_text())["callback"],
                         "observation")
        with patch.object(ResearchBudget, "confirm_trade_entry", return_value=True) as parent:
            self.assertFalse(self.confirm(instance, self.closed_at + timedelta(seconds=10)))
            parent.assert_not_called()

    def test_exit_evidence_failure_does_not_trap_existing_virtual_position(self):
        instance = ForwardM4Structure(self.config())
        with patch.object(instance, "_decision", side_effect=OSError("cannot write exit")), \
             patch.object(ComparisonBase, "confirm_trade_exit", return_value=True) as parent:
            allowed = instance.confirm_trade_exit(
                pair=PAIRS[2], trade=SimpleNamespace(id=3), order_type="market",
                amount=1, rate=98, time_in_force="GTC", exit_reason="stop_loss",
                current_time=self.closed_at,
            )
        self.assertTrue(allowed)
        parent.assert_called_once()
        self.assertTrue(instance.forward_fault)


if __name__ == "__main__":
    unittest.main()
