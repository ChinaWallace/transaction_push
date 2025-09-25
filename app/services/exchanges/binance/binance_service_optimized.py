# -*- coding: utf-8 -*-
"""
币安交易所服务 - 极度优化版本
Binance Exchange Service - Ultra Optimized Version
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import asyncio
import aiohttp
import hmac
import hashlib
import time
import urllib.parse

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError, APIConnectionError
from app.utils.http_manager import get_http_manager
from app.services.exchanges.binance.binance_region_handler import get_binance_region_handler, get_optimal_binance_config
from app.services.exchanges.binance.binance_batch_optimizer import get_batch_optimizer

logger = get_logger(__name__)
settings = get_settings()


class UltraOptimizedBinanceRateLimiter:
    """币安速率限制器 - 极度优化版本"""
    
    def __init__(self):
        # 币安API限制配置 - 极度优化设置
        self.limits = {
            'requests_per_minute': 1200,  # 每分钟1200次
            'orders_per_second': 10,      # 每秒10次
            'orders_per_day': 200000      # 每日20万次
        }
        
        # 请求计数器
        self.request_counts = {
            'minute': {'count': 0, 'reset_time': time.time() + 60},
            'second': {'count': 0, 'reset_time': time.time() + 1},
            'day': {'count': 0, 'reset_time': time.time() + 86400}
        }
        
        # 动态调整参数 - 极度优化
        self.current_weight = 1
        self.base_interval = 0.05      # 基础请求间隔50ms
        self.max_interval = 1.0        # 最大请求间隔1秒
        
        # 批量处理优化
        self.batch_size = 100          # 增大批量处理大小
        self.batch_interval = 0.5      # 减少批量处理间隔
        
        logger.debug("🚦 币安速率限制器初始化完成（极度优化版本）")
    
    async def acquire_permit(self, weight: int = 1) -> float:
        """获取请求许可 - 极度优化版本"""
        current_time = time.time()
        
        # 重置计数器
        self._reset_counters(current_time)
        
        # 检查是否超过限制 - 使用更宽松的检查
        if self._is_rate_limited():
            wait_time = self._calculate_wait_time()
            await asyncio.sleep(wait_time)
            return wait_time
        
        # 更新计数器
        self._update_counters(weight)
        
        # 极小的动态间隔
        interval = max(0.01, self.base_interval / max(1, self.current_weight))
        if interval > 0.01:
            await asyncio.sleep(interval)
        
        return interval
    
    def _reset_counters(self, current_time: float):
        """重置过期的计数器"""
        for period, data in self.request_counts.items():
            if current_time >= data['reset_time']:
                data['count'] = 0
                if period == 'minute':
                    data['reset_time'] = current_time + 60
                elif period == 'second':
                    data['reset_time'] = current_time + 1
                elif period == 'day':
                    data['reset_time'] = current_time + 86400
    
    def _is_rate_limited(self) -> bool:
        """检查是否触发速率限制 - 极度优化"""
        minute_limit = self.limits['requests_per_minute'] * 0.98  # 98%安全边际
        second_limit = self.limits['orders_per_second'] * 0.95    # 95%安全边际
        
        return (self.request_counts['minute']['count'] >= minute_limit or
                self.request_counts['second']['count'] >= second_limit)
    
    def _calculate_wait_time(self) -> float:
        """计算等待时间 - 极度优化"""
        minute_remaining = 60 - (time.time() - (self.request_counts['minute']['reset_time'] - 60))
        second_remaining = 1 - (time.time() - (self.request_counts['second']['reset_time'] - 1))
        
        # 返回最小等待时间
        return max(0.1, min(minute_remaining / 60, second_remaining))
    
    def _update_counters(self, weight: int):
        """更新计数器"""
        self.request_counts['minute']['count'] += weight
        self.request_counts['second']['count'] += weight
        self.request_counts['day']['count'] += weight
        self.current_weight = weight


# 创建全局实例
_ultra_rate_limiter = UltraOptimizedBinanceRateLimiter()


async def get_ultra_optimized_positions() -> List[Dict[str, Any]]:
    """获取合约持仓数据 - 极度优化版本"""
    try:
        logger.debug("🔍 获取币安合约持仓数据（极度优化）")
        
        # 使用批量优化器检查缓存
        batch_optimizer = get_batch_optimizer()
        cached_result = await batch_optimizer.add_to_batch("futures_positions", {})
        
        if cached_result:
            logger.debug("📋 使用缓存的合约持仓数据")
            return cached_result
        
        # 获取HTTP管理器
        http_manager = get_http_manager()
        
        # 获取币安配置
        config = get_optimal_binance_config()
        base_url = config['base_url']
        
        # 构建请求
        endpoint = '/fapi/v2/positionRisk'
        timestamp = int(time.time() * 1000)
        
        # 构建查询参数
        params = {
            'timestamp': timestamp,
            'recvWindow': 5000
        }
        
        # 生成签名
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            settings.binance_secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params['signature'] = signature
        
        # 构建请求头
        headers = {
            'X-MBX-APIKEY': settings.binance_api_key,
            'Content-Type': 'application/json'
        }
        
        # 获取速率限制许可
        await _ultra_rate_limiter.acquire_permit(1)
        
        # 发送请求
        url = f"{base_url}{endpoint}"
        
        async with http_manager.session.get(
            url, 
            params=params, 
            headers=headers,
            proxy=config.get('proxy'),
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 200:
                positions_data = await response.json()
                
                positions = []
                
                # 批量处理持仓数据，只返回有持仓的合约
                for position in positions_data:
                    try:
                        position_amt = float(position.get('positionAmt', 0))
                        unrealized_pnl = float(position.get('unRealizedProfit', 0))
                        
                        # 只返回有持仓或有未实现盈亏的合约
                        if abs(position_amt) > 0.0001 or abs(unrealized_pnl) > 0.01:
                            positions.append({
                                'symbol': position['symbol'],
                                'positionAmt': position['positionAmt'],
                                'entryPrice': position['entryPrice'],
                                'markPrice': position['markPrice'],
                                'unRealizedProfit': position['unRealizedProfit'],
                                'percentage': position.get('percentage', '0'),
                                'positionSide': position.get('positionSide', 'BOTH')
                            })
                    except (ValueError, TypeError) as e:
                        logger.debug(f"⚠️ 跳过无效持仓数据: {position}, 错误: {e}")
                        continue
                
                logger.info(f"✅ 获取币安合约持仓数据成功: {len(positions)} 个有效持仓")
                
                # 缓存结果
                batch_optimizer._cache_result("futures_positions", positions)
                
                return positions
            else:
                error_text = await response.text()
                logger.error(f"❌ 币安合约持仓API请求失败: {response.status} - {error_text}")
                return []
                
    except Exception as e:
        logger.error(f"❌ 获取合约持仓数据失败: {e}")
        return []


async def test_ultra_optimized_service():
    """测试极度优化的服务"""
    print("🚀 测试极度优化的币安合约持仓服务")
    
    try:
        # 并发测试
        tasks = []
        for i in range(10):
            task = get_ultra_optimized_positions()
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        print(f"✅ 并发测试成功: {success_count}/10")
        
        # 显示第一个成功结果
        for result in results:
            if not isinstance(result, Exception) and result:
                print(f"📊 合约持仓数量: {len(result)}")
                if result:
                    print(f"📋 示例持仓: {result[0]}")
                break
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(test_ultra_optimized_service())