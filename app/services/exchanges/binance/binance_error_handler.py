# -*- coding: utf-8 -*-
"""
币安错误处理器
Binance Error Handler - 专门处理币安交易所的错误和重试机制
"""

import asyncio
from typing import Dict, Any, Callable
from datetime import datetime
from enum import Enum

from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


class BinanceErrorType(Enum):
    """币安错误类型枚举"""
    RATE_LIMIT = "rate_limit"           # 频率限制
    CONNECTION_ERROR = "connection"      # 连接错误
    API_ERROR = "api_error"             # API错误
    WEBSOCKET_ERROR = "websocket"       # WebSocket错误
    TIMEOUT_ERROR = "timeout"           # 超时错误
    AUTHENTICATION_ERROR = "auth"       # 认证错误
    INSUFFICIENT_BALANCE = "balance"    # 余额不足
    INVALID_SYMBOL = "symbol"           # 无效交易对
    ORDER_ERROR = "order"               # 订单错误
    UNKNOWN_ERROR = "unknown"           # 未知错误


class BinanceErrorHandler:
    """
    币安错误处理器
    Binance Error Handler
    
    提供币安交易所特定的错误处理和重试机制
    """
    
    def __init__(self):
        # 错误统计
        self.error_counts: Dict[str, int] = {}
        self.last_error_time: Dict[str, datetime] = {}
        
        # 重试配置
        self.max_retries = {
            BinanceErrorType.RATE_LIMIT: 5,
            BinanceErrorType.CONNECTION_ERROR: 3,
            BinanceErrorType.API_ERROR: 2,
            BinanceErrorType.WEBSOCKET_ERROR: 3,
            BinanceErrorType.TIMEOUT_ERROR: 3,
            BinanceErrorType.AUTHENTICATION_ERROR: 1,
            BinanceErrorType.INSUFFICIENT_BALANCE: 0,
            BinanceErrorType.INVALID_SYMBOL: 0,
            BinanceErrorType.ORDER_ERROR: 1,
            BinanceErrorType.UNKNOWN_ERROR: 2
        }
        
        # 重试延迟配置（秒）
        self.retry_delays = {
            BinanceErrorType.RATE_LIMIT: [2, 5, 10, 20, 30],
            BinanceErrorType.CONNECTION_ERROR: [1, 2, 4],
            BinanceErrorType.API_ERROR: [1, 3],
            BinanceErrorType.WEBSOCKET_ERROR: [2, 5, 10],
            BinanceErrorType.TIMEOUT_ERROR: [1, 2, 4],
            BinanceErrorType.AUTHENTICATION_ERROR: [0],
            BinanceErrorType.INSUFFICIENT_BALANCE: [0],
            BinanceErrorType.INVALID_SYMBOL: [0],
            BinanceErrorType.ORDER_ERROR: [1],
            BinanceErrorType.UNKNOWN_ERROR: [1, 3]
        }
        
        # 错误恢复策略
        self.recovery_strategies: Dict[BinanceErrorType, Callable] = {
            BinanceErrorType.RATE_LIMIT: self._handle_rate_limit,
            BinanceErrorType.CONNECTION_ERROR: self._handle_connection_error,
            BinanceErrorType.WEBSOCKET_ERROR: self._handle_websocket_error,
            BinanceErrorType.TIMEOUT_ERROR: self._handle_timeout_error
        }
        
        logger.info("🛡️ 币安错误处理器初始化完成")
    
    def classify_error(self, error: Exception, response_data: Dict[str, Any] = None) -> BinanceErrorType:
        """
        分类错误类型
        Classify error type
        
        Args:
            error: 异常对象
            response_data: 响应数据（如果有）
            
        Returns:
            BinanceErrorType: 错误类型
        """
        try:
            error_msg = str(error).lower()
            
            # 检查响应数据中的错误码
            if response_data:
                error_code = response_data.get('code', 0)
                
                # 币安特定错误码
                if error_code == -1003:  # Too many requests
                    return BinanceErrorType.RATE_LIMIT
                elif error_code == -1021:  # Timestamp outside of recvWindow
                    return BinanceErrorType.AUTHENTICATION_ERROR
                elif error_code == -2010:  # Insufficient balance
                    return BinanceErrorType.INSUFFICIENT_BALANCE
                elif error_code == -1121:  # Invalid symbol
                    return BinanceErrorType.INVALID_SYMBOL
                elif error_code in [-2013, -2014, -2015]:  # Order errors
                    return BinanceErrorType.ORDER_ERROR
            
            # 基于异常类型和消息分类
            if 'timeout' in error_msg or 'timed out' in error_msg:
                return BinanceErrorType.TIMEOUT_ERROR
            elif 'rate limit' in error_msg or '429' in error_msg:
                return BinanceErrorType.RATE_LIMIT
            elif 'connection' in error_msg or 'network' in error_msg:
                return BinanceErrorType.CONNECTION_ERROR
            elif 'websocket' in error_msg or 'ws' in error_msg:
                return BinanceErrorType.WEBSOCKET_ERROR
            elif 'authentication' in error_msg or 'unauthorized' in error_msg:
                return BinanceErrorType.AUTHENTICATION_ERROR
            elif 'balance' in error_msg or 'insufficient' in error_msg:
                return BinanceErrorType.INSUFFICIENT_BALANCE
            elif 'symbol' in error_msg or 'invalid' in error_msg:
                return BinanceErrorType.INVALID_SYMBOL
            elif any(keyword in error_msg for keyword in ['api', 'request', 'response']):
                return BinanceErrorType.API_ERROR
            else:
                return BinanceErrorType.UNKNOWN_ERROR
                
        except Exception as e:
            logger.error(f"❌ 分类错误类型失败: {e}")
            return BinanceErrorType.UNKNOWN_ERROR    
   
    async def handle_error_with_retry(self, 
                                      operation_func: Callable,
                                      operation_name: str,
                                      *args, **kwargs) -> Any:
        """
        带重试机制的错误处理
        Error handling with retry mechanism
        
        Args:
            operation_func: 要执行的操作函数
            operation_name: 操作名称
            *args, **kwargs: 函数参数
            
        Returns:
            Any: 操作结果
        """
        last_error = None
        error_type = BinanceErrorType.UNKNOWN_ERROR
        
        # 获取最大重试次数
        max_attempts = self.max_retries.get(error_type, 2) + 1  # +1 for initial attempt
        
        for attempt in range(max_attempts):
            try:
                # 执行操作
                result = await operation_func(*args, **kwargs)
                
                # 成功时重置错误计数
                if attempt > 0:
                    logger.info(f"✅ 重试成功: {operation_name} (第{attempt}次重试)")
                    self._reset_error_count(operation_name)
                
                return result
                
            except Exception as error:
                last_error = error
                error_type = self.classify_error(error)
                
                # 更新错误统计
                self._update_error_stats(operation_name, error_type)
                
                # 检查是否应该重试
                if not self._should_retry(error_type, attempt, max_attempts - 1):
                    logger.error(f"❌ 操作失败，不再重试: {operation_name} - {error}")
                    break
                
                # 获取重试延迟
                delay = self._get_retry_delay(error_type, attempt)
                
                logger.warning(f"⚠️ 操作失败，{delay}秒后重试: {operation_name} (第{attempt + 1}次) - {error}")
                
                # 执行错误恢复策略
                await self._execute_recovery_strategy(error_type, error, operation_name)
                
                # 等待重试
                if delay > 0:
                    await asyncio.sleep(delay)
        
        # 所有重试都失败，抛出最后的错误
        if last_error:
            self._log_final_error(operation_name, error_type, last_error)
            raise self._convert_to_trading_tool_error(error_type, last_error, operation_name)
        
        raise TradingToolError(f"操作失败: {operation_name}")
    
    def _should_retry(self, error_type: BinanceErrorType, attempt: int, max_retries: int) -> bool:
        """
        判断是否应该重试
        Determine if should retry
        
        Args:
            error_type: 错误类型
            attempt: 当前尝试次数
            max_retries: 最大重试次数
            
        Returns:
            bool: 是否应该重试
        """
        # 检查重试次数
        if attempt >= max_retries:
            return False
        
        # 某些错误类型不应该重试
        non_retryable_errors = [
            BinanceErrorType.AUTHENTICATION_ERROR,
            BinanceErrorType.INSUFFICIENT_BALANCE,
            BinanceErrorType.INVALID_SYMBOL
        ]
        
        if error_type in non_retryable_errors:
            return False
        
        return True
    
    def _get_retry_delay(self, error_type: BinanceErrorType, attempt: int) -> float:
        """
        获取重试延迟时间
        Get retry delay time
        
        Args:
            error_type: 错误类型
            attempt: 当前尝试次数
            
        Returns:
            float: 延迟时间（秒）
        """
        delays = self.retry_delays.get(error_type, [1, 2, 4])
        
        if attempt < len(delays):
            return delays[attempt]
        else:
            # 指数退避，最大30秒
            return min(2 ** attempt, 30)
    
    def _update_error_stats(self, operation_name: str, error_type: BinanceErrorType) -> None:
        """
        更新错误统计
        Update error statistics
        
        Args:
            operation_name: 操作名称
            error_type: 错误类型
        """
        key = f"{operation_name}_{error_type.value}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        self.last_error_time[key] = datetime.now()
    
    def _reset_error_count(self, operation_name: str) -> None:
        """
        重置错误计数
        Reset error count
        
        Args:
            operation_name: 操作名称
        """
        keys_to_reset = [key for key in self.error_counts.keys() if key.startswith(operation_name)]
        for key in keys_to_reset:
            self.error_counts[key] = 0
    
    async def _execute_recovery_strategy(self, 
                                       error_type: BinanceErrorType, 
                                       error: Exception, 
                                       operation_name: str) -> None:
        """
        执行错误恢复策略
        Execute error recovery strategy
        
        Args:
            error_type: 错误类型
            error: 异常对象
            operation_name: 操作名称
        """
        try:
            recovery_func = self.recovery_strategies.get(error_type)
            if recovery_func:
                await recovery_func(error, operation_name)
        except Exception as e:
            logger.error(f"❌ 执行恢复策略失败: {e}")
    
    # 错误恢复策略实现
    async def _handle_rate_limit(self, error: Exception, operation_name: str) -> None:
        """处理频率限制错误"""
        logger.warning(f"🚦 触发频率限制: {operation_name}")
        # 可以在这里实现更复杂的频率控制逻辑
    
    async def _handle_connection_error(self, error: Exception, operation_name: str) -> None:
        """处理连接错误"""
        logger.warning(f"🔌 连接错误: {operation_name}")
        # 可以在这里实现连接重建逻辑
    
    async def _handle_websocket_error(self, error: Exception, operation_name: str) -> None:
        """处理WebSocket错误"""
        logger.warning(f"📡 WebSocket错误: {operation_name}")
        # 可以在这里实现WebSocket重连逻辑
    
    async def _handle_timeout_error(self, error: Exception, operation_name: str) -> None:
        """处理超时错误"""
        logger.warning(f"⏰ 超时错误: {operation_name}")
        # 可以在这里实现超时处理逻辑 
   
    def _convert_to_trading_tool_error(self, 
                                     error_type: BinanceErrorType, 
                                     original_error: Exception, 
                                     operation_name: str) -> TradingToolError:
        """
        转换为统一的交易工具错误
        Convert to unified trading tool error
        
        Args:
            error_type: 错误类型
            original_error: 原始异常
            operation_name: 操作名称
            
        Returns:
            TradingToolError: 统一的交易工具错误
        """
        error_messages = {
            BinanceErrorType.RATE_LIMIT: "币安API频率限制，请稍后重试",
            BinanceErrorType.CONNECTION_ERROR: "币安连接失败，请检查网络",
            BinanceErrorType.API_ERROR: "币安API错误",
            BinanceErrorType.WEBSOCKET_ERROR: "币安WebSocket连接错误",
            BinanceErrorType.TIMEOUT_ERROR: "币安请求超时",
            BinanceErrorType.AUTHENTICATION_ERROR: "币安认证失败，请检查API密钥",
            BinanceErrorType.INSUFFICIENT_BALANCE: "账户余额不足",
            BinanceErrorType.INVALID_SYMBOL: "无效的交易对",
            BinanceErrorType.ORDER_ERROR: "订单操作失败",
            BinanceErrorType.UNKNOWN_ERROR: "币安未知错误"
        }
        
        message = error_messages.get(error_type, "币安操作失败")
        
        return TradingToolError(
            message=f"{message}: {operation_name}",
            error_code=f"BINANCE_{error_type.value.upper()}",
            details={
                'operation': operation_name,
                'error_type': error_type.value,
                'original_error': str(original_error),
                'timestamp': datetime.now().isoformat()
            }
        )
    
    def _log_final_error(self, operation_name: str, error_type: BinanceErrorType, error: Exception) -> None:
        """
        记录最终错误日志
        Log final error
        
        Args:
            operation_name: 操作名称
            error_type: 错误类型
            error: 异常对象
        """
        logger.error(
            f"❌ 币安操作最终失败: {operation_name}",
            extra={
                'operation': operation_name,
                'error_type': error_type.value,
                'error_message': str(error),
                'error_count': self.error_counts.get(f"{operation_name}_{error_type.value}", 0),
                'timestamp': datetime.now().isoformat()
            }
        )
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        获取错误统计信息
        Get error statistics
        
        Returns:
            Dict[str, Any]: 错误统计信息
        """
        return {
            'error_counts': self.error_counts.copy(),
            'last_error_times': {
                key: time.isoformat() for key, time in self.last_error_time.items()
            },
            'total_errors': sum(self.error_counts.values()),
            'last_update': datetime.now().isoformat()
        }
    
    def reset_statistics(self) -> None:
        """
        重置错误统计
        Reset error statistics
        """
        self.error_counts.clear()
        self.last_error_time.clear()
        logger.info("📊 币安错误统计已重置")
    
    def is_error_rate_high(self, operation_name: str, threshold: int = 10, 
                          time_window: int = 300) -> bool:
        """
        检查错误率是否过高
        Check if error rate is high
        
        Args:
            operation_name: 操作名称
            threshold: 错误次数阈值
            time_window: 时间窗口（秒）
            
        Returns:
            bool: 错误率是否过高
        """
        try:
            now = datetime.now()
            total_errors = 0
            
            for key, count in self.error_counts.items():
                if key.startswith(operation_name):
                    last_error_time = self.last_error_time.get(key)
                    if last_error_time and (now - last_error_time).total_seconds() <= time_window:
                        total_errors += count
            
            return total_errors >= threshold
            
        except Exception as e:
            logger.error(f"❌ 检查错误率失败: {e}")
            return False


# 全局错误处理器实例
_binance_error_handler = None


def get_binance_error_handler() -> BinanceErrorHandler:
    """
    获取币安错误处理器实例
    Get Binance error handler instance
    
    Returns:
        BinanceErrorHandler: 错误处理器实例
    """
    global _binance_error_handler
    
    if _binance_error_handler is None:
        _binance_error_handler = BinanceErrorHandler()
    
    return _binance_error_handler


# 装饰器：自动错误处理和重试
def binance_retry(operation_name: str = None):
    """
    币安重试装饰器
    Binance retry decorator
    
    Args:
        operation_name: 操作名称
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            error_handler = get_binance_error_handler()
            op_name = operation_name or func.__name__
            
            return await error_handler.handle_error_with_retry(
                func, op_name, *args, **kwargs
            )
        
        return wrapper
    return decorator