# -*- coding: utf-8 -*-
"""
集成错误恢复系统
Integrated Error Recovery System
"""

import asyncio
from typing import Dict, Any
from datetime import datetime

from app.core.logging import get_logger, log_service_operation
from app.core.service_manager import service_manager, ServiceStatus
from app.core.error_recovery_manager import error_recovery_manager, CircuitBreakerConfig
from app.core.health_monitor import health_monitor, HealthStatus
from app.utils.exceptions import ServiceInitializationError, ServiceHealthCheckError

logger = get_logger(__name__)


class IntegratedRecoverySystem:
    """
    集成错误恢复系统
    Integrated Error Recovery System that combines service management, error recovery, and health monitoring
    """
    
    def __init__(self):
        self._initialized = False
        self._recovery_enabled = True
        
        logger.info("🚀 集成错误恢复系统初始化")
    
    async def initialize(self):
        """
        初始化集成系统
        Initialize integrated system
        """
        if self._initialized:
            logger.warning("⚠️ 集成错误恢复系统已初始化")
            return
        
        try:
            # 设置服务管理器与错误恢复的集成
            await self._setup_service_error_integration()
            
            # 设置健康监控与服务管理的集成
            await self._setup_health_service_integration()
            
            # 设置错误恢复与健康监控的集成
            await self._setup_recovery_health_integration()
            
            # 注册默认的断路器
            self._setup_default_circuit_breakers()
            
            # 注册服务恢复回调
            self._setup_service_recovery_callbacks()
            
            self._initialized = True
            logger.info("✅ 集成错误恢复系统初始化完成")
            
        except Exception as e:
            logger.error(f"❌ 集成错误恢复系统初始化失败: {e}")
            raise
    
    async def _setup_service_error_integration(self):
        """设置服务管理器与错误恢复的集成"""
        
        # 为服务初始化失败注册恢复处理器
        async def service_init_recovery_handler(error: ServiceInitializationError, context: Dict[str, Any]):
            """服务初始化恢复处理器"""
            service_name = getattr(error, 'service_name', None)
            if not service_name:
                return None
            
            logger.info(f"🔧 尝试恢复服务初始化: {service_name}")
            
            # 等待一段时间后重试
            await asyncio.sleep(2)
            
            # 尝试重新初始化服务
            success = await service_manager.initialize_service(service_name)
            if success:
                logger.info(f"✅ 服务恢复成功: {service_name}")
                return {"recovered": True, "service_name": service_name}
            
            return None
        
        error_recovery_manager.register_recovery_handler(
            ServiceInitializationError, 
            service_init_recovery_handler
        )
        
        logger.info("📝 服务管理器错误恢复集成完成")
    
    async def _setup_health_service_integration(self):
        """设置健康监控与服务管理的集成"""
        
        # 为所有已注册的服务注册健康检查
        for service_name in service_manager._service_configs.keys():
            await self._register_service_health_check(service_name)
        
        # 注册系统级健康检查
        health_monitor.register_health_check("service_manager", self._service_manager_health_check)
        
        logger.info("📝 健康监控与服务管理集成完成")
    
    async def _register_service_health_check(self, service_name: str):
        """为服务注册健康检查"""
        
        async def service_health_check():
            """服务健康检查函数"""
            try:
                # 获取服务实例
                service = service_manager.get_service(service_name)
                if not service:
                    return {
                        "status": HealthStatus.UNHEALTHY.value,
                        "error": "服务实例不存在"
                    }
                
                # 获取服务健康状态
                health = service_manager.get_service_health(service_name)
                if not health:
                    return {
                        "status": HealthStatus.UNKNOWN.value,
                        "error": "无法获取服务健康状态"
                    }
                
                # 转换服务状态到健康状态
                if health.status == ServiceStatus.HEALTHY:
                    health_status = HealthStatus.HEALTHY
                elif health.status == ServiceStatus.DEGRADED:
                    health_status = HealthStatus.DEGRADED
                elif health.status in [ServiceStatus.FAILED, ServiceStatus.STOPPED]:
                    health_status = HealthStatus.UNHEALTHY
                else:
                    health_status = HealthStatus.UNKNOWN
                
                # 检查服务是否有自定义健康检查方法
                if hasattr(service, 'health_check'):
                    try:
                        if asyncio.iscoroutinefunction(service.health_check):
                            custom_result = await service.health_check()
                        else:
                            custom_result = service.health_check()
                        
                        # 如果自定义检查失败，降级状态
                        if not custom_result:
                            health_status = HealthStatus.DEGRADED
                            
                    except Exception as e:
                        logger.warning(f"⚠️ 服务自定义健康检查失败: {service_name} - {e}")
                        health_status = HealthStatus.DEGRADED
                
                return {
                    "status": health_status.value,
                    "details": {
                        "service_status": health.status.value,
                        "error_count": health.error_count,
                        "last_check": health.last_check.isoformat(),
                        "fallback_available": health.fallback_available,
                        "initialization_time": health.initialization_time
                    },
                    "error": health.error_message
                }
                
            except Exception as e:
                return {
                    "status": HealthStatus.UNHEALTHY.value,
                    "error": str(e)
                }
        
        health_monitor.register_health_check(service_name, service_health_check)
    
    async def _service_manager_health_check(self):
        """服务管理器健康检查"""
        try:
            stats = service_manager.get_service_statistics()
            
            total_services = stats["total_services"]
            running_services = stats["running_services"]
            healthy_services = stats["healthy_services"]
            failed_services = stats["failed_services"]
            
            # 计算健康状态
            if failed_services == 0 and healthy_services == total_services:
                status = HealthStatus.HEALTHY
            elif failed_services > 0 and healthy_services > 0:
                status = HealthStatus.DEGRADED
            elif failed_services > 0:
                status = HealthStatus.UNHEALTHY
            else:
                status = HealthStatus.UNKNOWN
            
            return {
                "status": status.value,
                "details": {
                    "total_services": total_services,
                    "running_services": running_services,
                    "healthy_services": healthy_services,
                    "failed_services": failed_services
                }
            }
            
        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "error": str(e)
            }
    
    async def _setup_recovery_health_integration(self):
        """设置错误恢复与健康监控的集成"""
        
        # 注册健康检查失败的恢复处理器
        async def health_check_recovery_handler(error: ServiceHealthCheckError, context: Dict[str, Any]):
            """健康检查失败恢复处理器"""
            service_name = getattr(error, 'service_name', context.get('service_name'))
            if not service_name:
                return None
            
            logger.info(f"🔧 尝试恢复健康检查失败的服务: {service_name}")
            
            # 尝试重启服务
            try:
                await service_manager.stop_service(service_name)
                await asyncio.sleep(1)
                success = await service_manager.initialize_service(service_name)
                
                if success:
                    logger.info(f"✅ 服务健康检查恢复成功: {service_name}")
                    return {"recovered": True, "service_name": service_name}
                
            except Exception as e:
                logger.error(f"❌ 服务健康检查恢复失败: {service_name} - {e}")
            
            return None
        
        error_recovery_manager.register_recovery_handler(
            ServiceHealthCheckError,
            health_check_recovery_handler
        )
        
        logger.info("📝 错误恢复与健康监控集成完成")
    
    def _setup_default_circuit_breakers(self):
        """设置默认断路器"""
        
        # API服务断路器
        error_recovery_manager.register_circuit_breaker(
            "api_services",
            CircuitBreakerConfig(
                failure_threshold=5,
                recovery_timeout=60.0,
                success_threshold=2
            )
        )
        
        # 数据库服务断路器
        error_recovery_manager.register_circuit_breaker(
            "database_services",
            CircuitBreakerConfig(
                failure_threshold=3,
                recovery_timeout=30.0,
                success_threshold=1
            )
        )
        
        # 外部API断路器
        error_recovery_manager.register_circuit_breaker(
            "external_apis",
            CircuitBreakerConfig(
                failure_threshold=10,
                recovery_timeout=120.0,
                success_threshold=3
            )
        )
        
        logger.info("📝 默认断路器设置完成")
    
    def _setup_service_recovery_callbacks(self):
        """设置服务恢复回调"""
        
        async def service_recovery_callback(service_name: str, recovery_info: Dict[str, Any]):
            """服务恢复回调"""
            logger.info(f"📢 服务恢复通知: {service_name}")
            
            # 记录服务恢复日志
            log_service_operation(
                service_name=service_name,
                operation="recovery",
                status="completed",
                details=recovery_info
            )
            
            # 重新注册健康检查（如果需要）
            if service_name not in health_monitor._health_checks:
                await self._register_service_health_check(service_name)
        
        # 为所有服务注册恢复回调
        for service_name in service_manager._service_configs.keys():
            error_recovery_manager.register_service_recovery_callback(
                service_name, 
                service_recovery_callback
            )
        
        logger.info("📝 服务恢复回调设置完成")
    
    async def start_monitoring(self, interval: int = 30):
        """
        启动集成监控
        Start integrated monitoring
        """
        if not self._initialized:
            await self.initialize()
        
        logger.info("🚀 启动集成监控系统")
        
        # 启动健康监控
        await health_monitor.start_monitoring(interval)
        
        logger.info("✅ 集成监控系统启动完成")
    
    async def stop_monitoring(self):
        """
        停止集成监控
        Stop integrated monitoring
        """
        logger.info("🛑 停止集成监控系统")
        
        # 停止健康监控
        await health_monitor.stop_monitoring()
        
        logger.info("✅ 集成监控系统停止完成")
    
    def enable_recovery(self):
        """启用错误恢复"""
        self._recovery_enabled = True
        logger.info("✅ 错误恢复已启用")
    
    def disable_recovery(self):
        """禁用错误恢复"""
        self._recovery_enabled = False
        logger.warning("⚠️ 错误恢复已禁用")
    
    async def execute_with_full_recovery(self, func, operation: str = None, 
                                       context: Dict[str, Any] = None):
        """
        执行带完整恢复机制的操作
        Execute operation with full recovery mechanism
        """
        if not self._recovery_enabled:
            return await func()
        
        context = context or {}
        
        # 使用错误恢复上下文
        async with error_recovery_manager.error_recovery_context(operation, context):
            return await func()
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        获取系统状态
        Get system status
        """
        # 获取健康监控摘要
        health_summary = health_monitor.get_health_summary()
        
        # 获取服务管理器统计
        service_stats = service_manager.get_service_statistics()
        
        # 获取错误恢复统计
        recovery_stats = error_recovery_manager.get_error_statistics()
        
        # 获取降级报告
        degradation_report = health_monitor.get_degradation_report()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "recovery_enabled": self._recovery_enabled,
            "health_summary": health_summary,
            "service_statistics": service_stats,
            "recovery_statistics": recovery_stats,
            "degradation_report": degradation_report,
            "system_status": "operational" if health_summary["overall_status"] == "healthy" else "degraded"
        }
    
    def create_status_endpoint_handler(self):
        """创建状态端点处理器"""
        async def status_endpoint():
            """系统状态端点"""
            try:
                status = self.get_system_status()
                
                # 根据系统状态设置HTTP状态码
                if status["system_status"] == "operational":
                    status_code = 200
                else:
                    status_code = 200  # 降级状态仍返回200，但在响应中标明
                
                return {
                    "status_code": status_code,
                    "data": status
                }
                
            except Exception as e:
                logger.error(f"❌ 状态端点异常: {e}")
                return {
                    "status_code": 500,
                    "data": {
                        "system_status": "error",
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                }
        
        return status_endpoint


# 全局集成错误恢复系统实例
integrated_recovery_system = IntegratedRecoverySystem()