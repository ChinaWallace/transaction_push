# -*- coding: utf-8 -*-
"""
分析相关服务模块
Analysis services module
"""

from typing import Optional, Any
from app.core.logging import get_logger

logger = get_logger(__name__)

# 导入分析服务
from .trend_analysis_service import TrendAnalysisService

# 条件导入详细技术分析服务
try:
    from .detailed_technical_analysis_service import (
        DetailedTechnicalAnalysisService,
        get_detailed_technical_analysis_service,
        IndicatorResult,
        TechnicalAnalysisBreakdown,
        IndicatorWeight
    )
    _detailed_analysis_available = True
except ImportError as e:
    logger.warning(f"⚠️ 详细技术分析服务导入失败: {e}")
    DetailedTechnicalAnalysisService = None
    get_detailed_technical_analysis_service = None
    IndicatorResult = None
    TechnicalAnalysisBreakdown = None
    IndicatorWeight = None
    _detailed_analysis_available = False

# 导入已移动到analysis目录的服务
def _safe_import_analysis_service(module_name: str, class_name: str) -> Optional[Any]:
    """安全导入分析服务"""
    try:
        module = __import__(f"app.services.analysis.{module_name}", fromlist=[class_name])
        return getattr(module, class_name)
    except ImportError as e:
        logger.warning(f"⚠️ 分析服务 {class_name} 导入失败: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ 分析服务 {class_name} 加载失败: {e}")
        return None

# 延迟加载分析服务
_analysis_services = {}

def get_analysis_service_class(service_name: str) -> Optional[Any]:
    """获取分析服务类"""
    if service_name in _analysis_services:
        return _analysis_services[service_name]
    
    service_mappings = {
        'PositionAnalysisService': ('position_analysis_service', 'PositionAnalysisService'),
        'KronosPositionAnalysisService': ('kronos_position_analysis_service', 'KronosPositionAnalysisService'),
        'RiskManagementService': ('risk_management_service', 'RiskManagementService'),
        'NewsAnalysisService': ('news_analysis_service', 'NewsAnalysisService'),
        'OpenInterestAnalysisService': ('open_interest_analysis_service', 'OpenInterestAnalysisService')
    }
    
    if service_name in service_mappings:
        module_name, class_name = service_mappings[service_name]
        service = _safe_import_analysis_service(module_name, class_name)
        _analysis_services[service_name] = service
        return service
    
    return None

# 为向后兼容性提供属性访问
def __getattr__(name: str):
    """动态属性访问 - 支持向后兼容性"""
    # 首先检查是否是分析服务
    analysis_service = get_analysis_service_class(name)
    if analysis_service is not None:
        return analysis_service
    
    raise AttributeError(f"模块 'app.services.analysis' 没有属性 '{name}'")

# 便利函数
def get_trend_analysis_service():
    """
    获取趋势分析服务实例
    Get trend analysis service instance
    """
    return TrendAnalysisService()

def get_analysis_service(service_type: str = "trend"):
    """
    获取分析服务的便利函数
    Get analysis service convenience function
    
    Args:
        service_type: 服务类型 ('trend', 'detailed', 'position', 'risk', 'news', 'open_interest', 'kronos_position')
    """
    if service_type == "trend":
        return get_trend_analysis_service()
    elif service_type == "detailed" and _detailed_analysis_available:
        return get_detailed_technical_analysis_service()
    elif service_type in ["position", "risk", "news", "kronos_position", "open_interest"]:
        service_name = {
            "position": "PositionAnalysisService",
            "risk": "RiskManagementService", 
            "news": "NewsAnalysisService",
            "kronos_position": "KronosPositionAnalysisService",
            "open_interest": "OpenInterestAnalysisService"
        }[service_type]
        
        service_class = get_analysis_service_class(service_name)
        if service_class:
            return service_class()
    
    logger.warning(f"⚠️ 未知的分析服务类型: {service_type}")
    return None

# 动态构建 __all__ 列表
def _build_all_list():
    """动态构建导出列表"""
    all_list = [
        'TrendAnalysisService',
        'get_trend_analysis_service',
        'get_analysis_service',
        'get_analysis_service_class'
    ]
    
    # 添加详细技术分析相关导出（如果可用）
    if _detailed_analysis_available:
        all_list.extend([
            'DetailedTechnicalAnalysisService',
            'get_detailed_technical_analysis_service',
            'IndicatorResult',
            'TechnicalAnalysisBreakdown',
            'IndicatorWeight'
        ])
    
    return all_list

__all__ = _build_all_list()