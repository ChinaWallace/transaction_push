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
        [float(k.get('close', k.get('close_price', 0))) for k in klines]
        
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


class MovingAverageIndicator:
    """移动平均线指标计算器 - Moving Average Indicator"""
    
    def __init__(self, period: int = 20, ma_type: str = 'sma'):
        """
        初始化移动平均线指标
        Initialize Moving Average Indicator
        
        Args:
            period: 计算周期 / Calculation period
            ma_type: 移动平均类型 ('sma' 或 'ema') / MA type ('sma' or 'ema')
        """
        if period <= 0:
            raise ValueError("📊 移动平均周期必须大于0 / Period must be greater than 0")
        if ma_type not in ['sma', 'ema']:
            raise ValueError("📊 移动平均类型必须是 'sma' 或 'ema' / MA type must be 'sma' or 'ema'")
            
        self.period = period
        self.ma_type = ma_type
        logger.debug(f"🔍 初始化移动平均指标: 周期={period}, 类型={ma_type}")
    
    def calculate(self, prices: List[float]) -> List[Optional[float]]:
        """
        计算移动平均线
        Calculate moving average
        
        Args:
            prices: 价格列表 / Price list
            
        Returns:
            移动平均值列表 / Moving average values list
        """
        try:
            if not prices:
                logger.warning("⚠️ 价格数据为空")
                return []
            
            if len(prices) < self.period:
                logger.warning(f"⚠️ 数据长度不足: {len(prices)} < {self.period}")
                return [None] * len(prices)
            
            if self.ma_type == 'sma':
                return self.calculate_sma(prices)
            else:
                return self.calculate_ema(prices)
                
        except Exception as e:
            logger.error(f"❌ 移动平均计算失败: {e}")
            raise IndicatorCalculationError(f"Moving average calculation failed: {e}")
    
    def calculate_sma(self, prices: List[float]) -> List[Optional[float]]:
        """
        计算简单移动平均线 (SMA)
        Calculate Simple Moving Average
        """
        sma_values = [None] * (self.period - 1)
        
        for i in range(self.period - 1, len(prices)):
            window = prices[i - self.period + 1:i + 1]
            sma = sum(window) / len(window)
            sma_values.append(sma)
        
        logger.debug(f"🔍 SMA计算完成: {len([v for v in sma_values if v is not None])}个有效值")
        return sma_values
    
    def calculate_ema(self, prices: List[float]) -> List[Optional[float]]:
        """
        计算指数移动平均线 (EMA)
        Calculate Exponential Moving Average
        """
        ema_values = [None] * (self.period - 1)
        
        # 第一个EMA值使用SMA
        sma = sum(prices[:self.period]) / self.period
        ema_values.append(sma)
        
        # 计算后续EMA值
        multiplier = 2 / (self.period + 1)
        for i in range(self.period, len(prices)):
            ema = (prices[i] * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema)
        
        logger.debug(f"🔍 EMA计算完成: {len([v for v in ema_values if v is not None])}个有效值")
        return ema_values


