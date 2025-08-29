# -*- coding: utf-8 -*-
"""
监控服务 - 兼容性包装器
Monitor Service - Compatibility wrapper for CoreMonitoringService
"""

from .core_monitoring_service import CoreMonitoringService

class MonitorService(CoreMonitoringService):
    """兼容性包装器，支持exchange参数"""
    
    def __init__(self, exchange=None):
        # 忽略exchange参数，直接调用父类构造函数
        super().__init__()
        self.exchange_name = exchange  # 保存exchange名称以备后用

# 导出
__all__ = ["MonitorService"]