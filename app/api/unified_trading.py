# -*- coding: utf-8 -*-
"""
统一交易决策API
Unified Trading Decision API endpoints
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.unified_trading_service import UnifiedTradingService
from app.services.trading_notification_service import TradingNotificationService
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()


class UnifiedTradingRequest(BaseModel):
    """统一交易请求模型"""
    symbol: str = Field(..., description="交易对")
    send_notification: bool = Field(default=False, description="是否发送通知")


class BatchUnifiedTradingRequest(BaseModel):
    """批量统一交易请求模型"""
    symbols: List[str] = Field(..., description="交易对列表")
    send_notifications: bool = Field(default=False, description="是否发送通知")


class UnifiedTradingResponse(BaseResponse):
    """统一交易响应模型"""
    symbol: str
    final_action: str
    confidence: float
    
    # 分析结果
    traditional_signal: str
    traditional_confidence: float
    ml_signal: str
    ml_confidence: float
    
    # 市场状态
    market_regime: str
    volatility_level: str
    
    # 动态止盈止损
    dynamic_stop_loss: float
    dynamic_take_profit: float
    risk_reward_ratio: float
    
    # 仓位管理
    position_size_percent: float
    leverage: float
    risk_level: str
    
    # 价格信息
    current_price: float
    entry_price: float
    
    # 决策理由
    reasoning: str
    key_factors: List[str]
    
    # 时间建议
    entry_timing: str
    hold_duration_hours: Optional[int]


# 创建服务实例
unified_service = UnifiedTradingService()
notification_service = TradingNotificationService()


@router.post("/recommendation", response_model=UnifiedTradingResponse)
async def get_unified_recommendation(request: UnifiedTradingRequest) -> UnifiedTradingResponse:
    """
    获取统一交易建议
    
    融合传统技术分析和机器学习，提供综合交易建议，支持动态止盈止损
    """
    try:
        # 获取统一交易建议
        recommendation = await unified_service.get_unified_recommendation(request.symbol)
        
        # 发送通知（如果需要）
        if request.send_notification:
            # 转换为详细通知格式
            notification_data = {
                'symbol': recommendation.symbol,
                'action': recommendation.final_action.value,
                'confidence': recommendation.confidence,
                'reasoning': recommendation.reasoning,
                'current_price': recommendation.current_price,
                'stop_loss': recommendation.dynamic_stop_loss,
                'take_profit': recommendation.dynamic_take_profit,
                'position_size': recommendation.position_size_percent,
                'risk_level': recommendation.risk_level.value,
                
                # 详细技术分析信息
                'traditional_signal': recommendation.traditional_signal,
                'traditional_confidence': recommendation.traditional_confidence,
                'ml_signal': recommendation.ml_signal,
                'ml_confidence': recommendation.ml_confidence,
                'market_regime': recommendation.market_regime.value,
                'volatility_level': recommendation.volatility_level,
                'key_factors': recommendation.key_factors,
                'entry_timing': recommendation.entry_timing,
                'leverage': recommendation.leverage,
                'risk_reward_ratio': recommendation.risk_reward_ratio
            }
            
            # 发送详细通知
            await notification_service.send_unified_trading_notification(notification_data)
        
        return UnifiedTradingResponse(
            status="success",
            symbol=recommendation.symbol,
            final_action=recommendation.final_action.value,
            confidence=recommendation.confidence,
            
            # 分析结果
            traditional_signal=recommendation.traditional_signal,
            traditional_confidence=recommendation.traditional_confidence,
            ml_signal=recommendation.ml_signal,
            ml_confidence=recommendation.ml_confidence,
            
            # 市场状态
            market_regime=recommendation.market_regime.value,
            volatility_level=recommendation.volatility_level,
            
            # 动态止盈止损
            dynamic_stop_loss=recommendation.dynamic_stop_loss,
            dynamic_take_profit=recommendation.dynamic_take_profit,
            risk_reward_ratio=recommendation.risk_reward_ratio,
            
            # 仓位管理
            position_size_percent=recommendation.position_size_percent,
            leverage=recommendation.leverage,
            risk_level=recommendation.risk_level.value,
            
            # 价格信息
            current_price=recommendation.current_price,
            entry_price=recommendation.entry_price,
            
            # 决策理由
            reasoning=recommendation.reasoning,
            key_factors=recommendation.key_factors,
            
            # 时间建议
            entry_timing=recommendation.entry_timing,
            hold_duration_hours=recommendation.hold_duration_hours,
            
            timestamp=recommendation.timestamp
        )
        
    except Exception as e:
        logger.error(f"Unified trading recommendation API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取统一交易建议失败: {str(e)}")


@router.post("/batch-analysis", response_model=BaseResponse)
async def batch_unified_analysis(request: BatchUnifiedTradingRequest) -> BaseResponse:
    """
    批量统一交易分析
    
    对多个交易对进行批量统一分析，支持所有配置的交易对
    """
    try:
        # 批量分析
        recommendations = await unified_service.batch_analyze_symbols(request.symbols)
        
        # 统计结果
        summary = {
            "total_symbols": len(request.symbols),
            "successful_analyses": len(recommendations),
            "failed_analyses": len(request.symbols) - len(recommendations),
            "actions": {
                "强烈买入": 0,
                "买入": 0,
                "持有": 0,
                "卖出": 0,
                "强烈卖出": 0,
                "等待": 0
            },
            "risk_levels": {
                "极低风险": 0,
                "低风险": 0,
                "中等风险": 0,
                "高风险": 0,
                "极高风险": 0
            },
            "average_confidence": 0.0,
            "high_confidence_signals": []
        }
        
        total_confidence = 0.0
        results = {}
        
        for symbol, recommendation in recommendations.items():
            # 统计动作
            action = recommendation.final_action.value
            summary["actions"][action] += 1
            
            # 统计风险等级
            risk_level = recommendation.risk_level.value
            summary["risk_levels"][risk_level] += 1
            
            # 累计置信度
            total_confidence += recommendation.confidence
            
            # 高置信度信号
            if recommendation.confidence > 75:
                summary["high_confidence_signals"].append({
                    "symbol": symbol,
                    "action": action,
                    "confidence": recommendation.confidence,
                    "reasoning": recommendation.reasoning
                })
            
            # 存储结果
            results[symbol] = {
                "action": action,
                "confidence": recommendation.confidence,
                "traditional_signal": recommendation.traditional_signal,
                "ml_signal": recommendation.ml_signal,
                "market_regime": recommendation.market_regime.value,
                "dynamic_stop_loss": recommendation.dynamic_stop_loss,
                "dynamic_take_profit": recommendation.dynamic_take_profit,
                "position_size": recommendation.position_size_percent,
                "leverage": recommendation.leverage,
                "risk_level": risk_level,
                "entry_timing": recommendation.entry_timing,
                "key_factors": recommendation.key_factors
            }
            
            # 只发送强信号通知
            if (request.send_notifications and 
                recommendation.confidence > 75 and 
                action in ["强烈买入", "强烈卖出"]):
                notification_data = {
                    'symbol': symbol,
                    'action': action,
                    'confidence': recommendation.confidence,
                    'reasoning': recommendation.reasoning,
                    'current_price': recommendation.current_price,
                    'stop_loss': recommendation.dynamic_stop_loss,
                    'take_profit': recommendation.dynamic_take_profit,
                    'position_size': recommendation.position_size_percent,
                    'risk_level': risk_level,
                    
                    # 详细技术分析信息
                    'traditional_signal': recommendation.traditional_signal,
                    'traditional_confidence': recommendation.traditional_confidence,
                    'ml_signal': recommendation.ml_signal,
                    'ml_confidence': recommendation.ml_confidence,
                    'market_regime': recommendation.market_regime.value,
                    'volatility_level': recommendation.volatility_level,
                    'key_factors': recommendation.key_factors,
                    'entry_timing': recommendation.entry_timing,
                    'leverage': recommendation.leverage,
                    'risk_reward_ratio': recommendation.risk_reward_ratio
                }
                
                try:
                    await notification_service.send_unified_trading_notification(notification_data)
                except Exception as e:
                    logger.warning(f"发送{symbol}通知失败: {e}")
        
        # 计算平均置信度
        if len(recommendations) > 0:
            summary["average_confidence"] = total_confidence / len(recommendations)
        
        return BaseResponse(
            status="success",
            data={
                "results": results,
                "summary": summary
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Batch unified analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"批量统一分析失败: {str(e)}")


@router.get("/market-overview", response_model=BaseResponse)
async def get_market_overview() -> BaseResponse:
    """
    市场概览
    
    获取所有监控交易对的统一分析概览
    """
    try:
        # 使用配置中的监控交易对
        symbols = settings.monitored_symbols
        
        # 批量分析
        recommendations = await unified_service.batch_analyze_symbols(symbols)
        
        # 构建市场概览
        overview = {
            "market_sentiment": {
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0
            },
            "risk_distribution": {
                "low_risk": 0,
                "medium_risk": 0,
                "high_risk": 0
            },
            "top_opportunities": [],
            "market_alerts": [],
            "volatility_analysis": {
                "high_volatility": [],
                "low_volatility": [],
                "normal_volatility": []
            }
        }
        
        for symbol, recommendation in recommendations.items():
            action = recommendation.final_action.value
            
            # 市场情绪统计
            if action in ["强烈买入", "买入"]:
                overview["market_sentiment"]["bullish_count"] += 1
            elif action in ["强烈卖出", "卖出"]:
                overview["market_sentiment"]["bearish_count"] += 1
            else:
                overview["market_sentiment"]["neutral_count"] += 1
            
            # 风险分布
            risk = recommendation.risk_level.value
            if risk in ["极低风险", "低风险"]:
                overview["risk_distribution"]["low_risk"] += 1
            elif risk in ["中等风险"]:
                overview["risk_distribution"]["medium_risk"] += 1
            else:
                overview["risk_distribution"]["high_risk"] += 1
            
            # 顶级机会（高置信度 + 强信号）
            if (recommendation.confidence > 75 and 
                action in ["强烈买入", "强烈卖出"]):
                overview["top_opportunities"].append({
                    "symbol": symbol,
                    "action": action,
                    "confidence": recommendation.confidence,
                    "risk_reward": recommendation.risk_reward_ratio,
                    "entry_timing": recommendation.entry_timing
                })
            
            # 市场警报（高风险或异常）
            if (recommendation.risk_level.value in ["高风险", "极高风险"] or
                recommendation.volatility_level == "高"):
                overview["market_alerts"].append({
                    "symbol": symbol,
                    "alert_type": "高风险" if "高风险" in recommendation.risk_level.value else "高波动",
                    "description": f"{symbol} {recommendation.risk_level.value}，波动性{recommendation.volatility_level}"
                })
            
            # 波动性分析
            volatility = recommendation.volatility_level
            if volatility == "高":
                overview["volatility_analysis"]["high_volatility"].append(symbol)
            elif volatility == "低":
                overview["volatility_analysis"]["low_volatility"].append(symbol)
            else:
                overview["volatility_analysis"]["normal_volatility"].append(symbol)
        
        # 排序顶级机会
        overview["top_opportunities"].sort(key=lambda x: x["confidence"], reverse=True)
        overview["top_opportunities"] = overview["top_opportunities"][:5]
        
        return BaseResponse(
            status="success",
            data=overview,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Market overview failed: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场概览失败: {str(e)}")


@router.get("/symbol-comparison", response_model=BaseResponse)
async def compare_symbols(
    symbols: List[str] = Query(..., description="要比较的交易对列表")
) -> BaseResponse:
    """
    交易对比较分析
    
    比较多个交易对的统一分析结果
    """
    try:
        if len(symbols) > 10:
            raise HTTPException(status_code=400, detail="最多只能比较10个交易对")
        
        # 批量分析
        recommendations = await unified_service.batch_analyze_symbols(symbols)
        
        # 构建比较结果
        comparison = {
            "symbols": symbols,
            "comparison_matrix": [],
            "best_opportunities": [],
            "risk_comparison": {},
            "performance_ranking": []
        }
        
        for symbol, recommendation in recommendations.items():
            comparison_item = {
                "symbol": symbol,
                "final_action": recommendation.final_action.value,
                "confidence": recommendation.confidence,
                "traditional_vs_ml": {
                    "traditional": recommendation.traditional_signal,
                    "ml": recommendation.ml_signal,
                    "agreement": recommendation.traditional_signal == recommendation.ml_signal
                },
                "risk_reward": recommendation.risk_reward_ratio,
                "position_size": recommendation.position_size_percent,
                "volatility": recommendation.volatility_level,
                "entry_timing": recommendation.entry_timing
            }
            
            comparison["comparison_matrix"].append(comparison_item)
            
            # 风险比较
            comparison["risk_comparison"][symbol] = {
                "risk_level": recommendation.risk_level.value,
                "leverage": recommendation.leverage,
                "stop_loss_distance": abs(recommendation.current_price - recommendation.dynamic_stop_loss) / recommendation.current_price * 100
            }
            
            # 性能排名（基于置信度和风险收益比）
            performance_score = recommendation.confidence * recommendation.risk_reward_ratio / 100
            comparison["performance_ranking"].append({
                "symbol": symbol,
                "score": performance_score,
                "action": recommendation.final_action.value,
                "confidence": recommendation.confidence,
                "risk_reward": recommendation.risk_reward_ratio
            })
        
        # 排序性能排名
        comparison["performance_ranking"].sort(key=lambda x: x["score"], reverse=True)
        
        # 最佳机会（前3名）
        comparison["best_opportunities"] = comparison["performance_ranking"][:3]
        
        return BaseResponse(
            status="success",
            data=comparison,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Symbol comparison failed: {e}")
        raise HTTPException(status_code=500, detail=f"交易对比较失败: {str(e)}")