# -*- coding: utf-8 -*-
"""
HTTP连接管理器 - 遵循异步模式最佳实践
HTTP connection manager following async patterns best practices
"""

import asyncio
import aiohttp
from typing import Dict, Any, Optional, AsyncContextManager
from contextlib import asynccontextmanager
import logging
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.utils.exceptions import ServiceUnavailableError, InternalServerError

logger = logging.getLogger(__name__)


class HTTPConnectionManager:
    """HTTP连接管理器 - 单例模式，全局共享连接池"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.session: Optional[aiohttp.ClientSession] = None
        self.settings = get_settings()
        self._last_health_check = None
        self._health_check_interval = 300  # 5分钟检查一次
        self._connection_stats = {
            "requests_made": 0,
            "errors_count": 0,
            "last_request_time": None,
            "session_created_time": None
        }
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 - 不关闭session，保持连接池"""
        # 记录异常但不关闭session，让连接池保持活跃
        if exc_type:
            logger.error(f"HTTP连接管理器异常: {exc_type.__name__}: {exc_val}")
            self._connection_stats["errors_count"] += 1
    
    async def _ensure_session(self):
        """确保session可用"""
        async with HTTPConnectionManager._lock:
            if self.session is None or self.session.closed:
                await self._create_session()
    
    async def _create_session(self):
        """创建新的session"""
        try:
            # 关闭旧session（如果存在）
            if self.session and not self.session.closed:
                await self.session.close()
                await asyncio.sleep(0.1)  # 等待连接完全关闭
            
            http_config = self.settings.http_pool_config
            
            # 创建连接器
            connector = aiohttp.TCPConnector(
                limit=http_config["pool_limit"],
                limit_per_host=http_config["pool_limit_per_host"],
                keepalive_timeout=http_config["keepalive_timeout"],
                enable_cleanup_closed=True,
                ttl_dns_cache=http_config["dns_cache_ttl"],
                use_dns_cache=True,
                ssl=False,  # 对于大多数API，禁用SSL验证
                force_close=False
            )
            
            # 创建超时配置
            timeout = aiohttp.ClientTimeout(
                total=http_config["total_timeout"],
                connect=http_config["connect_timeout"],
                sock_read=http_config["read_timeout"],
                sock_connect=http_config["connect_timeout"]
            )
            
            # 创建session
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Python-Trading-Tool/1.0.0',
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive'
                },
                cookie_jar=aiohttp.CookieJar(),
                raise_for_status=False,
                trust_env=True
            )
            
            self._connection_stats["session_created_time"] = datetime.now()
            logger.info("✅ HTTP连接池已创建")
            
        except Exception as e:
            logger.error(f"创建HTTP session失败: {e}")
            self.session = None
            raise ServiceUnavailableError(f"无法创建HTTP连接: {e}")
    
    @asynccontextmanager
    async def get_session(self) -> AsyncContextManager[aiohttp.ClientSession]:
        """获取session的上下文管理器"""
        await self._ensure_session()
        
        if self.session is None:
            raise ServiceUnavailableError("HTTP session不可用")
        
        try:
            yield self.session
        except Exception as e:
            logger.error(f"HTTP请求异常: {e}")
            self._connection_stats["errors_count"] += 1
            raise
        finally:
            self._connection_stats["requests_made"] += 1
            self._connection_stats["last_request_time"] = datetime.now()
    
    async def safe_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """安全的HTTP请求方法"""
        max_retries = self.settings.http_max_retries
        
        for attempt in range(max_retries + 1):
            try:
                async with self.get_session() as session:
                    # 添加代理支持
                    if self.settings.proxy_enabled and self.settings.proxy_url:
                        kwargs['proxy'] = self.settings.proxy_url
                    
                    async with session.request(method, url, **kwargs) as response:
                        # 处理响应
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.warning(f"HTTP {response.status}: {error_text}")
                            
                            if response.status == 429:  # 限流
                                retry_after = int(response.headers.get('Retry-After', 60))
                                if attempt < max_retries:
                                    await asyncio.sleep(retry_after)
                                    continue
                            
                            raise ServiceUnavailableError(f"HTTP {response.status}: {error_text}")
                        
                        # 成功响应
                        try:
                            return await response.json()
                        except Exception:
                            text = await response.text()
                            return {"raw_data": text}
                            
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries + 1}), {wait_time}秒后重试: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"请求最终失败: {e}")
                    raise ServiceUnavailableError(f"网络请求失败: {e}")
            except Exception as e:
                logger.error(f"未知错误: {e}")
                raise InternalServerError(f"内部错误: {e}")
        
        raise ServiceUnavailableError("请求重试次数已用完")
    
    async def get(self, url: str, **kwargs) -> Dict[str, Any]:
        """GET请求"""
        return await self.safe_request('GET', url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> Dict[str, Any]:
        """POST请求"""
        return await self.safe_request('POST', url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> Dict[str, Any]:
        """PUT请求"""
        return await self.safe_request('PUT', url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> Dict[str, Any]:
        """DELETE请求"""
        return await self.safe_request('DELETE', url, **kwargs)
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            current_time = datetime.now()
            
            # 检查是否需要进行健康检查
            if (self._last_health_check and 
                current_time - self._last_health_check < timedelta(seconds=self._health_check_interval)):
                return True
            
            # 检查session状态
            if self.session is None or self.session.closed:
                return False
            
            # 执行简单的网络测试（可选）
            # 这里可以添加对特定端点的ping测试
            
            self._last_health_check = current_time
            return True
            
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计信息"""
        stats = self._connection_stats.copy()
        
        if self.session and not self.session.closed:
            connector = self.session.connector
            try:
                # 尝试获取连接器统计信息
                if hasattr(connector, '_conns'):
                    stats["active_connections"] = len(connector._conns)
                
                # 安全地获取连接器属性
                if hasattr(connector, 'limit'):
                    stats["connection_limit"] = connector.limit
                if hasattr(connector, 'limit_per_host'):
                    stats["per_host_limit"] = connector.limit_per_host
                if hasattr(connector, '_keepalive_timeout'):
                    stats["keepalive_timeout"] = connector._keepalive_timeout
                elif hasattr(connector, 'keepalive_timeout'):
                    stats["keepalive_timeout"] = connector.keepalive_timeout
                    
            except Exception as e:
                logger.debug(f"获取连接器统计信息时出错: {e}")
                # 忽略错误，继续返回基本统计
        
        stats.update({
            "session_active": self.session is not None and not self.session.closed,
            "last_health_check": self._last_health_check,
            "health_check_interval": self._health_check_interval
        })
        
        return stats
    
    async def close(self):
        """关闭连接管理器"""
        async with HTTPConnectionManager._lock:
            if self.session and not self.session.closed:
                await self.session.close()
                self.session = None
                logger.info("🔒 HTTP连接池已关闭")
    
    async def reconnect(self):
        """重新连接"""
        logger.info("重新连接HTTP连接池...")
        await self.close()
        await self._ensure_session()
        logger.info("✅ HTTP连接池重新连接成功")


# 全局HTTP连接管理器实例
http_manager = HTTPConnectionManager()


async def get_http_manager() -> HTTPConnectionManager:
    """获取HTTP连接管理器实例"""
    return http_manager


@asynccontextmanager
async def http_session():
    """获取HTTP session的上下文管理器"""
    async with http_manager.get_session() as session:
        yield session


async def safe_http_request(method: str, url: str, **kwargs) -> Dict[str, Any]:
    """安全的HTTP请求函数"""
    return await http_manager.safe_request(method, url, **kwargs)


async def cleanup_http_resources():
    """清理HTTP资源"""
    await http_manager.close()