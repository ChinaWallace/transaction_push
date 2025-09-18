# -*- coding: utf-8 -*-
"""
服务快捷导入
Service shortcuts for easy importing
"""

from app.core.logging import get_logger

logger = get_logger(__name__)

# 交易所服务快捷导入
try:
    from .exchanges import (
        get_default_exchange, get_exchange_by_name, ExchangeFactory
    )
    from .exchanges.exchange_service_manager import (
        get_exchange_service, get_current_exchange_name, 
        is_okx_configured, is_binance_configured
    )
    # 保留特定交易所服务的导入以便向后兼容
    try:
        from .exchanges.okx import OKXHybridService, get_okx_hybrid_service
        from .exchanges.binance import BinanceHybridService
    except ImportError:
        logger.warning("⚠️ 特定交易所服务导入失败，使用统一服务管理器")
except ImportError as e:
    logger.warning(f"⚠️ 交易所服务导入失败: {e}")

# 交易服务快捷导入
try:
    from .trading import (
        CoreTradingService, UnifiedTradingService, TradingDecisionService,
        get_trading_service, get_unified_trading_service, get_decision_service
    )
except ImportError as e:
    logger.warning(f"⚠️ 交易服务导入失败: {e}")

# 通知服务快捷导入
try:
    from .notification import CoreNotificationService, get_core_notification_service
except ImportError as e:
    logger.warning(f"⚠️ 通知服务导入失败: {e}")

# ML服务快捷导入
try:
    from .ml import (
        KronosPredictionService, get_kronos_service,
        KronosIntegratedDecisionService, get_kronos_integrated_service,
        get_ml_enhanced_service, get_prediction_service, 
        get_integrated_decision_service, get_market_opportunity_service
    )
except ImportError as e:
    logger.warning(f"⚠️ ML服务导入失败: {e}")

# 数据服务快捷导入
try:
    from .data import (
        UnifiedDataService, DataSharingService,
        get_unified_data_service, get_data_sharing_service, get_news_service
    )
except ImportError as e:
    logger.warning(f"⚠️ 数据服务导入失败: {e}")

# 监控服务快捷导入
try:
    from .monitoring import FundingRateMonitorService, CoreMonitoringService
except ImportError as e:
    logger.warning(f"⚠️ 监控服务导入失败: {e}")

# 分析服务快捷导入
try:
    from .analysis import (
        EnhancedTechnicalAnalysisService,
        get_enhanced_technical_analysis_service,
        EnhancedVolumePriceAnalysisService,
        get_enhanced_volume_price_analysis_service
    )
    # 为了向后兼容，创建别名
    TrendAnalysisService = EnhancedTechnicalAnalysisService
    get_trend_analysis_service = get_enhanced_technical_analysis_service
    
    # 尝试导入详细技术分析服务（可能有依赖问题）
    try:
        from .analysis import DetailedTechnicalAnalysisService, get_detailed_technical_analysis_service
    except ImportError:
        DetailedTechnicalAnalysisService = None
        get_detailed_technical_analysis_service = None
        logger.warning("⚠️ 详细技术分析服务导入失败，可能缺少依赖")
except ImportError as e:
    logger.warning(f"⚠️ 分析服务导入失败: {e}")
    # 设置默认值
    EnhancedTechnicalAnalysisService = None
    get_enhanced_technical_analysis_service = None
    EnhancedVolumePriceAnalysisService = None
    get_enhanced_volume_price_analysis_service = None
    TrendAnalysisService = None
    get_trend_analysis_service = None

# 核心服务快捷导入
try:
    from .core import (
        SchedulerService, CoreSchedulerService, DynamicWeightService,
        get_scheduler_service, get_core_scheduler_service, 
        get_opportunity_service, get_backtest_service
    )
except ImportError as e:
    logger.warning(f"⚠️ 核心服务导入失败: {e}")

# 回测服务快捷导入
try:
    from .backtest import (
        CompleteBacktestService, BacktestReportService,
        get_complete_backtest_service, get_backtest_report_service
    )
except ImportError as e:
    logger.warning(f"⚠️ 回测服务导入失败: {e}")

__all__ = [
    # 交易所服务
    'get_default_exchange',
    'get_exchange_by_name', 
    'ExchangeFactory',
    'get_exchange_service',
    'get_current_exchange_name',
    'is_okx_configured',
    'is_binance_configured',
    # 向后兼容的特定交易所服务
    'OKXHybridService',
    'get_okx_hybrid_service',
    'BinanceHybridService',
    
    # 交易服务
    'CoreTradingService',
    'UnifiedTradingService',
    'TradingDecisionService',
    'get_trading_service',
    'get_unified_trading_service',
    'get_decision_service',
    
    # 通知服务
    'CoreNotificationService',
    'get_core_notification_service',
    
    # ML服务
    'KronosPredictionService',
    'get_kronos_service',
    'KronosIntegratedDecisionService',
    'get_kronos_integrated_service',
    'get_ml_enhanced_service',
    'get_prediction_service',
    'get_integrated_decision_service',
    'get_market_opportunity_service',
    
    # 数据服务
    'UnifiedDataService',
    'DataSharingService',
    'get_unified_data_service',
    'get_data_sharing_service',
    'get_news_service',
    
    # 监控服务
    'FundingRateMonitorService',
    'CoreMonitoringService',
    
    # 分析服务
    'TrendAnalysisService',
    'DetailedTechnicalAnalysisService',
    
    # 核心服务
    'SchedulerService',
    'CoreSchedulerService',
    'DynamicWeightService',
    'get_scheduler_service',
    'get_core_scheduler_service',
    'get_opportunity_service',
    'get_backtest_service',
    
    # 回测服务
    'CompleteBacktestService',
    'BacktestReportService',
    'get_complete_backtest_service',
    'get_backtest_report_service'
]