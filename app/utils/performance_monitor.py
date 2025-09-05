# -*- coding: utf-8 -*-
"""
性能监控系统
Performance Monitoring System
"""

import time
import asyncio
import psutil
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque, defaultdict
from functools import wraps

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetric:
    """性能指标数据类"""
    name: str
    value: float
    unit: str
    timestamp: datetime
    category: str = "general"
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class OperationStats:
    """操作统计数据类"""
    operation_name: str
    total_calls: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    avg_time: float = 0.0
    error_count: int = 0
    last_call: Optional[datetime] = None
    recent_times: deque = field(default_factory=lambda: deque(maxlen=100))


class PerformanceMonitor:
    """
    性能监控器
    Performance Monitor for tracking system and operation performance
    """
    
    def __init__(self, max_metrics: int = 10000):
        self._metrics: deque = deque(maxlen=max_metrics)
        self._operation_stats: Dict[str, OperationStats] = {}
        self._system_stats: Dict[str, Any] = {}
        self._monitoring_active = True
        self._collection_interval = 30  # 秒
        self._collection_task: Optional[asyncio.Task] = None
        self._lock = threading.RLock()
        
        # 缓存优化
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }
        
        # 内存池
        self._metric_pool = []
        self._pool_size = 1000
        
        logger.info("📊 性能监控器初始化完成")
    
    def start_monitoring(self):
        """启动性能监控"""
        if self._collection_task and not self._collection_task.done():
            logger.warning("⚠️ 性能监控已在运行")
            return
        
        self._monitoring_active = True
        self._collection_task = asyncio.create_task(self._collect_system_metrics())
        logger.info("🚀 性能监控已启动")
    
    async def stop_monitoring(self):
        """停止性能监控"""
        self._monitoring_active = False
        
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
        
        logger.info("🛑 性能监控已停止")
    
    async def _collect_system_metrics(self):
        """收集系统指标"""
        while self._monitoring_active:
            try:
                # CPU使用率
                cpu_percent = psutil.cpu_percent(interval=1)
                self.record_metric("system.cpu.usage", cpu_percent, "%", "system")
                
                # 内存使用情况
                memory = psutil.virtual_memory()
                self.record_metric("system.memory.usage", memory.percent, "%", "system")
                self.record_metric("system.memory.available", memory.available / 1024 / 1024, "MB", "system")
                
                # 磁盘使用情况
                disk = psutil.disk_usage('/')
                disk_percent = (disk.used / disk.total) * 100
                self.record_metric("system.disk.usage", disk_percent, "%", "system")
                
                # 网络统计
                net_io = psutil.net_io_counters()
                self.record_metric("system.network.bytes_sent", net_io.bytes_sent, "bytes", "system")
                self.record_metric("system.network.bytes_recv", net_io.bytes_recv, "bytes", "system")
                
                # 进程信息
                process = psutil.Process()
                self.record_metric("process.memory.rss", process.memory_info().rss / 1024 / 1024, "MB", "process")
                self.record_metric("process.cpu.percent", process.cpu_percent(), "%", "process")
                self.record_metric("process.threads", process.num_threads(), "count", "process")
                
                # 缓存统计
                total_cache_ops = self._cache_stats['hits'] + self._cache_stats['misses']
                if total_cache_ops > 0:
                    hit_rate = (self._cache_stats['hits'] / total_cache_ops) * 100
                    self.record_metric("cache.hit_rate", hit_rate, "%", "cache")
                
                self.record_metric("cache.evictions", self._cache_stats['evictions'], "count", "cache")
                
                await asyncio.sleep(self._collection_interval)
                
            except Exception as e:
                logger.error(f"❌ 系统指标收集失败: {e}")
                await asyncio.sleep(5)  # 错误时短暂等待
    
    def record_metric(self, name: str, value: float, unit: str, category: str = "general", 
                     tags: Dict[str, str] = None):
        """
        记录性能指标
        Record performance metric
        
        Args:
            name: 指标名称 / Metric name
            value: 指标值 / Metric value
            unit: 单位 / Unit
            category: 分类 / Category
            tags: 标签 / Tags
        """
        try:
            with self._lock:
                # 使用对象池优化内存分配
                if self._metric_pool:
                    metric = self._metric_pool.pop()
                    metric.name = name
                    metric.value = value
                    metric.unit = unit
                    metric.timestamp = datetime.now()
                    metric.category = category
                    metric.tags = tags or {}
                else:
                    metric = PerformanceMetric(
                        name=name,
                        value=value,
                        unit=unit,
                        timestamp=datetime.now(),
                        category=category,
                        tags=tags or {}
                    )
                
                self._metrics.append(metric)
                
                # 如果队列满了，回收最老的指标到对象池
                if len(self._metrics) == self._metrics.maxlen and len(self._metric_pool) < self._pool_size:
                    old_metric = self._metrics[0]
                    self._metric_pool.append(old_metric)
                
        except Exception as e:
            logger.error(f"❌ 指标记录失败: {name} - {e}")
    
    def time_operation(self, operation_name: str):
        """
        操作计时装饰器
        Operation timing decorator
        
        Args:
            operation_name: 操作名称 / Operation name
        """
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                error_occurred = False
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self._update_operation_stats(operation_name, duration, error_occurred)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                error_occurred = False
                
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    self._update_operation_stats(operation_name, duration, error_occurred)
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator
    
    def _update_operation_stats(self, operation_name: str, duration: float, error_occurred: bool):
        """更新操作统计"""
        with self._lock:
            if operation_name not in self._operation_stats:
                self._operation_stats[operation_name] = OperationStats(operation_name)
            
            stats = self._operation_stats[operation_name]
            stats.total_calls += 1
            stats.total_time += duration
            stats.min_time = min(stats.min_time, duration)
            stats.max_time = max(stats.max_time, duration)
            stats.avg_time = stats.total_time / stats.total_calls
            stats.last_call = datetime.now()
            stats.recent_times.append(duration)
            
            if error_occurred:
                stats.error_count += 1
            
            # 记录性能指标
            self.record_metric(f"operation.{operation_name}.duration", duration * 1000, "ms", "operation")
            self.record_metric(f"operation.{operation_name}.calls", stats.total_calls, "count", "operation")
            
            if error_occurred:
                self.record_metric(f"operation.{operation_name}.errors", stats.error_count, "count", "operation")
    
    def get_operation_stats(self, operation_name: str = None) -> Dict[str, Any]:
        """
        获取操作统计
        Get operation statistics
        
        Args:
            operation_name: 操作名称，None表示获取所有 / Operation name, None for all
            
        Returns:
            Dict[str, Any]: 操作统计 / Operation statistics
        """
        with self._lock:
            if operation_name:
                if operation_name in self._operation_stats:
                    stats = self._operation_stats[operation_name]
                    return {
                        "operation_name": stats.operation_name,
                        "total_calls": stats.total_calls,
                        "total_time": stats.total_time,
                        "avg_time": stats.avg_time,
                        "min_time": stats.min_time,
                        "max_time": stats.max_time,
                        "error_count": stats.error_count,
                        "error_rate": stats.error_count / stats.total_calls if stats.total_calls > 0 else 0,
                        "last_call": stats.last_call.isoformat() if stats.last_call else None,
                        "recent_avg": sum(stats.recent_times) / len(stats.recent_times) if stats.recent_times else 0
                    }
                else:
                    return {}
            else:
                return {
                    name: {
                        "operation_name": stats.operation_name,
                        "total_calls": stats.total_calls,
                        "avg_time": stats.avg_time,
                        "error_count": stats.error_count,
                        "error_rate": stats.error_count / stats.total_calls if stats.total_calls > 0 else 0,
                        "last_call": stats.last_call.isoformat() if stats.last_call else None
                    }
                    for name, stats in self._operation_stats.items()
                }
    
    def get_metrics(self, category: str = None, since: datetime = None, 
                   limit: int = None) -> List[Dict[str, Any]]:
        """
        获取性能指标
        Get performance metrics
        
        Args:
            category: 指标分类 / Metric category
            since: 起始时间 / Start time
            limit: 限制数量 / Limit count
            
        Returns:
            List[Dict[str, Any]]: 指标列表 / Metrics list
        """
        with self._lock:
            metrics = list(self._metrics)
            
            # 过滤条件
            if category:
                metrics = [m for m in metrics if m.category == category]
            
            if since:
                metrics = [m for m in metrics if m.timestamp >= since]
            
            # 排序（最新的在前）
            metrics.sort(key=lambda m: m.timestamp, reverse=True)
            
            # 限制数量
            if limit:
                metrics = metrics[:limit]
            
            # 转换为字典
            return [
                {
                    "name": m.name,
                    "value": m.value,
                    "unit": m.unit,
                    "timestamp": m.timestamp.isoformat(),
                    "category": m.category,
                    "tags": m.tags
                }
                for m in metrics
            ]
    
    def get_system_summary(self) -> Dict[str, Any]:
        """
        获取系统性能摘要
        Get system performance summary
        
        Returns:
            Dict[str, Any]: 系统性能摘要 / System performance summary
        """
        recent_time = datetime.now() - timedelta(minutes=5)
        recent_metrics = self.get_metrics(since=recent_time)
        
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_metrics": len(self._metrics),
            "total_operations": len(self._operation_stats),
            "system": {},
            "operations": {},
            "cache": {
                "hit_rate": 0,
                "total_operations": self._cache_stats['hits'] + self._cache_stats['misses'],
                "evictions": self._cache_stats['evictions']
            }
        }
        
        # 系统指标摘要
        system_metrics = [m for m in recent_metrics if m['category'] == 'system']
        if system_metrics:
            # 按指标名称分组并取最新值
            system_groups = defaultdict(list)
            for metric in system_metrics:
                system_groups[metric['name']].append(metric['value'])
            
            for name, values in system_groups.items():
                summary["system"][name] = {
                    "current": values[0] if values else 0,
                    "avg": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0
                }
        
        # 操作性能摘要
        top_operations = sorted(
            self._operation_stats.items(),
            key=lambda x: x[1].total_calls,
            reverse=True
        )[:10]
        
        for name, stats in top_operations:
            summary["operations"][name] = {
                "calls": stats.total_calls,
                "avg_time": stats.avg_time * 1000,  # 转换为毫秒
                "error_rate": stats.error_count / stats.total_calls if stats.total_calls > 0 else 0
            }
        
        # 缓存命中率
        total_cache_ops = self._cache_stats['hits'] + self._cache_stats['misses']
        if total_cache_ops > 0:
            summary["cache"]["hit_rate"] = (self._cache_stats['hits'] / total_cache_ops) * 100
        
        return summary
    
    def record_cache_hit(self):
        """记录缓存命中"""
        self._cache_stats['hits'] += 1
    
    def record_cache_miss(self):
        """记录缓存未命中"""
        self._cache_stats['misses'] += 1
    
    def record_cache_eviction(self):
        """记录缓存驱逐"""
        self._cache_stats['evictions'] += 1
    
    def clear_metrics(self, older_than: timedelta = None):
        """
        清理指标数据
        Clear metrics data
        
        Args:
            older_than: 清理早于此时间的数据 / Clear data older than this
        """
        if not older_than:
            with self._lock:
                # 将清理的指标回收到对象池
                while self._metrics and len(self._metric_pool) < self._pool_size:
                    old_metric = self._metrics.popleft()
                    self._metric_pool.append(old_metric)
                
                self._metrics.clear()
                logger.info("🧹 所有性能指标已清理")
        else:
            cutoff_time = datetime.now() - older_than
            with self._lock:
                # 移除旧指标并回收到对象池
                while (self._metrics and 
                       self._metrics[0].timestamp < cutoff_time and 
                       len(self._metric_pool) < self._pool_size):
                    old_metric = self._metrics.popleft()
                    self._metric_pool.append(old_metric)
                
                logger.info(f"🧹 清理了早于 {cutoff_time} 的性能指标")
    
    def get_performance_report(self) -> str:
        """
        生成性能报告
        Generate performance report
        
        Returns:
            str: 性能报告文本 / Performance report text
        """
        summary = self.get_system_summary()
        
        report = [
            "📊 性能监控报告",
            "=" * 50,
            f"生成时间: {summary['timestamp']}",
            f"总指标数: {summary['total_metrics']}",
            f"总操作数: {summary['total_operations']}",
            "",
            "🖥️ 系统性能:",
        ]
        
        for name, stats in summary["system"].items():
            report.append(f"  • {name}: {stats['current']:.2f} (平均: {stats['avg']:.2f})")
        
        report.extend([
            "",
            "⚡ 操作性能 (Top 10):",
        ])
        
        for name, stats in summary["operations"].items():
            error_rate = stats['error_rate'] * 100
            report.append(f"  • {name}: {stats['calls']} 次调用, 平均 {stats['avg_time']:.2f}ms, 错误率 {error_rate:.1f}%")
        
        report.extend([
            "",
            "💾 缓存性能:",
            f"  • 命中率: {summary['cache']['hit_rate']:.1f}%",
            f"  • 总操作: {summary['cache']['total_operations']}",
            f"  • 驱逐次数: {summary['cache']['evictions']}",
        ])
        
        return "\n".join(report)


# 全局性能监控器实例
performance_monitor = PerformanceMonitor()