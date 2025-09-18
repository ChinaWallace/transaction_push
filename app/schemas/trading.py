# -*- coding: utf-8 -*-
"""
交易相关数据模式
Trading related data schemas
"""

from pydantic import BaseModel, Field
from typing import Any, Optional, Dict, List, Union
from datetime import datetime
from enum import Enum


class AnalysisType(Enum):
    """分析类型枚举"""
    KRONOS_ONLY = "kronos_only"
    TECHNICAL_ONLY = "technical_only"
    ML_ONLY = "ml_only"
    INTEGRATED = "integrated"


class SignalStrength(Enum):
    """信号强度枚举"""
    VERY_WEAK = "VERY_WEAK"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    VERY_STRONG = "VERY_STRONG"
    
    @classmethod
    def from_confidence(cls, confidence: float) -> 'SignalStrength':
        """根据置信度返回信号强度"""
        if confidence >= 0.8:
            return cls.VERY_STRONG
        elif confidence >= 0.6:
            return cls.STRONG
        elif confidence >= 0.4:
            return cls.MODERATE
        elif confidence >= 0.2:
            return cls.WEAK
        else:
            return cls.VERY_WEAK


class TradingAction(Enum):
    """交易动作枚举"""
    BUY = "买入"
    SELL = "卖出"
    HOLD = "持有"
    STRONG_BUY = "强烈买入"
    STRONG_SELL = "强烈卖出"


class TradingSignal(BaseModel):
    """交易信号模型 - 增强版包含详细操作建议"""
    symbol: str = Field(..., description="交易对符号")
    final_action: str = Field(..., description="最终交易建议")
    final_confidence: float = Field(..., description="综合置信度", ge=0, le=1)
    signal_strength: SignalStrength = Field(..., description="信号强度")
    reasoning: str = Field(..., description="决策推理")
    timestamp: datetime = Field(default_factory=datetime.now, description="信号生成时间")
    
    # 详细操作建议 (新增)
    operation_advice: Optional[str] = Field(None, description="详细操作建议，包含具体价位")
    
    # 各模块分析结果
    kronos_result: Optional[Union[Dict[str, Any], Any]] = Field(None, description="Kronos分析结果")
    technical_result: Optional[Union[Dict[str, Any], Any]] = Field(None, description="技术分析结果")
    ml_result: Optional[Union[Dict[str, Any], Any]] = Field(None, description="ML分析结果")
    
    # 置信度分解 - 支持复杂结构以显示完整分析详情
    confidence_breakdown: Dict[str, Any] = Field(default_factory=dict, description="置信度分解详情，包含原始评分、应用权重、加权置信度等")
    key_factors: List[str] = Field(default_factory=list, description="关键因素")
    
    # 技术指标和详细分析 (新增)
    technical_indicators: Dict[str, Any] = Field(default_factory=dict, description="技术指标")
    technical_details: Dict[str, Any] = Field(default_factory=dict, description="详细技术分析")
    volume_analysis: Dict[str, Any] = Field(default_factory=dict, description="量价分析结果")
    
    # 价格信息 (扩展)
    entry_price: Optional[float] = Field(None, description="建议入场价格")
    current_price: Optional[float] = Field(None, description="当前价格")
    stop_loss: Optional[float] = Field(None, description="止损价格")
    take_profit: Optional[float] = Field(None, description="止盈价格")
    
    # 支撑阻力位 (新增)
    support_level: Optional[float] = Field(None, description="支撑位")
    resistance_level: Optional[float] = Field(None, description="阻力位")
    
    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class TradingAnalysisRequest(BaseModel):
    """交易分析请求"""
    symbol: str = Field(..., description="交易对符号", example="BTC-USDT-SWAP")
    analysis_type: AnalysisType = Field(default=AnalysisType.INTEGRATED, description="分析类型")
    force_update: bool = Field(default=False, description="是否强制更新")


