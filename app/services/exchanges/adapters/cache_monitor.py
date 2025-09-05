# -*- coding: utf-8 -*-
"""
缓存监控和管理工具
Cache monitoring and management utilities
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.core.logging import get_logger
from .cache_manager import adapter_cache_manager
from .performance_monitor import performance_monitor

logger = get_logger(__name__)


@dataclass
class CacheHealthMetrics:
    """缓存健康指标"""
    hit_rate: float
    memory_usage_mb: float
    total_entries: int
    expired_entries: int
    evicted_entries: int
    avg_response_time: float
    cache_efficiency: float  # 缓存效率 = 命中率 * (1 - 内存使用率)


class CacheMonitor:
    """
    缓存监控器
    Cache monitor for tracking cache performance and health
    """
    
    def __init__(self, check_interval: int = 300):  # 5分钟检查一次
        """
        初始化缓存监控器
        
        Args:
            check_interval: 检查间隔（秒）
        """
        self.check_interval = check_interval
        self._monitoring_task = None
        self._health_history: List[CacheHealthMetrics] = []
        self._max_history = 288  # 24小时的数据（每5分钟一次）
        
        # 健康阈值
        self._health_thresholds = {
            'min_hit_rate': 60.0,      # 最小命中率60%
            'max_memory_mb': 100.0,    # 最大内存使用100MB
            'max_entries': 800,        # 最大条目数800
            'min_efficiency': 0.5      # 最小效率0.5
        }
        
        logger.info("🔧 缓存监控器初始化完成")
    
    async def start_monitoring(self):
        """开始监控"""
        if self._monitoring_task is None or self._monitoring_task.done():
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("🚀 缓存监控已启动")
    
    async def stop_monitoring(self):
        """停止监控"""
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            logger.info("🛑 缓存监控已停止")
    
    async def _monitoring_loop(self):
        """监控循环"""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                await self._check_cache_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 缓存监控异常: {e}")
    
    async def _check_cache_health(self):
        """检查缓存健康状态"""
        try:
            # 获取缓存统计信息
            cache_stats = adapter_cache_manager.get_stats()
            
            # 获取性能统计信息
            perf_stats = performance_monitor.get_performance_stats()
            
            # 计算健康指标
            health_metrics = self._calculate_health_metrics(cache_stats, perf_stats)
            
            # 记录健康指标
            self._record_health_metrics(health_metrics)
            
            # 检查健康状态
            await self._evaluate_health(health_metrics)
            
            # 执行自动优化
            await self._auto_optimize(health_metrics)
            
        except Exception as e:
            logger.error(f"❌ 缓存健康检查失败: {e}")
    
    def _calculate_health_metrics(
        self, 
        cache_stats: Dict[str, Any], 
        perf_stats: Dict[str, Any]
    ) -> CacheHealthMetrics:
        """计算健康指标"""
        cache_data = cache_stats.get("cache_stats", {})
        current_state = cache_stats.get("current_state", {})
        
        hit_rate = cache_data.get("hit_rate", 0.0)
        memory_usage_mb = current_state.get("memory_usage_mb", 0.0)
        total_entries = current_state.get("total_entries", 0)
        expired_entries = cache_data.get("expired_count", 0)
        evicted_entries = cache_data.get("eviction_count", 0)
        
        # 计算平均响应时间
        avg_response_time = 0.0
        if "operations" in perf_stats:
            response_times = []
            for op_stats in perf_stats["operations"].values():
                if "duration_stats" in op_stats:
                    response_times.append(op_stats["duration_stats"].get("avg", 0))
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
        
        # 计算缓存效率
        memory_usage_rate = min(memory_usage_mb / 100.0, 1.0)  # 假设100MB为满负荷
        cache_efficiency = (hit_rate / 100.0) * (1 - memory_usage_rate)
        
        return CacheHealthMetrics(
            hit_rate=hit_rate,
            memory_usage_mb=memory_usage_mb,
            total_entries=total_entries,
            expired_entries=expired_entries,
            evicted_entries=evicted_entries,
            avg_response_time=avg_response_time,
            cache_efficiency=cache_efficiency
        )
    
    def _record_health_metrics(self, metrics: CacheHealthMetrics):
        """记录健康指标"""
        self._health_history.append(metrics)
        
        # 限制历史记录数量
        if len(self._health_history) > self._max_history:
            self._health_history = self._health_history[-self._max_history:]
        
        # 记录关键指标
        logger.debug(
            f"📊 缓存健康指标: 命中率={metrics.hit_rate:.1f}%, "
            f"内存={metrics.memory_usage_mb:.1f}MB, "
            f"条目数={metrics.total_entries}, "
            f"效率={metrics.cache_efficiency:.3f}"
        )
    
    async def _evaluate_health(self, metrics: CacheHealthMetrics):
        """评估健康状态"""
        issues = []
        
        # 检查命中率
        if metrics.hit_rate < self._health_thresholds['min_hit_rate']:
            issues.append(f"缓存命中率过低: {metrics.hit_rate:.1f}% < {self._health_thresholds['min_hit_rate']}%")
        
        # 检查内存使用
        if metrics.memory_usage_mb > self._health_thresholds['max_memory_mb']:
            issues.append(f"内存使用过高: {metrics.memory_usage_mb:.1f}MB > {self._health_thresholds['max_memory_mb']}MB")
        
        # 检查条目数
        if metrics.total_entries > self._health_thresholds['max_entries']:
            issues.append(f"缓存条目过多: {metrics.total_entries} > {self._health_thresholds['max_entries']}")
        
        # 检查效率
        if metrics.cache_efficiency < self._health_thresholds['min_efficiency']:
            issues.append(f"缓存效率过低: {metrics.cache_efficiency:.3f} < {self._health_thresholds['min_efficiency']}")
        
        # 报告问题
        if issues:
            logger.warning(f"⚠️ 缓存健康问题: {'; '.join(issues)}")
        else:
            logger.debug("✅ 缓存健康状态良好")
    
    async def _auto_optimize(self, metrics: CacheHealthMetrics):
        """自动优化缓存"""
        try:
            # 如果内存使用过高，清理过期条目
            if metrics.memory_usage_mb > self._health_thresholds['max_memory_mb'] * 0.8:
                logger.info("🧹 内存使用较高，执行缓存清理")
                adapter_cache_manager._cleanup_expired()
            
            # 如果命中率过低，调整TTL配置
            if metrics.hit_rate < self._health_thresholds['min_hit_rate']:
                await self._optimize_ttl_config(metrics)
            
            # 如果条目数过多，减少缓存大小
            if metrics.total_entries > self._health_thresholds['max_entries']:
                await self._optimize_cache_size(metrics)
                
        except Exception as e:
            logger.error(f"❌ 自动优化失败: {e}")
    
    async def _optimize_ttl_config(self, metrics: CacheHealthMetrics):
        """优化TTL配置"""
        # 简单的TTL优化策略：如果命中率低，增加TTL
        logger.info("🎯 优化TTL配置以提高命中率")
        
        # 这里可以实现更复杂的TTL优化逻辑
        # 例如：分析不同数据类型的访问模式，动态调整TTL
    
    async def _optimize_cache_size(self, metrics: CacheHealthMetrics):
        """优化缓存大小"""
        logger.info("📏 优化缓存大小")
        
        # 可以实现缓存大小的动态调整
        # 例如：根据内存使用情况调整max_size
    
    def get_health_report(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取健康报告
        Get health report
        
        Args:
            hours: 报告时间范围（小时）
            
        Returns:
            Dict: 健康报告
        """
        if not self._health_history:
            return {"error": "没有健康数据"}
        
        # 计算时间范围
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_metrics = self._health_history[-int(hours * 12):]  # 每5分钟一次
        
        if not recent_metrics:
            recent_metrics = self._health_history[-1:]
        
        # 计算统计信息
        hit_rates = [m.hit_rate for m in recent_metrics]
        memory_usages = [m.memory_usage_mb for m in recent_metrics]
        efficiencies = [m.cache_efficiency for m in recent_metrics]
        
        return {
            "time_range": f"最近 {hours} 小时",
            "data_points": len(recent_metrics),
            "hit_rate": {
                "current": hit_rates[-1] if hit_rates else 0,
                "avg": sum(hit_rates) / len(hit_rates) if hit_rates else 0,
                "min": min(hit_rates) if hit_rates else 0,
                "max": max(hit_rates) if hit_rates else 0,
                "trend": self._calculate_trend(hit_rates)
            },
            "memory_usage": {
                "current_mb": memory_usages[-1] if memory_usages else 0,
                "avg_mb": sum(memory_usages) / len(memory_usages) if memory_usages else 0,
                "peak_mb": max(memory_usages) if memory_usages else 0,
                "trend": self._calculate_trend(memory_usages)
            },
            "efficiency": {
                "current": efficiencies[-1] if efficiencies else 0,
                "avg": sum(efficiencies) / len(efficiencies) if efficiencies else 0,
                "trend": self._calculate_trend(efficiencies)
            },
            "health_status": self._get_overall_health_status(recent_metrics[-1] if recent_metrics else None),
            "recommendations": self._get_recommendations(recent_metrics[-1] if recent_metrics else None)
        }
    
    def _calculate_trend(self, values: List[float]) -> str:
        """计算趋势"""
        if len(values) < 3:
            return "insufficient_data"
        
        # 简单的趋势计算
        recent_avg = sum(values[-3:]) / 3
        earlier_avg = sum(values[:3]) / 3
        
        if recent_avg > earlier_avg * 1.1:
            return "increasing"
        elif recent_avg < earlier_avg * 0.9:
            return "decreasing"
        else:
            return "stable"
    
    def _get_overall_health_status(self, metrics: Optional[CacheHealthMetrics]) -> str:
        """获取整体健康状态"""
        if not metrics:
            return "unknown"
        
        issues = 0
        
        if metrics.hit_rate < self._health_thresholds['min_hit_rate']:
            issues += 1
        if metrics.memory_usage_mb > self._health_thresholds['max_memory_mb']:
            issues += 1
        if metrics.total_entries > self._health_thresholds['max_entries']:
            issues += 1
        if metrics.cache_efficiency < self._health_thresholds['min_efficiency']:
            issues += 1
        
        if issues == 0:
            return "excellent"
        elif issues == 1:
            return "good"
        elif issues == 2:
            return "fair"
        else:
            return "poor"
    
    def _get_recommendations(self, metrics: Optional[CacheHealthMetrics]) -> List[str]:
        """获取优化建议"""
        if not metrics:
            return []
        
        recommendations = []
        
        if metrics.hit_rate < self._health_thresholds['min_hit_rate']:
            recommendations.append("考虑增加缓存TTL或优化缓存键策略")
        
        if metrics.memory_usage_mb > self._health_thresholds['max_memory_mb']:
            recommendations.append("考虑减少缓存大小或增加清理频率")
        
        if metrics.total_entries > self._health_thresholds['max_entries']:
            recommendations.append("考虑减少最大缓存条目数或优化数据结构")
        
        if metrics.cache_efficiency < self._health_thresholds['min_efficiency']:
            recommendations.append("考虑重新评估缓存策略和数据访问模式")
        
        if not recommendations:
            recommendations.append("缓存运行良好，继续保持当前配置")
        
        return recommendations


# 全局缓存监控器实例
cache_monitor = CacheMonitor()