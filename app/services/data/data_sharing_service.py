# -*- coding: utf-8 -*-
"""
数据共享服务
提供跨服务的数据共享和缓存机制
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from app.core.config import get_settings
from app.core.logging import get_logger

# 全局服务实例
_data_sharing_service = None


class DataType(Enum):
    """数据类型"""
    MARKET_DATA = "market_data"
    ANALYSIS_RESULT = "analysis_result"
    PREDICTION = "prediction"
    SIGNAL = "signal"
    NOTIFICATION = "notification"


@dataclass
class SharedData:
    """共享数据结构"""
    key: str
    data_type: DataType
    data: Any
    timestamp: datetime
    ttl_seconds: int = 300  # 默认5分钟TTL
    metadata: Optional[Dict] = None
    
    def is_expired(self) -> bool:
        """检查数据是否过期"""
        return (datetime.now() - self.timestamp).total_seconds() > self.ttl_seconds


class DataSharingService:
    """数据共享服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 内存缓存
        self._cache: Dict[str, SharedData] = {}
        self._access_log: Dict[str, List[datetime]] = {}
        
        # 配置
        self.max_cache_size = 1000
        self.cleanup_interval = 300  # 5分钟清理一次
        
    async def store_data(
        self,
        key: str,
        data: Any,
        data_type: DataType,
        ttl_seconds: int = 300,
        metadata: Optional[Dict] = None
    ) -> bool:
        """存储共享数据"""
        try:
            shared_data = SharedData(
                key=key,
                data_type=data_type,
                data=data,
                timestamp=datetime.now(),
                ttl_seconds=ttl_seconds,
                metadata=metadata or {}
            )
            
            self._cache[key] = shared_data
            
            # 记录访问日志
            if key not in self._access_log:
                self._access_log[key] = []
            self._access_log[key].append(datetime.now())
            
            # 清理过期数据
            await self._cleanup_expired_data()
            
            self.logger.debug(f"存储共享数据: {key} ({data_type.value})")
            return True
            
        except Exception as e:
            self.logger.error(f"存储共享数据失败: {e}")
            return False
    
    async def get_data(
        self,
        key: str,
        default: Any = None
    ) -> Any:
        """获取共享数据"""
        try:
            if key not in self._cache:
                return default
            
            shared_data = self._cache[key]
            
            # 检查是否过期
            if shared_data.is_expired():
                del self._cache[key]
                if key in self._access_log:
                    del self._access_log[key]
                return default
            
            # 记录访问
            if key not in self._access_log:
                self._access_log[key] = []
            self._access_log[key].append(datetime.now())
            
            return shared_data.data
            
        except Exception as e:
            self.logger.error(f"获取共享数据失败: {e}")
            return default
    
    async def get_data_with_metadata(
        self,
        key: str
    ) -> Optional[SharedData]:
        """获取共享数据及其元数据"""
        try:
            if key not in self._cache:
                return None
            
            shared_data = self._cache[key]
            
            # 检查是否过期
            if shared_data.is_expired():
                del self._cache[key]
                if key in self._access_log:
                    del self._access_log[key]
                return None
            
            return shared_data
            
        except Exception as e:
            self.logger.error(f"获取共享数据及元数据失败: {e}")
            return None
    
    async def delete_data(self, key: str) -> bool:
        """删除共享数据"""
        try:
            if key in self._cache:
                del self._cache[key]
            if key in self._access_log:
                del self._access_log[key]
            
            self.logger.debug(f"删除共享数据: {key}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除共享数据失败: {e}")
            return False
    
    async def list_keys(
        self,
        data_type: Optional[DataType] = None,
        pattern: Optional[str] = None
    ) -> List[str]:
        """列出缓存键"""
        try:
            keys = []
            
            for key, shared_data in self._cache.items():
                # 检查数据类型过滤
                if data_type and shared_data.data_type != data_type:
                    continue
                
                # 检查模式匹配
                if pattern and pattern not in key:
                    continue
                
                # 检查是否过期
                if not shared_data.is_expired():
                    keys.append(key)
            
            return keys
            
        except Exception as e:
            self.logger.error(f"列出缓存键失败: {e}")
            return []
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            # 清理过期数据
            await self._cleanup_expired_data()
            
            # 统计各类型数据数量
            type_counts = {}
            for shared_data in self._cache.values():
                data_type = shared_data.data_type.value
                type_counts[data_type] = type_counts.get(data_type, 0) + 1
            
            # 计算访问频率
            access_stats = {}
            for key, access_times in self._access_log.items():
                recent_accesses = [
                    t for t in access_times 
                    if (datetime.now() - t).total_seconds() < 3600  # 最近1小时
                ]
                access_stats[key] = len(recent_accesses)
            
            return {
                "total_items": len(self._cache),
                "type_distribution": type_counts,
                "most_accessed": sorted(
                    access_stats.items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:10],
                "cache_size_limit": self.max_cache_size,
                "cleanup_interval": self.cleanup_interval
            }
            
        except Exception as e:
            self.logger.error(f"获取缓存统计失败: {e}")
            return {}
    
    async def _cleanup_expired_data(self):
        """清理过期数据"""
        try:
            expired_keys = []
            
            for key, shared_data in self._cache.items():
                if shared_data.is_expired():
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_log:
                    del self._access_log[key]
            
            if expired_keys:
                self.logger.debug(f"清理了{len(expired_keys)}个过期数据项")
            
            # 如果缓存过大，清理最少访问的数据
            if len(self._cache) > self.max_cache_size:
                await self._cleanup_least_accessed()
                
        except Exception as e:
            self.logger.error(f"清理过期数据失败: {e}")
    
    async def _cleanup_least_accessed(self):
        """清理最少访问的数据"""
        try:
            # 计算访问频率
            access_counts = {}
            for key in self._cache.keys():
                access_times = self._access_log.get(key, [])
                recent_accesses = [
                    t for t in access_times 
                    if (datetime.now() - t).total_seconds() < 3600
                ]
                access_counts[key] = len(recent_accesses)
            
            # 按访问频率排序，删除最少访问的
            sorted_keys = sorted(access_counts.items(), key=lambda x: x[1])
            cleanup_count = len(self._cache) - self.max_cache_size + 100  # 多清理100个
            
            for key, _ in sorted_keys[:cleanup_count]:
                if key in self._cache:
                    del self._cache[key]
                if key in self._access_log:
                    del self._access_log[key]
            
            self.logger.info(f"清理了{cleanup_count}个最少访问的数据项")
            
        except Exception as e:
            self.logger.error(f"清理最少访问数据失败: {e}")
    
    async def clear_all(self):
        """清空所有缓存"""
        try:
            self._cache.clear()
            self._access_log.clear()
            self.logger.info("已清空所有共享数据缓存")
            
        except Exception as e:
            self.logger.error(f"清空缓存失败: {e}")


