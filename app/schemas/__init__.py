# -*- coding: utf-8 -*-
"""
数据模式定义
Data schemas for request/response models
"""

from .trend import *
from .monitor import *
from .notification import *
from .news import *
from .base import *

__all__ = [
    "TrendAnalysisRequest",
    "TrendAnalysisResponse", 
    "BatchAnalysisRequest",
    "MonitorStatusResponse",
    "NotificationRequest",
    "NotificationResponse",
    "NewsItem",
    "NewsAnalysisResult",
    "NewsRequest",
    "NewsAnalysisRequest",
    "NewsResponse",
    "NewsAnalysisResponse",
    "KronosNewsAnalysisData",
    "BaseResponse"
]
