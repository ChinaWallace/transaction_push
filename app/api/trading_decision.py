# -*- coding: utf-8 -*-
"""
交易决策API
Trading Decision API endpoints
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.trading_decision_service import TradingDecisionService, MarketAnalysis, TradingRecommendation
from app.services.trading_notification_service import TradingNotificationService
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()


class TradingRecommendationRequest(BaseModel):
    """交易建议请求模型"""
    symbol: str = Field(..., description="交易对")
    account_balance: float = Field(default=10000, description="账户余额")
    current_positions: Optional[Dict[str, float]] = Field(default=None, description="当前持仓")
    send_notification: bool = Field(default=False, description="是否发送通知")


class MarketAnalysisRequest(BaseModel):
    """市场分析请求模型"""
    symbol: str = Field(..., description="交易对")
    send_notification: bool = Field(default=False, description="是否发送通知")


class BatchAnalysisRequest(BaseModel):
    """批量分析请求模型"""
    symbols: List[str] = Field(..., description="交易对列表")
    account_balance: float = Field(default=10000, description="账户余额")
    send_notifications: bool = Field(default=False, description="是否发送通知")


class TradingRecommendationResponse(BaseResponse):
    """交易建议响应模型"""
    symbol: str
    action: str
    confidence: float
    position_size_percent: float
    leverage: float
    stop_loss_percent: float
    take_profit_percent: float
    risk_level: str
    reasoning: str
    support_levels: List[float]
    resistance_levels: List[float]
    entry_timing: str
    hold_duration_hours: Optional[int]


class MarketAnalysisResponse(BaseResponse):
    """市场分析响应模型"""
    symbol: str
    bullish_score: float
    bearish_score: float
    volatility_score: float
    market_regime: str
    trend_strength: float
    traditional_signals: Dict[str, Any]
    ml_prediction: Dict[str, Any]
    ml_anomalies: List[Dict[str, Any]]


# 创建服务实例
trading_service = TradingDecisionService()
notification_service = TradingNotificationService()


@router.post("/recommendation", response_model=TradingRecommendationResponse)
async def get_trading_recommendation(request: TradingRecommendationRequest) -> TradingRecommendationResponse:
    """
    获取交易建议
    
    融合传统技术分析和机器学习，提供综合交易建议包含仓位管理和风险控制
    """
    try:
        # 获取交易建议
        recommendation = await trading_service.get_trading_recommendation(
            symbol=request.symbol,
            account_balance=request.account_balance,
            current_positions=request.current_positions
        )
        
        # 发送通知（如果需要）
        if request.send_notification:
            await notification_service.send_trading_recommendation(recommendation)
        
        return TradingRecommendationResponse(
            status="success",
            symbol=recommendation.symbol,
            action=recommendation.action.value,
            confidence=recommendation.confidence,
            position_size_percent=recommendation.position_size_percent,
            leverage=recommendation.leverage,
            stop_loss_percent=recommendation.stop_loss_percent,
            take_profit_percent=recommendation.take_profit_percent,
            risk_level=recommendation.risk_level.value,
            reasoning=recommendation.reasoning,
            support_levels=recommendation.support_levels,
            resistance_levels=recommendation.resistance_levels,
            entry_timing=recommendation.entry_timing,
            hold_duration_hours=recommendation.hold_duration_hours,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Trading recommendation API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取交易建议失败: {str(e)}")


@router.post("/analysis", response_model=MarketAnalysisResponse)
async def get_market_analysis(request: MarketAnalysisRequest) -> MarketAnalysisResponse:
    """
    获取市场分析
    
    提供详细的市场分析，包含技术指标、ML预测和异常检测
    """
    try:
        # 获取市场分析
        analysis = await trading_service.analyze_market(request.symbol)
        
        # 发送通知（如果需要）
        if request.send_notification:
            await notification_service.send_market_analysis(analysis)
        
        return MarketAnalysisResponse(
            status="success",
            symbol=analysis.symbol,
            bullish_score=analysis.bullish_score,
            bearish_score=analysis.bearish_score,
            volatility_score=analysis.volatility_score,
            market_regime=analysis.market_regime,
            trend_strength=analysis.trend_strength,
            traditional_signals=analysis.traditional_signals,
            ml_prediction=analysis.ml_prediction,
            ml_anomalies=analysis.ml_anomalies,
            timestamp=analysis.timestamp
        )
        
    except Exception as e:
        logger.error(f"Market analysis API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"市场分析失败: {str(e)}")


@router.post("/batch-analysis", response_model=BaseResponse)
async def batch_trading_analysis(request: BatchAnalysisRequest) -> BaseResponse:
    """
    批量交易分析
    
    对多个交易对进行批量分析并提供交易建议
    """
    try:
        results = {}
        summary = {
            "total_symbols": len(request.symbols),
            "recommendations": {
                "strong_buy": 0,
                "buy": 0,
                "hold": 0,
                "sell": 0,
                "strong_sell": 0,
                "wait": 0
            },
            "risk_levels": {
                "very_low": 0,
                "low": 0,
                "medium": 0,
                "high": 0,
                "very_high": 0
            },
            "average_confidence": 0.0
        }
        
        total_confidence = 0.0
        
        for symbol in request.symbols:
            try:
                # 获取交易建议
                recommendation = await trading_service.get_trading_recommendation(
                    symbol=symbol,
                    account_balance=request.account_balance
                )
                
                # 统计数据
                summary["recommendations"][recommendation.action.value] += 1
                summary["risk_levels"][recommendation.risk_level.value] += 1
                total_confidence += recommendation.confidence
                
                # 存储结果
                results[symbol] = {
                    "action": recommendation.action.value,
                    "confidence": recommendation.confidence,
                    "position_size": recommendation.position_size_percent,
                    "leverage": recommendation.leverage,
                    "risk_level": recommendation.risk_level.value,
                    "entry_timing": recommendation.entry_timing
                }
                
                # 只发送强信号的通知
                if request.send_notifications and recommendation.action.value in ['strong_buy', 'strong_sell']:
                    await notification_service.send_trading_recommendation(recommendation)
                
            except Exception as e:
                logger.warning(f"Failed to analyze {symbol}: {e}")
                results[symbol] = {"error": str(e)}
        
        # 计算平均置信度
        successful_analyses = len([r for r in results.values() if "error" not in r])
        if successful_analyses > 0:
            summary["average_confidence"] = total_confidence / successful_analyses
        
        return BaseResponse(
            status="success",
            data={
                "results": results,
                "summary": summary
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Batch trading analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"批量分析失败: {str(e)}")


@router.get("/strategy-comparison/{symbol}", response_model=BaseResponse)
async def compare_strategies(symbol: str) -> BaseResponse:
    """
    策略对比分析
    
    对比传统技术分析和机器学习策略的差异
    """
    try:
        # 获取市场分析
        analysis = await trading_service.analyze_market(symbol)
        
        # 分别计算传统策略和ML策略的建议
        traditional_score = 0
        ml_score = 0
        
        # 传统策略评分
        if analysis.traditional_signals:
            signal = analysis.traditional_signals.get('overall_signal', 'hold')
            strength = analysis.traditional_signals.get('signal_strength', 0.5)
            
            signal_values = {
                'strong_buy': 2, 'buy': 1, 'hold': 0, 'sell': -1, 'strong_sell': -2
            }
            traditional_score = signal_values.get(signal, 0) * strength
        
        # ML策略评分
        if analysis.ml_prediction:
            ml_signal = analysis.ml_prediction.get('signal', 'hold')
            ml_confidence = analysis.ml_prediction.get('confidence', 0.5)
            
            signal_values = {
                'strong_buy': 2, 'buy': 1, 'hold': 0, 'sell': -1, 'strong_sell': -2
            }
            ml_score = signal_values.get(ml_signal, 0) * ml_confidence
        
        # 策略一致性
        consistency = 1 - abs(traditional_score - ml_score) / 2
        
        # 综合建议
        combined_score = (traditional_score + ml_score) / 2
        
        if combined_score > 0.8:
            combined_action = "strong_buy"
        elif combined_score > 0.3:
            combined_action = "buy"
        elif combined_score < -0.8:
            combined_action = "strong_sell"
        elif combined_score < -0.3:
            combined_action = "sell"
        else:
            combined_action = "hold"
        
        comparison_data = {
            "symbol": symbol,
            "traditional_strategy": {
                "signal": analysis.traditional_signals.get('overall_signal', 'unknown') if analysis.traditional_signals else 'unknown',
                "strength": analysis.traditional_signals.get('signal_strength', 0) if analysis.traditional_signals else 0,
                "score": traditional_score
            },
            "ml_strategy": {
                "signal": analysis.ml_prediction.get('signal', 'unknown') if analysis.ml_prediction else 'unknown',
                "confidence": analysis.ml_prediction.get('confidence', 0) if analysis.ml_prediction else 0,
                "score": ml_score
            },
            "strategy_consistency": consistency,
            "combined_recommendation": {
                "action": combined_action,
                "confidence": abs(combined_score),
                "reasoning": f"传统策略评分: {traditional_score:.2f}, ML策略评分: {ml_score:.2f}, 一致性: {consistency:.2f}"
            },
            "market_context": {
                "regime": analysis.market_regime,
                "volatility": analysis.volatility_score,
                "trend_strength": analysis.trend_strength
            }
        }
        
        return BaseResponse(
            status="success",
            data=comparison_data,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Strategy comparison failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"策略对比失败: {str(e)}")


@router.post("/risk-assessment", response_model=BaseResponse)
async def assess_portfolio_risk(
    positions: Dict[str, float] = Body(..., description="当前持仓 {symbol: position_size}"),
    account_balance: float = Body(..., description="账户余额")
) -> BaseResponse:
    """
    投资组合风险评估
    
    评估当前持仓的整体风险水平
    """
    try:
        total_risk_score = 0
        position_analyses = {}
        
        for symbol, position_size in positions.items():
            try:
                # 获取市场分析
                analysis = await trading_service.analyze_market(symbol)
                
                # 计算单个持仓风险
                position_risk = 0
                
                # 波动性风险
                volatility_risk = analysis.volatility_score / 100 * 0.4
                
                # 异常风险
                high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
                anomaly_risk = min(high_anomalies * 0.1, 0.3)
                
                # 仓位集中度风险
                concentration_risk = min(position_size / account_balance, 0.3)
                
                position_risk = volatility_risk + anomaly_risk + concentration_risk
                total_risk_score += position_risk * (position_size / account_balance)
                
                position_analyses[symbol] = {
                    "position_size": position_size,
                    "position_percent": (position_size / account_balance) * 100,
                    "volatility_score": analysis.volatility_score,
                    "anomaly_count": len(analysis.ml_anomalies),
                    "high_risk_anomalies": high_anomalies,
                    "risk_score": position_risk,
                    "market_regime": analysis.market_regime
                }
                
            except Exception as e:
                logger.warning(f"Failed to analyze risk for {symbol}: {e}")
                position_analyses[symbol] = {"error": str(e)}
        
        # 整体风险评级
        if total_risk_score > 0.8:
            overall_risk = "very_high"
            risk_recommendation = "建议立即减仓，降低风险敞口"
        elif total_risk_score > 0.6:
            overall_risk = "high"
            risk_recommendation = "建议适当减仓，加强风险管理"
        elif total_risk_score > 0.4:
            overall_risk = "medium"
            risk_recommendation = "风险适中，注意市场变化"
        elif total_risk_score > 0.2:
            overall_risk = "low"
            risk_recommendation = "风险较低，可适当增加仓位"
        else:
            overall_risk = "very_low"
            risk_recommendation = "风险很低，可考虑增加投资"
        
        risk_assessment = {
            "overall_risk_level": overall_risk,
            "risk_score": total_risk_score,
            "recommendation": risk_recommendation,
            "portfolio_summary": {
                "total_positions": len(positions),
                "total_value": sum(positions.values()),
                "account_utilization": (sum(positions.values()) / account_balance) * 100,
                "largest_position": max(positions.values()) if positions else 0,
                "position_concentration": (max(positions.values()) / sum(positions.values())) * 100 if positions else 0
            },
            "position_details": position_analyses,
            "risk_management_tips": [
                "设置合理的止损位",
                "分散投资，避免过度集中",
                "定期评估和调整仓位",
                "关注市场异常信号",
                "保持适当的现金储备"
            ]
        }
        
        return BaseResponse(
            status="success",
            data=risk_assessment,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Portfolio risk assessment failed: {e}")
        raise HTTPException(status_code=500, detail=f"风险评估失败: {str(e)}")