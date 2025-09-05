# -*- coding: utf-8 -*-
"""
通知服务 - 兼容性包装器
Notification Service - Compatibility wrapper for CoreNotificationService
"""

from .core_notification_service import CoreNotificationService

# 为了向后兼容，创建一个别名
NotificationService = CoreNotificationService

# 导出
__all__ = ["NotificationService"]