# -*- coding: utf-8 -*-
"""
数据提供者
Unified data provider for multiple exchanges and timeframes
"""

import asyncio
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from app.core.logging import get_logger
from app.services.binance_service import BinanceService
from app.data.data_converter import DataConverter
from app.data.data_cache import DataCache
from app.utils.exceptions import DataNotFoundError
# Temporarily commented out to avoid circular import
# from app.services.data.unified_data_service import get_unified_data_service, DataRequest, DataSource

logger = get_logger(__name__)


class BaseDataProvider(ABC):
    """基础数据提供者抽象类"""
    
    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, 
                       since: Optional[datetime] = None,
                       limit: int = 500) -> pd.DataFrame:
        """获取OHLCV数据"""
    
    @abstractmethod
    async def get_available_symbols(self) -> List[str]:
        """获取可用交易对"""


class BinanceDataProvider(BaseDataProvider):
    """币安数据提供者"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.converter = DataConverter()
    
    async def get_ohlcv(self, symbol: str, timeframe: str,
                       since: Optional[datetime] = None,
                       limit: int = 500) -> pd.DataFrame:
        """从币安获取OHLCV数据"""
        try:
            # 获取K线数据
            klines = await self.binance_service.get_kline_data(
                symbol=symbol,
                interval=timeframe,
                limit=limit,
                start_time=since
            )
            
            if not klines:
                raise DataNotFoundError(f"No data found for {symbol} {timeframe}")
            
            # 转换为DataFrame
            df = self.converter.klines_to_dataframe(klines)
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get OHLCV data for {symbol}: {e}")
            raise
    
    async def get_available_symbols(self) -> List[str]:
        """获取币安可用交易对"""
        return await self.binance_service.get_active_symbols()


class DataProvider:
    """
    统一数据提供者
    支持多个交易所和数据源
    """
    
    def __init__(self, use_cache: bool = True):
        self.providers = {
            'binance': BinanceDataProvider()
        }
        self._use_cache = use_cache
        self._cache = None
        self.converter = DataConverter()
        self._unified_service = None  # 统一数据服务
    
    @property
    def cache(self):
        """延迟初始化缓存"""
        if self._use_cache and self._cache is None:
            self._cache = DataCache()
        return self._cache
    
    async def _get_unified_service(self):
        """获取统一数据服务"""
        if self._unified_service is None:
            self._unified_service = await get_unified_data_service()
        return self._unified_service
    
    async def get_ohlcv(self, symbol: str, timeframe: str,
                       exchange: str = 'auto',
                       since: Optional[datetime] = None,
                       limit: int = 500,
                       use_cache: bool = True) -> pd.DataFrame:
        """
        获取OHLCV数据 - 使用统一数据服务
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            exchange: 交易所 ('auto', 'binance', 'okx')
            since: 开始时间
            limit: 数据条数
            use_cache: 是否使用缓存
            
        Returns:
            OHLCV DataFrame
        """
        try:
            # 使用统一数据服务获取数据
            unified_service = await self._get_unified_service()
            
            # 转换交易所参数
            if exchange == 'auto':
                source = DataSource.AUTO
            elif exchange == 'binance':
                source = DataSource.BINANCE
            elif exchange == 'okx':
                source = DataSource.OKX
            else:
                # 回退到传统方式
                return await self._get_ohlcv_legacy(symbol, timeframe, exchange, since, limit, use_cache)
            
            # 创建数据请求
            request = DataRequest(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                source=source,
                use_cache=use_cache
            )
            
            # 获取数据
            result = await unified_service.get_kline_data(request)
            
            logger.info(f"✅ 获取数据: {symbol} {timeframe} from {result.source} "
                       f"({'缓存' if result.cached else '实时'})")
            
            return result.data
            
        except Exception as e:
            logger.error(f"❌ 获取OHLCV数据失败: {e}")
            # 回退到传统方式
            try:
                return await self._get_ohlcv_legacy(symbol, timeframe, exchange, since, limit, use_cache)
            except Exception as fallback_error:
                logger.error(f"❌ 回退方式也失败: {fallback_error}")
                raise DataNotFoundError(f"获取 {symbol} 数据失败: {e}")
    
    async def _get_ohlcv_legacy(self, symbol: str, timeframe: str,
                               exchange: str = 'binance',
                               since: Optional[datetime] = None,
                               limit: int = 500,
                               use_cache: bool = True) -> pd.DataFrame:
        """传统方式获取OHLCV数据（回退机制）"""
        try:
            # 检查缓存
            if use_cache and self.cache:
                cached_data = await self.cache.get_ohlcv(
                    symbol, timeframe, exchange, since, limit
                )
                if cached_data is not None:
                    logger.debug(f"Cache hit for {symbol} {timeframe}")
                    return cached_data
            
            # 从数据提供者获取数据
            if exchange not in self.providers:
                raise ValueError(f"Unsupported exchange: {exchange}")
            
            provider = self.providers[exchange]
            df = await provider.get_ohlcv(symbol, timeframe, since, limit)
            
            # 数据验证和清洗
            df = self._validate_and_clean_data(df)
            
            # 缓存数据
            if use_cache and self.cache:
                await self.cache.set_ohlcv(
                    symbol, timeframe, exchange, df, since, limit
                )
            
            logger.info(f"Retrieved {len(df)} rows of {symbol} {timeframe} data (legacy)")
            return df
            
        except Exception as e:
            logger.error(f"Legacy data fetch failed: {e}")
            raise
    
    async def get_multi_timeframe_data(self, symbol: str,
                                     timeframes: List[str],
                                     exchange: str = 'auto',
                                     limit: int = 500) -> Dict[str, pd.DataFrame]:
        """
        获取多时间周期数据 - 使用统一数据服务批量优化
        
        Args:
            symbol: 交易对
            timeframes: 时间周期列表
            exchange: 交易所
            limit: 数据条数
            
        Returns:
            时间周期数据字典
        """
        try:
            # 使用统一数据服务的批量获取功能
            unified_service = await self._get_unified_service()
            
            # 转换交易所参数
            if exchange == 'auto':
                source = DataSource.AUTO
            elif exchange == 'binance':
                source = DataSource.BINANCE
            elif exchange == 'okx':
                source = DataSource.OKX
            else:
                source = DataSource.AUTO
            
            # 创建批量请求
            requests = []
            for timeframe in timeframes:
                request = DataRequest(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                    source=source,
                    use_cache=True
                )
                requests.append(request)
            
            # 批量获取数据
            results = await unified_service.batch_get_kline_data(requests)
            
            # 构建结果字典
            timeframe_data = {}
            for result in results:
                timeframe_data[result.timeframe] = result.data
            
            # 确保所有时间周期都有数据（即使是空DataFrame）
            for timeframe in timeframes:
                if timeframe not in timeframe_data:
                    timeframe_data[timeframe] = pd.DataFrame()
            
            logger.info(f"✅ 多周期数据获取完成: {symbol} {len(timeframe_data)} 个周期")
            return timeframe_data
            
        except Exception as e:
            logger.error(f"❌ 批量获取多周期数据失败: {e}")
            # 回退到传统方式
            return await self._get_multi_timeframe_data_legacy(symbol, timeframes, exchange, limit)
    
    async def _get_multi_timeframe_data_legacy(self, symbol: str, timeframes: List[str],
                                             exchange: str, limit: int) -> Dict[str, pd.DataFrame]:
        """传统方式获取多周期数据（回退机制）"""
        try:
            tasks = []
            for timeframe in timeframes:
                task = self._get_ohlcv_legacy(symbol, timeframe, exchange, limit=limit)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            timeframe_data = {}
            for i, timeframe in enumerate(timeframes):
                result = results[i]
                if isinstance(result, Exception):
                    logger.warning(f"Failed to get {timeframe} data: {result}")
                    timeframe_data[timeframe] = pd.DataFrame()
                else:
                    timeframe_data[timeframe] = result
            
            return timeframe_data
            
        except Exception as e:
            logger.error(f"Legacy multi-timeframe fetch failed: {e}")
            raise
    
    async def get_historical_data(self, symbol: str, timeframe: str,
                                days: int = 30,
                                exchange: str = 'binance') -> pd.DataFrame:
        """
        获取历史数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            days: 历史天数
            exchange: 交易所
            
        Returns:
            历史数据DataFrame
        """
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            # 计算需要的数据条数
            timeframe_minutes = self._timeframe_to_minutes(timeframe)
            total_minutes = days * 24 * 60
            estimated_limit = min(int(total_minutes / timeframe_minutes), 1500)
            
            df = await self.get_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                exchange=exchange,
                since=start_time,
                limit=estimated_limit
            )
            
            # 过滤时间范围
            if not df.empty:
                df = df[df.index >= start_time]
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get historical data: {e}")
            raise
    
    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """将时间周期转换为分钟数"""
        timeframe_map = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720,
            '1d': 1440, '3d': 4320, '1w': 10080, '1M': 43200
        }
        return timeframe_map.get(timeframe, 60)
    
    def _validate_and_clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """验证和清洗数据"""
        if df.empty:
            return df
        
        # 检查必需列
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")
        
        # 数据类型转换
        for col in required_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 删除无效数据
        df = df.dropna(subset=required_columns)
        
        # 验证OHLC逻辑
        invalid_ohlc = (
            (df['high'] < df['low']) |
            (df['high'] < df['open']) |
            (df['high'] < df['close']) |
            (df['low'] > df['open']) |
            (df['low'] > df['close'])
        )
        
        if invalid_ohlc.any():
            logger.warning(f"Found {invalid_ohlc.sum()} invalid OHLC rows, removing...")
            df = df[~invalid_ohlc]
        
        # 按时间排序
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp')
        elif df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
            df = df.sort_index()
        
        return df
    
    async def get_available_symbols(self, exchange: str = 'binance') -> List[str]:
        """获取可用交易对"""
        if exchange not in self.providers:
            raise ValueError(f"Unsupported exchange: {exchange}")
        
        provider = self.providers[exchange]
        return await provider.get_available_symbols()
    
    async def health_check(self) -> Dict[str, bool]:
        """健康检查"""
        health_status = {}
        
        for exchange, provider in self.providers.items():
            try:
                if hasattr(provider, 'binance_service'):
                    health_status[exchange] = await provider.binance_service.health_check()
                else:
                    # 尝试获取一个简单的数据来测试连接
                    symbols = await provider.get_available_symbols()
                    health_status[exchange] = len(symbols) > 0
            except Exception as e:
                logger.error(f"Health check failed for {exchange}: {e}")
                health_status[exchange] = False
        
        return health_status