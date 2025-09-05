# -*- coding: utf-8 -*-
"""
信号数据模型
Signal data models
"""

from sqlalchemy import Column, String, Integer, DateTime, Index, Text, Boolean
from sqlalchemy.dialects.mysql import DECIMAL, JSON
from typing import Dict, Any

from .base import BaseModel, StatusMixin


class TrendSignal(BaseModel, StatusMixin):
    """趋势信号模型"""
    
    __tablename__ = "trend_signal"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    signal_type = Column(String(50), nullable=False, comment="信号类型")
    signal_level = Column(String(20), nullable=False, comment="信号级别(strong/medium/weak/watch)")
    
    # 多周期趋势方向
    daily_trend = Column(String(10), comment="日线趋势(up/down/unclear)")
    h4_trend = Column(String(10), comment="4小时趋势(up/down/unclear)")
    h1_trend = Column(String(10), comment="1小时趋势(up/down/unclear)")
    m15_trend = Column(String(10), comment="15分钟趋势(up/down/unclear)")
    
    # 信号详情
    signal_combination = Column(String(20), comment="信号组合编号")
    strategy_advice = Column(Text, comment="策略建议")
    confidence_score = Column(DECIMAL(5, 4), comment="置信度分数")
    
    # 价格信息
    trigger_price = Column(DECIMAL(20, 8), comment="触发价格")
    timestamp = Column(DateTime, nullable=False, comment="信号时间")
    
    # 额外数据
    extra_data = Column(JSON, comment="额外数据")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_signal_level_timestamp', 'signal_level', 'timestamp'),
    )
    
    def set_extra_data(self, data: Dict[str, Any]):
        """设置额外数据"""
        self.extra_data = data
    
    def get_extra_data(self) -> Dict[str, Any]:
        """获取额外数据"""
        return self.extra_data or {}


class SignalHistory(BaseModel):
    """信号历史记录"""
    
    __tablename__ = "signal_history"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    signal_id = Column(Integer, nullable=False, comment="信号ID")
    change_type = Column(String(20), nullable=False, comment="变化类型(new/update/cancel)")
    
    # 变化前后对比
    previous_signal = Column(JSON, comment="变化前信号")
    current_signal = Column(JSON, comment="变化后信号")
    
    # 变化描述
    change_description = Column(Text, comment="变化描述")
    timestamp = Column(DateTime, nullable=False, comment="变化时间")
    
    # 创建索引
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_signal_id_timestamp', 'signal_id', 'timestamp'),
    )


class SuperTrendData(BaseModel):
    """SuperTrend指标数据"""
    
    __tablename__ = "supertrend_data"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    interval = Column(String(10), nullable=False, comment="时间间隔")
    timestamp = Column(DateTime, nullable=False, comment="数据时间")
    
    # SuperTrend指标值
    supertrend_value = Column(DECIMAL(20, 8), comment="SuperTrend值")
    is_uptrend = Column(Boolean, comment="是否上升趋势")
    trend_direction = Column(String(10), comment="趋势方向")
    
    # 计算参数
    period = Column(Integer, default=10, comment="计算周期")
    multiplier = Column(DECIMAL(5, 2), default=3.0, comment="ATR倍数")
    
    # 价格数据
    close_price = Column(DECIMAL(20, 8), comment="收盘价")
    atr_value = Column(DECIMAL(20, 8), comment="ATR值")
    
    # 创建复合索引
    __table_args__ = (
        Index('idx_symbol_interval_timestamp', 'symbol', 'interval', 'timestamp'),
    )


class SignalConfiguration(BaseModel, StatusMixin):
    """信号配置"""
    
    __tablename__ = "signal_configuration"
    
    name = Column(String(100), nullable=False, comment="配置名称")
    signal_type = Column(String(50), nullable=False, comment="信号类型")
    
    # 配置参数
    parameters = Column(JSON, comment="配置参数")
    thresholds = Column(JSON, comment="阈值设置")
    
    # 启用设置
    enabled_symbols = Column(JSON, comment="启用的交易对")
    enabled_intervals = Column(JSON, comment="启用的时间间隔")
    
    # 通知设置
    notification_enabled = Column(Boolean, default=True, comment="是否启用通知")
    notification_channels = Column(JSON, comment="通知渠道")
    
    # 描述
    description = Column(Text, comment="配置描述")
    
    def get_parameters(self) -> Dict[str, Any]:
        """获取配置参数"""
        return self.parameters or {}
    
    def get_thresholds(self) -> Dict[str, Any]:
        """获取阈值设置"""
        return self.thresholds or {}
    
    def get_enabled_symbols(self) -> list:
        """获取启用的交易对"""
        return self.enabled_symbols or []
    
    def get_enabled_intervals(self) -> list:
        """获取启用的时间间隔"""
        return self.enabled_intervals or []
    
    def get_notification_channels(self) -> list:
        """获取通知渠道"""
        return self.notification_channels or []
