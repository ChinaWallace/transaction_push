# -*- coding: utf-8 -*-
"""
API路由模块
API routes module
"""

from .trend import router as trend_router
from .monitor import router as monitor_router  
from .notification import router as notification_router

__all__ = [
    "trend_router",
    "monitor_router",
    "notification_router"
]
