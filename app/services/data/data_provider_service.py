# -*- coding: utf-8 -*-
"""
数据提供服务模块
Data Provider Service Module

提供统一的数据获取接口，整合多个数据源
Provides unified data access interface integrating multiple data sources
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.data.cache_service import get_cache_service

logger = get_logger(__name__)


class DataProviderService:
    """
    数据提供服务
    Data Provider Service - 统一数据获取接口
    """
    
    def __init__(self):
        """初始化数据提供服务"""
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 服务依赖
        self.cache_service = None
        self.exchange_service = None
        
        # 配置
        self.cache_enabled = True
        self.default_cache_ttl = 60  # 1分钟缓存
        
        self.initialized = False
    
    async def initialize(self) -> None:
        """初始化数据提供服务"""
        if self.initialized:
            return
        
        try:
            # 初始化缓存服务
            self.cache_service = await get_cache_service()
            
            # 延迟导入交易所服务，避免循环依赖
            try:
                from app.services.exchanges.service_manager import get_exchange_service
                self.exchange_service = await get_exchange_service()
            except ImportError:
                self.logger.warning("⚠️ 交易所服务未找到，部分功能可能不可用")
            
            self.initialized = True
            self.logger.info("✅ 数据提供服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 数据提供服务初始化失败: {e}")
            raise
    
    async def get_market_data(
        self, 
        symbol: str, 
        use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        获取市场数据
        Get market data for symbol
        
        Args:
            symbol: 交易对符号
            use_cache: 是否使用缓存
            
        Returns:
            市场数据字典
        """
        try:
            cache_key = f"market_data:{symbol}"
            
            # 尝试从缓存获取
            if use_cache and self.cache_service:
                cached_data = await self.cache_service.get(cache_key)
                if cached_data:
                    self.logger.debug(f"📋 市场数据缓存命中: {symbol}")
                    return cached_data
            
            # 从交易所获取数据
            if self.exchange_service:
                market_data = await self._fetch_from_exchange(symbol)
                
                # 缓存数据
                if market_data and use_cache and self.cache_service:
                    await self.cache_service.set(
                        cache_key, 
                        market_data, 
                        self.default_cache_ttl
                    )
                
                return market_data
            
            # 如果没有交易所服务，返回模拟数据
            return await self._get_mock_market_data(symbol)
            
        except Exception as e:
            self.logger.error(f"获取市场数据失败 {symbol}: {e}")
            return None
    
    async def get_historical_data(
        self, 
        symbol: str, 
        timeframe: str = "1h",
        limit: int = 100,
        use_cache: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        获取历史数据
        Get historical data for symbol
        
        Args:
            symbol: 交易对符号
            timeframe: 时间周期
            limit: 数据条数
            use_cache: 是否使用缓存
            
        Returns:
            历史数据 DataFrame
        """
        try:
            cache_key = f"historical_data:{symbol}:{timeframe}:{limit}"
            
            # 尝试从缓存获取
            if use_cache and self.cache_service:
                cached_data = await self.cache_service.get(cache_key)
                if cached_data:
                    self.logger.debug(f"📋 历史数据缓存命中: {symbol}")
                    return pd.DataFrame(cached_data)
            
            # 从交易所获取历史数据
            if self.exchange_service:
                historical_data = await self._fetch_historical_from_exchange(
                    symbol, timeframe, limit
                )
                
                # 缓存数据
                if historical_data is not None and use_cache and self.cache_service:
                    await self.cache_service.set(
                        cache_key,
                        historical_data.to_dict('records'),
                        self.default_cache_ttl * 2  # 历史数据缓存更久
                    )
                
                return historical_data
            
            # 返回模拟历史数据
            return await self._get_mock_historical_data(symbol, limit)
            
        except Exception as e:
            self.logger.error(f"获取历史数据失败 {symbol}: {e}")
            return None
    
    async def get_symbol_info(
        self, 
        symbol: str, 
        use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        获取交易对信息
        Get symbol information
        
        Args:
            symbol: 交易对符号
            use_cache: 是否使用缓存
            
        Returns:
            交易对信息字典
        """
        try:
            cache_key = f"symbol_info:{symbol}"
            
            # 尝试从缓存获取
            if use_cache and self.cache_service:
                cached_data = await self.cache_service.get(cache_key)
                if cached_data:
                    return cached_data
            
            # 从交易所获取
            if self.exchange_service:
                symbol_info = await self.exchange_service.get_symbol_info(symbol)
                
                # 缓存数据（交易对信息变化较少，缓存更久）
                if symbol_info and use_cache and self.cache_service:
                    await self.cache_service.set(
                        cache_key,
                        symbol_info,
                        self.default_cache_ttl * 10  # 10分钟缓存
                    )
                
                return symbol_info
            
            # 返回模拟交易对信息
            return await self._get_mock_symbol_info(symbol)
            
        except Exception as e:
            self.logger.error(f"获取交易对信息失败 {symbol}: {e}")
            return None
    
    async def get_multiple_market_data(
        self, 
        symbols: List[str], 
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        批量获取市场数据
        Get market data for multiple symbols
        
        Args:
            symbols: 交易对符号列表
            use_cache: 是否使用缓存
            
        Returns:
            符号到市场数据的映射
        """
        try:
            # 并发获取多个交易对数据
            tasks = [
                self.get_market_data(symbol, use_cache) 
                for symbol in symbols
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 组织结果
            market_data = {}
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    self.logger.warning(f"获取 {symbol} 数据失败: {result}")
                    market_data[symbol] = None
                else:
                    market_data[symbol] = result
            
            return market_data
            
        except Exception as e:
            self.logger.error(f"批量获取市场数据失败: {e}")
            return {}
    
    async def _fetch_from_exchange(self, symbol: str) -> Optional[Dict[str, Any]]:
        """从交易所获取市场数据"""
        try:
            if hasattr(self.exchange_service, 'get_ticker'):
                return await self.exchange_service.get_ticker(symbol)
            elif hasattr(self.exchange_service, 'get_market_data'):
                return await self.exchange_service.get_market_data(symbol)
            else:
                self.logger.warning("交易所服务不支持获取市场数据")
                return None
        except Exception as e:
            self.logger.error(f"从交易所获取数据失败: {e}")
            return None
    
    async def _fetch_historical_from_exchange(
        self, 
        symbol: str, 
        timeframe: str, 
        limit: int
    ) -> Optional[pd.DataFrame]:
        """从交易所获取历史数据"""
        try:
            if hasattr(self.exchange_service, 'get_klines'):
                klines = await self.exchange_service.get_klines(symbol, timeframe, limit)
                if klines:
                    return pd.DataFrame(klines)
            return None
        except Exception as e:
            self.logger.error(f"从交易所获取历史数据失败: {e}")
            return None
    
    async def _get_mock_market_data(self, symbol: str) -> Dict[str, Any]:
        """获取模拟市场数据"""
        import random
        
        base_price = 50000 if "BTC" in symbol else 3000 if "ETH" in symbol else 100
        
        return {
            "symbol": symbol,
            "price": base_price + random.uniform(-1000, 1000),
            "volume_24h": random.uniform(1000000, 10000000),
            "change_24h": random.uniform(-0.1, 0.1),
            "high_24h": base_price + random.uniform(0, 2000),
            "low_24h": base_price - random.uniform(0, 2000),
            "timestamp": datetime.now().isoformat(),
            "source": "mock"
        }
    
    async def _get_mock_historical_data(self, symbol: str, limit: int) -> pd.DataFrame:
        """获取模拟历史数据"""
        import random
        
        base_price = 50000 if "BTC" in symbol else 3000 if "ETH" in symbol else 100
        
        data = []
        for i in range(limit):
            timestamp = datetime.now() - timedelta(hours=limit - i)
            price = base_price + random.uniform(-2000, 2000)
            
            data.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + random.uniform(0, 500),
                "low": price - random.uniform(0, 500),
                "close": price + random.uniform(-200, 200),
                "volume": random.uniform(100000, 1000000)
            })
        
        return pd.DataFrame(data)
    
    async def _get_mock_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """获取模拟交易对信息"""
        parts = symbol.split("-")
        base = parts[0] if len(parts) > 0 else "BTC"
        quote = parts[1] if len(parts) > 1 else "USDT"
        
        return {
            "symbol": symbol,
            "base_currency": base,
            "quote_currency": quote,
            "status": "active",
            "min_order_size": 0.001,
            "max_order_size": 1000000,
            "price_precision": 2,
            "size_precision": 6,
            "source": "mock"
        }
    
    async def clear_cache(self, pattern: Optional[str] = None) -> int:
        """
        清理缓存
        Clear cache
        
        Args:
            pattern: 缓存键匹配模式
            
        Returns:
            清理的缓存数量
        """
        if self.cache_service:
            return await self.cache_service.clear(pattern)
        return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        if self.cache_service:
            return await self.cache_service.get_cache_stats()
        return {}
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            checks = {
                "initialized": self.initialized,
                "cache_service": False,
                "exchange_service": False
            }
            
            # 检查缓存服务
            if self.cache_service:
                cache_health = await self.cache_service.health_check()
                checks["cache_service"] = cache_health.get("status") == "healthy"
            
            # 检查交易所服务
            if self.exchange_service:
                if hasattr(self.exchange_service, 'health_check'):
                    exchange_health = await self.exchange_service.health_check()
                    checks["exchange_service"] = exchange_health.get("healthy", False)
                else:
                    checks["exchange_service"] = True  # 假设可用
            
            # 测试数据获取
            test_symbol = "BTC-USDT-SWAP"
            test_data = await self.get_market_data(test_symbol, use_cache=False)
            checks["data_access"] = test_data is not None
            
            overall_healthy = all([
                checks["initialized"],
                checks["cache_service"],
                checks["data_access"]
            ])
            
            return {
                "status": "healthy" if overall_healthy else "degraded",
                "checks": checks
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "initialized": self.initialized
            }
    
    async def cleanup(self) -> None:
        """清理资源"""
        try:
            if self.cache_service:
                await self.cache_service.cleanup()
            
            self.logger.info("✅ 数据提供服务资源清理完成")
        except Exception as e:
            self.logger.error(f"❌ 数据提供服务清理失败: {e}")


# 全局数据提供服务实例
_data_provider_service: Optional[DataProviderService] = None


async def get_data_provider_service() -> DataProviderService:
    """
    获取数据提供服务实例 - 单例模式
    Get data provider service instance - singleton pattern
    
    Returns:
        DataProviderService: 数据提供服务实例
    """
    global _data_provider_service
    if _data_provider_service is None:
        _data_provider_service = DataProviderService()
        await _data_provider_service.initialize()
    return _data_provider_service