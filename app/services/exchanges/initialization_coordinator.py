# -*- coding: utf-8 -*-
"""
服务初始化协调器
Service Initialization Coordinator - 协调多个服务的初始化，避免并发API调用
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)

class ServiceInitializationCoordinator:
    """服务初始化协调器 - 避免并发API调用导致速率限制"""
    
    def __init__(self):
        self._initialization_lock = asyncio.Lock()
        self._initialized_services: Dict[str, Any] = {}
        self._initialization_queue = asyncio.Queue()
        self._is_processing = False
        
        # 初始化统计
        self._init_stats = {
            'total_requests': 0,
            'queued_requests': 0,
            'concurrent_avoided': 0,
            'start_time': datetime.now()
        }
        
        logger.debug("🔧 服务初始化协调器已启动")
    
    async def coordinate_exchange_service_init(self, service_name: str, init_func) -> Any:
        """协调交易所服务初始化"""
        async with self._initialization_lock:
            # 检查是否已经初始化
            if service_name in self._initialized_services:
                logger.debug(f"🔄 复用已初始化的服务: {service_name}")
                self._init_stats['concurrent_avoided'] += 1
                return self._initialized_services[service_name]
            
            # 执行初始化
            logger.debug(f"🚀 开始初始化服务: {service_name}")
            self._init_stats['total_requests'] += 1
            
            try:
                service = await init_func()
                self._initialized_services[service_name] = service
                logger.info(f"✅ 服务初始化完成: {service_name}")
                return service
            except Exception as e:
                logger.error(f"❌ 服务初始化失败: {service_name}, 错误: {e}")
                raise
    
    async def coordinate_api_call(self, call_name: str, api_func, *args, **kwargs) -> Any:
        """协调API调用，避免并发请求"""
        # 添加到队列
        await self._initialization_queue.put((call_name, api_func, args, kwargs))
        self._init_stats['queued_requests'] += 1
        
        # 启动处理器（如果未运行）
        if not self._is_processing:
            asyncio.create_task(self._process_queue())
        
        # 等待结果（简化版，实际应该用更复杂的机制）
        return await api_func(*args, **kwargs)
    
    async def _process_queue(self):
        """处理API调用队列"""
        if self._is_processing:
            return
        
        self._is_processing = True
        logger.debug("🔄 开始处理API调用队列")
        
        try:
            while not self._initialization_queue.empty():
                try:
                    call_name, api_func, args, kwargs = await asyncio.wait_for(
                        self._initialization_queue.get(), timeout=1.0
                    )
                    
                    logger.debug(f"📞 处理API调用: {call_name}")
                    
                    # 添加延迟避免并发
                    await asyncio.sleep(0.2)
                    
                    # 执行API调用
                    await api_func(*args, **kwargs)
                    
                except asyncio.TimeoutError:
                    break
                except Exception as e:
                    logger.warning(f"⚠️ API调用处理异常: {e}")
        finally:
            self._is_processing = False
            logger.debug("✅ API调用队列处理完成")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取初始化统计信息"""
        runtime = (datetime.now() - self._init_stats['start_time']).total_seconds()
        
        return {
            **self._init_stats,
            'initialized_services': list(self._initialized_services.keys()),
            'runtime_seconds': runtime,
            'queue_size': self._initialization_queue.qsize(),
            'efficiency': (
                self._init_stats['concurrent_avoided'] / 
                max(1, self._init_stats['total_requests'])
            ) * 100
        }
    
    def reset(self):
        """重置协调器状态"""
        self._initialized_services.clear()
        self._init_stats = {
            'total_requests': 0,
            'queued_requests': 0,
            'concurrent_avoided': 0,
            'start_time': datetime.now()
        }
        logger.info("🔄 服务初始化协调器已重置")


# 全局协调器实例
_global_coordinator: Optional[ServiceInitializationCoordinator] = None

def get_initialization_coordinator() -> ServiceInitializationCoordinator:
    """获取全局初始化协调器"""
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = ServiceInitializationCoordinator()
    return _global_coordinator

async def coordinate_service_init(service_name: str, init_func):
    """协调服务初始化的便捷函数"""
    coordinator = get_initialization_coordinator()
    return await coordinator.coordinate_exchange_service_init(service_name, init_func)