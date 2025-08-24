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
from .trading_decision import router as trading_decision_router
from .comprehensive_trading import router as comprehensive_trading_router
from .trading_advice import router as trading_advice_router
from .strategy_trading import router as strategy_trading_router
from .enhanced_trading_advice import router as enhanced_trading_advice_router
from .ml_strategy_optimization import router as ml_strategy_optimization_router
from .backtest import router as backtest_router
from .unified_trading import router as unified_trading_router

__all__ = [
    "trend_router",
    "monitor_router",
    "notification_router",
    "tradingview_router",
    "strategy_router",
    "ml_enhanced_router",
    "trading_decision_router",
    "comprehensive_trading_router",
    "trading_advice_router",
    "strategy_trading_router",
    "enhanced_trading_advice_router",
    "ml_strategy_optimization_router",
    "backtest_router",
    "unified_trading_router"
]
