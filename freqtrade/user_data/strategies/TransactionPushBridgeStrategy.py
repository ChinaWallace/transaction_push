from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta


class TransactionPushBridgeStrategy(IStrategy):
    """
    Conservative starter strategy for the transaction_push Freqtrade bridge.

    This is intentionally simple: use it to verify data, backtesting, dry-run,
    REST control, and risk settings before porting stronger signals from the
    main project.
    """

    timeframe = "5m"
    can_short = False
    startup_candle_count = 120
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.04,
        "60": 0.02,
        "180": 0.01,
    }
    stoploss = -0.025
    trailing_stop = True
    trailing_stop_positive = 0.012
    trailing_stop_positive_offset = 0.024
    trailing_only_offset_is_reached = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(30).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
                & (dataframe["rsi"] > 52)
                & (dataframe["rsi"] < 72)
                & (dataframe["volume"] > dataframe["volume_mean"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    (dataframe["ema_fast"] < dataframe["ema_slow"])
                    | ((dataframe["close"] < dataframe["ema_slow"]) & (dataframe["rsi"] < 48))
                    | ((dataframe["close"] < dataframe["ema_fast"]) & (dataframe["rsi"] < 55))
                )
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1
        return dataframe

