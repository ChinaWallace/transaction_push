# -*- coding: utf-8 -*-
"""
数据共享服务
Data Sharing Service - 为其他服务提供优化的数据访问机制
"""

import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import pandas as pd

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.unified_data_service import (
    get_unified_data_service, 
    DataRequest, 
    DataSource,
    get_shared_market_data
)

logger = get_logger(__name__)
settings = get_settings()


class DataSharingService:
    """
    数据共享服务
    
    为其他服务提供高效的数据访问，避免重复获取相同数据
    """
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self._unified_service = None
        
        # 常用数据的快速访问缓存
        self._hot_data_cache = {}
        self._cache_lock = asyncio.Lock()
        
        # 订阅者管理
        self._subscribers = {}
        
    async def _get_unified_service(self):
        """获取统一数据服务"""
        if self._unified_service is None:
            self._unified_service = await get_unified_data_service()
        return self._unified_service
    
    async def get_market_data_for_analysis(self, symbol: str, 
                                         timeframes: List[str] = None) -> Dict[str, pd.DataFrame]:
        """
        为分析服务获取市场数据
        优先使用共享数据，减少重复请求
        """
        if timeframes is None:
            timeframes = ['1h', '4h', '1d']
        
        try:
            market_data = {}
            
            # 首先尝试获取共享数据
            for timeframe in timeframes:
                shared_data = await get_shared_market_data(symbol, timeframe)
                if shared_data is not None:
                    market_data[timeframe] = shared_data
                    self.logger.debug(f"📈 使用共享数据: {symbol} {timeframe}")
            
            # 获取缺失的数据
            missing_timeframes = [tf for tf in timeframes if tf not in market_data]
            if missing_timeframes:
                unified_service = await self._get_unified_service()
                
                # 批量请求缺失的数据
                requests = []
                for timeframe in missing_timeframes:
                    request = DataRequest(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=200,  # 分析通常不需要太多历史数据
                        source=DataSource.AUTO,
                        use_cache=True
                    )
                    requests.append(request)
                
                results = await unified_service.batch_get_kline_data(requests)
                
                for result in results:
                    market_data[result.timeframe] = result.data
                    self.logger.debug(f"📊 获取新数据: {symbol} {result.timeframe}")
            
            self.logger.info(f"✅ 为分析服务提供 {symbol} 数据: {len(market_data)} 个周期")
            return market_data
            
        except Exception as e:
            self.logger.error(f"❌ 获取分析数据失败: {symbol} - {e}")
            return {}
    
    async def get_funding_rates_batch(self, symbols: List[str]) -> Dict[str, Any]:
        """
        批量获取资金费率，支持数据共享
        """
        try:
            async with self._cache_lock:
                cache_key = "funding_rates_batch"
                
                # 检查缓存（5分钟内的数据）
                if (cache_key in self._hot_data_cache and 
                    datetime.now() - self._hot_data_cache[cache_key]['timestamp'] < timedelta(minutes=5)):
                    
                    cached_rates = self._hot_data_cache[cache_key]['data']
                    
                    # 返回请求的币种数据
                    result = {symbol: cached_rates.get(symbol) for symbol in symbols if symbol in cached_rates}
                    self.logger.debug(f"📈 使用缓存费率数据: {len(result)} 个币种")
                    return result
            
            # 获取新数据
            unified_service = await self._get_unified_service()
            all_rates = await unified_service.get_funding_rates(symbols)
            
            # 更新缓存
            async with self._cache_lock:
                self._hot_data_cache[cache_key] = {
                    'data': all_rates,
                    'timestamp': datetime.now()
                }
            
            self.logger.info(f"✅ 批量获取费率数据: {len(all_rates)} 个币种")
            return all_rates
            
        except Exception as e:
            self.logger.error(f"❌ 批量获取费率数据失败: {e}")
            return {}
    
    async def get_top_symbols_data(self, count: int = 20) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        获取热门币种的数据，多服务共享
        """
        try:
            # 获取热门币种列表（这里简化为使用配置中的币种）
            hot_symbols = settings.monitored_symbols + settings.funding_rate_only_symbols[:count-len(settings.monitored_symbols)]
            hot_symbols = hot_symbols[:count]
            
            result = {}
            
            # 并发获取多个币种的多周期数据
            tasks = []
            for symbol in hot_symbols:
                task = self.get_market_data_for_analysis(symbol, ['1h', '4h'])
                tasks.append((symbol, task))
            
            # 等待所有任务完成
            for symbol, task in tasks:
                try:
                    data = await task
                    if data:
                        result[symbol] = data
                except Exception as e:
                    self.logger.warning(f"获取 {symbol} 数据失败: {e}")
            
            self.logger.info(f"✅ 获取热门币种数据: {len(result)} 个币种")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 获取热门币种数据失败: {e}")
            return {}
    
    async def subscribe_to_data_updates(self, service_name: str, symbols: List[str], 
                                      callback) -> bool:
        """
        订阅数据更新（为未来扩展预留）
        """
        try:
            if service_name not in self._subscribers:
                self._subscribers[service_name] = {
                    'symbols': set(),
                    'callback': callback,
                    'last_update': datetime.now()
                }
            
            self._subscribers[service_name]['symbols'].update(symbols)
            self.logger.info(f"✅ 服务 {service_name} 订阅数据更新: {len(symbols)} 个币种")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 订阅数据更新失败: {e}")
            return False
    
    async def get_shared_indicators(self, symbol: str, timeframe: str = "1h") -> Dict[str, Any]:
        """
        获取共享的技术指标数据
        避免多个服务重复计算相同指标
        """
        try:
            cache_key = f"indicators_{symbol}_{timeframe}"
            
            async with self._cache_lock:
                # 检查缓存（2分钟内的指标）
                if (cache_key in self._hot_data_cache and 
                    datetime.now() - self._hot_data_cache[cache_key]['timestamp'] < timedelta(minutes=2)):
                    
                    self.logger.debug(f"📈 使用缓存指标: {symbol} {timeframe}")
                    return self._hot_data_cache[cache_key]['data']
            
            # 获取市场数据
            market_data = await self.get_market_data_for_analysis(symbol, [timeframe])
            if timeframe not in market_data or market_data[timeframe].empty:
                return {}
            
            df = market_data[timeframe]
            
            # 计算常用技术指标
            indicators = {}
            
            if len(df) >= 20:
                # 移动平均线
                indicators['ma_20'] = df['close'].rolling(20).mean().iloc[-1]
                indicators['ma_50'] = df['close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else None
                
                # 价格变化
                indicators['price_change_24h'] = ((df['close'].iloc[-1] - df['close'].iloc[-25]) / df['close'].iloc[-25] * 100) if len(df) >= 25 else None
                
                # 成交量指标
                indicators['volume_avg_20'] = df['volume'].rolling(20).mean().iloc[-1]
                indicators['volume_ratio'] = df['volume'].iloc[-1] / indicators['volume_avg_20']
                
                # 波动率
                indicators['volatility'] = df['close'].pct_change().rolling(20).std().iloc[-1] * 100
                
                # 当前价格信息
                indicators['current_price'] = df['close'].iloc[-1]
                indicators['high_24h'] = df['high'].tail(24).max() if len(df) >= 24 else df['high'].max()
                indicators['low_24h'] = df['low'].tail(24).min() if len(df) >= 24 else df['low'].min()
            
            # 缓存指标
            async with self._cache_lock:
                self._hot_data_cache[cache_key] = {
                    'data': indicators,
                    'timestamp': datetime.now()
                }
            
            self.logger.debug(f"📊 计算技术指标: {symbol} {timeframe}")
            return indicators
            
        except Exception as e:
            self.logger.error(f"❌ 获取技术指标失败: {symbol} {timeframe} - {e}")
            return {}
    
    async def get_service_stats(self) -> Dict[str, Any]:
        """获取数据共享服务统计"""
        try:
            unified_service = await self._get_unified_service()
            unified_stats = unified_service.get_stats()
            
            return {
                "data_sharing": {
                    "hot_cache_size": len(self._hot_data_cache),
                    "subscribers_count": len(self._subscribers),
                    "subscribers": list(self._subscribers.keys())
                },
                "unified_service": unified_stats
            }
            
        except Exception as e:
            self.logger.error(f"获取服务统计失败: {e}")
            return {}
    
    async def cleanup_cache(self):
        """清理过期缓存"""
        try:
            current_time = datetime.now()
            expired_keys = []
            
            async with self._cache_lock:
                for key, cache_entry in self._hot_data_cache.items():
                    # 清理超过10分钟的缓存
                    if current_time - cache_entry['timestamp'] > timedelta(minutes=10):
                        expired_keys.append(key)
                
                for key in expired_keys:
                    del self._hot_data_cache[key]
            
            if expired_keys:
                self.logger.info(f"🧹 清理过期缓存: {len(expired_keys)} 个条目")
                
        except Exception as e:
            self.logger.error(f"清理缓存失败: {e}")


# 全局数据共享服务实例
_data_sharing_service = None


async def get_data_sharing_service() -> DataSharingService:
    """获取数据共享服务实例"""
    global _data_sharing_service
    if _data_sharing_service is None:
        _data_sharing_service = DataSharingService()
    return _data_sharing_service


# 便捷函数
async def get_analysis_data(symbol: str, timeframes: List[str] = None) -> Dict[str, pd.DataFrame]:
    """便捷函数：获取分析数据"""
    service = await get_data_sharing_service()
    return await service.get_market_data_for_analysis(symbol, timeframes)


async def get_batch_funding_rates(symbols: List[str]) -> Dict[str, Any]:
    """便捷函数：批量获取费率数据"""
    service = await get_data_sharing_service()
    return await service.get_funding_rates_batch(symbols)


async def get_technical_indicators(symbol: str, timeframe: str = "1h") -> Dict[str, Any]:
    """便捷函数：获取技术指标"""
    service = await get_data_sharing_service()
    return await service.get_shared_indicators(symbol, timeframe)
