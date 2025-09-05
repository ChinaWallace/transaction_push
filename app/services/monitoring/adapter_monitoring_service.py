# -*- coding: utf-8 -*-
"""
适配器监控服务
Adapter monitoring service

监控数据适配器的健康状态、性能指标和错误情况
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from app.core.logging import get_logger
from app.services.exchanges.adapters.adapter_factory import AdapterFactory
from app.services.exchanges.adapters.adapter_diagnostics import AdapterDiagnostics

logger = get_logger(__name__)


@dataclass
class AdapterHealthStatus:
    """适配器健康状态"""
    exchange: str
    status: str  # healthy, unhealthy, error, unknown
    last_check: str
    response_time: float
    error_count: int
    success_rate: float
    details: Dict[str, Any]


@dataclass
class AdapterPerformanceMetrics:
    """适配器性能指标"""
    exchange: str
    avg_response_time: float
    max_response_time: float
    min_response_time: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    cache_hit_rate: float
    last_updated: str


@dataclass
class AdapterErrorInfo:
    """适配器错误信息"""
    exchange: str
    error_type: str
    error_message: str
    error_count: int
    first_occurrence: str
    last_occurrence: str
    data_type: str


class AdapterMonitoringService:
    """
    适配器监控服务
    Adapter monitoring service
    
    提供适配器系统的实时监控、健康检查和性能统计功能
    """
    
    def __init__(self):
        self.health_status: Dict[str, AdapterHealthStatus] = {}
        self.performance_metrics: Dict[str, AdapterPerformanceMetrics] = {}
        self.error_history: List[AdapterErrorInfo] = []
        self.diagnostics = AdapterDiagnostics()
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        
        # 配置参数
        self.check_interval = 300  # 5分钟检查一次
        self.error_threshold = 10  # 错误阈值
        self.response_time_threshold = 5.0  # 响应时间阈值（秒）
        self.max_error_history = 1000  # 最大错误历史记录数
        
        logger.info("🔧 适配器监控服务初始化完成")
    
    async def start_monitoring(self) -> None:
        """
        启动监控
        Start monitoring
        """
        if self._monitoring_active:
            logger.warning("⚠️ 适配器监控已经在运行")
            return
        
        self._monitoring_active = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("🚀 适配器监控服务已启动")
    
    async def stop_monitoring(self) -> None:
        """
        停止监控
        Stop monitoring
        """
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("🛑 适配器监控服务已停止")
    
    async def _monitoring_loop(self) -> None:
        """监控循环"""
        while self._monitoring_active:
            try:
                await self._perform_health_checks()
                await self._update_performance_metrics()
                await self._cleanup_old_errors()
                
                # 检查告警条件
                await self._check_alert_conditions()
                
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 监控循环异常: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再继续
    
    async def _perform_health_checks(self) -> None:
        """执行健康检查"""
        exchanges = AdapterFactory.get_supported_exchanges()
        
        for exchange in exchanges:
            try:
                start_time = datetime.now()
                
                # 执行健康检查
                is_healthy = await self.diagnostics.quick_health_check(exchange)
                
                response_time = (datetime.now() - start_time).total_seconds()
                
                # 获取详细信息
                details = {}
                try:
                    adapter = AdapterFactory.get_adapter(exchange)
                    details = adapter.get_adapter_info()
                except Exception as e:
                    details = {"error": str(e)}
                
                # 更新健康状态
                self.health_status[exchange] = AdapterHealthStatus(
                    exchange=exchange,
                    status="healthy" if is_healthy else "unhealthy",
                    last_check=datetime.now().isoformat(),
                    response_time=response_time,
                    error_count=self._get_recent_error_count(exchange),
                    success_rate=self._calculate_success_rate(exchange),
                    details=details
                )
                
                logger.debug(f"🔍 {exchange} 健康检查完成: {is_healthy}")
                
            except Exception as e:
                # 记录错误
                self._record_error(exchange, "health_check", str(e))
                
                self.health_status[exchange] = AdapterHealthStatus(
                    exchange=exchange,
                    status="error",
                    last_check=datetime.now().isoformat(),
                    response_time=0.0,
                    error_count=self._get_recent_error_count(exchange),
                    success_rate=0.0,
                    details={"error": str(e)}
                )
                
                logger.error(f"❌ {exchange} 健康检查失败: {e}")
    
    async def _update_performance_metrics(self) -> None:
        """更新性能指标"""
        exchanges = AdapterFactory.get_supported_exchanges()
        
        for exchange in exchanges:
            try:
                # 这里可以从缓存或日志中获取性能数据
                # 目前使用模拟数据，实际实现中应该从性能监控器获取
                
                metrics = AdapterPerformanceMetrics(
                    exchange=exchange,
                    avg_response_time=0.1,  # 模拟数据
                    max_response_time=0.5,
                    min_response_time=0.05,
                    total_requests=1000,
                    successful_requests=950,
                    failed_requests=50,
                    cache_hit_rate=0.8,
                    last_updated=datetime.now().isoformat()
                )
                
                self.performance_metrics[exchange] = metrics
                
            except Exception as e:
                logger.error(f"❌ 更新 {exchange} 性能指标失败: {e}")
    
    def _record_error(self, exchange: str, error_type: str, error_message: str, 
                     data_type: str = "unknown") -> None:
        """记录错误"""
        now = datetime.now().isoformat()
        
        # 查找是否已存在相同错误
        existing_error = None
        for error in self.error_history:
            if (error.exchange == exchange and 
                error.error_type == error_type and 
                error.error_message == error_message):
                existing_error = error
                break
        
        if existing_error:
            # 更新现有错误
            existing_error.error_count += 1
            existing_error.last_occurrence = now
        else:
            # 创建新错误记录
            error_info = AdapterErrorInfo(
                exchange=exchange,
                error_type=error_type,
                error_message=error_message,
                error_count=1,
                first_occurrence=now,
                last_occurrence=now,
                data_type=data_type
            )
            self.error_history.append(error_info)
        
        # 限制错误历史记录数量
        if len(self.error_history) > self.max_error_history:
            self.error_history = self.error_history[-self.max_error_history:]
    
    def _get_recent_error_count(self, exchange: str, hours: int = 24) -> int:
        """获取最近错误数量"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff_time.isoformat()
        
        count = 0
        for error in self.error_history:
            if (error.exchange == exchange and 
                error.last_occurrence >= cutoff_str):
                count += error.error_count
        
        return count
    
    def _calculate_success_rate(self, exchange: str) -> float:
        """计算成功率"""
        metrics = self.performance_metrics.get(exchange)
        if not metrics or metrics.total_requests == 0:
            return 1.0
        
        return metrics.successful_requests / metrics.total_requests
    
    async def _cleanup_old_errors(self) -> None:
        """清理旧错误记录"""
        cutoff_time = datetime.now() - timedelta(days=7)  # 保留7天的错误记录
        cutoff_str = cutoff_time.isoformat()
        
        self.error_history = [
            error for error in self.error_history
            if error.last_occurrence >= cutoff_str
        ]
    
    async def _check_alert_conditions(self) -> None:
        """检查告警条件"""
        for exchange, health in self.health_status.items():
            # 检查错误数量
            if health.error_count > self.error_threshold:
                logger.warning(f"⚠️ {exchange} 错误数量过多: {health.error_count}")
            
            # 检查响应时间
            if health.response_time > self.response_time_threshold:
                logger.warning(f"⚠️ {exchange} 响应时间过长: {health.response_time:.2f}s")
            
            # 检查成功率
            if health.success_rate < 0.9:
                logger.warning(f"⚠️ {exchange} 成功率过低: {health.success_rate:.2%}")
    
    async def get_overall_status(self) -> Dict[str, Any]:
        """
        获取整体状态
        Get overall status
        """
        if not self.health_status:
            return {
                "status": "unknown",
                "message": "监控数据不可用",
                "timestamp": datetime.now().isoformat()
            }
        
        # 统计各状态数量
        status_counts = {"healthy": 0, "unhealthy": 0, "error": 0, "unknown": 0}
        total_exchanges = len(self.health_status)
        
        for health in self.health_status.values():
            status_counts[health.status] = status_counts.get(health.status, 0) + 1
        
        # 确定整体状态
        if status_counts["error"] > 0:
            overall_status = "error"
        elif status_counts["unhealthy"] > 0:
            overall_status = "degraded"
        elif status_counts["healthy"] == total_exchanges:
            overall_status = "healthy"
        else:
            overall_status = "unknown"
        
        return {
            "status": overall_status,
            "total_exchanges": total_exchanges,
            "status_breakdown": status_counts,
            "monitoring_active": self._monitoring_active,
            "last_check": max(
                (h.last_check for h in self.health_status.values()),
                default=datetime.now().isoformat()
            ),
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_exchange_status(self, exchange: str) -> Dict[str, Any]:
        """
        获取特定交易所状态
        Get specific exchange status
        """
        if exchange not in self.health_status:
            return {
                "exchange": exchange,
                "status": "unknown",
                "message": "未找到监控数据",
                "timestamp": datetime.now().isoformat()
            }
        
        health = self.health_status[exchange]
        metrics = self.performance_metrics.get(exchange)
        recent_errors = [
            error for error in self.error_history
            if error.exchange == exchange
        ][-10:]  # 最近10个错误
        
        return {
            "exchange": exchange,
            "health": asdict(health),
            "performance": asdict(metrics) if metrics else None,
            "recent_errors": [asdict(error) for error in recent_errors],
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_all_statuses(self) -> Dict[str, Any]:
        """
        获取所有交易所状态
        Get all exchange statuses
        """
        overall = await self.get_overall_status()
        
        exchange_statuses = {}
        for exchange in self.health_status.keys():
            exchange_statuses[exchange] = await self.get_exchange_status(exchange)
        
        return {
            "overall": overall,
            "exchanges": exchange_statuses,
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """
        获取性能摘要
        Get performance summary
        """
        if not self.performance_metrics:
            return {
                "status": "no_data",
                "message": "性能数据不可用",
                "timestamp": datetime.now().isoformat()
            }
        
        # 计算汇总统计
        total_requests = sum(m.total_requests for m in self.performance_metrics.values())
        total_successful = sum(m.successful_requests for m in self.performance_metrics.values())
        total_failed = sum(m.failed_requests for m in self.performance_metrics.values())
        
        avg_response_times = [m.avg_response_time for m in self.performance_metrics.values()]
        overall_avg_response_time = sum(avg_response_times) / len(avg_response_times) if avg_response_times else 0
        
        cache_hit_rates = [m.cache_hit_rate for m in self.performance_metrics.values()]
        overall_cache_hit_rate = sum(cache_hit_rates) / len(cache_hit_rates) if cache_hit_rates else 0
        
        return {
            "summary": {
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "failed_requests": total_failed,
                "success_rate": total_successful / total_requests if total_requests > 0 else 0,
                "avg_response_time": overall_avg_response_time,
                "cache_hit_rate": overall_cache_hit_rate
            },
            "by_exchange": {
                exchange: asdict(metrics)
                for exchange, metrics in self.performance_metrics.items()
            },
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_error_summary(self) -> Dict[str, Any]:
        """
        获取错误摘要
        Get error summary
        """
        if not self.error_history:
            return {
                "status": "no_errors",
                "message": "无错误记录",
                "timestamp": datetime.now().isoformat()
            }
        
        # 按交易所统计错误
        error_by_exchange = {}
        error_by_type = {}
        
        for error in self.error_history:
            # 按交易所统计
            if error.exchange not in error_by_exchange:
                error_by_exchange[error.exchange] = 0
            error_by_exchange[error.exchange] += error.error_count
            
            # 按类型统计
            if error.error_type not in error_by_type:
                error_by_type[error.error_type] = 0
            error_by_type[error.error_type] += error.error_count
        
        # 最近的错误
        recent_errors = sorted(
            self.error_history,
            key=lambda x: x.last_occurrence,
            reverse=True
        )[:20]  # 最近20个错误
        
        return {
            "total_errors": len(self.error_history),
            "error_by_exchange": error_by_exchange,
            "error_by_type": error_by_type,
            "recent_errors": [asdict(error) for error in recent_errors],
            "timestamp": datetime.now().isoformat()
        }
    
    async def run_comprehensive_diagnostics(self, exchange: str = None) -> Dict[str, Any]:
        """
        运行综合诊断
        Run comprehensive diagnostics
        """
        if exchange:
            exchanges = [exchange]
        else:
            exchanges = AdapterFactory.get_supported_exchanges()
        
        logger.info(f"🔍 开始适配器综合诊断: {exchanges}")
        
        try:
            diagnostics_result = await self.diagnostics.run_comprehensive_diagnostics(exchanges)
            
            # 记录诊断结果中的错误
            for exchange_name, result in diagnostics_result.get("exchange_results", {}).items():
                if result.get("status") != "healthy":
                    for error in result.get("errors", []):
                        self._record_error(exchange_name, "diagnostic", error)
            
            return diagnostics_result
            
        except Exception as e:
            logger.error(f"❌ 综合诊断失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_monitoring_config(self) -> Dict[str, Any]:
        """获取监控配置"""
        return {
            "check_interval": self.check_interval,
            "error_threshold": self.error_threshold,
            "response_time_threshold": self.response_time_threshold,
            "max_error_history": self.max_error_history,
            "monitoring_active": self._monitoring_active
        }
    
    def update_monitoring_config(self, config: Dict[str, Any]) -> None:
        """更新监控配置"""
        if "check_interval" in config:
            self.check_interval = max(60, config["check_interval"])  # 最小1分钟
        if "error_threshold" in config:
            self.error_threshold = max(1, config["error_threshold"])
        if "response_time_threshold" in config:
            self.response_time_threshold = max(0.1, config["response_time_threshold"])
        if "max_error_history" in config:
            self.max_error_history = max(100, config["max_error_history"])
        
        logger.info(f"📝 监控配置已更新: {config}")


# 全局监控服务实例
_adapter_monitoring_service: Optional[AdapterMonitoringService] = None


def get_adapter_monitoring_service() -> AdapterMonitoringService:
    """获取适配器监控服务实例"""
    global _adapter_monitoring_service
    if _adapter_monitoring_service is None:
        _adapter_monitoring_service = AdapterMonitoringService()
    return _adapter_monitoring_service


async def start_adapter_monitoring() -> None:
    """启动适配器监控"""
    service = get_adapter_monitoring_service()
    await service.start_monitoring()


async def stop_adapter_monitoring() -> None:
    """停止适配器监控"""
    service = get_adapter_monitoring_service()
    await service.stop_monitoring()


# 初始化日志
logger.info("🔧 适配器监控服务模块初始化完成")