# -*- coding: utf-8 -*-
"""
币安智能请求管理器
Binance Smart Request Manager - 智能合并和优化API请求
"""

import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import time
from collections import defaultdict

from app.core.logging import get_logger

logger = get_logger(__name__)

class BinanceSmartRequestManager:
    """币安智能请求管理器"""
    
    def __init__(self):
        # 请求合并配置
        self.merge_window = 0.5  # 请求合并窗口（秒）
        self.max_merge_size = 20  # 最大合并请求数
        
        # 请求队列
        self.pending_requests: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.request_timers: Dict[str, float] = {}
        
        # 去重配置
        self.dedup_window = 5.0  # 去重窗口（秒）
        self.recent_requests: Dict[str, float] = {}
        
        # 优先级配置
        self.priority_endpoints = {
            '/api/v3/account': 1,      # 账户信息 - 高优先级
            '/api/v3/exchangeInfo': 2,  # 交易对信息 - 中优先级
            '/api/v3/ticker/24hr': 3,   # 行情数据 - 低优先级
        }
        
        logger.debug("🧠 币安智能请求管理器初始化完成")
    
    async def smart_request(
        self, 
        endpoint: str, 
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        priority: int = 5
    ) -> Optional[Any]:
        """智能请求处理"""
        
        # 生成请求标识
        request_key = self._generate_request_key(endpoint, method, params)
        
        # 检查去重
        if self._is_duplicate_request(request_key):
            logger.debug(f"🔄 跳过重复请求: {endpoint}")
            return None
        
        # 检查是否可以合并
        if self._can_merge_request(endpoint):
            return await self._add_to_merge_queue(endpoint, method, params, priority)
        
        # 直接执行请求
        return await self._execute_single_request(endpoint, method, params)
    
    def _generate_request_key(
        self, 
        endpoint: str, 
        method: str, 
        params: Optional[Dict[str, Any]]
    ) -> str:
        """生成请求唯一标识"""
        import hashlib
        import json
        
        key_data = {
            'endpoint': endpoint,
            'method': method,
            'params': params or {}
        }
        
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()[:12]
    
    def _is_duplicate_request(self, request_key: str) -> bool:
        """检查是否为重复请求"""
        current_time = time.time()
        
        if request_key in self.recent_requests:
            last_request_time = self.recent_requests[request_key]
            if current_time - last_request_time < self.dedup_window:
                return True
        
        # 记录请求时间
        self.recent_requests[request_key] = current_time
        
        # 清理过期记录
        self._cleanup_recent_requests(current_time)
        
        return False
    
    def _cleanup_recent_requests(self, current_time: float) -> None:
        """清理过期的请求记录"""
        expired_keys = [
            key for key, timestamp in self.recent_requests.items()
            if current_time - timestamp > self.dedup_window * 2
        ]
        
        for key in expired_keys:
            del self.recent_requests[key]
    
    def _can_merge_request(self, endpoint: str) -> bool:
        """检查请求是否可以合并"""
        # 某些端点适合合并（如批量查询）
        mergeable_endpoints = {
            '/api/v3/ticker/24hr',
            '/api/v3/ticker/price',
            '/api/v3/ticker/bookTicker'
        }
        
        return endpoint in mergeable_endpoints
    
    async def _add_to_merge_queue(
        self, 
        endpoint: str, 
        method: str, 
        params: Optional[Dict[str, Any]], 
        priority: int
    ) -> Optional[Any]:
        """添加到合并队列"""
        
        request_item = {
            'endpoint': endpoint,
            'method': method,
            'params': params or {},
            'priority': priority,
            'timestamp': time.time()
        }
        
        self.pending_requests[endpoint].append(request_item)
        
        # 设置合并定时器
        if endpoint not in self.request_timers:
            self.request_timers[endpoint] = time.time()
            
            # 延迟执行合并
            asyncio.create_task(self._delayed_merge_execution(endpoint))
        
        # 检查是否达到最大合并数量
        if len(self.pending_requests[endpoint]) >= self.max_merge_size:
            return await self._execute_merged_requests(endpoint)
        
        return None
    
    async def _delayed_merge_execution(self, endpoint: str) -> None:
        """延迟执行合并请求"""
        await asyncio.sleep(self.merge_window)
        
        if endpoint in self.pending_requests and self.pending_requests[endpoint]:
            await self._execute_merged_requests(endpoint)
    
    async def _execute_merged_requests(self, endpoint: str) -> Optional[Any]:
        """执行合并的请求"""
        if endpoint not in self.pending_requests:
            return None
        
        requests = self.pending_requests[endpoint]
        if not requests:
            return None
        
        logger.info(f"🔄 执行合并请求: {endpoint}, 合并数量: {len(requests)}")
        
        try:
            # 按优先级排序
            requests.sort(key=lambda x: x['priority'])
            
            # 合并参数（如果适用）
            merged_params = self._merge_request_params(requests)
            
            # 执行合并后的请求
            result = await self._execute_single_request(
                endpoint, 
                requests[0]['method'], 
                merged_params
            )
            
            # 清理队列
            self.pending_requests[endpoint].clear()
            if endpoint in self.request_timers:
                del self.request_timers[endpoint]
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 合并请求执行失败: {e}")
            return None
    
    def _merge_request_params(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并请求参数"""
        merged_params = {}
        
        # 简单的参数合并逻辑
        for request in requests:
            params = request.get('params', {})
            for key, value in params.items():
                if key not in merged_params:
                    merged_params[key] = value
                elif isinstance(value, list) and isinstance(merged_params[key], list):
                    # 合并列表参数
                    merged_params[key].extend(value)
                    merged_params[key] = list(set(merged_params[key]))  # 去重
        
        return merged_params
    
    async def _execute_single_request(
        self, 
        endpoint: str, 
        method: str, 
        params: Optional[Dict[str, Any]]
    ) -> Optional[Any]:
        """执行单个请求"""
        # 这里应该调用实际的API服务
        # 暂时返回None，避免实际API调用
        logger.debug(f"📡 执行API请求: {method} {endpoint}")
        return None
    
    def get_queue_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        return {
            'pending_requests': {
                endpoint: len(requests) 
                for endpoint, requests in self.pending_requests.items()
            },
            'active_timers': len(self.request_timers),
            'recent_requests_count': len(self.recent_requests),
            'merge_window': self.merge_window,
            'max_merge_size': self.max_merge_size
        }
    
    def clear_queues(self) -> None:
        """清空所有队列"""
        self.pending_requests.clear()
        self.request_timers.clear()
        self.recent_requests.clear()
        logger.debug("🗑️ 智能请求管理器队列已清空")


# 全局智能请求管理器实例
_smart_request_manager: Optional[BinanceSmartRequestManager] = None

def get_smart_request_manager() -> BinanceSmartRequestManager:
    """获取智能请求管理器实例"""
    global _smart_request_manager
    if _smart_request_manager is None:
        _smart_request_manager = BinanceSmartRequestManager()
    return _smart_request_manager