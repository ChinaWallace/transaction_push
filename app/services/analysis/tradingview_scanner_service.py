# -*- coding: utf-8 -*-
"""
TradingView 扫描服务
TradingView Scanner Service

实现TradingView强势标的扫描功能，包括数据获取、解析和通知推送
"""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.tradingview_config import (
    get_default_scan_request_data,
    get_proxy_config,
    get_request_cookies,
    get_request_headers,
    get_tradingview_config,
)
from app.schemas.tradingview import (
    TradingViewNotificationMessage,
    TradingViewScanRequest,
    TradingViewScanResponse,
    TradingViewStrongSymbolVO,
)
from app.utils.exceptions import TradingToolError


class TradingViewScannerService:
    """TradingView 扫描服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.config = get_tradingview_config()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # TradingView API 配置
        self.base_url = self.config.api_url
        self.headers = get_request_headers()
        self.cookies = get_request_cookies()
        self.proxy_config = get_proxy_config()
        
        # 历史记录缓存 (用于判断首次入选)
        self.historical_symbols: Dict[str, datetime] = {}
        
        # 通知服务
        self.notification_service = None
    
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
        
        try:
            # 初始化通知服务
            from app.services.notification.core_notification_service import (
                get_core_notification_service,
            )
            self.notification_service = await get_core_notification_service()
            
            self.initialized = True
            self.logger.info("✅ TradingView扫描服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ TradingView扫描服务初始化失败: {e}")
            raise TradingToolError(f"TradingView扫描服务初始化失败: {str(e)}") from e
    
    async def scan_strong_symbols(
        self, 
        custom_request: Optional[TradingViewScanRequest] = None
    ) -> TradingViewScanResponse:
        """
        扫描强势标的
        Scan strong symbols from TradingView
        
        Args:
            custom_request: 自定义扫描请求参数
            
        Returns:
            TradingViewScanResponse: 扫描结果
        """
        if not self.initialized:
            await self.initialize()
        
        try:
            # 使用默认或自定义请求参数
            if custom_request:
                request_data = {
                    "columns": custom_request.columns,
                    "filter": custom_request.filter,
                    "ignore_unknown_fields": custom_request.ignore_unknown_fields,
                    "options": custom_request.options,
                    "range": custom_request.range,
                    "sort": custom_request.sort,
                    "symbols": custom_request.symbols,
                    "markets": custom_request.markets
                }
            else:
                # 使用配置文件中的默认请求数据
                request_data = get_default_scan_request_data()
            
            # 发送HTTP请求
            symbols_data = await self._fetch_tradingview_data(request_data)
            
            # 解析响应数据
            strong_symbols = await self._parse_response_data(symbols_data)
            
            # 检查首次入选状态
            await self._check_first_selection(strong_symbols)
            
            # 构建响应
            response = TradingViewScanResponse(
                success=True,
                total_count=len(strong_symbols),
                symbols=strong_symbols,
                scan_time=datetime.now(),
                message="扫描完成"
            )
            
            self.logger.info(f"✅ TradingView扫描完成，发现 {len(strong_symbols)} 个强势标的")
            return response
            
        except Exception as e:
            self.logger.error(f"❌ TradingView扫描失败: {e}")
            return TradingViewScanResponse(
                success=False,
                total_count=0,
                symbols=[],
                scan_time=datetime.now(),
                message=f"扫描失败: {str(e)}"
            )
    
    async def _fetch_tradingview_data(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取TradingView数据 - 带重试机制
        Fetch data from TradingView API with retry mechanism
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
                
                # 构建连接器配置
                connector = aiohttp.TCPConnector()
                
                async with aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector
                ) as session:
                    
                    # 构建请求参数
                    request_kwargs = {
                        'json': request_data,
                        'headers': self.headers,
                        'cookies': self.cookies
                    }
                    
                    # 如果有代理配置，添加到请求中
                    if self.proxy_config:
                        if 'https' in self.proxy_config:
                            request_kwargs['proxy'] = self.proxy_config['https']
                        elif 'http' in self.proxy_config:
                            request_kwargs['proxy'] = self.proxy_config['http']
                    
                    async with session.post(self.base_url, **request_kwargs) as response:
                        
                        if response.status != 200:
                            error_text = await response.text()
                            raise TradingToolError(
                                f"TradingView API请求失败: HTTP {response.status}, 响应: {error_text[:200]}"
                            )
                        
                        response_text = await response.text()
                        self.logger.debug(f"TradingView API响应 (尝试 {attempt + 1}): {response_text[:500]}...")
                        
                        return json.loads(response_text)
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                self.logger.warning(
                    f"TradingView API请求失败 (尝试 {attempt + 1}/{self.config.max_retries}): {str(e)}"
                )
                
                if attempt < self.config.max_retries - 1:
                    # 等待后重试
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                else:
                    # 最后一次尝试失败
                    break
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"响应数据解析失败: {str(e)}")
                raise TradingToolError(f"响应数据解析失败: {str(e)}") from e
            except Exception as e:
                self.logger.error(f"未知错误: {str(e)}")
                raise TradingToolError(f"请求失败: {str(e)}") from e
        
        # 所有重试都失败了
        raise TradingToolError(f"网络请求失败: {str(last_exception)}") from last_exception
    
    async def _parse_response_data(self, response_data: Dict[str, Any]) -> List[TradingViewStrongSymbolVO]:
        """
        解析响应数据
        Parse TradingView response data
        """
        strong_symbols = []
        
        try:
            data_list = response_data.get("data", [])
            
            for item in data_list:
                data_array = item.get("d", [])
                if len(data_array) < 22:  # 确保数据完整
                    continue
                
                # 解析数据字段 (根据columns顺序)
                symbol = data_array[0] if data_array[0] else "UNKNOWN"
                crypto_total_rank = data_array[7] if len(data_array) > 7 else None
                current_price = data_array[8] if len(data_array) > 8 else None  # close价格
                change_24h = data_array[14] if len(data_array) > 14 else None
                vol_to_market_cap = data_array[15] if len(data_array) > 15 else None
                volatility = data_array[21] if len(data_array) > 21 else None
                
                # 解析标签
                tags_array = data_array[20] if len(data_array) > 20 and isinstance(data_array[20], list) else []
                tags = ",".join(str(tag) for tag in tags_array) if tags_array else ""
                
                # 创建强势标的对象
                strong_symbol = TradingViewStrongSymbolVO(
                    symbol=symbol,
                    current_price=Decimal(str(current_price)) if current_price else None,
                    rank=crypto_total_rank if crypto_total_rank and crypto_total_rank > 0 else None,
                    effective_liquidity=Decimal(str(vol_to_market_cap)) if vol_to_market_cap else None,
                    volatility=Decimal(str(volatility)) if volatility else None,
                    change_24h=Decimal(str(change_24h)) if change_24h else None,
                    first_flag="否",  # 默认值，后续会更新
                    tags=tags
                )
                
                strong_symbols.append(strong_symbol)
            
            # 按波动率从高到低排序
            strong_symbols = await self._sort_by_volatility(strong_symbols)
            
            self.logger.info(f"解析到 {len(strong_symbols)} 个强势标的，已按波动率排序")
            return strong_symbols
            
        except Exception as e:
            self.logger.error(f"数据解析失败: {e}")
            raise TradingToolError(f"数据解析失败: {str(e)}") from e
    
    async def _sort_by_volatility(self, symbols: List[TradingViewStrongSymbolVO]) -> List[TradingViewStrongSymbolVO]:
        """
        按波动率从高到低排序
        Sort symbols by volatility from high to low
        
        Args:
            symbols: 待排序的标的列表
            
        Returns:
            List[TradingViewStrongSymbolVO]: 排序后的标的列表
        """
        try:
            # 按波动率排序，波动率为None的放在最后
            sorted_symbols = sorted(
                symbols,
                key=lambda x: (
                    x.volatility is not None,  # 有波动率数据的排在前面
                    x.volatility or Decimal('0')  # 按波动率从高到低排序
                ),
                reverse=True
            )
            
            # 记录排序结果
            if sorted_symbols:
                top_volatility = sorted_symbols[0].volatility or Decimal('0')
                bottom_volatility = sorted_symbols[-1].volatility or Decimal('0')
                self.logger.debug(
                    f"波动率排序完成: 最高 {top_volatility:.2f}%, 最低 {bottom_volatility:.2f}%"
                )
            
            return sorted_symbols
            
        except Exception as e:
            self.logger.warning(f"波动率排序失败，返回原始顺序: {e}")
            return symbols
    
    async def _check_first_selection(self, symbols: List[TradingViewStrongSymbolVO]) -> None:
        """
        检查首次入选状态
        Check first-time selection status
        """
        current_time = datetime.now()
        three_days_ago = current_time - timedelta(days=3)
        
        for symbol_vo in symbols:
            symbol = symbol_vo.symbol
            
            # 检查历史记录
            if symbol in self.historical_symbols:
                last_seen = self.historical_symbols[symbol]
                if last_seen > three_days_ago:
                    symbol_vo.first_flag = "否"
                else:
                    symbol_vo.first_flag = "是"
                    self.historical_symbols[symbol] = current_time
            else:
                # 首次出现
                symbol_vo.first_flag = "是"
                self.historical_symbols[symbol] = current_time
        
        # 清理过期的历史记录
        expired_symbols = [
            sym for sym, time in self.historical_symbols.items()
            if time < three_days_ago
        ]
        for sym in expired_symbols:
            del self.historical_symbols[sym]
    
    async def scan_and_notify(self) -> bool:
        """
        扫描并发送通知
        Scan and send notifications
        
        Returns:
            bool: 是否成功发送通知
        """
        try:
            # 执行扫描
            scan_result = await self.scan_strong_symbols()
            
            if not scan_result.success:
                self.logger.warning(f"扫描失败: {scan_result.message}")
                return False
            
            if not scan_result.symbols:
                self.logger.info("未发现符合条件的强势标的")
                return True
            
            # 构建通知消息
            notification_message = TradingViewNotificationMessage(
                symbols=scan_result.symbols,
                scan_time=scan_result.scan_time
            )
            
            # 发送通知
            if self.notification_service:
                message_text = notification_message.format_message()
                await self.notification_service.send_notification(
                    message=message_text
                )
                
                self.logger.info(f"✅ 已发送TradingView扫描通知，包含 {len(scan_result.symbols)} 个标的")
                return True
            else:
                self.logger.warning("通知服务未初始化，跳过通知发送")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 扫描并通知失败: {e}")
            return False
    
    async def get_scan_history(self, days: int = 7) -> Dict[str, Any]:
        """
        获取扫描历史
        Get scan history
        
        Args:
            days: 查询天数
            
        Returns:
            Dict: 历史数据统计
        """
        cutoff_time = datetime.now() - timedelta(days=days)
        
        recent_symbols = {
            symbol: last_seen 
            for symbol, last_seen in self.historical_symbols.items()
            if last_seen > cutoff_time
        }
        
        return {
            "total_symbols": len(recent_symbols),
            "symbols": recent_symbols,
            "query_days": days,
            "query_time": datetime.now()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """服务健康检查"""
        try:
            # 测试API连接
            test_request = TradingViewScanRequest()
            test_request.range = [0, 1]  # 只获取1条数据进行测试
            
            test_result = await self.scan_strong_symbols(test_request)
            
            return {
                "status": "healthy" if test_result.success else "degraded",
                "initialized": self.initialized,
                "api_accessible": test_result.success,
                "notification_service": self.notification_service is not None,
                "historical_symbols_count": len(self.historical_symbols),
                "last_check": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "initialized": self.initialized,
                "last_check": datetime.now().isoformat()
            }


# 全局服务实例
_tradingview_scanner_service: Optional[TradingViewScannerService] = None


async def get_tradingview_scanner_service() -> TradingViewScannerService:
    """获取TradingView扫描服务实例 - 单例模式"""
    global _tradingview_scanner_service
    if _tradingview_scanner_service is None:
        _tradingview_scanner_service = TradingViewScannerService()
        await _tradingview_scanner_service.initialize()
    return _tradingview_scanner_service