# -*- coding: utf-8 -*-
"""
数据缓存管理
Data caching system for improved performance
"""

import asyncio
import pickle
import gzip
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
import os

from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class DataCache:
    """
    数据缓存管理器
    支持内存缓存和磁盘缓存
    """
    
    def __init__(self):
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_config = settings.cache_config
        self.cache_dir = os.path.join(settings.log_path, 'cache')
        self.max_memory_size = self.cache_config.get('max_cache_size_mb', 100) * 1024 * 1024
        self.ttl_minutes = self.cache_config.get('cache_ttl_minutes', 5)
        self.enable_compression = self.cache_config.get('cache_compression', True)
        self._cleanup_task_started = False
        
        # 创建缓存目录
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _generate_cache_key(self, symbol: str, timeframe: str, exchange: str,
                          since: Optional[datetime] = None, limit: int = 500) -> str:
        """生成缓存键"""
        key_parts = [symbol, timeframe, exchange, str(limit)]
        if since:
            key_parts.append(since.isoformat())
        
        key_string = '|'.join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """检查缓存是否有效"""
        if 'timestamp' not in cache_entry:
            return False
        
        cache_time = cache_entry['timestamp']
        expiry_time = cache_time + timedelta(minutes=self.ttl_minutes)
        
        return datetime.now() < expiry_time
    
    def _get_memory_usage(self) -> int:
        """计算内存缓存使用量"""
        total_size = 0
        for cache_entry in self.memory_cache.values():
            if 'data' in cache_entry:
                # 估算DataFrame大小
                df = cache_entry['data']
                if isinstance(df, pd.DataFrame):
                    total_size += df.memory_usage(deep=True).sum()
        return total_size
    
    def _cleanup_memory_cache(self):
        """清理内存缓存"""
        # 删除过期缓存
        expired_keys = []
        for key, cache_entry in self.memory_cache.items():
            if not self._is_cache_valid(cache_entry):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.memory_cache[key]
        
        # 如果内存使用超限，删除最旧的缓存
        while self._get_memory_usage() > self.max_memory_size and self.memory_cache:
            oldest_key = min(
                self.memory_cache.keys(),
                key=lambda k: self.memory_cache[k].get('timestamp', datetime.min)
            )
            del self.memory_cache[oldest_key]
        
        logger.debug(f"Memory cache cleaned, {len(self.memory_cache)} entries remaining")
    
    def _start_cleanup_task(self):
        """启动清理任务（如果尚未启动）"""
        if not self._cleanup_task_started and self.cache_config.get('enable_cache', True):
            try:
                # 检查是否有运行中的事件循环
                loop = asyncio.get_running_loop()
                loop.create_task(self._cleanup_task())
                self._cleanup_task_started = True
                logger.debug("Cache cleanup task started")
            except RuntimeError:
                # 没有运行中的事件循环，稍后再试
                logger.debug("No running event loop, cleanup task will start later")
    
    async def _cleanup_task(self):
        """定期清理任务"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                self._cleanup_memory_cache()
                await self._cleanup_disk_cache()
            except Exception as e:
                logger.error(f"Cache cleanup task failed: {e}")
    
    async def _cleanup_disk_cache(self):
        """清理磁盘缓存"""
        try:
            current_time = datetime.now()
            
            for filename in os.listdir(self.cache_dir):
                if not filename.endswith('.cache'):
                    continue
                
                file_path = os.path.join(self.cache_dir, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                # 删除超过1小时的缓存文件
                if current_time - file_mtime > timedelta(hours=1):
                    try:
                        os.remove(file_path)
                        logger.debug(f"Removed expired cache file: {filename}")
                    except OSError as e:
                        logger.warning(f"Failed to remove cache file {filename}: {e}")
        
        except Exception as e:
            logger.error(f"Disk cache cleanup failed: {e}")
    
    def _serialize_data(self, data: pd.DataFrame) -> bytes:
        """序列化数据"""
        try:
            serialized = pickle.dumps(data)
            
            if self.enable_compression:
                serialized = gzip.compress(serialized)
            
            return serialized
        except Exception as e:
            logger.error(f"Data serialization failed: {e}")
            raise
    
    def _deserialize_data(self, data: bytes) -> pd.DataFrame:
        """反序列化数据"""
        try:
            if self.enable_compression:
                data = gzip.decompress(data)
            
            return pickle.loads(data)
        except Exception as e:
            logger.error(f"Data deserialization failed: {e}")
            raise
    
    async def get_ohlcv(self, symbol: str, timeframe: str, exchange: str,
                       since: Optional[datetime] = None, limit: int = 500) -> Optional[pd.DataFrame]:
        """
        从缓存获取OHLCV数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            exchange: 交易所
            since: 开始时间
            limit: 数据条数
            
        Returns:
            缓存的DataFrame或None
        """
        if not self.cache_config.get('enable_cache', True):
            return None
        
        # 启动清理任务（如果需要）
        self._start_cleanup_task()
        
        try:
            cache_key = self._generate_cache_key(symbol, timeframe, exchange, since, limit)
            
            # 检查内存缓存
            if cache_key in self.memory_cache:
                cache_entry = self.memory_cache[cache_key]
                if self._is_cache_valid(cache_entry):
                    logger.debug(f"Memory cache hit for {symbol} {timeframe}")
                    return cache_entry['data'].copy()
                else:
                    del self.memory_cache[cache_key]
            
            # 检查磁盘缓存
            cache_file = os.path.join(self.cache_dir, f"{cache_key}.cache")
            if os.path.exists(cache_file):
                file_mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
                if datetime.now() - file_mtime < timedelta(minutes=self.ttl_minutes):
                    try:
                        with open(cache_file, 'rb') as f:
                            data = self._deserialize_data(f.read())
                        
                        # 加载到内存缓存
                        self.memory_cache[cache_key] = {
                            'data': data,
                            'timestamp': file_mtime
                        }
                        
                        logger.debug(f"Disk cache hit for {symbol} {timeframe}")
                        return data.copy()
                    except Exception as e:
                        logger.warning(f"Failed to load disk cache: {e}")
                        # 删除损坏的缓存文件
                        try:
                            os.remove(cache_file)
                        except OSError:
                            pass
            
            return None
            
        except Exception as e:
            logger.error(f"Cache get operation failed: {e}")
            return None
    
    async def set_ohlcv(self, symbol: str, timeframe: str, exchange: str, data: pd.DataFrame,
                       since: Optional[datetime] = None, limit: int = 500):
        """
        设置OHLCV数据缓存
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            exchange: 交易所
            data: DataFrame数据
            since: 开始时间
            limit: 数据条数
        """
        if not self.cache_config.get('enable_cache', True) or data.empty:
            return
        
        # 启动清理任务（如果需要）
        self._start_cleanup_task()
        
        try:
            cache_key = self._generate_cache_key(symbol, timeframe, exchange, since, limit)
            current_time = datetime.now()
            
            # 设置内存缓存
            self.memory_cache[cache_key] = {
                'data': data.copy(),
                'timestamp': current_time
            }
            
            # 清理内存缓存（如果需要）
            if self._get_memory_usage() > self.max_memory_size:
                self._cleanup_memory_cache()
            
            # 设置磁盘缓存
            try:
                cache_file = os.path.join(self.cache_dir, f"{cache_key}.cache")
                serialized_data = self._serialize_data(data)
                
                with open(cache_file, 'wb') as f:
                    f.write(serialized_data)
                
                logger.debug(f"Data cached for {symbol} {timeframe}")
                
            except Exception as e:
                logger.warning(f"Failed to write disk cache: {e}")
            
        except Exception as e:
            logger.error(f"Cache set operation failed: {e}")
    
    async def invalidate(self, symbol: str = None, timeframe: str = None, exchange: str = None):
        """
        使缓存失效
        
        Args:
            symbol: 交易对（可选，为None时清除所有）
            timeframe: 时间周期（可选）
            exchange: 交易所（可选）
        """
        try:
            if symbol is None and timeframe is None and exchange is None:
                # 清除所有缓存
                self.memory_cache.clear()
                
                # 清除磁盘缓存
                for filename in os.listdir(self.cache_dir):
                    if filename.endswith('.cache'):
                        try:
                            os.remove(os.path.join(self.cache_dir, filename))
                        except OSError:
                            pass
                
                logger.info("All cache invalidated")
                return
            
            # 选择性清除
            keys_to_remove = []
            
            for key in self.memory_cache.keys():
                # 这里需要根据缓存键的格式来判断是否匹配
                # 简化实现：如果指定了参数，就清除所有相关缓存
                if symbol or timeframe or exchange:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.memory_cache[key]
                
                # 删除对应的磁盘缓存
                cache_file = os.path.join(self.cache_dir, f"{key}.cache")
                if os.path.exists(cache_file):
                    try:
                        os.remove(cache_file)
                    except OSError:
                        pass
            
            logger.info(f"Cache invalidated for symbol={symbol}, timeframe={timeframe}, exchange={exchange}")
            
        except Exception as e:
            logger.error(f"Cache invalidation failed: {e}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            memory_entries = len(self.memory_cache)
            memory_usage = self._get_memory_usage()
            
            # 统计磁盘缓存
            disk_entries = 0
            disk_usage = 0
            
            if os.path.exists(self.cache_dir):
                for filename in os.listdir(self.cache_dir):
                    if filename.endswith('.cache'):
                        disk_entries += 1
                        file_path = os.path.join(self.cache_dir, filename)
                        disk_usage += os.path.getsize(file_path)
            
            return {
                'memory': {
                    'entries': memory_entries,
                    'usage_bytes': memory_usage,
                    'usage_mb': round(memory_usage / 1024 / 1024, 2)
                },
                'disk': {
                    'entries': disk_entries,
                    'usage_bytes': disk_usage,
                    'usage_mb': round(disk_usage / 1024 / 1024, 2)
                },
                'config': self.cache_config
            }
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}