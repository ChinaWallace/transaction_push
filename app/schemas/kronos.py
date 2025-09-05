# -*- coding: utf-8 -*-
"""
Kronos预测相关的数据模型
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class KronosPredictionRequest(BaseModel):
    """Kronos预测请求模型"""
    symbol: str = Field(..., description="交易对符号")
    lookback_periods: Optional[int] = Field(default=200, description="历史数据回看期数")
    prediction_horizon: Optional[int] = Field(default=24, description="预测时间范围（小时）")
    force_update: Optional[bool] = Field(default=False, description="是否强制更新预测")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "ETH-USDT-SWAP",
                "lookback_periods": 200,
                "prediction_horizon": 24,
                "force_update": False
            }
        }


class KronosBatchPredictionRequest(BaseModel):
    """Kronos批量预测请求模型"""
    symbols: List[str] = Field(..., description="交易对符号列表")
    lookback_periods: Optional[int] = Field(default=200, description="历史数据回看期数")
    prediction_horizon: Optional[int] = Field(default=24, description="预测时间范围（小时）")
    force_update: Optional[bool] = Field(default=False, description="是否强制更新预测")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbols": ["ETH-USDT-SWAP", "SOL-USDT-SWAP"],
                "lookback_periods": 200,
                "prediction_horizon": 24,
                "force_update": False
            }
        }


class PredictionDataPoint(BaseModel):
    """单个预测数据点"""
    timestamp: datetime = Field(..., description="时间戳")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: float = Field(..., description="成交量")


class KronosPredictionResult(BaseModel):
    """Kronos预测结果模型"""
    symbol: str = Field(..., description="交易对符号")
    timestamp: datetime = Field(..., description="预测生成时间")
    predictions: List[PredictionDataPoint] = Field(..., description="预测数据点列表")
    confidence: float = Field(..., ge=0.0, le=1.0, description="预测置信度")
    signal: str = Field(..., description="交易信号")
    price_change_pct: float = Field(..., description="预测价格变化百分比")
    volatility: float = Field(..., description="预测波动率")
    trend_direction: str = Field(..., description="趋势方向")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "ETH-USDT-SWAP",
                "timestamp": "2025-08-24T12:00:00Z",
                "predictions": [
                    {
                        "timestamp": "2025-08-24T13:00:00Z",
                        "open": 2650.0,
                        "high": 2680.0,
                        "low": 2640.0,
                        "close": 2670.0,
                        "volume": 1500000.0
                    }
                ],
                "confidence": 0.75,
                "signal": "buy",
                "price_change_pct": 0.025,
                "volatility": 0.08,
                "trend_direction": "bullish"
            }
        }


class KronosPredictionResponse(BaseModel):
    """Kronos预测响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: str = Field(default="预测生成成功", description="响应消息")
    data: Optional[KronosPredictionResult] = Field(None, description="预测结果数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "预测生成成功",
                "data": {
                    "symbol": "ETH-USDT-SWAP",
                    "timestamp": "2025-08-24T12:00:00Z",
                    "predictions": [],
                    "confidence": 0.75,
                    "signal": "buy",
                    "price_change_pct": 0.025,
                    "volatility": 0.08,
                    "trend_direction": "bullish"
                },
                "timestamp": "2025-08-24T12:00:00Z"
            }
        }


