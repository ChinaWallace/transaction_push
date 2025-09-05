# -*- coding: utf-8 -*-
"""
错误恢复管理器
Error Recovery Manager for handling different error types and recovery strategies
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Callable, Type
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from contextlib import asynccontextmanager

from app.core.logging import get_logger, log_structured_error, log_performance_metric
from app.utils.exceptions import (
    APIConnectionError, DependencyError, ServiceInitializationError, BinanceAPIError,
    RateLimitError, ConfigurationError, MLModelError, PredictionError,
    ServiceHealthCheckError
)

logger = get_logger(__name__)


class RetryStrategy(Enum):
    """重试策略枚举"""
    NONE = "none"
    FIXED_DELAY = "fixed_delay"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    CUSTOM = "custom"


class CircuitBreakerState(Enum):
    """断路器状态枚举"""
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 断开状态
    HALF_OPEN = "half_open"  # 半开状态


@dataclass
class RetryConfig:
    """重试配置"""
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    timeout: Optional[float] = None


@dataclass
class CircuitBreakerConfig:
    """断路器配置"""
    failure_threshold: int = 5  # 失败阈值
    recovery_timeout: float = 60.0  # 恢复超时时间（秒）
    success_threshold: int = 2  # 半开状态下成功阈值
    monitor_window: float = 300.0  # 监控窗口时间（秒）


@dataclass
class ErrorStats:
    """错误统计"""
    error_type: str
    total_count: int = 0
    recent_count: int = 0
    last_occurrence: Optional[datetime] = None
    recovery_attempts: int = 0
    successful_recoveries: int = 0
    circuit_breaker_trips: int = 0


@dataclass
class CircuitBreakerState:
    """断路器状态"""
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    next_attempt_time: Optional[datetime] = None


class RetryHandler:
    """重试处理器"""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        执行带重试的函数
        Execute function with retry logic
        """
        last_exception = None
        
        for attempt in range(self.config.max_attempts):
            try:
                if self.config.timeout:
                    return await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
                else:
                    return await func(*args, **kwargs)
                    
            except Exception as e:
                last_exception = e
                
                if attempt == self.config.max_attempts - 1:
                    break
                
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    f"⚠️ 重试操作: 第{attempt + 1}次失败，{delay:.2f}秒后重试 - {e}",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": self.config.max_attempts,
                        "delay": delay,
                        "error": str(e)
                    }
                )
                
                await asyncio.sleep(delay)
        
        raise last_exception
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        if self.config.strategy == RetryStrategy.FIXED_DELAY:
            delay = self.config.base_delay
        elif self.config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = self.config.base_delay * (self.config.backoff_multiplier ** attempt)
        elif self.config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = self.config.base_delay * (attempt + 1)
        else:
            delay = self.config.base_delay
        
        # 应用最大延迟限制
        delay = min(delay, self.config.max_delay)
        
        # 添加抖动
        if self.config.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)
        
        return delay


