# -*- coding: utf-8 -*-
"""
数据库相关的数据模型
Database-related data models
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime


class ConnectionPoolStats(BaseModel):
    """连接池统计信息"""
    pool_size: int = Field(..., description="连接池大小")
    checked_in: int = Field(..., description="已检入连接数")
    checked_out: int = Field(..., description="已检出连接数")
    overflow: int = Field(..., description="溢出连接数")
    invalid: int = Field(..., description="无效连接数")
    total_connections: int = Field(..., description="总连接数")
    available_connections: int = Field(..., description="可用连接数")
    active_connections: int = Field(..., description="活跃连接数")
    pool_utilization: float = Field(..., description="连接池使用率(%)")


class DatabaseHealthResponse(BaseModel):
    """数据库健康状态响应"""
    status: str = Field(..., description="健康状态")
    pool_stats: Dict[str, Any] = Field(..., description="连接池统计")
    message: str = Field(..., description="状态消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")


class ConnectionPoolStatsResponse(BaseModel):
    """连接池统计响应"""
    pool_stats: Dict[str, Any] = Field(..., description="连接池统计信息")
    timestamp: datetime = Field(default_factory=datetime.now, description="统计时间")


class DatabaseInfoResponse(BaseModel):
    """数据库信息响应"""
    pool_stats: Dict[str, Any] = Field(..., description="连接池统计")
    health_status: bool = Field(..., description="健康状态")
    database_url: str = Field(..., description="数据库URL(隐藏密码)")
    pool_class: str = Field(..., description="连接池类型")
    last_check_time: float = Field(..., description="上次检查时间")
    check_interval: int = Field(..., description="检查间隔")


class DatabaseTestRequest(BaseModel):
    """数据库测试请求"""
    test_type: str = Field(default="basic", description="测试类型")
    timeout: int = Field(default=30, description="超时时间(秒)")


class DatabaseTestResponse(BaseModel):
    """数据库测试响应"""
    status: str = Field(..., description="测试状态")
    message: str = Field(..., description="测试消息")
    connection_healthy: bool = Field(..., description="连接是否健康")
    response_time: Optional[float] = Field(None, description="响应时间(秒)")
    timestamp: datetime = Field(default_factory=datetime.now, description="测试时间")


class DatabaseOperationResponse(BaseModel):
    """数据库操作响应"""
    status: str = Field(..., description="操作状态")
    message: str = Field(..., description="操作消息")
    data: Optional[Dict[str, Any]] = Field(None, description="操作结果数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="操作时间")