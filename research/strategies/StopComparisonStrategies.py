"""v6 fixed stop-policy ablation. Entries and signal exits stay in frozen v5.

Legacy and Wide retain the old intrabar engine assumptions for a distance-only
control. Fixed, ClosedTrail and Structure use only completed strategy candles.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from freqtrade.strategy import stoploss_from_absolute

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.quant.stop_profiles import PROFILES, closed_stop, initial_stop
from ComparisonStrategies import Donchian55, EMA4h, ADXBreakout1h, MTFFourHourExit


class StopAblation:
    stop_profile = "legacy"

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if self.stop_profile in PROFILES:
            state = trade.get_custom_data("v6_stop_" + self.stop_profile)
            # custom_stoploss is evaluated before custom_exit. If the new closed-
            # bar stop is above this opening price, use this actual open rather
            # than an unattainable stop fill or a zero-distance ignored update.
            if state is not None and current_rate <= state["stop"]:
                return "closed_bar_gap_stop"
        return super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill, **kwargs):
        if self.stop_profile == "legacy":
            return super().custom_stoploss(pair, trade, current_time, current_rate,
                                          current_profit, after_fill, **kwargs)
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if frame.empty:
            return None
        row = frame.iloc[-1]
        atr = float(row["atr_" + self.atr_frame])
        if not np.isfinite(atr) or atr <= 0:
            return None
        if self.stop_profile == "wide":
            return stoploss_from_absolute(current_rate - (4 if after_fill else 5) * atr,
                                          current_rate, is_short=False, leverage=1)
        profile = PROFILES[self.stop_profile]
        date = pd.Timestamp(row["date_" + self.atr_frame])
        delta = pd.Timedelta(hours=4 if self.atr_frame == "4h" else 1)
        if date + delta > pd.Timestamp(current_time):
            raise ValueError("An unclosed strategy candle reached stop evaluation")
        key = "v6_stop_" + self.stop_profile
        state = trade.get_custom_data(key)
        if state is None:
            # First fill fixes ATR and initial protective price for this trade.
            low = float(row["low10_" + self.atr_frame])
            # A gapped entry below the past range already has an exit signal;
            # retain a finite ATR guard if that structural level is above entry.
            if self.stop_profile == "structure" and low >= trade.open_rate:
                low = trade.open_rate - atr
            stop = initial_stop(profile, trade.open_rate, atr, abs(self.stoploss), low)
            state = {"initial": stop, "atr": atr, "high": trade.open_rate,
                     "last_date": None, "stop": stop}
        date_ms = int(date.timestamp() * 1000)
        if state["last_date"] != date_ms and date >= pd.Timestamp(trade.open_date_utc):
            state["high"] = max(state["high"], float(row["high_" + self.atr_frame]))
            state["stop"] = closed_stop(profile, entry=trade.open_rate, entry_atr=state["atr"],
                initial=state["initial"], previous_stop=state["stop"], closed_high=state["high"],
                current_atr=atr, structure_low=float(row["low10_" + self.atr_frame]))
            state["last_date"] = date_ms
        trade.set_custom_data(key, state)
        return stoploss_from_absolute(state["stop"], current_rate, is_short=False, leverage=1)


class D55Legacy(StopAblation, Donchian55): pass
class D55Wide(StopAblation, Donchian55): stop_profile = "wide"
class D55Fixed(StopAblation, Donchian55): stop_profile = "fixed"
class D55ClosedTrail(StopAblation, Donchian55): stop_profile = "closed_trail"
class D55Structure(StopAblation, Donchian55): stop_profile = "structure"

class E4Legacy(StopAblation, EMA4h): pass
class E4Wide(StopAblation, EMA4h): stop_profile = "wide"
class E4Fixed(StopAblation, EMA4h): stop_profile = "fixed"
class E4ClosedTrail(StopAblation, EMA4h): stop_profile = "closed_trail"
class E4Structure(StopAblation, EMA4h): stop_profile = "structure"

class A1Legacy(StopAblation, ADXBreakout1h): pass
class A1Wide(StopAblation, ADXBreakout1h): stop_profile = "wide"
class A1Fixed(StopAblation, ADXBreakout1h): stop_profile = "fixed"
class A1ClosedTrail(StopAblation, ADXBreakout1h): stop_profile = "closed_trail"
class A1Structure(StopAblation, ADXBreakout1h): stop_profile = "structure"

class M4Legacy(StopAblation, MTFFourHourExit): pass
class M4Wide(StopAblation, MTFFourHourExit): stop_profile = "wide"
class M4Fixed(StopAblation, MTFFourHourExit): stop_profile = "fixed"
class M4ClosedTrail(StopAblation, MTFFourHourExit): stop_profile = "closed_trail"
class M4Structure(StopAblation, MTFFourHourExit): stop_profile = "structure"