async def get_data_sharing_service() -> DataSharingService:
    """获取数据共享服务实例"""
    global _data_sharing_service
    if _data_sharing_service is None:
        _data_sharing_service = DataSharingService()
    return _data_sharing_service


# 便捷函数
async def store_shared_data(
    key: str,
    data: Any,
    data_type: DataType,
    ttl_seconds: int = 300,
    metadata: Optional[Dict] = None
) -> bool:
    """存储共享数据的便捷函数"""
    service = await get_data_sharing_service()
    return await service.store_data(key, data, data_type, ttl_seconds, metadata)


async def get_shared_data(key: str, default: Any = None) -> Any:
    """获取共享数据的便捷函数"""
    service = await get_data_sharing_service()
    return await service.get_data(key, default)


# API兼容性函数
async def get_analysis_data(symbol: str) -> Optional[Dict]:
    """获取分析数据（兼容性函数）"""
    try:
        service = await get_data_sharing_service()
        return await service.get_data(f"analysis_{symbol}")
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"获取分析数据失败: {e}")
        return None


async def get_batch_funding_rates(symbols: List[str]) -> Dict[str, Any]:
    """批量获取资金费率（兼容性函数）"""
    try:
        service = await get_data_sharing_service()
        results = {}
        
        for symbol in symbols:
            funding_data = await service.get_data(f"funding_rate_{symbol}")
            if funding_data:
                results[symbol] = funding_data
        
        return results
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"批量获取资金费率失败: {e}")
        return {}


async def get_technical_indicators(symbol: str) -> Optional[Dict]:
    """获取技术指标（兼容性函数）"""
    try:
        service = await get_data_sharing_service()
        return await service.get_data(f"technical_indicators_{symbol}")
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"获取技术指标失败: {e}")
        return None