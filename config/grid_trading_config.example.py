# -*- coding: utf-8 -*-
"""
网格交易配置示例
Grid Trading Configuration Example

复制此文件为 grid_trading_config.py 并根据需要修改配置
"""

# 网格交易基础配置
GRID_TRADING_CONFIG = {
    # 基准资金设置
    "base_capital": 10000,  # 基准资金 (USDT)
    
    # 筛选条件
    "filters": {
        "min_volume_24h": 50000000,    # 最小24h交易量 (USDT)
        "min_volatility": 0.02,        # 最小波动率 (2%)
        "max_volatility": 0.15,        # 最大波动率 (15%)
        "min_liquidity_score": 0.3,    # 最小流动性评分
        "trend_lookback_days": 7,      # 趋势分析回看天数
    },
    
    # 网格配置
    "grid_settings": {
        "default_grid_count": 20,      # 默认网格数量
        "min_grid_count": 10,          # 最小网格数量
        "max_grid_count": 30,          # 最大网格数量
        "grid_spacing_range": [0.5, 2.0],  # 网格间距范围 (%)
        "atr_multiplier": 2.0,         # ATR倍数
    },
    
    # 仓位配置
    "position_settings": {
        "excellent_position": 40,      # 优秀机会仓位比例 (%)
        "good_position": 30,           # 良好机会仓位比例 (%)
        "moderate_position": 20,       # 一般机会仓位比例 (%)
        "poor_position": 10,           # 较差机会仓位比例 (%)
        "high_volatility_reduction": 0.8,  # 高波动率仓位降低系数
        "low_volatility_reduction": 0.9,   # 低波动率仓位降低系数
    },
    
    # 机会等级评分权重
    "scoring_weights": {
        "volatility_weight": 30,       # 波动率权重
        "volume_weight": 25,           # 交易量权重
        "liquidity_weight": 20,        # 流动性权重
        "trend_weight": 25,            # 趋势权重
    },
    
    # 机会等级阈值
    "opportunity_thresholds": {
        "excellent": 85,               # 优秀机会阈值
        "good": 70,                    # 良好机会阈值
        "moderate": 55,                # 一般机会阈值
    },
    
    # 风险等级设置
    "risk_levels": {
        "low_risk_threshold": 0.03,    # 低风险波动率阈值
        "medium_risk_threshold": 0.06, # 中等风险波动率阈值
        "high_risk_threshold": 0.10,   # 高风险波动率阈值
    },
    
    # 推送设置
    "notification_settings": {
        "startup_push": True,          # 启动时推送
        "hourly_push": True,           # 每小时推送
        "min_opportunities": 1,        # 最少机会数才推送
        "max_recommendations": 10,     # 最多推荐数量
        "include_market_summary": True, # 包含市场总结
    },
    
    # 候选交易对设置
    "symbol_settings": {
        "auto_discover": True,         # 自动发现交易对
        "max_candidates": 50,          # 最大候选数量
        "volume_rank_limit": 50,       # 交易量排名限制
        "custom_symbols": [            # 自定义关注交易对
            "BTC-USDT-SWAP",
            "ETH-USDT-SWAP", 
            "SOL-USDT-SWAP",
            "BNB-USDT-SWAP",
            "XRP-USDT-SWAP",
            "ADA-USDT-SWAP",
            "DOGE-USDT-SWAP",
            "MATIC-USDT-SWAP",
            "DOT-USDT-SWAP",
            "AVAX-USDT-SWAP"
        ]
    },
    
    # 性能设置
    "performance_settings": {
        "max_concurrent_analysis": 10, # 最大并发分析数
        "analysis_timeout": 30,        # 分析超时时间 (秒)
        "cache_duration": 300,         # 缓存持续时间 (秒)
        "retry_attempts": 3,           # 重试次数
    }
}

