# -*- coding: utf-8 -*-
"""
Kronos 增强决策数据结构
Kronos Enhanced Decision Data Structures

统一的决策数据结构，避免循环导入
"""

from enum import Enum
from typing import Optional, Any
from datetime import datetime
from dataclasses import dataclass


class KronosSignalStrength(Enum):
    """Kronos信号强度"""
    VERY_STRONG = "极强"
    STRONG = "强"
    MODERATE = "中等"
    WEAK = "弱"
    VERY_WEAK = "极弱"


class MarketRegime(Enum):
    """市场状态枚举"""
    TRENDING_UP = "上涨趋势"
    TRENDING_DOWN = "下跌趋势"
    RANGING = "震荡整理"
    VOLATILE = "高波动"
    CALM = "平静"


@dataclass
class KronosEnhancedDecision:
    """Kronos增强决策结果"""
    symbol: str
    timestamp: datetime
    
    # Kronos预测结果
    kronos_prediction: Optional[Any]
    kronos_signal_strength: KronosSignalStrength
    kronos_confidence: float
    
    # 传统分析结果
    technical_signal: str
    technical_confidence: float
    
    # 持仓分析结果
    position_recommendation: Optional[Any] = None
    position_risk: Optional[Any] = None
    
    # 综合决策
    final_action: str = "持有观望"
    final_confidence: float = 0.5
    signal_confluence: float = 0.5  # 信号一致性
    
    # 风险管理 - 设置默认值避免None格式化错误
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: float = 0.1
    
    # 决策依据
    reasoning: str = "暂无详细说明"
    market_regime: Optional[MarketRegime] = None