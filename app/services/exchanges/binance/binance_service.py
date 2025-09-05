# -*- coding: utf-8 -*-
"""
币安交易所服务
Binance Exchange Service - 提供币安交易所数据获取和交易功能
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

logger = get_logger(__name__)
settings = get_settings()


class BinanceRateLimiter:
    """币安速率限制器"""
    
    def __init__(self):
        # 币安API限制配置
        self.limits = {
            'requests_per_minute': 1200,  # 每分钟请求数限制
            'orders_per_second': 10,      # 每秒订单数限制
            'orders_per_day': 200000      # 每日订单数限制
        }
        
        # 请求计数器
        self.request_counts = {
            'minute': {'count': 0, 'reset_time': time.time() + 60},
            'second': {'count': 0, 'reset_time': time.time() + 1},
            'day': {'count': 0, 'reset_time': time.time() + 86400}
        }
        
        # 动态调整参数
        self.current_weight = 1
        self.base_interval = 0.05  # 基础请求间隔50ms
        self.max_interval = 2.0    # 最大请求间隔2秒
        
        logger.debug("🚦 币安速率限制器初始化完成")
    
    async def acquire_permit(self, weight: int = 1) -> float:
        """获取请求许可"""
        current_time = time.time()
        
        # 重置计数器
        self._reset_counters(current_time)
        
        # 检查是否超过限制
        if self._is_rate_limited():
            wait_time = self._calculate_wait_time()
            logger.warning(f"🚦 触发速率限制，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)
            return wait_time
        
        # 更新计数器
        self._update_counters(weight)
        
        # 计算动态间隔
        interval = self._calculate_dynamic_interval()
        if interval > 0:
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
        """检查是否触发速率限制"""
        minute_limit = self.limits['requests_per_minute'] * 0.8  # 80%安全边际
        second_limit = self.limits['orders_per_second'] * 0.8
        
        return (self.request_counts['minute']['count'] >= minute_limit or
                self.request_counts['second']['count'] >= second_limit)
    
    def _calculate_wait_time(self) -> float:
        """计算等待时间"""
        current_time = time.time()
        
        # 计算到下一个重置时间的等待时间
        minute_wait = max(0, self.request_counts['minute']['reset_time'] - current_time)
        second_wait = max(0, self.request_counts['second']['reset_time'] - current_time)
        
        return max(minute_wait, second_wait, 1.0)  # 至少等待1秒
    
    def _update_counters(self, weight: int):
        """更新请求计数器"""
        self.request_counts['minute']['count'] += weight
        self.request_counts['second']['count'] += weight
        self.request_counts['day']['count'] += weight
    
    def _calculate_dynamic_interval(self) -> float:
        """计算动态请求间隔"""
        # 基于当前负载动态调整间隔
        minute_usage = self.request_counts['minute']['count'] / self.limits['requests_per_minute']
        
        if minute_usage > 0.8:
            return self.max_interval
        elif minute_usage > 0.6:
            return self.base_interval * 4
        elif minute_usage > 0.4:
            return self.base_interval * 2
        else:
            return self.base_interval
    
    def update_from_headers(self, headers: Dict[str, str]):
        """从响应头更新限制信息"""
        try:
            # 币安在响应头中提供限制信息
            if 'X-MBX-USED-WEIGHT-1M' in headers:
                used_weight = int(headers['X-MBX-USED-WEIGHT-1M'])
                self.current_weight = used_weight
                
            if 'Retry-After' in headers:
                retry_after = int(headers['Retry-After'])
                logger.warning(f"🚦 服务器要求等待 {retry_after} 秒")
                
        except Exception as e:
            logger.debug(f"🔍 解析响应头异常: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """获取限制器状态"""
        current_time = time.time()
        return {
            'current_weight': self.current_weight,
            'request_counts': self.request_counts.copy(),
            'limits': self.limits.copy(),
            'base_interval': self.base_interval,
            'max_interval': self.max_interval,
            'current_time': current_time
        }


class BinanceService:
    """币安交易所服务类"""
    
    def __init__(self):
        self.config = settings.binance_config
        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.testnet = self.config["testnet"]
        
        # API端点 - 使用地区处理器动态选择
        if self.testnet:
            self.base_url = "https://testnet.binancefuture.com"
        else:
            self.base_url = self.config["base_url"]
        
        # 地区处理器
        self.region_handler = get_binance_region_handler()
        self._optimal_config = None
        
        self.http_manager = None
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0
        self._current_interval = 0.1  # 币安允许更高频率
        
        # 增强的连接管理
        self._connection_pool = None
        self._rate_limiter = None
        self._api_key_validated = False
        self._connection_health = {
            'last_successful_request': None,
            'consecutive_failures': 0,
            'total_requests': 0,
            'total_failures': 0
        }
        
        # API密钥验证将在首次使用时进行
        
        # 服务器时间同步
        self._server_time_offset = 0  # 本地时间与服务器时间的偏移量（毫秒）
        self._last_time_sync = 0  # 上次同步时间
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_http_manager()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"币安服务异常: {exc_type.__name__}: {exc_val}")
    
    async def _validate_api_credentials(self):
        """验证API凭据"""
        try:
            if not self.api_key or not self.secret_key:
                logger.warning("⚠️ 币安API凭据未配置")
                return False
            
            # 验证API密钥格式
            if len(self.api_key) < 32 or len(self.secret_key) < 32:
                logger.error("❌ 币安API密钥格式无效")
                return False
            
            # 获取最优配置
            if not self.testnet:
                try:
                    self._optimal_config = await get_optimal_binance_config()
                    test_url = f"{self._optimal_config['base_url']}/fapi/v1/ping"
                    logger.info(f"🌍 使用最优端点进行API验证: {self._optimal_config['endpoint_info']['description']}")
                except Exception as config_error:
                    logger.warning(f"⚠️ 获取最优配置失败，使用默认配置: {config_error}")
                    test_url = f"{self.base_url}/fapi/v1/ping"
            else:
                test_url = f"{self.base_url}/fapi/v1/ping"
            
            # 测试API连接
            await self._ensure_http_manager()
            
            # 配置请求参数
            kwargs = {
                'timeout': aiohttp.ClientTimeout(total=10),
                'headers': {'User-Agent': 'Python Trading Tool/1.0'}
            }
            
            # 使用最优配置的代理设置
            if self._optimal_config and self._optimal_config.get('proxy'):
                kwargs['proxy'] = self._optimal_config['proxy']
                logger.debug(f"🔌 API验证使用代理: {self._optimal_config['proxy']}")
            elif settings.proxy_enabled and settings.proxy_url:
                kwargs['proxy'] = settings.proxy_url
                logger.debug(f"🔌 API验证使用默认代理: {settings.proxy_url}")
            
            async with self.http_manager.get_session() as session:
                async with session.get(test_url, **kwargs) as response:
                    if response.status == 200:
                        self._api_key_validated = True
                        logger.info("✅ 币安API凭据验证成功")
                        return True
                    elif response.status == 451:
                        logger.error("❌ 币安API地区限制，请检查代理配置")
                        return False
                    else:
                        logger.error(f"❌ 币安API连接测试失败: {response.status}")
                        return False
                
        except Exception as e:
            logger.error(f"❌ 币安API凭据验证异常: {e}")
            return False
    
    async def _ensure_http_manager(self):
        """确保HTTP管理器可用"""
        if not self.http_manager:
            self.http_manager = await get_http_manager()
            logger.debug("✅ 币安服务已连接到统一HTTP连接池")
            
            # 初始化速率限制器
            if not self._rate_limiter:
                self._rate_limiter = BinanceRateLimiter()
    
    async def _check_connection_health(self) -> bool:
        """检查连接健康状态"""
        try:
            # 如果连续失败次数过多，需要重新验证
            if self._connection_health['consecutive_failures'] > 5:
                logger.warning("⚠️ 连续失败次数过多，重新验证API凭据")
                return await self._validate_api_credentials()
            
            # 检查最近是否有成功请求
            if self._connection_health['last_successful_request']:
                from datetime import datetime, timedelta
                if datetime.now() - self._connection_health['last_successful_request'] > timedelta(minutes=30):
                    logger.info("🔍 长时间无成功请求，执行健康检查")
                    return await self._validate_api_credentials()
            
            # 如果还没有验证过API凭据，先进行验证
            if not self._api_key_validated:
                return await self._validate_api_credentials()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 连接健康检查异常: {e}")
            return False
    
    def _generate_signature(self, query_string: str) -> str:
        """生成币安API签名"""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def _get_server_time(self) -> Optional[int]:
        """获取币安服务器时间"""
        try:
            # 不需要签名的请求
            async with self.http_manager.get_session() as session:
                async with session.get(f"{self.base_url}/fapi/v1/time") as response:
                    if response.status == 200:
                        data = await response.json()
                        return int(data.get('serverTime', 0))
            return None
        except Exception as e:
            logger.debug(f"🔍 获取服务器时间失败: {e}")
            return None
    
    async def _sync_server_time(self) -> None:
        """同步服务器时间"""
        try:
            current_time = time.time()
            
            # 每5分钟同步一次
            if current_time - self._last_time_sync < 300:
                return
            
            server_time_ms = await self._get_server_time()
            if server_time_ms:
                local_time_ms = int(current_time * 1000)
                self._server_time_offset = server_time_ms - local_time_ms
                self._last_time_sync = current_time
                
                if abs(self._server_time_offset) > 1000:  # 超过1秒差异才记录
                    logger.info(f"⏰ 币安服务器时间同步: 偏移量 {self._server_time_offset}ms")
                
        except Exception as e:
            logger.debug(f"🔍 同步服务器时间异常: {e}")
    
    def _get_synced_timestamp(self) -> int:
        """获取同步后的时间戳"""
        local_time_ms = int(time.time() * 1000)
        return local_time_ms + self._server_time_offset
    
    def _get_headers(self, signed: bool = False) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json',
            'X-MBX-APIKEY': self.api_key
        }
        return headers
    
    async def _make_request(self, method: str, endpoint: str, params: Dict = None, 
                          data: Dict = None, signed: bool = False, weight: int = 1) -> Dict[str, Any]:
        """发起API请求 - 增强版本，支持速率限制和指数退避"""
        
        # 检查连接健康状态
        if not await self._check_connection_health():
            raise APIConnectionError("币安API连接不健康")
        
        # 确保HTTP管理器和速率限制器可用
        await self._ensure_http_manager()
        
        # 获取速率限制许可
        if self._rate_limiter:
            await self._rate_limiter.acquire_permit(weight)
        
        # 使用最优配置的base_url，如果可用的话
        if self._optimal_config and not self.testnet:
            base_url = self._optimal_config['base_url']
        else:
            base_url = self.base_url
        
        url = f"{base_url}{endpoint}"
        
        # 处理查询参数
        query_params = params or {}
        
        # 如果需要签名
        if signed:
            if not self._api_key_validated:
                raise APIConnectionError("API凭据未验证")
            
            # 同步服务器时间
            await self._sync_server_time()
            
            # 使用同步后的时间戳
            timestamp = self._get_synced_timestamp()
            query_params['timestamp'] = timestamp
            
            # 构建查询字符串
            query_string = urllib.parse.urlencode(query_params)
            signature = self._generate_signature(query_string)
            query_params['signature'] = signature
        
        headers = self._get_headers(signed)
        
        # 增强的重试机制 - 指数退避
        max_retries = 5
        base_delay = 1.0
        max_delay = 30.0
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # 更新请求统计
                self._connection_health['total_requests'] += 1
                
                async with self.http_manager.get_session() as session:
                    kwargs = {
                        'headers': headers,
                        'params': query_params,
                        'timeout': aiohttp.ClientTimeout(total=30)  # 30秒超时
                    }
                    
                    if data:
                        kwargs['json'] = data
                    
                    # 强制使用代理（币安在某些地区有访问限制）
                    if settings.proxy_enabled and settings.proxy_url:
                        kwargs['proxy'] = settings.proxy_url
                        logger.debug(f"🔌 使用代理访问币安API: {settings.proxy_url}")
                    
                    async with session.request(method, url, **kwargs) as response:
                        # 更新速率限制器状态
                        if self._rate_limiter:
                            self._rate_limiter.update_from_headers(dict(response.headers))
                        
                        # 处理不同的HTTP状态码
                        if response.status == 200:
                            # 成功请求
                            result = await response.json()
                            self._connection_health['last_successful_request'] = datetime.now()
                            self._connection_health['consecutive_failures'] = 0
                            
                            logger.debug(f"✅ 币安API请求成功: {method} {endpoint}")
                            return result
                            
                        elif response.status == 429:  # 频率限制
                            error_text = await response.text()
                            retry_after = int(response.headers.get('Retry-After', 60))
                            
                            logger.warning(f"🚦 币安频率限制: {error_text}")
                            
                            if attempt < max_retries - 1:
                                wait_time = min(retry_after, max_delay)
                                logger.warning(f"⏰ 等待 {wait_time} 秒后重试 (尝试 {attempt + 1}/{max_retries})")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                raise APIConnectionError(f"币安频率限制，已达最大重试次数: {error_text}")
                        
                        elif response.status in [400, 401, 403]:  # 客户端错误，不重试
                            error_text = await response.text()
                            logger.error(f"❌ 币安API客户端错误: {response.status} - {error_text}")
                            
                            if response.status == 401:
                                self._api_key_validated = False
                                raise APIConnectionError(f"币安API认证失败: {error_text}")
                            else:
                                raise TradingToolError(f"币安API错误: {response.status} - {error_text}")
                        
                        elif response.status >= 500:  # 服务器错误，可重试
                            error_text = await response.text()
                            logger.warning(f"⚠️ 币安服务器错误: {response.status} - {error_text}")
                            
                            if attempt < max_retries - 1:
                                # 指数退避
                                wait_time = min(base_delay * (2 ** attempt), max_delay)
                                logger.warning(f"⏰ 服务器错误，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{max_retries})")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                raise APIConnectionError(f"币安服务器错误: {response.status} - {error_text}")
                        
                        else:  # 其他状态码
                            error_text = await response.text()
                            logger.error(f"❌ 币安API未知错误: {response.status} - {error_text}")
                            raise TradingToolError(f"币安API未知错误: {response.status}")
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                self._connection_health['total_failures'] += 1
                self._connection_health['consecutive_failures'] += 1
                
                if attempt < max_retries - 1:
                    # 指数退避
                    wait_time = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(f"🔌 网络请求失败，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ 币安API网络请求最终失败: {e}")
                    raise APIConnectionError(f"币安API网络请求失败: {e}")
                    
            except Exception as e:
                last_exception = e
                self._connection_health['total_failures'] += 1
                self._connection_health['consecutive_failures'] += 1
                
                logger.error(f"❌ 币安API请求异常: {e}")
                
                if attempt < max_retries - 1:
                    wait_time = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(f"⏰ 请求异常，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise TradingToolError(f"币安API请求异常: {e}")
        
        # 如果所有重试都失败
        if last_exception:
            raise APIConnectionError(f"币安API请求失败，已用尽所有重试: {last_exception}")
        else:
            raise APIConnectionError("币安API请求失败，原因未知")
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            # 转换符号格式 (BTC-USDT-SWAP -> BTCUSDT)
            binance_symbol = self._convert_symbol_to_binance(symbol)
            params = {'symbol': binance_symbol}
            result = await self._make_request('GET', '/fapi/v1/ticker/price', params=params)
            
            if result and 'price' in result:
                return float(result['price'])
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol}价格失败: {e}")
            return None
    
    async def get_raw_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取原始ticker数据（未转换格式）
        Get raw ticker data without format conversion
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            
        Returns:
            Optional[Dict[str, Any]]: 币安原始ticker数据
        """
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            params = {'symbol': binance_symbol}
            logger.debug(f"🔍 获取币安原始ticker数据: {symbol} -> {binance_symbol}")
            
            result = await self._make_request('GET', '/fapi/v1/ticker/24hr', params=params)
            
            if result:
                # 添加原始symbol信息用于适配器处理
                result['original_symbol'] = symbol
                logger.debug(f"✅ 获取币安原始ticker数据成功: {symbol}")
                return result
            else:
                logger.warning(f"⚠️ 币安API返回空ticker数据: {symbol}")
                return None
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol}原始ticker数据失败: {e}")
            return None
    
    async def get_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ticker数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            params = {'symbol': binance_symbol}
            result = await self._make_request('GET', '/fapi/v1/ticker/24hr', params=params)
            
            if result:
                return {
                    'symbol': symbol,
                    'price': float(result.get('lastPrice', '0')),
                    'volume_24h': float(result.get('volume', '0')),
                    'change_24h': float(result.get('priceChange', '0')),
                    'change_percent_24h': float(result.get('priceChangePercent', '0')),
                    'high_24h': float(result.get('highPrice', '0')),
                    'low_24h': float(result.get('lowPrice', '0')),
                    'bid_price': float(result.get('bidPrice', '0')),
                    'ask_price': float(result.get('askPrice', '0')),
                    'timestamp': datetime.now(),
                    'source': 'rest_api'
                }
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol} ticker数据失败: {e}")
            return None
    
    async def get_kline_data(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            
            # 币安时间周期映射
            tf_mapping = {
                '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
                '1h': '1h', '4h': '4h', '1d': '1d', '1w': '1w'
            }
            
            binance_tf = tf_mapping.get(timeframe.lower(), '1h')
            
            params = {
                'symbol': binance_symbol,
                'interval': binance_tf,
                'limit': min(limit, 1500)  # 币安限制
            }
            
            result = await self._make_request('GET', '/fapi/v1/klines', params=params)
            
            klines = []
            for item in result:
                klines.append({
                    'timestamp': int(item[0]),
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': float(item[5]),
                    'source': 'rest_api'
                })
            
            return sorted(klines, key=lambda x: x['timestamp'])
            
        except Exception as e:
            logger.error(f"获取{symbol} K线数据失败: {e}")
            return []
    
    async def get_raw_funding_rate(self, symbol: str = None) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        获取原始资金费率数据（未转换格式）
        Get raw funding rate data without format conversion
        
        Args:
            symbol: 交易对符号，None表示获取所有 / Trading pair symbol, None for all
            
        Returns:
            Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]: 币安原始资金费率数据
        """
        try:
            if symbol:
                # 获取单个交易对的资金费率
                binance_symbol = self._convert_symbol_to_binance(symbol)
                params = {'symbol': binance_symbol}
                logger.debug(f"🔍 获取币安原始资金费率数据: {symbol} -> {binance_symbol}")
                
                result = await self._make_request('GET', '/fapi/v1/premiumIndex', params=params)
                
                if result:
                    # 添加原始symbol信息用于适配器处理
                    result['original_symbol'] = symbol
                    logger.debug(f"✅ 获取币安原始资金费率数据成功: {symbol}")
                    return result
                else:
                    logger.warning(f"⚠️ 币安API返回空资金费率数据: {symbol}")
                    return None
            else:
                # 获取所有永续合约的资金费率
                logger.debug("🔍 获取币安所有原始资金费率数据")
                result = await self._make_request('GET', '/fapi/v1/premiumIndex')
                
                if result:
                    logger.debug(f"✅ 获取币安所有原始资金费率数据成功: {len(result)} 个")
                    return result
                else:
                    logger.warning("⚠️ 币安API返回空资金费率数据")
                    return []
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol if symbol else '所有'}原始资金费率数据失败: {e}")
            return None
    
    async def get_funding_rate_history(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取资金费率历史数据
        Get funding rate history data
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            limit: 历史记录数量限制 / Limit of historical records
            
        Returns:
            List[Dict[str, Any]]: 资金费率历史数据列表 / List of funding rate history data
        """
        try:
            # 转换交易对符号为币安格式
            binance_symbol = self._convert_symbol_to_binance(symbol)
            
            params = {
                'symbol': binance_symbol,
                'limit': min(limit, 1000)  # 币安API限制最多1000条记录
            }
            
            logger.debug(f"🔍 获取币安资金费率历史: {symbol} -> {binance_symbol}, limit: {limit}")
            
            # 调用币安API获取资金费率历史
            result = await self._make_request('GET', '/fapi/v1/fundingRate', params=params)
            
            if not result:
                logger.warning(f"⚠️ 币安API返回空费率历史数据: {symbol}")
                return []
            
            # 转换为统一格式
            history_data = []
            for rate in result:
                history_data.append({
                    'symbol': symbol,  # 使用标准格式
                    'funding_time': int(rate['fundingTime']),  # 时间戳（毫秒）
                    'funding_rate': float(rate['fundingRate']),
                    'mark_price': float(rate.get('markPrice', 0))
                })
            
            logger.info(f"✅ 获取币安费率历史成功: {symbol}, {len(history_data)} 条记录")
            return history_data
            
        except Exception as e:
            logger.error(f"获取币安费率历史失败 {symbol}: {e}")
            raise APIConnectionError(f"币安费率历史API错误: {e}")
    
    def calculate_funding_interval(self, funding_history: List[Dict[str, Any]]) -> int:
        """
        根据费率历史计算费率间隔（小时）
        Calculate funding interval based on funding history
        
        Args:
            funding_history: 费率历史数据 / Funding rate history data
            
        Returns:
            int: 费率间隔（小时）/ Funding interval in hours
        """
        if len(funding_history) < 2:
            logger.debug("费率历史数据不足，使用默认间隔8小时")
            return 8  # 默认8小时
        
        try:
            # 计算相邻两次费率时间的差值
            intervals = []
            for i in range(len(funding_history) - 1):
                time1 = funding_history[i]['funding_time']
                time2 = funding_history[i + 1]['funding_time']
                interval_ms = abs(time1 - time2)
                interval_hours = interval_ms / (1000 * 3600)  # 转换为小时
                intervals.append(interval_hours)
            
            if intervals:
                # 取最常见的间隔
                avg_interval = sum(intervals) / len(intervals)
                # 四舍五入到最近的整数小时
                calculated_interval = round(avg_interval)
                
                # 验证间隔是否合理（通常是4小时或8小时）
                if calculated_interval in [4, 6, 8, 12]:
                    logger.debug(f"计算得到费率间隔: {calculated_interval}小时")
                    return calculated_interval
                else:
                    logger.warning(f"计算得到异常费率间隔: {calculated_interval}小时，使用默认8小时")
                    return 8
            else:
                logger.debug("无法计算费率间隔，使用默认8小时")
                return 8
                
        except Exception as e:
            logger.warning(f"计算费率间隔失败: {e}，使用默认8小时")
            return 8
    
    async def get_funding_rate(self, symbol: str = None) -> Optional[Dict[str, Any]]:
        """获取资金费率"""
        try:
            if symbol:
                # 获取单个交易对的资金费率
                binance_symbol = self._convert_symbol_to_binance(symbol)
                params = {'symbol': binance_symbol}
                result = await self._make_request('GET', '/fapi/v1/premiumIndex', params=params)
                
                if result:
                    next_funding_time = int(result.get('nextFundingTime', '0'))
                    
                    return {
                        'symbol': symbol,
                        'funding_rate': float(result.get('lastFundingRate', '0')),
                        'next_funding_time': datetime.fromtimestamp(next_funding_time / 1000) if next_funding_time else datetime.now(),
                        'timestamp': datetime.now(),
                        'source': 'rest_api'
                    }
            else:
                # 获取所有永续合约的资金费率
                result = await self._make_request('GET', '/fapi/v1/premiumIndex')
                
                funding_rates = []
                for item in result:
                    binance_symbol = item.get('symbol', '')
                    # 转换回标准格式
                    standard_symbol = self._convert_symbol_from_binance(binance_symbol)
                    next_funding_time = int(item.get('nextFundingTime', '0'))
                    
                    funding_rates.append({
                        'symbol': standard_symbol,
                        'funding_rate': float(item.get('lastFundingRate', '0')),
                        'next_funding_time': datetime.fromtimestamp(next_funding_time / 1000) if next_funding_time else datetime.now(),
                        'timestamp': datetime.now(),
                        'source': 'rest_api'
                    })
                
                return funding_rates
            
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol if symbol else '所有'}资金费率失败: {e}")
            return None
    
    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓量数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            params = {'symbol': binance_symbol}
            result = await self._make_request('GET', '/fapi/v1/openInterest', params=params)
            
            if result:
                return {
                    'symbol': symbol,
                    'open_interest': float(result.get('openInterest', '0')),
                    'open_interest_value': float(result.get('openInterestValue', '0')),
                    'change_24h': 0.0,  # 币安API不直接提供24h变化，需要额外计算
                    'timestamp': datetime.now(),
                    'source': 'rest_api'
                }
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol}持仓量失败: {e}")
            return None
    
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近交易数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            params = {
                'symbol': binance_symbol,
                'limit': min(limit, 1000)  # 币安限制
            }
            
            result = await self._make_request('GET', '/fapi/v1/aggTrades', params=params)
            
            trades = []
            for trade in result:
                trades.append({
                    'symbol': symbol,
                    'side': 'buy' if trade.get('m', False) else 'sell',  # m表示是否为买方成交
                    'size': float(trade.get('q', '0')),
                    'price': float(trade.get('p', '0')),
                    'trade_id': str(trade.get('a', '')),
                    'timestamp': datetime.fromtimestamp(int(trade.get('T', '0')) / 1000),
                    'source': 'rest_api'
                })
            
            return trades
            
        except Exception as e:
            logger.error(f"获取{symbol}最近交易数据失败: {e}")
            return []
    
    async def get_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据"""
        try:
            result = await self._make_request('GET', '/fapi/v1/ticker/24hr')
            
            tickers = []
            for ticker in result:
                binance_symbol = ticker.get('symbol', '')
                standard_symbol = self._convert_symbol_from_binance(binance_symbol)
                
                tickers.append({
                    'symbol': standard_symbol,
                    'price': float(ticker.get('lastPrice', '0')),
                    'volume_24h': float(ticker.get('volume', '0')),
                    'change_24h': float(ticker.get('priceChange', '0')),
                    'change_percent_24h': float(ticker.get('priceChangePercent', '0')),
                    'high_24h': float(ticker.get('highPrice', '0')),
                    'low_24h': float(ticker.get('lowPrice', '0')),
                    'bid_price': float(ticker.get('bidPrice', '0')),
                    'ask_price': float(ticker.get('askPrice', '0')),
                    'timestamp': datetime.now(),
                    'source': 'rest_api'
                })
            
            return tickers
            
        except Exception as e:
            logger.error(f"获取ticker数据失败: {e}")
            return []
    
    async def get_raw_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """
        获取原始交易对数据（未转换格式）
        Get raw instruments data without format conversion
        
        Args:
            inst_type: 交易对类型 / Instrument type
            
        Returns:
            List[Dict[str, Any]]: 币安原始交易对数据列表
        """
        try:
            logger.info(f"🔍 获取币安原始交易对数据: {inst_type}")
            result = await self._make_request('GET', '/fapi/v1/exchangeInfo')
            
            if result and 'symbols' in result:
                raw_instruments = result['symbols']
                logger.info(f"✅ 获取币安原始交易对数据成功: {len(raw_instruments)} 个")
                return raw_instruments
            else:
                logger.warning("⚠️ 币安API返回数据格式异常")
                return []
            
        except Exception as e:
            logger.error(f"❌ 获取{inst_type}原始交易对数据失败: {e}")
            return []
    
    async def get_all_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有交易对列表"""
        try:
            result = await self._make_request('GET', '/fapi/v1/exchangeInfo')
            
            instruments = []
            if result and 'symbols' in result:
                for item in result['symbols']:
                    if item.get('status') == 'TRADING':  # 只返回活跃交易对
                        binance_symbol = item.get('symbol', '')
                        standard_symbol = self._convert_symbol_from_binance(binance_symbol)
                        
                        instruments.append({
                            'symbol': standard_symbol,
                            'base_currency': item.get('baseAsset', ''),
                            'quote_currency': item.get('quoteAsset', ''),
                            'contract_type': 'PERPETUAL' if item.get('contractType') == 'PERPETUAL' else item.get('contractType', ''),
                            'status': 'active' if item.get('status') == 'TRADING' else 'inactive',
                            'min_size': float(item.get('filters', [{}])[0].get('minQty', '0')),
                            'tick_size': float(item.get('filters', [{}])[0].get('tickSize', '0')),
                            'source': 'binance'
                        })
            
            return instruments
            
        except Exception as e:
            logger.error(f"获取{inst_type}交易对列表失败: {e}")
            return []
    
    async def get_account_balance(self) -> Dict[str, Any]:
        """获取账户余额"""
        try:
            result = await self._make_request('GET', '/fapi/v2/account', signed=True)
            
            if not result:
                return {}
            
            balances = {}
            total_equity = 0
            
            for asset in result.get('assets', []):
                currency = asset.get('asset', '')
                equity = float(asset.get('walletBalance', '0'))
                available = float(asset.get('availableBalance', '0'))
                
                if equity > 0:
                    balances[currency] = {
                        'equity': equity,
                        'available': available,
                        'frozen': equity - available
                    }
                    
                    if currency == 'USDT':
                        total_equity += equity
            
            return {
                'total_equity': total_equity,
                'balances': balances,
                'update_time': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            raise TradingToolError(f"获取账户余额失败: {e}")
    
    async def get_raw_positions(self) -> List[Dict[str, Any]]:
        """
        获取原始持仓数据（未转换格式）
        Get raw positions data without format conversion
        
        Returns:
            List[Dict[str, Any]]: 币安原始持仓数据列表
        """
        try:
            logger.debug("🔍 获取币安原始持仓数据")
            result = await self._make_request('GET', '/fapi/v2/positionRisk', signed=True)
            
            if result:
                logger.debug(f"✅ 获取币安原始持仓数据成功: {len(result)} 个")
                return result
            else:
                logger.warning("⚠️ 币安API返回空持仓数据")
                return []
            
        except Exception as e:
            logger.error(f"❌ 获取原始持仓数据失败: {e}")
            raise TradingToolError(f"获取原始持仓数据失败: {e}")
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓信息"""
        try:
            result = await self._make_request('GET', '/fapi/v2/positionRisk', signed=True)
            
            positions = []
            for pos in result:
                pos_size = float(pos.get('positionAmt', '0'))
                if pos_size != 0:  # 只返回有持仓的
                    binance_symbol = pos.get('symbol', '')
                    standard_symbol = self._convert_symbol_from_binance(binance_symbol)
                    
                    positions.append({
                        'symbol': standard_symbol,
                        'side': 'long' if pos_size > 0 else 'short',
                        'size': abs(pos_size),
                        'avg_price': float(pos.get('entryPrice', '0')),
                        'mark_price': float(pos.get('markPrice', '0')),
                        'unrealized_pnl': float(pos.get('unRealizedProfit', '0')),
                        'leverage': float(pos.get('leverage', '1')),
                        'margin': float(pos.get('isolatedMargin', '0')),
                        'update_time': datetime.now()
                    })
            
            return positions
            
        except Exception as e:
            logger.error(f"获取持仓信息失败: {e}")
            raise TradingToolError(f"获取持仓信息失败: {e}")
    
    async def get_spot_balances(self) -> List[Dict[str, Any]]:
        """获取现货余额（币安期货账户不适用，返回空列表）"""
        logger.warning("币安期货账户不支持现货余额查询")
        return []
    
    def _convert_symbol_to_binance(self, symbol: str) -> str:
        """将标准符号转换为币安格式"""
        # BTC-USDT-SWAP -> BTCUSDT
        if '-USDT-SWAP' in symbol:
            return symbol.replace('-USDT-SWAP', 'USDT')
        elif '-USDT' in symbol:
            return symbol.replace('-USDT', 'USDT')
        return symbol
    
    def _convert_symbol_from_binance(self, binance_symbol: str) -> str:
        """将币安符号转换为标准格式"""
        # BTCUSDT -> BTC-USDT-SWAP
        if binance_symbol.endswith('USDT'):
            base = binance_symbol[:-4]  # 移除USDT
            return f"{base}-USDT-SWAP"
        return binance_symbol
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态信息"""
        return {
            'api_key_validated': self._api_key_validated,
            'connection_health': self._connection_health.copy(),
            'rate_limiter_status': self._rate_limiter.get_status() if self._rate_limiter else None,
            'current_interval': self._current_interval,
            'base_url': self.base_url,
            'testnet': self.testnet,
            'http_manager_active': self.http_manager is not None
        }
    
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接状态"""
        try:
            # 测试基础连接
            ping_result = await self._make_request('GET', '/fapi/v1/ping')
            
            # 测试服务器时间
            time_result = await self._make_request('GET', '/fapi/v1/time')
            
            # 如果API密钥已配置，测试账户信息
            account_test = None
            if self.api_key and self.secret_key:
                try:
                    account_test = await self._make_request('GET', '/fapi/v2/account', signed=True)
                    account_test = "success" if account_test else "failed"
                except Exception as e:
                    account_test = f"failed: {str(e)}"
            
            return {
                'status': 'success',
                'ping': 'success' if ping_result is not None else 'failed',
                'server_time': 'success' if time_result else 'failed',
                'account_access': account_test,
                'connection_health': self._connection_health.copy(),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ 币安连接测试失败: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'connection_health': self._connection_health.copy(),
                'timestamp': datetime.now().isoformat()
            }