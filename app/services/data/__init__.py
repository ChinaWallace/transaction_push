# -*- coding: utf-8 -*-
"""
数据处理相关服务模块
Data Processing Services Module
"""

from .unified_data_service import UnifiedDataService
from .data_sharing_service import DataSharingService
from .news_monitor_service import NewsMonitorService, get_news_monitor_service

# 便利函数
def get_unified_data_service():
    """获取统一数据服务的便利函数"""
    return UnifiedDataService()

def get_data_sharing_service():
    """获取数据共享服务的便利函数"""
    return DataSharingService()

def get_news_service():
    """获取新闻监控服务的便利函数"""
    return get_news_monitor_service()

__all__ = [
    'UnifiedDataService',
    'DataSharingService', 
    'NewsMonitorService',
    'get_news_monitor_service',
    # 便利函数
    'get_unified_data_service',
    'get_data_sharing_service',
    'get_news_service'
]