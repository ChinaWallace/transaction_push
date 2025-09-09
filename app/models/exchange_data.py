# -*- coding: utf-8 -*-
"""
统一交易所数据模型
Unified exchange data models
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


class ExchangeType(Enum):
    """交易所类型枚举"""
    OKX = "okx"
    BINANCE = "binance"


class DataSource(Enum):
    """数据源类型枚举"""
    WEBSOCKET = "websocket"
    REST_API = "rest_api"
    CACHE = "cache"


@dataclass
class TickerData:
    """
    统一的Ticker数据格式
    Unified ticker data format
    """
    symbol: str
    price: Decimal
    volume_24h: Decimal
    change_24h: Decimal
    change_percent_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal
    timestamp: datetime
    source: ExchangeType
    data_source: DataSource = DataSource.REST_API
    
    # 可选字段
    bid_price: Optional[Decimal] = None
    ask_price: Optional[Decimal] = None
    bid_size: Optional[Decimal] = None
    ask_size: Optional[Decimal] = None
    open_price: Optional[Decimal] = None
    quote_volume_24h: Optional[Decimal] = None
    trade_count_24h: Optional[int] = None
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保价格数据为Decimal类型
            if not isinstance(self.price, Decimal):
                self.price = Decimal(str(self.price))
            if not isinstance(self.volume_24h, Decimal):
                self.volume_24h = Decimal(str(self.volume_24h))
            if not isinstance(self.change_24h, Decimal):
                self.change_24h = Decimal(str(self.change_24h))
            if not isinstance(self.change_percent_24h, Decimal):
                self.change_percent_24h = Decimal(str(self.change_percent_24h))
            if not isinstance(self.high_24h, Decimal):
                self.high_24h = Decimal(str(self.high_24h))
            if not isinstance(self.low_24h, Decimal):
                self.low_24h = Decimal(str(self.low_24h))
                
            # 转换可选字段
            if self.bid_price is not None and not isinstance(self.bid_price, Decimal):
                self.bid_price = Decimal(str(self.bid_price))
            if self.ask_price is not None and not isinstance(self.ask_price, Decimal):
                self.ask_price = Decimal(str(self.ask_price))
            if self.bid_size is not None and not isinstance(self.bid_size, Decimal):
                self.bid_size = Decimal(str(self.bid_size))
            if self.ask_size is not None and not isinstance(self.ask_size, Decimal):
                self.ask_size = Decimal(str(self.ask_size))
            if self.open_price is not None and not isinstance(self.open_price, Decimal):
                self.open_price = Decimal(str(self.open_price))
            if self.quote_volume_24h is not None and not isinstance(self.quote_volume_24h, Decimal):
                self.quote_volume_24h = Decimal(str(self.quote_volume_24h))
                
        except (ValueError, TypeError) as e:
            logger.error(f"❌ TickerData数据转换失败: {e}")
            raise ValueError(f"Invalid ticker data: {e}")
    
    @property
    def spread(self) -> Optional[Decimal]:
        """买卖价差"""
        if self.bid_price is not None and self.ask_price is not None:
            return self.ask_price - self.bid_price
        return None
    
    @property
    def spread_percent(self) -> Optional[Decimal]:
        """买卖价差百分比"""
        if self.spread is not None and self.price > 0:
            return (self.spread / self.price) * 100
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "price": float(self.price),
            "volume_24h": float(self.volume_24h),
            "change_24h": float(self.change_24h),
            "change_percent_24h": float(self.change_percent_24h),
            "high_24h": float(self.high_24h),
            "low_24h": float(self.low_24h),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "bid_price": float(self.bid_price) if self.bid_price else None,
            "ask_price": float(self.ask_price) if self.ask_price else None,
            "bid_size": float(self.bid_size) if self.bid_size else None,
            "ask_size": float(self.ask_size) if self.ask_size else None,
            "open_price": float(self.open_price) if self.open_price else None,
            "quote_volume_24h": float(self.quote_volume_24h) if self.quote_volume_24h else None,
            "trade_count_24h": self.trade_count_24h,
            "spread": float(self.spread) if self.spread else None,
            "spread_percent": float(self.spread_percent) if self.spread_percent else None
        }


@dataclass
class KlineData:
    """
    统一的K线数据格式
    Unified kline data format
    """
    symbol: str
    timeframe: str
    timestamp: int  # Unix timestamp in milliseconds
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: ExchangeType
    data_source: DataSource = DataSource.REST_API
    
    # 可选字段
    quote_volume: Optional[Decimal] = None
    trade_count: Optional[int] = None
    taker_buy_volume: Optional[Decimal] = None
    taker_buy_quote_volume: Optional[Decimal] = None
    close_time: Optional[int] = None
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保OHLCV数据为Decimal类型
            if not isinstance(self.open, Decimal):
                self.open = Decimal(str(self.open))
            if not isinstance(self.high, Decimal):
                self.high = Decimal(str(self.high))
            if not isinstance(self.low, Decimal):
                self.low = Decimal(str(self.low))
            if not isinstance(self.close, Decimal):
                self.close = Decimal(str(self.close))
            if not isinstance(self.volume, Decimal):
                self.volume = Decimal(str(self.volume))
                
            # 转换可选字段
            if self.quote_volume is not None and not isinstance(self.quote_volume, Decimal):
                self.quote_volume = Decimal(str(self.quote_volume))
            if self.taker_buy_volume is not None and not isinstance(self.taker_buy_volume, Decimal):
                self.taker_buy_volume = Decimal(str(self.taker_buy_volume))
            if self.taker_buy_quote_volume is not None and not isinstance(self.taker_buy_quote_volume, Decimal):
                self.taker_buy_quote_volume = Decimal(str(self.taker_buy_quote_volume))
                
        except (ValueError, TypeError) as e:
            logger.error(f"❌ KlineData数据转换失败: {e}")
            raise ValueError(f"Invalid kline data: {e}")
    
    @property
    def datetime(self) -> datetime:
        """时间戳转换为datetime对象"""
        return datetime.fromtimestamp(self.timestamp / 1000)
    
    @property
    def price_change(self) -> Decimal:
        """价格变化"""
        return self.close - self.open
    
    @property
    def price_change_percent(self) -> Decimal:
        """价格变化百分比"""
        if self.open != 0:
            return ((self.close - self.open) / self.open) * 100
        return Decimal(0)
    
    @property
    def is_green(self) -> bool:
        """是否为阳线"""
        return self.close > self.open
    
    @property
    def body_size(self) -> Decimal:
        """实体大小"""
        return abs(self.close - self.open)
    
    @property
    def upper_shadow(self) -> Decimal:
        """上影线长度"""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_shadow(self) -> Decimal:
        """下影线长度"""
        return min(self.open, self.close) - self.low
    
    @property
    def body_ratio(self) -> Decimal:
        """实体占比"""
        total_range = self.high - self.low
        if total_range > 0:
            return self.body_size / total_range
        return Decimal(0)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "datetime": self.datetime.isoformat(),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "quote_volume": float(self.quote_volume) if self.quote_volume else None,
            "trade_count": self.trade_count,
            "taker_buy_volume": float(self.taker_buy_volume) if self.taker_buy_volume else None,
            "taker_buy_quote_volume": float(self.taker_buy_quote_volume) if self.taker_buy_quote_volume else None,
            "close_time": self.close_time,
            "price_change": float(self.price_change),
            "price_change_percent": float(self.price_change_percent),
            "is_green": self.is_green,
            "body_size": float(self.body_size),
            "upper_shadow": float(self.upper_shadow),
            "lower_shadow": float(self.lower_shadow),
            "body_ratio": float(self.body_ratio)
        }
@dataclass

class FundingRateData:
    """
    统一的资金费率数据格式
    Unified funding rate data format
    """
    symbol: str
    funding_rate: Decimal
    next_funding_time: datetime
    timestamp: datetime
    source: ExchangeType
    data_source: DataSource = DataSource.REST_API
    
    # 可选字段
    mark_price: Optional[Decimal] = None
    index_price: Optional[Decimal] = None
    estimated_rate: Optional[Decimal] = None
    funding_interval: Optional[int] = None  # 资金费率间隔（小时）
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保费率数据为Decimal类型
            if not isinstance(self.funding_rate, Decimal):
                self.funding_rate = Decimal(str(self.funding_rate))
                
            # 转换可选字段
            if self.mark_price is not None and not isinstance(self.mark_price, Decimal):
                self.mark_price = Decimal(str(self.mark_price))
            if self.index_price is not None and not isinstance(self.index_price, Decimal):
                self.index_price = Decimal(str(self.index_price))
            if self.estimated_rate is not None and not isinstance(self.estimated_rate, Decimal):
                self.estimated_rate = Decimal(str(self.estimated_rate))
                
        except (ValueError, TypeError) as e:
            logger.error(f"❌ FundingRateData数据转换失败: {e}")
            raise ValueError(f"Invalid funding rate data: {e}")
    
    @property
    def is_negative(self) -> bool:
        """是否为负费率"""
        return self.funding_rate < 0
    
    @property
    def rate_percentage(self) -> Decimal:
        """费率百分比"""
        return self.funding_rate * 100
    
    @property
    def annual_rate(self) -> Decimal:
        """年化费率（假设8小时收费一次）"""
        return self.funding_rate * 365 * 3  # 一天3次
    
    @property
    def time_to_next_funding(self) -> int:
        """距离下次资金费率的秒数"""
        return int((self.next_funding_time - datetime.now()).total_seconds())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "funding_rate": float(self.funding_rate),
            "next_funding_time": self.next_funding_time.isoformat(),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "mark_price": float(self.mark_price) if self.mark_price else None,
            "index_price": float(self.index_price) if self.index_price else None,
            "estimated_rate": float(self.estimated_rate) if self.estimated_rate else None,
            "funding_interval": self.funding_interval,
            "is_negative": self.is_negative,
            "rate_percentage": float(self.rate_percentage),
            "annual_rate": float(self.annual_rate),
            "time_to_next_funding": self.time_to_next_funding
        }

@dataclass
class OpenInterestData:
    """
    统一的持仓量数据格式
    Unified open interest data format
    """
    symbol: str
    open_interest: Decimal
    timestamp: datetime
    source: ExchangeType
    data_source: DataSource = DataSource.REST_API
    
    # 可选字段
    open_interest_value: Optional[Decimal] = None  # 持仓价值（USDT）
    currency: Optional[str] = None  # 持仓量单位
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保持仓量数据为Decimal类型
            if not isinstance(self.open_interest, Decimal):
                self.open_interest = Decimal(str(self.open_interest))
                
            # 转换可选字段
            if self.open_interest_value is not None and not isinstance(self.open_interest_value, Decimal):
                self.open_interest_value = Decimal(str(self.open_interest_value))
                
        except (ValueError, TypeError) as e:
            logger.error(f"❌ OpenInterestData数据转换失败: {e}")
            raise ValueError(f"Invalid open interest data: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "open_interest": float(self.open_interest),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "open_interest_value": float(self.open_interest_value) if self.open_interest_value else None,
            "currency": self.currency
        }


@dataclass
class OrderBookData:
    """
    统一的订单簿数据格式
    Unified order book data format
    """
    symbol: str
    bids: List[List[Decimal]]  # [[price, size], ...]
    asks: List[List[Decimal]]  # [[price, size], ...]
    timestamp: datetime
    source: ExchangeType
    data_source: DataSource = DataSource.WEBSOCKET
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保订单簿数据为Decimal类型
            self.bids = [[Decimal(str(price)), Decimal(str(size))] for price, size in self.bids]
            self.asks = [[Decimal(str(price)), Decimal(str(size))] for price, size in self.asks]
            
        except (ValueError, TypeError) as e:
            logger.error(f"❌ OrderBookData数据转换失败: {e}")
            raise ValueError(f"Invalid order book data: {e}")
    
    @property
    def best_bid(self) -> Optional[Decimal]:
        """最佳买价"""
        return self.bids[0][0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[Decimal]:
        """最佳卖价"""
        return self.asks[0][0] if self.asks else None
    
    @property
    def spread(self) -> Optional[Decimal]:
        """买卖价差"""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        """中间价"""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    def get_depth(self, levels: int = 5) -> Dict[str, Any]:
        """获取指定深度的订单簿"""
        return {
            "bids": [[float(price), float(size)] for price, size in self.bids[:levels]],
            "asks": [[float(price), float(size)] for price, size in self.asks[:levels]]
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "bids": [[float(price), float(size)] for price, size in self.bids],
            "asks": [[float(price), float(size)] for price, size in self.asks],
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "best_bid": float(self.best_bid) if self.best_bid else None,
            "best_ask": float(self.best_ask) if self.best_ask else None,
            "spread": float(self.spread) if self.spread else None,
            "mid_price": float(self.mid_price) if self.mid_price else None
        }


@dataclass
class TradeData:
    """
    统一的交易数据格式
    Unified trade data format
    """
    symbol: str
    trade_id: str
    price: Decimal
    size: Decimal
    side: str  # "buy" or "sell"
    timestamp: datetime
    source: ExchangeType
    data_source: DataSource = DataSource.WEBSOCKET
    
    # 可选字段
    is_maker: Optional[bool] = None
    
    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和转换"""
        try:
            # 确保交易数据为Decimal类型
            if not isinstance(self.price, Decimal):
                self.price = Decimal(str(self.price))
            if not isinstance(self.size, Decimal):
                self.size = Decimal(str(self.size))
                
        except (ValueError, TypeError) as e:
            logger.error(f"❌ TradeData数据转换失败: {e}")
            raise ValueError(f"Invalid trade data: {e}")
    
    @property
    def value(self) -> Decimal:
        """交易价值"""
        return self.price * self.size
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "trade_id": self.trade_id,
            "price": float(self.price),
            "size": float(self.size),
            "side": self.side,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "data_source": self.data_source.value,
            "is_maker": self.is_maker,
            "value": float(self.value)
        }


# 数据验证函数
def validate_symbol(symbol: str) -> bool:
    """
    验证交易对符号格式
    Validate trading pair symbol format
    """
    if not symbol or not isinstance(symbol, str):
        return False
    
    # 基本格式检查
    if len(symbol) < 3 or len(symbol) > 30:
        return False
    
    # 检查是否包含有效字符
    valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return all(c in valid_chars for c in symbol.upper())


def validate_decimal_precision(value: Decimal, max_precision: int = 8) -> bool:
    """
    验证Decimal精度
    Validate decimal precision
    """
    try:
        # 获取小数位数
        decimal_places = abs(value.as_tuple().exponent)
        return decimal_places <= max_precision
    except:
        return False


def sanitize_raw_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理原始数据中的敏感信息
    Sanitize sensitive information in raw data
    """
    sensitive_keys = ["api_key", "secret", "passphrase", "signature"]
    sanitized = raw_data.copy()
    
    for key in sensitive_keys:
        if key in sanitized:
            sanitized[key] = "***HIDDEN***"
    
    return sanitized