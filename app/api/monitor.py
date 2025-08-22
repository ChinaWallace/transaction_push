# -*- coding: utf-8 -*-
"""
监控服务API路由
Monitor service API routes
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict, Any, List, Optional

from app.core.logging import get_logger
from app.services.monitor_service import MonitorService
from app.schemas.monitor import MonitorStatusResponse

logger = get_logger(__name__)
router = APIRouter()

# 创建监控服务实例
monitor_service = MonitorService()


@router.get("/status", 
           summary="监控服务状态",
           response_model=MonitorStatusResponse)
async def get_monitor_status():
    """获取监控服务状态"""
    try:
        status_data = await monitor_service.get_monitor_status()
        
        return MonitorStatusResponse(
            success=True,
            data=status_data,
            message="Monitor status retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to get monitor status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get monitor status: {str(e)}")


@router.get("/funding-rate",
           summary="资金费率监控",
           response_model=Dict[str, Any])
async def monitor_funding_rate(
    symbols: Optional[str] = Query(None, description="交易对列表(逗号分隔)"),
    notify: bool = Query(True, description="是否发送通知")
):
    """
    执行资金费率监控
    
    Args:
        symbols: 交易对列表，用逗号分隔，如 "BTCUSDT,ETHUSDT"
        notify: 是否发送通知
    """
    try:
        logger.info("Starting funding rate monitoring via API")
        
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
        
        result = await monitor_service.monitor_funding_rate(symbol_list, notify)
        
        return {
            "success": True,
            "data": result,
            "message": f"Funding rate monitoring completed. Found {result['negative_count']} negative rates and {result['high_positive_count']} high positive rates"
        }
        
    except Exception as e:
        logger.error(f"Funding rate monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=f"Funding rate monitoring failed: {str(e)}")


@router.get("/open-interest",
           summary="持仓量变化监控",
           response_model=Dict[str, Any])
async def monitor_open_interest(
    symbols: Optional[str] = Query(None, description="交易对列表(逗号分隔)"),
    notify: bool = Query(True, description="是否发送通知")
):
    """
    执行持仓量变化监控
    
    Args:
        symbols: 交易对列表，用逗号分隔
        notify: 是否发送通知
    """
    try:
        logger.info("Starting open interest monitoring via API")
        
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
        
        result = await monitor_service.monitor_open_interest(symbol_list, notify)
        
        return {
            "success": True,
            "data": result,
            "message": f"Open interest monitoring completed. Found {result['alert_count']} symbols with significant changes"
        }
        
    except Exception as e:
        logger.error(f"Open interest monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=f"Open interest monitoring failed: {str(e)}")


@router.get("/volume-anomaly",
           summary="交易量异常监控",
           response_model=Dict[str, Any])
async def monitor_volume_anomaly(
    symbols: Optional[str] = Query(None, description="交易对列表(逗号分隔)"),
    notify: bool = Query(True, description="是否发送通知")
):
    """
    执行交易量异常监控（庄神指标）
    
    Args:
        symbols: 交易对列表，用逗号分隔
        notify: 是否发送通知
    """
    try:
        logger.info("Starting volume anomaly monitoring via API")
        
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
        
        result = await monitor_service.monitor_volume_anomaly(symbol_list, notify)
        
        return {
            "success": True,
            "data": result,
            "message": f"Volume anomaly monitoring completed. Found {len(result['strong_symbols'])} strong and {len(result['normal_symbols'])} normal anomalies"
        }
        
    except Exception as e:
        logger.error(f"Volume anomaly monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=f"Volume anomaly monitoring failed: {str(e)}")


@router.get("/comprehensive",
           summary="综合监控",
           response_model=Dict[str, Any])
async def run_comprehensive_monitoring(
    symbols: Optional[str] = Query(None, description="交易对列表(逗号分隔)")
):
    """
    执行综合监控（所有监控功能）
    
    Args:
        symbols: 交易对列表，用逗号分隔
    """
    try:
        logger.info("Starting comprehensive monitoring via API")
        
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
        
        result = await monitor_service.run_comprehensive_monitoring(symbol_list)
        
        return {
            "success": True,
            "data": result,
            "message": f"Comprehensive monitoring completed with {result['total_alerts']} total alerts"
        }
        
    except Exception as e:
        logger.error(f"Comprehensive monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=f"Comprehensive monitoring failed: {str(e)}")


@router.post("/test-notifications",
            summary="测试通知功能",
            response_model=Dict[str, Any])
async def test_notifications():
    """测试所有通知渠道"""
    try:
        from app.services.notification_service import NotificationService
        
        notification_service = NotificationService()
        results = await notification_service.test_notifications()
        
        success_channels = [ch for ch, success in results.items() if success]
        failed_channels = [ch for ch, success in results.items() if not success]
        
        return {
            "success": len(success_channels) > 0,
            "data": {
                "results": results,
                "success_channels": success_channels,
                "failed_channels": failed_channels
            },
            "message": f"Notification test completed. {len(success_channels)} channels succeeded, {len(failed_channels)} failed"
        }
        
    except Exception as e:
        logger.error(f"Notification test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Notification test failed: {str(e)}")
