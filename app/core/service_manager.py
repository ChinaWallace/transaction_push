# -*- coding: utf-8 -*-
"""
服务管理器
Service Manager for handling service lifecycle and dependencies
"""

import asyncio
import inspect
from typing import Dict, Any, Optional, Type, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.utils.exceptions import ServiceInitializationError
from app.utils.dependency_manager import dependency_manager

logger = get_logger(__name__)


class ServiceStatus(Enum):
    """服务状态枚举"""
    NOT_INITIALIZED = "not_initialized"
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ServiceHealth:
    """服务健康状态数据类"""
    name: str
    status: ServiceStatus
    last_check: datetime
    error_count: int = 0
    dependencies: List[str] = field(default_factory=list)
    fallback_available: bool = False
    error_message: Optional[str] = None
    initialization_time: Optional[float] = None
    last_error: Optional[Exception] = None


@dataclass
class ServiceConfig:
    """服务配置数据类"""
    name: str
    service_class: Type
    dependencies: List[str] = field(default_factory=list)
    optional_dependencies: List[str] = field(default_factory=list)
    required: bool = True
    auto_restart: bool = True
    health_check_interval: int = 60  # 秒
    max_restart_attempts: int = 3
    initialization_timeout: int = 30  # 秒
    fallback_service: Optional[Type] = None


