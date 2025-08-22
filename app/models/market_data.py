# -*- coding: utf-8 -*-
"""
市场数据模型
Market data models
"""

from sqlalchemy import Column, String, Float, Integer, DateTime, Index, BigInteger, Text
from sqlalchemy.dialects.mysql import DECIMAL
from decimal import Decimal
from datetime import datetime
from typing import Optional

from .base import BaseModel


class MarketData(BaseModel):
    """市场数据基础模型"""
    
    __tablename__ = "market_data"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    exchange = Column(String(20), nullable=False, default="binance", comment="交易所")
    data_type = Column(String(20), nullable=False, comment="数据类型")
    timestamp = Column(DateTime, nullable=False, index=True, comment="数据时间戳")
    raw_data = Column(Text, comment="原始数据(JSON格式)")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_symbol_type_timestamp', 'symbol', 'data_type', 'timestamp'),
    )


class KlineData(BaseModel):
    """K线数据模型"""
    
    __tablename__ = "kline_data"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    interval = Column(String(10), nullable=False, comment="时间间隔")
    open_time = Column(DateTime, nullable=False, comment="开盘时间")
    close_time = Column(DateTime, nullable=False, comment="收盘时间")
    
    # OHLCV数据
    open_price = Column(DECIMAL(20, 8), nullable=False, comment="开盘价")
    high_price = Column(DECIMAL(20, 8), nullable=False, comment="最高价")
    low_price = Column(DECIMAL(20, 8), nullable=False, comment="最低价")
    close_price = Column(DECIMAL(20, 8), nullable=False, comment="收盘价")
    volume = Column(DECIMAL(20, 8), nullable=False, comment="成交量")
    quote_volume = Column(DECIMAL(20, 8), comment="成交额")
    
    # 交易统计
    trade_count = Column(Integer, comment="交易次数")
    taker_buy_volume = Column(DECIMAL(20, 8), comment="主动买入成交量")
    taker_buy_quote_volume = Column(DECIMAL(20, 8), comment="主动买入成交额")
    
    # 技术指标字段
    supertrend_value = Column(DECIMAL(20, 8), comment="SuperTrend值")
    supertrend_direction = Column(String(10), comment="SuperTrend方向(up/down)")
    
    # 其他技术指标
    sma_20 = Column(DECIMAL(20, 8), comment="20周期简单移动平均")
    ema_20 = Column(DECIMAL(20, 8), comment="20周期指数移动平均")
    rsi_14 = Column(DECIMAL(10, 4), comment="14周期RSI")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_interval_time', 'symbol', 'interval', 'open_time'),
        Index('idx_symbol_close_time', 'symbol', 'close_time'),
    )
    
    @property
    def price_change(self) -> Decimal:
        """价格变化"""
        if self.open_price and self.close_price:
            return self.close_price - self.open_price
        return Decimal(0)
    
    @property
    def price_change_percent(self) -> Decimal:
        """价格变化百分比"""
        if self.open_price and self.close_price and self.open_price != 0:
            return ((self.close_price - self.open_price) / self.open_price) * 100
        return Decimal(0)
    
    @property
    def is_green(self) -> bool:
        """是否为阳线"""
        return self.close_price > self.open_price
    
    @property
    def body_size(self) -> Decimal:
        """实体大小"""
        return abs(self.close_price - self.open_price)
    
    @property
    def upper_shadow(self) -> Decimal:
        """上影线长度"""
        return self.high_price - max(self.open_price, self.close_price)
    
    @property
    def lower_shadow(self) -> Decimal:
        """下影线长度"""
        return min(self.open_price, self.close_price) - self.low_price


class FundingRate(BaseModel):
    """资金费率模型"""
    
    __tablename__ = "funding_rate"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    funding_time = Column(DateTime, nullable=False, comment="费率时间")
    funding_rate = Column(DECIMAL(10, 8), nullable=False, comment="资金费率")
    mark_price = Column(DECIMAL(20, 8), comment="标记价格")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_funding_time', 'symbol', 'funding_time'),
        Index('idx_funding_rate', 'funding_rate'),
    )
    
    @property
    def is_negative(self) -> bool:
        """是否为负费率"""
        return self.funding_rate < 0
    
    @property
    def rate_percentage(self) -> Decimal:
        """费率百分比"""
        return self.funding_rate * 100


class OpenInterest(BaseModel):
    """持仓量数据模型"""
    
    __tablename__ = "open_interest"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    timestamp = Column(DateTime, nullable=False, comment="时间戳")
    open_interest = Column(DECIMAL(20, 8), nullable=False, comment="持仓量")
    open_interest_value = Column(DECIMAL(20, 8), comment="持仓价值(USDT)")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )


class VolumeData(BaseModel):
    """成交量数据模型"""
    
    __tablename__ = "volume_data"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    interval = Column(String(10), nullable=False, comment="时间间隔")
    timestamp = Column(DateTime, nullable=False, comment="时间戳")
    volume = Column(DECIMAL(20, 8), nullable=False, comment="成交量")
    quote_volume = Column(DECIMAL(20, 8), comment="成交额")
    trade_count = Column(Integer, comment="交易次数")
    
    # 庄神指标相关字段
    volume_ratio = Column(DECIMAL(10, 4), comment="成交量比率")
    is_volume_anomaly = Column(String(10), comment="成交量异常类型(strong/normal/none)")
    price_up = Column(String(10), comment="价格是否上涨(yes/no)")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_interval_timestamp', 'symbol', 'interval', 'timestamp'),
    )
