# -*- coding: utf-8 -*-
"""
应用配置管理
Configuration management for the trading analysis tool
"""

import json
import os
from typing import Any, Dict, List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""
    
    def _build_kronos_config(self) -> Dict[str, Any]:
        """从环境变量构建Kronos配置 - 优化版，支持短线和中线预测"""
        # 解析target_symbols字符串为列表
        target_symbols_str = os.getenv('KRONOS_CONFIG__TARGET_SYMBOLS', '["BTC-USDT-SWAP","ETH-USDT-SWAP","SOL-USDT-SWAP","ADA-USDT-SWAP","DOGE-USDT-SWAP"]')
        try:
            target_symbols = json.loads(target_symbols_str)
        except json.JSONDecodeError:
            target_symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'ADA-USDT-SWAP', 'DOGE-USDT-SWAP']
        
        return {
            'enable_kronos_prediction': os.getenv('KRONOS_CONFIG__ENABLE_KRONOS_PREDICTION', 'true').lower() == 'true',
            'model_name': os.getenv('KRONOS_CONFIG__MODEL_NAME', 'NeoQuasar/Kronos-Tokenizer-base'),
            'tokenizer_name': os.getenv('KRONOS_CONFIG__TOKENIZER_NAME', 'NeoQuasar/Kronos-Tokenizer-base'),
            'max_context': int(os.getenv('KRONOS_CONFIG__MAX_CONTEXT', '256')),
            
            # 🎯 短线交易配置 (日内交易)
            'short_term': {
                'timeframe': os.getenv('KRONOS_CONFIG__SHORT_TERM__TIMEFRAME', '1H'),  # 1小时K线
                'lookback_periods': int(os.getenv('KRONOS_CONFIG__SHORT_TERM__LOOKBACK_PERIODS', '48')),  # 2天数据
                'prediction_horizon': int(os.getenv('KRONOS_CONFIG__SHORT_TERM__PREDICTION_HORIZON', '6')),  # 预测6小时
                'confidence_threshold': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__CONFIDENCE_THRESHOLD', '0.35')),  # 提高阈值
                'trend_filter_enabled': os.getenv('KRONOS_CONFIG__SHORT_TERM__TREND_FILTER_ENABLED', 'true').lower() == 'true',
                'volatility_adjustment': os.getenv('KRONOS_CONFIG__SHORT_TERM__VOLATILITY_ADJUSTMENT', 'true').lower() == 'true',
                'signal_thresholds': {
                    'strong_buy': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__STRONG_BUY_THRESHOLD', '0.75')),
                    'buy': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__BUY_THRESHOLD', '0.60')),
                    'hold': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__HOLD_THRESHOLD', '0.45')),
                    'sell': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__SELL_THRESHOLD', '0.60')),
                    'strong_sell': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__STRONG_SELL_THRESHOLD', '0.75'))
                },
                'trend_confirmation': {
                    'bullish_threshold': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__BULLISH_THRESHOLD', '0.80')),  # 强势上涨中需要80%置信度才卖出
                    'bearish_threshold': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__BEARISH_THRESHOLD', '0.80')),  # 强势下跌中需要80%置信度才买入
                    'price_change_threshold': float(os.getenv('KRONOS_CONFIG__SHORT_TERM__PRICE_CHANGE_THRESHOLD', '0.08'))  # 需要8%以上变化
                }
            },
            
            # 🎯 中线交易配置 (持仓几天)
            'medium_term': {
                'timeframe': os.getenv('KRONOS_CONFIG__MEDIUM_TERM__TIMEFRAME', '4H'),  # 4小时K线
                'lookback_periods': int(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__LOOKBACK_PERIODS', '72')),  # 12天数据
                'prediction_horizon': int(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__PREDICTION_HORIZON', '24')),  # 预测24小时
                'confidence_threshold': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__CONFIDENCE_THRESHOLD', '0.30')),  # 中线可以稍低
                'trend_filter_enabled': os.getenv('KRONOS_CONFIG__MEDIUM_TERM__TREND_FILTER_ENABLED', 'true').lower() == 'true',
                'volatility_adjustment': os.getenv('KRONOS_CONFIG__MEDIUM_TERM__VOLATILITY_ADJUSTMENT', 'true').lower() == 'true',
                'signal_thresholds': {
                    'strong_buy': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__STRONG_BUY_THRESHOLD', '0.70')),
                    'buy': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__BUY_THRESHOLD', '0.55')),
                    'hold': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__HOLD_THRESHOLD', '0.40')),
                    'sell': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__SELL_THRESHOLD', '0.55')),
                    'strong_sell': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__STRONG_SELL_THRESHOLD', '0.70'))
                },
                'trend_confirmation': {
                    'bullish_threshold': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__BULLISH_THRESHOLD', '0.70')),  # 中线稍低要求
                    'bearish_threshold': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__BEARISH_THRESHOLD', '0.70')),
                    'price_change_threshold': float(os.getenv('KRONOS_CONFIG__MEDIUM_TERM__PRICE_CHANGE_THRESHOLD', '0.06'))  # 6%变化阈值
                }
            },
            
            # 🎯 默认模式选择
            'default_mode': os.getenv('KRONOS_CONFIG__DEFAULT_MODE', 'short_term'),  # 默认短线模式
            'auto_mode_selection': os.getenv('KRONOS_CONFIG__AUTO_MODE_SELECTION', 'true').lower() == 'true',  # 自动模式选择
            
            # 🎯 多时间框架验证
            'multi_timeframe_analysis': {
                'enabled': os.getenv('KRONOS_CONFIG__MULTI_TIMEFRAME_ENABLED', 'true').lower() == 'true',
                'timeframes': ['15M', '1H', '4H', '1D'],  # 多时间框架分析
                'consensus_threshold': float(os.getenv('KRONOS_CONFIG__CONSENSUS_THRESHOLD', '0.7')),  # 70%一致性
                'weight_distribution': {
                    '15m': 0.15,  # 短期噪音权重较低
                    '1h': 0.35,   # 主要权重
                    '4h': 0.35,   # 主要权重
                    '1d': 0.15    # 长期趋势权重
                }
            },
            
            # 兼容性配置 (保持向后兼容)
            'lookback_periods': int(os.getenv('KRONOS_CONFIG__LOOKBACK_PERIODS', '48')),  # 默认使用短线配置
            'prediction_horizon': int(os.getenv('KRONOS_CONFIG__PREDICTION_HORIZON', '6')),  # 默认使用短线配置
            'confidence_threshold': float(os.getenv('KRONOS_CONFIG__CONFIDENCE_THRESHOLD', '0.35')),  # 默认使用短线配置
            
            'sampling_params': {
                'temperature': float(os.getenv('KRONOS_CONFIG__TEMPERATURE', '0.8')),
                'top_p': float(os.getenv('KRONOS_CONFIG__TOP_P', '0.9')),
                'sample_count': int(os.getenv('KRONOS_CONFIG__SAMPLE_COUNT', '3'))
            },
            'update_interval_minutes': int(os.getenv('KRONOS_CONFIG__UPDATE_INTERVAL_MINUTES', '5')),
            'cache_predictions': os.getenv('KRONOS_CONFIG__CACHE_PREDICTIONS', 'true').lower() == 'true',
            'use_gpu': os.getenv('KRONOS_CONFIG__USE_GPU', 'false').lower() == 'true',
            'device': os.getenv('KRONOS_CONFIG__DEVICE', 'cpu'),
            'prediction_timeout': int(os.getenv('KRONOS_CONFIG__PREDICTION_TIMEOUT', '120')),
            'max_retries': int(os.getenv('KRONOS_CONFIG__MAX_RETRIES', '2')),
            'target_symbols': target_symbols,
            'enhanced_analysis': os.getenv('KRONOS_CONFIG__ENHANCED_ANALYSIS', 'true').lower() == 'true',
            'strict_kronos_only': os.getenv('KRONOS_CONFIG__STRICT_KRONOS_ONLY', 'true').lower() == 'true',
            'disable_traditional_signals': os.getenv('KRONOS_CONFIG__DISABLE_TRADITIONAL_SIGNALS', 'true').lower() == 'true',
            
            'notification_config': {
                'enable_strong_signal_notification': True,
                'strong_signal_threshold': 0.35,
                'medium_signal_threshold': 0.25,
                'notification_channels': ['feishu', 'wechat'],
                'notification_priority': 'high',
                'batch_notification': False,
                'enable_immediate_alerts': True,
                'enable_enhanced_analysis': True,
                'include_technical_details': True,
                'include_trade_params': True,
                'profit_opportunity_threshold': 3.0,
                'require_kronos_validation': True,
                'unified_signal_analysis': True
            },
            'market_scan_config': {
                'enable_market_scan': True,
                'enable_profit_scan': True,
                'strong_signal_threshold': 0.35,
                'profit_opportunity_threshold': 2.0,
                'scan_intervals': {
                    'strong_signal_minutes': 3,
                    'profit_scan_minutes': 2,
                    'grid_trading_hours': 1
                },
                'top_volume_limit': 100,
                'notification_config': {
                    'enable_opportunity_notifications': True,
                    'max_opportunities_per_notification': 3,
                    'priority_mapping': {
                        'strong_signal': 'high',
                        'profit_opportunity': 'urgent',
                        'grid_trading': 'medium'
                    },
                    'auto_notify_high_return': True,
                    'high_return_threshold': 3.0
                }
            }
        }
    
    # 应用基础配置
    app_name: str = Field(default="Python Trading Tool", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    debug: bool = Field(default=False, description="调试模式")
    log_level: str = Field(default="INFO", description="日志级别")
    
    # 服务配置
    host: str = Field(default="0.0.0.0", description="服务主机")
    port: int = Field(default=8000, description="服务端口")
    
    # 交易所选择配置
    exchange_provider: str = Field(default="okx", description="交易所提供商: okx, binance")
    
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
    binance_api_key: str = Field(default="", description="币安API Key")
    binance_secret_key: str = Field(default="", description="币安Secret Key")
    binance_testnet: bool = Field(default=False, description="是否使用测试网")
    binance_base_url: str = Field(default="https://fapi.binance.com", description="币安API基础URL")
    binance_websocket_url: str = Field(default="wss://fstream.binance.com/ws/", description="币安WebSocket URL")
    binance_enable_websocket: bool = Field(default=True, description="是否启用币安WebSocket")
    
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
    
    # 监控参数配置 - 日内短线交易优化
    open_interest_threshold: float = Field(default=1.02, description="持仓量变化阈值(日内短线敏感度)")
    volume_multiplier: float = Field(default=2.0, description="成交量异常倍数(短线交易敏感度)")
    funding_rate_interval: int = Field(default=20, description="费率监控间隔(分钟) - 日内短线优化")
    trend_analysis_interval: int = Field(default=3, description="趋势分析间隔(分钟) - 日内短线高频")
    open_interest_interval: int = Field(default=2, description="持仓量监控间隔(分钟) - 日内短线高频")
    volume_monitor_interval: int = Field(default=5, description="交易量监控间隔(分钟) - 日内短线优化")
    position_analysis_interval: int = Field(default=15, description="持仓分析间隔(分钟) - 日内短线优化")
    grid_opportunities_interval: int = Field(default=30, description="网格机会分析间隔(分钟) - 日内短线优化")
    market_opportunities_interval: int = Field(default=60, description="市场机会分析间隔(分钟) - 日内短线优化")
    
    # 策略配置
    strategy_config: Dict[str, Any] = Field(default_factory=lambda: {
        'supertrend': {
            'period': 10,
            'multiplier': 3.0,
            'timeframes': ['1D', '4H', '1H', '15M']
        },
        'volume': {
            'threshold_multiplier': 3.0,
            'consecutive_periods': 3
        },
        'funding_rate': {
            'negative_threshold': -0.0005,  # -0.05% 阈值，只推送显著的负费率机会
            'high_threshold': 0.1
        }
    }, description="策略参数配置")
    
    # ==================== 账户配置 ====================
    # 账户本金配置 (USDT)
    account_initial_capital: float = Field(default=10000.0, description="账户初始本金 (USDT)")
    
    # 风险管理配置
    risk_config: Dict[str, Any] = Field(default_factory=lambda: {
        'max_risk_per_trade': 0.02,      # 单笔交易最大风险 2%
        'max_total_risk': 0.10,          # 总体最大风险 10%
        'risk_free_rate': 0.03,          # 无风险利率 3%
        'volatility_lookback': 30,       # 波动率回看期 30天
        'correlation_threshold': 0.7,     # 相关性阈值
        'max_drawdown_threshold': 0.15,   # 最大回撤阈值 15%
        'sharpe_ratio_threshold': 1.0,    # 夏普比率阈值
        'var_confidence': 0.95           # VaR 置信度 95%
    }, description="风险管理配置")
    
    # Kronos预测模型配置 - 从环境变量读取
    @property
    def kronos_config(self) -> Dict[str, Any]:
        """动态从环境变量构建Kronos配置"""
        return self._build_kronos_config()
    
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
    
    # 主要监控币种配置 - 增加主要币种，使用Kronos进行深度分析
    monitored_symbols: List[str] = Field(default=[
        'BTC-USDT-SWAP',   # 比特币
        'ETH-USDT-SWAP',   # 以太坊
        'SOL-USDT-SWAP',   # Solana
        'BNB-USDT-SWAP',   # 币安币
        'ADA-USDT-SWAP',   # Cardano
        'DOGE-USDT-SWAP',  # 狗狗币
        'AVAX-USDT-SWAP',  # Avalanche
        'DOT-USDT-SWAP'    # Polkadot
    ], description="主要监控的交易对列表 - 包含主流币种，使用Kronos进行深度分析和交易决策")
    
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
        'LPT-USDT-SWAP',  # 添加LPT - 经常有负费率机会
        
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
        'chart_timeframes': ['1M', '5M', '15M', '1H', '4H', '1D']
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
            'volatility_acceleration_factor': 2.0    # 波动率加速因子
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
    
    # 新闻分析配置
    news_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_news_analysis': True,
        'panews_api_url': 'https://api.panewslab.com/webapi',
        'fetch_interval_minutes': 30,  # 新闻获取间隔
        'analysis_interval_minutes': 15,  # 新闻分析间隔
        'max_news_per_fetch': 50,  # 每次最多获取新闻数量
        'news_retention_hours': 168,  # 新闻保留时间（7天）
        
        # 新闻过滤配置
        'importance_threshold': 0.3,  # 重要性阈值
        'sentiment_threshold': 0.2,   # 情感强度阈值
        'enable_auto_notification': True,  # 自动通知
        
        # Kronos集成配置
        'enable_kronos_integration': True,
        'kronos_analysis_symbols': [
            'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 
            'BNB-USDT-SWAP', 'ADA-USDT-SWAP', 'DOGE-USDT-SWAP',
            'AVAX-USDT-SWAP', 'DOT-USDT-SWAP'
        ],
        'kronos_confidence_threshold': 0.6,
        
        # 通知配置
        'notification_config': {
            'enable_news_alerts': True,
            'high_impact_threshold': 0.7,  # 高影响新闻阈值
            'max_alerts_per_hour': 10,     # 每小时最大通知数
            'channels': ['feishu', 'wechat']  # 通知渠道
        }
    }, description="新闻分析配置 - PANews集成和Kronos分析")
    
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
    
    # 依赖管理配置
    dependency_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_dependency_check': True,
        'check_interval_minutes': 60,  # 每小时检查一次依赖状态
        'auto_install_missing': False,  # 是否自动安装缺失依赖
        'required_dependencies': [
            'pandas', 'numpy', 'aiohttp', 'fastapi', 'pydantic',
            'sqlalchemy', 'pymysql', 'redis', 'asyncio'
        ],
        'optional_dependencies': [
            'torch', 'transformers', 'scikit-learn', 'joblib',
            'ta-lib', 'ccxt', 'websockets', 'plotly'
        ],
        'kronos_dependencies': [
            'torch', 'transformers', 'tokenizers', 'accelerate'
        ],
        'fallback_config': {
            'enable_fallback_mode': True,
            'fallback_timeout_seconds': 30,
            'max_fallback_attempts': 3,
            'fallback_services': ['basic_analysis', 'simple_prediction']
        },
        'version_constraints': {
            'torch': '>=1.9.0',
            'transformers': '>=4.20.0',
            'pandas': '>=1.3.0',
            'numpy': '>=1.21.0',
            'fastapi': '>=0.68.0'
        },
        'installation_config': {
            'pip_index_url': 'https://pypi.org/simple/',
            'pip_extra_index_urls': ['https://download.pytorch.org/whl/cpu'],
            'pip_timeout': 300,
            'pip_retries': 3
        }
    }, description="依赖管理配置 - 自动检查、验证和管理系统依赖")
    
    # 服务初始化配置
    service_config: Dict[str, Any] = Field(default_factory=lambda: {
        'initialization_timeout': 120,  # 服务初始化超时时间(秒)
        'startup_retry_attempts': 3,    # 启动重试次数
        'startup_retry_delay': 5,       # 重试延迟(秒)
        'graceful_shutdown_timeout': 30,  # 优雅关闭超时(秒)
        'health_check_interval': 60,    # 健康检查间隔(秒)
        'service_priorities': {
            'core': ['config', 'logging', 'database'],
            'essential': ['exchange_factory', 'data_service'],
            'analysis': ['indicator_service', 'prediction_service'],
            'optional': ['kronos_service', 'notification_service']
        },
        'failure_handling': {
            'continue_on_optional_failure': True,
            'max_failed_services': 2,  # 最多允许2个非核心服务失败
            'enable_service_recovery': True,
            'recovery_check_interval': 300,  # 5分钟检查一次恢复
            'auto_restart_failed_services': True
        },
        'resource_limits': {
            'max_memory_mb': 2048,      # 最大内存使用(MB)
            'max_cpu_percent': 80,      # 最大CPU使用率
            'max_concurrent_tasks': 50,  # 最大并发任务数
            'connection_pool_size': 100  # 连接池大小
        }
    }, description="服务初始化和管理配置 - 控制服务启动、健康检查和故障恢复")
    
    # 回退服务配置
    fallback_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_fallback_services': True,
        'fallback_timeout': 30,  # 回退服务超时(秒)
        'prediction_fallback': {
            'enable': True,
            'method': 'simple_technical_analysis',  # 简单技术分析作为回退
            'indicators': ['sma', 'ema', 'rsi', 'macd'],
            'confidence_penalty': 0.3,  # 回退预测置信度惩罚
            'cache_duration_minutes': 15
        },
        'data_fallback': {
            'enable': True,
            'use_cached_data': True,
            'max_cache_age_minutes': 30,
            'fallback_exchanges': ['okx', 'binance'],  # 备用交易所
            'retry_original_after_minutes': 10
        },
        'notification_fallback': {
            'enable': True,
            'fallback_channels': ['console', 'file'],  # 备用通知渠道
            'log_failed_notifications': True
        },
        'analysis_fallback': {
            'enable': True,
            'use_basic_indicators': True,
            'disable_advanced_features': True,
            'simplified_signals': True
        }
    }, description="回退服务配置 - 当主要服务不可用时的备用方案")
    
    # API增强错误处理配置
    api_error_handling_config: Dict[str, Any] = Field(default_factory=lambda: {
        'enable_enhanced_error_handling': True,
        'max_retry_attempts': 5,
        'base_retry_delay': 1.0,  # 基础重试延迟(秒)
        'max_retry_delay': 60.0,  # 最大重试延迟(秒)
        'exponential_backoff_factor': 2.0,
        'jitter_enabled': True,   # 启用抖动避免雷群效应
        'circuit_breaker': {
            'enable': True,
            'failure_threshold': 5,    # 失败阈值
            'recovery_timeout': 60,    # 恢复超时(秒)
            'half_open_max_calls': 3   # 半开状态最大调用数
        },
        'rate_limiting': {
            'enable': True,
            'requests_per_second': 10,
            'burst_size': 20,
            'adaptive_rate_limiting': True
        },
        'timeout_config': {
            'connect_timeout': 10,
            'read_timeout': 30,
            'total_timeout': 60,
            'adaptive_timeout': True,  # 自适应超时
            'timeout_multiplier': 1.5
        },
        'error_classification': {
            'retryable_errors': [
                'ConnectionError', 'TimeoutError', 'HTTPError_5xx',
                'RateLimitError', 'TemporaryUnavailable'
            ],
            'non_retryable_errors': [
                'AuthenticationError', 'InvalidParameterError',
                'HTTPError_4xx', 'ValidationError'
            ]
        },
        'monitoring': {
            'track_error_rates': True,
            'alert_on_high_error_rate': True,
            'error_rate_threshold': 0.1,  # 10%错误率阈值
            'alert_cooldown_minutes': 15
        }
    }, description="API增强错误处理配置 - 重试、熔断、限流和监控")
    
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
    
    @validator("exchange_provider")
    def validate_exchange_provider(cls, v):
        """验证交易所提供商"""
        valid_exchanges = ["okx", "binance"]
        if v.lower() not in valid_exchanges:
            raise ValueError(f"Exchange provider must be one of {valid_exchanges}")
        return v.lower()
    
    @validator("binance_api_key")
    def validate_binance_api_key(cls, v, values):
        """验证币安API Key"""
        exchange_provider = values.get("exchange_provider", "okx")
        if exchange_provider == "binance" and not v:
            raise ValueError("Binance API key is required when exchange_provider is 'binance'")
        return v
    
    @validator("binance_secret_key")
    def validate_binance_secret_key(cls, v, values):
        """验证币安Secret Key"""
        exchange_provider = values.get("exchange_provider", "okx")
        if exchange_provider == "binance" and not v:
            raise ValueError("Binance secret key is required when exchange_provider is 'binance'")
        return v
    
    @validator("okx_api_key")
    def validate_okx_api_key(cls, v, values):
        """验证OKX API Key"""
        exchange_provider = values.get("exchange_provider", "okx")
        if exchange_provider == "okx" and not v:
            raise ValueError("OKX API key is required when exchange_provider is 'okx'")
        return v
    
    @validator("okx_secret_key")
    def validate_okx_secret_key(cls, v, values):
        """验证OKX Secret Key"""
        exchange_provider = values.get("exchange_provider", "okx")
        if exchange_provider == "okx" and not v:
            raise ValueError("OKX secret key is required when exchange_provider is 'okx'")
        return v
    
    @validator("okx_passphrase")
    def validate_okx_passphrase(cls, v, values):
        """验证OKX Passphrase"""
        exchange_provider = values.get("exchange_provider", "okx")
        if exchange_provider == "okx" and not v:
            raise ValueError("OKX passphrase is required when exchange_provider is 'okx'")
        return v
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.debug
    
    def validate_exchange_config(self) -> bool:
        """验证交易所配置是否完整"""
        if self.exchange_provider == "okx":
            return bool(self.okx_api_key and self.okx_secret_key and self.okx_passphrase)
        elif self.exchange_provider == "binance":
            return bool(self.binance_api_key and self.binance_secret_key)
        return False
    
    def get_active_exchange_config(self) -> dict:
        """获取当前激活的交易所配置"""
        if self.exchange_provider == "okx":
            return self.okx_config
        elif self.exchange_provider == "binance":
            return self.binance_config
        else:
            raise ValueError(f"Unsupported exchange provider: {self.exchange_provider}")
    
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
            "enable_websocket": self.binance_enable_websocket,
            "websocket_config": {
                "websocket_url": self.binance_websocket_url,
                "reconnect_interval": 5,
                "max_reconnect_attempts": 10,
                "ping_interval": 20,
                "connection_timeout": 30,
                "enable_compression": False,
                "enable_auto_reconnect": True,
                "heartbeat_interval": 20
            }
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
            "enable_websocket": True,  # 启用WebSocket
            "websocket_config": {
                "public_url": "wss://ws.okx.com:8443/ws/v5/public" if not self.okx_sandbox else "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999",
                "private_url": "wss://ws.okx.com:8443/ws/v5/private" if not self.okx_sandbox else "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999",
                "reconnect_interval": 5,
                "max_reconnect_attempts": 10,
                "ping_interval": 25,
                "connection_timeout": 30,
                "max_subscriptions_per_connection": 240,  # OKX限制
                "enable_compression": True,
                "enable_auto_reconnect": True,
                "heartbeat_interval": 25
            }
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
