# -*- coding: utf-8 -*-
"""
交易所工厂类
Exchange Factory - 配置驱动的交易所实例创建和管理
"""

import asyncio
from typing import Dict, Optional, Type, Any, List
from datetime import datetime

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError, UnsupportedExchangeError
from .base.exchange_interface import ExchangeInterface

logger = get_logger(__name__)


class ExchangeFactory:
    """
    交易所工厂类
    Exchange Factory Class
    
    提供配置驱动的交易所实例创建和管理功能：
    1. 单例模式管理交易所实例
    2. 支持配置驱动的交易所选择
    3. 自动资源管理和清理
    4. 支持动态交易所切换
    """
    
    # 单例实例存储
    _instances: Dict[str, ExchangeInterface] = {}
    _current_exchange: Optional[str] = None
    _initialization_lock = asyncio.Lock()
    _cleanup_lock = asyncio.Lock()
    
    # 支持的交易所注册表
    _exchange_registry: Dict[str, Type[ExchangeInterface]] = {}
    
    # 工厂状态
    _is_initialized = False
    _last_config_check = None
    _initialization_stats = {
        'total_created': 0,
        'total_cleaned': 0,
        'current_active': 0,
        'last_update': datetime.now()
    }
    
    @classmethod
    def register_exchange(cls, name: str, exchange_class: Type[ExchangeInterface]) -> None:
        """
        注册交易所类
        Register exchange class
        
        Args:
            name: 交易所名称 / Exchange name (e.g., 'binance')
            exchange_class: 交易所类 / Exchange class
        """
        cls._exchange_registry[name.lower()] = exchange_class
        logger.info(f"📝 注册交易所: {name} -> {exchange_class.__name__}")
    
    @classmethod
    def get_supported_exchanges(cls) -> List[str]:
        """
        获取支持的交易所列表
        Get list of supported exchanges
        
        Returns:
            List[str]: 支持的交易所名称列表 / List of supported exchange names
        """
        return list(cls._exchange_registry.keys())
    
    @classmethod
    async def get_exchange(cls, exchange_name: str = None) -> ExchangeInterface:
        """
        获取交易所实例
        Get exchange instance
        
        Args:
            exchange_name: 交易所名称，None时使用配置中的默认值 / Exchange name, None for default from config
            
        Returns:
            ExchangeInterface: 交易所实例 / Exchange instance
            
        Raises:
            UnsupportedExchangeError: 不支持的交易所 / Unsupported exchange
            TradingToolError: 初始化失败 / Initialization failed
        """
        async with cls._initialization_lock:
            # 获取交易所名称
            if exchange_name is None:
                exchange_name = cls._get_default_exchange_name()
            
            exchange_name = exchange_name.lower()
            
            # 检查是否支持该交易所
            if exchange_name not in cls._exchange_registry:
                supported = ', '.join(cls._exchange_registry.keys())
                raise UnsupportedExchangeError(
                    f"不支持的交易所: {exchange_name}。支持的交易所: {supported}"
                )
            
            # 检查是否已存在实例
            if exchange_name in cls._instances:
                instance = cls._instances[exchange_name]
                
                # 检查实例是否健康
                if await cls._check_instance_health(instance):
                    logger.debug(f"🔄 复用现有交易所实例: {exchange_name}")
                    cls._current_exchange = exchange_name
                    return instance
                else:
                    logger.warning(f"⚠️ 现有实例不健康，重新创建: {exchange_name}")
                    await cls._cleanup_instance(exchange_name)
            
            # 创建新实例
            try:
                logger.info(f"🏗️ 创建交易所实例: {exchange_name}")
                
                exchange_class = cls._exchange_registry[exchange_name]
                instance = exchange_class()
                
                # 初始化实例
                await instance.initialize()
                
                # 存储实例
                cls._instances[exchange_name] = instance
                cls._current_exchange = exchange_name
                
                # 更新统计
                cls._initialization_stats['total_created'] += 1
                cls._initialization_stats['current_active'] = len(cls._instances)
                cls._initialization_stats['last_update'] = datetime.now()
                
                logger.info(f"✅ 交易所实例创建成功: {exchange_name}")
                return instance
                
            except Exception as e:
                logger.error(f"❌ 创建交易所实例失败: {exchange_name} - {e}")
                raise TradingToolError(f"交易所初始化失败 ({exchange_name}): {e}")
    
    @classmethod
    async def get_current_exchange(cls) -> Optional[ExchangeInterface]:
        """
        获取当前活跃的交易所实例
        Get current active exchange instance
        
        Returns:
            Optional[ExchangeInterface]: 当前交易所实例，无活跃实例时返回None
        """
        if cls._current_exchange and cls._current_exchange in cls._instances:
            instance = cls._instances[cls._current_exchange]
            
            # 检查实例健康状态
            if await cls._check_instance_health(instance):
                return instance
            else:
                logger.warning(f"⚠️ 当前交易所实例不健康: {cls._current_exchange}")
                await cls._cleanup_instance(cls._current_exchange)
                cls._current_exchange = None
        
        return None
    
    @classmethod
    async def switch_exchange(cls, new_exchange_name: str) -> ExchangeInterface:
        """
        切换到新的交易所
        Switch to a new exchange
        
        Args:
            new_exchange_name: 新交易所名称 / New exchange name
            
        Returns:
            ExchangeInterface: 新的交易所实例 / New exchange instance
        """
        new_exchange_name = new_exchange_name.lower()
        
        logger.info(f"🔄 切换交易所: {cls._current_exchange} -> {new_exchange_name}")
        
        # 如果已经是当前交易所，直接返回
        if cls._current_exchange == new_exchange_name:
            return await cls.get_current_exchange()
        
        # 清理当前交易所实例（可选，也可以保留以便快速切换回来）
        if cls._current_exchange:
            logger.info(f"🧹 清理当前交易所实例: {cls._current_exchange}")
            # 注意：这里不清理实例，而是保留以便快速切换
            # await cls._cleanup_instance(cls._current_exchange)
        
        # 获取新的交易所实例
        new_instance = await cls.get_exchange(new_exchange_name)
        
        logger.info(f"✅ 交易所切换完成: {new_exchange_name}")
        return new_instance
    
    @classmethod
    async def cleanup_exchange(cls, exchange_name: str) -> None:
        """
        清理指定交易所实例
        Cleanup specific exchange instance
        
        Args:
            exchange_name: 交易所名称 / Exchange name
        """
        await cls._cleanup_instance(exchange_name.lower())
    
    @classmethod
    async def cleanup_all(cls) -> None:
        """
        清理所有交易所实例
        Cleanup all exchange instances
        """
        async with cls._cleanup_lock:
            logger.info("🧹 开始清理所有交易所实例...")
            
            cleanup_tasks = []
            for exchange_name in list(cls._instances.keys()):
                task = asyncio.create_task(
                    cls._cleanup_instance(exchange_name),
                    name=f"cleanup_{exchange_name}"
                )
                cleanup_tasks.append(task)
            
            # 并发清理所有实例
            if cleanup_tasks:
                results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                
                # 检查清理结果
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        exchange_name = list(cls._instances.keys())[i] if i < len(cls._instances) else "unknown"
                        logger.error(f"❌ 清理交易所实例失败: {exchange_name} - {result}")
            
            # 重置状态
            cls._instances.clear()
            cls._current_exchange = None
            cls._is_initialized = False
            
            # 更新统计
            cls._initialization_stats['current_active'] = 0
            cls._initialization_stats['last_update'] = datetime.now()
            
            logger.info("✅ 所有交易所实例清理完成")
    
    @classmethod
    async def _cleanup_instance(cls, exchange_name: str) -> None:
        """
        清理单个交易所实例
        Cleanup single exchange instance
        
        Args:
            exchange_name: 交易所名称 / Exchange name
        """
        if exchange_name not in cls._instances:
            return
        
        try:
            instance = cls._instances[exchange_name]
            logger.info(f"🧹 清理交易所实例: {exchange_name}")
            
            # 调用实例的清理方法
            await instance.cleanup()
            
            # 从实例字典中移除
            del cls._instances[exchange_name]
            
            # 如果是当前交易所，重置当前交易所
            if cls._current_exchange == exchange_name:
                cls._current_exchange = None
            
            # 更新统计
            cls._initialization_stats['total_cleaned'] += 1
            cls._initialization_stats['current_active'] = len(cls._instances)
            cls._initialization_stats['last_update'] = datetime.now()
            
            logger.info(f"✅ 交易所实例清理完成: {exchange_name}")
            
        except Exception as e:
            logger.error(f"❌ 清理交易所实例失败: {exchange_name} - {e}")
            # 即使清理失败，也要从字典中移除
            cls._instances.pop(exchange_name, None)
    
    @classmethod
    async def _check_instance_health(cls, instance: ExchangeInterface) -> bool:
        """
        检查交易所实例健康状态
        Check exchange instance health
        
        Args:
            instance: 交易所实例 / Exchange instance
            
        Returns:
            bool: 实例是否健康 / Whether instance is healthy
        """
        try:
            # 检查实例是否有健康检查方法
            if hasattr(instance, 'health_check'):
                health_status = await instance.health_check()
                return health_status.get('overall_status') in ['healthy', 'degraded']
            
            # 简单检查：获取服务状态
            status = instance.get_service_status()
            return status.get('is_initialized', False)
            
        except Exception as e:
            logger.warning(f"⚠️ 健康检查失败: {e}")
            return False
    
    @classmethod
    def _get_default_exchange_name(cls) -> str:
        """
        获取默认交易所名称
        Get default exchange name from configuration
        
        Returns:
            str: 默认交易所名称 / Default exchange name
        """
        try:
            settings = get_settings()
            
            # 尝试从配置中获取交易所提供商设置
            # 注意：这个设置将在后续任务中添加到配置文件中
            if hasattr(settings, 'exchange_provider'):
                return settings.exchange_provider.lower()
            
            # 临时回退逻辑：检查 Binance 配置是否完整
            if (hasattr(settings, 'binance_api_key') and settings.binance_api_key and 
                  hasattr(settings, 'binance_secret_key') and settings.binance_secret_key):
                logger.info("🔧 使用币安作为默认交易所（基于API配置）")
                return 'binance'
            else:
                # 最终回退：使用 Binance 作为默认值
                logger.info("🔧 使用币安作为默认交易所（默认选择）")
                return 'binance'
                
        except Exception as e:
            logger.warning(f"⚠️ 获取默认交易所配置失败，使用币安: {e}")
            return 'binance'
    
    @classmethod
    def get_factory_status(cls) -> Dict[str, Any]:
        """
        获取工厂状态信息
        Get factory status information
        
        Returns:
            Dict[str, Any]: 工厂状态信息 / Factory status information
        """
        return {
            'is_initialized': cls._is_initialized,
            'current_exchange': cls._current_exchange,
            'active_instances': list(cls._instances.keys()),
            'supported_exchanges': list(cls._exchange_registry.keys()),
            'statistics': cls._initialization_stats.copy(),
            'instance_count': len(cls._instances),
            'registry_count': len(cls._exchange_registry),
            'last_config_check': cls._last_config_check,
            'timestamp': datetime.now()
        }
    
    @classmethod
    def get_initialization_statistics(cls) -> Dict[str, Any]:
        """
        获取初始化统计信息
        Get initialization statistics
        
        Returns:
            Dict[str, Any]: 初始化统计信息 / Initialization statistics
        """
        return cls._initialization_stats.copy()
    
    @classmethod
    async def reload_configuration(cls) -> None:
        """
        重新加载配置
        Reload configuration
        
        检查配置变化并相应地调整交易所实例
        """
        try:
            logger.info("🔄 重新加载交易所配置...")
            
            # 获取新的默认交易所
            new_default_exchange = cls._get_default_exchange_name()
            
            # 如果默认交易所发生变化，切换到新的交易所
            if cls._current_exchange != new_default_exchange:
                logger.info(f"🔄 检测到配置变化，切换交易所: {cls._current_exchange} -> {new_default_exchange}")
                await cls.switch_exchange(new_default_exchange)
            
            cls._last_config_check = datetime.now()
            logger.info("✅ 配置重新加载完成")
            
        except Exception as e:
            logger.error(f"❌ 重新加载配置失败: {e}")
            raise TradingToolError(f"配置重新加载失败: {e}")
    
    @classmethod
    async def initialize_factory(cls) -> None:
        """
        初始化工厂
        Initialize factory
        
        执行工厂的初始化设置，如注册默认交易所等
        """
        if cls._is_initialized:
            return
        
        try:
            logger.info("🏗️ 初始化交易所工厂...")
            
            # 注册币安交易所
            await cls._register_binance_exchange()
            
            cls._is_initialized = True
            cls._last_config_check = datetime.now()
            
            logger.info("✅ 交易所工厂初始化完成")
            
        except Exception as e:
            logger.error(f"❌ 交易所工厂初始化失败: {e}")
            raise TradingToolError(f"交易所工厂初始化失败: {e}")
    
    @classmethod
    async def _register_binance_exchange(cls) -> None:
        """
        注册币安交易所
        Register Binance exchange
        """
        try:
            # 动态导入币安混合服务
            from app.services.exchanges.binance.binance_hybrid_service import BinanceHybridService
            
            # 注册币安交易所
            cls.register_exchange('binance', BinanceHybridService)
            
            logger.info("✅ 币安交易所注册成功")
            
        except ImportError as e:
            logger.warning(f"⚠️ 导入币安服务失败: {e}")
            logger.info("💡 币安服务可能尚未实现，跳过注册")
        except Exception as e:
            logger.error(f"❌ 注册币安交易所失败: {e}")
            raise TradingToolError(f"币安交易所注册失败: {e}")


