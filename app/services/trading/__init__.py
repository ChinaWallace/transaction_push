# -*- coding: utf-8 -*-
"""
交易相关服务模块
Trading Services Module
"""

from .core_trading_service import CoreTradingService, TradingSignal, AnalysisType, SignalStrength, get_core_trading_service
from .unified_trading_service import UnifiedTradingService
from .strategy_trading_service import StrategyTradingService
from .trading_decision_service import TradingDecisionService, TradingAction, RiskLevel
from .trading_pair_service import TradingPairService

# 便利函数
def get_trading_service():
    """获取核心交易服务的便利函数"""
    return get_core_trading_service()

def get_unified_trading_service():
    """获取统一交易服务的便利函数"""
    return UnifiedTradingService()

def get_decision_service():
    """获取交易决策服务的便利函数"""
    return TradingDecisionService()

__all__ = [
    'CoreTradingService',
    'TradingSignal', 
    'AnalysisType',
    'SignalStrength',
    'get_core_trading_service',
    'UnifiedTradingService',
    'StrategyTradingService',
    'TradingDecisionService',
    'TradingAction',
    'RiskLevel',
    'TradingPairService',
    # 便利函数
    'get_trading_service',
    'get_unified_trading_service',
    'get_decision_service'
]