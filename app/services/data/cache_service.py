# -*- coding: utf-8 -*-
"""
缓存服务模块
Cache Service Module

提供统一的缓存管理功能，支持内存缓存和持久化缓存
Provides unified cache management with memory and persistent cache support
"""

import asyncio
import json
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import hashlib

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    """
    缓存服务
    Cache Service - 提供内存和文件缓存功能
    """
    
    def __init__(self):
        """初始化缓存服务"""
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 内存缓存
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        
        # 缓存配置
        self.cache_config = getattr(self.settings, 'cache_config', {})
        self.default_ttl = self.cache_config.get('default_ttl_seconds', 300)  # 5分钟
        self.max_cache_size_mb = self.cache_config.get('max_cache_size_mb', 100)
        self.enable_file_cache = self.cache_config.get('enable_file_cache', True)
        
        # 文件缓存目录
        self.cache_dir = Path("logs/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.initialized = False
    
    async def initialize(self) -> None:
        """初始化缓存服务"""
        if self.initialized:
            return
        
        try:
            # 清理过期的文件缓存
            await self._cleanup_expired_file_cache()
            
            self.initialized = True
            self.logger.info("✅ 缓存服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 缓存服务初始化失败: {e}")
            raise
    
    async def get(
        self, 
        key: str, 
        default: Any = None,
        use_file_cache: bool = True
    ) -> Any:
        """
        获取缓存数据
        Get cached data
        
        Args:
            key: 缓存键
            default: 默认值
            use_file_cache: 是否使用文件缓存
            
        Returns:
            缓存的数据或默认值
        """
        try:
            # 1. 检查内存缓存
            if key in self._memory_cache:
                cache_time = self._cache_timestamps.get(key)
                if cache_time and datetime.now() - cache_time < timedelta(seconds=self.default_ttl):
                    self.logger.debug(f"📋 内存缓存命中: {key}")
                    return self._memory_cache[key]['data']
                else:
                    # 过期，删除内存缓存
                    await self._remove_from_memory(key)
            
            # 2. 检查文件缓存
            if use_file_cache and self.enable_file_cache:
                file_data = await self._get_from_file_cache(key)
                if file_data is not None:
                    # 将文件缓存加载到内存
                    await self._set_to_memory(key, file_data)
                    self.logger.debug(f"📁 文件缓存命中: {key}")
                    return file_data
            
            return default
            
        except Exception as e:
            self.logger.error(f"获取缓存失败 {key}: {e}")
            return default
    
    async def set(
        self, 
        key: str, 
        data: Any, 
        ttl_seconds: Optional[int] = None,
        use_file_cache: bool = True
    ) -> bool:
        """
        设置缓存数据
        Set cache data
        
        Args:
            key: 缓存键
            data: 要缓存的数据
            ttl_seconds: 过期时间（秒）
            use_file_cache: 是否使用文件缓存
            
        Returns:
            是否设置成功
        """
        try:
            # 设置内存缓存
            await self._set_to_memory(key, data)
            
            # 设置文件缓存
            if use_file_cache and self.enable_file_cache:
                await self._set_to_file_cache(key, data, ttl_seconds)
            
            self.logger.debug(f"💾 缓存已设置: {key}")
            return True
            
        except Exception as e:
            self.logger.error(f"设置缓存失败 {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        删除缓存
        Delete cache
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        try:
            # 删除内存缓存
            await self._remove_from_memory(key)
            
            # 删除文件缓存
            await self._remove_from_file_cache(key)
            
            self.logger.debug(f"🗑️ 缓存已删除: {key}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除缓存失败 {key}: {e}")
            return False
    
    async def clear(self, pattern: Optional[str] = None) -> int:
        """
        清空缓存
        Clear cache
        
        Args:
            pattern: 匹配模式，如果提供则只清除匹配的键
            
        Returns:
            清除的缓存数量
        """
        try:
            cleared_count = 0
            
            if pattern:
                # 清除匹配模式的缓存
                keys_to_remove = [
                    key for key in self._memory_cache.keys() 
                    if pattern in key
                ]
                for key in keys_to_remove:
                    await self.delete(key)
                    cleared_count += 1
            else:
                # 清空所有缓存
                cleared_count = len(self._memory_cache)
                self._memory_cache.clear()
                self._cache_timestamps.clear()
                
                # 清空文件缓存
                if self.enable_file_cache:
                    for cache_file in self.cache_dir.glob("*.cache"):
                        cache_file.unlink()
            
            self.logger.info(f"🧹 已清除 {cleared_count} 个缓存项")
            return cleared_count
            
        except Exception as e:
            self.logger.error(f"清空缓存失败: {e}")
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        Get cache statistics
        
        Returns:
            缓存统计信息
        """
        try:
            memory_size = len(self._memory_cache)
            file_cache_count = len(list(self.cache_dir.glob("*.cache"))) if self.cache_dir.exists() else 0
            
            # 计算内存使用量（估算）
            memory_usage_mb = sum(
                len(str(data).encode('utf-8')) 
                for data in self._memory_cache.values()
            ) / (1024 * 1024)
            
            return {
                "memory_cache_count": memory_size,
                "file_cache_count": file_cache_count,
                "memory_usage_mb": round(memory_usage_mb, 2),
                "max_cache_size_mb": self.max_cache_size_mb,
                "default_ttl_seconds": self.default_ttl,
                "cache_hit_rate": await self._calculate_hit_rate()
            }
            
        except Exception as e:
            self.logger.error(f"获取缓存统计失败: {e}")
            return {}
    
    async def _set_to_memory(self, key: str, data: Any) -> None:
        """设置内存缓存"""
        self._memory_cache[key] = {
            'data': data,
            'size': len(str(data).encode('utf-8'))
        }
        self._cache_timestamps[key] = datetime.now()
        
        # 检查内存使用量
        await self._check_memory_limit()
    
    async def _remove_from_memory(self, key: str) -> None:
        """从内存中移除缓存"""
        self._memory_cache.pop(key, None)
        self._cache_timestamps.pop(key, None)
    
    async def _get_from_file_cache(self, key: str) -> Any:
        """从文件缓存获取数据"""
        try:
            cache_file = self.cache_dir / f"{self._hash_key(key)}.cache"
            
            if not cache_file.exists():
                return None
            
            # 检查文件是否过期
            file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - file_mtime > timedelta(seconds=self.default_ttl * 2):  # 文件缓存TTL更长
                cache_file.unlink()
                return None
            
            # 读取缓存数据
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
                
        except Exception as e:
            self.logger.debug(f"读取文件缓存失败 {key}: {e}")
            return None
    
    async def _set_to_file_cache(self, key: str, data: Any, ttl_seconds: Optional[int] = None) -> None:
        """设置文件缓存"""
        try:
            cache_file = self.cache_dir / f"{self._hash_key(key)}.cache"
            
            # 序列化数据
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
                
        except Exception as e:
            self.logger.debug(f"设置文件缓存失败 {key}: {e}")
    
    async def _remove_from_file_cache(self, key: str) -> None:
        """从文件缓存中移除"""
        try:
            cache_file = self.cache_dir / f"{self._hash_key(key)}.cache"
            if cache_file.exists():
                cache_file.unlink()
        except Exception as e:
            self.logger.debug(f"删除文件缓存失败 {key}: {e}")
    
    def _hash_key(self, key: str) -> str:
        """生成缓存键的哈希值"""
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    async def _check_memory_limit(self) -> None:
        """检查内存限制"""
        total_size_mb = sum(
            cache_data.get('size', 0) 
            for cache_data in self._memory_cache.values()
        ) / (1024 * 1024)
        
        if total_size_mb > self.max_cache_size_mb:
            # 清理最旧的缓存
            await self._cleanup_old_cache()
    
    async def _cleanup_old_cache(self) -> None:
        """清理旧缓存"""
        # 按时间排序，删除最旧的缓存
        sorted_keys = sorted(
            self._cache_timestamps.keys(),
            key=lambda k: self._cache_timestamps[k]
        )
        
        # 删除最旧的25%缓存
        keys_to_remove = sorted_keys[:len(sorted_keys) // 4]
        for key in keys_to_remove:
            await self._remove_from_memory(key)
        
        self.logger.debug(f"🧹 清理了 {len(keys_to_remove)} 个旧缓存")
    
    async def _cleanup_expired_file_cache(self) -> None:
        """清理过期的文件缓存"""
        try:
            if not self.cache_dir.exists():
                return
            
            expired_count = 0
            cutoff_time = datetime.now() - timedelta(seconds=self.default_ttl * 2)
            
            for cache_file in self.cache_dir.glob("*.cache"):
                file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
                if file_mtime < cutoff_time:
                    cache_file.unlink()
                    expired_count += 1
            
            if expired_count > 0:
                self.logger.info(f"🧹 清理了 {expired_count} 个过期文件缓存")
                
        except Exception as e:
            self.logger.error(f"清理过期文件缓存失败: {e}")
    
    async def _calculate_hit_rate(self) -> float:
        """计算缓存命中率（简化实现）"""
        # 这里可以实现更复杂的命中率统计
        return 0.0
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 测试缓存功能
            test_key = "health_check_test"
            test_data = {"timestamp": datetime.now().isoformat()}
            
            # 测试设置和获取
            await self.set(test_key, test_data)
            retrieved_data = await self.get(test_key)
            await self.delete(test_key)
            
            is_healthy = retrieved_data is not None
            
            stats = await self.get_cache_stats()
            
            return {
                "status": "healthy" if is_healthy else "unhealthy",
                "initialized": self.initialized,
                "cache_stats": stats,
                "test_passed": is_healthy
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
            await self.clear()
            self.logger.info("✅ 缓存服务资源清理完成")
        except Exception as e:
            self.logger.error(f"❌ 缓存服务清理失败: {e}")


# 全局缓存服务实例
_cache_service: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """
    获取缓存服务实例 - 单例模式
    Get cache service instance - singleton pattern
    
    Returns:
        CacheService: 缓存服务实例
    """
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
        await _cache_service.initialize()
    return _cache_service


# 便捷函数
async def cache_get(key: str, default: Any = None) -> Any:
    """便捷的缓存获取函数"""
    service = await get_cache_service()
    return await service.get(key, default)


async def cache_set(key: str, data: Any, ttl_seconds: Optional[int] = None) -> bool:
    """便捷的缓存设置函数"""
    service = await get_cache_service()
    return await service.set(key, data, ttl_seconds)


async def cache_delete(key: str) -> bool:
    """便捷的缓存删除函数"""
    service = await get_cache_service()
    return await service.delete(key)


async def cache_clear(pattern: Optional[str] = None) -> int:
    """便捷的缓存清理函数"""
    service = await get_cache_service()
    return await service.clear(pattern)