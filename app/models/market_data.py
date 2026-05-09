# -*- coding: utf-8 -*-
"""
Market data database models.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import DECIMAL

from .base import BaseModel


class MarketData(BaseModel):
    """Raw market data payloads."""

    __tablename__ = "market_data"

    symbol = Column(String(40), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, default="binance")
    data_type = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    raw_data = Column(Text)

    __table_args__ = (
        Index("idx_symbol_timestamp", "symbol", "timestamp"),
        Index("idx_symbol_type_timestamp", "symbol", "data_type", "timestamp"),
    )


class KlineData(BaseModel):
    """Kline/candlestick data."""

    __tablename__ = "kline_data"

    symbol = Column(String(40), nullable=False, index=True)
    interval = Column(String(10), nullable=False)
    open_time = Column(DateTime, nullable=False)
    close_time = Column(DateTime, nullable=False)

    open_price = Column(DECIMAL(20, 8), nullable=False)
    high_price = Column(DECIMAL(20, 8), nullable=False)
    low_price = Column(DECIMAL(20, 8), nullable=False)
    close_price = Column(DECIMAL(20, 8), nullable=False)
    volume = Column(DECIMAL(20, 8), nullable=False)
    quote_volume = Column(DECIMAL(20, 8))

    trade_count = Column(Integer)
    taker_buy_volume = Column(DECIMAL(20, 8))
    taker_buy_quote_volume = Column(DECIMAL(20, 8))

    supertrend_value = Column(DECIMAL(20, 8))
    supertrend_direction = Column(String(10))

    sma_20 = Column(DECIMAL(20, 8))
    ema_20 = Column(DECIMAL(20, 8))
    rsi_14 = Column(DECIMAL(10, 4))

    __table_args__ = (
        Index("idx_symbol_interval_time", "symbol", "interval", "open_time"),
        Index("idx_symbol_close_time", "symbol", "close_time"),
    )

    @property
    def price_change(self) -> Decimal:
        if self.open_price and self.close_price:
            return self.close_price - self.open_price
        return Decimal(0)

    @property
    def price_change_percent(self) -> Decimal:
        if self.open_price and self.close_price and self.open_price != 0:
            return ((self.close_price - self.open_price) / self.open_price) * 100
        return Decimal(0)

    @property
    def is_green(self) -> bool:
        return self.close_price > self.open_price

    @property
    def body_size(self) -> Decimal:
        return abs(self.close_price - self.open_price)

    @property
    def upper_shadow(self) -> Decimal:
        return self.high_price - max(self.open_price, self.close_price)

    @property
    def lower_shadow(self) -> Decimal:
        return min(self.open_price, self.close_price) - self.low_price


class FundingRate(BaseModel):
    """Funding rate data."""

    __tablename__ = "funding_rate"

    symbol = Column(String(40), nullable=False, index=True)
    funding_time = Column(DateTime, nullable=False)
    funding_rate = Column(DECIMAL(10, 8), nullable=False)
    mark_price = Column(DECIMAL(20, 8))

    __table_args__ = (
        Index("idx_symbol_funding_time", "symbol", "funding_time"),
        Index("idx_funding_rate", "funding_rate"),
    )

    @property
    def is_negative(self) -> bool:
        return self.funding_rate < 0

    @property
    def rate_percentage(self) -> Decimal:
        return self.funding_rate * 100


class OpenInterest(BaseModel):
    """Open interest data."""

    __tablename__ = "open_interest"

    symbol = Column(String(40), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    open_interest = Column(DECIMAL(20, 8), nullable=False)
    open_interest_value = Column(DECIMAL(20, 8))

    __table_args__ = (
        Index("idx_symbol_timestamp", "symbol", "timestamp"),
    )


class VolumeData(BaseModel):
    """Volume data."""

    __tablename__ = "volume_data"

    symbol = Column(String(40), nullable=False, index=True)
    interval = Column(String(10), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    volume = Column(DECIMAL(20, 8), nullable=False)
    quote_volume = Column(DECIMAL(20, 8))
    trade_count = Column(Integer)

    volume_ratio = Column(DECIMAL(10, 4))
    is_volume_anomaly = Column(String(10))
    price_up = Column(String(10))

    __table_args__ = (
        Index("idx_symbol_interval_timestamp", "symbol", "interval", "timestamp"),
    )


class TradingPair(BaseModel):
    """Trading pair metadata."""

    __tablename__ = "trading_pairs"

    inst_id = Column(String(40), nullable=False, unique=True, index=True)
    inst_type = Column(String(10), nullable=False)
    base_ccy = Column(String(30), nullable=False)
    quote_ccy = Column(String(30), nullable=False)
    settle_ccy = Column(String(30))

    ct_val = Column(String(20))
    ct_mult = Column(String(20))
    ct_val_ccy = Column(String(30))

    min_sz = Column(String(30))
    lot_sz = Column(String(30))
    tick_sz = Column(String(30))

    state = Column(String(20))
    list_time = Column(BigInteger)
    exp_time = Column(BigInteger)

    is_active = Column(String(5), default="true")
    last_updated = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_inst_type_quote", "inst_type", "quote_ccy"),
        Index("idx_base_quote", "base_ccy", "quote_ccy"),
        Index("idx_state_active", "state", "is_active"),
    )
