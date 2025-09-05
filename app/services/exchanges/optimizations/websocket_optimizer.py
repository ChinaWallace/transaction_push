# -*- coding: utf-8 -*-
"""
WebSocket连接优化器
WebSocket Connection Optimizer - 优化WebSocket连接性能和稳定性
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


class ConnectionState(Enum):
    """连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class ConnectionMetrics:
    """连接指标"""
    connect_time: float = 0.0
    disconnect_time: float = 0.0
    total_messages: int = 0
    error_count: int = 0
    reconnect_count: int = 0
    last_message_time: float = 0.0
    average_latency: float = 0.0
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=100))


@dataclass
class OptimizationConfig:
    """优化配置"""
    # 连接池配置
    max_connections_per_host: int = 5
    connection_timeout: float = 10.0
    read_timeout: float = 30.0
    
    # 重连配置
    initial_reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    reconnect_backoff_factor: float = 1.5
    max_reconnect_attempts: int = 10
    
    # 心跳配置
    ping_interval: float = 20.0
    pong_timeout: float = 10.0
    health_check_interval: float = 30.0
    
    # 消息处理配置
    message_queue_size: int = 1000
    batch_processing_size: int = 10
    batch_processing_timeout: float = 0.1
    
    # 性能优化配置
    enable_compression: bool = True
    enable_message_batching: bool = True
    enable_connection_pooling: bool = True
    enable_adaptive_reconnect: bool = True


