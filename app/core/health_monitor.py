# -*- coding: utf-8 -*-
"""
服务健康监控系统
Service Health Monitoring System
"""

import asyncio
import time
import psutil
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager

from app.core.logging import get_logger, log_structured_error
from app.utils.dependency_manager import dependency_manager

logger = get_logger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AlertLevel(Enum):
    """警报级别枚举"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    service_name: str
    status: HealthStatus
    response_time: float
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    dependencies_status: Dict[str, HealthStatus] = field(default_factory=dict)


@dataclass
class ServiceMetrics:
    """服务指标"""
    service_name: str
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    request_count: int = 0
    error_count: int = 0
    average_response_time: float = 0.0
    last_request_time: Optional[datetime] = None
    uptime: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "service_name": self.service_name,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "average_response_time": self.average_response_time,
            "last_request_time": self.last_request_time.isoformat() if self.last_request_time else None,
            "uptime": self.uptime
        }


@dataclass
class AlertRule:
    """警报规则"""
    name: str
    condition: Callable[[HealthCheckResult], bool]
    level: AlertLevel
    message_template: str
    cooldown_seconds: int = 300  # 5分钟冷却时间
    enabled: bool = True


@dataclass
class Alert:
    """警报"""
    rule_name: str
    service_name: str
    level: AlertLevel
    message: str
    timestamp: datetime
    resolved: bool = False
    resolved_timestamp: Optional[datetime] = None


class DependencyMonitor:
    """依赖监控器"""
    
    def __init__(self):
        self._dependency_status: Dict[str, HealthStatus] = {}
        self._last_check_time: Dict[str, datetime] = {}
        self._check_interval = 60  # 60秒检查一次
    
    async def check_dependencies(self) -> Dict[str, HealthStatus]:
        """
        检查所有依赖项状态
        Check all dependencies status
        """
        current_time = datetime.now()
        results = {}
        
        # 获取所有依赖项
        dependencies = dependency_manager.get_all_dependencies()
        
        for dep_name, dep_info in dependencies.items():
            # 检查是否需要更新状态
            last_check = self._last_check_time.get(dep_name)
            if (last_check is None or 
                (current_time - last_check).total_seconds() > self._check_interval):
                
                try:
                    # 重新检查依赖项
                    updated_info = dependency_manager.check_dependency(dep_name)
                    
                    if updated_info and updated_info.available:
                        status = HealthStatus.HEALTHY
                    elif updated_info and updated_info.fallback_available:
                        status = HealthStatus.DEGRADED
                    else:
                        status = HealthStatus.UNHEALTHY
                    
                    self._dependency_status[dep_name] = status
                    self._last_check_time[dep_name] = current_time
                    
                    logger.debug(f"🔍 依赖检查: {dep_name} - {status.value}")
                    
                except Exception as e:
                    logger.error(f"❌ 依赖检查失败: {dep_name} - {e}")
                    self._dependency_status[dep_name] = HealthStatus.UNKNOWN
            
            results[dep_name] = self._dependency_status.get(dep_name, HealthStatus.UNKNOWN)
        
        return results
    
    def get_dependency_status(self, dependency_name: str) -> HealthStatus:
        """获取特定依赖项状态"""
        return self._dependency_status.get(dependency_name, HealthStatus.UNKNOWN)
    
    def get_unhealthy_dependencies(self) -> List[str]:
        """获取不健康的依赖项"""
        return [
            name for name, status in self._dependency_status.items()
            if status in [HealthStatus.UNHEALTHY, HealthStatus.UNKNOWN]
        ]


class AlertManager:
    """警报管理器"""
    
    def __init__(self):
        self._alert_rules: Dict[str, AlertRule] = {}
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._last_alert_time: Dict[str, datetime] = {}
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        
        # 设置默认警报规则
        self._setup_default_alert_rules()
    
    def _setup_default_alert_rules(self):
        """设置默认警报规则"""
        # 服务不健康警报
        self.add_alert_rule(AlertRule(
            name="service_unhealthy",
            condition=lambda result: result.status == HealthStatus.UNHEALTHY,
            level=AlertLevel.ERROR,
            message_template="服务 {service_name} 状态不健康: {error_message}",
            cooldown_seconds=300
        ))
        
        # 服务降级警报
        self.add_alert_rule(AlertRule(
            name="service_degraded",
            condition=lambda result: result.status == HealthStatus.DEGRADED,
            level=AlertLevel.WARNING,
            message_template="服务 {service_name} 状态降级",
            cooldown_seconds=600
        ))
        
        # 响应时间过长警报
        self.add_alert_rule(AlertRule(
            name="slow_response",
            condition=lambda result: result.response_time > 5.0,
            level=AlertLevel.WARNING,
            message_template="服务 {service_name} 响应时间过长: {response_time:.2f}秒",
            cooldown_seconds=300
        ))
        
        # 依赖项不可用警报
        self.add_alert_rule(AlertRule(
            name="dependency_unavailable",
            condition=lambda result: any(
                status == HealthStatus.UNHEALTHY 
                for status in result.dependencies_status.values()
            ),
            level=AlertLevel.ERROR,
            message_template="服务 {service_name} 存在不可用依赖项",
            cooldown_seconds=600
        ))
    
    def add_alert_rule(self, rule: AlertRule):
        """添加警报规则"""
        self._alert_rules[rule.name] = rule
        logger.info(f"📝 添加警报规则: {rule.name}")
    
    def remove_alert_rule(self, rule_name: str):
        """移除警报规则"""
        if rule_name in self._alert_rules:
            del self._alert_rules[rule_name]
            logger.info(f"🗑️ 移除警报规则: {rule_name}")
    
    def add_alert_callback(self, callback: Callable[[Alert], None]):
        """添加警报回调"""
        self._alert_callbacks.append(callback)
        logger.info("📝 添加警报回调")
    
    async def check_alerts(self, health_result: HealthCheckResult):
        """检查并触发警报"""
        current_time = datetime.now()
        
        for rule_name, rule in self._alert_rules.items():
            if not rule.enabled:
                continue
            
            try:
                # 检查规则条件
                if rule.condition(health_result):
                    alert_key = f"{rule_name}_{health_result.service_name}"
                    
                    # 检查冷却时间
                    last_alert_time = self._last_alert_time.get(alert_key)
                    if (last_alert_time and 
                        (current_time - last_alert_time).total_seconds() < rule.cooldown_seconds):
                        continue
                    
                    # 创建警报
                    alert = Alert(
                        rule_name=rule_name,
                        service_name=health_result.service_name,
                        level=rule.level,
                        message=rule.message_template.format(
                            service_name=health_result.service_name,
                            error_message=health_result.error_message or "未知错误",
                            response_time=health_result.response_time,
                            **health_result.details
                        ),
                        timestamp=current_time
                    )
                    
                    # 触发警报
                    await self._trigger_alert(alert)
                    
                    # 更新最后警报时间
                    self._last_alert_time[alert_key] = current_time
                
                else:
                    # 检查是否需要解决现有警报
                    alert_key = f"{rule_name}_{health_result.service_name}"
                    if alert_key in self._active_alerts:
                        await self._resolve_alert(alert_key)
                        
            except Exception as e:
                logger.error(f"❌ 警报规则检查失败: {rule_name} - {e}")
    
    async def _trigger_alert(self, alert: Alert):
        """触发警报"""
        alert_key = f"{alert.rule_name}_{alert.service_name}"
        self._active_alerts[alert_key] = alert
        self._alert_history.append(alert)
        
        # 记录警报日志
        log_level = "ERROR" if alert.level in [AlertLevel.ERROR, AlertLevel.CRITICAL] else "WARNING"
        log_structured_error(
            error_type="ServiceAlert",
            error_message=alert.message,
            error_code=alert.rule_name,
            context={
                "service_name": alert.service_name,
                "alert_level": alert.level.value,
                "timestamp": alert.timestamp.isoformat()
            },
            level=log_level
        )
        
        # 执行警报回调
        for callback in self._alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                logger.error(f"❌ 警报回调执行失败: {e}")
    
    async def _resolve_alert(self, alert_key: str):
        """解决警报"""
        if alert_key in self._active_alerts:
            alert = self._active_alerts[alert_key]
            alert.resolved = True
            alert.resolved_timestamp = datetime.now()
            
            del self._active_alerts[alert_key]
            
            logger.info(f"✅ 警报已解决: {alert.rule_name} - {alert.service_name}")
    
    def get_active_alerts(self) -> List[Alert]:
        """获取活跃警报"""
        return list(self._active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """获取警报历史"""
        return self._alert_history[-limit:]


class HealthMonitor:
    """
    服务健康监控器
    Service Health Monitor
    """
    
    def __init__(self):
        self._health_checks: Dict[str, Callable] = {}
        self._health_results: Dict[str, HealthCheckResult] = {}
        self._service_metrics: Dict[str, ServiceMetrics] = {}
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._dependency_monitor = DependencyMonitor()
        self._alert_manager = AlertManager()
        self._shutdown_event = asyncio.Event()
        self._system_start_time = datetime.now()
        
        # 注册系统资源监控
        self._setup_system_monitoring()
        
        logger.info("🚀 健康监控器初始化完成")
    
    def _setup_system_monitoring(self):
        """设置系统监控"""
        # 注册系统健康检查
        self.register_health_check("system", self._system_health_check)
        
        # 添加系统警报回调
        self._alert_manager.add_alert_callback(self._system_alert_callback)
    
    def register_health_check(self, service_name: str, health_check_func: Callable):
        """
        注册健康检查函数
        Register health check function
        """
        self._health_checks[service_name] = health_check_func
        
        # 初始化服务指标
        if service_name not in self._service_metrics:
            self._service_metrics[service_name] = ServiceMetrics(service_name=service_name)
        
        logger.info(f"📝 注册健康检查: {service_name}")
    
    def unregister_health_check(self, service_name: str):
        """取消注册健康检查"""
        if service_name in self._health_checks:
            del self._health_checks[service_name]
            
            # 停止监控任务
            if service_name in self._monitoring_tasks:
                self._monitoring_tasks[service_name].cancel()
                del self._monitoring_tasks[service_name]
            
            logger.info(f"🗑️ 取消注册健康检查: {service_name}")
    
    async def check_service_health(self, service_name: str) -> HealthCheckResult:
        """
        检查单个服务健康状态
        Check single service health
        """
        if service_name not in self._health_checks:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                response_time=0.0,
                timestamp=datetime.now(),
                error_message="未注册健康检查函数"
            )
        
        start_time = time.time()
        
        try:
            health_check_func = self._health_checks[service_name]
            
            # 执行健康检查
            if asyncio.iscoroutinefunction(health_check_func):
                health_data = await health_check_func()
            else:
                health_data = health_check_func()
            
            response_time = time.time() - start_time
            
            # 检查依赖项状态
            dependencies_status = await self._dependency_monitor.check_dependencies()
            
            # 解析健康检查结果
            if isinstance(health_data, dict):
                status = HealthStatus(health_data.get("status", "unknown"))
                details = health_data.get("details", {})
                error_message = health_data.get("error")
            elif isinstance(health_data, bool):
                status = HealthStatus.HEALTHY if health_data else HealthStatus.UNHEALTHY
                details = {}
                error_message = None if health_data else "健康检查返回False"
            else:
                status = HealthStatus.HEALTHY if health_data else HealthStatus.UNHEALTHY
                details = {"raw_result": str(health_data)}
                error_message = None
            
            result = HealthCheckResult(
                service_name=service_name,
                status=status,
                response_time=response_time,
                timestamp=datetime.now(),
                details=details,
                error_message=error_message,
                dependencies_status=dependencies_status
            )
            
            # 更新服务指标
            self._update_service_metrics(service_name, result)
            
            # 检查警报
            await self._alert_manager.check_alerts(result)
            
            # 保存结果
            self._health_results[service_name] = result
            
            return result
            
        except Exception as e:
            response_time = time.time() - start_time
            
            result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
            
            # 更新服务指标（错误）
            self._update_service_metrics(service_name, result, is_error=True)
            
            # 检查警报
            await self._alert_manager.check_alerts(result)
            
            # 保存结果
            self._health_results[service_name] = result
            
            logger.error(f"❌ 服务健康检查失败: {service_name} - {e}")
            
            return result
    
    async def check_all_services_health(self) -> Dict[str, HealthCheckResult]:
        """
        检查所有服务健康状态
        Check all services health
        """
        results = {}
        
        # 并发执行所有健康检查
        tasks = []
        service_names = []
        
        for service_name in self._health_checks:
            task = asyncio.create_task(self.check_service_health(service_name))
            tasks.append(task)
            service_names.append(service_name)
        
        # 等待所有任务完成
        completed_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        for i, result in enumerate(completed_results):
            service_name = service_names[i]
            
            if isinstance(result, Exception):
                logger.error(f"❌ 健康检查任务失败: {service_name} - {result}")
                results[service_name] = HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.UNHEALTHY,
                    response_time=0.0,
                    timestamp=datetime.now(),
                    error_message=str(result)
                )
            else:
                results[service_name] = result
        
        return results
    
    def _update_service_metrics(self, service_name: str, result: HealthCheckResult, is_error: bool = False):
        """更新服务指标"""
        if service_name not in self._service_metrics:
            self._service_metrics[service_name] = ServiceMetrics(service_name=service_name)
        
        metrics = self._service_metrics[service_name]
        metrics.request_count += 1
        metrics.last_request_time = datetime.now()
        
        if is_error:
            metrics.error_count += 1
        
        # 更新平均响应时间
        if metrics.request_count == 1:
            metrics.average_response_time = result.response_time
        else:
            metrics.average_response_time = (
                (metrics.average_response_time * (metrics.request_count - 1) + result.response_time) 
                / metrics.request_count
            )
        
        # 更新运行时间
        metrics.uptime = (datetime.now() - self._system_start_time).total_seconds()
    
    async def _system_health_check(self) -> Dict[str, Any]:
        """系统健康检查"""
        try:
            # 获取系统资源使用情况
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # 判断系统状态
            status = HealthStatus.HEALTHY
            
            if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
                status = HealthStatus.UNHEALTHY
            elif cpu_percent > 70 or memory.percent > 70 or disk.percent > 80:
                status = HealthStatus.DEGRADED
            
            return {
                "status": status.value,
                "details": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "disk_percent": disk.percent,
                    "memory_available": memory.available,
                    "disk_free": disk.free
                }
            }
            
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "error": str(e)
            }
    
    def _system_alert_callback(self, alert: Alert):
        """系统警报回调"""
        # 这里可以集成外部通知系统，如邮件、短信、Slack等
        logger.info(f"🚨 系统警报: {alert.message}")
    
    async def start_monitoring(self, interval: int = 30):
        """
        启动监控
        Start monitoring
        """
        logger.info(f"🚀 启动健康监控 (间隔: {interval}秒)")
        
        for service_name in self._health_checks:
            task = asyncio.create_task(
                self._monitoring_loop(service_name, interval)
            )
            self._monitoring_tasks[service_name] = task
    
    async def _monitoring_loop(self, service_name: str, interval: int):
        """监控循环"""
        while not self._shutdown_event.is_set():
            try:
                await self.check_service_health(service_name)
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 监控循环异常: {service_name} - {e}")
                await asyncio.sleep(interval)
    
    async def stop_monitoring(self):
        """
        停止监控
        Stop monitoring
        """
        logger.info("🛑 停止健康监控")
        
        # 设置关闭事件
        self._shutdown_event.set()
        
        # 取消所有监控任务
        for task in self._monitoring_tasks.values():
            task.cancel()
        
        # 等待任务完成
        if self._monitoring_tasks:
            await asyncio.gather(*self._monitoring_tasks.values(), return_exceptions=True)
        
        self._monitoring_tasks.clear()
    
    def get_service_health(self, service_name: str) -> Optional[HealthCheckResult]:
        """获取服务健康状态"""
        return self._health_results.get(service_name)
    
    def get_all_service_health(self) -> Dict[str, HealthCheckResult]:
        """获取所有服务健康状态"""
        return self._health_results.copy()
    
    def get_service_metrics(self, service_name: str) -> Optional[ServiceMetrics]:
        """获取服务指标"""
        return self._service_metrics.get(service_name)
    
    def get_all_service_metrics(self) -> Dict[str, ServiceMetrics]:
        """获取所有服务指标"""
        return self._service_metrics.copy()
    
    def get_health_summary(self) -> Dict[str, Any]:
        """
        获取健康状态摘要
        Get health status summary
        """
        total_services = len(self._health_checks)
        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0
        unknown_count = 0
        
        for result in self._health_results.values():
            if result.status == HealthStatus.HEALTHY:
                healthy_count += 1
            elif result.status == HealthStatus.DEGRADED:
                degraded_count += 1
            elif result.status == HealthStatus.UNHEALTHY:
                unhealthy_count += 1
            else:
                unknown_count += 1
        
        # 获取依赖项状态
        unhealthy_dependencies = self._dependency_monitor.get_unhealthy_dependencies()
        
        # 获取活跃警报
        active_alerts = self._alert_manager.get_active_alerts()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_services": total_services,
            "healthy_services": healthy_count,
            "degraded_services": degraded_count,
            "unhealthy_services": unhealthy_count,
            "unknown_services": unknown_count,
            "overall_status": self._calculate_overall_status(
                healthy_count, degraded_count, unhealthy_count, unknown_count
            ).value,
            "unhealthy_dependencies": unhealthy_dependencies,
            "active_alerts_count": len(active_alerts),
            "system_uptime": (datetime.now() - self._system_start_time).total_seconds()
        }
    
    def _calculate_overall_status(self, healthy: int, degraded: int, 
                                unhealthy: int, unknown: int) -> HealthStatus:
        """计算整体状态"""
        if unhealthy > 0:
            return HealthStatus.UNHEALTHY
        elif degraded > 0 or unknown > 0:
            return HealthStatus.DEGRADED
        elif healthy > 0:
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    def get_degradation_report(self) -> Dict[str, Any]:
        """
        获取降级状态报告
        Get degradation status report
        """
        degraded_services = []
        fallback_services = []
        
        for service_name, result in self._health_results.items():
            if result.status == HealthStatus.DEGRADED:
                degraded_services.append({
                    "service_name": service_name,
                    "error_message": result.error_message,
                    "response_time": result.response_time,
                    "timestamp": result.timestamp.isoformat()
                })
            
            # 检查是否使用了回退服务
            if "fallback_active" in result.details:
                fallback_services.append({
                    "service_name": service_name,
                    "fallback_type": result.details.get("fallback_type"),
                    "timestamp": result.timestamp.isoformat()
                })
        
        return {
            "timestamp": datetime.now().isoformat(),
            "degraded_services": degraded_services,
            "fallback_services": fallback_services,
            "unhealthy_dependencies": self._dependency_monitor.get_unhealthy_dependencies(),
            "active_alerts": [
                {
                    "rule_name": alert.rule_name,
                    "service_name": alert.service_name,
                    "level": alert.level.value,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat()
                }
                for alert in self._alert_manager.get_active_alerts()
            ]
        }
    
    @asynccontextmanager
    async def monitoring_context(self, interval: int = 30):
        """
        监控上下文管理器
        Monitoring context manager
        """
        try:
            await self.start_monitoring(interval)
            yield self
        finally:
            await self.stop_monitoring()
    
    # 健康检查端点方法
    def create_health_endpoint_handler(self):
        """创建健康检查端点处理器"""
        async def health_endpoint():
            """健康检查端点"""
            try:
                summary = self.get_health_summary()
                
                # 根据整体状态设置HTTP状态码
                if summary["overall_status"] == HealthStatus.HEALTHY.value:
                    status_code = 200
                elif summary["overall_status"] == HealthStatus.DEGRADED.value:
                    status_code = 200  # 降级状态仍返回200，但在响应中标明
                else:
                    status_code = 503  # 服务不可用
                
                return {
                    "status_code": status_code,
                    "data": summary
                }
                
            except Exception as e:
                logger.error(f"❌ 健康检查端点异常: {e}")
                return {
                    "status_code": 500,
                    "data": {
                        "overall_status": HealthStatus.UNHEALTHY.value,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                }
        
        return health_endpoint
    
    def create_metrics_endpoint_handler(self):
        """创建指标端点处理器"""
        async def metrics_endpoint():
            """指标端点"""
            try:
                metrics = {}
                for service_name, service_metrics in self._service_metrics.items():
                    metrics[service_name] = service_metrics.to_dict()
                
                return {
                    "status_code": 200,
                    "data": {
                        "timestamp": datetime.now().isoformat(),
                        "services": metrics
                    }
                }
                
            except Exception as e:
                logger.error(f"❌ 指标端点异常: {e}")
                return {
                    "status_code": 500,
                    "data": {
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                }
        
        return metrics_endpoint


# 全局健康监控器实例
health_monitor = HealthMonitor()