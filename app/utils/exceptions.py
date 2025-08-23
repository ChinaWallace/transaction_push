# -*- coding: utf-8 -*-
"""
自定义异常类
Custom exception classes
"""


class TradingToolError(Exception):
    """交易工具基础异常"""
    pass


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
    pass


class IndicatorCalculationError(TradingToolError):
    """技术指标计算异常"""
    pass


class NotificationError(TradingToolError):
    """通知发送异常"""
    
    def __init__(self, message: str, channel: str = None):
        super().__init__(message)
        self.channel = channel


class ConfigurationError(TradingToolError):
    """配置错误异常"""
    pass


class DatabaseError(TradingToolError):
    """数据库异常"""
    pass


class ValidationError(TradingToolError):
    """数据验证异常"""
    pass


class MonitorError(TradingToolError):
    """监控服务异常"""
    pass


class SchedulerError(TradingToolError):
    """调度器异常"""
    pass


class MLModelError(TradingToolError):
    """机器学习模型异常"""
    
    def __init__(self, message: str, model_type: str = None):
        super().__init__(message)
        self.model_type = model_type


class ModelTrainingError(MLModelError):
    """模型训练异常"""
    pass


class PredictionError(MLModelError):
    """预测异常"""
    pass


class AnomalyDetectionError(MLModelError):
    """异常检测异常"""
    pass


class ServiceUnavailableError(TradingToolError):
    """服务不可用异常"""
    pass


class InternalServerError(TradingToolError):
    """内部服务器错误"""
    pass
