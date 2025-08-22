# -*- coding: utf-8 -*-
"""
基础数据模式
Base data schemas
"""

from pydantic import BaseModel, Field
from typing import Any, Optional, Dict, List
from datetime import datetime


class BaseResponse(BaseModel):
    """基础响应模型"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间")


class PaginatedResponse(BaseResponse):
    """分页响应模型"""
    data: List[Any] = Field(..., description="数据列表")
    pagination: Dict[str, Any] = Field(..., description="分页信息")


class ErrorResponse(BaseResponse):
    """错误响应模型"""
    error_code: Optional[str] = Field(None, description="错误代码")
    error_detail: Optional[str] = Field(None, description="错误详情")


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="健康状态")
    timestamp: datetime = Field(..., description="检查时间")
    checks: Dict[str, str] = Field(..., description="各组件检查结果")


class KlineDataSchema(BaseModel):
    """K线数据模式"""
    open_time: datetime = Field(..., description="开盘时间")
    close_time: datetime = Field(..., description="收盘时间")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")
    volume: float = Field(..., description="成交量")
    quote_volume: Optional[float] = Field(None, description="成交额")
    trade_count: Optional[int] = Field(None, description="交易次数")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
