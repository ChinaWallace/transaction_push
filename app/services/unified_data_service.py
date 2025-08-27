# -*- coding: utf-8 -*-
"""
统一数据服务
Unified Data Service - 提供统一的数据获取、缓存和共享机制
"""

import asyncio
import time
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import pandas as pd

from app.core.logging import get_logger
from app.core.config import get_settings
from app.data.data_cache import DataCache
from app.services.binance_service import BinanceService
from app.services.okx_service import OKXService
from app.utils.exceptions import DataNotFoundError, ServiceUnavailableError

logger = get_logger(__name__)
settings = get_settings()


class DataSource(Enum):
    """数据源枚举"""
    BINANCE = "binance"
    OKX = "okx"
    AUTO = "auto"  # 自动选择最佳数据源


@dataclass
class DataRequest:
    """数据请求配置"""
    symbol: str
    timeframe: str = "1h"
    limit: int = 500
    source: DataSource = DataSource.AUTO
    use_cache: bool = True
    cache_ttl_minutes: int = 2


@dataclass
class MarketDataResult:
    """市场数据结果"""
    data: pd.DataFrame
    source: str
    timestamp: datetime
    cached: bool
    symbol: str
    timeframe: str


class UnifiedDataService:
    """
    统一数据服务
    
    功能特性：
    1. 统一的数据获取接口
    2. 智能缓存管理
    3. 多数据源支持
    4. 自动故障转移
    5. 数据共享机制
    """
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.cache = DataCache()
        
        # 数据源优先级配置
        self.source_priority = [DataSource.BINANCE, DataSource.OKX]
        
        # 服务实例（延迟初始化）
        self._binance_service = None
        self._okx_service = None
        
        # 数据源健康状态
        self._source_health = {
            DataSource.BINANCE: {"healthy": True, "last_check": None, "error_count": 0},
            DataSource.OKX: {"healthy": True, "last_check": None, "error_count": 0}
        }
        
        # 请求统计
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "source_requests": {source.value: 0 for source in DataSource if source != DataSource.AUTO},
            "errors": {"total": 0, "by_source": {source.value: 0 for source in DataSource if source != DataSource.AUTO}}
        }
        
        # 数据共享存储（供多服务共享的热点数据）
        self._shared_data = {}
        self._shared_data_lock = asyncio.Lock()
    
    async def _get_binance_service(self) -> BinanceService:
        """获取币安服务实例"""
        if self._binance_service is None:
            self._binance_service = BinanceService()
        return self._binance_service
    
    async def _get_okx_service(self) -> OKXService:
        """获取OKX服务实例"""
        if self._okx_service is None:
            self._okx_service = OKXService()
        return self._okx_service
    
    async def get_kline_data(self, request: DataRequest) -> MarketDataResult:
        """
        获取K线数据 - 统一入口
        
        Args:
            request: 数据请求配置
            
        Returns:
            市场数据结果
        """
        self._stats["total_requests"] += 1
        start_time = time.time()
        
        try:
            # 检查缓存
            if request.use_cache:
                cached_data = await self._get_cached_data(request)
                if cached_data is not None:
                    self._stats["cache_hits"] += 1
                    self.logger.debug(f"✅ 缓存命中: {request.symbol} {request.timeframe}")
                    return MarketDataResult(
                        data=cached_data,
                        source="cache",
                        timestamp=datetime.now(),
                        cached=True,
                        symbol=request.symbol,
                        timeframe=request.timeframe
                    )
            
            self._stats["cache_misses"] += 1
            
            # 确定数据源
            data_source = await self._determine_data_source(request.source)
            
            # 获取数据
            data = await self._fetch_from_source(data_source, request)
            
            # 缓存数据
            if request.use_cache and not data.empty:
                await self._cache_data(request, data)
            
            # 更新共享数据（热点数据）
            await self._update_shared_data(request, data)
            
            elapsed_time = time.time() - start_time
            self.logger.info(f"🎯 数据获取完成: {request.symbol} {request.timeframe} "
                           f"from {data_source.value} ({elapsed_time:.2f}s)")
            
            return MarketDataResult(
                data=data,
                source=data_source.value,
                timestamp=datetime.now(),
                cached=False,
                symbol=request.symbol,
                timeframe=request.timeframe
            )
            
        except Exception as e:
            self._stats["errors"]["total"] += 1
            self.logger.error(f"❌ 数据获取失败: {request.symbol} {request.timeframe} - {e}")
            raise DataNotFoundError(f"获取 {request.symbol} 数据失败: {e}")
    
    async def _get_cached_data(self, request: DataRequest) -> Optional[pd.DataFrame]:
        """获取缓存数据"""
        try:
            # 构建缓存键
            cache_key = f"{request.symbol}_{request.timeframe}_{request.limit}"
            
            # 检查内存缓存
            if cache_key in self.cache.memory_cache:
                cache_entry = self.cache.memory_cache[cache_key]
                if self.cache._is_cache_valid(cache_entry):
                    return cache_entry['data']
            
            # 检查磁盘缓存
            cached_data = await self.cache.get_ohlcv(
                symbol=request.symbol,
                timeframe=request.timeframe,
                exchange="unified",  # 使用统一标识
                limit=request.limit
            )
            
            return cached_data
            
        except Exception as e:
            self.logger.warning(f"获取缓存数据失败: {e}")
            return None
    
    async def _cache_data(self, request: DataRequest, data: pd.DataFrame):
        """缓存数据"""
        try:
            await self.cache.set_ohlcv(
                symbol=request.symbol,
                timeframe=request.timeframe,
                exchange="unified",
                data=data,
                limit=request.limit
            )
            self.logger.debug(f"💾 数据已缓存: {request.symbol} {request.timeframe}")
            
        except Exception as e:
            self.logger.warning(f"缓存数据失败: {e}")
    
    async def _determine_data_source(self, preferred_source: DataSource) -> DataSource:
        """确定最佳数据源"""
        if preferred_source != DataSource.AUTO:
            # 检查指定数据源的健康状态
            if self._source_health[preferred_source]["healthy"]:
                return preferred_source
            else:
                self.logger.warning(f"指定数据源 {preferred_source.value} 不健康，使用备用数据源")
        
        # 按优先级选择健康的数据源
        for source in self.source_priority:
            if self._source_health[source]["healthy"]:
                return source
        
        # 如果所有数据源都不健康，选择错误最少的
        best_source = min(
            self.source_priority,
            key=lambda s: self._source_health[s]["error_count"]
        )
        
        self.logger.warning(f"所有数据源都有问题，选择错误最少的: {best_source.value}")
        return best_source
    
    async def _fetch_from_source(self, source: DataSource, request: DataRequest) -> pd.DataFrame:
        """从指定数据源获取数据"""
        self._stats["source_requests"][source.value] += 1
        
        try:
            if source == DataSource.BINANCE:
                service = await self._get_binance_service()
                klines = await service.get_kline_data(
                    symbol=request.symbol.replace('-SWAP', '').replace('-', ''),  # 币安格式转换
                    interval=request.timeframe,
                    limit=request.limit
                )
                
                # 转换为DataFrame（这里需要根据实际数据格式调整）
                if klines:
                    data = pd.DataFrame([{
                        'timestamp': k['open_time'],
                        'open': float(k['open_price']),
                        'high': float(k['high_price']),
                        'low': float(k['low_price']),
                        'close': float(k['close_price']),
                        'volume': float(k['volume'])
                    } for k in klines])
                    data.set_index('timestamp', inplace=True)
                    self._mark_source_healthy(source)
                    return data
                
            elif source == DataSource.OKX:
                async with await self._get_okx_service() as service:
                    klines = await service.get_kline_data(
                        symbol=request.symbol,
                        timeframe=request.timeframe,
                        limit=request.limit
                    )
                    
                    if klines:
                        data = pd.DataFrame([{
                            'timestamp': pd.to_datetime(k['timestamp'], unit='ms'),
                            'open': k['open'],
                            'high': k['high'],
                            'low': k['low'],
                            'close': k['close'],
                            'volume': k['volume']
                        } for k in klines])
                        data.set_index('timestamp', inplace=True)
                        self._mark_source_healthy(source)
                        return data
            
            # 如果没有数据，标记为轻微错误
            self._mark_source_error(source, is_critical=False)
            return pd.DataFrame()
            
        except Exception as e:
            self._mark_source_error(source, is_critical=True)
            self._stats["errors"]["by_source"][source.value] += 1
            self.logger.error(f"从 {source.value} 获取数据失败: {e}")
            raise
    
    def _mark_source_healthy(self, source: DataSource):
        """标记数据源为健康"""
        health = self._source_health[source]
        health["healthy"] = True
        health["last_check"] = datetime.now()
        health["error_count"] = max(0, health["error_count"] - 1)  # 逐渐恢复
    
    def _mark_source_error(self, source: DataSource, is_critical: bool = True):
        """标记数据源错误"""
        health = self._source_health[source]
        health["error_count"] += 1 if is_critical else 0.5
        health["last_check"] = datetime.now()
        
        # 错误超过阈值时标记为不健康
        if health["error_count"] >= 3:
            health["healthy"] = False
            self.logger.warning(f"数据源 {source.value} 标记为不健康")
    
    async def _update_shared_data(self, request: DataRequest, data: pd.DataFrame):
        """更新共享数据存储"""
        try:
            # 只缓存热点数据（主要监控币种的1小时数据）
            if (request.symbol in settings.monitored_symbols and 
                request.timeframe in ['1h', '4h'] and 
                not data.empty):
                
                async with self._shared_data_lock:
                    key = f"{request.symbol}_{request.timeframe}"
                    self._shared_data[key] = {
                        'data': data.copy(),
                        'timestamp': datetime.now(),
                        'symbol': request.symbol,
                        'timeframe': request.timeframe
                    }
                    
                    self.logger.debug(f"📊 共享数据已更新: {key}")
        
        except Exception as e:
            self.logger.warning(f"更新共享数据失败: {e}")
    
    async def get_shared_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """获取共享数据"""
        try:
            async with self._shared_data_lock:
                key = f"{symbol}_{timeframe}"
                if key in self._shared_data:
                    shared_entry = self._shared_data[key]
                    
                    # 检查数据是否还新鲜（5分钟内）
                    age = datetime.now() - shared_entry['timestamp']
                    if age < timedelta(minutes=5):
                        self.logger.debug(f"📈 共享数据命中: {key}")
                        return shared_entry['data'].copy()
                    else:
                        # 删除过期数据
                        del self._shared_data[key]
                        
            return None
            
        except Exception as e:
            self.logger.warning(f"获取共享数据失败: {e}")
            return None
    
    async def batch_get_kline_data(self, requests: List[DataRequest]) -> List[MarketDataResult]:
        """批量获取K线数据"""
        self.logger.info(f"🚀 开始批量获取数据，总计 {len(requests)} 个请求")
        
        # 并发获取数据
        tasks = [self.get_kline_data(request) for request in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"批量请求失败: {requests[i].symbol} - {result}")
            else:
                successful_results.append(result)
        
        self.logger.debug(f"✅ 批量获取完成: {len(successful_results)}/{len(requests)} 成功")
        return successful_results
    
    async def get_funding_rates(self, symbols: List[str]) -> Dict[str, Any]:
        """获取资金费率数据（统一接口）"""
        try:
            # 优先使用OKX（支持更多币种）
            async with await self._get_okx_service() as okx_service:
                rates = await okx_service.get_batch_funding_rates(symbols)
                
                # 转换为统一格式
                result = {}
                for rate in rates:
                    if rate and 'symbol' in rate:
                        result[rate['symbol']] = {
                            'funding_rate': rate['funding_rate'],
                            'next_funding_time': rate.get('next_funding_time'),
                            'source': 'okx',
                            'timestamp': datetime.now()
                        }
                
                self.logger.info(f"📊 获取费率数据: {len(result)} 个币种")
                return result
                
        except Exception as e:
            self.logger.error(f"获取费率数据失败: {e}")
            return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        cache_hit_rate = 0
        if self._stats["total_requests"] > 0:
            cache_hit_rate = self._stats["cache_hits"] / self._stats["total_requests"]
        
        return {
            "requests": self._stats,
            "cache_hit_rate": f"{cache_hit_rate:.2%}",
            "source_health": self._source_health,
            "shared_data_count": len(self._shared_data),
            "cache_stats": self.cache.get_cache_stats()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        health_status = {"overall": "healthy", "sources": {}}
        
        try:
            # 检查币安服务
            binance_service = await self._get_binance_service()
            binance_healthy = await binance_service.health_check()
            health_status["sources"]["binance"] = "healthy" if binance_healthy else "unhealthy"
            
            # 检查OKX服务
            async with await self._get_okx_service() as okx_service:
                okx_healthy = await okx_service.health_check()
                health_status["sources"]["okx"] = "healthy" if okx_healthy else "unhealthy"
            
            # 更新健康状态
            self._source_health[DataSource.BINANCE]["healthy"] = binance_healthy
            self._source_health[DataSource.OKX]["healthy"] = okx_healthy
            
            # 判断整体健康状态
            if not binance_healthy and not okx_healthy:
                health_status["overall"] = "critical"
            elif not binance_healthy or not okx_healthy:
                health_status["overall"] = "degraded"
            
        except Exception as e:
            self.logger.error(f"健康检查失败: {e}")
            health_status["overall"] = "error"
            health_status["error"] = str(e)
        
        return health_status
    
    async def cleanup(self):
        """清理资源"""
        try:
            # 清理共享数据
            async with self._shared_data_lock:
                self._shared_data.clear()
            
            # 清理缓存
            await self.cache.invalidate()
            
            self.logger.info("🧹 统一数据服务资源已清理")
            
        except Exception as e:
            self.logger.error(f"清理资源失败: {e}")


# 全局统一数据服务实例
_unified_data_service = None


async def get_unified_data_service() -> UnifiedDataService:
    """获取统一数据服务实例"""
    global _unified_data_service
    if _unified_data_service is None:
        _unified_data_service = UnifiedDataService()
    return _unified_data_service


# 便捷函数
async def get_market_data(symbol: str, timeframe: str = "1h", 
                         limit: int = 500, source: DataSource = DataSource.AUTO) -> MarketDataResult:
    """便捷函数：获取市场数据"""
    service = await get_unified_data_service()
    request = DataRequest(symbol=symbol, timeframe=timeframe, limit=limit, source=source)
    return await service.get_kline_data(request)


async def get_shared_market_data(symbol: str, timeframe: str = "1h") -> Optional[pd.DataFrame]:
    """便捷函数：获取共享市场数据"""
    service = await get_unified_data_service()
    return await service.get_shared_data(symbol, timeframe)