class BollingerBandsIndicator:
    """布林带指标计算器 - Bollinger Bands Indicator"""
    
    def __init__(self, period: int = 20, std_dev: float = 2.0):
        """
        初始化布林带指标
        Initialize Bollinger Bands Indicator
        
        Args:
            period: 计算周期 / Calculation period
            std_dev: 标准差倍数 / Standard deviation multiplier
        """
        if period <= 0:
            raise ValueError("📊 布林带周期必须大于0 / Period must be greater than 0")
        if std_dev <= 0:
            raise ValueError("📊 标准差倍数必须大于0 / Standard deviation multiplier must be greater than 0")
            
        self.period = period
        self.std_dev = std_dev
        logger.debug(f"🔍 初始化布林带指标: 周期={period}, 标准差倍数={std_dev}")
    
    def calculate(self, prices: List[float]) -> Dict[str, List[Optional[float]]]:
        """
        计算布林带
        Calculate Bollinger Bands
        
        Args:
            prices: 价格列表 / Price list
            
        Returns:
            包含上轨、中轨、下轨的字典 / Dict with upper, middle, lower bands
        """
        try:
            if not prices:
                logger.warning("⚠️ 价格数据为空")
                return {'upper': [], 'middle': [], 'lower': []}
            
            if len(prices) < self.period:
                logger.warning(f"⚠️ 数据长度不足: {len(prices)} < {self.period}")
                null_list = [None] * len(prices)
                return {'upper': null_list, 'middle': null_list, 'lower': null_list}
            
            # 计算中轨（SMA）
            ma_indicator = MovingAverageIndicator(self.period, 'sma')
            middle_band = ma_indicator.calculate(prices)
            
            # 计算上轨和下轨
            upper_band = [None] * (self.period - 1)
            lower_band = [None] * (self.period - 1)
            
            for i in range(self.period - 1, len(prices)):
                window = prices[i - self.period + 1:i + 1]
                
                # 计算标准差
                mean = sum(window) / len(window)
                variance = sum((x - mean) ** 2 for x in window) / len(window)
                std = variance ** 0.5
                
                # 计算上下轨
                upper_band.append(middle_band[i] + (self.std_dev * std))
                lower_band.append(middle_band[i] - (self.std_dev * std))
            
            logger.info(f"✅ 布林带计算完成: {len([v for v in middle_band if v is not None])}个有效值")
            
            return {
                'upper': upper_band,
                'middle': middle_band,
                'lower': lower_band
            }
            
        except Exception as e:
            logger.error(f"❌ 布林带计算失败: {e}")
            raise IndicatorCalculationError(f"Bollinger Bands calculation failed: {e}")


class StochasticIndicator:
    """随机指标计算器 - Stochastic Oscillator"""
    
    def __init__(self, k_period: int = 14, d_period: int = 3, smooth_k: int = 3):
        """
        初始化随机指标
        Initialize Stochastic Oscillator
        
        Args:
            k_period: %K计算周期 / %K calculation period
            d_period: %D平滑周期 / %D smoothing period  
            smooth_k: %K平滑周期 / %K smoothing period
        """
        if k_period <= 0 or d_period <= 0 or smooth_k <= 0:
            raise ValueError("📊 所有周期参数必须大于0 / All period parameters must be greater than 0")
            
        self.k_period = k_period
        self.d_period = d_period
        self.smooth_k = smooth_k
        logger.debug(f"🔍 初始化随机指标: K周期={k_period}, D周期={d_period}, K平滑={smooth_k}")
    
    def calculate(self, high: List[float], low: List[float], close: List[float]) -> Dict[str, List[Optional[float]]]:
        """
        计算随机指标
        Calculate Stochastic Oscillator
        
        Args:
            high: 最高价列表 / High prices list
            low: 最低价列表 / Low prices list
            close: 收盘价列表 / Close prices list
            
        Returns:
            包含%K和%D的字典 / Dict with %K and %D values
        """
        try:
            if len(high) != len(low) or len(low) != len(close):
                raise ValueError("❌ OHLC数据长度不一致 / OHLC data length mismatch")
            
            if not high or len(high) < self.k_period:
                logger.warning(f"⚠️ 数据长度不足: {len(high) if high else 0} < {self.k_period}")
                null_list = [None] * len(high) if high else []
                return {'%K': null_list, '%D': null_list}
            
            # 计算原始%K值
            raw_k = [None] * (self.k_period - 1)
            
            for i in range(self.k_period - 1, len(close)):
                # 获取周期内的最高价和最低价
                period_high = max(high[i - self.k_period + 1:i + 1])
                period_low = min(low[i - self.k_period + 1:i + 1])
                
                # 计算%K
                if period_high != period_low:
                    k_value = ((close[i] - period_low) / (period_high - period_low)) * 100
                else:
                    k_value = 50  # 当最高价等于最低价时，设为中性值
                
                raw_k.append(k_value)
            
            # 平滑%K值
            if self.smooth_k > 1:
                k_values = [None] * (len(raw_k) - len([v for v in raw_k if v is not None]) + self.smooth_k - 1)
                
                valid_k_start = next(i for i, v in enumerate(raw_k) if v is not None)
                for i in range(valid_k_start + self.smooth_k - 1, len(raw_k)):
                    window = [raw_k[j] for j in range(i - self.smooth_k + 1, i + 1) if raw_k[j] is not None]
                    if len(window) == self.smooth_k:
                        k_values.append(sum(window) / len(window))
                    else:
                        k_values.append(None)
                
                # 补齐长度
                while len(k_values) < len(raw_k):
                    k_values.append(None)
            else:
                k_values = raw_k
            
            # 计算%D值（%K的移动平均）
            d_values = [None] * len(k_values)
            
            valid_k_indices = [i for i, v in enumerate(k_values) if v is not None]
            if len(valid_k_indices) >= self.d_period:
                for i in range(valid_k_indices[self.d_period - 1], len(k_values)):
                    window = [k_values[j] for j in range(i - self.d_period + 1, i + 1) if k_values[j] is not None]
                    if len(window) == self.d_period:
                        d_values[i] = sum(window) / len(window)
            
            logger.info(f"✅ 随机指标计算完成: %K有{len([v for v in k_values if v is not None])}个有效值")
            
            return {
                '%K': k_values,
                '%D': d_values
            }
            
        except Exception as e:
            logger.error(f"❌ 随机指标计算失败: {e}")
            raise IndicatorCalculationError(f"Stochastic calculation failed: {e}")


