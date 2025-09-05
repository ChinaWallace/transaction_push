# -*- coding: utf-8 -*-
"""
SuperTrend多周期策略
Multi-timeframe SuperTrend strategy
"""

import pandas as pd
from typing import List, Dict, Any
from datetime import datetime

from .base_strategy import BaseStrategy, SignalType, SignalStrength, StrategySignal
from app.utils.indicators import SuperTrendIndicator
from app.core.logging import get_logger

logger = get_logger(__name__)


class SuperTrendStrategy(BaseStrategy):
    """
    SuperTrend多周期策略
    基于原有的10种信号组合逻辑
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        default_config = {
            'period': 10,
            'multiplier': 3.0,
            'timeframes': ['1d', '4h', '1h', '15m'],
            'min_data_points': 50
        }
        
        if config:
            default_config.update(config)
            
        super().__init__('SuperTrend', default_config)
        
        # 初始化指标计算器
        self.supertrend = SuperTrendIndicator(
            period=self.config['period'],
            multiplier=self.config['multiplier']
        )
        
        # 信号组合映射（保持原有逻辑）
        self.signal_combinations = {
            (True, True, True, True): ('强势多头共振', SignalType.STRONG_BUY, SignalStrength.VERY_STRONG),
            (True, True, True, False): ('回调中多头', SignalType.BUY, SignalStrength.MEDIUM),
            (True, True, False, True): ('短线反弹', SignalType.BUY, SignalStrength.MEDIUM),
            (True, False, True, True): ('背离多头', SignalType.BUY, SignalStrength.MEDIUM),
            (False, False, False, False): ('强势空头共振', SignalType.STRONG_SELL, SignalStrength.VERY_STRONG),
            (False, False, False, True): ('短线反弹', SignalType.SELL, SignalStrength.MEDIUM),
            (False, False, True, True): ('反转尝试', SignalType.BUY, SignalStrength.WEAK),
            (False, True, True, True): ('底部反转', SignalType.BUY, SignalStrength.MEDIUM),
            (True, True, False, False): ('回调确认', SignalType.HOLD, SignalStrength.WEAK),
        }
    
    def get_required_params(self) -> List[str]:
        """获取必需参数"""
        return ['period', 'multiplier']
    
    def populate_indicators(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """填充SuperTrend指标"""
        try:
            if len(dataframe) < self.config['min_data_points']:
                return dataframe
            
            # 计算SuperTrend
            high = dataframe['high'].values
            low = dataframe['low'].values  
            close = dataframe['close'].values
            
            supertrend_values, trend_directions = self.supertrend.calculate(
                high.tolist(), low.tolist(), close.tolist()
            )
            
            # 添加到数据框
            dataframe['supertrend'] = supertrend_values
            dataframe['supertrend_direction'] = trend_directions
            
            # 计算趋势变化
            dataframe['trend_change'] = dataframe['supertrend_direction'].diff() != 0
            
            return dataframe
            
        except Exception as e:
            logger.error(f"SuperTrend indicator calculation failed: {e}")
            return dataframe
    
    def populate_entry_trend(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """填充入场信号"""
        # 基于SuperTrend方向判断入场
        dataframe['enter_long'] = (
            (dataframe['supertrend_direction'] == True) &
            (dataframe['supertrend_direction'].shift(1) == False)
        )
        
        dataframe['enter_short'] = (
            (dataframe['supertrend_direction'] == False) &
            (dataframe['supertrend_direction'].shift(1) == True)
        )
        
        return dataframe
    
    def populate_exit_trend(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """填充出场信号"""
        # SuperTrend反向时出场
        dataframe['exit_long'] = (
            (dataframe['supertrend_direction'] == False) &
            (dataframe['supertrend_direction'].shift(1) == True)
        )
        
        dataframe['exit_short'] = (
            (dataframe['supertrend_direction'] == True) &
            (dataframe['supertrend_direction'].shift(1) == False)
        )
        
        return dataframe
    
    def analyze_multi_timeframe(self, timeframe_data: Dict[str, pd.DataFrame]) -> StrategySignal:
        """
        多周期分析
        
        Args:
            timeframe_data: 各周期的OHLCV数据
            
        Returns:
            综合策略信号
        """
        try:
            # 分析各周期趋势
            trends = {}
            
            for timeframe in ['1d', '4h', '1h', '15m']:
                if timeframe in timeframe_data:
                    df = timeframe_data[timeframe].copy()
                    df = self.populate_indicators(df)
                    
                    if len(df) > 0 and not df['supertrend_direction'].empty:
                        latest_trend = df['supertrend_direction'].iloc[-1]
                        trends[timeframe] = bool(latest_trend) if pd.notna(latest_trend) else None
                    else:
                        trends[timeframe] = None
            
            # 构建趋势组合
            trend_tuple = (
                trends.get('1d'),
                trends.get('4h'), 
                trends.get('1h'),
                trends.get('15m')
            )
            
            # 获取信号组合
            signal_info = self.signal_combinations.get(trend_tuple)
            
            if signal_info:
                signal_name, signal_type, strength = signal_info
                confidence = self._calculate_multi_timeframe_confidence(trends)
            else:
                signal_name = '信号混乱'
                signal_type = SignalType.HOLD
                strength = SignalStrength.VERY_WEAK
                confidence = 0.3
            
            # 获取当前价格
            current_price = 0.0
            if '15m' in timeframe_data and len(timeframe_data['15m']) > 0:
                current_price = float(timeframe_data['15m']['close'].iloc[-1])
            
            # 构建元数据
            metadata = {
                'strategy': self.name,
                'signal_name': signal_name,
                'trends': {
                    'daily': trends.get('1d'),
                    'h4': trends.get('4h'),
                    'h1': trends.get('1h'),
                    'm15': trends.get('15m')
                },
                'trend_combination': trend_tuple,
                'config': self.config
            }
            
            return StrategySignal(
                signal_type=signal_type,
                strength=strength,
                confidence=confidence,
                price=current_price,
                timestamp=datetime.now(),
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Multi-timeframe analysis failed: {e}")
            raise
    
    def _calculate_multi_timeframe_confidence(self, trends: Dict[str, bool]) -> float:
        """计算多周期置信度"""
        # 统计明确趋势的数量
        clear_trends = sum(1 for trend in trends.values() if trend is not None)
        total_trends = len(trends)
        
        if total_trends == 0:
            return 0.0
        
        # 基础置信度
        base_confidence = clear_trends / total_trends
        
        # 趋势一致性加成
        if clear_trends >= 2:
            trend_values = [t for t in trends.values() if t is not None]
            if len(set(trend_values)) == 1:  # 所有明确趋势都一致
                base_confidence *= 1.2
        
        return min(base_confidence, 1.0)
    
    def format_signal_message(self, signal: StrategySignal) -> str:
        """格式化信号消息"""
        trends = signal.metadata.get('trends', {})
        signal_name = signal.metadata.get('signal_name', '未知信号')
        
        # 趋势图标
        trend_icons = {True: '↑', False: '↓', None: '/'}
        
        # 信号级别图标
        level_icons = {
            SignalStrength.VERY_STRONG: '🔵',
            SignalStrength.STRONG: '🟡',
            SignalStrength.MEDIUM: '🟠', 
            SignalStrength.WEAK: '⚪',
            SignalStrength.VERY_WEAK: '⚫'
        }
        
        message = f"""📊 【SuperTrend策略信号】

🕐 多周期趋势：
├ 日线：{trend_icons.get(trends.get('daily'), '/')} 
├ 4小时：{trend_icons.get(trends.get('h4'), '/')}
├ 1小时：{trend_icons.get(trends.get('h1'), '/')}
└ 15分钟：{trend_icons.get(trends.get('m15'), '/')}

{level_icons.get(signal.strength, '⚪')} {signal_name}

📈 信号类型：{signal.signal_type.value.upper()}
💪 信号强度：{signal.strength.name}
📊 置信度：{signal.confidence:.2%}
💰 当前价格：{signal.price}

⏰ 分析时间：{signal.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        return message