# -*- coding: utf-8 -*-
"""
TradingView 调度管理 API
TradingView Scheduler Management API

提供TradingView扫描任务的调度管理接口
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from app.core.logging import get_logger
from app.services.core.tradingview_scheduler_service import get_tradingview_scheduler_service

logger = get_logger(__name__)
router = APIRouter(prefix="/api/tradingview/scheduler", tags=["TradingView调度"])


@router.post(
    "/start",
    response_model=Dict[str, Any],
    summary="启动调度器",
    description="启动TradingView扫描调度器，包含启动扫描、每小时扫描和每日扫描任务"
)
async def start_scheduler(
    service = Depends(get_tradingview_scheduler_service)
) -> Dict[str, Any]:
    """启动调度器"""
    try:
        await service.start_scheduler()
        
        return {
            "status": "success",
            "message": "TradingView调度器已启动",
            "scheduler_running": True
        }
        
    except Exception as e:
        logger.error(f"❌ 启动调度器失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"启动调度器失败: {str(e)}"
        )


@router.post(
    "/stop",
    response_model=Dict[str, Any],
    summary="停止调度器",
    description="停止TradingView扫描调度器，所有定时任务将停止执行"
)
async def stop_scheduler(
    service = Depends(get_tradingview_scheduler_service)
) -> Dict[str, Any]:
    """停止调度器"""
    try:
        await service.stop_scheduler()
        
        return {
            "status": "success",
            "message": "TradingView调度器已停止",
            "scheduler_running": False
        }
        
    except Exception as e:
        logger.error(f"❌ 停止调度器失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"停止调度器失败: {str(e)}"
        )


@router.post(
    "/execute",
    response_model=Dict[str, Any],
    summary="手动执行扫描",
    description="手动触发TradingView扫描任务，立即执行并发送通知"
)
async def execute_manual_scan(
    service = Depends(get_tradingview_scheduler_service)
) -> Dict[str, Any]:
    """手动执行扫描"""
    try:
        result = await service.execute_manual_scan()
        
        if result["success"]:
            logger.info(f"✅ 手动扫描成功，发现 {result['scan_result']['total_symbols']} 个标的")
        else:
            logger.warning(f"⚠️ 手动扫描失败: {result.get('error', '未知错误')}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 手动扫描API错误: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"手动扫描失败: {str(e)}"
        )


@router.get(
    "/status",
    response_model=Dict[str, Any],
    summary="获取调度器状态",
    description="获取TradingView调度器的详细状态信息，包含任务列表和执行统计"
)
async def get_scheduler_status(
    service = Depends(get_tradingview_scheduler_service)
) -> Dict[str, Any]:
    """获取调度器状态"""
    try:
        status = await service.get_scheduler_status()
        
        return {
            "status": "success",
            "data": status
        }
        
    except Exception as e:
        logger.error(f"❌ 获取调度器状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取状态失败: {str(e)}"
        )


@router.get(
    "/health",
    response_model=Dict[str, Any],
    summary="健康检查",
    description="检查TradingView调度服务的健康状态"
)
async def health_check(
    service = Depends(get_tradingview_scheduler_service)
) -> Dict[str, Any]:
    """健康检查"""
    try:
        health_status = await service.health_check()
        
        return {
            "service": "tradingview_scheduler",
            "health": health_status
        }
        
    except Exception as e:
        logger.error(f"❌ TradingView调度服务健康检查失败: {e}")
        return {
            "service": "tradingview_scheduler",
            "health": {
                "status": "unhealthy",
                "error": str(e)
            }
        }