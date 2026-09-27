"""v7 holding benchmarks and trend retention ablations, offline research only.

Every three-coin variant keeps the parent's entries and 70%/3 capital limits.
ZEC-only benchmarks are explicitly labelled concentration controls.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ComparisonStrategies import BuyHold1x, Donchian55, ADXBreakout1h, MTFFourHourExit


class HoldEqual(BuyHold1x):
    """Three equal initial allocations; the frozen v5 buy-and-hold benchmark."""


class HoldZecSlice(BuyHold1x):
    """Only ZEC's 23.33% slice invested; other allocations remain cash."""


class HoldZec70(BuyHold1x):
    """70% ZEC concentration benchmark, not the current per-coin policy."""
    def budget_per_pair(self):
        return self.wallets.get_total_stake_amount()


class RetainTrend:
    use_custom_stoploss = False
    trailing_stop = False
    stoploss = -.99
    holding_exit = "terminal_only"

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        if self.holding_exit == "slow_4h":
            # 48 closed 5m bars = one 4h bar. Two completed 4h closes below
            # their own EMA200, with no intrabar high or future information.
            below = dataframe.close_4h < dataframe.ema200_4h
            fresh = dataframe.date_4h != dataframe.date_4h.shift(1)
            two_closed = below & below.shift(48, fill_value=False)
            dataframe.loc[fresh & two_closed, ["exit_long", "exit_tag"]] = (1, "two_4h_below_ema200")
        return dataframe

    def custom_exit(self, **kwargs):
        return None


class M4HoldEntry(RetainTrend, MTFFourHourExit): pass
class A1HoldEntry(RetainTrend, ADXBreakout1h): pass
class D55HoldEntry(RetainTrend, Donchian55): pass

class M4SlowHold(RetainTrend, MTFFourHourExit): holding_exit = "slow_4h"
class A1SlowHold(RetainTrend, ADXBreakout1h): holding_exit = "slow_4h"
class D55SlowHold(RetainTrend, Donchian55): holding_exit = "slow_4h"
