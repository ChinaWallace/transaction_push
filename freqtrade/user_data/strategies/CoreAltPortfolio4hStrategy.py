import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame


class CoreAltPortfolio4hStrategy(IStrategy):
    """
    Medium-term portfolio strategy.

    Core pairs use 4h trend, pullback, breakout, and reward/risk filters.
    Alt pairs are smaller heat/volume momentum trades allowed only when BTC's
    4h market regime is constructive.
    """

    timeframe = "4h"
    can_short = False
    startup_candle_count = 240
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.14,
        "2880": 0.075,
        "10080": 0.035,
        "20160": 0,
    }
    stoploss = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.035
    trailing_stop_positive_offset = 0.085
    trailing_only_offset_is_reached = True

    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    core_pairs = {
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "ZEC/USDT:USDT",
    }

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
                "max_allowed_drawdown": 0.12,
            },
        ]

    @informative("4h", "BTC/USDT:USDT", fmt="btc_{column}")
    def populate_btc_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["return_18"] = dataframe["close"].pct_change(18)
        dataframe["return_42"] = dataframe["close"].pct_change(42)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        dataframe["volume_mean_12"] = dataframe["volume"].rolling(12).mean()
        dataframe["volume_mean_42"] = dataframe["volume"].rolling(42).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean_12"]
        dataframe["quote_volume"] = dataframe["volume"] * dataframe["close"]
        dataframe["quote_volume_mean_42"] = dataframe["quote_volume"].rolling(42).mean()
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"]

        dataframe["return_6"] = dataframe["close"].pct_change(6)
        dataframe["return_18"] = dataframe["close"].pct_change(18)
        dataframe["return_42"] = dataframe["close"].pct_change(42)
        dataframe["high_24"] = dataframe["high"].rolling(24).max().shift(1)
        dataframe["high_60"] = dataframe["high"].rolling(60).max().shift(1)
        dataframe["high_120"] = dataframe["high"].rolling(120).max().shift(1)
        dataframe["low_12"] = dataframe["low"].rolling(12).min().shift(1)
        dataframe["risk_unit"] = dataframe["close"] - dataframe[["low_12", "ema_200"]].max(axis=1)
        dataframe["reward_unit"] = dataframe["high_120"] - dataframe["close"]
        dataframe["rr_proxy"] = dataframe["reward_unit"] / dataframe["risk_unit"].clip(lower=dataframe["atr"] * 0.8)

        dataframe["btc_regime_ok"] = (
            (dataframe["btc_close"] > dataframe["btc_ema_200"])
            & (dataframe["btc_ema_50"] > dataframe["btc_ema_200"] * 0.98)
            & (dataframe["btc_return_18"] > -0.055)
            & (dataframe["btc_rsi"] > 42)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        pair = metadata.get("pair", "")
        is_core = pair in self.core_pairs

        base_liquidity = (
            (dataframe["quote_volume_mean_42"] > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["atr_ratio"].between(0.01, 0.12))
        )

        core_trend = (
            is_core
            & base_liquidity
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["ema_50"] > dataframe["ema_200"] * 0.97)
            & (dataframe["plus_di"] > dataframe["minus_di"])
        )
        core_pullback_rr = (
            core_trend
            & (dataframe["close"] > dataframe["ema_50"] * 0.94)
            & (dataframe["close"] < dataframe["ema_50"] * 1.05)
            & (dataframe["rsi"].between(38, 58))
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["macdhist"] > dataframe["macdhist"].shift(1))
            & (dataframe["rr_proxy"] > 1.8)
        )
        core_breakout = (
            core_trend
            & (dataframe["close"] > dataframe["high_60"])
            & (dataframe["adx"] > 18)
            & (dataframe["rsi"].between(52, 74))
            & (dataframe["volume_ratio"] > 1.15)
            & (dataframe["return_18"] > 0.035)
        )
        alt_heat = (
            (not is_core)
            & base_liquidity
            & dataframe["btc_regime_ok"]
            & (dataframe["close"] > dataframe["ema_50"])
            & (dataframe["ema_12"] > dataframe["ema_50"])
            & (dataframe["close"] > dataframe["high_24"])
            & (dataframe["volume_ratio"] > 1.45)
            & (dataframe["quote_volume"] > dataframe["quote_volume_mean_42"] * 1.35)
            & (dataframe["return_6"] > 0.035)
            & (dataframe["return_42"] > dataframe["btc_return_42"])
            & (dataframe["rsi"].between(55, 80))
            & (dataframe["adx"] > 18)
        )

        dataframe.loc[core_pullback_rr, ["enter_long", "enter_tag"]] = (1, "core_pullback_rr_4h")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        return dataframe

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
        if pair in self.core_pairs:
            stake = proposed_stake * 3.0
        elif entry_tag == "alt_heat_volume_4h":
            stake = proposed_stake * 0.5
        else:
            stake = proposed_stake

        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

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
