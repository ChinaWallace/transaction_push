# -*- coding: utf-8 -*-
"""
机器学习相关服务模块
Machine Learning Services Module
"""

from .ml_enhanced_service import MLEnhancedService, PredictionSignal
from .kronos_prediction_service import KronosPredictionService, get_kronos_service
from .kronos_integrated_decision_service import (
    KronosIntegratedDecisionService, 
    get_kronos_integrated_service,
    KronosEnhancedDecision,
    KronosSignalStrength
)
from .kronos_market_opportunity_service import KronosMarketOpportunityService
from .anomaly_state_manager import AnomalyStateManager

# 全局服务实例
_ml_enhanced_service = None

# 便利函数
async def get_ml_enhanced_service():
    """获取ML增强服务的便利函数 - 异步单例模式"""
    global _ml_enhanced_service
    if _ml_enhanced_service is None:
        _ml_enhanced_service = MLEnhancedService()
        # 这里可以添加异步初始化逻辑
    return _ml_enhanced_service

def get_prediction_service():
    """获取Kronos预测服务的便利函数"""
    return get_kronos_service()

def get_integrated_decision_service():
    """获取Kronos集成决策服务的便利函数"""
    return get_kronos_integrated_service()

def get_market_opportunity_service():
    """获取Kronos市场机会服务的便利函数"""
    return KronosMarketOpportunityService()

__all__ = [
    'MLEnhancedService',
    'PredictionSignal',
    'KronosPredictionService',
    'get_kronos_service',
    'KronosIntegratedDecisionService',
    'get_kronos_integrated_service',
    'KronosEnhancedDecision',
    'KronosSignalStrength',
    'KronosMarketOpportunityService',
    'AnomalyStateManager',
    # 便利函数
    'get_ml_enhanced_service',
    'get_prediction_service',
    'get_integrated_decision_service',
    'get_market_opportunity_service'
]