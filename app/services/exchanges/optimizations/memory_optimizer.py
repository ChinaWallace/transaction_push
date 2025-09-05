# -*- coding: utf-8 -*-
"""
内存优化器
Memory Optimizer - 监控和优化内存使用，防止内存泄漏
"""

import gc
import psutil
import asyncio
import weakref
import tracemalloc
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MemorySnapshot:
    """内存快照"""
    timestamp: datetime
    rss_mb: float  # 物理内存使用 (MB)
    vms_mb: float  # 虚拟内存使用 (MB)
    percent: float  # 内存使用百分比
    available_mb: float  # 可用内存 (MB)
    gc_counts: Tuple[int, int, int]  # 垃圾回收计数
    object_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class MemoryAlert:
    """内存告警"""
    timestamp: datetime
    alert_type: str
    message: str
    memory_usage_mb: float
    threshold_mb: float
    severity: str  # 'warning', 'critical'


class MemoryOptimizer:
    """内存优化器"""
    
    def __init__(self, 
                 memory_limit_mb: float = 1024,  # 1GB默认限制
                 warning_threshold: float = 0.8,  # 80%警告阈值
                 critical_threshold: float = 0.9,  # 90%严重阈值
                 monitoring_interval: float = 30.0,  # 30秒监控间隔
                 cleanup_interval: float = 300.0,  # 5分钟清理间隔
                 enable_tracemalloc: bool = False):  # 是否启用内存跟踪
        
        self.memory_limit_mb = memory_limit_mb
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.monitoring_interval = monitoring_interval
        self.cleanup_interval = cleanup_interval
        self.enable_tracemalloc = enable_tracemalloc
        
        # 监控数据
        self.snapshots: deque = deque(maxlen=1000)  # 保留最近1000个快照
        self.alerts: deque = deque(maxlen=100)  # 保留最近100个告警
        
        # 对象跟踪
        self.tracked_objects: Dict[str, weakref.WeakSet] = defaultdict(weakref.WeakSet)
        self.object_creation_counts: Dict[str, int] = defaultdict(int)
        self.object_cleanup_counts: Dict[str, int] = defaultdict(int)
        
        # 缓存管理
        self.cache_registries: List[weakref.ref] = []
        self.cache_cleanup_callbacks: List[callable] = []
        
        # 运行状态
        self.is_running = False
        self.monitoring_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        
        # 统计信息
        self.stats = {
            'start_time': datetime.now(),
            'total_cleanups': 0,
            'total_alerts': 0,
            'peak_memory_mb': 0.0,
            'gc_collections': 0,
            'cache_cleanups': 0
        }
        
        # 启用内存跟踪
        if self.enable_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start()
            logger.info("🔍 启用内存跟踪")
        
        logger.info(f"🧠 内存优化器初始化: 限制 {memory_limit_mb}MB, 警告阈值 {warning_threshold*100}%")
    
    async def start(self):
        """启动内存优化器"""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("🚀 启动内存优化器")
        
        # 启动监控任务
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # 记录初始快照
        await self._take_snapshot()
        
        logger.info("✅ 内存优化器启动完成")
    
    async def stop(self):
        """停止内存优化器"""
        if not self.is_running:
            return
        
        logger.info("🛑 停止内存优化器")
        self.is_running = False
        
        # 取消任务
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
        
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
        
        # 等待任务完成
        tasks = [t for t in [self.monitoring_task, self.cleanup_task] if t]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 最终清理
        await self._force_cleanup()
        
        logger.info("✅ 内存优化器已停止")
    
    async def _monitoring_loop(self):
        """监控循环"""
        try:
            while self.is_running:
                try:
                    # 拍摄内存快照
                    snapshot = await self._take_snapshot()
                    
                    # 检查内存使用
                    await self._check_memory_usage(snapshot)
                    
                    # 更新统计
                    if snapshot.rss_mb > self.stats['peak_memory_mb']:
                        self.stats['peak_memory_mb'] = snapshot.rss_mb
                    
                    await asyncio.sleep(self.monitoring_interval)
                    
                except Exception as e:
                    logger.error(f"❌ 内存监控异常: {e}")
                    await asyncio.sleep(5)
        
        except asyncio.CancelledError:
            logger.debug("🔄 内存监控任务被取消")
        except Exception as e:
            logger.error(f"❌ 内存监控循环异常: {e}")
    
    async def _cleanup_loop(self):
        """清理循环"""
        try:
            while self.is_running:
                try:
                    await self._perform_cleanup()
                    await asyncio.sleep(self.cleanup_interval)
                    
                except Exception as e:
                    logger.error(f"❌ 内存清理异常: {e}")
                    await asyncio.sleep(30)
        
        except asyncio.CancelledError:
            logger.debug("🔄 内存清理任务被取消")
        except Exception as e:
            logger.error(f"❌ 内存清理循环异常: {e}")
    
    async def _take_snapshot(self) -> MemorySnapshot:
        """拍摄内存快照"""
        try:
            # 获取进程内存信息
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            # 获取系统内存信息
            system_memory = psutil.virtual_memory()
            
            # 获取垃圾回收信息
            gc_counts = gc.get_count()
            
            # 获取对象计数
            object_counts = {}
            if self.enable_tracemalloc and tracemalloc.is_tracing():
                try:
                    current, peak = tracemalloc.get_traced_memory()
                    object_counts['traced_current_mb'] = current / 1024 / 1024
                    object_counts['traced_peak_mb'] = peak / 1024 / 1024
                except Exception as e:
                    logger.debug(f"🔍 获取内存跟踪信息失败: {e}")
            
            # 创建快照
            snapshot = MemorySnapshot(
                timestamp=datetime.now(),
                rss_mb=memory_info.rss / 1024 / 1024,
                vms_mb=memory_info.vms / 1024 / 1024,
                percent=memory_percent,
                available_mb=system_memory.available / 1024 / 1024,
                gc_counts=gc_counts,
                object_counts=object_counts
            )
            
            # 添加到快照队列
            self.snapshots.append(snapshot)
            
            return snapshot
            
        except Exception as e:
            logger.error(f"❌ 拍摄内存快照异常: {e}")
            # 返回空快照
            return MemorySnapshot(
                timestamp=datetime.now(),
                rss_mb=0.0,
                vms_mb=0.0,
                percent=0.0,
                available_mb=0.0,
                gc_counts=(0, 0, 0)
            )
    
    async def _check_memory_usage(self, snapshot: MemorySnapshot):
        """检查内存使用情况"""
        try:
            memory_usage_mb = snapshot.rss_mb
            usage_ratio = memory_usage_mb / self.memory_limit_mb
            
            # 检查是否超过阈值
            if usage_ratio >= self.critical_threshold:
                await self._create_alert(
                    alert_type="critical_memory",
                    message=f"内存使用达到严重水平: {memory_usage_mb:.1f}MB ({usage_ratio:.1%})",
                    memory_usage_mb=memory_usage_mb,
                    threshold_mb=self.memory_limit_mb * self.critical_threshold,
                    severity="critical"
                )
                
                # 触发紧急清理
                await self._emergency_cleanup()
                
            elif usage_ratio >= self.warning_threshold:
                await self._create_alert(
                    alert_type="warning_memory",
                    message=f"内存使用达到警告水平: {memory_usage_mb:.1f}MB ({usage_ratio:.1%})",
                    memory_usage_mb=memory_usage_mb,
                    threshold_mb=self.memory_limit_mb * self.warning_threshold,
                    severity="warning"
                )
                
                # 触发预防性清理
                await self._preventive_cleanup()
        
        except Exception as e:
            logger.error(f"❌ 检查内存使用异常: {e}")
    
    async def _create_alert(self, alert_type: str, message: str, 
                          memory_usage_mb: float, threshold_mb: float, severity: str):
        """创建内存告警"""
        try:
            alert = MemoryAlert(
                timestamp=datetime.now(),
                alert_type=alert_type,
                message=message,
                memory_usage_mb=memory_usage_mb,
                threshold_mb=threshold_mb,
                severity=severity
            )
            
            self.alerts.append(alert)
            self.stats['total_alerts'] += 1
            
            # 记录日志
            if severity == "critical":
                logger.error(f"🚨 {message}")
            else:
                logger.warning(f"⚠️ {message}")
        
        except Exception as e:
            logger.error(f"❌ 创建内存告警异常: {e}")
    
    async def _perform_cleanup(self):
        """执行常规清理"""
        try:
            logger.debug("🧹 执行常规内存清理")
            
            # 清理缓存
            await self._cleanup_caches()
            
            # 清理弱引用对象
            await self._cleanup_weak_references()
            
            # 执行垃圾回收
            await self._perform_garbage_collection()
            
            self.stats['total_cleanups'] += 1
            
        except Exception as e:
            logger.error(f"❌ 常规内存清理异常: {e}")
    
    async def _preventive_cleanup(self):
        """预防性清理"""
        try:
            logger.info("🧹 执行预防性内存清理")
            
            # 执行常规清理
            await self._perform_cleanup()
            
            # 额外的预防性措施
            await self._cleanup_large_objects()
            
        except Exception as e:
            logger.error(f"❌ 预防性内存清理异常: {e}")
    
    async def _emergency_cleanup(self):
        """紧急清理"""
        try:
            logger.error("🚨 执行紧急内存清理")
            
            # 执行所有清理措施
            await self._perform_cleanup()
            await self._cleanup_large_objects()
            await self._force_cleanup()
            
            # 强制垃圾回收
            for i in range(3):
                collected = gc.collect()
                logger.info(f"🗑️ 强制垃圾回收第{i+1}次: 清理 {collected} 个对象")
                await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"❌ 紧急内存清理异常: {e}")
    
    async def _cleanup_caches(self):
        """清理缓存"""
        try:
            cleaned_count = 0
            
            # 调用注册的缓存清理回调
            for callback in self.cache_cleanup_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                    cleaned_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ 缓存清理回调异常: {e}")
            
            # 清理已失效的缓存注册
            self.cache_registries = [ref for ref in self.cache_registries if ref() is not None]
            
            if cleaned_count > 0:
                self.stats['cache_cleanups'] += cleaned_count
                logger.debug(f"🧹 清理 {cleaned_count} 个缓存")
        
        except Exception as e:
            logger.error(f"❌ 清理缓存异常: {e}")
    
    async def _cleanup_weak_references(self):
        """清理弱引用对象"""
        try:
            cleaned_count = 0
            
            for obj_type, weak_set in self.tracked_objects.items():
                # 清理已失效的弱引用
                initial_count = len(weak_set)
                # WeakSet会自动清理失效的引用，这里只是触发清理
                list(weak_set)  # 遍历触发清理
                final_count = len(weak_set)
                
                if initial_count != final_count:
                    cleaned = initial_count - final_count
                    cleaned_count += cleaned
                    self.object_cleanup_counts[obj_type] += cleaned
            
            if cleaned_count > 0:
                logger.debug(f"🧹 清理 {cleaned_count} 个弱引用对象")
        
        except Exception as e:
            logger.error(f"❌ 清理弱引用对象异常: {e}")
    
    async def _cleanup_large_objects(self):
        """清理大对象"""
        try:
            # 这里可以实现特定的大对象清理逻辑
            # 例如清理大的数据结构、临时文件等
            
            # 清理快照历史（保留最近的）
            if len(self.snapshots) > 500:
                removed = len(self.snapshots) - 500
                for _ in range(removed):
                    self.snapshots.popleft()
                logger.debug(f"🧹 清理 {removed} 个历史快照")
            
            # 清理告警历史
            if len(self.alerts) > 50:
                removed = len(self.alerts) - 50
                for _ in range(removed):
                    self.alerts.popleft()
                logger.debug(f"🧹 清理 {removed} 个历史告警")
        
        except Exception as e:
            logger.error(f"❌ 清理大对象异常: {e}")
    
    async def _perform_garbage_collection(self):
        """执行垃圾回收"""
        try:
            # 执行垃圾回收
            collected = gc.collect()
            
            if collected > 0:
                self.stats['gc_collections'] += 1
                logger.debug(f"🗑️ 垃圾回收: 清理 {collected} 个对象")
        
        except Exception as e:
            logger.error(f"❌ 垃圾回收异常: {e}")
    
    async def _force_cleanup(self):
        """强制清理"""
        try:
            logger.info("🧹 执行强制内存清理")
            
            # 清理所有跟踪的对象
            for obj_type in list(self.tracked_objects.keys()):
                self.tracked_objects[obj_type].clear()
            
            # 清理缓存注册
            self.cache_registries.clear()
            
            # 强制垃圾回收
            for _ in range(3):
                gc.collect()
            
            logger.info("✅ 强制内存清理完成")
        
        except Exception as e:
            logger.error(f"❌ 强制内存清理异常: {e}")
    
    def register_cache_cleanup(self, cleanup_callback: callable):
        """注册缓存清理回调"""
        try:
            self.cache_cleanup_callbacks.append(cleanup_callback)
            logger.debug("📝 注册缓存清理回调")
        except Exception as e:
            logger.error(f"❌ 注册缓存清理回调异常: {e}")
    
    def track_object(self, obj: Any, obj_type: str = None):
        """跟踪对象"""
        try:
            if obj_type is None:
                obj_type = type(obj).__name__
            
            self.tracked_objects[obj_type].add(obj)
            self.object_creation_counts[obj_type] += 1
            
        except Exception as e:
            logger.debug(f"🔍 跟踪对象异常: {e}")
    
    def get_memory_status(self) -> Dict[str, Any]:
        """获取内存状态"""
        try:
            current_snapshot = None
            if self.snapshots:
                current_snapshot = self.snapshots[-1]
            
            # 计算内存趋势
            memory_trend = "stable"
            if len(self.snapshots) >= 2:
                recent_avg = sum(s.rss_mb for s in list(self.snapshots)[-5:]) / min(5, len(self.snapshots))
                older_avg = sum(s.rss_mb for s in list(self.snapshots)[-10:-5]) / min(5, len(self.snapshots) - 5) if len(self.snapshots) > 5 else recent_avg
                
                if recent_avg > older_avg * 1.1:
                    memory_trend = "increasing"
                elif recent_avg < older_avg * 0.9:
                    memory_trend = "decreasing"
            
            return {
                'is_running': self.is_running,
                'memory_limit_mb': self.memory_limit_mb,
                'warning_threshold': self.warning_threshold,
                'critical_threshold': self.critical_threshold,
                'current_memory': {
                    'rss_mb': current_snapshot.rss_mb if current_snapshot else 0,
                    'vms_mb': current_snapshot.vms_mb if current_snapshot else 0,
                    'percent': current_snapshot.percent if current_snapshot else 0,
                    'available_mb': current_snapshot.available_mb if current_snapshot else 0,
                    'usage_ratio': (current_snapshot.rss_mb / self.memory_limit_mb) if current_snapshot else 0
                },
                'memory_trend': memory_trend,
                'statistics': self.stats.copy(),
                'tracked_objects': {
                    obj_type: len(weak_set) 
                    for obj_type, weak_set in self.tracked_objects.items()
                },
                'object_creation_counts': dict(self.object_creation_counts),
                'object_cleanup_counts': dict(self.object_cleanup_counts),
                'recent_alerts': [
                    {
                        'timestamp': alert.timestamp.isoformat(),
                        'type': alert.alert_type,
                        'message': alert.message,
                        'severity': alert.severity
                    }
                    for alert in list(self.alerts)[-5:]  # 最近5个告警
                ],
                'snapshot_count': len(self.snapshots),
                'timestamp': datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"❌ 获取内存状态异常: {e}")
            return {'error': str(e)}
    
    def get_memory_history(self, hours: int = 1) -> List[Dict[str, Any]]:
        """获取内存历史"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            history = []
            for snapshot in self.snapshots:
                if snapshot.timestamp >= cutoff_time:
                    history.append({
                        'timestamp': snapshot.timestamp.isoformat(),
                        'rss_mb': snapshot.rss_mb,
                        'vms_mb': snapshot.vms_mb,
                        'percent': snapshot.percent,
                        'available_mb': snapshot.available_mb,
                        'gc_counts': snapshot.gc_counts
                    })
            
            return history
        
        except Exception as e:
            logger.error(f"❌ 获取内存历史异常: {e}")
            return []


# 全局内存优化器实例
_global_memory_optimizer: Optional[MemoryOptimizer] = None


async def get_memory_optimizer(**kwargs) -> MemoryOptimizer:
    """获取全局内存优化器实例"""
    global _global_memory_optimizer
    
    if _global_memory_optimizer is None:
        _global_memory_optimizer = MemoryOptimizer(**kwargs)
        await _global_memory_optimizer.start()
    
    return _global_memory_optimizer


async def cleanup_memory_optimizer():
    """清理全局内存优化器"""
    global _global_memory_optimizer
    
    if _global_memory_optimizer:
        await _global_memory_optimizer.stop()
        _global_memory_optimizer = None


def track_object(obj: Any, obj_type: str = None):
    """便利函数：跟踪对象"""
    global _global_memory_optimizer
    
    if _global_memory_optimizer:
        _global_memory_optimizer.track_object(obj, obj_type)


def register_cache_cleanup(cleanup_callback: callable):
    """便利函数：注册缓存清理回调"""
    global _global_memory_optimizer
    
    if _global_memory_optimizer:
        _global_memory_optimizer.register_cache_cleanup(cleanup_callback)