class WilliamsRIndicator:
    """威廉指标计算器 - Williams %R Indicator"""
    
    def __init__(self, period: int = 14):
        """
        初始化威廉指标
        Initialize Williams %R Indicator
        
        Args:
            period: 计算周期 / Calculation period
        """
        if period <= 0:
            raise ValueError("📊 威廉指标周期必须大于0 / Period must be greater than 0")
            
        self.period = period
        logger.debug(f"🔍 初始化威廉指标: 周期={period}")
    
    def calculate(self, high: List[float], low: List[float], close: List[float]) -> List[Optional[float]]:
        """
        计算威廉指标 %R
        Calculate Williams %R
        
        Args:
            high: 最高价列表 / High prices list
            low: 最低价列表 / Low prices list
            close: 收盘价列表 / Close prices list
            
        Returns:
            威廉指标值列表 / Williams %R values list
        """
        try:
            if len(high) != len(low) or len(low) != len(close):
                raise ValueError("❌ OHLC数据长度不一致 / OHLC data length mismatch")
            
            if not high or len(high) < self.period:
                logger.warning(f"⚠️ 数据长度不足: {len(high) if high else 0} < {self.period}")
                return [None] * len(high) if high else []
            
            williams_r = [None] * (self.period - 1)
            
            for i in range(self.period - 1, len(close)):
                # 获取周期内的最高价和最低价
                period_high = max(high[i - self.period + 1:i + 1])
                period_low = min(low[i - self.period + 1:i + 1])
                
                # 计算Williams %R
                if period_high != period_low:
                    wr_value = ((period_high - close[i]) / (period_high - period_low)) * -100
                else:
                    wr_value = -50  # 当最高价等于最低价时，设为中性值
                
                williams_r.append(wr_value)
            
            logger.info(f"✅ 威廉指标计算完成: {len([v for v in williams_r if v is not None])}个有效值")
            return williams_r
            
        except Exception as e:
            logger.error(f"❌ 威廉指标计算失败: {e}")
            raise IndicatorCalculationError(f"Williams %R calculation failed: {e}")


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


class IndicatorFactory:
    """指标工厂类 - Indicator Factory for centralized indicator creation"""
    
    @staticmethod
    def create_indicator(indicator_type: str, **kwargs) -> Any:
        """
        创建指标实例
        Create indicator instance
        
        Args:
            indicator_type: 指标类型 / Indicator type
            **kwargs: 指标参数 / Indicator parameters
            
        Returns:
            指标实例 / Indicator instance
        """
        try:
            indicator_map = {
                'ma': MovingAverageIndicator,
                'moving_average': MovingAverageIndicator,
                'bollinger': BollingerBandsIndicator,
                'bollinger_bands': BollingerBandsIndicator,
                'stochastic': StochasticIndicator,
                'stoch': StochasticIndicator,
                'williams_r': WilliamsRIndicator,
                'williams': WilliamsRIndicator,
                'wr': WilliamsRIndicator,
                'macd': MACDIndicator,
                'rsi': RSIIndicator,
                'supertrend': SuperTrendIndicator,
                'volume': VolumeIndicator
            }
            
            indicator_type_lower = indicator_type.lower()
            
            if indicator_type_lower not in indicator_map:
                available_types = ', '.join(indicator_map.keys())
                raise ValueError(f"❌ 不支持的指标类型: {indicator_type}. 可用类型: {available_types}")
            
            indicator_class = indicator_map[indicator_type_lower]
            
            # 对于静态方法类（如VolumeIndicator），直接返回类
            if indicator_type_lower == 'volume':
                logger.info(f"✅ 创建成交量指标实例")
                return indicator_class
            
            # 创建指标实例
            indicator = indicator_class(**kwargs)
            logger.info(f"✅ 创建{indicator_type}指标实例: {kwargs}")
            
            return indicator
            
        except Exception as e:
            logger.error(f"❌ 指标创建失败: {indicator_type} - {e}")
            raise IndicatorCalculationError(f"Indicator creation failed: {e}")
    
    @staticmethod
    def get_available_indicators() -> List[str]:
        """
        获取可用指标列表
        Get available indicators list
        
        Returns:
            可用指标类型列表 / Available indicator types list
        """
        return [
            'ma', 'moving_average',
            'bollinger', 'bollinger_bands', 
            'stochastic', 'stoch',
            'williams_r', 'williams', 'wr',
            'macd', 'rsi', 'supertrend', 'volume'
        ]
    
    @staticmethod
    def get_indicator_info(indicator_type: str) -> Dict[str, Any]:
        """
        获取指标信息
        Get indicator information
        
        Args:
            indicator_type: 指标类型 / Indicator type
            
        Returns:
            指标信息字典 / Indicator information dict
        """
        info_map = {
            'ma': {
                'name': '移动平均线 / Moving Average',
                'description': '计算简单移动平均(SMA)或指数移动平均(EMA)',
                'parameters': {'period': 'int', 'ma_type': 'str (sma/ema)'}
            },
            'bollinger': {
                'name': '布林带 / Bollinger Bands', 
                'description': '基于移动平均和标准差的统计指标',
                'parameters': {'period': 'int', 'std_dev': 'float'}
            },
            'stochastic': {
                'name': '随机指标 / Stochastic Oscillator',
                'description': '动量震荡指标，显示价格相对于一定周期内价格范围的位置',
                'parameters': {'k_period': 'int', 'd_period': 'int', 'smooth_k': 'int'}
            },
            'williams_r': {
                'name': '威廉指标 / Williams %R',
                'description': '动量指标，衡量收盘价在一定周期内价格范围中的位置',
                'parameters': {'period': 'int'}
            },
            'macd': {
                'name': 'MACD指标 / MACD',
                'description': '趋势跟踪动量指标',
                'parameters': {'fast_period': 'int', 'slow_period': 'int', 'signal_period': 'int'}
            },
            'rsi': {
                'name': 'RSI指标 / RSI',
                'description': '相对强弱指标，衡量价格变动的速度和变化',
                'parameters': {'period': 'int'}
            },
            'supertrend': {
                'name': 'SuperTrend指标 / SuperTrend',
                'description': '趋势跟踪指标，基于ATR计算',
                'parameters': {'period': 'int', 'multiplier': 'float'}
            },
            'volume': {
                'name': '成交量指标 / Volume Indicators',
                'description': '成交量相关分析指标',
                'parameters': {'periods': 'int', 'threshold_multiplier': 'float'}
            }
        }
        
        indicator_type_lower = indicator_type.lower()
        # 处理别名
        alias_map = {
            'moving_average': 'ma',
            'bollinger_bands': 'bollinger',
            'stoch': 'stochastic', 
            'williams': 'williams_r',
            'wr': 'williams_r'
        }
        
        if indicator_type_lower in alias_map:
            indicator_type_lower = alias_map[indicator_type_lower]
        
        return info_map.get(indicator_type_lower, {
            'name': f'未知指标 / Unknown Indicator: {indicator_type}',
            'description': '指标信息不可用',
            'parameters': {}
        })