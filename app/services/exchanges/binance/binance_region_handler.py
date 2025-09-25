# -*- coding: utf-8 -*-
"""
币安地区处理器
Binance Region Handler - 处理地区限制和自动切换
"""

import aiohttp
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError, APIConnectionError

logger = get_logger(__name__)
settings = get_settings()


class BinanceRegionHandler:
    """
    币安地区处理器
    处理地区限制，自动选择可用的API端点
    """
    
    def __init__(self):
        # 可用的API端点列表（按优先级排序）- 只使用主网，强制使用代理
        self.api_endpoints = [
            {
                'name': 'binance_main',
                'base_url': 'https://api.binance.com',
                'description': '币安主网API（强制代理）',
                'requires_proxy': True,  # 强制使用代理
                'priority': 1
            }
            # 移除美国币安和测试网选项，只使用主网
        ]
        
        # 当前可用的端点
        self.available_endpoints: List[Dict[str, Any]] = []
        self.current_endpoint: Optional[Dict[str, Any]] = None
        
        # 检测结果缓存
        self.last_check_time: Optional[datetime] = None
        self.check_interval = timedelta(hours=1)  # 每小时重新检测一次
        
        logger.info("🌍 币安地区处理器初始化完成")
        
        # 强制验证代理配置
        self._validate_proxy_config()
    
    async def detect_available_endpoints(self) -> List[Dict[str, Any]]:
        """检测可用的API端点"""
        
        # 检查缓存是否有效
        if (self.last_check_time and 
            datetime.now() - self.last_check_time < self.check_interval and
            self.available_endpoints):
            logger.debug("🔍 使用缓存的端点检测结果")
            return self.available_endpoints
        
        logger.info("🔍 开始检测可用的币安API端点...")
        available = []
        
        for endpoint in self.api_endpoints:
            if await self._test_endpoint(endpoint):
                available.append(endpoint)
                logger.info(f"✅ 端点可用: {endpoint['description']} ({endpoint['base_url']})")
            else:
                logger.warning(f"❌ 端点不可用: {endpoint['description']} ({endpoint['base_url']})")
        
        # 按优先级排序
        available.sort(key=lambda x: x['priority'])
        
        self.available_endpoints = available
        self.last_check_time = datetime.now()
        
        if available:
            logger.info(f"🌍 检测完成，发现 {len(available)} 个可用端点")
        else:
            logger.error("❌ 未发现任何可用的币安API端点")
        
        return available
    
    async def _test_endpoint(self, endpoint: Dict[str, Any]) -> bool:
        """测试单个端点的可用性"""
        try:
            url = f"{endpoint['base_url']}/api/v3/ping"
            
            # 配置请求参数
            kwargs = {
                'timeout': aiohttp.ClientTimeout(total=10),
                'headers': {'User-Agent': 'Python Trading Tool/1.0'}
            }
            
            # 强制使用代理 - 检查代理配置
            if not settings.proxy_enabled or not settings.proxy_url:
                logger.error("❌ 代理未配置或未启用，无法连接币安API")
                return False
            
            # 强制为所有端点使用代理
            kwargs['proxy'] = settings.proxy_url
            logger.debug(f"🔌 强制使用代理连接: {endpoint['name']} -> {settings.proxy_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, **kwargs) as response:
                    # 检查响应状态
                    if response.status == 200:
                        logger.info(f"✅ 代理连接成功: {endpoint['name']}")
                        return True
                    elif response.status == 451:
                        # 451是地区限制，但通过代理应该能访问，可能是代理IP问题
                        logger.warning(f"⚠️ 地区限制错误 (451): {endpoint['name']} - 代理IP可能仍被限制")
                        # 尝试读取响应内容获取更多信息
                        try:
                            content = await response.text()
                            if "restricted" in content.lower() or "unavailable" in content.lower():
                                logger.warning(f"⚠️ 确认为地区限制: {endpoint['name']}")
                                return False
                        except:
                            pass
                        # 如果无法确定具体原因，暂时认为可用但记录警告
                        logger.warning(f"⚠️ 状态码451但继续尝试: {endpoint['name']}")
                        return True
                    else:
                        logger.warning(f"⚠️ 代理连接响应异常: {endpoint['name']} - 状态码: {response.status}")
                        return False
                    
        except Exception as e:
            logger.error(f"❌ 代理连接失败: {endpoint['name']} - {e}")
            return False
    
    async def get_best_endpoint(self) -> Optional[Dict[str, Any]]:
        """获取最佳可用端点"""
        
        # 如果当前端点仍然可用，继续使用
        if self.current_endpoint and await self._test_endpoint(self.current_endpoint):
            return self.current_endpoint
        
        # 重新检测可用端点
        available_endpoints = await self.detect_available_endpoints()
        
        if not available_endpoints:
            logger.error("❌ 没有可用的币安API端点")
            return None
        
        # 选择优先级最高的端点
        best_endpoint = available_endpoints[0]
        
        if self.current_endpoint != best_endpoint:
            logger.info(f"🔄 切换到最佳端点: {best_endpoint['description']}")
            self.current_endpoint = best_endpoint
        
        return best_endpoint
    
    def get_request_config(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """获取请求配置"""
        config = {
            'base_url': endpoint['base_url'],
            'headers': {'User-Agent': 'Python Trading Tool/1.0'},
            'timeout': aiohttp.ClientTimeout(total=30)
        }
        
        # 强制使用代理 - 检查代理配置
        if not settings.proxy_enabled or not settings.proxy_url:
            raise TradingToolError("代理未配置或未启用，无法连接币安API")
        
        # 强制为所有请求配置代理
        config['proxy'] = settings.proxy_url
        logger.info(f"🔌 强制使用代理: {endpoint['name']} -> {settings.proxy_url}")
        
        return config
    
    def get_status(self) -> Dict[str, Any]:
        """获取地区处理器状态"""
        return {
            'current_endpoint': self.current_endpoint,
            'available_endpoints': self.available_endpoints,
            'last_check_time': self.last_check_time,
            'total_endpoints': len(self.api_endpoints),
            'available_count': len(self.available_endpoints)
        }
    
    async def force_refresh(self) -> None:
        """强制刷新端点检测"""
        logger.info("🔄 强制刷新币安API端点检测...")
        self.last_check_time = None
        self.available_endpoints.clear()
        self.current_endpoint = None
        await self.detect_available_endpoints()
    
    def _validate_proxy_config(self) -> None:
        """验证代理配置"""
        if not settings.proxy_enabled:
            raise TradingToolError("❌ 代理未启用，无法连接币安API。请在.env文件中设置 PROXY_ENABLED=true")
        
        if not settings.proxy_url:
            raise TradingToolError("❌ 代理URL未配置，无法连接币安API。请在.env文件中设置 PROXY_URL")
        
        logger.info(f"✅ 代理配置验证通过: {settings.proxy_url}")
        logger.warning("⚠️ 强制代理模式：所有币安API请求都将通过代理")


# 全局地区处理器实例
_region_handler: Optional[BinanceRegionHandler] = None


def get_binance_region_handler() -> BinanceRegionHandler:
    """获取币安地区处理器实例"""
    global _region_handler
    if _region_handler is None:
        _region_handler = BinanceRegionHandler()
    return _region_handler


async def get_optimal_binance_config() -> Dict[str, Any]:
    """获取最优的币安配置"""
    handler = get_binance_region_handler()
    endpoint = await handler.get_best_endpoint()
    
    if not endpoint:
        raise APIConnectionError("无法找到可用的币安API端点")
    
    config = handler.get_request_config(endpoint)
    
    logger.info(f"🌍 使用币安端点: {endpoint['description']} ({endpoint['base_url']})")
    
    return {
        'base_url': config['base_url'],
        'proxy': config.get('proxy'),
        'headers': config['headers'],
        'timeout': config['timeout'],
        'endpoint_info': endpoint
    }