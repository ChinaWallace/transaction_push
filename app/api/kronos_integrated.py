# -*- coding: utf-8 -*-
"""
Kronos集成API
提供Kronos集成决策服务的API接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.logging import get_logger
from app.services.kronos_integrated_decision_service import (
    get_kronos_integrated_service,
    KronosEnhancedDecision
)
from app.utils.exceptions import TradingToolError

router = APIRouter(prefix="/kronos-integrated", tags=["Kronos集成"])
logger = get_logger(__name__)


@router.get("/decision/{symbol}")
async def get_enhanced_decision(
    symbol: str,
    force_update: bool = Query(False, description="强制更新预测")
) -> Dict[str, Any]:
    """获取单个币种的Kronos增强决策"""
    try:
        service = await get_kronos_integrated_service()
        decision = await service.get_kronos_enhanced_decision(symbol, force_update)
        
        if not decision:
            raise HTTPException(status_code=404, detail=f"无法获取{symbol}的决策")
        
        return {
            "success": True,
            "data": {
                "symbol": decision.symbol,
                "timestamp": decision.timestamp.isoformat(),
                "final_action": decision.final_action,
                "final_confidence": decision.final_confidence,
                "signal_confluence": decision.signal_confluence,
                "kronos_confidence": decision.kronos_confidence,
                "kronos_signal_strength": decision.kronos_signal_strength.value,
                "technical_signal": decision.technical_signal,
                "technical_confidence": decision.technical_confidence,
                "reasoning": decision.reasoning,
                "risk_management": {
                    "entry_price": decision.entry_price,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "position_size": decision.position_size
                },
                "market_regime": decision.market_regime.value if decision.market_regime else None
            }
        }
        
    except Exception as e:
        logger.error(f"获取{symbol}增强决策失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-analysis")
async def batch_analysis(
    symbols: str = Query(..., description="币种列表，逗号分隔"),
    force_update: bool = Query(False, description="强制更新预测")
) -> Dict[str, Any]:
    """批量分析多个币种"""
    try:
        symbol_list = [s.strip() for s in symbols.split(",")]
        service = await get_kronos_integrated_service()
        
        results = await service.batch_analyze_symbols(symbol_list, force_update)
        
        formatted_results = {}
        for symbol, decision in results.items():
            if decision:
                formatted_results[symbol] = {
                    "final_action": decision.final_action,
                    "final_confidence": decision.final_confidence,
                    "signal_confluence": decision.signal_confluence,
                    "kronos_confidence": decision.kronos_confidence,
                    "reasoning": decision.reasoning
                }
            else:
                formatted_results[symbol] = None
        
        return {
            "success": True,
            "data": formatted_results,
            "summary": {
                "total_symbols": len(symbol_list),
                "analyzed_symbols": len([r for r in results.values() if r is not None]),
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"批量分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_service_status() -> Dict[str, Any]:
    """获取服务状态"""
    try:
        service = await get_kronos_integrated_service()
        
        return {
            "success": True,
            "data": {
                "service_available": True,
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"获取服务状态失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }