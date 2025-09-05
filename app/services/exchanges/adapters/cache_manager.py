# -*- coding: utf-8 -*-
"""
适配器缓存管理器
Adapter cache manager
"""

import asyncio
import hashlib
import json
import time
from typing import Dict, Any, Optional, Callable, TypeVar
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import OrderedDict
import pickle
import threading
from functools import wraps

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    data: Any
    created_at: float
    expires_at: float
    access_count: int = 0
    last_accessed: float = 0
    data_size: int = 0
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at
    
    def is_valid(self) -> bool:
        """检查是否有效"""
        return not self.is_expired()
    
    def touch(self):
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheStats:
    """缓存统计信息"""
    total_entries: int = 0
    total_size: int = 0
    hit_count: int = 0
    miss_count: int = 0
    eviction_count: int = 0
    expired_count: int = 0
    
    @property
    def hit_rate(self) -> float:
        """缓存命中率"""
        total = self.hit_count + self.miss_count
        return (self.hit_count / total * 100) if total > 0 else 0.0
    
    @property
    def miss_rate(self) -> float:
        """缓存未命中率"""
        return 100.0 - self.hit_rate


class AdapterCacheManager:
    """
    适配器缓存管理器
    Cache manager for adapter results
    """
    
    def __init__(
        self, 
        max_size: int = 1000,
        default_ttl: int = 300,  # 5分钟
        cleanup_interval: int = 60  # 1分钟清理一次
    ):
        """
        初始化缓存管理器
        
        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认TTL（秒）
            cleanup_interval: 清理间隔（秒）
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cleanup_interval = cleanup_interval
        
        # 使用OrderedDict实现LRU缓存
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()
        self._lock = threading.RLock()
        
        # 不同数据类型的TTL配置
        self._ttl_config = {
            'instruments': 3600,    # 交易对信息1小时
            'ticker': 30,           # ticker数据30秒
            'funding_rate': 300,    # 资金费率5分钟
            'position': 60,         # 持仓信息1分钟
            'batch_instruments': 1800,  # 批量交易对30分钟
            'batch_tickers': 60,    # 批量ticker1分钟
        }
        
        # 清理任务（延迟启动）
        self._cleanup_task = None
        self._cleanup_started = False
        
        logger.info(f"🔧 适配器缓存管理器初始化完成: max_size={max_size}, default_ttl={default_ttl}s")
    
    def _start_cleanup_task(self):
        """启动清理任务"""
        try:
            if not self._cleanup_started and (self._cleanup_task is None or self._cleanup_task.done()):
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
                self._cleanup_started = True
        except RuntimeError:
            # 没有运行的事件循环，延迟启动
            pass
    
    async def _periodic_cleanup(self):
        """定期清理过期缓存"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 缓存清理任务异常: {e}")
    
    def _generate_cache_key(self, prefix: str, data: Any, **kwargs) -> str:
        """
        生成缓存键
        Generate cache key
        
        Args:
            prefix: 键前缀
            data: 数据
            **kwargs: 额外参数
            
        Returns:
            str: 缓存键
        """
        try:
            # 创建包含所有相关信息的字典
            key_data = {
                'prefix': prefix,
                'data_hash': self._hash_data(data),
                'kwargs': kwargs
            }
            
            # 生成JSON字符串并计算哈希
            key_str = json.dumps(key_data, sort_keys=True)
            return hashlib.md5(key_str.encode()).hexdigest()
            
        except Exception as e:
            logger.warning(f"⚠️ 生成缓存键失败: {e}")
            # 回退到简单的字符串键
            return f"{prefix}_{hash(str(data))}_{hash(str(kwargs))}"
    
    def _hash_data(self, data: Any) -> str:
        """计算数据哈希"""
        try:
            if isinstance(data, (list, dict)):
                # 对于复杂数据结构，使用JSON序列化
                json_str = json.dumps(data, sort_keys=True, default=str)
                return hashlib.md5(json_str.encode()).hexdigest()
            else:
                # 对于简单数据，直接转换为字符串
                return hashlib.md5(str(data).encode()).hexdigest()
        except Exception:
            # 如果序列化失败，使用pickle
            try:
                return hashlib.md5(pickle.dumps(data)).hexdigest()
            except Exception:
                # 最后回退到字符串哈希
                return hashlib.md5(str(data).encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据
        Get cached data
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存的数据，如果不存在或过期则返回None
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats.miss_count += 1
                return None
            
            if entry.is_expired():
                # 删除过期条目
                del self._cache[key]
                self._stats.expired_count += 1
                self._stats.miss_count += 1
                return None
            
            # 更新访问信息并移到末尾（LRU）
            entry.touch()
            self._cache.move_to_end(key)
            self._stats.hit_count += 1
            
            logger.debug(f"🎯 缓存命中: {key[:16]}...")
            return entry.data
    
    def set(
        self, 
        key: str, 
        data: Any, 
        ttl: Optional[int] = None,
        data_type: Optional[str] = None
    ) -> bool:
        """
        设置缓存数据
        Set cached data
        
        Args:
            key: 缓存键
            data: 要缓存的数据
            ttl: 生存时间（秒），None使用默认值
            data_type: 数据类型，用于确定TTL
            
        Returns:
            bool: 是否成功设置
        """
        try:
            with self._lock:
                # 确定TTL
                if ttl is None:
                    ttl = self._ttl_config.get(data_type, self.default_ttl)
                
                # 计算数据大小
                data_size = self._estimate_size(data)
                
                # 创建缓存条目
                now = time.time()
                entry = CacheEntry(
                    key=key,
                    data=data,
                    created_at=now,
                    expires_at=now + ttl,
                    last_accessed=now,
                    data_size=data_size
                )
                
                # 检查是否需要清理空间
                if len(self._cache) >= self.max_size:
                    self._evict_lru()
                
                # 添加到缓存
                self._cache[key] = entry
                self._stats.total_entries = len(self._cache)
                self._stats.total_size += data_size
                
                # 尝试启动清理任务（如果还没启动）
                if not self._cleanup_started:
                    self._start_cleanup_task()
                
                logger.debug(f"💾 缓存设置: {key[:16]}..., TTL={ttl}s, 大小={data_size}字节")
                return True
                
        except Exception as e:
            logger.error(f"❌ 设置缓存失败: {e}")
            return False
    
    def _evict_lru(self):
        """清理最少使用的缓存条目"""
        if not self._cache:
            return
        
        # 移除最旧的条目（OrderedDict的第一个）
        key, entry = self._cache.popitem(last=False)
        self._stats.total_size -= entry.data_size
        self._stats.eviction_count += 1
        
        logger.debug(f"🗑️ LRU清理: {key[:16]}...")
    
    def _cleanup_expired(self):
        """清理过期的缓存条目"""
        with self._lock:
            expired_keys = []
            current_time = time.time()
            
            for key, entry in self._cache.items():
                if entry.expires_at < current_time:
                    expired_keys.append(key)
            
            for key in expired_keys:
                entry = self._cache.pop(key)
                self._stats.total_size -= entry.data_size
                self._stats.expired_count += 1
            
            if expired_keys:
                self._stats.total_entries = len(self._cache)
                logger.debug(f"🧹 清理过期缓存: {len(expired_keys)} 个条目")
    
    def _estimate_size(self, data: Any) -> int:
        """估算数据大小"""
        try:
            if isinstance(data, str):
                return len(data.encode('utf-8'))
            elif isinstance(data, (list, tuple)):
                return sum(self._estimate_size(item) for item in data)
            elif isinstance(data, dict):
                return sum(
                    self._estimate_size(k) + self._estimate_size(v) 
                    for k, v in data.items()
                )
            elif hasattr(data, '__dict__'):
                # 对于自定义对象，估算其属性大小
                return sum(
                    self._estimate_size(k) + self._estimate_size(v)
                    for k, v in data.__dict__.items()
                )
            else:
                # 对于其他类型，使用pickle序列化大小
                return len(pickle.dumps(data))
        except Exception:
            # 如果估算失败，返回默认大小
            return 1024
    
    def cache_result(
        self, 
        cache_key_prefix: str, 
        ttl: Optional[int] = None,
        data_type: Optional[str] = None
    ):
        """
        缓存结果装饰器
        Cache result decorator
        
        Args:
            cache_key_prefix: 缓存键前缀
            ttl: 生存时间
            data_type: 数据类型
        """
        def decorator(func: Callable):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # 生成缓存键
                cache_key = self._generate_cache_key(cache_key_prefix, args, **kwargs)
                
                # 尝试从缓存获取
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # 执行函数并缓存结果
                result = await func(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl, data_type)
                
                return result
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # 生成缓存键
                cache_key = self._generate_cache_key(cache_key_prefix, args, **kwargs)
                
                # 尝试从缓存获取
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # 执行函数并缓存结果
                result = func(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl, data_type)
                
                return result
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator
    
    def invalidate(self, pattern: Optional[str] = None, data_type: Optional[str] = None):
        """
        失效缓存
        Invalidate cache
        
        Args:
            pattern: 键模式（简单字符串匹配）
            data_type: 数据类型
        """
        with self._lock:
            keys_to_remove = []
            
            for key in self._cache.keys():
                should_remove = False
                
                if pattern and pattern in key:
                    should_remove = True
                elif data_type and key.startswith(data_type):
                    should_remove = True
                elif pattern is None and data_type is None:
                    should_remove = True
                
                if should_remove:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                entry = self._cache.pop(key)
                self._stats.total_size -= entry.data_size
            
            self._stats.total_entries = len(self._cache)
            
            if keys_to_remove:
                logger.info(f"🗑️ 失效缓存: {len(keys_to_remove)} 个条目")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        Get cache statistics
        """
        with self._lock:
            return {
                "cache_stats": asdict(self._stats),
                "cache_config": {
                    "max_size": self.max_size,
                    "default_ttl": self.default_ttl,
                    "cleanup_interval": self.cleanup_interval,
                    "ttl_config": self._ttl_config
                },
                "current_state": {
                    "total_entries": len(self._cache),
                    "memory_usage_mb": self._stats.total_size / (1024 * 1024),
                    "oldest_entry": self._get_oldest_entry_info(),
                    "newest_entry": self._get_newest_entry_info()
                }
            }
    
    def _get_oldest_entry_info(self) -> Optional[Dict[str, Any]]:
        """获取最旧条目信息"""
        if not self._cache:
            return None
        
        oldest_entry = min(self._cache.values(), key=lambda e: e.created_at)
        return {
            "key": oldest_entry.key[:16] + "...",
            "created_at": datetime.fromtimestamp(oldest_entry.created_at).isoformat(),
            "expires_at": datetime.fromtimestamp(oldest_entry.expires_at).isoformat(),
            "access_count": oldest_entry.access_count
        }
    
    def _get_newest_entry_info(self) -> Optional[Dict[str, Any]]:
        """获取最新条目信息"""
        if not self._cache:
            return None
        
        newest_entry = max(self._cache.values(), key=lambda e: e.created_at)
        return {
            "key": newest_entry.key[:16] + "...",
            "created_at": datetime.fromtimestamp(newest_entry.created_at).isoformat(),
            "expires_at": datetime.fromtimestamp(newest_entry.expires_at).isoformat(),
            "access_count": newest_entry.access_count
        }
    
    def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats()
            logger.info("🧹 已清空所有缓存")
    
    async def shutdown(self):
        """关闭缓存管理器"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        self.clear()
        logger.info("🔒 缓存管理器已关闭")


# 全局缓存管理器实例
adapter_cache_manager = AdapterCacheManager()


def cache_adapter_result(
    cache_key_prefix: str, 
    ttl: Optional[int] = None,
    data_type: Optional[str] = None
):
    """
    适配器结果缓存装饰器
    Adapter result cache decorator
    
    Args:
        cache_key_prefix: 缓存键前缀
        ttl: 生存时间
        data_type: 数据类型
    """
    return adapter_cache_manager.cache_result(cache_key_prefix, ttl, data_type)