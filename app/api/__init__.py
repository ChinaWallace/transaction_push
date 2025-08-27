# -*- coding: utf-8 -*-
"""
API路由模块
API routes module
"""

from .trend import router as trend_router
from .monitor import router as monitor_router  
from .notification import router as notification_router
from .tradingview import router as tradingview_router
from .strategy import router as strategy_router
from .ml_enhanced import router as ml_enhanced_router
from .backtest import router as backtest_router

__all__ = [
    "trend_router",
    "monitor_router",
    "notification_router",
    "tradingview_router",
    "strategy_router",
    "ml_enhanced_router",
    "backtest_router"
]
