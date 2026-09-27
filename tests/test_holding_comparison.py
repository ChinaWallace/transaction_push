"""Offline checks for the v7 hold and slow trend-exit controls."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
from freqtrade.strategy import merge_informative_pair

from research.strategies.HoldingComparisonStrategies import (
    A1HoldEntry, A1SlowHold, D55HoldEntry, D55SlowHold,
    HoldEqual, HoldZec70, HoldZecSlice, M4HoldEntry, M4SlowHold,
)


UTC = timezone.utc
HOLD_ENTRY = (M4HoldEntry, A1HoldEntry, D55HoldEntry)
SLOW_HOLD = (M4SlowHold, A1SlowHold, D55SlowHold)


def strategy(cls):
    return cls({"runmode": "backtest", "dry_run": True})


def merged_four_hour_frame():
    """The 08:00 candle joins the 11:55 5m row, which closes at 12:00."""
    base = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=193,
                                                freq="5min", tz="UTC"),
                         "close": [100.0] * 193})
    informative = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC"),
        "close": [90.0, 90.0, 90.0],
        # The first 4h close is above its own EMA; the next two are below
        # their respective EMA values.
        "ema200": [80.0, 100.0, 95.0],
    })
    return merge_informative_pair(base, informative, "5m", "4h", ffill=True)


class HoldingComparisonTests(unittest.TestCase):
    def test_research_classes_reject_live_and_remain_long_one_x(self):
        for cls in (HoldEqual, HoldZec70, *HOLD_ENTRY, *SLOW_HOLD):
            with self.subTest(strategy=cls.__name__):
                with self.assertRaisesRegex(ValueError, "offline research only"):
                    cls({"runmode": "live", "dry_run": True})
                with self.assertRaisesRegex(ValueError, "dry_run=true"):
                    cls({"runmode": "backtest", "dry_run": False})
                instance = strategy(cls)
                self.assertFalse(instance.can_short)
                self.assertEqual(instance.leverage(), 1)

    def test_hold_entry_disables_atr_and_time_or_signal_exits(self):
        frame = merged_four_hour_frame()
        for cls in HOLD_ENTRY:
            with self.subTest(strategy=cls.__name__):
                instance = strategy(cls)
                self.assertFalse(instance.use_custom_stoploss)
                self.assertFalse(instance.trailing_stop)
                self.assertEqual(instance.stoploss, -.99)
                result = instance.populate_exit_trend(frame.copy(), {})
                self.assertEqual(result.exit_long.sum(), 0)
                # An inherited timed exit would return a reason here.
                self.assertIsNone(instance.custom_exit(pair="ZEC/USDT:USDT", trade=None,
                    current_time=datetime(2026, 1, 2, tzinfo=UTC),
                    current_rate=100, current_profit=0))

    def test_slow_exit_requires_two_distinct_closed_four_hour_bars(self):
        frame = merged_four_hour_frame()
        for cls in SLOW_HOLD:
            with self.subTest(strategy=cls.__name__):
                result = strategy(cls).populate_exit_trend(frame.copy(), {})
                exits = result.loc[result.exit_long.eq(1), ["date", "date_4h", "exit_tag"]]
                self.assertEqual(len(exits), 1)
                # Freqtrade's merge shifts by 4h-5m, then backtesting shifts
                # this signal one 5m row before it can execute at 12:00.
                self.assertEqual(exits.iloc[0]["date"], pd.Timestamp("2026-01-01 11:55:00+00:00"))
                self.assertEqual(exits.iloc[0]["date_4h"], pd.Timestamp("2026-01-01 08:00:00+00:00"))
                self.assertEqual(exits.iloc[0]["exit_tag"], "two_4h_below_ema200")
                # At 08:00 only one below-EMA 4h bar was closed. Repeated 5m
                # rows within it must not count as another confirmation.
                before = result[result.date < pd.Timestamp("2026-01-01 11:55:00+00:00")]
                self.assertEqual(before.exit_long.sum(), 0)

    def test_equal_budget_is_one_third_of_seventy_percent_zec70_is_concentrated(self):
        wallet = SimpleNamespace(get_total_stake_amount=lambda: 7000)
        for cls in (HoldEqual, HoldZecSlice, *HOLD_ENTRY, *SLOW_HOLD):
            with self.subTest(strategy=cls.__name__):
                instance = strategy(cls)
                instance.wallets = wallet
                self.assertAlmostEqual(instance.budget_per_pair(), 7000 / 3)
                stake = instance.custom_stake_amount("ZEC/USDT:USDT", datetime.now(UTC),
                    100, 7000, 10, 7000, 1, None, "long")
                self.assertAlmostEqual(stake, 7000 / 3)
                self.assertEqual(instance.custom_stake_amount("ZEC/USDT:USDT", datetime.now(UTC),
                    100, 7000, 10, 7000, 1, None, "short"), 0)
        concentrated = strategy(HoldZec70)
        concentrated.wallets = wallet
        self.assertEqual(concentrated.budget_per_pair(), 7000)
        self.assertEqual(concentrated.custom_stake_amount("ZEC/USDT:USDT", datetime.now(UTC),
            100, 7000, 10, 7000, 1, None, "long"), 7000)


if __name__ == "__main__":
    unittest.main()
