# -*- coding: utf-8 -*-
"""
技术指标计算器 - 修复版
Technical indicators calculator with fixed SuperTrend implementation
"""

import numpy as np
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

    def calculate_atr(self, high: np.array, low: np.array, close: np.array) -> np.array:
        """计算ATR (Average True Range)"""
        # True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        
        # 第一个值特殊处理
        tr2[0] = high[0] - low[0]
        tr3[0] = high[0] - low[0]
        
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))
        
        # 计算ATR (使用RMA - Wilder's smoothing)
        atr = np.zeros_like(true_range)
        atr[0] = true_range[0]
        
        for i in range(1, len(true_range)):
            atr[i] = (atr[i-1] * (self.period - 1) + true_range[i]) / self.period
        
        return atr

    def calculate(self, high: List[float], low: List[float], close: List[float]) -> Tuple[List[float], List[bool]]:
        """
        计算SuperTrend指标 - 修复版
        
        Args:
            high: 最高价列表
            low: 最低价列表  
            close: 收盘价列表
            
        Returns:
            Tuple[List[float], List[bool]]: (SuperTrend值列表, 趋势方向列表 - True为上涨)
        """
        try:
            if len(high) != len(low) or len(low) != len(close):
                raise ValueError("OHLC数据长度不一致")
            
            if len(high) < self.period:
                raise ValueError(f"数据长度不足，需要至少{self.period}个数据点")
            
            # 转换为numpy数组
            high_arr = np.array(high, dtype=float)
            low_arr = np.array(low, dtype=float)
            close_arr = np.array(close, dtype=float)
            
            # 计算ATR
            atr = self.calculate_atr(high_arr, low_arr, close_arr)
            
            # 计算HL2 (中位价)
            hl2 = (high_arr + low_arr) / 2
            
            # 计算基础上下轨
            upper_basic = hl2 + (self.multiplier * atr)
            lower_basic = hl2 - (self.multiplier * atr)
            
            # 计算最终上下轨
            upper_final = np.zeros_like(upper_basic)
            lower_final = np.zeros_like(lower_basic)
            
            # 初始化
            upper_final[0] = upper_basic[0]
            lower_final[0] = lower_basic[0]
            
            for i in range(1, len(close_arr)):
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
            
            # 计算SuperTrend和趋势方向
            supertrend = np.zeros_like(close_arr)
            trend_up = np.zeros(len(close_arr), dtype=bool)
            
            # 初始化第一个值
            if close_arr[0] <= lower_final[0]:
                supertrend[0] = lower_final[0]
                trend_up[0] = True
            else:
                supertrend[0] = upper_final[0]
                trend_up[0] = False
            
            # 计算后续值
            for i in range(1, len(close_arr)):
                # SuperTrend趋势判断逻辑
                if trend_up[i-1]:
                    # 之前是上涨趋势
                    if close_arr[i] <= lower_final[i]:
                        # 价格跌破下轨，转为下跌趋势
                        supertrend[i] = upper_final[i]
                        trend_up[i] = False
                    else:
                        # 继续上涨趋势
                        supertrend[i] = lower_final[i]
                        trend_up[i] = True
                else:
                    # 之前是下跌趋势
                    if close_arr[i] >= upper_final[i]:
                        # 价格突破上轨，转为上涨趋势
                        supertrend[i] = lower_final[i]
                        trend_up[i] = True
                    else:
                        # 继续下跌趋势
                        supertrend[i] = upper_final[i]
                        trend_up[i] = False
            
            # 转换为列表
            supertrend_values = supertrend.tolist()
            trend_directions = trend_up.tolist()
            
            return supertrend_values, trend_directions
            
        except Exception as e:
            logger.error(f"SuperTrend calculation failed: {e}")
            raise IndicatorCalculationError(f"SuperTrend calculation failed: {e}")
    
    def calculate_from_klines(self, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从K线数据计算SuperTrend"""
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
                    # 计算前N个周期的平均成交量
                    recent_volumes = []
                    for j in range(i - periods + 1, i + 1):
                        volume = klines[j].get('volume', 0)
                        if isinstance(volume, (int, float, Decimal)):
                            recent_volumes.append(float(volume))
                    
                    if recent_volumes:
                        avg_volume = sum(recent_volumes) / len(recent_volumes)
                        current_volume = float(kline.get('volume', 0))
                        
                        # 计算成交量比率
                        if avg_volume > 0:
                            volume_ratio = current_volume / avg_volume
                        else:
                            volume_ratio = 1.0
                        
                        enriched_kline['volume_ratio'] = volume_ratio
                        enriched_kline['avg_volume'] = avg_volume
                        
                        # 判断是否为异常成交量
                        enriched_kline['volume_spike'] = volume_ratio > 2.0
                    else:
                        enriched_kline['volume_ratio'] = 1.0
                        enriched_kline['avg_volume'] = float(kline.get('volume', 0))
                        enriched_kline['volume_spike'] = False
                else:
                    enriched_kline['volume_ratio'] = 1.0
                    enriched_kline['avg_volume'] = float(kline.get('volume', 0))
                    enriched_kline['volume_spike'] = False
                
                result.append(enriched_kline)
            
            return result
            
        except Exception as e:
            logger.error(f"Volume ratio calculation failed: {e}")
            raise IndicatorCalculationError(f"Volume ratio calculation failed: {e}")
    
    @staticmethod
    def detect_volume_anomaly(klines: List[Dict[str, Any]], threshold_multiplier: float = 3.0) -> List[Dict[str, Any]]:
        """
        检测成交量异常
        
        Args:
            klines: K线数据
            threshold_multiplier: 异常阈值倍数
            
        Returns:
            包含异常检测结果的K线数据
        """
        try:
            if len(klines) < 20:  # 需要足够的历史数据
                return klines
            
            # 计算成交量的移动平均和标准差
            volumes = [float(k.get('volume', 0)) for k in klines]
            
            result = []
            for i, kline in enumerate(klines):
                enriched_kline = kline.copy()
                
                if i >= 19:  # 使用前20个数据点计算统计量
                    recent_volumes = volumes[i-19:i+1]
                    avg_volume = sum(recent_volumes) / len(recent_volumes)
                    
                    # 计算标准差
                    variance = sum((v - avg_volume) ** 2 for v in recent_volumes) / len(recent_volumes)
                    std_volume = variance ** 0.5
                    
                    current_volume = volumes[i]
                    
                    # 检测异常
                    if std_volume > 0:
                        z_score = (current_volume - avg_volume) / std_volume
                        is_anomaly = abs(z_score) > threshold_multiplier
                    else:
                        z_score = 0
                        is_anomaly = False
                    
                    enriched_kline['volume_z_score'] = z_score
                    enriched_kline['volume_anomaly'] = is_anomaly
                    enriched_kline['volume_avg_20'] = avg_volume
                    enriched_kline['volume_std_20'] = std_volume
                else:
                    enriched_kline['volume_z_score'] = 0
                    enriched_kline['volume_anomaly'] = False
                    enriched_kline['volume_avg_20'] = volumes[i]
                    enriched_kline['volume_std_20'] = 0
                
                result.append(enriched_kline)
            
            return result
            
        except Exception as e:
            logger.error(f"Volume anomaly detection failed: {e}")
            raise IndicatorCalculationError(f"Volume anomaly detection failed: {e}")


class RSIIndicator:
    """RSI指标计算器"""
    
    def __init__(self, period: int = 14):
        self.period = period
    
    def calculate(self, prices: List[float]) -> List[Optional[float]]:
        """
        计算RSI指标
        
        Args:
            prices: 价格列表（通常是收盘价）
            
        Returns:
            RSI值列表
        """
        try:
            if len(prices) < self.period + 1:
                return [None] * len(prices)
            
            # 计算价格变化
            price_changes = []
            for i in range(1, len(prices)):
                change = prices[i] - prices[i-1]
                price_changes.append(change)
            
            # 分离上涨和下跌
            gains = [max(change, 0) for change in price_changes]
            losses = [abs(min(change, 0)) for change in price_changes]
            
            rsi_values = [None]  # 第一个值为None
            
            # 计算初始平均值
            if len(gains) >= self.period:
                avg_gain = sum(gains[:self.period]) / self.period
                avg_loss = sum(losses[:self.period]) / self.period
                
                # 计算第一个RSI值
                if avg_loss != 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100
                
                rsi_values.append(rsi)
                
                # 计算后续RSI值（使用Wilder's smoothing）
                for i in range(self.period + 1, len(price_changes) + 1):
                    current_gain = gains[i-1]
                    current_loss = losses[i-1]
                    
                    # Wilder's smoothing
                    avg_gain = (avg_gain * (self.period - 1) + current_gain) / self.period
                    avg_loss = (avg_loss * (self.period - 1) + current_loss) / self.period
                    
                    if avg_loss != 0:
                        rs = avg_gain / avg_loss
                        rsi = 100 - (100 / (1 + rs))
                    else:
                        rsi = 100
                    
                    rsi_values.append(rsi)
            
            # 补齐长度
            while len(rsi_values) < len(prices):
                rsi_values.append(None)
            
            return rsi_values
            
        except Exception as e:
            logger.error(f"RSI calculation failed: {e}")
            raise IndicatorCalculationError(f"RSI calculation failed: {e}")


def calculate_support_resistance(
    klines: List[Dict[str, Any]], 
    lookback_period: int = 20,
    min_touches: int = 2
) -> Dict[str, List[float]]:
    """
    计算支撑阻力位
    
    Args:
        klines: K线数据列表
        lookback_period: 回看周期
        min_touches: 最小触及次数
        
    Returns:
        Dict: 包含支撑位和阻力位的字典
    """
    try:
        if len(klines) < lookback_period:
            return {'support_levels': [], 'resistance_levels': []}
        
        # 提取价格数据
        highs = [float(k.get('high', k.get('high_price', 0))) for k in klines]
        lows = [float(k.get('low', k.get('low_price', 0))) for k in klines]
        closes = [float(k.get('close', k.get('close_price', 0))) for k in klines]
        
        # 寻找局部高点和低点
        local_highs = []
        local_lows = []
        
        for i in range(lookback_period // 2, len(highs) - lookback_period // 2):
            # 检查是否为局部高点
            is_local_high = True
            for j in range(i - lookback_period // 2, i + lookback_period // 2 + 1):
                if j != i and highs[j] >= highs[i]:
                    is_local_high = False
                    break
            
            if is_local_high:
                local_highs.append(highs[i])
            
            # 检查是否为局部低点
            is_local_low = True
            for j in range(i - lookback_period // 2, i + lookback_period // 2 + 1):
                if j != i and lows[j] <= lows[i]:
                    is_local_low = False
                    break
            
            if is_local_low:
                local_lows.append(lows[i])
        
        # 聚类相近的价格水平
        def cluster_levels(levels: List[float], tolerance: float = 0.01) -> List[float]:
            if not levels:
                return []
            
            sorted_levels = sorted(levels)
            clusters = []
            current_cluster = [sorted_levels[0]]
            
            for level in sorted_levels[1:]:
                if abs(level - current_cluster[-1]) / current_cluster[-1] <= tolerance:
                    current_cluster.append(level)
                else:
                    if len(current_cluster) >= min_touches:
                        clusters.append(sum(current_cluster) / len(current_cluster))
                    current_cluster = [level]
            
            # 处理最后一个聚类
            if len(current_cluster) >= min_touches:
                clusters.append(sum(current_cluster) / len(current_cluster))
            
            return clusters
        
        # 获取支撑阻力位
        resistance_levels = cluster_levels(local_highs)
        support_levels = cluster_levels(local_lows)
        
        return {
            'support_levels': support_levels,
            'resistance_levels': resistance_levels
        }
        
    except Exception as e:
        logger.error(f"Support/Resistance calculation failed: {e}")
        return {'support_levels': [], 'resistance_levels': []}


class MACDIndicator:
    """MACD指标计算器"""
    
    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
    
    def calculate_ema(self, prices: List[float], period: int) -> List[Optional[float]]:
        """计算EMA"""
        if len(prices) < period:
            return [None] * len(prices)
        
        ema_values = [None] * (period - 1)
        
        # 第一个EMA值是SMA
        sma = sum(prices[:period]) / period
        ema_values.append(sma)
        
        # 计算后续EMA值
        multiplier = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema = (prices[i] * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema)
        
        return ema_values
    
    def calculate(self, prices: List[float]) -> Dict[str, List[Optional[float]]]:
        """
        计算MACD指标
        
        Args:
            prices: 价格列表
            
        Returns:
            包含MACD线、信号线和柱状图的字典
        """
        try:
            # 计算快线和慢线EMA
            fast_ema = self.calculate_ema(prices, self.fast_period)
            slow_ema = self.calculate_ema(prices, self.slow_period)
            
            # 计算MACD线
            macd_line = []
            for i in range(len(prices)):
                if fast_ema[i] is not None and slow_ema[i] is not None:
                    macd_line.append(fast_ema[i] - slow_ema[i])
                else:
                    macd_line.append(None)
            
            # 计算信号线（MACD的EMA）
            macd_values_for_signal = [v for v in macd_line if v is not None]
            if len(macd_values_for_signal) >= self.signal_period:
                signal_ema = self.calculate_ema(macd_values_for_signal, self.signal_period)
                
                # 对齐信号线
                signal_line = [None] * len(macd_line)
                signal_start_index = len(macd_line) - len(signal_ema)
                for i, sig_val in enumerate(signal_ema):
                    if signal_start_index + i < len(signal_line):
                        signal_line[signal_start_index + i] = sig_val
            else:
                signal_line = [None] * len(macd_line)
            
            # 计算柱状图
            histogram = []
            for i in range(len(macd_line)):
                if macd_line[i] is not None and signal_line[i] is not None:
                    histogram.append(macd_line[i] - signal_line[i])
                else:
                    histogram.append(None)
            
            return {
                'macd': macd_line,
                'signal': signal_line,
                'histogram': histogram
            }
            
        except Exception as e:
            logger.error(f"MACD calculation failed: {e}")
            raise IndicatorCalculationError(f"MACD calculation failed: {e}")