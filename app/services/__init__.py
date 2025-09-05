
# -*- coding: utf-8 -*-
"""
服务模块主入口
Services module main entry point
"""

from typing import Dict, Any, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

# 服务注册表 - 用于服务发现和延迟加载
_service_registry: Dict[str, Dict[str, Any]] = {}
_loaded_services: Dict[str, Any] = {}

def register_service(name: str, module_path: str, class_name: str, category: str = "general"):
    """
    注册服务到服务发现机制
    Register service to service discovery mechanism
    """
    _service_registry[name] = {
        "module_path": module_path,
        "class_name": class_name,
        "category": category,
        "loaded": False
    }

def get_service(name: str) -> Optional[Any]:
    """
    获取服务实例（延迟加载）
    Get service instance with lazy loading
    """
    if name in _loaded_services:
        return _loaded_services[name]
    
    if name not in _service_registry:
        logger.warning(f"⚠️ 服务 '{name}' 未注册")
        return None
    
    service_info = _service_registry[name]
    try:
        # 动态导入模块
        module = __import__(service_info["module_path"], fromlist=[service_info["class_name"]])
        service_class = getattr(module, service_info["class_name"])
        
        # 缓存服务实例
        _loaded_services[name] = service_class
        service_info["loaded"] = True
        
        logger.debug(f"🔍 成功加载服务: {name}")
        return service_class
        
    except ImportError as e:
        logger.warning(f"⚠️ 服务 '{name}' 导入失败: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ 服务 '{name}' 加载失败: {e}")
        return None

def list_services(category: str = None) -> Dict[str, Dict[str, Any]]:
    """
    列出所有注册的服务
    List all registered services
    """
    if category:
        return {k: v for k, v in _service_registry.items() if v["category"] == category}
    return _service_registry.copy()

# 导入子模块 - 使用条件导入避免循环依赖
_submodules = {}

def _import_submodule(name: str, path: str) -> bool:
    """安全导入子模块"""
    try:
        module = __import__(f"app.services.{path}", fromlist=[name])
        _submodules[name] = module
        return True
    except ImportError as e:
        logger.warning(f"⚠️ 子模块 '{name}' 导入失败: {e}")
        return False

# 导入核心子模块
_import_submodule("exchanges", "exchanges")
_import_submodule("monitoring", "monitoring")
_import_submodule("analysis", "analysis")
_import_submodule("trading", "trading")
_import_submodule("notification", "notification")
_import_submodule("data", "data")
_import_submodule("ml", "ml")
_import_submodule("core", "core")
_import_submodule("backtest", "backtest")

# 注册核心服务到服务发现机制
def _register_core_services():
    """注册核心服务"""
    # 交易所服务
    register_service("ExchangeFactory", "app.services.exchanges", "ExchangeFactory", "exchange")
    register_service("get_default_exchange", "app.services.exchanges", "get_default_exchange", "exchange")
    register_service("get_exchange_by_name", "app.services.exchanges", "get_exchange_by_name", "exchange")
    
    # 交易服务
    register_service("CoreTradingService", "app.services.trading", "CoreTradingService", "trading")
    register_service("UnifiedTradingService", "app.services.trading", "UnifiedTradingService", "trading")
    register_service("TradingDecisionService", "app.services.trading", "TradingDecisionService", "trading")
    
    # 通知服务
    register_service("CoreNotificationService", "app.services.notification", "CoreNotificationService", "notification")
    register_service("NotificationService", "app.services.notification", "NotificationService", "notification")
    
    # 数据服务
    register_service("UnifiedDataService", "app.services.data", "UnifiedDataService", "data")
    register_service("DataSharingService", "app.services.data", "DataSharingService", "data")
    
    # ML服务
    register_service("KronosPredictionService", "app.services.ml", "KronosPredictionService", "ml")
    register_service("MLEnhancedService", "app.services.ml", "MLEnhancedService", "ml")
    register_service("get_kronos_service", "app.services.ml", "get_kronos_service", "ml")
    
    # 核心服务
    register_service("SchedulerService", "app.services.core", "SchedulerService", "core")
    register_service("CoreSchedulerService", "app.services.core", "CoreSchedulerService", "core")
    
    # 分析服务 - 已移动到analysis子模块
    register_service("PositionAnalysisService", "app.services.analysis.position_analysis_service", "PositionAnalysisService", "analysis")
    register_service("KronosPositionAnalysisService", "app.services.analysis.kronos_position_analysis_service", "KronosPositionAnalysisService", "analysis")
    register_service("RiskManagementService", "app.services.analysis.risk_management_service", "RiskManagementService", "analysis")
    register_service("NewsAnalysisService", "app.services.analysis.news_analysis_service", "NewsAnalysisService", "analysis")
    register_service("OpenInterestAnalysisService", "app.services.analysis.open_interest_analysis_service", "OpenInterestAnalysisService", "analysis")
    register_service("DetailedTechnicalAnalysisService", "app.services.analysis.detailed_technical_analysis_service", "DetailedTechnicalAnalysisService", "analysis")
    
    # 向后兼容的根目录服务
    register_service("BinanceService", "app.services.binance_service", "BinanceService", "legacy")
    register_service("CoreMonitoringService", "app.services.core_monitoring_service", "CoreMonitoringService", "legacy")
    register_service("MonitorService", "app.services.monitor_service", "MonitorService", "legacy")
    register_service("MarketAnomalyMonitorService", "app.services.market_anomaly_monitor_service", "MarketAnomalyMonitorService", "legacy")
    register_service("NegativeFundingMonitorService", "app.services.negative_funding_monitor_service", "NegativeFundingMonitorService", "legacy")
    register_service("VolumeAnomalyService", "app.services.volume_anomaly_service", "VolumeAnomalyService", "legacy")

# 初始化服务注册
_register_core_services()

# 便利导入 - 通过服务发现机制提供向后兼容性
def _create_lazy_import(service_name: str):
    """创建延迟导入的便利函数"""
    def lazy_getter():
        return get_service(service_name)
    return lazy_getter

# 为向后兼容性创建便利导入
try:
    # 交易所服务
    ExchangeFactory = get_service("ExchangeFactory")
    get_default_exchange = get_service("get_default_exchange")
    get_exchange_by_name = get_service("get_exchange_by_name")
    
    # 交易服务
    CoreTradingService = get_service("CoreTradingService")
    UnifiedTradingService = get_service("UnifiedTradingService")
    TradingDecisionService = get_service("TradingDecisionService")
    
    # 通知服务
    CoreNotificationService = get_service("CoreNotificationService")
    NotificationService = get_service("NotificationService")
    
    # 数据服务
    UnifiedDataService = get_service("UnifiedDataService")
    DataSharingService = get_service("DataSharingService")
    
    # ML服务
    KronosPredictionService = get_service("KronosPredictionService")
    MLEnhancedService = get_service("MLEnhancedService")
    get_kronos_service = get_service("get_kronos_service")
    
    # 核心服务
    SchedulerService = get_service("SchedulerService")
    CoreSchedulerService = get_service("CoreSchedulerService")
    
    # 向后兼容的根目录服务
    BinanceService = get_service("BinanceService")
    CoreMonitoringService = get_service("CoreMonitoringService")
    MonitorService = get_service("MonitorService")
    MarketAnomalyMonitorService = get_service("MarketAnomalyMonitorService")
    NegativeFundingMonitorService = get_service("NegativeFundingMonitorService")
    VolumeAnomalyService = get_service("VolumeAnomalyService")
    OpenInterestAnalysisService = get_service("OpenInterestAnalysisService")
    PositionAnalysisService = get_service("PositionAnalysisService")
    KronosPositionAnalysisService = get_service("KronosPositionAnalysisService")
    RiskManagementService = get_service("RiskManagementService")
    NewsAnalysisService = get_service("NewsAnalysisService")
    
    # 条件导入 - 可能有依赖问题的服务
    DetailedTechnicalAnalysisService = get_service("DetailedTechnicalAnalysisService")
    if DetailedTechnicalAnalysisService is None:
        logger.warning("⚠️ DetailedTechnicalAnalysisService 导入失败，可能缺少依赖")
    
except Exception as e:
    logger.warning(f"⚠️ 部分服务导入失败，使用延迟加载: {e}")

# 便利函数 - 简化常用服务的获取
def get_exchange_service(exchange_name: str = None):
    """
    获取交易所服务的便利函数
    Get exchange service convenience function
    """
    try:
        get_exchange_func = get_service("get_exchange_by_name")
        if get_exchange_func:
            return get_exchange_func(exchange_name)
        return None
    except Exception as e:
        logger.error(f"❌ 获取交易所服务失败: {e}")
        return None

def get_trading_service():
    """
    获取核心交易服务的便利函数
    Get core trading service convenience function
    """
    try:
        trading_service_class = get_service("CoreTradingService")
        if trading_service_class:
            return trading_service_class()
        return None
    except Exception as e:
        logger.error(f"❌ 获取交易服务失败: {e}")
        return None

def get_notification_service():
    """
    获取通知服务的便利函数
    Get notification service convenience function
    """
    try:
        notification_service_class = get_service("CoreNotificationService")
        if notification_service_class:
            return notification_service_class()
        return None
    except Exception as e:
        logger.error(f"❌ 获取通知服务失败: {e}")
        return None

def get_ml_service():
    """
    获取ML服务的便利函数
    Get ML service convenience function
    """
    try:
        ml_service_func = get_service("get_kronos_service")
        if ml_service_func:
            return ml_service_func()
        return None
    except Exception as e:
        logger.error(f"❌ 获取ML服务失败: {e}")
        return None

# 导入快捷方式模块，提供便利的导入路径
def _import_shortcuts():
    """安全导入快捷方式模块"""
    try:
        from . import shortcuts
        return shortcuts
    except ImportError as e:
        logger.warning(f"⚠️ 快捷导入模块加载失败: {e}")
        return None

shortcuts = _import_shortcuts()

# 动态构建 __all__ 列表
def _build_all_list():
    """动态构建导出列表"""
    all_list = [
        # 服务发现函数
        "register_service",
        "get_service", 
        "list_services",
        
        # 便利函数
        "get_exchange_service",
        "get_trading_service",
        "get_notification_service",
        "get_ml_service",
    ]
    
    # 添加成功加载的子模块
    for name, module in _submodules.items():
        if module is not None:
            all_list.append(name)
    
    # 添加快捷方式模块（如果可用）
    if shortcuts is not None:
        all_list.append("shortcuts")
    
    # 添加成功加载的服务类
    for service_name, service_info in _service_registry.items():
        if service_info.get("loaded", False):
            all_list.append(service_name)
    
    return all_list

__all__ = _build_all_list()

# 为子模块提供便利访问
def __getattr__(name: str):
    """
    动态属性访问 - 支持延迟加载和向后兼容性
    Dynamic attribute access - supports lazy loading and backward compatibility
    """
    # 首先检查子模块
    if name in _submodules:
        return _submodules[name]
    
    # 然后检查服务注册表
    service = get_service(name)
    if service is not None:
        return service
    
    # 最后尝试从快捷方式模块获取
    if shortcuts is not None and hasattr(shortcuts, name):
        return getattr(shortcuts, name)
    
    raise AttributeError(f"模块 'app.services' 没有属性 '{name}'")