class ServiceManager:
    """
    服务管理器
    Service Manager for handling service registration, initialization, and lifecycle
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._service_configs: Dict[str, ServiceConfig] = {}
        self._service_health: Dict[str, ServiceHealth] = {}
        self._initialization_order: List[str] = []
        self._health_check_tasks: Dict[str, asyncio.Task] = {}
        self._restart_attempts: Dict[str, int] = {}
        self._shutdown_event = asyncio.Event()
        
        logger.info("🚀 服务管理器初始化完成")
    
    def register_service(self, config: ServiceConfig) -> None:
        """
        注册服务
        Register a service
        
        Args:
            config: 服务配置 / Service configuration
        """
        if config.name in self._service_configs:
            logger.warning(f"⚠️ 服务已存在，将覆盖: {config.name}")
        
        self._service_configs[config.name] = config
        self._service_health[config.name] = ServiceHealth(
            name=config.name,
            status=ServiceStatus.NOT_INITIALIZED,
            last_check=datetime.now(),
            dependencies=config.dependencies + config.optional_dependencies
        )
        
        logger.info(f"📝 服务注册成功: {config.name}")
    
    def register_service_simple(self, name: str, service_class: Type, 
                              dependencies: List[str] = None,
                              optional_dependencies: List[str] = None,
                              required: bool = True) -> None:
        """
        简化的服务注册方法
        Simplified service registration method
        
        Args:
            name: 服务名称 / Service name
            service_class: 服务类 / Service class
            dependencies: 必需依赖项 / Required dependencies
            optional_dependencies: 可选依赖项 / Optional dependencies
            required: 是否为必需服务 / Whether service is required
        """
        config = ServiceConfig(
            name=name,
            service_class=service_class,
            dependencies=dependencies or [],
            optional_dependencies=optional_dependencies or [],
            required=required
        )
        self.register_service(config)
    
    async def initialize_service(self, name: str) -> bool:
        """
        初始化单个服务
        Initialize a single service
        
        Args:
            name: 服务名称 / Service name
            
        Returns:
            bool: 初始化是否成功 / Whether initialization was successful
        """
        if name not in self._service_configs:
            logger.error(f"❌ 服务未注册: {name}")
            return False
        
        config = self._service_configs[name]
        health = self._service_health[name]
        
        if health.status == ServiceStatus.HEALTHY:
            logger.debug(f"🔍 服务已初始化: {name}")
            return True
        
        health.status = ServiceStatus.INITIALIZING
        health.last_check = datetime.now()
        
        try:
            logger.info(f"🔧 正在初始化服务: {name}")
            start_time = datetime.now()
            
            # 检查依赖项
            if not await self._check_service_dependencies(config):
                if config.required:
                    raise ServiceInitializationError(
                        f"服务 {name} 的必需依赖项不可用",
                        service_name=name
                    )
                else:
                    logger.warning(f"⚠️ 可选服务 {name} 的依赖项不可用，跳过初始化")
                    health.status = ServiceStatus.FAILED
                    return False
            
            # 初始化服务实例
            service_instance = await self._create_service_instance(config)
            
            if service_instance is None:
                raise ServiceInitializationError(
                    f"服务 {name} 实例创建失败",
                    service_name=name
                )
            
            # 执行服务初始化
            await self._initialize_service_instance(service_instance, config)
            
            # 保存服务实例
            self._services[name] = service_instance
            
            # 更新健康状态
            initialization_time = (datetime.now() - start_time).total_seconds()
            health.status = ServiceStatus.HEALTHY
            health.error_count = 0
            health.initialization_time = initialization_time
            health.error_message = None
            health.last_error = None
            
            # 重置重启计数
            self._restart_attempts[name] = 0
            
            # 启动健康检查
            await self._start_health_check(name)
            
            logger.info(f"✅ 服务初始化成功: {name} ({initialization_time:.2f}秒)")
            return True
            
        except Exception as e:
            health.status = ServiceStatus.FAILED
            health.error_count += 1
            health.error_message = str(e)
            health.last_error = e
            
            logger.error(f"❌ 服务初始化失败: {name} - {e}")
            
            # 尝试使用回退服务
            if config.fallback_service and await self._try_fallback_service(config):
                health.status = ServiceStatus.DEGRADED
                health.fallback_available = True
                logger.warning(f"⚠️ 服务 {name} 使用回退模式")
                return True
            
            return False
    
    async def _check_service_dependencies(self, config: ServiceConfig) -> bool:
        """检查服务依赖项"""
        all_available = True
        
        # 检查必需依赖项
        for dep_name in config.dependencies:
            dep_info = dependency_manager.get_dependency_status(dep_name)
            if not dep_info or not dep_info.available:
                logger.error(f"❌ 必需依赖项不可用: {dep_name}")
                all_available = False
        
        # 检查可选依赖项（仅记录警告）
        for dep_name in config.optional_dependencies:
            dep_info = dependency_manager.get_dependency_status(dep_name)
            if not dep_info or not dep_info.available:
                logger.warning(f"⚠️ 可选依赖项不可用: {dep_name}")
        
        return all_available
    
    async def _create_service_instance(self, config: ServiceConfig) -> Optional[Any]:
        """创建服务实例"""
        try:
            # 检查是否为异步初始化
            if inspect.iscoroutinefunction(config.service_class.__init__):
                # 异步初始化
                instance = await asyncio.wait_for(
                    config.service_class(),
                    timeout=config.initialization_timeout
                )
            else:
                # 同步初始化
                instance = config.service_class()
            
            return instance
            
        except asyncio.TimeoutError:
            logger.error(f"❌ 服务创建超时: {config.name}")
            return None
        except Exception as e:
            logger.error(f"❌ 服务创建失败: {config.name} - {e}")
            return None
    
    async def _initialize_service_instance(self, instance: Any, config: ServiceConfig) -> None:
        """初始化服务实例"""
        # 检查是否有初始化方法
        init_methods = ['initialize', 'init', 'start', 'setup']
        
        for method_name in init_methods:
            if hasattr(instance, method_name):
                method = getattr(instance, method_name)
                
                if inspect.iscoroutinefunction(method):
                    await asyncio.wait_for(
                        method(),
                        timeout=config.initialization_timeout
                    )
                else:
                    method()
                
                logger.debug(f"🔍 执行初始化方法: {config.name}.{method_name}")
                break
    
    async def _try_fallback_service(self, config: ServiceConfig) -> bool:
        """尝试使用回退服务"""
        if not config.fallback_service:
            return False
        
        try:
            logger.info(f"🔄 尝试回退服务: {config.name}")
            
            fallback_instance = await self._create_service_instance(
                ServiceConfig(
                    name=f"{config.name}_fallback",
                    service_class=config.fallback_service
                )
            )
            
            if fallback_instance:
                self._services[config.name] = fallback_instance
                return True
                
        except Exception as e:
            logger.error(f"❌ 回退服务失败: {config.name} - {e}")
        
        return False
    
    async def initialize_all_services(self) -> Dict[str, bool]:
        """
        初始化所有服务
        Initialize all services
        
        Returns:
            Dict[str, bool]: 各服务初始化结果 / Initialization results for each service
        """
        logger.info("🚀 开始初始化所有服务...")
        
        # 计算初始化顺序
        self._calculate_initialization_order()
        
        results = {}
        
        for service_name in self._initialization_order:
            try:
                success = await self.initialize_service(service_name)
                results[service_name] = success
                
                if not success:
                    config = self._service_configs[service_name]
                    if config.required:
                        logger.error(f"❌ 必需服务初始化失败: {service_name}")
                    else:
                        logger.warning(f"⚠️ 可选服务初始化失败: {service_name}")
                
            except Exception as e:
                logger.error(f"❌ 服务初始化异常: {service_name} - {e}")
                results[service_name] = False
        
        # 统计结果
        successful = sum(1 for success in results.values() if success)
        total = len(results)
        
        logger.info(f"📊 服务初始化完成: {successful}/{total} 成功")
        
        return results
    
    def _calculate_initialization_order(self) -> None:
        """计算服务初始化顺序"""
        # 简单的拓扑排序
        visited = set()
        temp_visited = set()
        order = []
        
        def visit(service_name: str):
            if service_name in temp_visited:
                logger.warning(f"⚠️ 检测到循环依赖: {service_name}")
                return
            
            if service_name in visited:
                return
            
            temp_visited.add(service_name)
            
            if service_name in self._service_configs:
                config = self._service_configs[service_name]
                for dep in config.dependencies:
                    if dep in self._service_configs:
                        visit(dep)
            
            temp_visited.remove(service_name)
            visited.add(service_name)
            order.append(service_name)
        
        for service_name in self._service_configs:
            visit(service_name)
        
        self._initialization_order = order
        logger.debug(f"🔍 服务初始化顺序: {order}")
    
    def get_service(self, name: str) -> Optional[Any]:
        """
        获取服务实例
        Get service instance
        
        Args:
            name: 服务名称 / Service name
            
        Returns:
            Optional[Any]: 服务实例 / Service instance
        """
        return self._services.get(name)
    
    def get_service_health(self, name: str) -> Optional[ServiceHealth]:
        """
        获取服务健康状态
        Get service health status
        
        Args:
            name: 服务名称 / Service name
            
        Returns:
            Optional[ServiceHealth]: 服务健康状态 / Service health status
        """
        return self._service_health.get(name)
    
    def get_all_service_health(self) -> Dict[str, ServiceHealth]:
        """
        获取所有服务健康状态
        Get all service health statuses
        
        Returns:
            Dict[str, ServiceHealth]: 所有服务健康状态 / All service health statuses
        """
        return self._service_health.copy()
    
    async def health_check(self, service_name: str = None) -> Dict[str, bool]:
        """
        执行健康检查
        Perform health check
        
        Args:
            service_name: 特定服务名称，None表示检查所有服务 / Specific service name, None for all
            
        Returns:
            Dict[str, bool]: 健康检查结果 / Health check results
        """
        results = {}
        
        services_to_check = [service_name] if service_name else list(self._services.keys())
        
        for name in services_to_check:
            if name not in self._services:
                results[name] = False
                continue
            
            try:
                service = self._services[name]
                health = self._service_health[name]
                
                # 检查服务是否有健康检查方法
                if hasattr(service, 'health_check'):
                    if inspect.iscoroutinefunction(service.health_check):
                        is_healthy = await service.health_check()
                    else:
                        is_healthy = service.health_check()
                else:
                    # 默认认为服务健康（如果能获取到实例）
                    is_healthy = True
                
                results[name] = is_healthy
                
                # 更新健康状态
                if is_healthy:
                    if health.status == ServiceStatus.FAILED:
                        health.status = ServiceStatus.HEALTHY
                        health.error_count = 0
                        logger.info(f"✅ 服务恢复健康: {name}")
                else:
                    health.status = ServiceStatus.DEGRADED
                    health.error_count += 1
                    logger.warning(f"⚠️ 服务健康检查失败: {name}")
                
                health.last_check = datetime.now()
                
            except Exception as e:
                results[name] = False
                health = self._service_health[name]
                health.status = ServiceStatus.FAILED
                health.error_count += 1
                health.last_error = e
                health.last_check = datetime.now()
                
                logger.error(f"❌ 服务健康检查异常: {name} - {e}")
        
        return results
    
    async def _start_health_check(self, service_name: str) -> None:
        """启动服务健康检查任务"""
        if service_name in self._health_check_tasks:
            self._health_check_tasks[service_name].cancel()
        
        config = self._service_configs[service_name]
        
        async def health_check_loop():
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.sleep(config.health_check_interval)
                    await self.health_check(service_name)
                    
                    # 检查是否需要重启服务
                    health = self._service_health[service_name]
                    if (health.status == ServiceStatus.FAILED and 
                        config.auto_restart and 
                        self._restart_attempts.get(service_name, 0) < config.max_restart_attempts):
                        
                        await self._restart_service(service_name)
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"❌ 健康检查任务异常: {service_name} - {e}")
        
        task = asyncio.create_task(health_check_loop())
        self._health_check_tasks[service_name] = task
    
    async def _restart_service(self, service_name: str) -> bool:
        """重启服务"""
        self._restart_attempts[service_name] = self._restart_attempts.get(service_name, 0) + 1
        attempt = self._restart_attempts[service_name]
        
        logger.info(f"🔄 尝试重启服务: {service_name} (第{attempt}次)")
        
        try:
            # 停止服务
            await self.stop_service(service_name)
            
            # 等待一段时间
            await asyncio.sleep(2)
            
            # 重新初始化
            success = await self.initialize_service(service_name)
            
            if success:
                logger.info(f"✅ 服务重启成功: {service_name}")
                return True
            else:
                logger.error(f"❌ 服务重启失败: {service_name}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 服务重启异常: {service_name} - {e}")
            return False
    
    async def stop_service(self, service_name: str) -> bool:
        """
        停止服务
        Stop service
        
        Args:
            service_name: 服务名称 / Service name
            
        Returns:
            bool: 停止是否成功 / Whether stop was successful
        """
        if service_name not in self._services:
            logger.warning(f"⚠️ 服务不存在: {service_name}")
            return False
        
        try:
            service = self._services[service_name]
            
            # 停止健康检查任务
            if service_name in self._health_check_tasks:
                self._health_check_tasks[service_name].cancel()
                del self._health_check_tasks[service_name]
            
            # 检查服务是否有停止方法
            stop_methods = ['stop', 'shutdown', 'close', 'cleanup']
            
            for method_name in stop_methods:
                if hasattr(service, method_name):
                    method = getattr(service, method_name)
                    
                    if inspect.iscoroutinefunction(method):
                        await method()
                    else:
                        method()
                    
                    logger.debug(f"🔍 执行停止方法: {service_name}.{method_name}")
                    break
            
            # 移除服务实例
            del self._services[service_name]
            
            # 更新健康状态
            health = self._service_health[service_name]
            health.status = ServiceStatus.STOPPED
            health.last_check = datetime.now()
            
            logger.info(f"🛑 服务停止成功: {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 服务停止失败: {service_name} - {e}")
            return False
    
    async def stop_all_services(self) -> Dict[str, bool]:
        """
        停止所有服务
        Stop all services
        
        Returns:
            Dict[str, bool]: 各服务停止结果 / Stop results for each service
        """
        logger.info("🛑 开始停止所有服务...")
        
        # 设置关闭事件
        self._shutdown_event.set()
        
        results = {}
        
        # 按相反顺序停止服务
        for service_name in reversed(self._initialization_order):
            if service_name in self._services:
                results[service_name] = await self.stop_service(service_name)
        
        # 等待所有健康检查任务完成
        if self._health_check_tasks:
            await asyncio.gather(*self._health_check_tasks.values(), return_exceptions=True)
            self._health_check_tasks.clear()
        
        successful = sum(1 for success in results.values() if success)
        total = len(results)
        
        logger.info(f"📊 服务停止完成: {successful}/{total} 成功")
        
        return results
    
    @asynccontextmanager
    async def service_lifecycle(self):
        """
        服务生命周期上下文管理器
        Service lifecycle context manager
        """
        try:
            # 初始化所有服务
            await self.initialize_all_services()
            yield self
        finally:
            # 停止所有服务
            await self.stop_all_services()
    
    def get_service_statistics(self) -> Dict[str, Any]:
        """
        获取服务统计信息
        Get service statistics
        
        Returns:
            Dict[str, Any]: 服务统计信息 / Service statistics
        """
        stats = {
            "total_services": len(self._service_configs),
            "running_services": len(self._services),
            "healthy_services": 0,
            "degraded_services": 0,
            "failed_services": 0,
            "services": {}
        }
        
        for name, health in self._service_health.items():
            service_stats = {
                "status": health.status.value,
                "error_count": health.error_count,
                "last_check": health.last_check.isoformat(),
                "initialization_time": health.initialization_time,
                "fallback_available": health.fallback_available
            }
            
            stats["services"][name] = service_stats
            
            if health.status == ServiceStatus.HEALTHY:
                stats["healthy_services"] += 1
            elif health.status == ServiceStatus.DEGRADED:
                stats["degraded_services"] += 1
            elif health.status == ServiceStatus.FAILED:
                stats["failed_services"] += 1
        
        return stats


# 全局服务管理器实例
service_manager = ServiceManager()