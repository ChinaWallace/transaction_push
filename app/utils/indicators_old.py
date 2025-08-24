# -*- coding: utf-8 -*-
"""
技术指标计算工具
Technical indicators calculation utilities
"""

import numpy as np
import pandas as pd
import talib
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal

from app.core.logging import get_logger
from app.utils.exceptions import IndicatorCalculationError

logger = get_logger(__name__)


class SuperTrendIndicator:
    """SuperTrend指标计算器 - 修复版"""
    
    def __init__(self, period: int = 10, multiplier: float = 3.0):
        self.period = period
        self.multiplier = multiplier
    
    def _calculate_atr_numpy(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """
        使用numpy计算ATR (Average True Range)
        
        Args:
            high: 最高价数组
            low: 最低价数组
            close: 收盘价数组
            
        Returns:
            ATR数组
        """
        if len(high) < self.period:
            raise IndicatorCalculationError(f"数据不足，需要至少{self.period}个数据点")
        
        # 计算真实波动幅度
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]  # 第一个值使用当前收盘价
        
        tr1 = high - low
        tr2 = np.abs(high - prev_close)
        tr3 = np.abs(low - prev_close)
        
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))
        
        # 计算ATR (简单移动平均)
        atr = np.full_like(close, np.nan)
        
        for i in range(len(close)):
            if i >= self.period - 1:
                atr[i] = np.mean(true_range[i-self.period+1:i+1])
        
        return atr
    
    def calculate(self, high: List[float], low: List[float], close: List[float]) -> Tuple[List[float], List[bool]]:
        """
        计算SuperTrend指标
        
        Args:
            high: 最高价列表
            low: 最低价列表  
            close: 收盘价列表
            
        Returns:
            Tuple[List[float], List[bool]]: (SuperTrend值列表, 趋势方向列表)
        """
        try:
            if len(high) != len(low) or len(low) != len(close):
                raise IndicatorCalculationError("High, Low, Close arrays must have same length")
            
            if len(close) < self.period:
                raise IndicatorCalculationError(f"Not enough data points. Need at least {self.period}")
            
            # 转换为numpy数组
            high_arr = np.array(high, dtype=float)
            low_arr = np.array(low, dtype=float)
            close_arr = np.array(close, dtype=float)
            
            # 计算ATR (使用TA-Lib)
            atr = talib.ATR(high_arr, low_arr, close_arr, timeperiod=self.period)
            
            # 计算HL2 (High + Low) / 2
            hl2 = (high_arr + low_arr) / 2
            
            # 计算基础上下轨
            upper_basic = hl2 + (self.multiplier * atr)
            lower_basic = hl2 - (self.multiplier * atr)
            
            # 初始化最终上下轨
            upper_final = np.full_like(close_arr, np.nan)
            lower_final = np.full_like(close_arr, np.nan)
            
            # 计算最终上下轨
            for i in range(len(close_arr)):
                if i == 0:
                    upper_final[i] = upper_basic[i]
                    lower_final[i] = lower_basic[i]
                else:
                    # 上轨计算
                    if upper_basic[i] < upper_final[i-1] or close_arr[i-1] > upper_final[i-1]:
                        upper_final[i] = upper_basic[i]
                    else:
                        upper_final[i] = upper_final[i-1]
                    
                    # 下轨计算
                    if lower_basic[i] > lower_final[i-1] or close_arr[i-1] < lower_final[i-1]:
                        lower_final[i] = lower_basic[i]
                    else:
                        lower_final[i] = lower_final[i-1]
            
            # 计算SuperTrend值和方向
            supertrend = np.full_like(close_arr, np.nan)
            is_uptrend = np.full(len(close_arr), False, dtype=bool)
            
            for i in range(len(close_arr)):
                if i == 0:
                    # 初始方向判断 - 正确的SuperTrend逻辑
                    if close_arr[i] <= lower_final[i]:
                        supertrend[i] = lower_final[i]
                        is_uptrend[i] = True   # 价格在下轨之上，上升趋势
                    else:
                        supertrend[i] = upper_final[i]
                        is_uptrend[i] = False  # 价格在上轨之下，下降趋势
                else:
                    # 趋势延续或转换 - 正确的SuperTrend逻辑
                    if is_uptrend[i-1]:
                        # 之前是上升趋势
                        if close_arr[i] <= lower_final[i]:
                            # 价格跌破下轨，转为下降趋势
                            supertrend[i] = upper_final[i]
                            is_uptrend[i] = False
                        else:
                            # 继续上升趋势
                            supertrend[i] = lower_final[i]
                            is_uptrend[i] = True
                    else:
                        # 之前是下降趋势
                        if close_arr[i] >= upper_final[i]:
                            # 价格突破上轨，转为上升趋势
                            supertrend[i] = lower_final[i]
                            is_uptrend[i] = True
                        else:
                            # 继续下降趋势
                            supertrend[i] = upper_final[i]
                            is_uptrend[i] = False
            
            # 转换为列表并处理NaN值
            supertrend_values = []
            trend_directions = []
            
            for i in range(len(supertrend)):
                if np.isnan(supertrend[i]):
                    supertrend_values.append(None)
                    trend_directions.append(False)  # 默认为下降趋势
                else:
                    supertrend_values.append(float(supertrend[i]))
                    trend_directions.append(bool(is_uptrend[i]))
            
            return supertrend_values, trend_directions
            
        except Exception as e:
            logger.error(f"SuperTrend calculation failed: {e}")
            raise IndicatorCalculationError(f"SuperTrend calculation failed: {e}")
    
    def calculate_from_klines(self, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从K线数据计算SuperTrend - 支持多种字段名格式"""
        try:
            if not klines:
                return []
            
            # 智能提取OHLC数据 - 支持多种字段名格式
            def get_price_field(kline, field_name):
                """智能获取价格字段"""
                # 优先使用带_price后缀的字段名
                if f'{field_name}_price' in kline:
                    return float(kline[f'{field_name}_price'])
                # 其次使用不带后缀的字段名
                elif field_name in kline:
                    return float(kline[field_name])
                # 最后尝试其他可能的字段名
                else:
                    for key in kline.keys():
                        if field_name.lower() in key.lower():
                            return float(kline[key])
                    raise KeyError(f"Cannot find {field_name} field in kline data")
            
            high = [get_price_field(k, 'high') for k in klines]
            low = [get_price_field(k, 'low') for k in klines]
            close = [get_price_field(k, 'close') for k in klines]
            
            # 计算SuperTrend
            supertrend_values, trend_directions = self.calculate(high, low, close)
            
            # 添加指标数据到K线
            result = []
            for i, kline in enumerate(klines):
                enriched_kline = kline.copy()
                enriched_kline['supertrend_value'] = supertrend_values[i]
                # 正确处理趋势方向
                if trend_directions[i] is None:
                    enriched_kline['supertrend_direction'] = None
                else:
                    enriched_kline['supertrend_direction'] = 'up' if trend_directions[i] else 'down'
                result.append(enriched_kline)
            
            return result
            
        except Exception as e:
            logger.error(f"SuperTrend calculation from klines failed: {e}")
            raise


class VolumeIndicator:
    """成交量指标计算器"""
    
    @staticmethod
    def calculate_volume_ratio(klines: List[Dict[str, Any]], periods: int = 3) -> List[Dict[str, Any]]:
        """
        计算成交量比率（庄神指标）
        
        Args:
            klines: K线数据列表
            periods: 计算周期
            
        Returns:
            包含成交量比率的K线数据
        """
        try:
            if len(klines) < periods:
                return klines
            
            result = []
            for i, kline in enumerate(klines):
                enriched_kline = kline.copy()
                
                if i >= periods - 1:
                    # 计算成交量比率
                    current_volume = float(kline['volume'])
                    previous_volume = float(klines[i-1]['volume'])
                    
                    if previous_volume > 0:
                        volume_ratio = current_volume / previous_volume
                        enriched_kline['volume_ratio'] = round(volume_ratio, 4)
                        
                        # 判断是否为成交量异常
                        if volume_ratio >= 3.0:
                            # 检查是否连续多根K线都满足条件
                            consecutive_count = 1
                            for j in range(1, min(periods, i + 1)):
                                prev_kline = klines[i-j]
                                prev_prev_kline = klines[i-j-1] if i-j-1 >= 0 else None
                                
                                if prev_prev_kline:
                                    prev_ratio = float(prev_kline['volume']) / float(prev_prev_kline['volume'])
                                    if prev_ratio >= 3.0:
                                        consecutive_count += 1
                                    else:
                                        break
                            
                            # 检查价格是否配合 - 智能字段名处理
                            def get_price_value(kline_data, field_name):
                                """智能获取价格值"""
                                if f'{field_name}_price' in kline_data:
                                    return float(kline_data[f'{field_name}_price'])
                                elif field_name in kline_data:
                                    return float(kline_data[field_name])
                                else:
                                    for key in kline_data.keys():
                                        if field_name.lower() in key.lower():
                                            return float(kline_data[key])
                                    return 0.0
                            
                            current_close = get_price_value(kline, 'close')
                            current_open = get_price_value(kline, 'open')
                            is_price_up = current_close > current_open
                            
                            enriched_kline['price_up'] = 'yes' if is_price_up else 'no'
                            
                            # 强势标的：连续成交量放大且价格配合
                            if consecutive_count >= periods and is_price_up:
                                enriched_kline['is_volume_anomaly'] = 'strong'
                            elif is_price_up:
                                enriched_kline['is_volume_anomaly'] = 'normal'
                            else:
                                enriched_kline['is_volume_anomaly'] = 'none'
                        else:
                            enriched_kline['is_volume_anomaly'] = 'none'
                            enriched_kline['price_up'] = 'no'
                    else:
                        enriched_kline['volume_ratio'] = 0
                        enriched_kline['is_volume_anomaly'] = 'none'
                        enriched_kline['price_up'] = 'no'
                else:
                    enriched_kline['volume_ratio'] = None
                    enriched_kline['is_volume_anomaly'] = 'none'
                    enriched_kline['price_up'] = 'no'
                
                result.append(enriched_kline)
            
            return result
            
        except Exception as e:
            logger.error(f"Volume ratio calculation failed: {e}")
            raise IndicatorCalculationError(f"Volume ratio calculation failed: {e}")


class MovingAverageIndicator:
    """移动平均线指标"""
    
    @staticmethod
    def sma(prices: List[float], period: int) -> List[float]:
        """简单移动平均"""
        try:
            prices_arr = np.array(prices, dtype=float)
            sma_values = talib.SMA(prices_arr, timeperiod=period)
            return [float(x) if not np.isnan(x) else None for x in sma_values]
        except Exception as e:
            logger.error(f"SMA calculation failed: {e}")
            raise IndicatorCalculationError(f"SMA calculation failed: {e}")
    
    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        """指数移动平均"""
        try:
            prices_arr = np.array(prices, dtype=float)
            ema_values = talib.EMA(prices_arr, timeperiod=period)
            return [float(x) if not np.isnan(x) else None for x in ema_values]
        except Exception as e:
            logger.error(f"EMA calculation failed: {e}")
            raise IndicatorCalculationError(f"EMA calculation failed: {e}")


class RSIIndicator:
    """RSI指标"""
    
    @staticmethod
    def calculate(prices: List[float], period: int = 14) -> List[float]:
        """计算RSI"""
        try:
            prices_arr = np.array(prices, dtype=float)
            rsi_values = talib.RSI(prices_arr, timeperiod=period)
            return [float(x) if not np.isnan(x) else None for x in rsi_values]
        except Exception as e:
            logger.error(f"RSI calculation failed: {e}")
            raise IndicatorCalculationError(f"RSI calculation failed: {e}")


def calculate_support_resistance(
    market_data: pd.DataFrame, 
    lookback_periods: int = 20
) -> Tuple[List[float], List[float]]:
    """
    计算支撑位和阻力位
    
    Args:
        market_data: 包含OHLC数据的DataFrame
        lookback_periods: 回看周期
        
    Returns:
        Tuple[List[float], List[float]]: (支撑位列表, 阻力位列表)
    """
    try:
        if market_data.empty or len(market_data) < lookback_periods:
            return [], []
        
        # 获取最近的数据
        recent_data = market_data.tail(lookback_periods)
        
        # 计算局部高点和低点 - 智能字段名处理
        def get_price_column(df, price_type):
            """智能获取价格列"""
            # 优先使用带_price后缀的字段名
            if f'{price_type}_price' in df.columns:
                return df[f'{price_type}_price'].values
            # 其次使用不带后缀的字段名
            elif price_type in df.columns:
                return df[price_type].values
            # 最后尝试其他可能的字段名
            else:
                for col in df.columns:
                    if price_type.lower() in col.lower():
                        return df[col].values
                raise KeyError(f"Cannot find {price_type} column in DataFrame")
        
        highs = get_price_column(recent_data, 'high')
        lows = get_price_column(recent_data, 'low')
        closes = get_price_column(recent_data, 'close')
        
        # 寻找局部极值点
        support_levels = []
        resistance_levels = []
        
        # 简化的支撑阻力计算
        window = min(5, len(recent_data) // 4)  # 动态窗口大小
        
        for i in range(window, len(recent_data) - window):
            # 检查是否为局部低点（支撑）
            current_low = lows[i]
            is_local_min = all(current_low <= lows[j] for j in range(i-window, i+window+1))
            
            if is_local_min:
                support_levels.append(current_low)
            
            # 检查是否为局部高点（阻力）
            current_high = highs[i]
            is_local_max = all(current_high >= highs[j] for j in range(i-window, i+window+1))
            
            if is_local_max:
                resistance_levels.append(current_high)
        
        # 当前价格
        current_price = closes[-1]
        
        # 过滤并排序支撑位（小于当前价格）
        valid_supports = [s for s in support_levels if s < current_price]
        valid_supports = sorted(set(valid_supports), reverse=True)[:3]  # 最近的3个支撑位
        
        # 过滤并排序阻力位（大于当前价格）
        valid_resistances = [r for r in resistance_levels if r > current_price]
        valid_resistances = sorted(set(valid_resistances))[:3]  # 最近的3个阻力位
        
        return valid_supports, valid_resistances
        
    except Exception as e:
        logger.error(f"Support/Resistance calculation failed: {e}")
        return [], []
