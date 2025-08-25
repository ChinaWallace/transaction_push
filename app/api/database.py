# -*- coding: utf-8 -*-
"""
数据库管理API
Database management API endpoints
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from app.utils.db_monitor import get_db_monitor, DatabaseMonitor
from app.core.database import db_manager
from app.schemas.database import (
    DatabaseHealthResponse,
    ConnectionPoolStatsResponse,
    DatabaseInfoResponse
)

router = APIRouter()


@router.get("/health", response_model=DatabaseHealthResponse)
async def get_database_health(
    monitor: DatabaseMonitor = Depends(get_db_monitor)
) -> DatabaseHealthResponse:
    """获取数据库健康状态"""
    try:
        health_status = monitor.check_pool_health()
        pool_stats = monitor.get_pool_stats()
        
        return DatabaseHealthResponse(
            status="healthy" if health_status else "unhealthy",
            pool_stats=pool_stats,
            message="数据库连接正常" if health_status else "数据库连接异常"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据库健康状态失败: {str(e)}")


@router.get("/pool/stats", response_model=ConnectionPoolStatsResponse)
async def get_pool_stats(
    monitor: DatabaseMonitor = Depends(get_db_monitor)
) -> ConnectionPoolStatsResponse:
    """获取连接池统计信息"""
    try:
        stats = monitor.get_pool_stats()
        return ConnectionPoolStatsResponse(
            pool_stats=stats,
            timestamp=None  # 会自动设置为当前时间
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取连接池统计失败: {str(e)}")


@router.get("/info", response_model=DatabaseInfoResponse)
async def get_database_info(
    monitor: DatabaseMonitor = Depends(get_db_monitor)
) -> DatabaseInfoResponse:
    """获取数据库详细信息"""
    try:
        info = monitor.get_connection_info()
        return DatabaseInfoResponse(**info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据库信息失败: {str(e)}")


@router.post("/pool/cleanup")
async def cleanup_pool(
    monitor: DatabaseMonitor = Depends(get_db_monitor)
) -> Dict[str, Any]:
    """清理连接池"""
    try:
        monitor.auto_cleanup()
        stats = monitor.get_pool_stats()
        
        return {
            "status": "success",
            "message": "连接池清理完成",
            "pool_stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理连接池失败: {str(e)}")


@router.post("/reconnect")
async def force_reconnect(
    monitor: DatabaseMonitor = Depends(get_db_monitor)
) -> Dict[str, Any]:
    """强制重新连接数据库"""
    try:
        monitor.force_reconnect()
        health_status = monitor.check_pool_health()
        
        return {
            "status": "success",
            "message": "数据库重新连接成功",
            "health_status": health_status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新连接数据库失败: {str(e)}")


@router.get("/test")
async def test_database_connection() -> Dict[str, Any]:
    """测试数据库连接"""
    try:
        health_check = db_manager.health_check()
        
        if health_check:
            return {
                "status": "success",
                "message": "数据库连接测试成功",
                "connection_healthy": True
            }
        else:
            return {
                "status": "error",
                "message": "数据库连接测试失败",
                "connection_healthy": False
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库连接测试失败: {str(e)}")