# 便利函数 Convenience Functions

async def get_default_exchange() -> ExchangeInterface:
    """
    获取默认交易所实例
    Get default exchange instance
    
    Returns:
        ExchangeInterface: 默认交易所实例 / Default exchange instance
    """
    return await ExchangeFactory.get_exchange()

async def get_exchange_by_name(exchange_name: str) -> ExchangeInterface:
    """
    根据名称获取交易所实例
    Get exchange instance by name
    
    Args:
        exchange_name: 交易所名称 / Exchange name
        
    Returns:
        ExchangeInterface: 交易所实例 / Exchange instance
    """
    return await ExchangeFactory.get_exchange(exchange_name)

async def cleanup_all_exchanges() -> None:
    """
    清理所有交易所实例
    Cleanup all exchange instances
    """
    await ExchangeFactory.cleanup_all()

def get_supported_exchanges() -> List[str]:
    """
    获取支持的交易所列表
    Get list of supported exchanges
    
    Returns:
        List[str]: 支持的交易所名称列表 / List of supported exchange names
    """
    return ExchangeFactory.get_supported_exchanges()

def register_exchange(name: str, exchange_class: Type[ExchangeInterface]) -> None:
    """
    注册交易所类
    Register exchange class
    
    Args:
        name: 交易所名称 / Exchange name
        exchange_class: 交易所类 / Exchange class
    """
    ExchangeFactory.register_exchange(name, exchange_class)
