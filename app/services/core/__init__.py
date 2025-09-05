# -*- coding: utf-8 -*-
"""
核心服务模块
Core Services Module
"""

from .scheduler_service import SchedulerService
from .core_scheduler_service import CoreSchedulerService
from .core_opportunity_service import CoreOpportunityService
from .dynamic_weight_service import DynamicWeightService, get_dynamic_weight_service
from .core_backtest_service import CoreBacktestService

# 便利函数
def get_scheduler_service():
    """获取调度服务的便利函数"""
    return SchedulerService()

def get_core_scheduler_service():
    """获取核心调度服务的便利函数"""
    return CoreSchedulerService()

def get_opportunity_service():
    """获取机会服务的便利函数"""
    return CoreOpportunityService()

def get_backtest_service():
    """获取回测服务的便利函数"""
    return CoreBacktestService()

__all__ = [
    'SchedulerService',
    'CoreSchedulerService',
    'CoreOpportunityService', 
    'DynamicWeightService',
    'get_dynamic_weight_service',
    'CoreBacktestService',
    # 便利函数
    'get_scheduler_service',
    'get_core_scheduler_service',
    'get_opportunity_service',
    'get_backtest_service'
]