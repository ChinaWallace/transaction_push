# -*- coding: utf-8 -*-
"""
通知相关数据模式
Notification related schemas
"""

from pydantic import BaseModel, Field, validator
from typing import Dict, Any, Optional

from .base import BaseResponse


class NotificationRequest(BaseModel):
    """通知请求"""
    channel: str = Field(..., description="通知渠道")
    message: str = Field(..., description="通知消息")
    priority: Optional[str] = Field("normal", description="优先级")
    
    @validator('channel')
    def validate_channel(cls, v):
        valid_channels = ['feishu', 'wechat', 'telegram', 'email']
        if v not in valid_channels:
            raise ValueError(f"Invalid channel. Must be one of: {valid_channels}")
        return v


class NotificationResponse(BaseResponse):
    """通知响应"""
    data: Dict[str, Any] = Field(..., description="通知结果数据")