class KronosBatchPredictionResponse(BaseModel):
    """Kronos批量预测响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: str = Field(default="批量预测完成", description="响应消息")
    data: Dict[str, Optional[KronosPredictionResult]] = Field(default_factory=dict, description="批量预测结果")
    successful_count: int = Field(default=0, description="成功预测数量")
    failed_count: int = Field(default=0, description="失败预测数量")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")


class KronosConfigResponse(BaseModel):
    """Kronos配置响应模型"""
    status: str = Field(default="success", description="响应状态")
    data: Dict[str, Any] = Field(..., description="Kronos配置信息")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")


class KronosHealthResponse(BaseModel):
    """Kronos健康检查响应模型"""
    status: str = Field(..., description="服务状态")
    model_loaded: bool = Field(..., description="模型是否已加载")
    device: Optional[str] = Field(None, description="使用的计算设备")
    model_name: Optional[str] = Field(None, description="模型名称")
    cache_size: int = Field(default=0, description="缓存大小")
    last_prediction_time: Optional[datetime] = Field(None, description="最后预测时间")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间戳")


class TradingSignalWithKronos(BaseModel):
    """集成Kronos的交易信号模型"""
    symbol: str = Field(..., description="交易对符号")
    timestamp: datetime = Field(..., description="信号生成时间")
    
    # 传统技术分析信号
    technical_signal: str = Field(..., description="技术分析信号")
    technical_confidence: float = Field(..., description="技术分析置信度")
    
    # Kronos预测信号
    kronos_signal: Optional[str] = Field(None, description="Kronos预测信号")
    kronos_confidence: Optional[float] = Field(None, description="Kronos预测置信度")
    kronos_price_target: Optional[float] = Field(None, description="Kronos价格目标")
    
    # 综合信号
    final_signal: str = Field(..., description="最终综合信号")
    final_confidence: float = Field(..., description="最终信号置信度")
    signal_strength: str = Field(..., description="信号强度")
    
    # 风险管理
    stop_loss: Optional[float] = Field(None, description="止损价格")
    take_profit: Optional[float] = Field(None, description="止盈价格")
    position_size: Optional[float] = Field(None, description="建议仓位大小")
    
    # 额外信息
    reasoning: str = Field(..., description="信号生成原因")
    risk_level: str = Field(..., description="风险等级")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "ETH-USDT-SWAP",
                "timestamp": "2025-08-24T12:00:00Z",
                "technical_signal": "buy",
                "technical_confidence": 0.7,
                "kronos_signal": "strong_buy",
                "kronos_confidence": 0.8,
                "kronos_price_target": 2750.0,
                "final_signal": "strong_buy",
                "final_confidence": 0.85,
                "signal_strength": "强烈",
                "stop_loss": 2500.0,
                "take_profit": 2800.0,
                "position_size": 0.3,
                "reasoning": "技术分析显示突破关键阻力位，Kronos预测24小时内上涨3%",
                "risk_level": "中等"
            }
        }

class KronosIntegratedDecisionData(BaseModel):
    """Kronos集成决策数据模型"""
    symbol: str = Field(..., description="交易对符号")
    timestamp: datetime = Field(..., description="决策生成时间")
    
    # Kronos预测结果
    kronos_confidence: float = Field(..., description="Kronos预测置信度")
    kronos_signal_strength: str = Field(..., description="Kronos信号强度")
    kronos_predicted_change: Optional[float] = Field(None, description="Kronos预测价格变化")
    
    # 传统分析结果
    technical_signal: str = Field(..., description="技术分析信号")
    technical_confidence: float = Field(..., description="技术分析置信度")
    
    # 持仓分析结果
    position_recommendation: str = Field(..., description="持仓建议")
    position_risk: str = Field(..., description="持仓风险等级")
    
    # 综合决策
    final_action: str = Field(..., description="最终交易行动")
    final_confidence: float = Field(..., description="最终决策置信度")
    signal_confluence: float = Field(..., description="信号一致性评分")
    
    # 风险管理
    entry_price: Optional[float] = Field(None, description="建议入场价格")
    stop_loss: Optional[float] = Field(None, description="止损价格")
    take_profit: Optional[float] = Field(None, description="止盈价格")
    position_size: float = Field(..., description="建议仓位大小")
    
    # 市场状态和决策依据
    market_regime: str = Field(..., description="市场状态")
    reasoning: str = Field(..., description="决策依据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT",
                "timestamp": "2025-08-24T12:00:00Z",
                "kronos_confidence": 0.82,
                "kronos_signal_strength": "强",
                "kronos_predicted_change": 0.035,
                "technical_signal": "bullish",
                "technical_confidence": 0.75,
                "position_recommendation": "加仓",
                "position_risk": "中等",
                "final_action": "强烈买入",
                "final_confidence": 0.85,
                "signal_confluence": 0.88,
                "entry_price": 65000.0,
                "stop_loss": 63000.0,
                "take_profit": 68000.0,
                "position_size": 0.25,
                "market_regime": "上涨趋势",
                "reasoning": "Kronos预测: +3.50% (置信度: 0.82, 信号强度: 强) | 技术分析: bullish | 持仓建议: 加仓 | 信号一致性: 0.88 | 综合决策: 强烈买入"
            }
        }


class KronosIntegratedDecisionResponse(BaseModel):
    """Kronos集成决策响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: str = Field(default="Kronos集成决策分析完成", description="响应消息")
    data: Optional[KronosIntegratedDecisionData] = Field(None, description="集成决策数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "BTC-USDT的Kronos集成决策分析完成",
                "data": {
                    "symbol": "BTC-USDT",
                    "timestamp": "2025-08-24T12:00:00Z",
                    "kronos_confidence": 0.82,
                    "kronos_signal_strength": "强",
                    "final_action": "强烈买入",
                    "final_confidence": 0.85
                },
                "timestamp": "2025-08-24T12:00:00Z"
            }
        }


class KronosStrongSignalData(BaseModel):
    """Kronos强信号数据模型"""
    symbol: str = Field(..., description="交易对符号")
    action: str = Field(..., description="交易行动")
    confidence: float = Field(..., description="综合置信度")
    kronos_confidence: float = Field(..., description="Kronos置信度")
    signal_strength: str = Field(..., description="信号强度")
    signal_confluence: float = Field(..., description="信号一致性")
    reasoning: str = Field(..., description="决策依据")


class KronosMarketRegimeData(BaseModel):
    """Kronos市场状态数据模型"""
    symbol: str = Field(..., description="交易对符号")
    market_regime: str = Field(..., description="市场状态")
    kronos_confidence: float = Field(..., description="Kronos置信度")
    final_action: str = Field(..., description="最终行动")