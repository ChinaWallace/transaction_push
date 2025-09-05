# -*- coding: utf-8 -*-
"""
市场异常监控相关数据模式
Market anomaly monitoring related schemas
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum

from .base import BaseResponse


class AnomalyType(Enum):
    """异常类型"""
    VOLATILITY = "volatility"  # 波动率异常
    VOLUME = "volume"  # 交易量异常
    OPEN_INTEREST = "open_interest"  # 持仓量异常
    COMBINED = "combined"  # 综合异常


class AnomalyLevel(Enum):
    """异常级别"""
    EXTREME = "extreme"  # 极端异常
    HIGH = "high"  # 高度异常
    MEDIUM = "medium"  # 中度异常
    LOW = "low"  # 轻度异常
    NORMAL = "normal"  # 正常


class TrendDirection(Enum):
    """趋势方向"""
    STRONG_UP = "strong_up"  # 强烈上涨
    UP = "up"  # 上涨
    SIDEWAYS = "sideways"  # 横盘
    DOWN = "down"  # 下跌
    STRONG_DOWN = "strong_down"  # 强烈下跌


class MarketAnomalyData(BaseModel):
    """市场异常数据"""
    symbol: str = Field(..., description="交易对")
    symbol_name: str = Field(..., description="币种名称")
    timestamp: datetime = Field(..., description="检测时间")
    
    # 价格数据
    current_price: float = Field(..., description="当前价格")
    price_change_24h: float = Field(..., description="24小时价格变化百分比")
    price_change_1h: float = Field(..., description="1小时价格变化百分比")
    
    # 波动率数据
    volatility_24h: float = Field(..., description="24小时波动率")
    volatility_avg_7d: float = Field(..., description="7天平均波动率")
    volatility_ratio: float = Field(..., description="波动率比值")
    volatility_anomaly_level: AnomalyLevel = Field(..., description="波动率异常级别")
    
    # 交易量数据
    volume_24h: float = Field(..., description="24小时交易量")
    volume_avg_7d: float = Field(..., description="7天平均交易量")
    volume_ratio: float = Field(..., description="交易量比值")
    volume_anomaly_level: AnomalyLevel = Field(..., description="交易量异常级别")
    
    # 持仓量数据（期货合约）
    open_interest: Optional[float] = Field(None, description="当前持仓量")
    oi_change_24h: Optional[float] = Field(None, description="24小时持仓量变化百分比")
    oi_avg_7d: Optional[float] = Field(None, description="7天平均持仓量")
    oi_ratio: Optional[float] = Field(None, description="持仓量比值")
    oi_anomaly_level: Optional[AnomalyLevel] = Field(None, description="持仓量异常级别")
    
    # 综合评估
    overall_anomaly_level: AnomalyLevel = Field(..., description="综合异常级别")
    trend_direction: TrendDirection = Field(..., description="趋势方向")
    anomaly_score: float = Field(..., description="异常评分", ge=0, le=100)
    
    # 推荐信息
    is_recommended: bool = Field(..., description="是否推荐")
    recommendation_reason: List[str] = Field(..., description="推荐原因")
    risk_factors: List[str] = Field(..., description="风险因素")
    
    # 技术指标
    rsi_14: Optional[float] = Field(None, description="RSI指标")
    ma_trend: Optional[str] = Field(None, description="均线趋势")
    support_level: Optional[float] = Field(None, description="支撑位")
    resistance_level: Optional[float] = Field(None, description="阻力位")


class MarketAnomalyRequest(BaseModel):
    """市场异常监控请求"""
    symbols: Optional[List[str]] = Field(None, description="指定监控的交易对列表")
    anomaly_types: List[AnomalyType] = Field(
        default=[AnomalyType.VOLATILITY, AnomalyType.VOLUME, AnomalyType.OPEN_INTEREST],
        description="监控的异常类型"
    )
    min_anomaly_level: AnomalyLevel = Field(
        default=AnomalyLevel.MEDIUM,
        description="最小异常级别"
    )
    min_volume_24h: float = Field(
        default=1000000,
        description="最小24小时交易量过滤"
    )
    only_recommended: bool = Field(
        default=True,
        description="是否只返回推荐的币种"
    )


class MarketAnomalyResponse(BaseResponse):
    """市场异常监控响应"""
    data: List[MarketAnomalyData] = Field(..., description="异常数据列表")
    summary: Dict[str, Any] = Field(..., description="汇总信息")
    
    
class AnomalySummary(BaseModel):
    """异常汇总信息"""
    total_symbols_checked: int = Field(..., description="检查的总币种数")
    anomalies_found: int = Field(..., description="发现的异常数量")
    recommended_count: int = Field(..., description="推荐币种数量")
    
    # 按异常级别分类
    by_anomaly_level: Dict[str, int] = Field(..., description="按异常级别分类统计")
    
    # 按趋势方向分类
    by_trend_direction: Dict[str, int] = Field(..., description="按趋势方向分类统计")
    
    # 按异常类型分类
    by_anomaly_type: Dict[str, int] = Field(..., description="按异常类型分类统计")
    
    # 最佳机会
    top_opportunities: List[str] = Field(..., description="最佳机会币种列表")
    
    # 风险警告
    high_risk_symbols: List[str] = Field(..., description="高风险币种列表")


class NotificationData(BaseModel):
    """通知数据"""
    title: str = Field(..., description="通知标题")
    message: str = Field(..., description="通知内容")
    priority: str = Field(..., description="优先级")
    symbols: List[str] = Field(..., description="相关币种")
    timestamp: datetime = Field(..., description="通知时间")