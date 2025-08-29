# -*- coding: utf-8 -*-
"""
交易通知服务 - 兼容性包装器
Trading Notification Service - Compatibility wrapper for CoreNotificationService
"""

from .core_notification_service import CoreNotificationService

# 为了向后兼容，创建一个别名
TradingNotificationService = CoreNotificationService

# 导出
__all__ = ["TradingNotificationService"]