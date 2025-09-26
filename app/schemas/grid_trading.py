# -*- coding: utf-8 -*-
"""
网格交易相关数据模型
Grid Trading Related Data Models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class GridTrendType(str, Enum):
    """网格趋势类型"""
    UPWARD = "upward"      # 向上趋势
    SIDEWAYS = "sideways"  # 震荡趋势
    DOWNWARD = "downward"  # 向下趋势


class GridOpportunityLevel(str, Enum):
    """网格机会等级"""
    EXCELLENT = "excellent"  # 优秀
    GOOD = "good"           # 良好
    MODERATE = "moderate"   # 一般
    POOR = "poor"          # 较差


class GridTradingMetrics(BaseModel):
    """网格交易指标"""
    volatility_24h: float = Field(..., description="24小时波动率")
    volume_24h: float = Field(..., description="24小时交易量(USDT)")
    volume_rank: int = Field(..., description="交易量排名")
    price_change_24h: float = Field(..., description="24小时价格变化(%)")
    price_change_7d: float = Field(..., description="7天价格变化(%)")
    atr_ratio: float = Field(..., description="ATR比率")
    liquidity_score: float = Field(..., description="流动性评分")


class GridTradingRange(BaseModel):
    """网格交易区间"""
    lower_bound: float = Field(..., description="下边界价格")
    upper_bound: float = Field(..., description="上边界价格")
    grid_count: int = Field(..., description="网格数量")
    grid_spacing: float = Field(..., description="网格间距(%)")
    position_size_per_grid: float = Field(..., description="每格仓位(USDT)")


class GridTradingRecommendation(BaseModel):
    """网格交易推荐"""
    symbol: str = Field(..., description="交易对")
    current_price: float = Field(..., description="当前价格")
    trend_type: GridTrendType = Field(..., description="趋势类型")
    opportunity_level: GridOpportunityLevel = Field(..., description="机会等级")
    
    # 交易指标
    metrics: GridTradingMetrics = Field(..., description="交易指标")
    
    # 推荐配置
    recommended_capital: float = Field(..., description="推荐资金(USDT)")
    position_percentage: float = Field(..., description="仓位比例(%)")
    trading_range: GridTradingRange = Field(..., description="交易区间")
    
    # 收益预期
    expected_daily_return: float = Field(..., description="预期日收益率(%)")
    expected_monthly_return: float = Field(..., description="预期月收益率(%)")
    risk_level: str = Field(..., description="风险等级")
    
    # 分析说明
    reasoning: str = Field(..., description="推荐理由")
    risk_warning: str = Field(..., description="风险提示")
    
    # 时间戳
    timestamp: datetime = Field(default_factory=datetime.now, description="生成时间")
    
    class Config:
        schema_extra = {
            "example": {
                "symbol": "ETH-USDT-SWAP",
                "current_price": 2500.0,
                "trend_type": "sideways",
                "opportunity_level": "good",
                "metrics": {
                    "volatility_24h": 0.045,
                    "volume_24h": 1500000000,
                    "volume_rank": 2,
                    "price_change_24h": 1.2,
                    "price_change_7d": -2.1,
                    "atr_ratio": 0.038,
                    "liquidity_score": 0.92
                },
                "recommended_capital": 3000,
                "position_percentage": 30,
                "trading_range": {
                    "lower_bound": 2300,
                    "upper_bound": 2700,
                    "grid_count": 20,
                    "grid_spacing": 1.0,
                    "position_size_per_grid": 150
                },
                "expected_daily_return": 0.8,
                "expected_monthly_return": 24.0,
                "risk_level": "中等",
                "reasoning": "ETH震荡趋势明显，波动率适中，交易量充足",
                "risk_warning": "注意突破风险，建议设置止损"
            }
        }


class GridTradingBatch(BaseModel):
    """网格交易批量推荐"""
    recommendations: List[GridTradingRecommendation] = Field(..., description="推荐列表")
    total_count: int = Field(..., description="总数量")
    excellent_count: int = Field(..., description="优秀机会数量")
    good_count: int = Field(..., description="良好机会数量")
    analysis_time: datetime = Field(default_factory=datetime.now, description="分析时间")
    market_summary: str = Field(..., description="市场总结")
    
    class Config:
        schema_extra = {
            "example": {
                "recommendations": [],
                "total_count": 5,
                "excellent_count": 2,
                "good_count": 3,
                "analysis_time": "2025-01-01T14:30:00Z",
                "market_summary": "当前市场震荡为主，适合网格交易"
            }
        }