class TradingSignalResponse(BaseModel):
    """交易信号响应"""
    symbol: str = Field(..., description="交易对符号")
    final_action: str = Field(..., description="最终交易建议")
    final_confidence: float = Field(..., description="综合置信度")
    signal_strength: str = Field(..., description="信号强度")
    reasoning: str = Field(..., description="决策推理")
    timestamp: datetime = Field(..., description="信号生成时间")
    
    # 置信度分解
    confidence_breakdown: Optional[Dict[str, float]] = Field(None, description="置信度分解")
    key_factors: Optional[List[str]] = Field(None, description="关键因素")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "final_action": "强烈买入",
                "final_confidence": 0.782,
                "signal_strength": "STRONG",
                "reasoning": "多重AI信号高度一致看多",
                "timestamp": "2025-01-01T14:30:00Z"
            }
        }
    }


class BatchAnalysisRequest(BaseModel):
    """批量分析请求"""
    symbols: List[str] = Field(..., description="交易对列表")
    analysis_type: AnalysisType = Field(default=AnalysisType.INTEGRATED, description="分析类型")
    max_concurrent: int = Field(default=5, description="最大并发数", ge=1, le=20)


class CoreSymbolsAnalysisResponse(BaseModel):
    """核心币种分析响应"""
    status: str = Field(..., description="分析状态")
    total_symbols: int = Field(..., description="总币种数")
    analyzed_symbols: int = Field(..., description="已分析币种数")
    signals: List[TradingSignalResponse] = Field(..., description="交易信号列表")
    timestamp: datetime = Field(..., description="分析时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TechnicalIndicators(BaseModel):
    """技术指标模型"""
    rsi: Optional[float] = Field(None, description="RSI指标")
    macd: Optional[float] = Field(None, description="MACD指标")
    macd_signal: Optional[float] = Field(None, description="MACD信号线")
    macd_histogram: Optional[float] = Field(None, description="MACD柱状图")
    bb_upper: Optional[float] = Field(None, description="布林带上轨")
    bb_middle: Optional[float] = Field(None, description="布林带中轨")
    bb_lower: Optional[float] = Field(None, description="布林带下轨")
    sma_20: Optional[float] = Field(None, description="20日简单移动平均")
    ema_12: Optional[float] = Field(None, description="12日指数移动平均")
    ema_26: Optional[float] = Field(None, description="26日指数移动平均")


class MarketData(BaseModel):
    """市场数据模型"""
    symbol: str = Field(..., description="交易对符号")
    price: float = Field(..., description="当前价格")
    volume_24h: float = Field(..., description="24小时成交量")
    change_24h: float = Field(..., description="24小时涨跌幅")
    high_24h: float = Field(..., description="24小时最高价")
    low_24h: float = Field(..., description="24小时最低价")
    funding_rate: Optional[float] = Field(None, description="资金费率")
    open_interest: Optional[float] = Field(None, description="持仓量")
    timestamp: datetime = Field(default_factory=datetime.now, description="数据时间")
    
    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class PositionInfo(BaseModel):
    """持仓信息模型"""
    symbol: str = Field(..., description="交易对符号")
    side: str = Field(..., description="持仓方向", pattern="^(long|short)$")
    size: float = Field(..., description="持仓数量")
    entry_price: float = Field(..., description="开仓价格")
    mark_price: float = Field(..., description="标记价格")
    unrealized_pnl: float = Field(..., description="未实现盈亏")
    percentage: float = Field(..., description="盈亏百分比")
    margin: float = Field(..., description="保证金")
    timestamp: datetime = Field(default_factory=datetime.now, description="更新时间")
    
    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class TradingRecommendation(BaseModel):
    """交易建议模型"""
    action: TradingAction = Field(..., description="建议动作")
    confidence: float = Field(..., description="置信度", ge=0, le=1)
    reasoning: str = Field(..., description="建议理由")
    risk_level: str = Field(..., description="风险等级")
    stop_loss: Optional[float] = Field(None, description="止损价格")
    take_profit: Optional[float] = Field(None, description="止盈价格")
    position_size: Optional[float] = Field(None, description="建议仓位大小")