class CircuitBreaker:
    """断路器"""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitBreakerState()
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过断路器调用函数
        Call function through circuit breaker
        """
        async with self._lock:
            current_time = datetime.now()
            
            # 检查断路器状态
            if self.state.state == CircuitBreakerState.OPEN:
                if (self.state.next_attempt_time and 
                    current_time < self.state.next_attempt_time):
                    raise ServiceHealthCheckError(
                        f"断路器开启: {self.name}",
                        service_name=self.name,
                        health_status="circuit_breaker_open"
                    )
                else:
                    # 转换到半开状态
                    self.state.state = CircuitBreakerState.HALF_OPEN
                    self.state.success_count = 0
                    logger.info(f"🔄 断路器转为半开状态: {self.name}")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
            
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """成功回调"""
        async with self._lock:
            if self.state.state == CircuitBreakerState.HALF_OPEN:
                self.state.success_count += 1
                
                if self.state.success_count >= self.config.success_threshold:
                    self.state.state = CircuitBreakerState.CLOSED
                    self.state.failure_count = 0
                    logger.info(f"✅ 断路器恢复正常: {self.name}")
            
            elif self.state.state == CircuitBreakerState.CLOSED:
                # 重置失败计数
                self.state.failure_count = max(0, self.state.failure_count - 1)
    
    async def _on_failure(self):
        """失败回调"""
        async with self._lock:
            self.state.failure_count += 1
            self.state.last_failure_time = datetime.now()
            
            if (self.state.state == CircuitBreakerState.CLOSED and 
                self.state.failure_count >= self.config.failure_threshold):
                
                self.state.state = CircuitBreakerState.OPEN
                self.state.next_attempt_time = (
                    datetime.now() + timedelta(seconds=self.config.recovery_timeout)
                )
                
                logger.error(f"🚨 断路器开启: {self.name} (失败次数: {self.state.failure_count})")
            
            elif self.state.state == CircuitBreakerState.HALF_OPEN:
                self.state.state = CircuitBreakerState.OPEN
                self.state.next_attempt_time = (
                    datetime.now() + timedelta(seconds=self.config.recovery_timeout)
                )
                
                logger.warning(f"⚠️ 断路器重新开启: {self.name}")
    
    def get_state(self) -> Dict[str, Any]:
        """获取断路器状态"""
        return {
            "name": self.name,
            "state": self.state.state.value,
            "failure_count": self.state.failure_count,
            "success_count": self.state.success_count,
            "last_failure_time": self.state.last_failure_time.isoformat() if self.state.last_failure_time else None,
            "next_attempt_time": self.state.next_attempt_time.isoformat() if self.state.next_attempt_time else None
        }


class ErrorRecoveryManager:
    """
    错误恢复管理器
    Error Recovery Manager for handling different error types and recovery strategies
    """
    
    def __init__(self):
        self._retry_configs: Dict[Type[Exception], RetryConfig] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._fallback_handlers: Dict[Type[Exception], Callable] = {}
        self._recovery_handlers: Dict[Type[Exception], Callable] = {}
        self._error_stats: Dict[str, ErrorStats] = {}
        self._service_recovery_callbacks: Dict[str, List[Callable]] = {}
        
        # 初始化默认配置
        self._setup_default_configurations()
        
        logger.info("🚀 错误恢复管理器初始化完成")
    
    def _setup_default_configurations(self):
        """设置默认配置"""
        # API连接错误 - 指数退避重试
        self._retry_configs[APIConnectionError] = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0,
            backoff_multiplier=2.0
        )
        
        # Binance API错误 - 固定延迟重试
        self._retry_configs[BinanceAPIError] = RetryConfig(
            strategy=RetryStrategy.FIXED_DELAY,
            max_attempts=2,
            base_delay=2.0,
            timeout=10.0
        )
        
        # 速率限制错误 - 线性退避
        self._retry_configs[RateLimitError] = RetryConfig(
            strategy=RetryStrategy.LINEAR_BACKOFF,
            max_attempts=5,
            base_delay=5.0,
            max_delay=60.0
        )
        
        # 依赖错误 - 不重试，使用回退
        self._retry_configs[DependencyError] = RetryConfig(
            strategy=RetryStrategy.NONE,
            max_attempts=1
        )
        
        # 服务初始化错误 - 短延迟重试
        self._retry_configs[ServiceInitializationError] = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_attempts=2,
            base_delay=2.0,
            max_delay=10.0
        )
        
        # ML模型错误 - 使用回退
        self._retry_configs[MLModelError] = RetryConfig(
            strategy=RetryStrategy.NONE,
            max_attempts=1
        )
        
        # 预测错误 - 快速重试一次
        self._retry_configs[PredictionError] = RetryConfig(
            strategy=RetryStrategy.FIXED_DELAY,
            max_attempts=2,
            base_delay=0.5
        )
    
    def register_retry_config(self, exception_type: Type[Exception], config: RetryConfig):
        """
        注册重试配置
        Register retry configuration
        """
        self._retry_configs[exception_type] = config
        logger.info(f"📝 注册重试配置: {exception_type.__name__}")
    
    def register_circuit_breaker(self, name: str, config: CircuitBreakerConfig):
        """
        注册断路器
        Register circuit breaker
        """
        self._circuit_breakers[name] = CircuitBreaker(name, config)
        logger.info(f"📝 注册断路器: {name}")
    
    def register_fallback_handler(self, exception_type: Type[Exception], handler: Callable):
        """
        注册回退处理器
        Register fallback handler
        """
        self._fallback_handlers[exception_type] = handler
        logger.info(f"📝 注册回退处理器: {exception_type.__name__}")
    
    def register_recovery_handler(self, exception_type: Type[Exception], handler: Callable):
        """
        注册恢复处理器
        Register recovery handler
        """
        self._recovery_handlers[exception_type] = handler
        logger.info(f"📝 注册恢复处理器: {exception_type.__name__}")
    
    def register_service_recovery_callback(self, service_name: str, callback: Callable):
        """
        注册服务恢复回调
        Register service recovery callback
        """
        if service_name not in self._service_recovery_callbacks:
            self._service_recovery_callbacks[service_name] = []
        
        self._service_recovery_callbacks[service_name].append(callback)
        logger.info(f"📝 注册服务恢复回调: {service_name}")
    
    async def handle_error(self, error: Exception, context: Dict[str, Any] = None, 
                          operation: str = None) -> Any:
        """
        处理错误并尝试恢复
        Handle error and attempt recovery
        """
        error_type = type(error)
        error_name = error_type.__name__
        context = context or {}
        
        # 更新错误统计
        self._update_error_stats(error_name)
        
        # 记录错误
        log_structured_error(
            error_type=error_name,
            error_message=str(error),
            error_code=getattr(error, 'error_code', None),
            context=context,
            recovery_actions=self._get_recovery_actions(error)
        )
        
        try:
            # 尝试特定的恢复处理器
            if error_type in self._recovery_handlers:
                logger.info(f"🔧 尝试恢复处理: {error_name}")
                result = await self._execute_recovery_handler(error, context)
                if result is not None:
                    self._record_successful_recovery(error_name)
                    return result
            
            # 尝试回退处理器
            if error_type in self._fallback_handlers:
                logger.info(f"🔄 使用回退处理: {error_name}")
                result = await self._execute_fallback_handler(error, context)
                if result is not None:
                    return result
            
            # 如果没有特定处理器，重新抛出异常
            raise error
            
        except Exception as recovery_error:
            logger.error(f"❌ 错误恢复失败: {error_name} - {recovery_error}")
            raise error
    
    async def execute_with_retry(self, func: Callable, exception_types: List[Type[Exception]] = None,
                                context: Dict[str, Any] = None, operation: str = None) -> Any:
        """
        执行带重试的操作
        Execute operation with retry logic
        """
        exception_types = exception_types or [Exception]
        context = context or {}
        
        # 查找适用的重试配置
        retry_config = None
        for exc_type in exception_types:
            if exc_type in self._retry_configs:
                retry_config = self._retry_configs[exc_type]
                break
        
        if not retry_config or retry_config.strategy == RetryStrategy.NONE:
            # 没有重试配置，直接执行
            try:
                return await func()
            except Exception as e:
                return await self.handle_error(e, context, operation)
        
        # 使用重试处理器
        retry_handler = RetryHandler(retry_config)
        
        try:
            start_time = time.time()
            result = await retry_handler.execute(func)
            
            # 记录成功的性能指标
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={"status": "success", "retry_used": True}
                )
            
            return result
            
        except Exception as e:
            # 记录失败的性能指标
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={
                        "status": "failed",
                        "error_type": type(e).__name__,
                        "retry_used": True
                    }
                )
            
            return await self.handle_error(e, context, operation)
    
    async def execute_with_circuit_breaker(self, circuit_breaker_name: str, func: Callable,
                                         context: Dict[str, Any] = None, operation: str = None) -> Any:
        """
        通过断路器执行操作
        Execute operation through circuit breaker
        """
        if circuit_breaker_name not in self._circuit_breakers:
            logger.warning(f"⚠️ 断路器不存在: {circuit_breaker_name}")
            return await func()
        
        circuit_breaker = self._circuit_breakers[circuit_breaker_name]
        context = context or {}
        
        try:
            start_time = time.time()
            result = await circuit_breaker.call(func)
            
            # 记录成功的性能指标
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={
                        "status": "success",
                        "circuit_breaker": circuit_breaker_name,
                        "circuit_breaker_state": circuit_breaker.state.state.value
                    }
                )
            
            return result
            
        except Exception as e:
            # 记录失败的性能指标
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={
                        "status": "failed",
                        "error_type": type(e).__name__,
                        "circuit_breaker": circuit_breaker_name,
                        "circuit_breaker_state": circuit_breaker.state.state.value
                    }
                )
            
            return await self.handle_error(e, context, operation)
    
    @asynccontextmanager
    async def error_recovery_context(self, operation: str = None, 
                                   context: Dict[str, Any] = None):
        """
        错误恢复上下文管理器
        Error recovery context manager
        """
        context = context or {}
        start_time = time.time()
        
        try:
            yield self
            
            # 记录成功
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={"status": "success", "context": context}
                )
                
        except Exception as e:
            # 记录失败并尝试恢复
            if operation:
                log_performance_metric(
                    operation=operation,
                    duration=time.time() - start_time,
                    metadata={
                        "status": "failed",
                        "error_type": type(e).__name__,
                        "context": context
                    }
                )
            
            recovered_result = await self.handle_error(e, context, operation)
            if recovered_result is not None:
                # In async context managers, we should raise the exception or let it propagate
                # Cannot return a value from an async generator
                pass
            raise
    
    async def notify_service_recovery(self, service_name: str, recovery_info: Dict[str, Any] = None):
        """
        通知服务恢复
        Notify service recovery
        """
        if service_name not in self._service_recovery_callbacks:
            return
        
        recovery_info = recovery_info or {}
        
        logger.info(f"📢 通知服务恢复: {service_name}")
        
        for callback in self._service_recovery_callbacks[service_name]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(service_name, recovery_info)
                else:
                    callback(service_name, recovery_info)
                    
            except Exception as e:
                logger.error(f"❌ 服务恢复回调失败: {service_name} - {e}")
    
    async def _execute_recovery_handler(self, error: Exception, context: Dict[str, Any]) -> Any:
        """执行恢复处理器"""
        error_type = type(error)
        handler = self._recovery_handlers[error_type]
        
        if asyncio.iscoroutinefunction(handler):
            return await handler(error, context)
        else:
            return handler(error, context)
    
    async def _execute_fallback_handler(self, error: Exception, context: Dict[str, Any]) -> Any:
        """执行回退处理器"""
        error_type = type(error)
        handler = self._fallback_handlers[error_type]
        
        if asyncio.iscoroutinefunction(handler):
            return await handler(error, context)
        else:
            return handler(error, context)
    
    def _update_error_stats(self, error_name: str):
        """更新错误统计"""
        if error_name not in self._error_stats:
            self._error_stats[error_name] = ErrorStats(error_type=error_name)
        
        stats = self._error_stats[error_name]
        stats.total_count += 1
        stats.recent_count += 1
        stats.last_occurrence = datetime.now()
    
    def _record_successful_recovery(self, error_name: str):
        """记录成功恢复"""
        if error_name in self._error_stats:
            self._error_stats[error_name].successful_recoveries += 1
    
    def _get_recovery_actions(self, error: Exception) -> List[str]:
        """获取恢复建议"""
        if hasattr(error, 'get_recovery_suggestions'):
            return error.get_recovery_suggestions()
        
        # 基于错误类型提供默认建议
        error_type = type(error)
        
        if issubclass(error_type, APIConnectionError):
            return ["检查网络连接", "验证API凭据", "稍后重试"]
        elif issubclass(error_type, DependencyError):
            return ["安装缺失依赖", "检查依赖版本", "使用回退方案"]
        elif issubclass(error_type, ServiceInitializationError):
            return ["检查服务配置", "重启服务", "检查依赖项"]
        elif issubclass(error_type, ConfigurationError):
            return ["检查配置文件", "验证配置参数", "使用默认配置"]
        else:
            return ["检查系统状态", "查看日志详情", "联系技术支持"]
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        获取错误统计信息
        Get error statistics
        """
        stats = {
            "total_errors": sum(stat.total_count for stat in self._error_stats.values()),
            "error_types": len(self._error_stats),
            "circuit_breakers": len(self._circuit_breakers),
            "recovery_handlers": len(self._recovery_handlers),
            "fallback_handlers": len(self._fallback_handlers),
            "error_details": {},
            "circuit_breaker_states": {}
        }
        
        # 错误详情
        for error_name, error_stat in self._error_stats.items():
            stats["error_details"][error_name] = {
                "total_count": error_stat.total_count,
                "recent_count": error_stat.recent_count,
                "last_occurrence": error_stat.last_occurrence.isoformat() if error_stat.last_occurrence else None,
                "recovery_attempts": error_stat.recovery_attempts,
                "successful_recoveries": error_stat.successful_recoveries,
                "success_rate": (
                    error_stat.successful_recoveries / error_stat.recovery_attempts 
                    if error_stat.recovery_attempts > 0 else 0
                )
            }
        
        # 断路器状态
        for name, circuit_breaker in self._circuit_breakers.items():
            stats["circuit_breaker_states"][name] = circuit_breaker.get_state()
        
        return stats
    
    def reset_error_statistics(self):
        """重置错误统计"""
        self._error_stats.clear()
        logger.info("🔄 错误统计已重置")
    
    def get_recovery_suggestions(self, error: Exception) -> List[str]:
        """
        获取错误恢复建议
        Get error recovery suggestions
        """
        return self._get_recovery_actions(error)


# 全局错误恢复管理器实例
error_recovery_manager = ErrorRecoveryManager()