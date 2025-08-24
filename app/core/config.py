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
    
    # OKX API配置
    okx_api_key: str = Field(default="", description="OKX API Key")
    okx_secret_key: str = Field(default="", description="OKX Secret Key")
    okx_passphrase: str = Field(default="", description="OKX API Passphrase")
    okx_sandbox: bool = Field(default=False, description="是否使用OKX沙盒环境")
    okx_base_url: str = Field(default="https://www.okx.com", description="OKX API基础URL")
    
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
    
    # 监控参数配置 - 针对数字货币高波动性优化
    open_interest_threshold: float = Field(default=1.03, description="持仓量变化阈值(降低以捕捉更多信号)")
    volume_multiplier: float = Field(default=2.5, description="成交量异常倍数(降低以提高敏感度)")
    funding_rate_interval: int = Field(default=120, description="费率监控间隔(分钟) - 优化为2小时")
    trend_analysis_interval: int = Field(default=5, description="趋势分析间隔(分钟) - 优化为5分钟")
    open_interest_interval: int = Field(default=3, description="持仓量监控间隔(分钟) - 优化为3分钟")
    volume_monitor_interval: int = Field(default=15, description="交易量监控间隔(分钟) - 优化为15分钟")
    position_analysis_interval: int = Field(default=30, description="持仓分析间隔(分钟) - 优化为30分钟")
    grid_opportunities_interval: int = Field(default=60, description="网格机会分析间隔(分钟) - 优化为1小时")
    market_opportunities_interval: int = Field(default=120, description="市场机会分析间隔(分钟) - 优化为2小时")
    
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
            'negative_threshold': -0.001,  # -0.1% 阈值，只推送更显著的负费率
            'high_threshold': 0.1
        }
    }, description="策略参数配置")
    
    # Kronos预测模型配置 - 专门分析ETH和SOL
    kronos_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_kronos_prediction': True,
        'model_name': 'NeoQuasar/Kronos-small',  # 默认使用small模型
        'tokenizer_name': 'NeoQuasar/Kronos-Tokenizer-base',
        'max_context': 512,  # Kronos-small和base的最大上下文长度
        'lookback_periods': 200,  # 历史数据回看期数
        'prediction_horizon': 24,  # 预测未来24小时
        'sampling_params': {
            'temperature': 0.8,
            'top_p': 0.9,
            'sample_count': 5  # 生成5个预测样本取平均
        },
        'confidence_threshold': 0.5,  # 降低预测置信度阈值
        'update_interval_minutes': 30,  # 预测更新间隔
        'cache_predictions': True,
        'use_gpu': True,  # 如果有GPU则使用
        # 专注ETH和SOL的分析配置
        'target_symbols': ['ETH-USDT-SWAP', 'SOL-USDT-SWAP'],  # 只分析这两个币种
        'enhanced_analysis': True,  # 对目标币种进行增强分析
        # 强信号通知配置
        'notification_config': {
            'enable_strong_signal_notification': True,  # 启用强信号通知
            'strong_signal_threshold': 0.55,  # 强信号阈值 - 降低以捕获更多机会
            'medium_signal_threshold': 0.45,   # 中等信号阈值 - 相应降低
            'notification_channels': ['feishu', 'wechat'],  # 通知渠道
            'notification_priority': 'high',  # 通知优先级
            'batch_notification': True,       # 批量通知
            'max_notifications_per_hour': 10  # 每小时最大通知数
        }
    }, description="Kronos金融预测模型配置 - 专门分析ETH和SOL，对账户已有持仓和负费率币种提供买入建议")
    
    # 机器学习增强配置 - 针对高波动性优化，提高信号敏感度
    ml_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_ml_prediction': True,
        'enable_anomaly_detection': True,
        'enable_adaptive_optimization': True,
        'enable_kronos_integration': True,  # 启用Kronos集成
        'prediction_model': {
            'model_type': 'gradient_boosting',  # 对高波动性更敏感
            'lookback_periods': 24,  # 进一步减少以适应快速变化
            'prediction_horizon': 2,  # 缩短预测期间到2小时
            'retrain_interval_hours': 8,  # 更频繁重训练
            'min_accuracy_threshold': 0.60,  # 降低准确度要求以提高敏感度
            'signal_threshold': {
                'strong_buy': 0.65,  # 65%强买入阈值
                'buy': 0.55,         # 降低买入阈值
                'sell': 0.55,        # 降低卖出阈值
                'strong_sell': 0.65  # 65%强卖出阈值
            }
        },
        'anomaly_detection': {
            'algorithm': 'isolation_forest',
            'contamination': 0.20,  # 进一步增加以捕捉更多异常
            'sensitivity': 0.95,    # 最大化敏感度
            'min_samples': 30       # 进一步减少样本要求
        },
        'adaptive_optimization': {
            'enable_parameter_tuning': True,
            'optimization_interval_hours': 4,  # 更频繁的参数优化
            'performance_window_days': 2,      # 进一步缩短评估窗口
            'min_improvement_threshold': 0.02  # 进一步降低改进阈值
        },
        'feature_engineering': {
            'technical_indicators': True,
            'price_patterns': True,
            'volume_features': True,
            'market_microstructure': True,
            'volatility_clustering': True,
            'momentum_features': True,
            'price_acceleration': True,  # 新增价格加速度特征
            'volume_price_trend': True   # 新增量价趋势特征
        },
        # 高频监控配置 - 提高响应速度
        'high_frequency_mode': {
            'enable': True,
            'signal_update_seconds': 15,  # 15秒更新一次信号
            'volatility_threshold': 0.03, # 降低到3%波动率阈值
            'emergency_stop_loss': 0.06,  # 6%紧急止损
            'momentum_threshold': 0.02    # 2%动量阈值
        }
    }, description="机器学习增强配置 - 高敏感度优化，专为捕捉ETH和SOL高波动币种信号")
    
    # 主要监控币种配置 - 只分析ETH和SOL，使用Kronos进行深度分析
    monitored_symbols: List[str] = Field(default=[
        'ETH-USDT-SWAP',
        'SOL-USDT-SWAP'
    ], description="主要监控的交易对列表 - 只分析ETH和SOL，使用Kronos进行深度分析和交易决策")
    
    # 费率监控币种配置 - 其他币种只监控负费率买入机会
    funding_rate_only_symbols: List[str] = Field(default=[
        'BTC-USDT-SWAP',
        'BNB-USDT-SWAP',
        'ADA-USDT-SWAP',
        'DOT-USDT-SWAP',
        'AVAX-USDT-SWAP',
        'ATOM-USDT-SWAP',
        'NEAR-USDT-SWAP',
        'ALGO-USDT-SWAP',
        'LINK-USDT-SWAP',
        'UNI-USDT-SWAP',
        'SUSHI-USDT-SWAP',
        'CRV-USDT-SWAP',
        'COMP-USDT-SWAP',
        'MKR-USDT-SWAP',
        'OP-USDT-SWAP',
        'ARB-USDT-SWAP',
        'SHIB-USDT-SWAP',
        'APT-USDT-SWAP',
        'SUI-USDT-SWAP',
        'FIL-USDT-SWAP',
        'AR-USDT-SWAP',
        'STORJ-USDT-SWAP',
        'AXS-USDT-SWAP',
        'SAND-USDT-SWAP',
        'MANA-USDT-SWAP',
        'LTC-USDT-SWAP',
        'BCH-USDT-SWAP',
        'ETC-USDT-SWAP',
        'XRP-USDT-SWAP',
        'DOGE-USDT-SWAP'
    ], description="费率监控币种列表 - 只监控负费率买入机会，不进行完整技术分析")
    
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
    def okx_config(self) -> dict:
        """获取OKX API配置"""
        return {
            "api_key": self.okx_api_key,
            "secret_key": self.okx_secret_key,
            "passphrase": self.okx_passphrase,
            "sandbox": self.okx_sandbox,
            "base_url": self.okx_base_url,
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
                "position_analysis": self.position_analysis_interval,
                "grid_opportunities": self.grid_opportunities_interval,
                "market_opportunities": self.market_opportunities_interval,
            }
        }


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings
