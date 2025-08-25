# -*- coding: utf-8 -*-
"""
OKX API频率限制管理器
基于OKX官方文档的API限制规则进行精确控制
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


class APIType(Enum):
    """API类型枚举"""
    PUBLIC = "public"           # 公开接口
    PRIVATE = "private"         # 私有接口
    MARKET_DATA = "market_data" # 市场数据接口
    TRADING = "trading"         # 交易接口


@dataclass
class RateLimitRule:
    """频率限制规则"""
    requests_per_second: int
    requests_per_minute: int
    burst_limit: int  # 突发请求限制
    cooldown_seconds: float  # 冷却时间


class OKXRateLimiter:
    """OKX API频率限制管理器"""
    
    # OKX官方API限制规则 (基于2024年最新文档)
    RATE_LIMITS = {
        APIType.PUBLIC: RateLimitRule(
            requests_per_second=20,
            requests_per_minute=1200,
            burst_limit=5,
            cooldown_seconds=0.05  # 50ms
        ),
        APIType.PRIVATE: RateLimitRule(
            requests_per_second=10,
            requests_per_minute=600,
            burst_limit=3,
            cooldown_seconds=0.1   # 100ms
        ),
        APIType.MARKET_DATA: RateLimitRule(
            requests_per_second=40,
            requests_per_minute=2400,
            burst_limit=10,
            cooldown_seconds=0.025  # 25ms
        ),
        APIType.TRADING: RateLimitRule(
            requests_per_second=5,
            requests_per_minute=300,
            burst_limit=2,
            cooldown_seconds=0.2   # 200ms
        )
    }
    
    def __init__(self):
        self.request_history: Dict[APIType, list] = {
            api_type: [] for api_type in APIType
        }
        self.last_request_time: Dict[str, datetime] = {}
        self.burst_count: Dict[APIType, int] = {
            api_type: 0 for api_type in APIType
        }
        self.is_cooling_down: Dict[APIType, bool] = {
            api_type: False for api_type in APIType
        }
    
    def _classify_endpoint(self, endpoint: str) -> APIType:
        """根据端点分类API类型"""
        if '/account/' in endpoint or '/trade/' in endpoint:
            if '/trade/order' in endpoint or '/trade/cancel' in endpoint:
                return APIType.TRADING
            return APIType.PRIVATE
        elif '/market/' in endpoint:
            return APIType.MARKET_DATA
        else:
            return APIType.PUBLIC
    
    async def acquire_permit(self, endpoint: str) -> bool:
        """获取API调用许可"""
        api_type = self._classify_endpoint(endpoint)
        rule = self.RATE_LIMITS[api_type]
        current_time = datetime.now()
        
        # 检查是否在冷却期
        if self.is_cooling_down[api_type]:
            logger.warning(f"API {api_type.value} 正在冷却中，拒绝请求: {endpoint}")
            return False
        
        # 清理过期的请求记录
        self._cleanup_old_requests(api_type, current_time)
        
        # 检查每秒限制
        recent_requests = [
            req_time for req_time in self.request_history[api_type]
            if (current_time - req_time).total_seconds() <= 1.0
        ]
        
        if len(recent_requests) >= rule.requests_per_second:
            logger.warning(f"API {api_type.value} 每秒限制已达上限: {len(recent_requests)}/{rule.requests_per_second}")
            await self._enter_cooldown(api_type, rule.cooldown_seconds)
            return False
        
        # 检查每分钟限制
        minute_requests = [
            req_time for req_time in self.request_history[api_type]
            if (current_time - req_time).total_seconds() <= 60.0
        ]
        
        if len(minute_requests) >= rule.requests_per_minute:
            logger.warning(f"API {api_type.value} 每分钟限制已达上限: {len(minute_requests)}/{rule.requests_per_minute}")
            await self._enter_cooldown(api_type, rule.cooldown_seconds * 10)  # 更长冷却时间
            return False
        
        # 检查突发请求限制
        if self.burst_count[api_type] >= rule.burst_limit:
            logger.info(f"API {api_type.value} 突发请求限制，等待冷却")
            await asyncio.sleep(rule.cooldown_seconds)
            self.burst_count[api_type] = 0
        
        # 检查最小请求间隔
        endpoint_key = f"{api_type.value}:{endpoint}"
        if endpoint_key in self.last_request_time:
            time_diff = (current_time - self.last_request_time[endpoint_key]).total_seconds()
            if time_diff < rule.cooldown_seconds:
                wait_time = rule.cooldown_seconds - time_diff
                logger.debug(f"等待最小间隔: {wait_time:.3f}秒")
                await asyncio.sleep(wait_time)
        
        # 记录请求
        self.request_history[api_type].append(current_time)
        self.last_request_time[endpoint_key] = datetime.now()
        self.burst_count[api_type] += 1
        
        return True
    
    def _cleanup_old_requests(self, api_type: APIType, current_time: datetime):
        """清理过期的请求记录"""
        cutoff_time = current_time - timedelta(minutes=2)  # 保留2分钟内的记录
        self.request_history[api_type] = [
            req_time for req_time in self.request_history[api_type]
            if req_time > cutoff_time
        ]
    
    async def _enter_cooldown(self, api_type: APIType, duration: float):
        """进入冷却期"""
        self.is_cooling_down[api_type] = True
        logger.warning(f"API {api_type.value} 进入冷却期: {duration}秒")
        
        await asyncio.sleep(duration)
        
        self.is_cooling_down[api_type] = False
        self.burst_count[api_type] = 0
        logger.info(f"API {api_type.value} 冷却期结束")
    
    def get_rate_limit_status(self) -> Dict[str, Dict[str, any]]:
        """获取频率限制状态"""
        current_time = datetime.now()
        status = {}
        
        for api_type in APIType:
            rule = self.RATE_LIMITS[api_type]
            
            # 统计最近1秒和1分钟的请求数
            recent_1s = len([
                req_time for req_time in self.request_history[api_type]
                if (current_time - req_time).total_seconds() <= 1.0
            ])
            
            recent_1m = len([
                req_time for req_time in self.request_history[api_type]
                if (current_time - req_time).total_seconds() <= 60.0
            ])
            
            status[api_type.value] = {
                'requests_last_second': recent_1s,
                'requests_last_minute': recent_1m,
                'limit_per_second': rule.requests_per_second,
                'limit_per_minute': rule.requests_per_minute,
                'burst_count': self.burst_count[api_type],
                'burst_limit': rule.burst_limit,
                'is_cooling_down': self.is_cooling_down[api_type],
                'utilization_1s': f"{recent_1s/rule.requests_per_second*100:.1f}%",
                'utilization_1m': f"{recent_1m/rule.requests_per_minute*100:.1f}%"
            }
        
        return status
    
    def reset_limits(self, api_type: Optional[APIType] = None):
        """重置频率限制计数器"""
        if api_type:
            self.request_history[api_type].clear()
            self.burst_count[api_type] = 0
            self.is_cooling_down[api_type] = False
            logger.info(f"已重置 {api_type.value} API限制计数器")
        else:
            for at in APIType:
                self.request_history[at].clear()
                self.burst_count[at] = 0
                self.is_cooling_down[at] = False
            self.last_request_time.clear()
            logger.info("已重置所有API限制计数器")


# 全局频率限制管理器实例
_rate_limiter = None

def get_okx_rate_limiter() -> OKXRateLimiter:
    """获取OKX频率限制管理器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = OKXRateLimiter()
    return _rate_limiter