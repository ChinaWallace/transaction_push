# -*- coding: utf-8 -*-
"""
数据适配性能监控器
Data adaptation performance monitor
"""

import time
import asyncio
from typing import Dict, Any, List, Optional, Callable
from functools import wraps
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict, deque
import statistics

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    operation_name: str
    start_time: float
    end_time: float
    duration: float
    data_size: int
    success: bool
    error_message: Optional[str] = None
    memory_usage: Optional[float] = None
    
    @property
    def throughput(self) -> float:
        """计算吞吐量 (items/second)"""
        if self.duration > 0:
            return self.data_size / self.duration
        return 0.0


class AdapterPerformanceMonitor:
    """
    数据适配器性能监控器
    Performance monitor for data adapters
    """
    
    def __init__(self, max_history: int = 1000):
        """
        初始化性能监控器
        
        Args:
            max_history: 最大历史记录数量
        """
        self.max_history = max_history
        self._metrics_history: deque = deque(maxlen=max_history)
        self._operation_stats: Dict[str, List[PerformanceMetrics]] = defaultdict(list)
        self._performance_thresholds = {
            'adapt_instruments': 0.5,  # 秒
            'adapt_tickers': 0.3,
            'adapt_funding_rates': 0.2,
            'adapt_positions': 0.2
        }
        logger.info("🔧 数据适配性能监控器初始化完成")
    
    def log_performance(self, operation_name: str, threshold_multiplier: float = 1.0):
        """
        性能日志装饰器
        Performance logging decorator
        
        Args:
            operation_name: 操作名称
            threshold_multiplier: 阈值倍数
        """
        def decorator(func: Callable):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await self._execute_with_monitoring(
                    func, operation_name, threshold_multiplier, True, *args, **kwargs
                )
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # 同步版本的性能监控
                start_time = time.time()
                data_size = self._estimate_data_size(args, kwargs)
                success = False
                error_message = None
                result = None
                
                try:
                    result = func(*args, **kwargs)
                    success = True
                    
                    # 更新数据大小（基于结果）
                    if result:
                        if isinstance(result, list):
                            data_size = len(result)
                        elif isinstance(result, dict):
                            data_size = 1
                            
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"❌ {operation_name} 执行失败: {e}")
                    raise
                finally:
                    end_time = time.time()
                    duration = end_time - start_time
                    
                    # 记录性能指标
                    metrics = PerformanceMetrics(
                        operation_name=operation_name,
                        start_time=start_time,
                        end_time=end_time,
                        duration=duration,
                        data_size=data_size,
                        success=success,
                        error_message=error_message
                    )
                    
                    self._record_metrics(metrics)
                    self._check_performance_threshold(metrics, threshold_multiplier)
                
                return result
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator
    
    async def _execute_with_monitoring(
        self, 
        func: Callable, 
        operation_name: str, 
        threshold_multiplier: float,
        is_async: bool,
        *args, 
        **kwargs
    ):
        """执行函数并监控性能"""
        start_time = time.time()
        data_size = self._estimate_data_size(args, kwargs)
        success = False
        error_message = None
        result = None
        
        try:
            if is_async:
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            success = True
            
            # 更新数据大小（基于结果）
            if result:
                if isinstance(result, list):
                    data_size = len(result)
                elif isinstance(result, dict):
                    data_size = 1
                    
        except Exception as e:
            error_message = str(e)
            logger.error(f"❌ {operation_name} 执行失败: {e}")
            raise
        finally:
            end_time = time.time()
            duration = end_time - start_time
            
            # 记录性能指标
            metrics = PerformanceMetrics(
                operation_name=operation_name,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                data_size=data_size,
                success=success,
                error_message=error_message
            )
            
            self._record_metrics(metrics)
            self._check_performance_threshold(metrics, threshold_multiplier)
        
        return result
    
    def _estimate_data_size(self, args: tuple, kwargs: dict) -> int:
        """估算数据大小"""
        data_size = 0
        
        # 检查参数中的列表数据
        for arg in args:
            if isinstance(arg, list):
                data_size = max(data_size, len(arg))
            elif isinstance(arg, dict):
                data_size = max(data_size, 1)
        
        # 检查关键字参数中的数据
        for value in kwargs.values():
            if isinstance(value, list):
                data_size = max(data_size, len(value))
            elif isinstance(value, dict):
                data_size = max(data_size, 1)
        
        return data_size
    
    def _record_metrics(self, metrics: PerformanceMetrics):
        """记录性能指标"""
        self._metrics_history.append(metrics)
        self._operation_stats[metrics.operation_name].append(metrics)
        
        # 限制每个操作的历史记录数量
        if len(self._operation_stats[metrics.operation_name]) > 100:
            self._operation_stats[metrics.operation_name] = \
                self._operation_stats[metrics.operation_name][-100:]
    
    def _check_performance_threshold(self, metrics: PerformanceMetrics, threshold_multiplier: float):
        """检查性能阈值"""
        threshold = self._performance_thresholds.get(metrics.operation_name, 1.0) * threshold_multiplier
        
        if metrics.duration > threshold:
            logger.warning(
                f"⚠️ 性能警告: {metrics.operation_name} 耗时 {metrics.duration:.3f}秒 "
                f"(阈值: {threshold:.3f}秒), 数据量: {metrics.data_size}, "
                f"吞吐量: {metrics.throughput:.1f} items/sec"
            )
        else:
            logger.debug(
                f"⏱️ {metrics.operation_name} 完成: {metrics.duration:.3f}秒, "
                f"数据量: {metrics.data_size}, 吞吐量: {metrics.throughput:.1f} items/sec"
            )
    
    def get_performance_stats(self, operation_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取性能统计信息
        Get performance statistics
        
        Args:
            operation_name: 特定操作名称，None表示所有操作
            
        Returns:
            Dict: 性能统计信息
        """
        if operation_name:
            metrics_list = self._operation_stats.get(operation_name, [])
            if not metrics_list:
                return {"error": f"没有找到操作 {operation_name} 的性能数据"}
            
            return self._calculate_stats(operation_name, metrics_list)
        else:
            # 返回所有操作的统计信息
            all_stats = {}
            for op_name, metrics_list in self._operation_stats.items():
                all_stats[op_name] = self._calculate_stats(op_name, metrics_list)
            
            return {
                "operations": all_stats,
                "total_operations": len(self._metrics_history),
                "monitoring_period": self._get_monitoring_period()
            }
    
    def _calculate_stats(self, operation_name: str, metrics_list: List[PerformanceMetrics]) -> Dict[str, Any]:
        """计算统计信息"""
        if not metrics_list:
            return {}
        
        durations = [m.duration for m in metrics_list]
        throughputs = [m.throughput for m in metrics_list if m.throughput > 0]
        data_sizes = [m.data_size for m in metrics_list]
        success_count = sum(1 for m in metrics_list if m.success)
        
        stats = {
            "operation_name": operation_name,
            "total_calls": len(metrics_list),
            "success_rate": success_count / len(metrics_list) * 100,
            "duration_stats": {
                "min": min(durations),
                "max": max(durations),
                "avg": statistics.mean(durations),
                "median": statistics.median(durations)
            },
            "data_size_stats": {
                "min": min(data_sizes) if data_sizes else 0,
                "max": max(data_sizes) if data_sizes else 0,
                "avg": statistics.mean(data_sizes) if data_sizes else 0
            }
        }
        
        if throughputs:
            stats["throughput_stats"] = {
                "min": min(throughputs),
                "max": max(throughputs),
                "avg": statistics.mean(throughputs),
                "median": statistics.median(throughputs)
            }
        
        # 最近的性能趋势
        recent_metrics = metrics_list[-10:] if len(metrics_list) >= 10 else metrics_list
        recent_durations = [m.duration for m in recent_metrics]
        stats["recent_performance"] = {
            "avg_duration": statistics.mean(recent_durations),
            "trend": self._calculate_trend(recent_durations)
        }
        
        return stats
    
    def _calculate_trend(self, values: List[float]) -> str:
        """计算性能趋势"""
        if len(values) < 3:
            return "insufficient_data"
        
        # 简单的趋势计算：比较前半部分和后半部分的平均值
        mid = len(values) // 2
        first_half_avg = statistics.mean(values[:mid])
        second_half_avg = statistics.mean(values[mid:])
        
        if second_half_avg > first_half_avg * 1.1:
            return "degrading"
        elif second_half_avg < first_half_avg * 0.9:
            return "improving"
        else:
            return "stable"
    
    def _get_monitoring_period(self) -> Dict[str, str]:
        """获取监控时间段"""
        if not self._metrics_history:
            return {"start": "N/A", "end": "N/A"}
        
        start_time = datetime.fromtimestamp(self._metrics_history[0].start_time)
        end_time = datetime.fromtimestamp(self._metrics_history[-1].end_time)
        
        return {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "duration": str(end_time - start_time)
        }
    
    def reset_stats(self, operation_name: Optional[str] = None):
        """
        重置统计信息
        Reset statistics
        
        Args:
            operation_name: 特定操作名称，None表示重置所有
        """
        if operation_name:
            if operation_name in self._operation_stats:
                self._operation_stats[operation_name].clear()
                logger.info(f"🔄 已重置 {operation_name} 的性能统计")
        else:
            self._metrics_history.clear()
            self._operation_stats.clear()
            logger.info("🔄 已重置所有性能统计")
    
    def set_performance_threshold(self, operation_name: str, threshold: float):
        """
        设置性能阈值
        Set performance threshold
        
        Args:
            operation_name: 操作名称
            threshold: 阈值（秒）
        """
        self._performance_thresholds[operation_name] = threshold
        logger.info(f"🎯 设置 {operation_name} 性能阈值为 {threshold:.3f}秒")
    
    def get_slow_operations(self, threshold_multiplier: float = 2.0) -> List[Dict[str, Any]]:
        """
        获取慢操作列表
        Get slow operations list
        
        Args:
            threshold_multiplier: 阈值倍数
            
        Returns:
            List: 慢操作列表
        """
        slow_operations = []
        
        for metrics in self._metrics_history:
            threshold = self._performance_thresholds.get(
                metrics.operation_name, 1.0
            ) * threshold_multiplier
            
            if metrics.duration > threshold:
                slow_operations.append({
                    "operation_name": metrics.operation_name,
                    "duration": metrics.duration,
                    "threshold": threshold,
                    "data_size": metrics.data_size,
                    "throughput": metrics.throughput,
                    "timestamp": datetime.fromtimestamp(metrics.start_time).isoformat(),
                    "success": metrics.success,
                    "error_message": metrics.error_message
                })
        
        # 按持续时间排序
        slow_operations.sort(key=lambda x: x["duration"], reverse=True)
        return slow_operations


# 全局性能监控器实例
performance_monitor = AdapterPerformanceMonitor()


def log_adapter_performance(operation_name: str, threshold_multiplier: float = 1.0):
    """
    适配器性能日志装饰器
    Adapter performance logging decorator
    
    Args:
        operation_name: 操作名称
        threshold_multiplier: 阈值倍数
    """
    return performance_monitor.log_performance(operation_name, threshold_multiplier)