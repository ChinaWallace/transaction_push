# -*- coding: utf-8 -*-
"""
交易所服务管理器
Exchange Service Manager - 统一管理交易所服务的获取和使用
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.exchanges.factory import ExchangeFactory
from app.services.exchanges.base.exchange_interface import ExchangeInterface
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)

# 全局服务实例缓存
_current_exchange_service: Optional[ExchangeInterface] = None
_service_lock = asyncio.Lock()


async def get_exchange_service() -> ExchangeInterface:
    """
    获取当前配置的交易所服务
    Get current configured exchange service
    
    Returns:
        ExchangeInterface: 交易所服务实例
        
    Raises:
        TradingToolError: 获取服务失败时抛出
    """
    global _current_exchange_service
    
    async with _service_lock:
        try:
            # 确保工厂已初始化
            await ExchangeFactory.initialize_factory()
            
            # 获取配置的交易所
            settings = get_settings()
            exchange_provider = getattr(settings, 'exchange_provider', 'binance').lower()
            
            logger.info(f"🔧 使用配置的交易所: {exchange_provider}")
            
            # 通过工厂获取交易所实例
            exchange_service = await ExchangeFactory.get_exchange(exchange_provider)
            
            # 缓存服务实例
            _current_exchange_service = exchange_service
            
            return exchange_service
            
        except Exception as e:
            logger.error(f"❌ 获取交易所服务失败: {e}")
            raise TradingToolError(f"无法获取交易所服务: {e}")


async def get_okx_service():
    """
    获取OKX服务 - 兼容性函数
    Get OKX service - compatibility function
    
    注意：这个函数仅用于向后兼容，新代码应该使用 get_exchange_service()
    """
    logger.warning("⚠️ 使用了已弃用的 get_okx_service()，建议使用 get_exchange_service()")
    
    # 检查当前配置是否为OKX
    settings = get_settings()
    exchange_provider = getattr(settings, 'exchange_provider', 'binance').lower()
    
    if exchange_provider == 'okx':
        return await get_exchange_service()
    else:
        logger.warning(f"⚠️ 当前配置为 {exchange_provider}，但代码请求OKX服务")
        # 仍然返回配置的交易所服务
        return await get_exchange_service()


async def get_binance_service():
    """
    获取币安服务 - 兼容性函数
    Get Binance service - compatibility function
    
    注意：这个函数仅用于向后兼容，新代码应该使用 get_exchange_service()
    """
    logger.warning("⚠️ 使用了已弃用的 get_binance_service()，建议使用 get_exchange_service()")
    
    # 检查当前配置是否为币安
    settings = get_settings()
    exchange_provider = getattr(settings, 'exchange_provider', 'binance').lower()
    
    if exchange_provider == 'binance':
        return await get_exchange_service()
    else:
        logger.warning(f"⚠️ 当前配置为 {exchange_provider}，但代码请求币安服务")
        # 仍然返回配置的交易所服务
        return await get_exchange_service()


async def cleanup_exchange_service():
    """
    清理交易所服务
    Cleanup exchange service
    """
    global _current_exchange_service
    
    async with _service_lock:
        try:
            if _current_exchange_service:
                logger.info("🧹 清理交易所服务...")
                await ExchangeFactory.cleanup_all()
                _current_exchange_service = None
                logger.info("✅ 交易所服务清理完成")
        except Exception as e:
            logger.error(f"❌ 清理交易所服务失败: {e}")


def get_current_exchange_name() -> str:
    """
    获取当前配置的交易所名称
    Get current configured exchange name
    
    Returns:
        str: 交易所名称
    """
    settings = get_settings()
    return getattr(settings, 'exchange_provider', 'binance').lower()


def is_okx_configured() -> bool:
    """
    检查是否配置为使用OKX
    Check if configured to use OKX
    
    Returns:
        bool: 是否使用OKX
    """
    return get_current_exchange_name() == 'okx'


def is_binance_configured() -> bool:
    """
    检查是否配置为使用币安
    Check if configured to use Binance
    
    Returns:
        bool: 是否使用币安
    """
    return get_current_exchange_name() == 'binance'


async def switch_exchange(new_exchange: str) -> ExchangeInterface:
    """
    切换到新的交易所
    Switch to new exchange
    
    Args:
        new_exchange: 新交易所名称
        
    Returns:
        ExchangeInterface: 新的交易所服务实例
    """
    global _current_exchange_service
    
    async with _service_lock:
        try:
            logger.info(f"🔄 切换交易所到: {new_exchange}")
            
            # 通过工厂切换交易所
            new_service = await ExchangeFactory.switch_exchange(new_exchange)
            
            # 更新缓存
            _current_exchange_service = new_service
            
            logger.info(f"✅ 交易所切换完成: {new_exchange}")
            return new_service
            
        except Exception as e:
            logger.error(f"❌ 切换交易所失败: {e}")
            raise TradingToolError(f"切换交易所失败: {e}")


def get_service_status() -> Dict[str, Any]:
    """
    获取服务状态
    Get service status
    
    Returns:
        Dict[str, Any]: 服务状态信息
    """
    return {
        'current_exchange': get_current_exchange_name(),
        'is_okx_configured': is_okx_configured(),
        'is_binance_configured': is_binance_configured(),
        'has_active_service': _current_exchange_service is not None,
        'factory_status': ExchangeFactory.get_factory_status(),
        'timestamp': datetime.now()
    }