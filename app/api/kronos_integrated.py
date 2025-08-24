# -*- coding: utf-8 -*-
"""
Kronos集成决策API
提供Kronos前置集成的交易决策接口
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Query, Path, HTTPException, BackgroundTasks
from datetime import datetime

from app.core.logging import get_logger
from app.services.kronos_integrated_decision_service import (
    get_kronos_integrated_service,
    KronosEnhancedDecision,
    KronosSignalStrength
)
from app.schemas.base import BaseResponse
from app.schemas.kronos import KronosIntegratedDecisionResponse

router = APIRouter()
logger = get_logger(__name__)


@router.get("/{symbol}/decision", response_model=KronosIntegratedDecisionResponse)
async def get_kronos_integrated_decision(
    symbol: str = Path(..., description="交易对符号，如BTC-USDT"),
    force_update: bool = Query(False, description="是否强制更新预测")
) -> KronosIntegratedDecisionResponse:
    """
    获取单个交易对的Kronos集成决策
    
    将Kronos预测前置到持仓分析和技术分析中，提供综合交易决策
    """
    try:
        service = await get_kronos_integrated_service()
        decision = await service.get_kronos_enhanced_decision(symbol, force_update)
        
        if not decision:
            raise HTTPException(
                status_code=404,
                detail=f"无法获取{symbol}的决策分析"
            )
        
        return KronosIntegratedDecisionResponse(
            status="success",
            data=decision,
            timestamp=datetime.now(),
            message=f"{symbol}的Kronos集成决策分析完成"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{symbol}的Kronos集成决策失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"决策分析失败: {str(e)}"
        )


@router.post("/batch-analysis", response_model=BaseResponse)
async def batch_kronos_analysis(
    symbols: List[str],
    force_update: bool = Query(False, description="是否强制更新预测")
) -> BaseResponse:
    """
    批量分析多个交易对的Kronos集成决策
    """
    try:
        if not symbols:
            raise HTTPException(
                status_code=400,
                detail="交易对列表不能为空"
            )
        
        if len(symbols) > 20:
            raise HTTPException(
                status_code=400,
                detail="单次最多分析20个交易对"
            )
        
        service = await get_kronos_integrated_service()
        results = await service.batch_analyze_symbols(symbols, force_update)
        
        # 统计结果
        successful_count = sum(1 for r in results.values() if r is not None)
        failed_symbols = [symbol for symbol, result in results.items() if result is None]
        
        return BaseResponse(
            status="success",
            data={
                "results": results,
                "summary": {
                    "total": len(symbols),
                    "successful": successful_count,
                    "failed": len(failed_symbols),
                    "failed_symbols": failed_symbols
                }
            },
            timestamp=datetime.now(),
            message=f"批量分析完成: {successful_count}/{len(symbols)}个成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量Kronos分析失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"批量分析失败: {str(e)}"
        )


@router.get("/signals/strong", response_model=BaseResponse)
async def get_strong_kronos_signals(
    min_confidence: float = Query(0.7, description="最小置信度阈值"),
    symbols: Optional[List[str]] = Query(None, description="指定交易对列表")
) -> BaseResponse:
    """
    获取强Kronos信号的交易对
    """
    try:
        service = await get_kronos_integrated_service()
        
        # 如果没有指定交易对，使用默认热门交易对
        if not symbols:
            symbols = [
                "BTC-USDT", "ETH-USDT", "BNB-USDT", "ADA-USDT", "SOL-USDT",
                "XRP-USDT", "DOT-USDT", "DOGE-USDT", "AVAX-USDT", "MATIC-USDT"
            ]
        
        # 批量分析
        results = await service.batch_analyze_symbols(symbols, force_update=True)
        
        # 筛选强信号
        strong_signals = []
        for symbol, decision in results.items():
            if decision and decision.kronos_confidence >= min_confidence:
                if decision.kronos_signal_strength in [
                    KronosSignalStrength.STRONG,
                    KronosSignalStrength.VERY_STRONG
                ]:
                    strong_signals.append({
                        "symbol": symbol,
                        "action": decision.final_action,
                        "confidence": decision.final_confidence,
                        "kronos_confidence": decision.kronos_confidence,
                        "signal_strength": decision.kronos_signal_strength.value,
                        "signal_confluence": decision.signal_confluence,
                        "reasoning": decision.reasoning
                    })
        
        # 按置信度排序
        strong_signals.sort(key=lambda x: x["confidence"], reverse=True)
        
        return BaseResponse(
            status="success",
            data={
                "strong_signals": strong_signals,
                "count": len(strong_signals),
                "min_confidence": min_confidence
            },
            timestamp=datetime.now(),
            message=f"找到{len(strong_signals)}个强Kronos信号"
        )
        
    except Exception as e:
        logger.error(f"获取强Kronos信号失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取强信号失败: {str(e)}"
        )


@router.get("/market-regime", response_model=BaseResponse)
async def get_market_regime_analysis(
    symbols: Optional[List[str]] = Query(None, description="指定交易对列表")
) -> BaseResponse:
    """
    基于Kronos预测分析市场状态
    """
    try:
        service = await get_kronos_integrated_service()
        
        # 如果没有指定交易对，使用主要交易对
        if not symbols:
            symbols = ["BTC-USDT", "ETH-USDT", "BNB-USDT"]
        
        # 批量分析
        results = await service.batch_analyze_symbols(symbols, force_update=True)
        
        # 统计市场状态
        regime_stats = {}
        valid_results = [r for r in results.values() if r is not None]
        
        for decision in valid_results:
            regime = decision.market_regime.value
            if regime not in regime_stats:
                regime_stats[regime] = 0
            regime_stats[regime] += 1
        
        # 确定主导市场状态
        dominant_regime = max(regime_stats.items(), key=lambda x: x[1]) if regime_stats else ("未知", 0)
        
        return BaseResponse(
            status="success",
            data={
                "market_regime_distribution": regime_stats,
                "dominant_regime": dominant_regime[0],
                "analyzed_symbols": len(valid_results),
                "symbol_details": [
                    {
                        "symbol": decision.symbol,
                        "market_regime": decision.market_regime.value,
                        "kronos_confidence": decision.kronos_confidence,
                        "final_action": decision.final_action
                    }
                    for decision in valid_results
                ]
            },
            timestamp=datetime.now(),
            message=f"市场状态分析完成，主导状态: {dominant_regime[0]}"
        )
        
    except Exception as e:
        logger.error(f"市场状态分析失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"市场状态分析失败: {str(e)}"
        )