# -*- coding: utf-8 -*-
"""
混合服务基类
Hybrid Service Base Class - WebSocket + REST API 混合数据源基础框架
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable
from datetime import datetime

from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError, APIConnectionError

logger = get_logger(__name__)


class HybridServiceBase(ABC):
    """
    混合服务基类 - WebSocket + REST API
    Hybrid Service Base Class - Combines WebSocket and REST API data sources
    
    提供智能数据源选择策略：
    1. 优先使用WebSocket获取实时数据
    2. WebSocket不可用时自动回退到REST API
    3. 某些操作（如历史数据、账户操作）直接使用REST API
    4. 提供统一的错误处理和重试机制
    """
    
    def __init__(self):
        # WebSocket配置
        self.is_websocket_enabled = True
        self.websocket_timeout = 5.0  # WebSocket数据超时时间（秒）
        self.websocket_retry_count = 3  # WebSocket重试次数
        self.websocket_retry_delay = 2.0  # WebSocket重试延迟（秒）
        
        # 服务状态
        self.is_initialized = False
        self.is_websocket_connected = False
        self.last_websocket_error = None
        self.websocket_error_count = 0
        
        # 数据源状态跟踪
        self.data_source_stats = {
            'websocket_requests': 0,
            'websocket_successes': 0,
            'rest_api_requests': 0,
            'rest_api_successes': 0,
            'fallback_count': 0,
            'last_update': datetime.now()
        }
        
        # 回退策略配置
        self.fallback_enabled = True
        self.max_websocket_errors = 5  # 最大WebSocket错误次数，超过后禁用WebSocket
        self.websocket_recovery_interval = 300  # WebSocket恢复检查间隔（秒）
        self.last_websocket_recovery_check = datetime.now()
        
        logger.debug("🔄 混合服务基类初始化完成")
    
    # ==================== 抽象方法 Abstract Methods ====================
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        初始化混合服务
        Initialize hybrid service
        
        子类必须实现此方法来初始化具体的WebSocket和REST API服务
        """
    
    @abstractmethod
    async def _setup_websocket(self) -> None:
        """
        设置WebSocket连接
        Setup WebSocket connection
        
        子类实现具体的WebSocket连接逻辑
        """
    
    @abstractmethod
    async def _setup_rest_api(self) -> None:
        """
        设置REST API服务
        Setup REST API service
        
        子类实现具体的REST API初始化逻辑
        """
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        清理资源
        Cleanup resources
        
        子类实现具体的资源清理逻辑
        """
    
    # ==================== WebSocket状态管理 WebSocket State Management ====================
    
    async def _check_websocket_health(self) -> bool:
        """
        检查WebSocket连接健康状态
        Check WebSocket connection health
        
        Returns:
            bool: WebSocket是否健康 / Whether WebSocket is healthy
        """
        if not self.is_websocket_enabled:
            return False
        
        # 检查连接状态
        if not self.is_websocket_connected:
            return False
        
        # 检查错误计数
        if self.websocket_error_count >= self.max_websocket_errors:
            logger.warning(f"⚠️ WebSocket错误次数过多 ({self.websocket_error_count})，暂时禁用")
            return False
        
        return True
    
    async def _handle_websocket_error(self, error: Exception, operation: str = "") -> None:
        """
        处理WebSocket错误
        Handle WebSocket error
        
        Args:
            error: 错误对象 / Error object
            operation: 操作名称 / Operation name
        """
        self.websocket_error_count += 1
        self.last_websocket_error = error
        
        logger.warning(f"⚠️ WebSocket错误 ({operation}): {error}")
        
        # 如果错误次数过多，暂时禁用WebSocket
        if self.websocket_error_count >= self.max_websocket_errors:
            logger.error(f"❌ WebSocket错误次数达到上限 ({self.max_websocket_errors})，禁用WebSocket服务")
            self.is_websocket_connected = False
            
            # 设置恢复检查时间
            self.last_websocket_recovery_check = datetime.now()
    
    async def _try_websocket_recovery(self) -> bool:
        """
        尝试WebSocket恢复
        Try WebSocket recovery
        
        Returns:
            bool: 恢复是否成功 / Whether recovery was successful
        """
        now = datetime.now()
        
        # 检查是否到了恢复检查时间
        if (now - self.last_websocket_recovery_check).total_seconds() < self.websocket_recovery_interval:
            return False
        
        logger.info("🔄 尝试恢复WebSocket连接...")
        
        try:
            # 重置错误计数
            self.websocket_error_count = 0
            self.last_websocket_error = None
            
            # 重新设置WebSocket
            await self._setup_websocket()
            
            if self.is_websocket_connected:
                logger.info("✅ WebSocket连接恢复成功")
                return True
            else:
                logger.warning("⚠️ WebSocket连接恢复失败")
                return False
                
        except Exception as e:
            logger.error(f"❌ WebSocket恢复异常: {e}")
            await self._handle_websocket_error(e, "recovery")
            return False
        finally:
            self.last_websocket_recovery_check = now
    
    # ==================== 数据源选择策略 Data Source Selection Strategy ====================
    
    async def _get_data_with_fallback(self, 
                                    websocket_func: Callable,
                                    rest_api_func: Callable,
                                    operation_name: str,
                                    *args, **kwargs) -> Any:
        """
        使用回退策略获取数据
        Get data with fallback strategy
        
        Args:
            websocket_func: WebSocket数据获取函数 / WebSocket data function
            rest_api_func: REST API数据获取函数 / REST API data function
            operation_name: 操作名称 / Operation name
            *args, **kwargs: 函数参数 / Function arguments
            
        Returns:
            Any: 获取的数据 / Retrieved data
        """
        # 首先尝试WebSocket恢复（如果需要）
        if not await self._check_websocket_health():
            await self._try_websocket_recovery()
        
        # 优先尝试WebSocket
        if await self._check_websocket_health():
            try:
                self.data_source_stats['websocket_requests'] += 1
                
                # 使用超时控制
                result = await asyncio.wait_for(
                    websocket_func(*args, **kwargs),
                    timeout=self.websocket_timeout
                )
                
                if result is not None:
                    self.data_source_stats['websocket_successes'] += 1
                    logger.debug(f"🔌 WebSocket获取数据成功: {operation_name}")
                    return result
                else:
                    logger.debug(f"🔌 WebSocket返回空数据: {operation_name}")
                    
            except asyncio.TimeoutError:
                logger.warning(f"⏰ WebSocket超时: {operation_name}")
                await self._handle_websocket_error(
                    APIConnectionError(f"WebSocket timeout: {operation_name}"), 
                    operation_name
                )
            except Exception as e:
                logger.warning(f"⚠️ WebSocket获取数据失败: {operation_name} - {e}")
                await self._handle_websocket_error(e, operation_name)
        
        # 回退到REST API
        if self.fallback_enabled:
            try:
                self.data_source_stats['rest_api_requests'] += 1
                self.data_source_stats['fallback_count'] += 1
                
                logger.debug(f"🌐 回退到REST API: {operation_name}")
                result = await rest_api_func(*args, **kwargs)
                
                if result is not None:
                    self.data_source_stats['rest_api_successes'] += 1
                    logger.debug(f"🌐 REST API获取数据成功: {operation_name}")
                    return result
                else:
                    logger.warning(f"🌐 REST API返回空数据: {operation_name}")
                    
            except Exception as e:
                logger.error(f"❌ REST API获取数据失败: {operation_name} - {e}")
                raise TradingToolError(f"数据获取失败 ({operation_name}): WebSocket和REST API都不可用")
        
        # 所有数据源都失败
        raise TradingToolError(f"数据获取失败 ({operation_name}): 所有数据源不可用")
    
    async def _fallback_to_rest(self, operation_func: Callable, operation_name: str, *args, **kwargs) -> Any:
        """
        直接回退到REST API
        Direct fallback to REST API
        
        Args:
            operation_func: REST API操作函数 / REST API operation function
            operation_name: 操作名称 / Operation name
            *args, **kwargs: 函数参数 / Function arguments
            
        Returns:
            Any: 操作结果 / Operation result
        """
        try:
            self.data_source_stats['rest_api_requests'] += 1
            self.data_source_stats['fallback_count'] += 1
            
            logger.debug(f"🌐 使用REST API: {operation_name}")
            result = await operation_func(*args, **kwargs)
            
            if result is not None:
                self.data_source_stats['rest_api_successes'] += 1
                logger.debug(f"🌐 REST API操作成功: {operation_name}")
                return result
            else:
                logger.warning(f"🌐 REST API返回空结果: {operation_name}")
                return result
                
        except Exception as e:
            logger.error(f"❌ REST API操作失败: {operation_name} - {e}")
            raise TradingToolError(f"REST API操作失败 ({operation_name}): {e}")
    
    # ==================== 重试机制 Retry Mechanism ====================
    
    async def _retry_operation(self, 
                             operation_func: Callable,
                             operation_name: str,
                             max_retries: int = 3,
                             retry_delay: float = 1.0,
                             backoff_factor: float = 2.0,
                             *args, **kwargs) -> Any:
        """
        带重试机制的操作执行
        Execute operation with retry mechanism
        
        Args:
            operation_func: 操作函数 / Operation function
            operation_name: 操作名称 / Operation name
            max_retries: 最大重试次数 / Maximum retry attempts
            retry_delay: 重试延迟 / Retry delay
            backoff_factor: 退避因子 / Backoff factor
            *args, **kwargs: 函数参数 / Function arguments
            
        Returns:
            Any: 操作结果 / Operation result
        """
        last_exception = None
        
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                result = await operation_func(*args, **kwargs)
                
                if attempt > 0:
                    logger.info(f"✅ 重试成功: {operation_name} (第{attempt}次重试)")
                
                return result
                
            except (APIConnectionError, asyncio.TimeoutError) as e:
                last_exception = e
                
                if attempt < max_retries:
                    wait_time = retry_delay * (backoff_factor ** attempt)
                    logger.warning(f"🔄 操作失败，{wait_time:.1f}秒后重试: {operation_name} (第{attempt + 1}次)")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ 重试失败: {operation_name} (已重试{max_retries}次)")
                    
            except Exception as e:
                # 不可重试的异常直接抛出
                logger.error(f"❌ 不可重试的异常: {operation_name} - {e}")
                raise
        
        # 所有重试都失败
        if last_exception:
            raise last_exception
        else:
            raise TradingToolError(f"操作失败: {operation_name}")
    
    # ==================== 统计和监控 Statistics and Monitoring ====================
    
    def get_data_source_statistics(self) -> Dict[str, Any]:
        """
        获取数据源统计信息
        Get data source statistics
        
        Returns:
            Dict[str, Any]: 统计信息 / Statistics information
        """
        stats = self.data_source_stats.copy()
        
        # 计算成功率
        if stats['websocket_requests'] > 0:
            stats['websocket_success_rate'] = stats['websocket_successes'] / stats['websocket_requests']
        else:
            stats['websocket_success_rate'] = 0.0
        
        if stats['rest_api_requests'] > 0:
            stats['rest_api_success_rate'] = stats['rest_api_successes'] / stats['rest_api_requests']
        else:
            stats['rest_api_success_rate'] = 0.0
        
        # 添加状态信息
        stats.update({
            'is_websocket_enabled': self.is_websocket_enabled,
            'is_websocket_connected': self.is_websocket_connected,
            'websocket_error_count': self.websocket_error_count,
            'last_websocket_error': str(self.last_websocket_error) if self.last_websocket_error else None,
            'fallback_enabled': self.fallback_enabled,
            'last_update': datetime.now()
        })
        
        return stats
    
    def reset_statistics(self) -> None:
        """
        重置统计信息
        Reset statistics
        """
        self.data_source_stats = {
            'websocket_requests': 0,
            'websocket_successes': 0,
            'rest_api_requests': 0,
            'rest_api_successes': 0,
            'fallback_count': 0,
            'last_update': datetime.now()
        }
        
        logger.info("📊 数据源统计信息已重置")
    
    # ==================== 配置管理 Configuration Management ====================
    
    def configure_websocket(self, 
                          enabled: bool = None,
                          timeout: float = None,
                          retry_count: int = None,
                          retry_delay: float = None) -> None:
        """
        配置WebSocket参数
        Configure WebSocket parameters
        
        Args:
            enabled: 是否启用WebSocket / Whether to enable WebSocket
            timeout: 超时时间 / Timeout duration
            retry_count: 重试次数 / Retry count
            retry_delay: 重试延迟 / Retry delay
        """
        if enabled is not None:
            self.is_websocket_enabled = enabled
            logger.info(f"🔧 WebSocket启用状态: {enabled}")
        
        if timeout is not None:
            self.websocket_timeout = timeout
            logger.info(f"🔧 WebSocket超时时间: {timeout}秒")
        
        if retry_count is not None:
            self.websocket_retry_count = retry_count
            logger.info(f"🔧 WebSocket重试次数: {retry_count}")
        
        if retry_delay is not None:
            self.websocket_retry_delay = retry_delay
            logger.info(f"🔧 WebSocket重试延迟: {retry_delay}秒")
    
    def configure_fallback(self, 
                         enabled: bool = None,
                         max_errors: int = None,
                         recovery_interval: int = None) -> None:
        """
        配置回退策略参数
        Configure fallback strategy parameters
        
        Args:
            enabled: 是否启用回退 / Whether to enable fallback
            max_errors: 最大错误次数 / Maximum error count
            recovery_interval: 恢复检查间隔 / Recovery check interval
        """
        if enabled is not None:
            self.fallback_enabled = enabled
            logger.info(f"🔧 回退策略启用状态: {enabled}")
        
        if max_errors is not None:
            self.max_websocket_errors = max_errors
            logger.info(f"🔧 最大WebSocket错误次数: {max_errors}")
        
        if recovery_interval is not None:
            self.websocket_recovery_interval = recovery_interval
            logger.info(f"🔧 WebSocket恢复检查间隔: {recovery_interval}秒")
    
    # ==================== 健康检查 Health Check ====================
    
    async def health_check(self) -> Dict[str, Any]:
        """
        执行健康检查
        Perform health check
        
        Returns:
            Dict[str, Any]: 健康状态信息 / Health status information
        """
        health_status = {
            'overall_status': 'healthy',
            'is_initialized': self.is_initialized,
            'websocket_status': 'unknown',
            'rest_api_status': 'unknown',
            'issues': [],
            'timestamp': datetime.now()
        }
        
        # 检查WebSocket状态
        if self.is_websocket_enabled:
            if await self._check_websocket_health():
                health_status['websocket_status'] = 'healthy'
            else:
                health_status['websocket_status'] = 'unhealthy'
                health_status['issues'].append('WebSocket连接不健康')
                health_status['overall_status'] = 'degraded'
        else:
            health_status['websocket_status'] = 'disabled'
        
        # 检查REST API状态（子类可以重写此方法）
        try:
            await self._check_rest_api_health()
            health_status['rest_api_status'] = 'healthy'
        except Exception as e:
            health_status['rest_api_status'] = 'unhealthy'
            health_status['issues'].append(f'REST API不可用: {e}')
            
            # 如果WebSocket也不可用，则整体状态为不健康
            if health_status['websocket_status'] != 'healthy':
                health_status['overall_status'] = 'unhealthy'
        
        return health_status
    
    async def _check_rest_api_health(self) -> None:
        """
        检查REST API健康状态（子类可重写）
        Check REST API health (can be overridden by subclasses)
        """
        # 默认实现，子类可以重写以实现具体的健康检查
