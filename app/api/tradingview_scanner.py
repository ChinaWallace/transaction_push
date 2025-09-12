# -*- coding: utf-8 -*-
"""
TradingView 扫描 API
TradingView Scanner API

提供TradingView强势标的扫描的HTTP接口
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, Optional

from app.core.logging import get_logger
from app.services.analysis.tradingview_scanner_service import get_tradingview_scanner_service
from app.schemas.tradingview import (
    TradingViewScanRequest,
    TradingViewScanResponse,
    TradingViewNotificationMessage
)

logger = get_logger(__name__)
router = APIRouter(tags=["TradingView扫描"])


@router.post(
    "/scan",
    response_model=TradingViewScanResponse,
    summary="扫描强势标的",
    description="""
    扫描TradingView强势标的
    
    **功能特点:**
    - 基于TradingView筛选器获取强势标的
    - 支持自定义筛选条件
    - 自动判断首次入选状态
    - 返回详细的标的信息
    
    **筛选条件:**
    - 流动性: 24小时交易量/市值 在 0.01-2 之间
    - 交易量: 24小时交易量 > 1亿美元
    - 波动率: 日波动率 > 5%
    - 支持多种加密货币类别
    """
)
async def scan_strong_symbols(
    request: Optional[TradingViewScanRequest] = None,
    service = Depends(get_tradingview_scanner_service)
) -> TradingViewScanResponse:
    """扫描强势标的"""
    try:
        result = await service.scan_strong_symbols(request)
        
        if result.success:
            logger.info(f"✅ TradingView扫描成功，发现 {result.total_count} 个强势标的")
        else:
            logger.warning(f"⚠️ TradingView扫描失败: {result.message}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ TradingView扫描API错误: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"扫描失败: {str(e)}"
        )


@router.post(
    "/scan-and-notify",
    response_model=Dict[str, Any],
    summary="扫描并发送通知",
    description="""
    扫描强势标的并发送通知
    
    **通知内容包含:**
    - 警报类型: 强势标的
    - 标的列表: 符号、流动性、首次入选状态
    - 扫描时间
    
    **通知渠道:**
    - 飞书群消息
    - 微信群消息 (如果配置)
    """
)
async def scan_and_notify(
    background_tasks: BackgroundTasks,
    request: Optional[TradingViewScanRequest] = None,
    service = Depends(get_tradingview_scanner_service)
) -> Dict[str, Any]:
    """扫描并发送通知"""
    try:
        # 在后台执行扫描和通知
        background_tasks.add_task(service.scan_and_notify)
        
        return {
            "status": "success",
            "message": "扫描任务已启动，将在后台执行并发送通知",
            "timestamp": "2025-01-01T17:00:00Z"
        }
        
    except Exception as e:
        logger.error(f"❌ 扫描通知API错误: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"启动扫描任务失败: {str(e)}"
        )


@router.get(
    "/history",
    response_model=Dict[str, Any],
    summary="获取扫描历史",
    description="""
    获取TradingView扫描历史记录
    
    **返回信息:**
    - 历史标的数量
    - 标的列表及最后出现时间
    - 查询时间范围
    """
)
async def get_scan_history(
    days: int = 7,
    service = Depends(get_tradingview_scanner_service)
) -> Dict[str, Any]:
    """获取扫描历史"""
    try:
        if days < 1 or days > 30:
            raise HTTPException(
                status_code=400,
                detail="查询天数必须在1-30之间"
            )
        
        history = await service.get_scan_history(days)
        
        return {
            "status": "success",
            "data": history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取扫描历史失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取历史记录失败: {str(e)}"
        )


@router.get(
    "/health",
    response_model=Dict[str, Any],
    summary="健康检查",
    description="检查TradingView扫描服务的健康状态"
)
async def health_check(
    service = Depends(get_tradingview_scanner_service)
) -> Dict[str, Any]:
    """健康检查"""
    try:
        health_status = await service.health_check()
        
        return {
            "service": "tradingview_scanner",
            "health": health_status
        }
        
    except Exception as e:
        logger.error(f"❌ TradingView扫描服务健康检查失败: {e}")
        return {
            "service": "tradingview_scanner",
            "health": {
                "status": "unhealthy",
                "error": str(e)
            }
        }


@router.get(
    "/test",
    response_model=Dict[str, Any],
    summary="测试扫描功能",
    description="测试TradingView扫描功能，只获取少量数据用于验证"
)
async def test_scan(
    service = Depends(get_tradingview_scanner_service)
) -> Dict[str, Any]:
    """测试扫描功能"""
    try:
        # 创建测试请求 - 只获取前5条数据
        test_request = TradingViewScanRequest()
        test_request.range = [0, 5]
        
        result = await service.scan_strong_symbols(test_request)
        
        return {
            "status": "success" if result.success else "failed",
            "test_result": {
                "success": result.success,
                "total_count": result.total_count,
                "symbols_count": len(result.symbols),
                "sample_symbols": [s.symbol for s in result.symbols[:3]],
                "message": result.message
            },
            "timestamp": result.scan_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ TradingView扫描测试失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"测试失败: {str(e)}"
        )