# -*- coding: utf-8 -*-
"""
趋势分析相关数据模式
Trend analysis related schemas
"""

from pydantic import BaseModel, Field, validator
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base import BaseResponse, KlineDataSchema


class TrendAnalysisRequest(BaseModel):
    """趋势分析请求"""
    timeframe_data: Dict[str, List[KlineDataSchema]] = Field(
        ..., 
        description="多时间周期K线数据"
    )
    
    @validator('timeframe_data')
    def validate_timeframe_data(cls, v):
        required_timeframes = ['1d', '4h', '1h', '15m']
        for tf in required_timeframes:
            if tf not in v:
                raise ValueError(f"Missing required timeframe: {tf}")
            if not v[tf]:
                raise ValueError(f"Empty data for timeframe: {tf}")
        return v


class BatchAnalysisRequest(BaseModel):
    """批量分析请求"""
    symbols: List[str] = Field(
        ..., 
        description="交易对列表",
        min_items=1,
        max_items=20
    )
    
    @validator('symbols')
    def validate_symbols(cls, v):
        for symbol in v:
            if not symbol or not isinstance(symbol, str):
                raise ValueError("Invalid symbol in list")
            if not symbol.endswith('USDT'):
                raise ValueError(f"Symbol {symbol} must end with USDT")
        return v


class TrendData(BaseModel):
    """趋势数据"""
    daily: str = Field(..., description="日线趋势")
    h4: str = Field(..., description="4小时趋势")
    h1: str = Field(..., description="1小时趋势") 
    m15: str = Field(..., description="15分钟趋势")


class SignalCombinationData(BaseModel):
    """信号组合数据"""
    combination_id: str = Field(..., description="组合ID")
    name: str = Field(..., description="信号名称")
    strategy: str = Field(..., description="策略建议")
    level: str = Field(..., description="信号级别")
    description: str = Field(..., description="信号描述")


class TrendAnalysisData(BaseModel):
    """趋势分析结果数据"""
    symbol: str = Field(..., description="交易对")
    timestamp: datetime = Field(..., description="分析时间")
    trends: TrendData = Field(..., description="各周期趋势")
    signal_combination: SignalCombinationData = Field(..., description="信号组合")
    signal_level: str = Field(..., description="信号级别")
    strategy_advice: str = Field(..., description="策略建议")
    confidence_score: float = Field(..., description="置信度分数", ge=0, le=1)
    current_price: Optional[float] = Field(None, description="当前价格")
    should_notify: bool = Field(..., description="是否应该通知")


class TrendAnalysisResponse(BaseResponse):
    """趋势分析响应"""
    data: TrendAnalysisData = Field(..., description="分析结果")


class HistoricalSignalData(BaseModel):
    """历史信号数据"""
    timestamp: datetime = Field(..., description="信号时间")
    signal_data: TrendAnalysisData = Field(..., description="信号数据")
    change_type: str = Field(..., description="变化类型")
    previous_signal: Optional[str] = Field(None, description="前一个信号")
    current_signal: str = Field(..., description="当前信号")


class HistoricalAnalysisResponse(BaseResponse):
    """历史分析响应"""
    data: Dict[str, Any] = Field(..., description="历史分析数据")


class SignalCombinationsResponse(BaseResponse):
    """信号组合定义响应"""
    data: Dict[str, SignalCombinationData] = Field(..., description="信号组合定义")


class NotificationFormatResponse(BaseResponse):
    """通知格式化响应"""
    data: Dict[str, Any] = Field(..., description="格式化的通知数据")


class BatchAnalysisResponse(BaseResponse):
    """批量分析响应"""
    data: Dict[str, Any] = Field(..., description="批量分析结果")
    statistics: Dict[str, int] = Field(..., description="统计信息")
