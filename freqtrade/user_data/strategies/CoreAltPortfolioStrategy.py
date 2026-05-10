import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame


class CoreAltPortfolioStrategy(IStrategy):
    """
    Portfolio strategy for two different crypto jobs:

    - Core pairs: BTC/ETH/SOL/ZEC style large-cap entries with trend, pullback,
      and reward/risk filters.
    - Alt pairs: smaller positions only when BTC regime is constructive and
      the pair shows relative strength, volume expansion, and breakout demand.
    """

    timeframe = "1h"
    can_short = False
    startup_candle_count = 360
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.085,
        "720": 0.045,
        "2160": 0.02,
        "4320": 0,
    }
    stoploss = -0.055
    trailing_stop = True
    trailing_stop_positive = 0.022
    trailing_stop_positive_offset = 0.055
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
                "stop_duration_candles": 6,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 2,
                "stop_duration_candles": 36,
                "only_per_pair": True,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 336,
                "trade_limit": 12,
                "stop_duration_candles": 72,
                "max_allowed_drawdown": 0.10,
            },
        ]

    @informative("1h", "BTC/USDT:USDT", fmt="btc_{column}")
    def populate_btc_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["return_72"] = dataframe["close"].pct_change(72)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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

        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]

        dataframe["volume_mean_24"] = dataframe["volume"].rolling(24).mean()
        dataframe["volume_mean_96"] = dataframe["volume"].rolling(96).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean_24"]
        dataframe["quote_volume"] = dataframe["volume"] * dataframe["close"]
        dataframe["quote_volume_mean_72"] = dataframe["quote_volume"].rolling(72).mean()
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"]

        dataframe["return_24"] = dataframe["close"].pct_change(24)
        dataframe["return_72"] = dataframe["close"].pct_change(72)
        dataframe["return_168"] = dataframe["close"].pct_change(168)
        dataframe["high_96"] = dataframe["high"].rolling(96).max().shift(1)
        dataframe["high_240"] = dataframe["high"].rolling(240).max().shift(1)
        dataframe["low_48"] = dataframe["low"].rolling(48).min().shift(1)
        dataframe["risk_unit"] = dataframe["close"] - dataframe[["low_48", "ema_200"]].max(axis=1)
        dataframe["reward_unit"] = dataframe["high_240"] - dataframe["close"]
        dataframe["rr_proxy"] = dataframe["reward_unit"] / dataframe["risk_unit"].clip(lower=dataframe["atr"] * 0.7)

        dataframe["btc_regime_ok"] = (
            (dataframe["btc_close"] > dataframe["btc_ema_200"])
            & (dataframe["btc_ema_50"] > dataframe["btc_ema_200"] * 0.98)
            & (dataframe["btc_return_72"] > -0.06)
            & (dataframe["btc_rsi"] > 42)
        )
        dataframe["btc_regime_risk_off"] = (
            (dataframe["btc_close"] < dataframe["btc_ema_200"])
            & (dataframe["btc_return_72"] < -0.04)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        pair = metadata.get("pair", "")
        is_core = pair in self.core_pairs

        base_liquidity = (
            (dataframe["quote_volume_mean_72"] > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["atr_ratio"].between(0.006, 0.085))
        )

        core_trend = (
            is_core
            & base_liquidity
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["ema_50"] > dataframe["ema_200"] * 0.985)
            & (dataframe["plus_di"] > dataframe["minus_di"])
            & (dataframe["adx"] > 17)
        )
        core_pullback_rr = (
            core_trend
            & (dataframe["close"] > dataframe["ema_50"] * 0.97)
            & (dataframe["close"] < dataframe["ema_50"] * 1.045)
            & (dataframe["rsi"].between(42, 60))
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["macdhist"] > dataframe["macdhist"].shift(1))
            & (dataframe["rr_proxy"] > 1.6)
        )
        core_breakout = (
            core_trend
            & (dataframe["close"] > dataframe["high_96"])
            & (dataframe["rsi"].between(52, 72))
            & (dataframe["volume_ratio"] > 1.15)
            & (dataframe["return_72"] > 0.025)
        )

        alt_heat = (
            (not is_core)
            & base_liquidity
            & dataframe["btc_regime_ok"]
            & (dataframe["close"] > dataframe["ema_50"])
            & (dataframe["ema_20"] > dataframe["ema_50"])
            & (dataframe["close"] > dataframe["high_96"])
            & (dataframe["volume_ratio"] > 1.45)
            & (dataframe["quote_volume"] > dataframe["quote_volume_mean_72"] * 1.35)
            & (dataframe["return_24"] > 0.018)
            & (dataframe["return_168"] > dataframe["btc_return_72"])
            & (dataframe["rsi"].between(55, 78))
            & (dataframe["adx"] > 20)
        )

        dataframe.loc[core_pullback_rr, ["enter_long", "enter_tag"]] = (1, "core_pullback_rr")
        dataframe.loc[core_breakout, ["enter_long", "enter_tag"]] = (1, "core_breakout")
        dataframe.loc[alt_heat, ["enter_long", "enter_tag"]] = (1, "alt_heat_volume")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        pair = metadata.get("pair", "")
        is_core = pair in self.core_pairs

        core_exit = (
            is_core
            & (
                ((dataframe["close"] < dataframe["ema_50"]) & (dataframe["rsi"] < 45))
                | ((dataframe["ema_20"] < dataframe["ema_50"]) & (dataframe["macd"] < dataframe["macdsignal"]))
            )
        )
        alt_exit = (
            (not is_core)
            & (
                dataframe["btc_regime_risk_off"]
                | ((dataframe["close"] < dataframe["ema_20"]) & (dataframe["volume_ratio"] < 0.95))
                | ((dataframe["rsi"] < 50) & (dataframe["macd"] < dataframe["macdsignal"]))
            )
        )

        dataframe.loc[
            ((core_exit | alt_exit) & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "portfolio_exit")
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
            stake = proposed_stake * 2.5
        elif entry_tag == "alt_heat_volume":
            stake = proposed_stake * 0.6
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
