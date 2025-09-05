# -*- coding: utf-8 -*-
"""
交易所相关服务模块
Exchange services module
"""

import asyncio
from app.core.logging import get_logger
from .base import ExchangeInterface, HybridServiceBase
from .factory import (
    ExchangeFactory,
    get_default_exchange,
    get_exchange_by_name,
    cleanup_all_exchanges,
    get_supported_exchanges,
    register_exchange
)
from .data_converter_factory import (
    DataConverterFactory,
    get_data_converter,
    convert_ticker_data,
    convert_kline_data,
    convert_funding_rate_data
)

logger = get_logger(__name__)

# 自动初始化工厂
_factory_initialized = False

async def initialize_exchanges():
    """初始化交易所服务"""
    global _factory_initialized
    if not _factory_initialized:
        try:
            await ExchangeFactory.initialize_factory()
            _factory_initialized = True
            logger.info("✅ 交易所服务初始化完成")
        except Exception as e:
            logger.error(f"❌ 交易所服务初始化失败: {e}")
            raise

def ensure_factory_initialized():
    """确保工厂已初始化（同步版本）"""
    global _factory_initialized
    if not _factory_initialized:
        try:
            # 在事件循环中运行初始化
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建任务
                asyncio.create_task(initialize_exchanges())
            else:
                # 如果没有事件循环，直接运行
                asyncio.run(initialize_exchanges())
        except Exception as e:
            logger.error(f"❌ 同步初始化交易所服务失败: {e}")

# 便利函数 - 快速获取特定交易所服务
def get_okx_service():
    """获取OKX服务的便利函数"""
    try:
        return get_exchange_by_name('okx')
    except Exception as e:
        logger.error(f"❌ 获取OKX服务失败: {e}")
        return None

def get_binance_service():
    """获取币安服务的便利函数"""
    try:
        return get_exchange_by_name('binance')
    except Exception as e:
        logger.error(f"❌ 获取币安服务失败: {e}")
        return None

__all__ = [
    # 抽象基类
    'ExchangeInterface',
    'HybridServiceBase',
    
    # 工厂类和便利函数
    'ExchangeFactory',
    'get_default_exchange',
    'get_exchange_by_name',
    'cleanup_all_exchanges',
    'get_supported_exchanges',
    'register_exchange',
    
    # 数据转换器
    'DataConverterFactory',
    'get_data_converter',
    'convert_ticker_data',
    'convert_kline_data',
    'convert_funding_rate_data',
    
    # 初始化函数
    'initialize_exchanges',
    'ensure_factory_initialized',
    
    # 便利函数
    'get_okx_service',
    'get_binance_service'
]