# -*- coding: utf-8 -*-
"""
HTTP客户端工具
HTTP client utility for making API requests
"""

import asyncio
import aiohttp
from typing import Dict, Any, Optional
import json
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import RateLimitError, BinanceAPIError

logger = get_logger(__name__)


class HTTPClient:
    """HTTP客户端类 - 使用连接池"""
    
    # 类级别的共享session，实现连接池复用
    _shared_session = None
    _session_lock = asyncio.Lock()
    
    def __init__(self, timeout: int = 30, max_retries: int = 3, use_proxy: bool = None):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = None
        self._rate_limit_reset = {}
        
        # 代理配置
        settings = get_settings()
        if use_proxy is None:
            self.use_proxy = settings.proxy_enabled
        else:
            self.use_proxy = use_proxy
        self.proxy_url = settings.proxy_url if self.use_proxy else None
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close_session()
    
    async def start_session(self):
        """启动会话 - 使用共享连接池"""
        if self.session is None:
            # 使用共享session实现连接池复用
            async with HTTPClient._session_lock:
                if HTTPClient._shared_session is None or HTTPClient._shared_session.closed:
                    await self._create_shared_session()
                self.session = HTTPClient._shared_session
    
    async def _create_shared_session(self):
        """创建共享session"""
        settings = get_settings()
        http_config = settings.http_pool_config
        
        # 使用配置文件中的连接池配置
        connector = aiohttp.TCPConnector(
            limit=http_config["pool_limit"],                    # 总连接池大小
            limit_per_host=http_config["pool_limit_per_host"],  # 每个主机的连接数
            keepalive_timeout=http_config["keepalive_timeout"], # 保持连接时间
            enable_cleanup_closed=True,                         # 自动清理关闭的连接
            ttl_dns_cache=http_config["dns_cache_ttl"],        # DNS缓存时间
            use_dns_cache=True,                                # 启用DNS缓存
            ssl=False,                                         # 对于HTTP API，禁用SSL验证以提高性能
            force_close=False                                  # 不强制关闭连接，复用连接
        )
        
        timeout = aiohttp.ClientTimeout(
            total=http_config["total_timeout"],
            connect=http_config["connect_timeout"],      # 连接超时
            sock_read=http_config["read_timeout"],       # 读取超时
            sock_connect=http_config["connect_timeout"]  # socket连接超时
        )
        
        # 设置代理
        session_kwargs = {
            'connector': connector,
            'timeout': timeout,
            'headers': {
                'User-Agent': 'Python-Trading-Tool/1.0.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'  # 保持连接
            },
            'cookie_jar': aiohttp.CookieJar(),  # 启用cookie支持
            'raise_for_status': False,  # 不自动抛出HTTP错误
            'trust_env': True  # 信任环境变量中的代理设置
        }
        
        # 如果启用了代理，使用代理连接器
        if http_config["proxy_enabled"] and http_config["proxy_url"]:
            logger.info(f"Using proxy: {http_config['proxy_url']}")
            # 代理情况下使用不同的连接器配置
            proxy_connector = aiohttp.TCPConnector(
                limit=http_config["pool_limit"] // 2,  # 代理时减少连接数
                limit_per_host=http_config["pool_limit_per_host"] // 2,
                keepalive_timeout=http_config["keepalive_timeout"],
                enable_cleanup_closed=True
            )
            session_kwargs['connector'] = proxy_connector
        
        HTTPClient._shared_session = aiohttp.ClientSession(**session_kwargs)
        logger.info("✅ HTTP连接池已创建")
    
    async def close_session(self):
        """关闭会话 - 不关闭共享session，只清理引用"""
        self.session = None
    
    @classmethod
    async def close_shared_session(cls):
        """关闭共享session - 应用关闭时调用"""
        async with cls._session_lock:
            if cls._shared_session and not cls._shared_session.closed:
                await cls._shared_session.close()
                cls._shared_session = None
                logger.info("🔒 HTTP连接池已关闭")
    
    def _check_rate_limit(self, url: str):
        """检查限流状态"""
        domain = url.split('/')[2] if '/' in url else url
        reset_time = self._rate_limit_reset.get(domain)
        
        if reset_time and datetime.now() < reset_time:
            raise RateLimitError(f"Rate limit exceeded for {domain}")
    
    def _handle_rate_limit(self, url: str, retry_after: int = None):
        """处理限流响应"""
        domain = url.split('/')[2] if '/' in url else url
        reset_time = datetime.now() + timedelta(seconds=retry_after or 60)
        self._rate_limit_reset[domain] = reset_time
        
        logger.warning(f"Rate limit hit for {domain}, reset at {reset_time}")
    
    async def _make_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """发起HTTP请求"""
        if not self.session:
            await self.start_session()
        
        # 检查限流状态
        self._check_rate_limit(url)
        
        for attempt in range(self.max_retries + 1):
            try:
                # 如果使用代理，添加代理参数
                if self.use_proxy and self.proxy_url:
                    kwargs['proxy'] = self.proxy_url
                
                async with self.session.request(method, url, **kwargs) as response:
                    # 处理限流
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self._handle_rate_limit(url, retry_after)
                        
                        if attempt < self.max_retries:
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            raise RateLimitError("Max retries exceeded for rate limiting")
                    
                    # 处理其他错误状态
                    if response.status >= 400:
                        error_text = await response.text()
                        try:
                            error_data = json.loads(error_text)
                            error_msg = error_data.get('msg', error_text)
                            error_code = error_data.get('code')
                        except json.JSONDecodeError:
                            error_msg = error_text
                            error_code = None
                        
                        raise BinanceAPIError(
                            f"API request failed: {error_msg}",
                            error_code=str(error_code) if error_code else None,
                            status_code=response.status
                        )
                    
                    # 成功响应
                    response_text = await response.text()
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        return {"raw_data": response_text}
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request failed after {self.max_retries} retries: {e}")
                    raise BinanceAPIError(f"Network error after {self.max_retries} retries: {e}")
    
    async def get(self, url: str, params: Dict[str, Any] = None, 
                  headers: Dict[str, str] = None) -> Dict[str, Any]:
        """GET请求"""
        kwargs = {}
        if params:
            kwargs['params'] = params
        if headers:
            kwargs['headers'] = headers
            
        return await self._make_request('GET', url, **kwargs)
    
    async def post(self, url: str, data: Dict[str, Any] = None, 
                   json_data: Dict[str, Any] = None,
                   headers: Dict[str, str] = None) -> Dict[str, Any]:
        """POST请求"""
        kwargs = {}
        if data:
            kwargs['data'] = data
        if json_data:
            kwargs['json'] = json_data
        if headers:
            kwargs['headers'] = headers
            
        return await self._make_request('POST', url, **kwargs)
    
    async def put(self, url: str, data: Dict[str, Any] = None,
                  json_data: Dict[str, Any] = None,
                  headers: Dict[str, str] = None) -> Dict[str, Any]:
        """PUT请求"""
        kwargs = {}
        if data:
            kwargs['data'] = data
        if json_data:
            kwargs['json'] = json_data
        if headers:
            kwargs['headers'] = headers
            
        return await self._make_request('PUT', url, **kwargs)
    
    async def delete(self, url: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
        """DELETE请求"""
        kwargs = {}
        if headers:
            kwargs['headers'] = headers
            
        return await self._make_request('DELETE', url, **kwargs)


class HTTPConnectionPool:
    """HTTP连接池管理器"""
    
    def __init__(self):
        self.clients = {}
        self._lock = asyncio.Lock()
    
    async def get_client(self, name: str = "default", **kwargs) -> HTTPClient:
        """获取HTTP客户端实例"""
        async with self._lock:
            if name not in self.clients:
                self.clients[name] = HTTPClient(**kwargs)
            return self.clients[name]
    
    async def close_all(self):
        """关闭所有客户端"""
        async with self._lock:
            for client in self.clients.values():
                await client.close_session()
            self.clients.clear()
            
            # 关闭共享session
            await HTTPClient.close_shared_session()
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        stats = {
            "total_clients": len(self.clients),
            "client_names": list(self.clients.keys()),
            "shared_session_active": HTTPClient._shared_session is not None and not HTTPClient._shared_session.closed
        }
        
        # 如果有共享session，获取连接器统计
        if HTTPClient._shared_session and not HTTPClient._shared_session.closed:
            connector = HTTPClient._shared_session.connector
            try:
                if hasattr(connector, '_conns'):
                    stats["total_connections"] = len(connector._conns)
                if hasattr(connector, 'limit'):
                    stats["connection_limit"] = connector.limit
                if hasattr(connector, 'limit_per_host'):
                    stats["per_host_limit"] = connector.limit_per_host
                if hasattr(connector, '_keepalive_timeout'):
                    stats["keepalive_timeout"] = connector._keepalive_timeout
                elif hasattr(connector, 'keepalive_timeout'):
                    stats["keepalive_timeout"] = connector.keepalive_timeout
            except Exception:
                # 忽略获取统计信息的错误
                pass
        
        return stats


# 全局HTTP连接池实例
http_pool = HTTPConnectionPool()


async def get_http_client(name: str = "default", **kwargs) -> HTTPClient:
    """获取HTTP客户端实例"""
    return await http_pool.get_client(name, **kwargs)


async def close_http_pool():
    """关闭HTTP连接池"""
    await http_pool.close_all()


def get_http_pool_stats() -> Dict[str, Any]:
    """获取HTTP连接池统计信息"""
    return http_pool.get_pool_stats()