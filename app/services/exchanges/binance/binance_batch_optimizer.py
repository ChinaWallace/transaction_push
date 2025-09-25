# -*- coding: utf-8 -*-
"""
币安批量请求优化器
Binance Batch Request Optimizer - 优化API请求频率和批量处理
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable, TypeVar
from datetime import datetime, timedelta
import time

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')

class BinanceBatchOptimizer:
    """币安批量请求优化器"""
    
    def __init__(self):
        self.batch_queue: List[Dict[str, Any]] = []
        self.batch_size = 50  # 批量处理大小
        self.batch_timeout = 2.0  # 批量超时时间（秒）
        self.last_batch_time = time.time()
        
        # 请求缓存
        self.request_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 60  # 缓存TTL（秒）
        
        logger.debug("🚀 币安批量优化器初始化完成")
    
    async def add_to_batch(self, request_type: str, params: Dict[str, Any]) -> Optional[Any]:
        """添加请求到批量队列"""
        # 检查缓存
        cache_key = self._generate_cache_key(request_type, params)
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            logger.debug(f"📋 使用缓存结果: {request_type}")
            return cached_result
        
        # 添加到批量队列
        request_item = {
            'type': request_type,
            'params': params,
            'timestamp': time.time(),
            'cache_key': cache_key
        }
        
        self.batch_queue.append(request_item)
        
        # 检查是否需要立即处理批量
        if len(self.batch_queue) >= self.batch_size:
            return await self._process_batch()
        
        # 检查超时
        if time.time() - self.last_batch_time > self.batch_timeout:
            return await self._process_batch()
        
        return None
    
    async def _process_batch(self) -> Optional[Any]:
        """处理批量请求"""
        if not self.batch_queue:
            return None
        
        logger.info(f"🔄 处理批量请求，共 {len(self.batch_queue)} 个")
        
        # 按类型分组请求
        grouped_requests = self._group_requests_by_type()
        
        results = {}
        
        # 处理每种类型的请求
        for request_type, requests in grouped_requests.items():
            try:
                if request_type == "positions":
                    result = await self._batch_process_positions(requests)
                elif request_type == "instruments":
                    result = await self._batch_process_instruments(requests)
                else:
                    # 其他类型的请求
                    result = await self._batch_process_generic(request_type, requests)
                
                results[request_type] = result
                
                # 缓存结果
                for request in requests:
                    self._cache_result(request['cache_key'], result)
                
            except Exception as e:
                logger.error(f"❌ 批量处理 {request_type} 失败: {e}")
                continue
        
        # 清空队列
        self.batch_queue.clear()
        self.last_batch_time = time.time()
        
        return results
    
    def _group_requests_by_type(self) -> Dict[str, List[Dict[str, Any]]]:
        """按类型分组请求"""
        grouped = {}
        for request in self.batch_queue:
            request_type = request['type']
            if request_type not in grouped:
                grouped[request_type] = []
            grouped[request_type].append(request)
        return grouped
    
    async def _batch_process_positions(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量处理持仓请求"""
        # 合并所有持仓请求为单个API调用
        logger.debug(f"📊 批量处理持仓请求: {len(requests)} 个")
        
        # 这里应该调用实际的API服务
        # 暂时返回空结果，避免实际API调用
        return []
    
    async def _batch_process_instruments(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量处理交易对请求"""
        logger.debug(f"📊 批量处理交易对请求: {len(requests)} 个")
        
        # 合并所有交易对请求为单个API调用
        return []
    
    async def _batch_process_generic(self, request_type: str, requests: List[Dict[str, Any]]) -> Any:
        """批量处理通用请求"""
        logger.debug(f"📊 批量处理 {request_type} 请求: {len(requests)} 个")
        return None
    
    def _generate_cache_key(self, request_type: str, params: Dict[str, Any]) -> str:
        """生成缓存键"""
        import hashlib
        import json
        
        # 创建参数的哈希值
        params_str = json.dumps(params, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        
        return f"{request_type}_{params_hash}"
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """从缓存获取结果"""
        if cache_key in self.request_cache:
            cache_item = self.request_cache[cache_key]
            
            # 检查是否过期
            if time.time() - cache_item['timestamp'] < self.cache_ttl:
                return cache_item['data']
            else:
                # 删除过期缓存
                del self.request_cache[cache_key]
        
        return None
    
    def _cache_result(self, cache_key: str, data: Any) -> None:
        """缓存结果"""
        self.request_cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self.request_cache.clear()
        logger.debug("🗑️ 批量优化器缓存已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'queue_size': len(self.batch_queue),
            'cache_size': len(self.request_cache),
            'batch_size': self.batch_size,
            'batch_timeout': self.batch_timeout,
            'last_batch_time': self.last_batch_time
        }


# 全局批量优化器实例
_batch_optimizer: Optional[BinanceBatchOptimizer] = None

def get_batch_optimizer() -> BinanceBatchOptimizer:
    """获取批量优化器实例"""
    global _batch_optimizer
    if _batch_optimizer is None:
        _batch_optimizer = BinanceBatchOptimizer()
    return _batch_optimizer