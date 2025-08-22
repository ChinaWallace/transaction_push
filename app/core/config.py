# -*- coding: utf-8 -*-
"""
应用配置管理
Configuration management for the trading analysis tool
"""

from typing import Optional, Dict, Any, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator
import os


class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用基础配置
    app_name: str = Field(default="Python Trading Tool", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    debug: bool = Field(default=False, description="调试模式")
    log_level: str = Field(default="INFO", description="日志级别")
    
    # 服务配置
    host: str = Field(default="0.0.0.0", description="服务主机")
    port: int = Field(default=8000, description="服务端口")
    
    # 数据库配置
    database_url: str = Field(default="mysql+pymysql://root:8964@localhost:3306/trading_db", description="数据库连接URL")
    database_echo: bool = Field(default=False, description="数据库SQL日志")
    
    # 币安API配置
    binance_api_key: str = Field(default="test_key", description="币安API Key")
    binance_secret_key: str = Field(default="test_secret", description="币安Secret Key")
    binance_testnet: bool = Field(default=False, description="是否使用测试网")
    binance_base_url: str = Field(default="https://fapi.binance.com", description="币安API基础URL")
    
    # Redis配置
    redis_url: Optional[str] = Field(default=None, description="Redis连接URL")
    
    # 代理配置
    proxy_url: Optional[str] = Field(default=None, description="HTTP代理URL (如: http://127.0.0.1:7890)")
    proxy_enabled: bool = Field(default=False, description="是否启用代理")
    
    # 通知推送配置
    feishu_webhook_url: Optional[str] = Field(default=None, description="飞书Webhook URL")
    wechat_webhook_url: Optional[str] = Field(default=None, description="企业微信Webhook URL")
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram Bot Token")
    telegram_chat_id: Optional[str] = Field(default=None, description="Telegram Chat ID")
    
    # 邮件配置
    smtp_host: Optional[str] = Field(default=None, description="SMTP服务器")
    smtp_port: int = Field(default=587, description="SMTP端口")
    smtp_user: Optional[str] = Field(default=None, description="SMTP用户名")
    smtp_password: Optional[str] = Field(default=None, description="SMTP密码")
    smtp_from: Optional[str] = Field(default=None, description="发件人地址")
    
    # 监控参数配置
    open_interest_threshold: float = Field(default=1.05, description="持仓量变化阈值")
    volume_multiplier: float = Field(default=3.0, description="成交量异常倍数")
    funding_rate_interval: int = Field(default=240, description="费率监控间隔(分钟)")
    trend_analysis_interval: int = Field(default=15, description="趋势分析间隔(分钟)")
    open_interest_interval: int = Field(default=5, description="持仓量监控间隔(分钟)")
    volume_monitor_interval: int = Field(default=60, description="交易量监控间隔(分钟)")
    
    # 策略配置
    strategy_config: Dict[str, Any] = Field(default_factory=lambda: {
        'supertrend': {
            'period': 10,
            'multiplier': 3.0,
            'timeframes': ['1d', '4h', '1h', '15m']
        },
        'volume': {
            'threshold_multiplier': 3.0,
            'consecutive_periods': 3
        },
        'funding_rate': {
            'negative_threshold': -0.01,
            'high_threshold': 0.1
        }
    }, description="策略参数配置")
    
    # 机器学习增强配置
    ml_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_ml_prediction': True,
        'enable_anomaly_detection': True,
        'enable_adaptive_optimization': True,
        'prediction_model': {
            'model_type': 'random_forest',  # random_forest, gradient_boosting, svm
            'lookback_periods': 50,
            'prediction_horizon': 5,
            'retrain_interval_hours': 24,
            'min_accuracy_threshold': 0.6
        },
        'anomaly_detection': {
            'algorithm': 'isolation_forest',  # isolation_forest, one_class_svm, local_outlier_factor
            'contamination': 0.1,
            'sensitivity': 0.8,
            'min_samples': 100
        },
        'adaptive_optimization': {
            'enable_parameter_tuning': True,
            'optimization_interval_hours': 12,
            'performance_window_days': 7,
            'min_improvement_threshold': 0.05
        },
        'feature_engineering': {
            'technical_indicators': True,
            'price_patterns': True,
            'volume_features': True,
            'market_microstructure': True
        }
    }, description="机器学习增强配置")
    
    # 监控币种配置
    monitored_symbols: List[str] = Field(default=[
        'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', 'XRPUSDT'
    ], description="监控的交易对列表")
    
    # TradingView集成配置
    tradingview_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_pine_indicators': True,
        'enable_volume_profile': True,
        'enable_order_flow': False,
        'chart_timeframes': ['1m', '5m', '15m', '1h', '4h', '1d']
    }, description="TradingView功能配置")
    
    # 数据缓存配置
    cache_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_cache': True,
        'cache_ttl_minutes': 5,
        'max_cache_size_mb': 100,
        'cache_compression': True
    }, description="数据缓存配置")
    
    # 数据保留配置
    data_retention_days: int = Field(default=30, description="数据保留天数")
    
    # 任务调度配置
    scheduler_timezone: str = Field(default="Asia/Shanghai", description="调度器时区")
    
    # 安全配置
    secret_key: str = Field(default="test_secret_key", description="应用密钥")
    access_token_expire_minutes: int = Field(default=30, description="访问令牌过期时间")
    
    # 限流配置
    rate_limit_per_minute: int = Field(default=60, description="每分钟请求限制")
    
    # 日志配置
    log_format: str = Field(default="text", description="日志格式")
    log_rotation: str = Field(default="1 day", description="日志轮转")
    log_retention: str = Field(default="30 days", description="日志保留")
    log_path: str = Field(default="logs/", description="日志路径")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,  # 忽略空的env文件
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @validator("log_level")
    def validate_log_level(cls, v):
        """验证日志级别"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()
    
    @validator("log_path")
    def validate_log_path(cls, v):
        """验证日志路径"""
        if not os.path.exists(v):
            os.makedirs(v, exist_ok=True)
        return v
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.debug
    
    @property
    def database_config(self) -> dict:
        """获取数据库配置"""
        return {
            "url": self.database_url,
            "echo": self.database_echo,
        }
    
    @property
    def binance_config(self) -> dict:
        """获取币安API配置"""
        return {
            "api_key": self.binance_api_key,
            "secret_key": self.binance_secret_key,
            "testnet": self.binance_testnet,
            "base_url": self.binance_base_url,
        }
    
    @property
    def notification_config(self) -> dict:
        """获取通知配置"""
        return {
            "feishu": {
                "webhook_url": self.feishu_webhook_url,
                "enabled": bool(self.feishu_webhook_url)
            },
            "wechat": {
                "webhook_url": self.wechat_webhook_url,
                "enabled": bool(self.wechat_webhook_url)
            },
            "telegram": {
                "bot_token": self.telegram_bot_token,
                "chat_id": self.telegram_chat_id,
                "enabled": bool(self.telegram_bot_token and self.telegram_chat_id)
            },
            "email": {
                "smtp_host": self.smtp_host,
                "smtp_port": self.smtp_port,
                "smtp_user": self.smtp_user,
                "smtp_password": self.smtp_password,
                "smtp_from": self.smtp_from,
                "enabled": bool(self.smtp_host and self.smtp_user and self.smtp_password)
            }
        }
    
    @property
    def monitor_config(self) -> dict:
        """获取监控配置"""
        return {
            "open_interest_threshold": self.open_interest_threshold,
            "volume_multiplier": self.volume_multiplier,
            "intervals": {
                "funding_rate": self.funding_rate_interval,
                "trend_analysis": self.trend_analysis_interval,
                "open_interest": self.open_interest_interval,
                "volume_monitor": self.volume_monitor_interval,
            }
        }


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings
