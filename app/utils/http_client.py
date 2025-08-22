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
    """HTTP客户端类"""
    
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
        """启动会话"""
        if self.session is None:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            
            # 设置代理
            session_kwargs = {
                'connector': connector,
                'timeout': timeout,
                'headers': {
                    'User-Agent': 'Python-Trading-Tool/1.0.0',
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip, deflate'
                }
            }
            
            # 如果启用了代理，添加代理配置
            if self.use_proxy and self.proxy_url:
                logger.info(f"Using proxy: {self.proxy_url}")
                session_kwargs['connector'] = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=30,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True
                )
            
            self.session = aiohttp.ClientSession(**session_kwargs)
    
    async def close_session(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
            self.session = None
    
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
