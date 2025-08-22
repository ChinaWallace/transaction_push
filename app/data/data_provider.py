# -*- coding: utf-8 -*-
"""
数据提供者
Unified data provider for multiple exchanges and timeframes
"""

import asyncio
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from app.core.logging import get_logger
from app.services.binance_service import BinanceService
from app.data.data_converter import DataConverter
from app.data.data_cache import DataCache
from app.utils.exceptions import DataNotFoundError

logger = get_logger(__name__)


class BaseDataProvider(ABC):
    """基础数据提供者抽象类"""
    
    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, 
                       since: Optional[datetime] = None,
                       limit: int = 500) -> pd.DataFrame:
        """获取OHLCV数据"""
        pass
    
    @abstractmethod
    async def get_available_symbols(self) -> List[str]:
        """获取可用交易对"""
        pass


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
    
    @property
    def cache(self):
        """延迟初始化缓存"""
        if self._use_cache and self._cache is None:
            self._cache = DataCache()
        return self._cache
    
    async def get_ohlcv(self, symbol: str, timeframe: str,
                       exchange: str = 'binance',
                       since: Optional[datetime] = None,
                       limit: int = 500,
                       use_cache: bool = True) -> pd.DataFrame:
        """
        获取OHLCV数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            exchange: 交易所
            since: 开始时间
            limit: 数据条数
            use_cache: 是否使用缓存
            
        Returns:
            OHLCV DataFrame
        """
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
            
            logger.info(f"Retrieved {len(df)} rows of {symbol} {timeframe} data")
            return df
            
        except Exception as e:
            logger.error(f"Failed to get OHLCV data: {e}")
            raise
    
    async def get_multi_timeframe_data(self, symbol: str,
                                     timeframes: List[str],
                                     exchange: str = 'binance',
                                     limit: int = 500) -> Dict[str, pd.DataFrame]:
        """
        获取多时间周期数据
        
        Args:
            symbol: 交易对
            timeframes: 时间周期列表
            exchange: 交易所
            limit: 数据条数
            
        Returns:
            时间周期数据字典
        """
        try:
            tasks = []
            for timeframe in timeframes:
                task = self.get_ohlcv(symbol, timeframe, exchange, limit=limit)
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
            logger.error(f"Failed to get multi-timeframe data: {e}")
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