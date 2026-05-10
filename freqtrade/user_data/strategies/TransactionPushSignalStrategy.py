import os

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter
from pandas import DataFrame


class TransactionPushSignalStrategy(IStrategy):
    """
    Freqtrade-native projection of the transaction_push signal stack.

    The live app fuses realtime Kronos, technical, volume/price, and quality
    gates into TradingSignal objects. Historical Freqtrade backtests need a
    candle-by-candle equivalent, so this strategy maps the replayable parts of
    that decision into dataframe columns:

    - tp_trend_score: EMA regime, ADX direction, broad trend filter.
    - tp_momentum_score: RSI/MACD/Bollinger momentum confirmation.
    - tp_volume_score: liquidity and participation confirmation.
    - tp_signal_score: weighted long-only score after risk penalties.
    - tp_buy_allowed: quality gate used as Freqtrade's entry input.
    """

    timeframe = os.getenv("TP_SIGNAL_TIMEFRAME", "1h")
    can_short = False
    startup_candle_count = 240
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.06,
        "240": 0.035,
        "720": 0.015,
        "1440": 0,
    }
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.018
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    buy_threshold = IntParameter(
        58,
        82,
        default=int(os.getenv("TP_SIGNAL_BUY_THRESHOLD", "68")),
        space="buy",
        optimize=True,
    )
    exit_threshold = IntParameter(
        35,
        62,
        default=int(os.getenv("TP_SIGNAL_EXIT_THRESHOLD", "48")),
        space="sell",
        optimize=True,
    )
    min_volume_factor = DecimalParameter(
        0.70,
        1.50,
        default=float(os.getenv("TP_SIGNAL_MIN_VOLUME_FACTOR", "0.95")),
        decimals=2,
        space="buy",
        optimize=True,
    )
    max_atr_ratio = DecimalParameter(
        0.025,
        0.090,
        default=float(os.getenv("TP_SIGNAL_MAX_ATR_RATIO", "0.065")),
        decimals=3,
        space="buy",
        optimize=True,
    )
    max_rsi = IntParameter(
        62,
        78,
        default=int(os.getenv("TP_SIGNAL_MAX_RSI", "72")),
        space="buy",
        optimize=True,
    )

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
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": True,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

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
        dataframe["distance_ema50"] = (dataframe["close"] / dataframe["ema_50"]) - 1

        self._populate_transaction_push_scores(dataframe)
        return dataframe

    def _populate_transaction_push_scores(self, dataframe: DataFrame) -> None:
        dataframe["tp_trend_score"] = 0.0
        dataframe.loc[dataframe["close"] > dataframe["ema_200"], "tp_trend_score"] += 10
        dataframe.loc[dataframe["ema_12"] > dataframe["ema_26"], "tp_trend_score"] += 10
        dataframe.loc[dataframe["ema_26"] > dataframe["ema_50"], "tp_trend_score"] += 10
        dataframe.loc[dataframe["ema_50"] > dataframe["ema_200"], "tp_trend_score"] += 10
        dataframe.loc[
            (dataframe["adx"] > 18) & (dataframe["plus_di"] > dataframe["minus_di"]),
            "tp_trend_score",
        ] += 5

        dataframe["tp_momentum_score"] = 0.0
        dataframe.loc[dataframe["rsi"].between(50, 68), "tp_momentum_score"] += 10
        dataframe.loc[dataframe["rsi"].between(45, 72), "tp_momentum_score"] += 5
        dataframe.loc[dataframe["macd"] > dataframe["macdsignal"], "tp_momentum_score"] += 8
        dataframe.loc[dataframe["macdhist"] > dataframe["macdhist"].shift(1), "tp_momentum_score"] += 4
        dataframe.loc[dataframe["close"] > dataframe["bb_middle"], "tp_momentum_score"] += 3

        dataframe["tp_volume_score"] = 0.0
        dataframe.loc[dataframe["volume"] > dataframe["volume_mean"], "tp_volume_score"] += 12
        dataframe.loc[dataframe["volume_ratio"] > 1.25, "tp_volume_score"] += 5
        dataframe.loc[dataframe["volume_ratio"].between(0.8, 1.25), "tp_volume_score"] += 3

        dataframe["tp_risk_penalty"] = 0.0
        dataframe.loc[dataframe["atr_ratio"] > float(self.max_atr_ratio.value), "tp_risk_penalty"] += 20
        dataframe.loc[dataframe["atr_ratio"] < 0.003, "tp_risk_penalty"] += 5
        dataframe.loc[dataframe["rsi"] > int(self.max_rsi.value), "tp_risk_penalty"] += 10
        dataframe.loc[dataframe["distance_ema50"] > 0.12, "tp_risk_penalty"] += 8
        dataframe.loc[dataframe["volume_mean"].isna() | (dataframe["volume_mean"] <= 0), "tp_risk_penalty"] += 30

        trend_pct = dataframe["tp_trend_score"] / 45.0 * 100.0
        momentum_pct = dataframe["tp_momentum_score"] / 30.0 * 100.0
        volume_pct = dataframe["tp_volume_score"] / 20.0 * 100.0
        raw_score = trend_pct * 0.55 + momentum_pct * 0.30 + volume_pct * 0.15
        dataframe["tp_signal_score"] = np.clip(raw_score - dataframe["tp_risk_penalty"], 0, 100)

        dataframe["tp_buy_allowed"] = (
            (dataframe["tp_signal_score"] >= int(self.buy_threshold.value))
            & (dataframe["close"] > dataframe["ema_50"])
            & (dataframe["ema_12"] > dataframe["ema_26"])
            & (dataframe["rsi"] < int(self.max_rsi.value))
            & (dataframe["atr_ratio"] <= float(self.max_atr_ratio.value))
            & (dataframe["volume_ratio"] >= float(self.min_volume_factor.value))
            & (dataframe["volume"] > 0)
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        dataframe.loc[
            (
                dataframe["tp_buy_allowed"]
                & (dataframe["tp_signal_score"] > dataframe["tp_signal_score"].shift(1))
                & (
                    (dataframe["adx"] > 18)
                    | (dataframe["macdhist"] > dataframe["macdhist"].shift(1))
                )
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "tp_signal_long")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        dataframe.loc[
            (
                (
                    (dataframe["tp_signal_score"] < int(self.exit_threshold.value))
                    | ((dataframe["close"] < dataframe["ema_26"]) & (dataframe["rsi"] < 48))
                    | ((dataframe["ema_12"] < dataframe["ema_26"]) & (dataframe["macd"] < dataframe["macdsignal"]))
                    | (dataframe["atr_ratio"] > float(self.max_atr_ratio.value) * 1.2)
                )
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "tp_signal_exit")
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
