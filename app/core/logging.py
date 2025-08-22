# -*- coding: utf-8 -*-
"""
日志配置管理
Logging configuration management
"""

import sys
import os
from loguru import logger
from typing import Dict, Any
import json
from datetime import datetime

from app.core.config import get_settings

settings = get_settings()


class LoggerConfig:
    """日志配置类"""
    
    def __init__(self):
        self.settings = settings
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


# 延迟初始化，避免导入时配置问题
_logger_config = None
_trading_logger = None
_monitor_logger = None

def _ensure_logger_configured():
    """确保日志已配置"""
    global _logger_config, _trading_logger, _monitor_logger
    if _logger_config is None:
        _logger_config = LoggerConfig()
        _trading_logger = get_trading_logger()
        _monitor_logger = get_monitor_logger()
        
        # 设置应用启动日志
        logger.info(f"Application starting with log level: {settings.log_level}")
        logger.info(f"Log format: {settings.log_format}")
        logger.info(f"Log path: {settings.log_path}")

def get_trading_logger_instance():
    """获取交易日志器实例"""
    _ensure_logger_configured()
    return _trading_logger

def get_monitor_logger_instance():
    """获取监控日志器实例"""
    _ensure_logger_configured() 
    return _monitor_logger

# 为了向后兼容，恢复 trading_logger 和 monitor_logger 导出
def _get_trading_logger_lazy():
    """延迟获取交易日志器"""
    return get_trading_logger_instance()

def _get_monitor_logger_lazy():
    """延迟获取监控日志器"""
    return get_monitor_logger_instance()

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
