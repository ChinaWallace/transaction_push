#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易对管理API
Trading Pairs Management API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from app.services.trading.trading_pair_service import TradingPairService
from app.schemas.base import BaseResponse
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/update", response_model=BaseResponse)
async def update_trading_pairs():
    """更新交易对列表"""
    try:
        service = TradingPairService()
        result = await service.fetch_and_update_trading_pairs()
        
        if result['success']:
            return BaseResponse(
                success=True,
                message="交易对更新成功",
                data=result
            )
        else:
            raise HTTPException(status_code=500, detail=result['error'])
            
    except Exception as e:
        logger.error(f"更新交易对失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新交易对失败: {str(e)}")


@router.get("/active", response_model=BaseResponse)
async def get_active_pairs(
    limit: Optional[int] = Query(100, description="返回数量限制")
):
    """获取活跃的交易对列表"""
    try:
        service = TradingPairService()
        pairs = await service.get_active_usdt_pairs()
        
        # 限制返回数量
        if limit and len(pairs) > limit:
            pairs = pairs[:limit]
        
        return BaseResponse(
            success=True,
            message=f"获取到 {len(pairs)} 个活跃交易对",
            data={
                'pairs': pairs,
                'count': len(pairs),
                'timestamp': datetime.now()
            }
        )
        
    except Exception as e:
        logger.error(f"获取活跃交易对失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取活跃交易对失败: {str(e)}")


@router.get("/funding-monitor", response_model=BaseResponse)
async def get_funding_monitor_pairs():
    """获取用于负费率监控的交易对列表"""
    try:
        service = TradingPairService()
        pairs = await service.get_pairs_for_funding_monitor()
        
        return BaseResponse(
            success=True,
            message=f"获取到 {len(pairs)} 个监控交易对",
            data={
                'pairs': pairs,
                'count': len(pairs),
                'timestamp': datetime.now()
            }
        )
        
    except Exception as e:
        logger.error(f"获取监控交易对失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取监控交易对失败: {str(e)}")


@router.put("/{inst_id}/status", response_model=BaseResponse)
async def update_pair_status(
    inst_id: str,
    is_active: bool = Query(..., description="是否启用监控")
):
    """更新交易对监控状态"""
    try:
        service = TradingPairService()
        success = await service.update_pair_status(inst_id, is_active)
        
        if success:
            return BaseResponse(
                success=True,
                message=f"交易对 {inst_id} 状态更新成功",
                data={
                    'inst_id': inst_id,
                    'is_active': is_active,
                    'timestamp': datetime.now()
                }
            )
        else:
            raise HTTPException(status_code=404, detail="交易对不存在或更新失败")
            
    except Exception as e:
        logger.error(f"更新交易对状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新交易对状态失败: {str(e)}")