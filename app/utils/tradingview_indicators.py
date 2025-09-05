# -*- coding: utf-8 -*-
"""
TradingView风格的技术指标库
TradingView-style technical indicators library
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any

from app.core.logging import get_logger
from app.utils.exceptions import IndicatorCalculationError

logger = get_logger(__name__)


class TradingViewIndicators:
    """TradingView风格的指标计算器"""
    
    @staticmethod
    def pine_sma(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的简单移动平均"""
        return source.rolling(window=length).mean()
    
    @staticmethod
    def pine_ema(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的指数移动平均"""
        return source.ewm(span=length).mean()
    
    @staticmethod
    def pine_rma(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的修正移动平均（RMA）"""
        alpha = 1.0 / length
        return source.ewm(alpha=alpha, adjust=False).mean()
    
    @staticmethod
    def pine_highest(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的最高值"""
        return source.rolling(window=length).max()
    
    @staticmethod
    def pine_lowest(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的最低值"""
        return source.rolling(window=length).min()
    
    @staticmethod
    def pine_stdev(source: pd.Series, length: int) -> pd.Series:
        """Pine Script风格的标准差"""
        return source.rolling(window=length).std()
    
    @staticmethod
    def pine_change(source: pd.Series, length: int = 1) -> pd.Series:
        """Pine Script风格的变化值"""
        return source.diff(length)
    
    @staticmethod
    def pine_cross(series1: pd.Series, series2: pd.Series) -> pd.Series:
        """Pine Script风格的交叉检测"""
        return (series1 > series2) & (series1.shift(1) <= series2.shift(1))
    
    @staticmethod
    def pine_crossover(series1: pd.Series, series2: pd.Series) -> pd.Series:
        """Pine Script风格的向上交叉"""
        return TradingViewIndicators.pine_cross(series1, series2)
    
    @staticmethod
    def pine_crossunder(series1: pd.Series, series2: pd.Series) -> pd.Series:
        """Pine Script风格的向下交叉"""
        return TradingViewIndicators.pine_cross(series2, series1)


class EnhancedSuperTrend:
    """增强版SuperTrend指标（TradingView风格）"""
    
    def __init__(self, atr_period: int = 10, factor: float = 3.0):
        self.atr_period = atr_period
        self.factor = factor
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算SuperTrend指标
        
        Args:
            df: 包含OHLC数据的DataFrame
            
        Returns:
            包含SuperTrend指标的DataFrame
        """
        try:
            result_df = df.copy()
            
            # 计算ATR
            high = df['high']
            low = df['low']
            close = df['close']
            
            # 使用TradingView风格的ATR计算
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = TradingViewIndicators.pine_rma(true_range, self.atr_period)
            
            # 计算基础上下轨
            hl2 = (high + low) / 2
            upper_basic = hl2 + (self.factor * atr)
            lower_basic = hl2 - (self.factor * atr)
            
            # 计算最终上下轨
            upper_final = pd.Series(index=df.index, dtype=float)
            lower_final = pd.Series(index=df.index, dtype=float)
            
            for i in range(len(df)):
                if i == 0:
                    upper_final.iloc[i] = upper_basic.iloc[i]
                    lower_final.iloc[i] = lower_basic.iloc[i]
                else:
                    # 上轨计算
                    if (upper_basic.iloc[i] < upper_final.iloc[i-1] or 
                        close.iloc[i-1] > upper_final.iloc[i-1]):
                        upper_final.iloc[i] = upper_basic.iloc[i]
                    else:
                        upper_final.iloc[i] = upper_final.iloc[i-1]
                    
                    # 下轨计算
                    if (lower_basic.iloc[i] > lower_final.iloc[i-1] or 
                        close.iloc[i-1] < lower_final.iloc[i-1]):
                        lower_final.iloc[i] = lower_basic.iloc[i]
                    else:
                        lower_final.iloc[i] = lower_final.iloc[i-1]
            
            # 计算SuperTrend
            supertrend = pd.Series(index=df.index, dtype=float)
            direction = pd.Series(index=df.index, dtype=bool)
            
            for i in range(len(df)):
                if i == 0:
                    if close.iloc[i] <= lower_final.iloc[i]:
                        supertrend.iloc[i] = lower_final.iloc[i]
                        direction.iloc[i] = True
                    else:
                        supertrend.iloc[i] = upper_final.iloc[i]
                        direction.iloc[i] = False
                else:
                    if ((direction.iloc[i-1] and close.iloc[i] > lower_final.iloc[i]) or
                        (not direction.iloc[i-1] and close.iloc[i] > upper_final.iloc[i])):
                        supertrend.iloc[i] = lower_final.iloc[i]
                        direction.iloc[i] = True
                    else:
                        supertrend.iloc[i] = upper_final.iloc[i]
                        direction.iloc[i] = False
            
            # 添加到结果DataFrame
            result_df['atr'] = atr
            result_df['supertrend_upper'] = upper_final
            result_df['supertrend_lower'] = lower_final
            result_df['supertrend'] = supertrend
            result_df['supertrend_direction'] = direction
            
            # 趋势变化信号
            result_df['trend_change'] = direction != direction.shift(1)
            result_df['bullish_signal'] = direction & (direction != direction.shift(1))
            result_df['bearish_signal'] = ~direction & (direction != direction.shift(1))
            
            return result_df
            
        except Exception as e:
            logger.error(f"Enhanced SuperTrend calculation failed: {e}")
            raise IndicatorCalculationError(f"SuperTrend calculation failed: {e}")


class VolumeProfileIndicator:
    """成交量分布指标（类似TradingView的Volume Profile）"""
    
    def __init__(self, num_bins: int = 20):
        self.num_bins = num_bins
    
    def calculate(self, df: pd.DataFrame, lookback_periods: int = 100) -> Dict[str, Any]:
        """
        计算成交量分布
        
        Args:
            df: OHLCV数据
            lookback_periods: 回看周期
            
        Returns:
            成交量分布数据
        """
        try:
            if len(df) < lookback_periods:
                lookback_periods = len(df)
            
            # 获取最近的数据
            recent_df = df.tail(lookback_periods)
            
            # 价格范围
            price_min = recent_df['low'].min()
            price_max = recent_df['high'].max()
            
            # 创建价格区间
            price_bins = np.linspace(price_min, price_max, self.num_bins + 1)
            
            # 计算每个区间的成交量
            volume_profile = []
            
            for i in range(len(price_bins) - 1):
                bin_low = price_bins[i]
                bin_high = price_bins[i + 1]
                bin_mid = (bin_low + bin_high) / 2
                
                # 计算在此价格区间内的成交量
                mask = (
                    (recent_df['low'] <= bin_high) & 
                    (recent_df['high'] >= bin_low)
                )
                
                bin_volume = recent_df.loc[mask, 'volume'].sum()
                
                volume_profile.append({
                    'price_low': bin_low,
                    'price_high': bin_high,
                    'price_mid': bin_mid,
                    'volume': float(bin_volume),
                    'percentage': 0.0  # 稍后计算
                })
            
            # 计算百分比
            total_volume = sum(vp['volume'] for vp in volume_profile)
            if total_volume > 0:
                for vp in volume_profile:
                    vp['percentage'] = vp['volume'] / total_volume * 100
            
            # 找到成交量最大的价格区间（POC - Point of Control）
            poc = max(volume_profile, key=lambda x: x['volume'])
            
            # 计算价值区域（Value Area）- 包含70%成交量的区域
            sorted_profile = sorted(volume_profile, key=lambda x: x['volume'], reverse=True)
            cumulative_volume = 0
            value_area_bins = []
            
            for vp in sorted_profile:
                cumulative_volume += vp['volume']
                value_area_bins.append(vp)
                if cumulative_volume >= total_volume * 0.7:
                    break
            
            # 价值区域的价格范围
            if value_area_bins:
                va_high = max(vp['price_high'] for vp in value_area_bins)
                va_low = min(vp['price_low'] for vp in value_area_bins)
            else:
                va_high = price_max
                va_low = price_min
            
            return {
                'volume_profile': volume_profile,
                'poc_price': poc['price_mid'],
                'poc_volume': poc['volume'],
                'value_area_high': va_high,
                'value_area_low': va_low,
                'total_volume': total_volume,
                'price_range': {
                    'high': price_max,
                    'low': price_min
                }
            }
            
        except Exception as e:
            logger.error(f"Volume Profile calculation failed: {e}")
            raise IndicatorCalculationError(f"Volume Profile calculation failed: {e}")


class OrderFlowIndicator:
    """订单流指标（模拟TradingView的Order Flow）"""
    
    @staticmethod
    def calculate_delta(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算Delta（买卖压力差）
        
        Args:
            df: 包含OHLCV数据的DataFrame
            
        Returns:
            包含Delta指标的DataFrame
        """
        try:
            result_df = df.copy()
            
            # 简化的Delta计算（基于价格变化和成交量）
            price_change = df['close'] - df['open']
            
            # 估算买入和卖出成交量
            buy_volume = np.where(price_change > 0, df['volume'], 0)
            sell_volume = np.where(price_change < 0, df['volume'], 0)
            neutral_volume = np.where(price_change == 0, df['volume'], 0)
            
            # 对于中性价格变化，按照前一根K线的趋势分配
            for i in range(1, len(df)):
                if price_change.iloc[i] == 0:
                    if price_change.iloc[i-1] > 0:
                        buy_volume[i] = df['volume'].iloc[i] * 0.6
                        sell_volume[i] = df['volume'].iloc[i] * 0.4
                    elif price_change.iloc[i-1] < 0:
                        buy_volume[i] = df['volume'].iloc[i] * 0.4
                        sell_volume[i] = df['volume'].iloc[i] * 0.6
                    else:
                        buy_volume[i] = df['volume'].iloc[i] * 0.5
                        sell_volume[i] = df['volume'].iloc[i] * 0.5
            
            # 计算Delta
            delta = buy_volume - sell_volume
            
            # 累积Delta
            cumulative_delta = np.cumsum(delta)
            
            # Delta移动平均
            delta_ma = pd.Series(delta).rolling(window=20).mean()
            
            result_df['buy_volume'] = buy_volume
            result_df['sell_volume'] = sell_volume
            result_df['delta'] = delta
            result_df['cumulative_delta'] = cumulative_delta
            result_df['delta_ma'] = delta_ma
            
            # Delta背离检测
            price_ma = df['close'].rolling(window=20).mean()
            result_df['delta_divergence'] = (
                ((df['close'] > price_ma) & (delta < delta_ma)) |
                ((df['close'] < price_ma) & (delta > delta_ma))
            )
            
            return result_df
            
        except Exception as e:
            logger.error(f"Order Flow Delta calculation failed: {e}")
            raise IndicatorCalculationError(f"Delta calculation failed: {e}")


class MarketStructureIndicator:
    """市场结构指标（支撑阻力、趋势线等）"""
    
    @staticmethod
    def find_swing_points(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
        """
        寻找摆动高低点
        
        Args:
            df: OHLC数据
            window: 检测窗口
            
        Returns:
            包含摆动点的DataFrame
        """
        try:
            result_df = df.copy()
            
            # 寻找摆动高点
            swing_highs = []
            swing_lows = []
            
            for i in range(window, len(df) - window):
                # 检查是否为摆动高点
                is_swing_high = True
                current_high = df['high'].iloc[i]
                
                for j in range(i - window, i + window + 1):
                    if j != i and df['high'].iloc[j] >= current_high:
                        is_swing_high = False
                        break
                
                if is_swing_high:
                    swing_highs.append(i)
                
                # 检查是否为摆动低点
                is_swing_low = True
                current_low = df['low'].iloc[i]
                
                for j in range(i - window, i + window + 1):
                    if j != i and df['low'].iloc[j] <= current_low:
                        is_swing_low = False
                        break
                
                if is_swing_low:
                    swing_lows.append(i)
            
            # 标记摆动点
            result_df['swing_high'] = False
            result_df['swing_low'] = False
            
            result_df.loc[swing_highs, 'swing_high'] = True
            result_df.loc[swing_lows, 'swing_low'] = True
            
            return result_df
            
        except Exception as e:
            logger.error(f"Swing points calculation failed: {e}")
            raise IndicatorCalculationError(f"Swing points calculation failed: {e}")
    
    @staticmethod
    def calculate_support_resistance(df: pd.DataFrame, min_touches: int = 2) -> Dict[str, List[float]]:
        """
        计算支撑阻力位
        
        Args:
            df: 包含摆动点的OHLC数据
            min_touches: 最小触及次数
            
        Returns:
            支撑阻力位字典
        """
        try:
            # 获取摆动点
            swing_df = MarketStructureIndicator.find_swing_points(df)
            
            # 提取摆动高点和低点的价格
            swing_high_prices = swing_df.loc[swing_df['swing_high'], 'high'].tolist()
            swing_low_prices = swing_df.loc[swing_df['swing_low'], 'low'].tolist()
            
            # 合并所有关键价格
            all_prices = swing_high_prices + swing_low_prices
            
            if not all_prices:
                return {'support': [], 'resistance': []}
            
            # 价格聚类（寻找相近的价格水平）
            price_tolerance = (max(all_prices) - min(all_prices)) * 0.01  # 1%容差
            
            support_levels = []
            resistance_levels = []
            
            # 简化的聚类算法
            processed_prices = set()
            
            for price in sorted(all_prices):
                if price in processed_prices:
                    continue
                
                # 找到相近的价格
                cluster = [p for p in all_prices if abs(p - price) <= price_tolerance]
                
                if len(cluster) >= min_touches:
                    avg_price = sum(cluster) / len(cluster)
                    
                    # 判断是支撑还是阻力
                    current_price = df['close'].iloc[-1]
                    if avg_price < current_price:
                        support_levels.append(avg_price)
                    else:
                        resistance_levels.append(avg_price)
                
                processed_prices.update(cluster)
            
            return {
                'support': sorted(support_levels, reverse=True)[:5],  # 最近的5个支撑位
                'resistance': sorted(resistance_levels)[:5]  # 最近的5个阻力位
            }
            
        except Exception as e:
            logger.error(f"Support/Resistance calculation failed: {e}")
            return {'support': [], 'resistance': []}