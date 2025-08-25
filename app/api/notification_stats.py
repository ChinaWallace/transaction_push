# -*- coding: utf-8 -*-
"""
通知统计API
Notification Statistics API - 查看通知发送统计和频率限制状态
"""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from datetime import datetime

from app.core.logging import get_logger
from app.services.intelligent_trading_notification_service import get_intelligent_notification_service
from app.utils.okx_rate_limiter import get_okx_rate_limiter

logger = get_logger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["通知统计"])


@router.get("/stats", summary="获取通知统计")
async def get_notification_stats() -> Dict[str, Any]:
    """
    获取通知发送统计信息
    
    Returns:
        Dict: 包含每日通知统计的详细信息
    """
    try:
        notification_service = await get_intelligent_notification_service()
        stats = notification_service.get_daily_notification_stats()
        
        return {
            "success": True,
            "data": stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取通知统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取通知统计失败: {str(e)}")


@router.get("/rate-limits", summary="获取API频率限制状态")
async def get_rate_limit_status() -> Dict[str, Any]:
    """
    获取OKX API频率限制状态
    
    Returns:
        Dict: API频率限制的详细状态
    """
    try:
        rate_limiter = get_okx_rate_limiter()
        status = rate_limiter.get_rate_limit_status()
        
        return {
            "success": True,
            "data": status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取频率限制状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取频率限制状态失败: {str(e)}")


@router.post("/reset-daily-limits", summary="重置每日通知限制")
async def reset_daily_notification_limits() -> Dict[str, Any]:
    """
    重置每日通知限制计数器（管理员功能）
    
    Returns:
        Dict: 重置结果
    """
    try:
        notification_service = await get_intelligent_notification_service()
        
        # 清空每日计数
        notification_service.daily_notification_count.clear()
        
        logger.info("每日通知限制已重置")
        
        return {
            "success": True,
            "message": "每日通知限制已重置",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"重置每日通知限制失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置失败: {str(e)}")


@router.post("/reset-rate-limits", summary="重置API频率限制")
async def reset_api_rate_limits() -> Dict[str, Any]:
    """
    重置API频率限制计数器（紧急情况使用）
    
    Returns:
        Dict: 重置结果
    """
    try:
        rate_limiter = get_okx_rate_limiter()
        rate_limiter.reset_limits()
        
        logger.warning("API频率限制已重置")
        
        return {
            "success": True,
            "message": "API频率限制已重置",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"重置API频率限制失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置失败: {str(e)}")


@router.get("/health", summary="通知系统健康检查")
async def notification_health_check() -> Dict[str, Any]:
    """
    通知系统健康检查
    
    Returns:
        Dict: 系统健康状态
    """
    try:
        notification_service = await get_intelligent_notification_service()
        rate_limiter = get_okx_rate_limiter()
        
        # 获取统计信息
        notification_stats = notification_service.get_daily_notification_stats()
        rate_limit_status = rate_limiter.get_rate_limit_status()
        
        # 检查是否有API在冷却
        apis_cooling = [
            api_type for api_type, status in rate_limit_status.items()
            if status.get('is_cooling_down', False)
        ]
        
        # 检查通知是否接近限制
        high_utilization_levels = [
            level for level, stats in notification_stats['levels'].items()
            if float(stats['utilization'].rstrip('%')) > 80
        ]
        
        health_status = "healthy"
        warnings = []
        
        if apis_cooling:
            health_status = "warning"
            warnings.append(f"API冷却中: {', '.join(apis_cooling)}")
        
        if high_utilization_levels:
            health_status = "warning"
            warnings.append(f"通知使用率过高: {', '.join(high_utilization_levels)}")
        
        return {
            "success": True,
            "health_status": health_status,
            "warnings": warnings,
            "notification_stats": notification_stats,
            "rate_limit_status": rate_limit_status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "success": False,
            "health_status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }