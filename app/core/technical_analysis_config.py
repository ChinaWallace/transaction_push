# -*- coding: utf-8 -*-
"""
技术分析配置
Technical Analysis Configuration - 管理技术指标权重和参数
"""

from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum


class IndicatorWeight(Enum):
    """指标权重等级"""
    VERY_HIGH = 30
    HIGH = 25
    MEDIUM = 20
    LOW = 15
    VERY_LOW = 10


@dataclass
class TechnicalConfig:
    """技术分析配置"""
    
    # 指标权重配置 (总和应为100%)
    indicator_weights: Dict[str, int] = None
    
    # RSI参数
    rsi_period: int = 14
    rsi_overbought: float = 70
    rsi_oversold: float = 30
    
    # MACD参数
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    
    # 布林带参数
    bb_period: int = 20
    bb_std_dev: float = 2.0
    
    # KDJ参数
    kdj_k_period: int = 9
    kdj_k_smooth: int = 3
    kdj_d_smooth: int = 3
    kdj_overbought: float = 80
    kdj_oversold: float = 20
    
    # 移动平均线参数
    ma_short: int = 5
    ma_medium: int = 10
    ma_long: int = 20
    ma_extra_long: int = 30
    
    # ATR参数
    atr_period: int = 14
    
    # 威廉指标参数
    williams_period: int = 14
    williams_overbought: float = -20
    williams_oversold: float = -80
    
    # 信号强度阈值
    strong_signal_threshold: float = 80.0
    moderate_signal_threshold: float = 65.0
    weak_signal_threshold: float = 50.0
    
    def __post_init__(self):
        if self.indicator_weights is None:
            self.indicator_weights = {
                'moving_averages': 25,      # 25% - 移动平均线
                'rsi': 20,                  # 20% - RSI
                'macd': 20,                 # 20% - MACD
                'bollinger_bands': 15,      # 15% - 布林带
                'kdj': 10,                  # 10% - KDJ
                'williams_r': 5,            # 5% - 威廉指标
                'breakout': 5               # 5% - 突破分析
            }


class TechnicalAnalysisConfig:
    """技术分析配置管理器"""
    
    def __init__(self):
        self.config = TechnicalConfig()
        self._validate_weights()
    
    def _validate_weights(self):
        """验证权重配置"""
        total_weight = sum(self.config.indicator_weights.values())
        if abs(total_weight - 100) > 1:  # 允许1%的误差
            raise ValueError(f"指标权重总和应为100%，当前为{total_weight}%")
    
    def get_config(self) -> TechnicalConfig:
        """获取技术分析配置"""
        return self.config
    
    def update_weights(self, new_weights: Dict[str, int]):
        """更新指标权重"""
        self.config.indicator_weights.update(new_weights)
        self._validate_weights()
    
    def get_signal_strength_level(self, confidence: float) -> str:
        """根据置信度获取信号强度等级"""
        if confidence >= self.config.strong_signal_threshold:
            return "very_strong"
        elif confidence >= self.config.moderate_signal_threshold:
            return "strong"
        elif confidence >= self.config.weak_signal_threshold:
            return "moderate"
        else:
            return "weak"
    
    def get_indicator_description(self, indicator: str) -> str:
        """获取指标描述"""
        descriptions = {
            'moving_averages': '移动平均线 - 趋势跟踪指标',
            'rsi': 'RSI相对强弱指数 - 超买超卖指标',
            'macd': 'MACD指数平滑移动平均 - 趋势和动量指标',
            'bollinger_bands': '布林带 - 波动性和支撑阻力指标',
            'kdj': 'KDJ随机指标 - 超买超卖和趋势指标',
            'williams_r': '威廉指标 - 超买超卖指标',
            'breakout': '价格突破 - 趋势确认指标'
        }
        return descriptions.get(indicator, f'{indicator} - 技术指标')


# 全局配置实例
_technical_config = None


def get_technical_config() -> TechnicalAnalysisConfig:
    """获取技术分析配置实例"""
    global _technical_config
    if _technical_config is None:
        _technical_config = TechnicalAnalysisConfig()
    return _technical_config


# 预设配置方案
CONSERVATIVE_CONFIG = {
    'moving_averages': 35,  # 更重视趋势
    'rsi': 25,             # 重视超买超卖
    'macd': 20,            # 趋势确认
    'bollinger_bands': 10,  # 降低波动性指标权重
    'kdj': 5,              # 降低随机指标权重
    'williams_r': 3,       # 最小权重
    'breakout': 2          # 最小权重
}

AGGRESSIVE_CONFIG = {
    'moving_averages': 20,  # 降低趋势权重
    'rsi': 15,             # 降低超买超卖权重
    'macd': 25,            # 提高动量指标权重
    'bollinger_bands': 20,  # 提高波动性权重
    'kdj': 15,             # 提高随机指标权重
    'williams_r': 3,       # 保持最小
    'breakout': 2          # 保持最小
}

BALANCED_CONFIG = {
    'moving_averages': 25,  # 默认配置
    'rsi': 20,
    'macd': 20,
    'bollinger_bands': 15,
    'kdj': 10,
    'williams_r': 5,
    'breakout': 5
}