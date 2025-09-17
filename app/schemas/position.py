# -*- coding: utf-8 -*-
"""
持仓分析相关数据模型
Position Analysis Related Data Models
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class PositionRecommendation(Enum):
    """持仓建议枚举"""
    HOLD = "持有"
    REDUCE = "减仓"
    INCREASE = "加仓"
    CLOSE = "平仓"
    HEDGE = "对冲"
    REBALANCE = "重新平衡"


class PositionRisk(Enum):
    """持仓风险等级"""
    LOW = "低风险"
    MEDIUM = "中等风险"
    HIGH = "高风险"
    CRITICAL = "极高风险"


class RiskLevel(Enum):
    """风险等级枚举"""
    VERY_LOW = "极低风险"
    LOW = "低风险"
    MEDIUM = "中等风险"
    HIGH = "高风险"
    VERY_HIGH = "极高风险"


class PositionAnalysisRequest(BaseModel):
    """持仓分析请求"""
    force_update: bool = Field(default=False, description="是否强制更新")
    include_recommendations: bool = Field(default=True, description="是否包含建议")
    include_risk_assessment: bool = Field(default=True, description="是否包含风险评估")


class AccountSummary(BaseModel):
    """账户摘要"""
    total_equity: float = Field(..., description="总权益 (USDT)")
    initial_capital: float = Field(..., description="初始本金 (USDT)")
    total_positions: int = Field(..., description="持仓数量")
    total_unrealized_pnl: float = Field(..., description="未实现盈亏 (USDT)")
    total_position_value: float = Field(..., description="持仓总价值 (USDT)")
    total_spot_value: float = Field(..., description="现货总价值 (USDT)")
    utilization_rate: float = Field(..., description="资金利用率 (%)")
    pnl_percentage: float = Field(..., description="盈亏比例 (%)")
    overall_pnl: float = Field(..., description="整体盈亏 (USDT)")
    overall_pnl_percentage: float = Field(..., description="整体盈亏比例 (%)")
    available_balance: float = Field(..., description="可用余额 (USDT)")
    leverage_ratio: float = Field(..., description="杠杆比率")
    risk_level: str = Field(..., description="风险等级")
    health_score: int = Field(..., description="健康评分 (0-100)")


class PositionDetail(BaseModel):
    """持仓详情"""
    symbol: str = Field(..., description="交易对")
    side: str = Field(..., description="方向 (long/short)")
    size: float = Field(..., description="持仓数量")
    position_value_usd: float = Field(..., description="持仓价值 (USD)")
    unrealized_pnl: float = Field(..., description="未实现盈亏 (USD)")
    unrealized_pnl_ratio: float = Field(..., description="未实现盈亏比例")
    actual_loss_ratio: float = Field(..., description="实际亏损比例")
    position_weight: float = Field(..., description="持仓权重 (%)")
    risk_exposure: float = Field(..., description="风险敞口")
    leverage: float = Field(..., description="杠杆倍数")
    avg_price: float = Field(..., description="平均价格")
    mark_price: float = Field(..., description="标记价格")
    health_score: int = Field(..., description="健康评分 (0-100)")
    risk_level: str = Field(..., description="风险等级")
    market_trend: str = Field(..., description="市场趋势")
    recommendation: str = Field(..., description="操作建议")
    recommendation_reason: str = Field(..., description="建议原因")


class RiskAssessment(BaseModel):
    """风险评估"""
    overall_risk: str = Field(..., description="整体风险等级")
    risk_score: int = Field(..., description="风险评分 (0-100)")
    risk_factors: List[str] = Field(..., description="风险因素列表")
    concentration_risk: float = Field(..., description="集中度风险 (%)")
    leverage_risk: float = Field(..., description="杠杆风险")
    correlation_risk: float = Field(..., description="相关性风险")
    pnl_percentage: float = Field(..., description="盈亏比例 (%)")
    total_positions: int = Field(..., description="总持仓数")
    long_positions: int = Field(..., description="多头持仓数")
    short_positions: int = Field(..., description="空头持仓数")


class PositionRecommendationDetail(BaseModel):
    """持仓建议详情"""
    type: str = Field(..., description="建议类型")
    title: str = Field(..., description="建议标题")
    description: str = Field(..., description="建议描述")
    actions: List[str] = Field(..., description="具体行动")
    priority: str = Field(..., description="优先级 (high/medium/low)")


class RiskAlert(BaseModel):
    """风险警报"""
    type: str = Field(..., description="警报类型")
    level: str = Field(..., description="警报级别")
    symbol: str = Field(..., description="交易对")
    message: str = Field(..., description="警报消息")
    suggestion: str = Field(..., description="建议")


class PositionAnalysisResponse(BaseModel):
    """持仓分析响应"""
    timestamp: datetime = Field(..., description="分析时间")
    account_summary: AccountSummary = Field(..., description="账户摘要")
    position_analysis: List[PositionDetail] = Field(..., description="持仓分析列表")
    risk_assessment: RiskAssessment = Field(..., description="风险评估")
    recommendations: List[PositionRecommendationDetail] = Field(..., description="建议列表")
    alerts: List[RiskAlert] = Field(..., description="警报列表")
    overall_score: int = Field(..., description="整体评分 (0-100)")
    status: str = Field(default="success", description="分析状态")


class ComprehensivePositionAnalysis(BaseModel):
    """综合持仓分析结果"""
    timestamp: datetime = Field(..., description="分析时间")
    total_positions: int = Field(..., description="持仓总数")
    total_value_usdt: float = Field(..., description="持仓总价值 (USDT)")
    total_pnl_percent: float = Field(..., description="总盈亏比例 (%)")
    overall_pnl_percent: float = Field(..., description="整体盈亏比例 (基于本金) (%)")
    risk_level: str = Field(..., description="风险等级")
    health_score: int = Field(..., description="健康评分 (0-100)")
    positions: List[Dict[str, Any]] = Field(..., description="持仓列表")
    recommendations: List[str] = Field(..., description="建议列表")
    urgent_actions: List[str] = Field(..., description="紧急行动列表")
    
    class Config:
        schema_extra = {
            "example": {
                "timestamp": "2025-01-01T14:30:00Z",
                "total_positions": 5,
                "total_value_usdt": 25000.0,
                "total_pnl_percent": -2.5,
                "overall_pnl_percent": 8.3,
                "risk_level": "中等风险",
                "health_score": 75,
                "positions": [
                    {
                        "symbol": "BTC-USDT-SWAP",
                        "side": "long",
                        "unrealized_pnl": -500.0,
                        "health_score": 70
                    }
                ],
                "recommendations": [
                    "建议减少BTC持仓风险",
                    "考虑增加对冲仓位"
                ],
                "urgent_actions": []
            }
        }