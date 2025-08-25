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
    
    # 数据库连接池配置
    db_pool_size: int = Field(default=20, description="数据库连接池大小")
    db_max_overflow: int = Field(default=30, description="数据库连接池最大溢出数")
    db_pool_timeout: int = Field(default=30, description="获取连接超时时间(秒)")
    db_pool_recycle: int = Field(default=3600, description="连接回收时间(秒)")
    db_pool_pre_ping: bool = Field(default=True, description="连接前ping检查")
    db_connect_timeout: int = Field(default=10, description="数据库连接超时(秒)")
    db_read_timeout: int = Field(default=30, description="数据库读取超时(秒)")
    db_write_timeout: int = Field(default=30, description="数据库写入超时(秒)")
    
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
    
    # HTTP连接池配置
    http_pool_limit: int = Field(default=200, description="HTTP连接池总大小")
    http_pool_limit_per_host: int = Field(default=50, description="每个主机的连接数限制")
    http_keepalive_timeout: int = Field(default=60, description="HTTP连接保持时间(秒)")
    http_connect_timeout: int = Field(default=10, description="HTTP连接超时(秒)")
    http_read_timeout: int = Field(default=30, description="HTTP读取超时(秒)")
    http_total_timeout: int = Field(default=60, description="HTTP总超时(秒)")
    http_dns_cache_ttl: int = Field(default=300, description="DNS缓存时间(秒)")
    http_max_retries: int = Field(default=3, description="HTTP请求最大重试次数")
    
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
    
    # Kronos预测模型配置 - 专门分析ETH和SOL，增加收益机会扫描
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
        'confidence_threshold': 0.35,  # 大幅降低阈值，抓住更多机会
        'update_interval_minutes': 15,  # 缩短更新间隔到15分钟
        'cache_predictions': True,
        'use_gpu': True,  # 如果有GPU则使用
        # 专注ETH和SOL的分析配置
        'target_symbols': ['ETH-USDT-SWAP', 'SOL-USDT-SWAP'],  # 只分析这两个币种
        'enhanced_analysis': True,  # 对目标币种进行增强分析
        # 强制只推送Kronos分析的信号
        'strict_kronos_only': True,  # 严格模式：只推送经过Kronos分析的信号
        'disable_traditional_signals': True,  # 禁用传统技术分析信号推送
        # 强信号通知配置 - 币圈优化
        'notification_config': {
            'enable_strong_signal_notification': True,  # 启用强信号通知
            'strong_signal_threshold': 0.4,   # 大幅降低强信号阈值
            'medium_signal_threshold': 0.3,   # 大幅降低中等信号阈值
            'notification_channels': ['feishu', 'wechat'],  # 通知渠道
            'notification_priority': 'high',  # 通知优先级
            'batch_notification': False,      # 关闭批量通知，立即推送
            'enable_immediate_alerts': True,  # 启用立即告警
            'profit_opportunity_threshold': 3.0,  # 预期收益3%以上立即通知
            'require_kronos_validation': True  # 要求所有信号都必须经过Kronos验证
        },
        # 市场机会扫描配置 - 增强版
        'market_scan_config': {
            'enable_market_scan': True,  # 启用市场机会扫描
            'enable_profit_scan': True,  # 启用收益机会扫描
            'strong_signal_threshold': 0.45,  # 大幅降低强信号扫描阈值
            'profit_opportunity_threshold': 5.0,  # 收益机会阈值5%
            'scan_intervals': {
                'strong_signal_minutes': 10,  # 强信号扫描间隔缩短到10分钟
                'profit_scan_minutes': 5,     # 收益机会扫描5分钟一次
                'grid_trading_hours': 1       # 网格交易扫描间隔缩短到1小时
            },
            'top_volume_limit': 100,  # 扫描交易量前100的币种
            'notification_config': {
                'enable_opportunity_notifications': True,
                'max_opportunities_per_notification': 3,  # 减少到3个，提高质量
                'priority_mapping': {
                    'strong_signal': 'high',
                    'profit_opportunity': 'urgent',  # 收益机会最高优先级
                    'grid_trading': 'medium'
                },
                'auto_notify_high_return': True,  # 自动推送高收益机会
                'high_return_threshold': 8.0     # 8%以上收益自动推送
            }
        }
    }, description="Kronos金融预测模型配置 - 专门分析ETH和SOL，增强收益机会扫描，币圈高频交易优化")
    
    # 机器学习增强配置 - 与Kronos协同工作，专注异常检测和特征工程
    ml_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_ml_prediction': True,  # 保留ML预测作为Kronos的补充
        'enable_anomaly_detection': True,  # 重点：异常检测
        'enable_adaptive_optimization': False,  # 关闭：避免与Kronos冲突
        'enable_kronos_integration': True,  # 启用与Kronos的深度集成
        'ml_role': 'assistant',  # ML作为Kronos的助手，而非主要预测器
        'prediction_model': {
            'model_type': 'random_forest',  # 轻量级模型，专注特征重要性分析
            'lookback_periods': 48,  # 更长历史用于异常检测
            'prediction_horizon': 1,  # 短期预测，主要用于验证Kronos
            'retrain_interval_hours': 24,  # 降低重训练频率
            'min_accuracy_threshold': 0.65,  # 提高准确度要求
            'signal_threshold': {
                'strong_buy': 0.75,  # 提高阈值，只在高确定性时发出信号
                'buy': 0.65,         
                'sell': 0.65,        
                'strong_sell': 0.75  
            }
        },
        'anomaly_detection': {
            'algorithm': 'isolation_forest',
            'contamination': 0.15,  # 适中的异常检测敏感度
            'sensitivity': 0.85,    # 平衡敏感度和准确性
            'min_samples': 50,      # 增加样本要求提高稳定性
            'focus_areas': ['volume_spike', 'price_gap', 'volatility_burst', 'funding_anomaly']
        },
        'kronos_integration': {
            'enable_signal_validation': True,  # 验证Kronos信号
            'enable_confidence_boost': True,   # 当ML和Kronos一致时提升置信度
            'enable_anomaly_alert': True,      # ML检测到异常时提醒Kronos重新预测
            'weight_in_ensemble': 0.25,       # ML在集成决策中的权重（Kronos占75%）
            'validation_threshold': 0.7       # ML验证Kronos信号的阈值
        },
        'feature_engineering': {
            'technical_indicators': True,
            'price_patterns': True,
            'volume_features': True,
            'market_microstructure': True,
            'volatility_clustering': True,
            'momentum_features': True,
            'price_acceleration': True,
            'volume_price_trend': True,
            'funding_rate_features': True,    # 新增：资金费率特征
            'order_book_features': False      # 暂时关闭：数据获取复杂
        },
        # 专注异常监控而非高频交易
        'anomaly_monitoring': {
            'enable': True,
            'check_interval_minutes': 5,      # 5分钟检查一次异常
            'alert_threshold': 0.8,           # 异常严重度阈值
            'auto_notify_kronos': True,       # 自动通知Kronos服务重新预测
            'emergency_threshold': 0.95       # 紧急异常阈值
        }
    }, description="机器学习增强配置 - 与Kronos协同工作，专注异常检测和信号验证，避免功能重复")
    
    # 主要监控币种配置 - 只分析ETH和SOL，使用Kronos进行深度分析
    monitored_symbols: List[str] = Field(default=[
        'ETH-USDT-SWAP',
        'SOL-USDT-SWAP'
    ], description="主要监控的交易对列表 - 只分析ETH和SOL，使用Kronos进行深度分析和交易决策")
    
    # 费率监控币种配置 - 扩展到更多币种，增加收益机会
    funding_rate_only_symbols: List[str] = Field(default=[
        # 主流币种
        'BTC-USDT-SWAP', 'BNB-USDT-SWAP', 'ADA-USDT-SWAP', 'DOT-USDT-SWAP',
        'AVAX-USDT-SWAP', 'ATOM-USDT-SWAP', 'NEAR-USDT-SWAP', 'ALGO-USDT-SWAP',
        'LINK-USDT-SWAP', 'UNI-USDT-SWAP', 'SUSHI-USDT-SWAP', 'CRV-USDT-SWAP',
        'COMP-USDT-SWAP', 'MKR-USDT-SWAP', 'OP-USDT-SWAP', 'ARB-USDT-SWAP',
        'LTC-USDT-SWAP', 'BCH-USDT-SWAP', 'ETC-USDT-SWAP', 'XRP-USDT-SWAP',
        'DOGE-USDT-SWAP',
        
        # 热门DeFi币种
        'AAVE-USDT-SWAP', 'SNX-USDT-SWAP', '1INCH-USDT-SWAP', 'YFI-USDT-SWAP',
        
        # Layer2和新兴币种
        'HBAR-USDT-SWAP', 'VET-USDT-SWAP', 'THETA-USDT-SWAP', 'ENJ-USDT-SWAP',
        
        # NFT和游戏币种
        'SHIB-USDT-SWAP', 'APT-USDT-SWAP', 'SUI-USDT-SWAP', 'AXS-USDT-SWAP',
        'SAND-USDT-SWAP', 'MANA-USDT-SWAP', 'GALA-USDT-SWAP', 'CHZ-USDT-SWAP',
        
        # 存储和基础设施
        'FIL-USDT-SWAP', 'AR-USDT-SWAP',
        
        # 新兴热门币种
        'PEPE-USDT-SWAP', 'FLOKI-USDT-SWAP', 'BONK-USDT-SWAP', 'WIF-USDT-SWAP',
        
        # AI和科技概念
        'FET-USDT-SWAP', 'OCEAN-USDT-SWAP',
        
        # 其他潜力币种
        'IMX-USDT-SWAP', 'GMT-USDT-SWAP', 'APE-USDT-SWAP',
        'DYDX-USDT-SWAP', 'GMX-USDT-SWAP'
    ], description="费率监控币种列表 - 扩展到70+币种，覆盖各个热门赛道，增加收益机会发现")
    
    # TradingView集成配置
    tradingview_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_pine_indicators': True,
        'enable_volume_profile': True,
        'enable_order_flow': False,
        'chart_timeframes': ['1m', '5m', '15m', '1h', '4h', '1d']
    }, description="TradingView功能配置")
    
    # 收益最大化策略配置 - 币圈专用
    profit_maximization_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_profit_scanning': True,
        'scan_interval_minutes': 3,  # 3分钟扫描一次
        'min_expected_return': 3.0,  # 最低预期收益3%
        'min_risk_reward_ratio': 1.5,  # 最低风险收益比1.5:1
        'max_position_risk': 0.03,   # 单笔最大风险3%
        
        # 策略权重配置
        'strategy_weights': {
            'breakout': 1.0,      # 突破策略
            'momentum': 1.2,      # 动量策略（币圈特色）
            'funding_rate': 0.8,  # 费率套利
            'volatility': 1.1,    # 波动率策略
            'reversal': 0.9,      # 反转策略
            'technical_pattern': 0.7  # 技术形态
        },
        
        # 币圈特色配置
        'crypto_specific': {
            'enable_meme_coin_boost': True,    # 启用meme币加成
            'meme_coin_multiplier': 1.5,       # meme币收益倍数
            'enable_defi_season_detection': True,  # DeFi季节检测
            'enable_nft_trend_analysis': True,     # NFT趋势分析
            'enable_layer2_opportunities': True,   # Layer2机会
            'high_volatility_threshold': 0.15,     # 高波动率阈值15%
            'momentum_acceleration_factor': 2.0    # 动量加速因子
        },
        
        # 自动通知配置
        'auto_notification': {
            'enable': True,
            'high_return_threshold': 6.0,     # 6%以上自动通知
            'urgent_return_threshold': 10.0,   # 10%以上紧急通知
            'max_notifications_per_hour': 20,  # 每小时最多20次通知
            'notification_channels': ['feishu', 'wechat'],
            'include_risk_warning': True       # 包含风险提示
        },
        
        # 市场状态适应
        'market_adaptation': {
            'bull_market_multiplier': 1.3,     # 牛市收益倍数
            'bear_market_safety_factor': 0.7,  # 熊市安全系数
            'sideways_market_threshold': 0.8,  # 震荡市场阈值
            'volatility_adjustment': True,     # 波动率自适应
            'volume_confirmation': True        # 成交量确认
        }
    }, description="收益最大化策略配置 - 专为币圈高波动环境设计，多策略并行，自动发现高收益机会")
    
    # 数据缓存配置
    cache_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_cache': True,
        'cache_ttl_minutes': 2,  # 缩短缓存时间，提高数据新鲜度
        'max_cache_size_mb': 200,  # 增加缓存大小
        'cache_compression': True,
        'enable_prediction_cache': True,  # 启用预测结果缓存
        'prediction_cache_ttl_minutes': 10  # 预测缓存10分钟
    }, description="数据缓存配置 - 优化币圈高频交易")
    
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
            "pool_config": {
                "pool_size": self.db_pool_size,
                "max_overflow": self.db_max_overflow,
                "pool_timeout": self.db_pool_timeout,
                "pool_recycle": self.db_pool_recycle,
                "pool_pre_ping": self.db_pool_pre_ping,
                "connect_timeout": self.db_connect_timeout,
                "read_timeout": self.db_read_timeout,
                "write_timeout": self.db_write_timeout,
            }
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
    def http_pool_config(self) -> dict:
        """获取HTTP连接池配置"""
        return {
            "pool_limit": self.http_pool_limit,
            "pool_limit_per_host": self.http_pool_limit_per_host,
            "keepalive_timeout": self.http_keepalive_timeout,
            "connect_timeout": self.http_connect_timeout,
            "read_timeout": self.http_read_timeout,
            "total_timeout": self.http_total_timeout,
            "dns_cache_ttl": self.http_dns_cache_ttl,
            "max_retries": self.http_max_retries,
            "proxy_enabled": self.proxy_enabled,
            "proxy_url": self.proxy_url
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
