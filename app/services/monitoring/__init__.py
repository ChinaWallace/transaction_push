# -*- coding: utf-8 -*-
"""
监控相关服务模块
Monitoring services module
"""

from app.core.logging import get_logger

logger = get_logger(__name__)

# 导入监控服务
from .funding_rate_monitor_service import FundingRateMonitorService

# 向后兼容性导入 - 从根目录的服务
try:
    from app.services.core_monitoring_service import CoreMonitoringService
    from app.services.monitor_service import MonitorService
    from app.services.market_anomaly_monitor_service import MarketAnomalyMonitorService
    from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
    from app.services.volume_anomaly_service import VolumeAnomalyService
    from app.services.analysis.open_interest_analysis_service import OpenInterestAnalysisService
except ImportError as e:
    logger.warning(f"⚠️ 部分监控服务导入失败: {e}")
    CoreMonitoringService = None
    MonitorService = None
    MarketAnomalyMonitorService = None
    NegativeFundingMonitorService = None
    VolumeAnomalyService = None
    OpenInterestAnalysisService = None

__all__ = [
    'FundingRateMonitorService',
    'CoreMonitoringService',
    # 向后兼容的导出
    'MonitorService', 
    'MarketAnomalyMonitorService',
    'NegativeFundingMonitorService',
    'VolumeAnomalyService',
    'OpenInterestAnalysisService'
]