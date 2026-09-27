"""Closed-candle stop proposals and Freqtrade callback boundaries."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from freqtrade.enums import ExitCheckTuple, ExitType
from freqtrade.optimize.backtesting import Backtesting

from app.quant.stop_profiles import PROFILES, closed_stop, initial_stop
from research.strategies.StopComparisonStrategies import (
    D55ClosedTrail, D55Fixed, D55Legacy, D55Structure,
)
from ComparisonStrategies import Donchian55


UTC = timezone.utc
PAIR = "ZEC/USDT:USDT"


class FakeTrade:
    def __init__(self, *, entry=100, opened=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
                 state=None):
        self.open_rate = entry
        self.open_date_utc = opened
        self.data = dict(state or {})

    def get_custom_data(self, key):
        return self.data.get(key)

    def set_custom_data(self, key, value):
        self.data[key] = value


def callback_strategy(cls, *, date="2026-01-01 00:00:00+00:00", atr=2,
                      high=110, low=90):
    strategy = object.__new__(cls)
    frame = pd.DataFrame([{"date_4h": pd.Timestamp(date), "atr_4h": atr,
                           "high_4h": high, "low10_4h": low}])
    strategy.dp = SimpleNamespace(get_analyzed_dataframe=lambda *_: (frame, None))
    return strategy, frame


def evaluate(strategy, trade, when, rate, *, after_fill=False):
    return strategy.custom_stoploss(PAIR, trade, when, rate, 0, after_fill)


class PureStopTests(unittest.TestCase):
    def test_initial_atr_stop_and_structure_are_capped_by_max_loss(self):
        self.assertEqual(initial_stop(PROFILES["fixed"], 100, 2, .25), 93)
        self.assertEqual(initial_stop(PROFILES["fixed"], 100, 20, .25), 75)
        self.assertEqual(initial_stop(PROFILES["structure"], 100, 2, .25, 90), 89)
        self.assertEqual(initial_stop(PROFILES["structure"], 100, 2, .25, 60), 75)
        with self.assertRaisesRegex(ValueError, "Structure"):
            initial_stop(PROFILES["structure"], 100, 2, .25, 105)

    def test_closed_trail_activates_only_after_entry_plus_two_initial_atr(self):
        profile = PROFILES["closed_trail"]
        pending = closed_stop(profile, entry=100, entry_atr=2, initial=93,
                              previous_stop=93, closed_high=103.99, current_atr=1)
        active = closed_stop(profile, entry=100, entry_atr=2, initial=93,
                             previous_stop=93, closed_high=104, current_atr=1)
        self.assertEqual(pending, 93)
        self.assertEqual(active, 100)

    def test_closed_stop_never_widens_after_atr_or_structure_changes(self):
        self.assertEqual(closed_stop(PROFILES["closed_trail"], entry=100, entry_atr=2,
                                     initial=93, previous_stop=110, closed_high=115,
                                     current_atr=10), 110)
        self.assertEqual(closed_stop(PROFILES["structure"], entry=100, entry_atr=2,
                                     initial=89, previous_stop=95, closed_high=105,
                                     current_atr=10, structure_low=80), 95)


class CallbackTests(unittest.TestCase):
    def test_unclosed_informative_candle_is_rejected(self):
        strategy, _ = callback_strategy(D55Fixed, date="2026-01-01 08:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "unclosed strategy candle"):
            evaluate(strategy, FakeTrade(), datetime(2026, 1, 1, 10, tzinfo=UTC), 100)

    def test_fixed_atr_survives_later_volatility_and_restored_trade_state(self):
        strategy, frame = callback_strategy(D55Fixed)
        trade = FakeTrade()
        evaluate(strategy, trade, datetime(2026, 1, 1, 4, tzinfo=UTC), 100,
                 after_fill=True)
        saved = trade.get_custom_data("v6_stop_fixed").copy()
        self.assertEqual(saved["atr"], 2)
        self.assertEqual(saved["initial"], 93)
        frame.loc[0, "date_4h"] = pd.Timestamp("2026-01-01 04:00:00+00:00")
        frame.loc[0, "atr_4h"] = 20
        restored = FakeTrade(state={"v6_stop_fixed": saved})
        ratio = evaluate(strategy, restored, datetime(2026, 1, 1, 8, tzinfo=UTC), 120)
        self.assertAlmostEqual(120 * (1 - ratio), 93)
        self.assertEqual(restored.get_custom_data("v6_stop_fixed")["atr"], 2)

    def test_closed_trail_ignores_same_signal_period_five_minute_highs(self):
        strategy, _ = callback_strategy(D55ClosedTrail,
                                        date="2026-01-01 04:00:00+00:00", high=120)
        trade = FakeTrade(state={"v6_stop_closed_trail": {
            "initial": 93, "atr": 2, "high": 100, "last_date": None, "stop": 93,
        }})
        first = evaluate(strategy, trade, datetime(2026, 1, 1, 8, tzinfo=UTC), 125)
        second = evaluate(strategy, trade, datetime(2026, 1, 1, 8, 5, tzinfo=UTC), 130)
        self.assertAlmostEqual(125 * (1 - first), 112)
        self.assertAlmostEqual(130 * (1 - second), 112)
        self.assertEqual(trade.get_custom_data("v6_stop_closed_trail")["high"], 120)

    def test_structure_uses_closed_low_and_does_not_recompute_with_same_date(self):
        strategy, frame = callback_strategy(D55Structure,
                                            date="2026-01-01 04:00:00+00:00", low=96)
        trade = FakeTrade(state={"v6_stop_structure": {
            "initial": 89, "atr": 2, "high": 100, "last_date": None, "stop": 89,
        }})
        first = evaluate(strategy, trade, datetime(2026, 1, 1, 8, tzinfo=UTC), 110)
        frame.loc[0, "low10_4h"] = 106  # Same date must not revise the stop.
        second = evaluate(strategy, trade, datetime(2026, 1, 1, 8, 5, tzinfo=UTC), 110)
        self.assertAlmostEqual(110 * (1 - first), 95)
        self.assertAlmostEqual(110 * (1 - second), 95)

    def test_legacy_delegates_unchanged_to_original_strategy(self):
        strategy = object.__new__(D55Legacy)
        trade = FakeTrade()
        when = datetime(2026, 1, 1, 4, tzinfo=UTC)
        with patch.object(Donchian55, "custom_stoploss", return_value=.123) as original:
            self.assertEqual(evaluate(strategy, trade, when, 100), .123)
        original.assert_called_once_with(PAIR, trade, when, 100, 0, False)

    def test_gap_below_new_closed_trail_has_immediate_exit(self):
        strategy, _ = callback_strategy(D55ClosedTrail,
                                        date="2026-01-01 04:00:00+00:00", high=120)
        trade = FakeTrade(state={"v6_stop_closed_trail": {
            "initial": 93, "atr": 2, "high": 100, "last_date": None, "stop": 93,
        }})
        when = datetime(2026, 1, 1, 8, tzinfo=UTC)
        evaluate(strategy, trade, when, 100)
        self.assertEqual(trade.get_custom_data("v6_stop_closed_trail")["stop"], 112)
        self.assertTrue(strategy.custom_exit(PAIR, trade, when, 100, 0))

    def test_gap_rebounds_above_stop_but_custom_exit_fills_at_open(self):
        strategy, _ = callback_strategy(D55ClosedTrail,
                                        date="2026-01-01 04:00:00+00:00", high=120)
        trade = FakeTrade(state={"v6_stop_closed_trail": {
            "initial": 93, "atr": 2, "high": 100, "last_date": None, "stop": 93,
        }})
        when = datetime(2026, 1, 1, 8, tzinfo=UTC)
        # The current 5m bar opens below the new 112 stop, then rebounds above it.
        # Normal stop handling could optimistically fill at 112; custom_exit must
        # take the observed opening price of 100 instead.
        candle = (pd.Timestamp(when), 100, 115, 95, 110)
        self.assertGreater(evaluate(strategy, trade, when, candle[2]), 0)
        self.assertEqual(trade.get_custom_data("v6_stop_closed_trail")["stop"], 112)
        reason = strategy.custom_exit(PAIR, trade, when, candle[1], 0)
        self.assertEqual(reason, "closed_bar_gap_stop")
        fill = Backtesting._get_close_rate(object.__new__(Backtesting), candle, trade,
                                           when, ExitCheckTuple(ExitType.CUSTOM_EXIT, reason), 0)
        self.assertEqual(fill, candle[1])


if __name__ == "__main__":
    unittest.main()