# 高级配置 - 专家用户
ADVANCED_CONFIG = {
    # 技术指标参数
    "technical_indicators": {
        "atr_period": 14,              # ATR周期
        "volatility_period": 7,        # 波动率计算周期
        "trend_ma_period": 20,         # 趋势MA周期
        "volume_ma_period": 20,        # 成交量MA周期
    },
    
    # 市场条件调整
    "market_conditions": {
        "bull_market_multiplier": 1.2, # 牛市权重倍数
        "bear_market_multiplier": 0.8, # 熊市权重倍数
        "sideways_market_multiplier": 1.5, # 震荡市权重倍数
    },
    
    # 动态调整参数
    "dynamic_adjustments": {
        "enable_dynamic_weights": True, # 启用动态权重调整
        "market_sentiment_factor": 0.1, # 市场情绪因子
        "volatility_adjustment": True,  # 波动率动态调整
        "volume_adjustment": True,      # 成交量动态调整
    }
}

# 测试配置 - 用于开发和测试
TEST_CONFIG = {
    "base_capital": 1000,             # 测试用小额资金
    "filters": {
        "min_volume_24h": 10000000,   # 降低交易量要求
        "min_volatility": 0.01,       # 降低波动率要求
        "max_volatility": 0.20,       # 提高波动率上限
    },
    "symbol_settings": {
        "max_candidates": 10,         # 减少候选数量
        "custom_symbols": [           # 测试用交易对
            "BTC-USDT-SWAP",
            "ETH-USDT-SWAP",
            "SOL-USDT-SWAP"
        ]
    },
    "notification_settings": {
        "min_opportunities": 0,       # 无论多少机会都推送
        "max_recommendations": 5,     # 限制推荐数量
    }
}

# 根据环境选择配置
def get_grid_trading_config(environment="production"):
    """
    根据环境获取网格交易配置
    
    Args:
        environment: 环境类型 ("production", "development", "test")
    
    Returns:
        配置字典
    """
    if environment == "test":
        config = GRID_TRADING_CONFIG.copy()
        config.update(TEST_CONFIG)
        return config
    elif environment == "development":
        config = GRID_TRADING_CONFIG.copy()
        # 开发环境可以使用更宽松的配置
        config["filters"]["min_volume_24h"] = 20000000
        return config
    else:
        # 生产环境使用默认配置
        return GRID_TRADING_CONFIG

# 配置验证函数
def validate_config(config):
    """
    验证配置的有效性
    
    Args:
        config: 配置字典
    
    Returns:
        (is_valid, error_message)
    """
    try:
        # 检查必需的配置项
        required_keys = ["base_capital", "filters", "grid_settings", "position_settings"]
        for key in required_keys:
            if key not in config:
                return False, f"缺少必需的配置项: {key}"
        
        # 检查数值范围
        if config["base_capital"] <= 0:
            return False, "base_capital 必须大于0"
        
        if config["filters"]["min_volatility"] >= config["filters"]["max_volatility"]:
            return False, "min_volatility 必须小于 max_volatility"
        
        # 检查权重总和
        weights = config.get("scoring_weights", {})
        if weights:
            total_weight = sum(weights.values())
            if abs(total_weight - 100) > 0.1:
                return False, f"评分权重总和必须为100，当前为{total_weight}"
        
        return True, "配置验证通过"
        
    except Exception as e:
        return False, f"配置验证失败: {str(e)}"

# 使用示例
if __name__ == "__main__":
    # 获取生产环境配置
    prod_config = get_grid_trading_config("production")
    
    # 验证配置
    is_valid, message = validate_config(prod_config)
    print(f"配置验证结果: {message}")
    
    # 打印配置摘要
    print(f"基准资金: {prod_config['base_capital']} USDT")
    print(f"最小交易量: {prod_config['filters']['min_volume_24h']:,} USDT")
    print(f"波动率范围: {prod_config['filters']['min_volatility']*100:.1f}% - {prod_config['filters']['max_volatility']*100:.1f}%")
    print(f"默认网格数: {prod_config['grid_settings']['default_grid_count']}")