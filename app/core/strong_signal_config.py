# -*- coding: utf-8 -*-
"""
强信号立即推送配置
优化交易机会的实时通知机制
"""

from datetime import timedelta
from typing import Dict, Any
from enum import Enum


class SignalUrgency(Enum):
    """信号紧急程度"""
    IMMEDIATE = "immediate"      # 立即推送
    HIGH = "high"               # 高优先级
    MEDIUM = "medium"           # 中等优先级
    LOW = "low"                 # 低优先级


class StrongSignalConfig:
    """强信号配置类"""
    
    # 强信号识别阈值
    SIGNAL_THRESHOLDS = {
        'kronos_very_strong': 0.75,     # Kronos极强信号
        'kronos_strong': 0.55,          # Kronos强信号
        'supertrend_strong': 0.70,      # SuperTrend强信号
        'combined_strong': 0.65,        # 综合强信号
        'volume_spike': 3.0,            # 成交量异常倍数
        'price_breakout': 0.02,         # 价格突破幅度(2%)
    }
    
    # 通知间隔配置（分级推送）
    NOTIFICATION_INTERVALS = {
        SignalUrgency.IMMEDIATE: timedelta(seconds=0),    # 立即推送
        SignalUrgency.HIGH: timedelta(minutes=5),         # 5分钟间隔
        SignalUrgency.MEDIUM: timedelta(minutes=15),      # 15分钟间隔
        SignalUrgency.LOW: timedelta(minutes=30),         # 30分钟间隔
    }
    
    # 信号优先级映射
    SIGNAL_PRIORITY_MAP = {
        # Kronos信号优先级
        'kronos_very_strong_buy': SignalUrgency.IMMEDIATE,
        'kronos_very_strong_sell': SignalUrgency.IMMEDIATE,
        'kronos_strong_buy': SignalUrgency.HIGH,
        'kronos_strong_sell': SignalUrgency.HIGH,
        
        # SuperTrend信号优先级
        'supertrend_strong_bullish': SignalUrgency.HIGH,
        'supertrend_strong_bearish': SignalUrgency.HIGH,
        
        # 综合信号优先级
        'multi_timeframe_consensus': SignalUrgency.IMMEDIATE,
        'volume_price_breakout': SignalUrgency.HIGH,
        
        # 特殊情况
        'market_anomaly': SignalUrgency.IMMEDIATE,
        'funding_rate_extreme': SignalUrgency.HIGH,
    }
    
    # 立即推送条件
    IMMEDIATE_PUSH_CONDITIONS = {
        'kronos_confidence_threshold': 0.75,        # Kronos置信度超过75%
        'supertrend_all_timeframes_aligned': True,  # 所有周期SuperTrend一致
        'volume_spike_with_breakout': True,         # 成交量异常+价格突破
        'funding_rate_extreme': True,               # 极端资金费率
        'market_structure_change': True,            # 市场结构变化
    }
    
    # 通知渠道优先级
    NOTIFICATION_CHANNELS = {
        SignalUrgency.IMMEDIATE: ['feishu', 'wechat', 'telegram'],  # 多渠道推送
        SignalUrgency.HIGH: ['feishu', 'wechat'],                   # 双渠道推送
        SignalUrgency.MEDIUM: ['feishu'],                           # 单渠道推送
        SignalUrgency.LOW: ['feishu'],                              # 单渠道推送
    }
    
    @classmethod
    def get_signal_urgency(cls, signal_type: str, confidence: float, **kwargs) -> SignalUrgency:
        """
        根据信号类型和置信度确定紧急程度
        
        Args:
            signal_type: 信号类型
            confidence: 置信度
            **kwargs: 其他参数
            
        Returns:
            SignalUrgency: 信号紧急程度
        """
        # 检查是否满足立即推送条件
        if cls._should_push_immediately(signal_type, confidence, **kwargs):
            return SignalUrgency.IMMEDIATE
        
        # 根据信号类型映射
        if signal_type in cls.SIGNAL_PRIORITY_MAP:
            return cls.SIGNAL_PRIORITY_MAP[signal_type]
        
        # 根据置信度判断
        if confidence >= cls.SIGNAL_THRESHOLDS['kronos_very_strong']:
            return SignalUrgency.IMMEDIATE
        elif confidence >= cls.SIGNAL_THRESHOLDS['kronos_strong']:
            return SignalUrgency.HIGH
        elif confidence >= 0.5:
            return SignalUrgency.MEDIUM
        else:
            return SignalUrgency.LOW
    
    @classmethod
    def _should_push_immediately(cls, signal_type: str, confidence: float, **kwargs) -> bool:
        """判断是否应该立即推送"""
        
        # Kronos极强信号
        if confidence >= cls.IMMEDIATE_PUSH_CONDITIONS['kronos_confidence_threshold']:
            return True
        
        # 多周期一致性
        if kwargs.get('all_timeframes_aligned', False):
            return True
        
        # 成交量异常+价格突破
        volume_ratio = kwargs.get('volume_ratio', 1.0)
        price_change = kwargs.get('price_change_abs', 0.0)
        if (volume_ratio >= cls.SIGNAL_THRESHOLDS['volume_spike'] and 
            abs(price_change) >= cls.SIGNAL_THRESHOLDS['price_breakout']):
            return True
        
        # 极端资金费率
        funding_rate = kwargs.get('funding_rate', 0.0)
        if abs(funding_rate) >= 0.01:  # 1%的极端费率
            return True
        
        return False
    
    @classmethod
    def get_notification_config(cls, urgency: SignalUrgency) -> Dict[str, Any]:
        """
        获取通知配置
        
        Args:
            urgency: 信号紧急程度
            
        Returns:
            Dict: 通知配置
        """
        return {
            'interval': cls.NOTIFICATION_INTERVALS[urgency],
            'channels': cls.NOTIFICATION_CHANNELS[urgency],
            'priority': urgency.value,
            'retry_count': 3 if urgency == SignalUrgency.IMMEDIATE else 1,
            'timeout': 10 if urgency == SignalUrgency.IMMEDIATE else 30,
        }


# 全局配置实例
strong_signal_config = StrongSignalConfig()