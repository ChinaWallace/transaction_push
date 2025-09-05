# -*- coding: utf-8 -*-
"""
Kronos市场机会API
提供基于Kronos预测的市场机会扫描接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
from datetime import datetime

from app.core.logging import get_logger
from app.services.ml.kronos_market_opportunity_service import (
    get_kronos_market_opportunity_service
)

router = APIRouter(prefix="/kronos-opportunities", tags=["Kronos市场机会"])
logger = get_logger(__name__)


@router.get("/scan")
async def scan_opportunities(
    force_update: bool = Query(False, description="强制更新预测")
) -> Dict[str, Any]:
    """扫描市场机会"""
    try:
        service = await get_kronos_market_opportunity_service()
        opportunities = await service.scan_market_opportunities(force_update)
        
        formatted_opportunities = []
        for opp in opportunities:
            formatted_opportunities.append({
                "symbol": opp.symbol,
                "opportunity_type": opp.opportunity_type.value,
                "confidence": opp.confidence,
                "expected_return": opp.expected_return,
                "risk_level": opp.risk_level,
                "entry_price": opp.entry_price,
                "target_price": opp.target_price,
                "stop_loss": opp.stop_loss,
                "reasoning": opp.reasoning,
                "timestamp": opp.timestamp.isoformat()
            })
        
        return {
            "success": True,
            "data": {
                "opportunities": formatted_opportunities,
                "total_count": len(opportunities),
                "scan_timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"扫描市场机会失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top")
async def get_top_opportunities(
    limit: int = Query(5, description="返回机会数量"),
    min_confidence: float = Query(0.6, description="最小置信度")
) -> Dict[str, Any]:
    """获取顶级交易机会"""
    try:
        service = await get_kronos_market_opportunity_service()
        opportunities = await service.get_top_opportunities(limit, min_confidence)
        
        formatted_opportunities = []
        for opp in opportunities:
            formatted_opportunities.append({
                "symbol": opp.symbol,
                "opportunity_type": opp.opportunity_type.value,
                "confidence": opp.confidence,
                "expected_return": opp.expected_return,
                "risk_level": opp.risk_level,
                "reasoning": opp.reasoning
            })
        
        return {
            "success": True,
            "data": {
                "top_opportunities": formatted_opportunities,
                "count": len(opportunities),
                "criteria": {
                    "limit": limit,
                    "min_confidence": min_confidence
                }
            }
        }
        
    except Exception as e:
        logger.error(f"获取顶级机会失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_scan_status() -> Dict[str, Any]:
    """获取扫描状态"""
    try:
        service = await get_kronos_market_opportunity_service()
        status = service.get_scan_status()
        
        return {
            "success": True,
            "data": status
        }
        
    except Exception as e:
        logger.error(f"获取扫描状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))