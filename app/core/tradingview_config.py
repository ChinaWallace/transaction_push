# -*- coding: utf-8 -*-
"""
TradingView 配置管理
"""

from typing import Dict, Any, Optional
from pydantic import Field
try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings
from app.core.config import get_settings


class TradingViewConfig(BaseSettings):
    """TradingView 配置类"""
    
    # API 配置 - 从 .env.tradingview.example 整合
    api_url: str = Field(default="https://scanner.tradingview.com/coin/scan")
    request_timeout: int = Field(default=30)
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)
    
    # 扫描配置
    default_scan_limit: int = Field(default=100)
    
    # 调度配置
    enable_startup_scan: bool = Field(default=True)
    startup_scan_delay: int = Field(default=5)
    enable_hourly_scan: bool = Field(default=True)
    enable_daily_scan: bool = Field(default=True)
    daily_scan_hour: int = Field(default=9)
    
    # 筛选配置
    min_volume_usd: float = Field(default=100000000.0)
    min_vol_to_market_cap: float = Field(default=0.01)
    max_vol_to_market_cap: float = Field(default=2.0)
    min_volatility: float = Field(default=5.0)
    
    # 通知配置
    enable_notifications: bool = Field(default=True)
    notification_threshold: int = Field(default=1)
    
    # 历史记录配置
    history_retention_days: int = Field(default=3)
    
    class Config:
        env_prefix = "TRADINGVIEW_"
        case_sensitive = False


def get_tradingview_config() -> TradingViewConfig:
    """获取TradingView配置"""
    return TradingViewConfig()


def get_default_scan_request_data() -> Dict[str, Any]:
    """获取默认扫描请求数据"""
    config = get_tradingview_config()
    
    return {
        "columns": [
            "base_currency",
            "base_currency_desc", 
            "base_currency_logoid",
            "update_mode",
            "type",
            "typespecs",
            "exchange",
            "crypto_total_rank",
            "close",
            "pricescale",
            "minmov",
            "fractional",
            "minmove2",
            "currency",
            "24h_close_change|5",
            "24h_vol_to_market_cap",
            "24h_vol_cmc",
            "fundamental_currency_code",
            "market_cap_calc",
            "circulating_supply",
            "crypto_common_categories.tr",
            "Volatility.D",
            "crypto_blockchain_ecosystems.tr"
        ],
        "filter": [
            {
                "left": "24h_vol_to_market_cap",
                "operation": "in_range",
                "right": [config.min_vol_to_market_cap, config.max_vol_to_market_cap]
            },
            {
                "left": "24h_vol_cmc",
                "operation": "egreater",
                "right": config.min_volume_usd
            },
            {
                "left": "crypto_common_categories",
                "operation": "has",
                "right": [
                    "loyalty-rewards", "tourism", "identity", "enterprise-solutions",
                    "smart-contract-platforms", "jobs", "web3", "centralized-exchange",
                    "seigniorage", "developments-tools", "internet-of-things",
                    "distributed-computing-storage", "sports", "logistics", "metaverse",
                    "insurance", "marketplace", "move-to-earn", "defi", "hospitality",
                    "energy", "payments", "real-estate", "decentralized-exchange",
                    "algorithmic-stablecoins", "cybersecurity", "marketing", "layer-1",
                    "wrapped-tokens", "memecoins", "derivatives", "asset-management",
                    "scaling", "data-management-ai", "sec-security-token",
                    "collectibles-nfts", "fan-tokens", "lending-borrowing",
                    "interoperability", "privacy", "cryptocurrencies",
                    "social-media-content", "fundraising", "transport", "e-commerce",
                    "asset-backed-tokens", "analytics", "oracles", "prediction-markets",
                    "dao", "education", "health", "gaming"
                ]
            },
            {
                "left": "Volatility.D",
                "operation": "greater",
                "right": config.min_volatility
            },
            {
                "left": "BB.basis|240",
                "operation": "less",
                "right": "close|240"
            }
        ],
        "ignore_unknown_fields": False,
        "options": {
            "lang": "zh"
        },
        "range": [0, config.default_scan_limit],
        "sort": {
            "sortBy": "24h_close_change|5",
            "sortOrder": "desc"
        },
        "symbols": {},
        "markets": ["coin"]
    }


def get_request_headers() -> Dict[str, str]:
    """获取请求头配置"""
    return {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://cn.tradingview.com",
        "Referer": "https://cn.tradingview.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site"
    }


def get_proxy_config() -> Optional[Dict[str, str]]:
    """获取代理配置 - 使用项目统一的代理设置"""
    settings = get_settings()
    
    # 使用项目统一的代理配置
    proxy_enabled = getattr(settings, 'proxy_enabled', False)
    proxy_url = getattr(settings, 'proxy_url', None)
    
    if proxy_enabled and proxy_url:
        return {
            "http": proxy_url,
            "https": proxy_url
        }
    
    return None


def get_request_cookies() -> Dict[str, str]:
    """获取请求Cookie配置"""
    return {
        # 可以根据需要添加必要的cookies
        # "sessionid": "your_session_id",
        # "csrftoken": "your_csrf_token"
    }