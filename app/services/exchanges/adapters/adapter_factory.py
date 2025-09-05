# -*- coding: utf-8 -*-
"""
数据适配器工厂
Data adapter factory
"""

from typing import Dict, Type, Any
from functools import lru_cache
from datetime import datetime

from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError
from .base_adapter import ExchangeDataAdapter
from .binance_adapter import BinanceDataAdapter
from .okx_adapter import OKXDataAdapter

logger = get_logger(__name__)


class AdapterFactory:
    """
    数据适配器工厂类
    Data adapter factory class
    
    负责创建和管理不同交易所的数据适配器实例
    """
    
    # 注册的适配器类
    _adapters: Dict[str, Type[ExchangeDataAdapter]] = {
        'binance': BinanceDataAdapter,
        'okx': OKXDataAdapter
    }
    
    # 适配器实例缓存
    _instances: Dict[str, ExchangeDataAdapter] = {}
    
    @classmethod
    def register_adapter(cls, exchange_name: str, adapter_class: Type[ExchangeDataAdapter]) -> None:
        """
        注册新的适配器类
        Register new adapter class
        
        Args:
            exchange_name: 交易所名称 / Exchange name
            adapter_class: 适配器类 / Adapter class
        """
        exchange_name = exchange_name.lower()
        cls._adapters[exchange_name] = adapter_class
        logger.info(f"📝 注册数据适配器: {exchange_name} -> {adapter_class.__name__}")
    
    @classmethod
    def get_adapter(cls, exchange_name: str, use_cache: bool = True) -> ExchangeDataAdapter:
        """
        获取指定交易所的数据适配器
        Get data adapter for specified exchange
        
        Args:
            exchange_name: 交易所名称 / Exchange name
            use_cache: 是否使用缓存 / Whether to use cache
            
        Returns:
            ExchangeDataAdapter: 数据适配器实例
            
        Raises:
            TradingToolError: 不支持的交易所时抛出
        """
        exchange_name = exchange_name.lower()
        
        # 检查是否支持该交易所
        if exchange_name not in cls._adapters:
            supported_exchanges = list(cls._adapters.keys())
            raise TradingToolError(
                f"不支持的交易所: {exchange_name}，支持的交易所: {supported_exchanges}",
                error_code="UNSUPPORTED_EXCHANGE",
                details={
                    "exchange": exchange_name,
                    "supported_exchanges": supported_exchanges
                }
            )
        
        # 使用缓存
        if use_cache and exchange_name in cls._instances:
            logger.debug(f"🔍 使用缓存的适配器: {exchange_name}")
            return cls._instances[exchange_name]
        
        # 创建新实例
        try:
            adapter_class = cls._adapters[exchange_name]
            adapter_instance = adapter_class()
            
            # 缓存实例
            if use_cache:
                cls._instances[exchange_name] = adapter_instance
            
            logger.info(f"🔧 创建数据适配器: {exchange_name} -> {adapter_class.__name__}")
            return adapter_instance
            
        except Exception as e:
            logger.error(f"❌ 创建数据适配器失败: {exchange_name} -> {e}")
            raise TradingToolError(
                f"创建数据适配器失败: {str(e)}",
                error_code="ADAPTER_CREATION_ERROR",
                details={
                    "exchange": exchange_name,
                    "error": str(e)
                }
            )
    
    @classmethod
    def get_supported_exchanges(cls) -> list[str]:
        """
        获取支持的交易所列表
        Get list of supported exchanges
        
        Returns:
            List[str]: 支持的交易所名称列表
        """
        return list(cls._adapters.keys())
    
    @classmethod
    def clear_cache(cls) -> None:
        """
        清空适配器缓存
        Clear adapter cache
        """
        cls._instances.clear()
        logger.info("🧹 清空适配器缓存")
    
    @classmethod
    def get_cache_info(cls) -> Dict[str, any]:
        """
        获取缓存信息
        Get cache information
        
        Returns:
            Dict: 缓存信息
        """
        return {
            "cached_adapters": list(cls._instances.keys()),
            "cache_size": len(cls._instances),
            "supported_exchanges": cls.get_supported_exchanges(),
            "registered_adapters": {
                name: adapter_class.__name__ 
                for name, adapter_class in cls._adapters.items()
            }
        }
    
    @classmethod
    def is_supported(cls, exchange_name: str) -> bool:
        """
        检查是否支持指定交易所
        Check if exchange is supported
        
        Args:
            exchange_name: 交易所名称 / Exchange name
            
        Returns:
            bool: 是否支持
        """
        return exchange_name.lower() in cls._adapters
    
    @classmethod
    def handle_adapter_error(cls, error: Exception, exchange_name: str, operation: str) -> Dict[str, Any]:
        """
        处理适配器错误并提供恢复建议
        Handle adapter errors and provide recovery suggestions
        
        Args:
            error: 异常对象
            exchange_name: 交易所名称
            operation: 操作类型
            
        Returns:
            Dict: 错误处理结果和建议
        """
        from app.models.unified_exchange_data import DataAdaptationError, FieldMappingError, DataValidationError
        
        error_info = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "exchange": exchange_name,
            "operation": operation,
            "timestamp": datetime.now().isoformat(),
            "recovery_suggestions": []
        }
        
        # 根据错误类型提供不同的恢复建议
        if isinstance(error, FieldMappingError):
            error_info["recovery_suggestions"].extend([
                "检查交易所API返回的数据格式是否发生变化",
                "验证必需字段是否存在于原始数据中",
                "考虑更新适配器的字段映射配置"
            ])
            if hasattr(error, 'missing_fields'):
                error_info["missing_fields"] = error.missing_fields
        
        elif isinstance(error, DataValidationError):
            error_info["recovery_suggestions"].extend([
                "检查数据类型和格式是否符合预期",
                "验证数值范围和精度设置",
                "考虑添加数据清洗和预处理步骤"
            ])
            if hasattr(error, 'validation_errors'):
                error_info["validation_errors"] = error.validation_errors
        
        elif isinstance(error, DataAdaptationError):
            error_info["recovery_suggestions"].extend([
                "检查交易所服务是否正常运行",
                "验证网络连接和API访问权限",
                "考虑使用备用数据源或缓存数据"
            ])
        
        else:
            error_info["recovery_suggestions"].extend([
                "检查系统资源和依赖包状态",
                "查看详细错误日志获取更多信息",
                "考虑重启相关服务"
            ])
        
        # 记录错误处理日志
        logger.error(f"🚨 适配器错误处理: {exchange_name} {operation} - {error}")
        logger.info(f"💡 恢复建议: {', '.join(error_info['recovery_suggestions'])}")
        
        return error_info
    
    @classmethod
    def validate_adapter_health(cls, exchange_name: str) -> Dict[str, Any]:
        """
        验证适配器健康状态
        Validate adapter health status
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            Dict: 健康状态信息
        """
        health_info = {
            "exchange": exchange_name,
            "timestamp": datetime.now().isoformat(),
            "status": "unknown",
            "checks": {}
        }
        
        try:
            # 检查是否支持该交易所
            if not cls.is_supported(exchange_name):
                health_info["status"] = "unsupported"
                health_info["checks"]["supported"] = False
                return health_info
            
            health_info["checks"]["supported"] = True
            
            # 尝试获取适配器实例
            adapter = cls.get_adapter(exchange_name, use_cache=False)
            health_info["checks"]["instantiation"] = True
            
            # 检查适配器基本信息
            adapter_info = adapter.get_adapter_info()
            health_info["checks"]["info_available"] = True
            health_info["adapter_info"] = adapter_info
            
            # 检查缓存状态
            cache_info = cls.get_cache_info()
            health_info["checks"]["cache_accessible"] = True
            health_info["cache_info"] = cache_info
            
            health_info["status"] = "healthy"
            logger.info(f"✅ 适配器健康检查通过: {exchange_name}")
            
        except Exception as e:
            health_info["status"] = "unhealthy"
            health_info["error"] = str(e)
            health_info["error_type"] = type(e).__name__
            logger.error(f"❌ 适配器健康检查失败: {exchange_name} - {e}")
        
        return health_info


# 便利函数
@lru_cache(maxsize=10)
def get_adapter(exchange_name: str) -> ExchangeDataAdapter:
    """
    获取数据适配器的便利函数
    Convenience function to get data adapter
    
    Args:
        exchange_name: 交易所名称 / Exchange name
        
    Returns:
        ExchangeDataAdapter: 数据适配器实例
    """
    return AdapterFactory.get_adapter(exchange_name)


def get_supported_exchanges() -> list[str]:
    """
    获取支持的交易所列表的便利函数
    Convenience function to get supported exchanges
    
    Returns:
        List[str]: 支持的交易所名称列表
    """
    return AdapterFactory.get_supported_exchanges()


def is_exchange_supported(exchange_name: str) -> bool:
    """
    检查交易所是否支持的便利函数
    Convenience function to check if exchange is supported
    
    Args:
        exchange_name: 交易所名称 / Exchange name
        
    Returns:
        bool: 是否支持
    """
    return AdapterFactory.is_supported(exchange_name)


# 初始化日志
logger.info(f"🏭 数据适配器工厂初始化完成，支持的交易所: {get_supported_exchanges()}")