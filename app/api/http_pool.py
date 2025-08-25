# -*- coding: utf-8 -*-
"""
HTTP连接池管理API
HTTP connection pool management API endpoints
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.utils.http_client import get_http_pool_stats, close_http_pool, http_pool
from app.schemas.http_pool import (
    HTTPPoolStatsResponse,
    HTTPPoolHealthResponse,
    HTTPPoolOperationResponse
)

router = APIRouter()


@router.get("/stats", response_model=HTTPPoolStatsResponse)
async def get_http_pool_stats_api() -> HTTPPoolStatsResponse:
    """获取HTTP连接池统计信息"""
    try:
        stats = get_http_pool_stats()
        return HTTPPoolStatsResponse(
            pool_stats=stats,
            message="HTTP连接池统计信息获取成功"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取HTTP连接池统计失败: {str(e)}")


@router.get("/health", response_model=HTTPPoolHealthResponse)
async def get_http_pool_health() -> HTTPPoolHealthResponse:
    """获取HTTP连接池健康状态"""
    try:
        stats = get_http_pool_stats()
        
        # 判断健康状态
        is_healthy = (
            stats.get("shared_session_active", False) and
            stats.get("total_clients", 0) > 0
        )
        
        return HTTPPoolHealthResponse(
            status="healthy" if is_healthy else "unhealthy",
            pool_stats=stats,
            message="HTTP连接池健康" if is_healthy else "HTTP连接池异常"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取HTTP连接池健康状态失败: {str(e)}")


@router.post("/cleanup", response_model=HTTPPoolOperationResponse)
async def cleanup_http_pool() -> HTTPPoolOperationResponse:
    """清理HTTP连接池"""
    try:
        await close_http_pool()
        
        return HTTPPoolOperationResponse(
            status="success",
            message="HTTP连接池清理完成",
            operation="cleanup"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理HTTP连接池失败: {str(e)}")


@router.get("/clients")
async def list_http_clients() -> Dict[str, Any]:
    """列出所有HTTP客户端"""
    try:
        stats = get_http_pool_stats()
        
        return {
            "status": "success",
            "total_clients": stats.get("total_clients", 0),
            "client_names": stats.get("client_names", []),
            "shared_session_active": stats.get("shared_session_active", False)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取HTTP客户端列表失败: {str(e)}")


@router.get("/connections")
async def get_connection_details() -> Dict[str, Any]:
    """获取连接详细信息"""
    try:
        stats = get_http_pool_stats()
        
        connection_info = {
            "pool_configuration": {
                "total_connections": stats.get("total_connections", 0),
                "connection_limit": stats.get("connection_limit", 0),
                "per_host_limit": stats.get("per_host_limit", 0),
                "keepalive_timeout": stats.get("keepalive_timeout", 0)
            },
            "current_status": {
                "shared_session_active": stats.get("shared_session_active", False),
                "total_clients": stats.get("total_clients", 0),
                "client_names": stats.get("client_names", [])
            }
        }
        
        return {
            "status": "success",
            "connection_info": connection_info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取连接详细信息失败: {str(e)}")