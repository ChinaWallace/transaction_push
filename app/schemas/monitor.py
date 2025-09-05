# -*- coding: utf-8 -*-
"""
监控相关数据模式
Monitor related schemas
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime

from .base import BaseResponse


class MonitorStatusResponse(BaseResponse):
    """监控状态响应"""
    data: Dict[str, Any] = Field(..., description="监控状态数据")


class FundingRateData(BaseModel):
    """资金费率数据"""
    symbol: str = Field(..., description="交易对")
    funding_rate: float = Field(..., description="资金费率")
    funding_time: datetime = Field(..., description="费率时间")
    mark_price: Optional[float] = Field(None, description="标记价格")


class OpenInterestData(BaseModel):
    """持仓量数据"""
    symbol: str = Field(..., description="交易对")
    open_interest: float = Field(..., description="持仓量")
    open_interest_value: Optional[float] = Field(None, description="持仓价值")
    timestamp: datetime = Field(..., description="时间戳")


class VolumeAnomalyData(BaseModel):
    """成交量异常数据"""
    symbol: str = Field(..., description="交易对")
    volume_ratio: float = Field(..., description="成交量比率")
    anomaly_type: str = Field(..., description="异常类型")
    price_up: bool = Field(..., description="价格是否上涨")
    timestamp: datetime = Field(..., description="时间戳")
