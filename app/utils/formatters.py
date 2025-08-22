# -*- coding: utf-8 -*-
"""
格式化工具函数
Formatting utility functions
"""

from typing import Any, Dict
from decimal import Decimal
from datetime import datetime


def format_currency(amount: float, currency: str = "USDT", decimals: int = 4) -> str:
    """格式化货币金额"""
    return f"{amount:,.{decimals}f} {currency}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比"""
    return f"{value:.{decimals}f}%"


def format_notification(data: Dict[str, Any]) -> str:
    """格式化通知消息"""
    return f"Notification: {data}"
