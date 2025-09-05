# -*- coding: utf-8 -*-
"""
自定义异常类
Custom exception classes
"""

from typing import Dict, Any, List
from datetime import datetime
from enum import Enum


class ErrorSeverity(Enum):
    """错误严重程度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryAction(Enum):
    """错误恢复建议枚举"""
    RETRY = "retry"
    FALLBACK = "fallback"
    RESTART_SERVICE = "restart_service"
    CHECK_CONFIG = "check_config"
    INSTALL_DEPENDENCY = "install_dependency"
    CONTACT_SUPPORT = "contact_support"


class TradingToolError(Exception):
    """
    交易工具基础异常类
    Base exception class for trading tool
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: str = None, 
        details: Dict[str, Any] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        recovery_actions: List[RecoveryAction] = None,
        context: Dict[str, Any] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.severity = severity
        self.recovery_actions = recovery_actions or []
        self.context = context or {}
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
            "severity": self.severity.value,
            "recovery_actions": [action.value for action in self.recovery_actions],
            "context": self.context,
            "timestamp": self.timestamp.isoformat()
        }
    
    def get_recovery_suggestions(self) -> List[str]:
        """获取错误恢复建议"""
        suggestions = []
        for action in self.recovery_actions:
            if action == RecoveryAction.RETRY:
                suggestions.append("请稍后重试操作")
            elif action == RecoveryAction.FALLBACK:
                suggestions.append("系统将使用备用方案")
            elif action == RecoveryAction.RESTART_SERVICE:
                suggestions.append("请重启相关服务")
            elif action == RecoveryAction.CHECK_CONFIG:
                suggestions.append("请检查配置文件")
            elif action == RecoveryAction.INSTALL_DEPENDENCY:
                suggestions.append("请安装缺失的依赖包")
            elif action == RecoveryAction.CONTACT_SUPPORT:
                suggestions.append("请联系技术支持")
        return suggestions