class WebSocketOptimizer:
    """WebSocket连接优化器"""
    
    def __init__(self, config: OptimizationConfig = None):
        self.config = config or OptimizationConfig()
        
        # 连接管理
        self.connections: Dict[str, Any] = {}
        self.connection_states: Dict[str, ConnectionState] = {}
        self.connection_metrics: Dict[str, ConnectionMetrics] = {}
        
        # 连接池
        self.connection_pool: Dict[str, List[Any]] = {}
        self.pool_lock = asyncio.Lock()
        
        # 消息处理
        self.message_queues: Dict[str, asyncio.Queue] = {}
        self.message_processors: Dict[str, asyncio.Task] = {}
        
        # 监控和统计
        self.global_metrics = {
            'total_connections': 0,
            'active_connections': 0,
            'total_messages': 0,
            'total_errors': 0,
            'total_reconnects': 0,
            'start_time': time.time()
        }
        
        # 优化任务
        self.optimization_tasks: List[asyncio.Task] = []
        self.is_running = False
        
        logger.info("🔧 WebSocket优化器初始化完成")
    
    async def start(self):
        """启动优化器"""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("🚀 启动WebSocket优化器")
        
        # 启动优化任务
        self.optimization_tasks = [
            asyncio.create_task(self._health_monitor_task()),
            asyncio.create_task(self._connection_pool_manager_task()),
            asyncio.create_task(self._metrics_collector_task()),
            asyncio.create_task(self._adaptive_reconnect_task())
        ]
        
        logger.info("✅ WebSocket优化器启动完成")
    
    async def stop(self):
        """停止优化器"""
        if not self.is_running:
            return
        
        logger.info("🛑 停止WebSocket优化器")
        self.is_running = False
        
        # 取消优化任务
        for task in self.optimization_tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        if self.optimization_tasks:
            await asyncio.gather(*self.optimization_tasks, return_exceptions=True)
        
        # 清理连接
        await self._cleanup_all_connections()
        
        logger.info("✅ WebSocket优化器已停止")
    
    async def optimize_connection(self, connection_id: str, websocket, 
                                callback: Optional[Callable] = None) -> bool:
        """优化WebSocket连接"""
        try:
            logger.info(f"🔧 开始优化连接: {connection_id}")
            
            # 初始化连接状态
            self.connection_states[connection_id] = ConnectionState.CONNECTED
            self.connection_metrics[connection_id] = ConnectionMetrics(
                connect_time=time.time()
            )
            self.connections[connection_id] = websocket
            
            # 创建消息队列
            if self.config.enable_message_batching:
                self.message_queues[connection_id] = asyncio.Queue(
                    maxsize=self.config.message_queue_size
                )
                
                # 启动消息处理器
                processor_task = asyncio.create_task(
                    self._message_processor(connection_id, callback)
                )
                self.message_processors[connection_id] = processor_task
            
            # 更新全局指标
            self.global_metrics['total_connections'] += 1
            self.global_metrics['active_connections'] += 1
            
            logger.info(f"✅ 连接优化完成: {connection_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 连接优化失败: {connection_id} - {e}")
            return False
    
    async def handle_message(self, connection_id: str, message: Any) -> bool:
        """处理消息（优化版本）"""
        try:
            metrics = self.connection_metrics.get(connection_id)
            if metrics:
                metrics.total_messages += 1
                metrics.last_message_time = time.time()
                
                # 计算延迟（如果消息包含时间戳）
                if isinstance(message, dict) and 'timestamp' in message:
                    try:
                        msg_time = float(message['timestamp']) / 1000  # 假设是毫秒时间戳
                        latency = time.time() - msg_time
                        metrics.latency_samples.append(latency)
                        
                        # 更新平均延迟
                        if metrics.latency_samples:
                            metrics.average_latency = sum(metrics.latency_samples) / len(metrics.latency_samples)
                    except (ValueError, TypeError):
                        pass
            
            # 更新全局指标
            self.global_metrics['total_messages'] += 1
            
            # 如果启用了消息批处理，将消息放入队列
            if self.config.enable_message_batching and connection_id in self.message_queues:
                try:
                    self.message_queues[connection_id].put_nowait(message)
                    return True
                except asyncio.QueueFull:
                    logger.warning(f"⚠️ 消息队列已满: {connection_id}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 处理消息异常: {connection_id} - {e}")
            await self._record_error(connection_id, e)
            return False
    
    async def handle_connection_error(self, connection_id: str, error: Exception) -> bool:
        """处理连接错误"""
        try:
            logger.warning(f"⚠️ 连接错误: {connection_id} - {error}")
            
            await self._record_error(connection_id, error)
            
            # 更新连接状态
            self.connection_states[connection_id] = ConnectionState.ERROR
            
            # 如果启用自适应重连，触发重连
            if self.config.enable_adaptive_reconnect:
                await self._schedule_reconnect(connection_id)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 处理连接错误异常: {connection_id} - {e}")
            return False
    
    async def handle_connection_close(self, connection_id: str) -> bool:
        """处理连接关闭"""
        try:
            logger.info(f"🔌 连接关闭: {connection_id}")
            
            # 更新连接状态
            self.connection_states[connection_id] = ConnectionState.DISCONNECTED
            
            # 更新指标
            metrics = self.connection_metrics.get(connection_id)
            if metrics:
                metrics.disconnect_time = time.time()
            
            # 清理连接资源
            await self._cleanup_connection(connection_id)
            
            # 更新全局指标
            if self.global_metrics['active_connections'] > 0:
                self.global_metrics['active_connections'] -= 1
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 处理连接关闭异常: {connection_id} - {e}")
            return False
    
    async def _message_processor(self, connection_id: str, callback: Optional[Callable]):
        """消息批处理器"""
        try:
            queue = self.message_queues[connection_id]
            batch = []
            last_process_time = time.time()
            
            while self.is_running and connection_id in self.message_queues:
                try:
                    # 等待消息或超时
                    message = await asyncio.wait_for(
                        queue.get(),
                        timeout=self.config.batch_processing_timeout
                    )
                    
                    batch.append(message)
                    
                    # 检查是否需要处理批次
                    current_time = time.time()
                    should_process = (
                        len(batch) >= self.config.batch_processing_size or
                        current_time - last_process_time >= self.config.batch_processing_timeout
                    )
                    
                    if should_process and batch:
                        # 处理批次
                        if callback:
                            try:
                                if len(batch) == 1:
                                    await self._safe_callback(callback, batch[0])
                                else:
                                    await self._safe_callback(callback, batch)
                            except Exception as e:
                                logger.error(f"❌ 批处理回调异常: {e}")
                        
                        batch.clear()
                        last_process_time = current_time
                
                except asyncio.TimeoutError:
                    # 超时，处理当前批次
                    if batch and callback:
                        try:
                            if len(batch) == 1:
                                await self._safe_callback(callback, batch[0])
                            else:
                                await self._safe_callback(callback, batch)
                        except Exception as e:
                            logger.error(f"❌ 超时批处理回调异常: {e}")
                        
                        batch.clear()
                        last_process_time = time.time()
                
                except Exception as e:
                    logger.error(f"❌ 消息处理器异常: {connection_id} - {e}")
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"❌ 消息处理器启动异常: {connection_id} - {e}")
        finally:
            logger.debug(f"🔄 消息处理器退出: {connection_id}")
    
    async def _safe_callback(self, callback: Callable, data: Any):
        """安全的回调执行"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error(f"❌ 回调执行异常: {e}")
    
    async def _record_error(self, connection_id: str, error: Exception):
        """记录错误"""
        metrics = self.connection_metrics.get(connection_id)
        if metrics:
            metrics.error_count += 1
        
        self.global_metrics['total_errors'] += 1
        
        logger.debug(f"📊 记录错误: {connection_id} - {error}")
    
    async def _schedule_reconnect(self, connection_id: str):
        """调度重连"""
        try:
            metrics = self.connection_metrics.get(connection_id)
            if not metrics:
                return
            
            # 计算重连延迟（指数退避）
            delay = min(
                self.config.initial_reconnect_delay * (
                    self.config.reconnect_backoff_factor ** metrics.reconnect_count
                ),
                self.config.max_reconnect_delay
            )
            
            logger.info(f"🔄 调度重连: {connection_id}, 延迟 {delay:.1f}秒")
            
            # 更新状态
            self.connection_states[connection_id] = ConnectionState.RECONNECTING
            metrics.reconnect_count += 1
            self.global_metrics['total_reconnects'] += 1
            
            # 延迟后触发重连（这里只是示例，实际重连逻辑需要由调用方实现）
            await asyncio.sleep(delay)
            
        except Exception as e:
            logger.error(f"❌ 调度重连异常: {connection_id} - {e}")
    
    async def _cleanup_connection(self, connection_id: str):
        """清理连接资源"""
        try:
            # 停止消息处理器
            if connection_id in self.message_processors:
                task = self.message_processors[connection_id]
                if not task.done():
                    task.cancel()
                del self.message_processors[connection_id]
            
            # 清理消息队列
            if connection_id in self.message_queues:
                del self.message_queues[connection_id]
            
            # 清理连接引用
            self.connections.pop(connection_id, None)
            
            logger.debug(f"🧹 连接资源清理完成: {connection_id}")
            
        except Exception as e:
            logger.error(f"❌ 清理连接资源异常: {connection_id} - {e}")
    
    async def _cleanup_all_connections(self):
        """清理所有连接"""
        try:
            logger.info("🧹 清理所有连接资源")
            
            # 停止所有消息处理器
            for task in self.message_processors.values():
                if not task.done():
                    task.cancel()
            
            # 等待任务完成
            if self.message_processors:
                await asyncio.gather(*self.message_processors.values(), return_exceptions=True)
            
            # 清理所有资源
            self.connections.clear()
            self.connection_states.clear()
            self.message_queues.clear()
            self.message_processors.clear()
            
            logger.info("✅ 所有连接资源清理完成")
            
        except Exception as e:
            logger.error(f"❌ 清理所有连接异常: {e}")
    
    async def _health_monitor_task(self):
        """健康监控任务"""
        try:
            while self.is_running:
                try:
                    current_time = time.time()
                    
                    # 检查连接健康状态
                    for connection_id, metrics in self.connection_metrics.items():
                        # 检查消息接收超时
                        if (metrics.last_message_time > 0 and 
                            current_time - metrics.last_message_time > self.config.read_timeout):
                            
                            logger.warning(f"⚠️ 连接消息接收超时: {connection_id}")
                            await self.handle_connection_error(
                                connection_id, 
                                TradingToolError("消息接收超时")
                            )
                    
                    await asyncio.sleep(self.config.health_check_interval)
                    
                except Exception as e:
                    logger.error(f"❌ 健康监控异常: {e}")
                    await asyncio.sleep(5)
        
        except asyncio.CancelledError:
            logger.debug("🔄 健康监控任务被取消")
        except Exception as e:
            logger.error(f"❌ 健康监控任务异常: {e}")
    
    async def _connection_pool_manager_task(self):
        """连接池管理任务"""
        try:
            while self.is_running:
                try:
                    # 连接池清理和维护逻辑
                    # 这里可以实现连接池的清理、预热等功能
                    
                    await asyncio.sleep(60)  # 每分钟检查一次
                    
                except Exception as e:
                    logger.error(f"❌ 连接池管理异常: {e}")
                    await asyncio.sleep(10)
        
        except asyncio.CancelledError:
            logger.debug("🔄 连接池管理任务被取消")
        except Exception as e:
            logger.error(f"❌ 连接池管理任务异常: {e}")
    
    async def _metrics_collector_task(self):
        """指标收集任务"""
        try:
            while self.is_running:
                try:
                    # 收集和记录性能指标
                    self._log_performance_metrics()
                    
                    await asyncio.sleep(300)  # 每5分钟记录一次
                    
                except Exception as e:
                    logger.error(f"❌ 指标收集异常: {e}")
                    await asyncio.sleep(30)
        
        except asyncio.CancelledError:
            logger.debug("🔄 指标收集任务被取消")
        except Exception as e:
            logger.error(f"❌ 指标收集任务异常: {e}")
    
    async def _adaptive_reconnect_task(self):
        """自适应重连任务"""
        try:
            while self.is_running:
                try:
                    # 检查需要重连的连接
                    for connection_id, state in self.connection_states.items():
                        if state == ConnectionState.ERROR:
                            metrics = self.connection_metrics.get(connection_id)
                            if metrics and metrics.reconnect_count < self.config.max_reconnect_attempts:
                                # 触发重连逻辑（实际实现需要调用方提供）
                                logger.debug(f"🔄 检测到需要重连的连接: {connection_id}")
                    
                    await asyncio.sleep(10)  # 每10秒检查一次
                    
                except Exception as e:
                    logger.error(f"❌ 自适应重连异常: {e}")
                    await asyncio.sleep(5)
        
        except asyncio.CancelledError:
            logger.debug("🔄 自适应重连任务被取消")
        except Exception as e:
            logger.error(f"❌ 自适应重连任务异常: {e}")
    
    def _log_performance_metrics(self):
        """记录性能指标"""
        try:
            current_time = time.time()
            uptime = current_time - self.global_metrics['start_time']
            
            # 计算平均指标
            avg_messages_per_second = self.global_metrics['total_messages'] / uptime if uptime > 0 else 0
            error_rate = self.global_metrics['total_errors'] / self.global_metrics['total_messages'] if self.global_metrics['total_messages'] > 0 else 0
            
            logger.info(f"📊 WebSocket性能指标:")
            logger.info(f"  运行时间: {uptime:.1f}秒")
            logger.info(f"  总连接数: {self.global_metrics['total_connections']}")
            logger.info(f"  活跃连接数: {self.global_metrics['active_connections']}")
            logger.info(f"  总消息数: {self.global_metrics['total_messages']}")
            logger.info(f"  平均消息/秒: {avg_messages_per_second:.2f}")
            logger.info(f"  错误率: {error_rate:.4f}")
            logger.info(f"  重连次数: {self.global_metrics['total_reconnects']}")
            
            # 记录连接级别的指标
            for connection_id, metrics in self.connection_metrics.items():
                if metrics.total_messages > 0:
                    logger.debug(f"  连接 {connection_id}: {metrics.total_messages} 消息, {metrics.error_count} 错误, 平均延迟 {metrics.average_latency:.3f}秒")
        
        except Exception as e:
            logger.error(f"❌ 记录性能指标异常: {e}")
    
    def get_optimization_status(self) -> Dict[str, Any]:
        """获取优化状态"""
        return {
            'is_running': self.is_running,
            'config': {
                'max_connections_per_host': self.config.max_connections_per_host,
                'connection_timeout': self.config.connection_timeout,
                'enable_compression': self.config.enable_compression,
                'enable_message_batching': self.config.enable_message_batching,
                'enable_connection_pooling': self.config.enable_connection_pooling,
                'enable_adaptive_reconnect': self.config.enable_adaptive_reconnect
            },
            'global_metrics': self.global_metrics.copy(),
            'active_connections': len(self.connections),
            'connection_states': {k: v.value for k, v in self.connection_states.items()},
            'message_queues': {k: v.qsize() for k, v in self.message_queues.items()},
            'timestamp': datetime.now().isoformat()
        }
    
    def get_connection_metrics(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """获取连接指标"""
        metrics = self.connection_metrics.get(connection_id)
        if not metrics:
            return None
        
        return {
            'connection_id': connection_id,
            'state': self.connection_states.get(connection_id, ConnectionState.DISCONNECTED).value,
            'connect_time': metrics.connect_time,
            'disconnect_time': metrics.disconnect_time,
            'total_messages': metrics.total_messages,
            'error_count': metrics.error_count,
            'reconnect_count': metrics.reconnect_count,
            'last_message_time': metrics.last_message_time,
            'average_latency': metrics.average_latency,
            'uptime': time.time() - metrics.connect_time if metrics.connect_time > 0 else 0
        }


# 全局优化器实例
_global_optimizer: Optional[WebSocketOptimizer] = None


async def get_websocket_optimizer(config: OptimizationConfig = None) -> WebSocketOptimizer:
    """获取全局WebSocket优化器实例"""
    global _global_optimizer
    
    if _global_optimizer is None:
        _global_optimizer = WebSocketOptimizer(config)
        await _global_optimizer.start()
    
    return _global_optimizer


async def cleanup_websocket_optimizer():
    """清理全局WebSocket优化器"""
    global _global_optimizer
    
    if _global_optimizer:
        await _global_optimizer.stop()
        _global_optimizer = None