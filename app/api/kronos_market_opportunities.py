# -*- coding: utf-8 -*-
"""
Kronos市场机会API
提供Kronos AI驱动的市场强交易机会和网格交易机会接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import datetime

from app.core.logging import get_logger
from app.services.kronos_market_opportunity_service import get_kronos_market_opportunity_service
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
router = APIRouter()


@router.post("/scan/strong-opportunities", response_model=BaseResponse)
async def scan_strong_trading_opportunities(
    force_scan: bool = Query(False, description="是否强制扫描，忽略时间间隔限制")
):
    """
    扫描Kronos强交易机会
    
    - 只推送Kronos AI识别的强信号
    - 传统技术分析已停用
    - 支持强制扫描模式
    """
    try:
        service = await get_kronos_market_opportunity_service()
        result = await service.scan_strong_trading_opportunities(force_scan=force_scan)
        
        return BaseResponse(
            success=True,
            data=result,
            message="Kronos强交易机会扫描完成"
        )
        
    except Exception as e:
        logger.error(f"扫描强交易机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.post("/scan/grid-opportunities", response_model=BaseResponse)
async def scan_grid_trading_opportunities(
    force_scan: bool = Query(False, description="是否强制扫描，忽略时间间隔限制")
):
    """
    扫描网格交易机会
    
    - 获取交易量前50的币种
    - 使用Kronos AI分析网格交易潜力
    - 评估波动性和适合度
    """
    try:
        service = await get_kronos_market_opportunity_service()
        result = await service.scan_grid_trading_opportunities(force_scan=force_scan)
        
        return BaseResponse(
            success=True,
            data=result,
            message="Kronos网格交易机会扫描完成"
        )
        
    except Exception as e:
        logger.error(f"扫描网格交易机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.get("/scan/status", response_model=BaseResponse)
async def get_scan_status():
    """
    获取扫描状态
    
    - 查看扫描开关状态
    - 查看最后扫描时间
    - 查看扫描间隔配置
    """
    try:
        service = await get_kronos_market_opportunity_service()
        status = await service.get_scan_status()
        
        return BaseResponse(
            success=True,
            data=status,
            message="获取扫描状态成功"
        )
        
    except Exception as e:
        logger.error(f"获取扫描状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/scan/all", response_model=BaseResponse)
async def scan_all_opportunities(
    force_scan: bool = Query(False, description="是否强制扫描所有类型")
):
    """
    扫描所有类型的机会
    
    - 强交易信号扫描
    - 网格交易机会扫描
    - 一次性完成所有扫描
    """
    try:
        service = await get_kronos_market_opportunity_service()
        
        # 并行执行两种扫描
        import asyncio
        strong_task = service.scan_strong_trading_opportunities(force_scan=force_scan)
        grid_task = service.scan_grid_trading_opportunities(force_scan=force_scan)
        
        strong_result, grid_result = await asyncio.gather(strong_task, grid_task)
        
        # 汇总结果
        total_opportunities = (
            strong_result.get("opportunities_found", 0) + 
            grid_result.get("grid_opportunities", 0)
        )
        
        total_notifications = (
            strong_result.get("notifications_sent", 0) + 
            grid_result.get("notifications_sent", 0)
        )
        
        result = {
            "scan_time": datetime.now(),
            "strong_signals": strong_result,
            "grid_opportunities": grid_result,
            "summary": {
                "total_opportunities": total_opportunities,
                "total_notifications": total_notifications,
                "strong_signals_count": strong_result.get("opportunities_found", 0),
                "grid_opportunities_count": grid_result.get("grid_opportunities", 0)
            }
        }
        
        return BaseResponse(
            success=True,
            data=result,
            message=f"全面扫描完成，发现{total_opportunities}个机会"
        )
        
    except Exception as e:
        logger.error(f"全面扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.get("/opportunities/current", response_model=BaseResponse)
async def get_current_opportunities():
    """
    获取当前有效的机会列表
    
    - 返回最近扫描发现的机会
    - 包含强信号和网格机会
    - 按评分排序
    """
    try:
        # 这里可以实现获取当前机会的逻辑
        # 暂时返回扫描状态作为示例
        service = await get_kronos_market_opportunity_service()
        status = await service.get_scan_status()
        
        return BaseResponse(
            success=True,
            data={
                "message": "当前机会列表功能开发中",
                "scan_status": status,
                "suggestion": "请使用 /scan/all 进行实时扫描"
            },
            message="获取当前机会成功"
        )
        
    except Exception as e:
        logger.error(f"获取当前机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/config", response_model=BaseResponse)
async def get_scan_config():
    """
    获取扫描配置信息
    
    - 扫描阈值设置
    - 扫描间隔配置
    - 通知设置
    """
    try:
        from app.core.config import get_settings
        settings = get_settings()
        
        scan_config = settings.kronos_config.get('market_scan_config', {})
        
        config_info = {
            "enabled": scan_config.get('enable_market_scan', True),
            "strong_signal_threshold": scan_config.get('strong_signal_threshold', 0.7),
            "grid_opportunity_threshold": scan_config.get('grid_opportunity_threshold', 0.6),
            "scan_intervals": {
                "strong_signal_minutes": 30,
                "grid_trading_hours": 2
            },
            "notification_config": settings.kronos_config.get('notification_config', {}),
            "description": {
                "strong_signal_threshold": "Kronos置信度阈值，超过此值才推送强信号",
                "grid_opportunity_threshold": "网格机会评分阈值，超过此值才推荐网格交易",
                "scan_intervals": "扫描间隔设置，避免过于频繁的扫描"
            }
        }
        
        return BaseResponse(
            success=True,
            data=config_info,
            message="获取扫描配置成功"
        )
        
    except Exception as e:
        logger.error(f"获取扫描配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")