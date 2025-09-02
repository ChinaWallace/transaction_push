# -*- coding: utf-8 -*-
"""
增强交易分析API
Enhanced Trading Analysis API - 集成交易量异常、持仓量变动和动态权重
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.core.logging import get_logger
from app.services.core_trading_service import get_core_trading_service, AnalysisType
from app.services.volume_anomaly_service import get_volume_anomaly_service
from app.services.open_interest_analysis_service import get_oi_analysis_service
from app.services.dynamic_weight_service import get_dynamic_weight_service

logger = get_logger(__name__)
router = APIRouter()


@router.get("/enhanced-analysis/{symbol}")
async def get_enhanced_analysis(
    symbol: str,
    force_update: bool = Query(False, description="是否强制更新数据")
):
    """
    获取增强版交易分析 - 集成所有新功能
    
    Args:
        symbol: 交易对符号
        force_update: 是否强制更新
        
    Returns:
        增强版分析结果
    """
    try:
        logger.info(f"🚀 开始增强分析: {symbol}")
        
        # 获取核心交易服务
        core_service = await get_core_trading_service()
        
        # 执行增强分析
        trading_signal = await core_service.analyze_symbol(
            symbol=symbol,
            analysis_type=AnalysisType.INTEGRATED,
            force_update=force_update
        )
        
        if not trading_signal:
            raise HTTPException(status_code=404, detail=f"无法分析 {symbol}")
        
        # 构建响应
        response = {
            "symbol": symbol,
            "timestamp": datetime.now(),
            "analysis_type": "enhanced_integrated",
            "trading_signal": {
                "action": trading_signal.final_action,
                "confidence": trading_signal.final_confidence,
                "signal_strength": trading_signal.signal_strength.value if hasattr(trading_signal.signal_strength, 'value') else str(trading_signal.signal_strength),
                "reasoning": trading_signal.reasoning,
                "key_factors": trading_signal.key_factors
            },
            "confidence_breakdown": trading_signal.confidence_breakdown,
            "risk_management": {
                "entry_price": trading_signal.entry_price,
                "stop_loss": trading_signal.stop_loss_price,
                "take_profit": trading_signal.take_profit_price,
                "position_size_usdt": trading_signal.position_size_usdt,
                "leverage": trading_signal.leverage
            },
            "technical_indicators": trading_signal.technical_indicators,
            "enhancement_summary": {
                "volume_boost": trading_signal.confidence_breakdown.get('volume_boost', 0),
                "oi_boost": trading_signal.confidence_breakdown.get('oi_boost', 0),
                "confidence_multiplier": trading_signal.confidence_breakdown.get('confidence_multiplier', 1.0)
            }
        }
        
        logger.info(f"✅ 增强分析完成: {symbol} -> {trading_signal.final_action} ({trading_signal.final_confidence:.2f})")
        return response
        
    except Exception as e:
        logger.error(f"❌ 增强分析失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/volume-anomaly/{symbol}")
async def get_volume_anomaly(symbol: str):
    """
    获取交易量异常分析
    
    Args:
        symbol: 交易对符号
        
    Returns:
        交易量异常分析结果
    """
    try:
        volume_service = get_volume_anomaly_service()
        anomaly_data = await volume_service.detect_volume_anomaly(symbol)
        
        if not anomaly_data:
            return {
                "symbol": symbol,
                "timestamp": datetime.now(),
                "anomaly_level": "normal",
                "message": "未检测到交易量异常"
            }
        
        return {
            "symbol": symbol,
            "timestamp": anomaly_data.timestamp,
            "anomaly_level": anomaly_data.anomaly_level.value,
            "volume_ratio": anomaly_data.volume_ratio,
            "current_volume": anomaly_data.current_volume,
            "avg_volume_24h": anomaly_data.avg_volume_24h,
            "price_change_24h": anomaly_data.price_change_24h,
            "confidence_boost": anomaly_data.confidence_boost,
            "is_bullish": anomaly_data.is_bullish_anomaly(),
            "is_bearish": anomaly_data.is_bearish_anomaly()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取交易量异常失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/open-interest-analysis/{symbol}")
async def get_open_interest_analysis(symbol: str):
    """
    获取持仓量变动分析
    
    Args:
        symbol: 交易对符号
        
    Returns:
        持仓量变动分析结果
    """
    try:
        oi_service = get_oi_analysis_service()
        analysis = await oi_service.analyze_open_interest(symbol)
        
        if not analysis:
            return {
                "symbol": symbol,
                "timestamp": datetime.now(),
                "change_level": "normal",
                "message": "未检测到显著持仓量变化"
            }
        
        return {
            "symbol": symbol,
            "timestamp": analysis.timestamp,
            "current_oi": analysis.current_oi,
            "oi_change_24h": analysis.oi_change_24h,
            "oi_change_percent": analysis.oi_change_percent,
            "change_level": analysis.change_level.value,
            "trend_signal": analysis.trend_signal.value,
            "price_change_24h": analysis.price_change_24h,
            "signal_strength_boost": analysis.signal_strength_boost,
            "trend_confirmation_score": analysis.trend_confirmation_score,
            "is_bullish": analysis.is_bullish_signal(),
            "is_bearish": analysis.is_bearish_signal()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取持仓量分析失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dynamic-weights/{symbol}")
async def get_dynamic_weights(symbol: str):
    """
    获取动态权重配置
    
    Args:
        symbol: 交易对符号
        
    Returns:
        动态权重配置
    """
    try:
        weight_service = get_dynamic_weight_service()
        weights = await weight_service.get_dynamic_weights(symbol)
        
        return {
            "symbol": symbol,
            "timestamp": weights.timestamp,
            "market_regime": weights.market_regime.value,
            "weights": {
                "kronos": weights.kronos_weight,
                "technical": weights.technical_weight,
                "ml": weights.ml_weight,
                "position": weights.position_weight
            },
            "confidence_multiplier": weights.confidence_multiplier,
            "reasoning": weights.reasoning
        }
        
    except Exception as e:
        logger.error(f"❌ 获取动态权重失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-enhanced-analysis")
async def batch_enhanced_analysis(
    symbols: List[str],
    max_concurrent: int = Query(5, description="最大并发数"),
    force_update: bool = Query(False, description="是否强制更新")
):
    """
    批量增强分析
    
    Args:
        symbols: 交易对列表
        max_concurrent: 最大并发数
        force_update: 是否强制更新
        
    Returns:
        批量分析结果
    """
    try:
        logger.info(f"🚀 开始批量增强分析: {len(symbols)} 个交易对")
        
        # 获取核心交易服务
        core_service = await get_core_trading_service()
        
        # 批量分析
        results = await core_service.batch_analyze_symbols(
            symbols=symbols,
            analysis_type=AnalysisType.INTEGRATED,
            max_concurrent=max_concurrent,
            force_update=force_update
        )
        
        # 构建响应
        analysis_results = {}
        strong_signals = []
        
        for symbol, signal in results.items():
            if signal:
                analysis_results[symbol] = {
                    "action": signal.final_action,
                    "confidence": signal.final_confidence,
                    "signal_strength": signal.signal_strength.value if hasattr(signal.signal_strength, 'value') else str(signal.signal_strength),
                    "reasoning": signal.reasoning,
                    "enhancement_summary": {
                        "volume_boost": signal.confidence_breakdown.get('volume_boost', 0),
                        "oi_boost": signal.confidence_breakdown.get('oi_boost', 0),
                        "confidence_multiplier": signal.confidence_breakdown.get('confidence_multiplier', 1.0)
                    }
                }
                
                # 收集强信号
                if (signal.final_action.upper() not in ['HOLD', '持有', '观望'] and 
                    signal.final_confidence > 0.6):
                    strong_signals.append({
                        "symbol": symbol,
                        "action": signal.final_action,
                        "confidence": signal.final_confidence,
                        "signal_strength": signal.signal_strength.value if hasattr(signal.signal_strength, 'value') else str(signal.signal_strength)
                    })
            else:
                analysis_results[symbol] = {
                    "error": "分析失败",
                    "action": "HOLD",
                    "confidence": 0.0
                }
        
        response = {
            "timestamp": datetime.now(),
            "total_symbols": len(symbols),
            "successful_analyses": len([r for r in results.values() if r is not None]),
            "strong_signals_count": len(strong_signals),
            "results": analysis_results,
            "strong_signals": strong_signals[:10]  # 最多返回10个强信号
        }
        
        logger.info(f"✅ 批量增强分析完成: {response['successful_analyses']}/{response['total_symbols']} 成功")
        return response
        
    except Exception as e:
        logger.error(f"❌ 批量增强分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/enhancement-summary")
async def get_enhancement_summary(
    symbols: List[str] = Query(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"], description="要分析的交易对")
):
    """
    获取增强功能摘要
    
    Args:
        symbols: 交易对列表
        
    Returns:
        增强功能摘要
    """
    try:
        logger.info(f"📊 获取增强功能摘要: {len(symbols)} 个交易对")
        
        # 获取各服务
        volume_service = get_volume_anomaly_service()
        oi_service = get_oi_analysis_service()
        weight_service = get_dynamic_weight_service()
        
        # 并发获取摘要
        import asyncio
        volume_summary, oi_summary, weight_summary = await asyncio.gather(
            volume_service.get_anomaly_summary(symbols),
            oi_service.get_analysis_summary(symbols),
            weight_service.get_weight_summary(symbols)
        )
        
        response = {
            "timestamp": datetime.now(),
            "symbols_analyzed": len(symbols),
            "volume_anomaly_summary": {
                "total_anomalies": volume_summary.get('anomalies_found', 0),
                "bullish_anomalies": volume_summary.get('bullish_anomalies', 0),
                "bearish_anomalies": volume_summary.get('bearish_anomalies', 0),
                "by_level": volume_summary.get('by_level', {}),
                "top_anomalies": volume_summary.get('top_anomalies', [])[:3]
            },
            "open_interest_summary": {
                "significant_changes": oi_summary.get('significant_changes', 0),
                "bullish_confirmations": oi_summary.get('bullish_confirmations', 0),
                "bearish_confirmations": oi_summary.get('bearish_confirmations', 0),
                "by_level": oi_summary.get('by_level', {}),
                "top_changes": oi_summary.get('top_changes', [])[:3]
            },
            "dynamic_weight_summary": {
                "regime_distribution": weight_summary.get('regime_distribution', {}),
                "average_weights": weight_summary.get('average_weights', {}),
                "regime_examples": weight_summary.get('regime_examples', {})
            }
        }
        
        logger.info(f"✅ 增强功能摘要完成")
        return response
        
    except Exception as e:
        logger.error(f"❌ 获取增强功能摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))