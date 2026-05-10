import talib.abstract as ta
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class OpenSourceTrendStrategy(IStrategy):
    """
    Conservative long-only strategy built from common open-source Freqtrade
    building blocks: EMA regime filter, RSI/Bollinger pullbacks, ADX breakouts,
    volume confirmation, and ATR volatility guard.
    """

    timeframe = "1h"
    can_short = False
    startup_candle_count = 240
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.045,
        "360": 0.025,
        "1080": 0.012,
        "2160": 0,
    }
    stoploss = -0.035
    trailing_stop = True
    trailing_stop_positive = 0.012
    trailing_stop_positive_offset = 0.028
    trailing_only_offset_is_reached = True

    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 4,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 72,
                "trade_limit": 2,
                "stop_duration_candles": 24,
                "only_per_pair": True,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 168,
                "trade_limit": 8,
                "stop_duration_candles": 48,
                "max_allowed_drawdown": 0.08,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=28)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]

        dataframe["volume_mean"] = dataframe["volume"].rolling(30).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean"]
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"]
        dataframe["high_48"] = dataframe["high"].rolling(48).max().shift(1)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        healthy_market = (
            (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["ema_50"] > dataframe["ema_200"] * 0.985)
            & (dataframe["atr_ratio"] < 0.065)
            & (dataframe["volume_ratio"] > 0.75)
            & (dataframe["volume"] > 0)
        )

        bollinger_reclaim = (
            healthy_market
            & (dataframe["close"].shift(1) < dataframe["bb_lower"].shift(1))
            & (dataframe["close"] > dataframe["bb_lower"])
            & (dataframe["rsi"].between(34, 52))
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["rsi_slow"] > 38)
        )

        volume_breakout = (
            healthy_market
            & (dataframe["close"] > dataframe["high_48"])
            & (dataframe["adx"] > 20)
            & (dataframe["plus_di"] > dataframe["minus_di"])
            & (dataframe["rsi"].between(52, 72))
            & (dataframe["volume_ratio"] > 1.25)
        )

        dataframe.loc[bollinger_reclaim, ["enter_long", "enter_tag"]] = (1, "bb_reclaim")
        dataframe.loc[volume_breakout, ["enter_long", "enter_tag"]] = (1, "volume_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        trend_break = (
            (dataframe["close"] < dataframe["ema_50"])
            & (dataframe["rsi"] < 46)
            & (dataframe["macd"] < dataframe["macdsignal"])
        )
        exhaustion = (
            (dataframe["close"] > dataframe["bb_upper"])
            & (dataframe["rsi"] > 74)
            & (dataframe["rsi"] < dataframe["rsi"].shift(1))
        )
        volatility_break = dataframe["atr_ratio"] > 0.085

        dataframe.loc[
            ((trend_break | exhaustion | volatility_break) & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "risk_exit")
        return dataframe

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
