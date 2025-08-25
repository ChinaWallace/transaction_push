# -*- coding: utf-8 -*-
"""
HTTP连接池相关的数据模型
HTTP connection pool related data models
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime


class HTTPPoolStats(BaseModel):
    """HTTP连接池统计信息"""
    total_clients: int = Field(..., description="客户端总数")
    client_names: list = Field(..., description="客户端名称列表")
    shared_session_active: bool = Field(..., description="共享session是否活跃")
    total_connections: Optional[int] = Field(None, description="总连接数")
    connection_limit: Optional[int] = Field(None, description="连接限制")
    per_host_limit: Optional[int] = Field(None, description="每主机连接限制")
    keepalive_timeout: Optional[int] = Field(None, description="保持连接超时时间")


class HTTPPoolStatsResponse(BaseModel):
    """HTTP连接池统计响应"""
    pool_stats: Dict[str, Any] = Field(..., description="连接池统计信息")
    message: str = Field(..., description="响应消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="统计时间")


class HTTPPoolHealthResponse(BaseModel):
    """HTTP连接池健康状态响应"""
    status: str = Field(..., description="健康状态")
    pool_stats: Dict[str, Any] = Field(..., description="连接池统计")
    message: str = Field(..., description="状态消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")


class HTTPPoolOperationResponse(BaseModel):
    """HTTP连接池操作响应"""
    status: str = Field(..., description="操作状态")
    message: str = Field(..., description="操作消息")
    operation: str = Field(..., description="操作类型")
    timestamp: datetime = Field(default_factory=datetime.now, description="操作时间")


class HTTPClientConfig(BaseModel):
    """HTTP客户端配置"""
    name: str = Field(..., description="客户端名称")
    timeout: int = Field(default=30, description="超时时间")
    max_retries: int = Field(default=3, description="最大重试次数")
    use_proxy: bool = Field(default=False, description="是否使用代理")


class HTTPConnectionInfo(BaseModel):
    """HTTP连接信息"""
    pool_limit: int = Field(..., description="连接池限制")
    pool_limit_per_host: int = Field(..., description="每主机连接限制")
    keepalive_timeout: int = Field(..., description="保持连接超时")
    connect_timeout: int = Field(..., description="连接超时")
    read_timeout: int = Field(..., description="读取超时")
    total_timeout: int = Field(..., description="总超时")
    dns_cache_ttl: int = Field(..., description="DNS缓存时间")
    proxy_enabled: bool = Field(..., description="是否启用代理")
    proxy_url: Optional[str] = Field(None, description="代理URL")