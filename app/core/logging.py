# -*- coding: utf-8 -*-
"""
日志配置管理
Logging configuration management
"""

import sys
import os
import time
import asyncio
from functools import wraps
from loguru import logger
from typing import Dict, Any, Optional, List
import json
from datetime import datetime
from enum import Enum

from app.core.config import get_settings

settings = get_settings()


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(Enum):
    """日志分类枚举"""
    GENERAL = "general"
    TRADING = "trading"
    MONITOR = "monitor"
    DEPENDENCY = "dependency"
    SERVICE = "service"
    PERFORMANCE = "performance"
    API = "api"
    ERROR = "error"


class StructuredLogFormatter:
    """结构化日志格式化器"""
    
    @staticmethod
    def format_dependency_log(
        operation: str,
        dependency_name: str,
        status: str,
        details: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """格式化依赖相关日志"""
        return {
            "category": LogCategory.DEPENDENCY.value,
            "operation": operation,
            "dependency_name": dependency_name,
            "status": status,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_service_log(
        service_name: str,
        operation: str,
        status: str,
        duration: Optional[float] = None,
        details: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """格式化服务相关日志"""
        log_data = {
            "category": LogCategory.SERVICE.value,
            "service_name": service_name,
            "operation": operation,
            "status": status,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        
        if duration is not None:
            log_data["duration_seconds"] = duration
        
        return log_data
    
    @staticmethod
    def format_performance_log(
        operation: str,
        duration: float,
        resource_usage: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """格式化性能日志"""
        return {
            "category": LogCategory.PERFORMANCE.value,
            "operation": operation,
            "duration_seconds": duration,
            "resource_usage": resource_usage or {},
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_error_log(
        error_type: str,
        error_message: str,
        error_code: Optional[str] = None,
        context: Dict[str, Any] = None,
        recovery_actions: List[str] = None
    ) -> Dict[str, Any]:
        """格式化错误日志"""
        return {
            "category": LogCategory.ERROR.value,
            "error_type": error_type,
            "error_message": error_message,
            "error_code": error_code,
            "context": context or {},
            "recovery_actions": recovery_actions or [],
            "timestamp": datetime.now().isoformat()
        }


class LoggerConfig:
    """日志配置类"""
    
    def __init__(self):
        self.settings = settings
        self.formatter = StructuredLogFormatter()
        self.configure_logger()
    
    def configure_logger(self):
        """配置日志"""
        # 移除默认日志处理器
        logger.remove()
        
        # 配置控制台输出
        logger.add(
            sys.stdout,
            level=self.settings.log_level,
            format=self._get_console_format(),
            colorize=True,
            backtrace=True,
            diagnose=True
        )
        
        # 配置文件输出
        log_file = os.path.join(self.settings.log_path, "app.log")
        if self.settings.log_format == "json":
            logger.add(
                log_file,
                level=self.settings.log_level,
                format=self._json_formatter,
                rotation=self.settings.log_rotation,
                retention=self.settings.log_retention,
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=True,
                serialize=False
            )
        else:
            logger.add(
                log_file,
                level=self.settings.log_level,
                format=self._get_file_format(),
                rotation=self.settings.log_rotation,
                retention=self.settings.log_retention,
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=True
            )
        
        # 配置错误日志
        error_log_file = os.path.join(self.settings.log_path, "error.log")
        if self.settings.log_format == "json":
            logger.add(
                error_log_file,
                level="ERROR",
                format=self._json_formatter,
                rotation=self.settings.log_rotation,
                retention=self.settings.log_retention,
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=True,
                serialize=False
            )
        else:
            logger.add(
                error_log_file,
                level="ERROR",
                format=self._get_file_format(),
                rotation=self.settings.log_rotation,
                retention=self.settings.log_retention,
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=True
            )
        
        # 配置交易相关日志
        trading_log_file = os.path.join(self.settings.log_path, "trading.log")
        if self.settings.log_format == "json":
            logger.add(
                trading_log_file,
                level="INFO",
                format=self._json_formatter,
                rotation="1 day",
                retention="90 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "trading" in record["extra"],
                serialize=False
            )
        else:
            logger.add(
                trading_log_file,
                level="INFO",
                format=self._get_file_format(),
                rotation="1 day",
                retention="90 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "trading" in record["extra"]
            )
        
        # 配置监控日志
        monitor_log_file = os.path.join(self.settings.log_path, "monitor.log")
        if self.settings.log_format == "json":
            logger.add(
                monitor_log_file,
                level="INFO",
                format=self._json_formatter,
                rotation="6 hours",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "monitor" in record["extra"],
                serialize=False
            )
        else:
            logger.add(
                monitor_log_file,
                level="INFO",
                format=self._get_file_format(),
                rotation="6 hours",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "monitor" in record["extra"]
            )
        
        # 配置依赖问题日志
        dependency_log_file = os.path.join(self.settings.log_path, "dependency.log")
        if self.settings.log_format == "json":
            logger.add(
                dependency_log_file,
                level="WARNING",
                format=self._json_formatter,
                rotation="1 day",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "dependency" in record["extra"],
                serialize=False
            )
        else:
            logger.add(
                dependency_log_file,
                level="WARNING",
                format=self._get_file_format(),
                rotation="1 day",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "dependency" in record["extra"]
            )
        
        # 配置服务初始化诊断日志
        service_log_file = os.path.join(self.settings.log_path, "service.log")
        if self.settings.log_format == "json":
            logger.add(
                service_log_file,
                level="INFO",
                format=self._json_formatter,
                rotation="1 day",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "service" in record["extra"],
                serialize=False
            )
        else:
            logger.add(
                service_log_file,
                level="INFO",
                format=self._get_file_format(),
                rotation="1 day",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "service" in record["extra"]
            )
        
        # 配置性能日志
        performance_log_file = os.path.join(self.settings.log_path, "performance.log")
        if self.settings.log_format == "json":
            logger.add(
                performance_log_file,
                level="INFO",
                format=self._json_formatter,
                rotation="1 day",
                retention="7 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "performance" in record["extra"],
                serialize=False
            )
        else:
            logger.add(
                performance_log_file,
                level="INFO",
                format=self._get_file_format(),
                rotation="1 day",
                retention="7 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "performance" in record["extra"]
            )
    
    def _get_console_format(self) -> str:
        """获取控制台日志格式"""
        # 控制台始终使用简单格式，方便阅读
        return "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
    
    def _get_file_format(self) -> str:
        """获取文件日志格式"""
        return "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}"
    
    def _json_formatter(self, record: Dict[str, Any]) -> str:
        """JSON格式化器"""
        log_entry = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "function": record["function"],
            "line": record["line"],
            "message": record["message"],
            "extra": record.get("extra", {})
        }
        
        if record.get("exception"):
            log_entry["exception"] = {
                "type": record["exception"].type.__name__,
                "value": str(record["exception"].value),
                "traceback": record["exception"].traceback
            }
        
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def get_logger(name: str = None):
    """获取日志器"""
    if name:
        return logger.bind(name=name)
    return logger


def get_trading_logger():
    """获取交易日志器"""
    return logger.bind(trading=True)


def get_monitor_logger():
    """获取监控日志器"""
    return logger.bind(monitor=True)


def get_dependency_logger():
    """获取依赖日志器"""
    return logger.bind(dependency=True)


def get_service_logger():
    """获取服务日志器"""
    return logger.bind(service=True)


def get_performance_logger():
    """获取性能日志器"""
    return logger.bind(performance=True)


def log_dependency_issue(
    operation: str,
    dependency_name: str,
    status: str,
    level: str = "WARNING",
    details: Dict[str, Any] = None
):
    """记录依赖问题日志"""
    dep_logger = get_dependency_logger()
    log_data = StructuredLogFormatter.format_dependency_log(
        operation, dependency_name, status, details
    )
    
    message = f"🔧 依赖操作: {operation} - {dependency_name} ({status})"
    
    if level.upper() == "ERROR":
        dep_logger.error(message, extra=log_data)
    elif level.upper() == "WARNING":
        dep_logger.warning(message, extra=log_data)
    else:
        dep_logger.info(message, extra=log_data)


def log_service_operation(
    service_name: str,
    operation: str,
    status: str,
    duration: Optional[float] = None,
    level: str = "INFO",
    details: Dict[str, Any] = None
):
    """记录服务操作日志"""
    svc_logger = get_service_logger()
    log_data = StructuredLogFormatter.format_service_log(
        service_name, operation, status, duration, details
    )
    
    message = f"🔧 服务操作: {service_name} - {operation} ({status})"
    if duration:
        message += f" [{duration:.2f}s]"
    
    if level.upper() == "ERROR":
        svc_logger.error(message, extra=log_data)
    elif level.upper() == "WARNING":
        svc_logger.warning(message, extra=log_data)
    else:
        svc_logger.info(message, extra=log_data)


def log_performance_metric(
    operation: str,
    duration: float,
    resource_usage: Dict[str, Any] = None,
    metadata: Dict[str, Any] = None
):
    """记录性能指标日志"""
    perf_logger = get_performance_logger()
    log_data = StructuredLogFormatter.format_performance_log(
        operation, duration, resource_usage, metadata
    )
    
    message = f"⏱️ 性能指标: {operation} - {duration:.2f}s"
    perf_logger.info(message, extra=log_data)


def log_structured_error(
    error_type: str,
    error_message: str,
    error_code: Optional[str] = None,
    context: Dict[str, Any] = None,
    recovery_actions: List[str] = None,
    level: str = "ERROR"
):
    """记录结构化错误日志"""
    log_data = StructuredLogFormatter.format_error_log(
        error_type, error_message, error_code, context, recovery_actions
    )
    
    message = f"❌ 错误: {error_type} - {error_message}"
    if error_code:
        message += f" [{error_code}]"
    
    if level.upper() == "CRITICAL":
        logger.critical(message, extra=log_data)
    elif level.upper() == "ERROR":
        logger.error(message, extra=log_data)
    else:
        logger.warning(message, extra=log_data)


def log_performance(operation_name: str, log_args: bool = False):
    """
    性能日志装饰器
    Performance logging decorator
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            func_name = f"{func.__module__}.{func.__name__}"
            
            # 记录开始
            log_data = {"operation": operation_name, "function": func_name}
            if log_args:
                log_data["args"] = str(args)[:200]  # 限制长度
                log_data["kwargs"] = {k: str(v)[:100] for k, v in kwargs.items()}
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                # 记录成功完成
                log_performance_metric(
                    operation=operation_name,
                    duration=duration,
                    metadata={
                        "function": func_name,
                        "status": "success",
                        "args_logged": log_args
                    }
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                # 记录失败
                log_performance_metric(
                    operation=operation_name,
                    duration=duration,
                    metadata={
                        "function": func_name,
                        "status": "failed",
                        "error": str(e),
                        "args_logged": log_args
                    }
                )
                
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            func_name = f"{func.__module__}.{func.__name__}"
            
            # 记录开始
            log_data = {"operation": operation_name, "function": func_name}
            if log_args:
                log_data["args"] = str(args)[:200]  # 限制长度
                log_data["kwargs"] = {k: str(v)[:100] for k, v in kwargs.items()}
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # 记录成功完成
                log_performance_metric(
                    operation=operation_name,
                    duration=duration,
                    metadata={
                        "function": func_name,
                        "status": "success",
                        "args_logged": log_args
                    }
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                # 记录失败
                log_performance_metric(
                    operation=operation_name,
                    duration=duration,
                    metadata={
                        "function": func_name,
                        "status": "failed",
                        "error": str(e),
                        "args_logged": log_args
                    }
                )
                
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def log_service_lifecycle(service_name: str):
    """
    服务生命周期日志装饰器
    Service lifecycle logging decorator
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            operation = func.__name__
            start_time = time.time()
            
            # 记录开始
            log_service_operation(
                service_name=service_name,
                operation=operation,
                status="started",
                level="INFO"
            )
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                # 记录成功完成
                log_service_operation(
                    service_name=service_name,
                    operation=operation,
                    status="completed",
                    duration=duration,
                    level="INFO"
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                # 记录失败
                log_service_operation(
                    service_name=service_name,
                    operation=operation,
                    status="failed",
                    duration=duration,
                    level="ERROR",
                    details={"error": str(e), "error_type": type(e).__name__}
                )
                
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            operation = func.__name__
            start_time = time.time()
            
            # 记录开始
            log_service_operation(
                service_name=service_name,
                operation=operation,
                status="started",
                level="INFO"
            )
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # 记录成功完成
                log_service_operation(
                    service_name=service_name,
                    operation=operation,
                    status="completed",
                    duration=duration,
                    level="INFO"
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                # 记录失败
                log_service_operation(
                    service_name=service_name,
                    operation=operation,
                    status="failed",
                    duration=duration,
                    level="ERROR",
                    details={"error": str(e), "error_type": type(e).__name__}
                )
                
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


# 延迟初始化，避免导入时配置问题
_logger_config = None
_trading_logger = None
_monitor_logger = None
_dependency_logger = None
_service_logger = None
_performance_logger = None

def _ensure_logger_configured():
    """确保日志已配置"""
    global _logger_config, _trading_logger, _monitor_logger, _dependency_logger, _service_logger, _performance_logger
    if _logger_config is None:
        _logger_config = LoggerConfig()
        _trading_logger = get_trading_logger()
        _monitor_logger = get_monitor_logger()
        _dependency_logger = get_dependency_logger()
        _service_logger = get_service_logger()
        _performance_logger = get_performance_logger()
        
        # 设置应用启动日志
        logger.info(f"🚀 应用启动 - 日志级别: {settings.log_level}")
        logger.info(f"📝 日志格式: {settings.log_format}")
        logger.info(f"📁 日志路径: {settings.log_path}")
        
        # 记录日志系统初始化
        log_service_operation(
            service_name="logging_system",
            operation="initialize",
            status="completed",
            details={
                "log_level": settings.log_level,
                "log_format": settings.log_format,
                "log_path": settings.log_path
            }
        )

def get_trading_logger_instance():
    """获取交易日志器实例"""
    _ensure_logger_configured()
    return _trading_logger

def get_monitor_logger_instance():
    """获取监控日志器实例"""
    _ensure_logger_configured() 
    return _monitor_logger


def get_dependency_logger_instance():
    """获取依赖日志器实例"""
    _ensure_logger_configured()
    return _dependency_logger


def get_service_logger_instance():
    """获取服务日志器实例"""
    _ensure_logger_configured()
    return _service_logger


def get_performance_logger_instance():
    """获取性能日志器实例"""
    _ensure_logger_configured()
    return _performance_logger

# 为了向后兼容，恢复 trading_logger 和 monitor_logger 导出
def _get_trading_logger_lazy():
    """延迟获取交易日志器"""
    return get_trading_logger_instance()

def _get_monitor_logger_lazy():
    """延迟获取监控日志器"""
    return get_monitor_logger_instance()


def _get_dependency_logger_lazy():
    """延迟获取依赖日志器"""
    return get_dependency_logger_instance()


def _get_service_logger_lazy():
    """延迟获取服务日志器"""
    return get_service_logger_instance()


def _get_performance_logger_lazy():
    """延迟获取性能日志器"""
    return get_performance_logger_instance()

# 创建延迟加载的代理对象
class _LazyLogger:
    def __init__(self, get_logger_func):
        self._get_logger_func = get_logger_func
        self._logger = None
    
    def _ensure_logger(self):
        if self._logger is None:
            self._logger = self._get_logger_func()
        return self._logger
    
    def info(self, message, *args, **kwargs):
        return self._ensure_logger().info(message, *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        return self._ensure_logger().error(message, *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        return self._ensure_logger().warning(message, *args, **kwargs)
    
    def debug(self, message, *args, **kwargs):
        return self._ensure_logger().debug(message, *args, **kwargs)

# 创建延迟加载的日志器实例
trading_logger = _LazyLogger(_get_trading_logger_lazy)
monitor_logger = _LazyLogger(_get_monitor_logger_lazy)
dependency_logger = _LazyLogger(_get_dependency_logger_lazy)
service_logger = _LazyLogger(_get_service_logger_lazy)
performance_logger = _LazyLogger(_get_performance_logger_lazy)


class LogLevelManager:
    """
    日志级别管理器
    Log level manager
    """
    
    def __init__(self):
        self._error_type_levels = {
            "DependencyError": LogLevel.WARNING,
            "MissingDependencyError": LogLevel.ERROR,
            "IncompatibleDependencyError": LogLevel.WARNING,
            "DependencyImportError": LogLevel.WARNING,
            "ServiceInitializationError": LogLevel.ERROR,
            "ServiceDependencyError": LogLevel.ERROR,
            "ServiceConfigurationError": LogLevel.WARNING,
            "ServiceTimeoutError": LogLevel.WARNING,
            "ServiceHealthCheckError": LogLevel.WARNING,
            "APIConnectionError": LogLevel.WARNING,
            "BinanceAPIError": LogLevel.WARNING,
            "RateLimitError": LogLevel.WARNING,
            "ConfigurationError": LogLevel.ERROR,
            "ValidationError": LogLevel.WARNING,
            "MLModelError": LogLevel.WARNING,
            "PredictionError": LogLevel.WARNING
        }
    
    def get_log_level_for_error(self, error_type: str) -> LogLevel:
        """获取错误类型对应的日志级别"""
        return self._error_type_levels.get(error_type, LogLevel.ERROR)
    
    def set_error_log_level(self, error_type: str, level: LogLevel):
        """设置错误类型的日志级别"""
        self._error_type_levels[error_type] = level
    
    def log_error_with_appropriate_level(self, error):
        """使用适当级别记录错误"""
        from app.utils.exceptions import TradingToolError
        
        if isinstance(error, TradingToolError):
            error_type = type(error).__name__
            level = self.get_log_level_for_error(error_type)
            
            log_structured_error(
                error_type=error_type,
                error_message=error.message,
                error_code=getattr(error, 'error_code', None),
                context=getattr(error, 'context', {}),
                recovery_actions=getattr(error, 'get_recovery_suggestions', lambda: [])(),
                level=level.value
            )
        else:
            # 对于非自定义异常，使用ERROR级别
            log_structured_error(
                error_type=type(error).__name__,
                error_message=str(error),
                level=LogLevel.ERROR.value
            )


# 全局日志级别管理器实例
log_level_manager = LogLevelManager()


def configure_error_logging_levels(config: Dict[str, str]):
    """
    配置错误日志级别
    Configure error logging levels
    
    Args:
        config: 错误类型到日志级别的映射
    """
    for error_type, level_str in config.items():
        try:
            level = LogLevel(level_str.upper())
            log_level_manager.set_error_log_level(error_type, level)
        except ValueError:
            logger.warning(f"⚠️ 无效的日志级别配置: {error_type} -> {level_str}")


def log_exception_with_context(
    exc: Exception, 
    context: Dict[str, Any] = None,
    operation: str = None
):
    """
    带上下文的异常日志记录
    Exception logging with context
    """
    from app.utils.exceptions import TradingToolError
    
    if isinstance(exc, TradingToolError):
        # 使用结构化错误日志
        log_level_manager.log_error_with_appropriate_level(exc)
        
        # 如果有操作上下文，也记录性能影响
        if operation:
            log_performance_metric(
                operation=operation,
                duration=0,  # 异常情况下无法测量完整时间
                metadata={
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)
                }
            )
    else:
        # 对于系统异常，记录完整堆栈
        logger.exception(
            f"💥 系统异常: {type(exc).__name__}: {str(exc)}",
            extra={
                "category": LogCategory.ERROR.value,
                "error_type": type(exc).__name__,
                "context": context or {},
                "operation": operation
            }
        )


def create_diagnostic_logger(component_name: str):
    """
    创建诊断日志器
    Create diagnostic logger
    """
    def diagnostic_log(level: str, message: str, **kwargs):
        """诊断日志函数"""
        extra_data = {
            "category": "diagnostic",
            "component": component_name,
            **kwargs
        }
        
        formatted_message = f"🔍 [{component_name}] {message}"
        
        if level.upper() == "DEBUG":
            logger.debug(formatted_message, extra=extra_data)
        elif level.upper() == "INFO":
            logger.info(formatted_message, extra=extra_data)
        elif level.upper() == "WARNING":
            logger.warning(formatted_message, extra=extra_data)
        elif level.upper() == "ERROR":
            logger.error(formatted_message, extra=extra_data)
        else:
            logger.info(formatted_message, extra=extra_data)
    
    return diagnostic_log