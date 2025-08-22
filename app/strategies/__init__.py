# -*- coding: utf-8 -*-
"""
策略框架模块
Strategy framework module inspired by freqtrade
"""

from .base_strategy import BaseStrategy
from .supertrend_strategy import SuperTrendStrategy

__all__ = [
    'BaseStrategy',
    'SuperTrendStrategy'
]