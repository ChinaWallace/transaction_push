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

# 便利函数
def get_ml_enhanced_service():
    """获取ML增强服务的便利函数"""
    return MLEnhancedService()

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