class BinanceAPIError(TradingToolError):
    """币安API异常"""
    
    def __init__(self, message: str, error_code: str = None, status_code: int = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class RateLimitError(BinanceAPIError):
    """API限流异常"""
    
    def __init__(self, message: str = "API rate limit exceeded"):
        super().__init__(message)


class DataNotFoundError(TradingToolError):
    """数据未找到异常"""


class IndicatorCalculationError(TradingToolError):
    """技术指标计算异常"""


class NotificationError(TradingToolError):
    """通知发送异常"""
    
    def __init__(self, message: str, channel: str = None):
        super().__init__(message)
        self.channel = channel


class ConfigurationError(TradingToolError):
    """配置错误异常"""


class DatabaseError(TradingToolError):
    """数据库异常"""


class ValidationError(TradingToolError):
    """数据验证异常"""


class MonitorError(TradingToolError):
    """监控服务异常"""


class SchedulerError(TradingToolError):
    """调度器异常"""


class MLModelError(TradingToolError):
    """机器学习模型异常"""
    
    def __init__(self, message: str, model_type: str = None):
        super().__init__(message)
        self.model_type = model_type


class ModelTrainingError(MLModelError):
    """模型训练异常"""


class PredictionError(MLModelError):
    """预测异常"""


class AnomalyDetectionError(MLModelError):
    """异常检测异常"""


class ServiceUnavailableError(TradingToolError):
    """服务不可用异常"""


class APIConnectionError(TradingToolError):
    """API连接异常"""
    
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.error_code = error_code


class UnsupportedExchangeError(TradingToolError):
    """不支持的交易所异常"""
    
    def __init__(self, message: str, exchange_name: str = None):
        super().__init__(message)
        self.exchange_name = exchange_name


class InternalServerError(TradingToolError):
    """内部服务器错误"""


class BacktestError(TradingToolError):
    """回测异常"""


class DependencyError(TradingToolError):
    """
    依赖相关异常
    Dependency related exception
    """
    
    def __init__(
        self, 
        message: str, 
        dependency_name: str = None, 
        details: Dict[str, Any] = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        recovery_actions: List[RecoveryAction] = None
    ):
        if recovery_actions is None:
            recovery_actions = [RecoveryAction.INSTALL_DEPENDENCY, RecoveryAction.CHECK_CONFIG]
        
        super().__init__(
            message=message,
            error_code="DEPENDENCY_ERROR",
            details=details or {},
            severity=severity,
            recovery_actions=recovery_actions,
            context={"dependency_name": dependency_name}
        )
        self.dependency_name = dependency_name


class MissingDependencyError(DependencyError):
    """
    缺失依赖异常
    Missing dependency exception
    """
    
    def __init__(
        self, 
        dependency_name: str, 
        install_command: str = None,
        required_version: str = None
    ):
        message = f"缺失依赖包: {dependency_name}"
        if required_version:
            message += f" (需要版本: {required_version})"
        
        details = {
            "dependency_name": dependency_name,
            "install_command": install_command,
            "required_version": required_version
        }
        
        super().__init__(
            message=message,
            dependency_name=dependency_name,
            details=details,
            severity=ErrorSeverity.HIGH,
            recovery_actions=[RecoveryAction.INSTALL_DEPENDENCY]
        )


class IncompatibleDependencyError(DependencyError):
    """
    依赖版本不兼容异常
    Incompatible dependency version exception
    """
    
    def __init__(
        self, 
        dependency_name: str, 
        current_version: str = None,
        required_version: str = None
    ):
        message = f"依赖版本不兼容: {dependency_name}"
        if current_version and required_version:
            message += f" (当前: {current_version}, 需要: {required_version})"
        
        details = {
            "dependency_name": dependency_name,
            "current_version": current_version,
            "required_version": required_version
        }
        
        super().__init__(
            message=message,
            dependency_name=dependency_name,
            details=details,
            severity=ErrorSeverity.MEDIUM,
            recovery_actions=[RecoveryAction.INSTALL_DEPENDENCY, RecoveryAction.CHECK_CONFIG]
        )


class DependencyImportError(DependencyError):
    """
    依赖导入异常
    Dependency import exception
    """
    
    def __init__(
        self, 
        dependency_name: str, 
        import_error: str = None,
        fallback_available: bool = False
    ):
        message = f"依赖导入失败: {dependency_name}"
        if import_error:
            message += f" - {import_error}"
        
        details = {
            "dependency_name": dependency_name,
            "import_error": import_error,
            "fallback_available": fallback_available
        }
        
        recovery_actions = [RecoveryAction.INSTALL_DEPENDENCY]
        if fallback_available:
            recovery_actions.append(RecoveryAction.FALLBACK)
        
        super().__init__(
            message=message,
            dependency_name=dependency_name,
            details=details,
            severity=ErrorSeverity.MEDIUM if fallback_available else ErrorSeverity.HIGH,
            recovery_actions=recovery_actions
        )


class ServiceInitializationError(TradingToolError):
    """
    服务初始化异常
    Service initialization exception
    """
    
    def __init__(
        self, 
        message: str, 
        service_name: str = None, 
        details: Dict[str, Any] = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        recovery_actions: List[RecoveryAction] = None
    ):
        if recovery_actions is None:
            recovery_actions = [RecoveryAction.RESTART_SERVICE, RecoveryAction.CHECK_CONFIG]
        
        super().__init__(
            message=message,
            error_code="SERVICE_INIT_ERROR",
            details=details or {},
            severity=severity,
            recovery_actions=recovery_actions,
            context={"service_name": service_name}
        )
        self.service_name = service_name


class ServiceDependencyError(ServiceInitializationError):
    """
    服务依赖异常
    Service dependency exception
    """
    
    def __init__(
        self, 
        service_name: str, 
        missing_dependencies: List[str] = None,
        failed_services: List[str] = None
    ):
        dependencies = missing_dependencies or []
        failed = failed_services or []
        
        message = f"服务 {service_name} 依赖不满足"
        if dependencies:
            message += f" - 缺失依赖: {', '.join(dependencies)}"
        if failed:
            message += f" - 失败服务: {', '.join(failed)}"
        
        details = {
            "service_name": service_name,
            "missing_dependencies": dependencies,
            "failed_services": failed
        }
        
        super().__init__(
            message=message,
            service_name=service_name,
            details=details,
            severity=ErrorSeverity.HIGH,
            recovery_actions=[
                RecoveryAction.INSTALL_DEPENDENCY,
                RecoveryAction.RESTART_SERVICE,
                RecoveryAction.CHECK_CONFIG
            ]
        )


class ServiceConfigurationError(ServiceInitializationError):
    """
    服务配置异常
    Service configuration exception
    """
    
    def __init__(
        self, 
        service_name: str, 
        config_key: str = None,
        config_value: Any = None,
        expected_type: str = None
    ):
        message = f"服务 {service_name} 配置错误"
        if config_key:
            message += f" - 配置项: {config_key}"
        
        details = {
            "service_name": service_name,
            "config_key": config_key,
            "config_value": str(config_value) if config_value is not None else None,
            "expected_type": expected_type
        }
        
        super().__init__(
            message=message,
            service_name=service_name,
            details=details,
            severity=ErrorSeverity.MEDIUM,
            recovery_actions=[RecoveryAction.CHECK_CONFIG]
        )


class ServiceTimeoutError(ServiceInitializationError):
    """
    服务初始化超时异常
    Service initialization timeout exception
    """
    
    def __init__(
        self, 
        service_name: str, 
        timeout_seconds: float = None
    ):
        message = f"服务 {service_name} 初始化超时"
        if timeout_seconds:
            message += f" ({timeout_seconds}秒)"
        
        details = {
            "service_name": service_name,
            "timeout_seconds": timeout_seconds
        }
        
        super().__init__(
            message=message,
            service_name=service_name,
            details=details,
            severity=ErrorSeverity.MEDIUM,
            recovery_actions=[RecoveryAction.RESTART_SERVICE, RecoveryAction.CHECK_CONFIG]
        )


class ServiceHealthCheckError(TradingToolError):
    """
    服务健康检查异常
    Service health check exception
    """
    
    def __init__(
        self, 
        service_name: str, 
        health_status: str = None,
        last_check: datetime = None
    ):
        message = f"服务 {service_name} 健康检查失败"
        if health_status:
            message += f" - 状态: {health_status}"
        
        details = {
            "service_name": service_name,
            "health_status": health_status,
            "last_check": last_check.isoformat() if last_check else None
        }
        
        super().__init__(
            message=message,
            error_code="SERVICE_HEALTH_ERROR",
            details=details,
            severity=ErrorSeverity.MEDIUM,
            recovery_actions=[RecoveryAction.RESTART_SERVICE],
            context={"service_name": service_name}
        )


class ErrorContext:
    """
    错误上下文管理器
    Error context manager
    """
    
    def __init__(self):
        self._context_stack: List[Dict[str, Any]] = []
    
    def push_context(self, **kwargs):
        """添加上下文信息"""
        self._context_stack.append(kwargs)
    
    def pop_context(self):
        """移除最新的上下文信息"""
        if self._context_stack:
            return self._context_stack.pop()
        return {}
    
    def get_current_context(self) -> Dict[str, Any]:
        """获取当前完整上下文"""
        context = {}
        for ctx in self._context_stack:
            context.update(ctx)
        return context
    
    def clear_context(self):
        """清空上下文"""
        self._context_stack.clear()


# 全局错误上下文实例
error_context = ErrorContext()


def with_error_context(**context_kwargs):
    """
    错误上下文装饰器
    Error context decorator
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            error_context.push_context(**context_kwargs)
            try:
                return func(*args, **kwargs)
            except TradingToolError as e:
                # 将当前上下文添加到异常中
                current_context = error_context.get_current_context()
                e.context.update(current_context)
                raise
            finally:
                error_context.pop_context()
        
        async def async_wrapper(*args, **kwargs):
            error_context.push_context(**context_kwargs)
            try:
                return await func(*args, **kwargs)
            except TradingToolError as e:
                # 将当前上下文添加到异常中
                current_context = error_context.get_current_context()
                e.context.update(current_context)
                raise
            finally:
                error_context.pop_context()
        
        import asyncio
        return async_wrapper if asyncio.iscoroutinefunction(func) else wrapper
    return decorator


def create_error_with_context(
    exception_class: type, 
    message: str, 
    **kwargs
) -> TradingToolError:
    """
    创建带上下文的异常
    Create exception with context
    """
    current_context = error_context.get_current_context()
    if 'context' in kwargs:
        kwargs['context'].update(current_context)
    else:
        kwargs['context'] = current_context
    
    return exception_class(message, **kwargs)


class ErrorRecoveryManager:
    """
    错误恢复管理器
    Error recovery manager
    """
    
    def __init__(self):
        self._recovery_handlers: Dict[type, callable] = {}
        self._fallback_handlers: Dict[type, callable] = {}
    
    def register_recovery_handler(self, exception_type: type, handler: callable):
        """注册错误恢复处理器"""
        self._recovery_handlers[exception_type] = handler
    
    def register_fallback_handler(self, exception_type: type, handler: callable):
        """注册回退处理器"""
        self._fallback_handlers[exception_type] = handler
    
    async def handle_error(self, error: TradingToolError, *args, **kwargs):
        """处理错误并尝试恢复"""
        error_type = type(error)
        
        # 尝试特定的恢复处理器
        if error_type in self._recovery_handlers:
            try:
                return await self._recovery_handlers[error_type](error, *args, **kwargs)
            except Exception:
                pass  # 恢复失败，尝试回退
        
        # 尝试回退处理器
        if error_type in self._fallback_handlers:
            try:
                return await self._fallback_handlers[error_type](error, *args, **kwargs)
            except Exception:
                pass  # 回退也失败
        
        # 如果都失败了，重新抛出原始异常
        raise error
    
    def get_recovery_suggestions(self, error: TradingToolError) -> List[str]:
        """获取错误恢复建议"""
        suggestions = error.get_recovery_suggestions()
        
        # 添加基于错误类型的额外建议
        if isinstance(error, MissingDependencyError):
            if error.details.get("install_command"):
                suggestions.append(f"运行命令: {error.details['install_command']}")
        
        elif isinstance(error, ServiceConfigurationError):
            config_key = error.details.get("config_key")
            if config_key:
                suggestions.append(f"检查配置项: {config_key}")
        
        elif isinstance(error, ServiceTimeoutError):
            suggestions.append("增加服务初始化超时时间")
            suggestions.append("检查网络连接和系统资源")
        
        return suggestions


# 全局错误恢复管理器实例
error_recovery_manager = ErrorRecoveryManager()