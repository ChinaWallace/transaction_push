"""Conservative BTC/ETH-only 4h research baseline.

This strategy is intentionally long-only and 1x.  It is a testable starting
point for backtesting and dry-run forward validation, not a profitability
claim and not a live-trading preset.
"""

import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame


class BtcEth4hStrategy(IStrategy):
    timeframe = "4h"
    can_short = False
    startup_candle_count = 240
    process_only_new_candles = True
    position_adjustment_enable = False

    allowed_pairs = {
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
    }

    minimal_roi = {
        "0": 0.08,
        "2880": 0.045,
        "10080": 0.02,
        "20160": 0,
    }
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.045
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 3,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 18,
                "only_per_pair": True,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 120,
                "trade_limit": 8,
                "stop_duration_candles": 36,
                "max_allowed_drawdown": 0.08,
            },
        ]

    @informative("4h", "BTC/USDT:USDT", fmt="btc_{column}")
    def populate_btc_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["return_18"] = dataframe["close"].pct_change(18)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"]

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["volume_mean_20"] = dataframe["volume"].rolling(20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        allowed_pair = metadata.get("pair", "") in self.allowed_pairs
        btc_regime_ok = (
            (dataframe["btc_close"] > dataframe["btc_ema_200"])
            & (dataframe["btc_ema_50"] > dataframe["btc_ema_200"] * 0.98)
            & (dataframe["btc_return_18"] > -0.05)
            & (dataframe["btc_rsi"] > 42)
        )
        trend_pullback = (
            allowed_pair
            & btc_regime_ok
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["ema_50"] > dataframe["ema_200"])
            & (dataframe["close"] > dataframe["ema_20"] * 0.96)
            & (dataframe["close"] < dataframe["ema_20"] * 1.03)
            & dataframe["rsi"].between(42, 60)
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["adx"] > 18)
            & (dataframe["macdhist"] > dataframe["macdhist"].shift(1))
            & dataframe["atr_ratio"].between(0.004, 0.08)
            & (dataframe["volume"] > dataframe["volume_mean_20"] * 0.8)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[trend_pullback, ["enter_long", "enter_tag"]] = (
            1,
            "btc_eth_4h_trend_pullback",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        trend_break = (
            (dataframe["close"] < dataframe["ema_50"])
            & (dataframe["rsi"] < 42)
            & (dataframe["macdhist"] < 0)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[trend_break, ["exit_long", "exit_tag"]] = (1, "trend_break")
        return dataframe

    def confirm_trade_entry(self, pair: str, **kwargs) -> bool:
        return pair in self.allowed_pairs

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        stake = min(proposed_stake, max_stake)
        if min_stake is not None:
            stake = max(stake, min_stake)
        return stake

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return min(1.0, max_leverage)
