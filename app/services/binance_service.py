# -*- coding: utf-8 -*-
"""
币安API服务
Binance API service for fetching market data
"""

import asyncio
import time
import hmac
import hashlib
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import pandas as pd
from decimal import Decimal

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.utils.http_manager import get_http_manager
from app.utils.exceptions import BinanceAPIError, RateLimitError

logger = get_logger(__name__)
settings = get_settings()


class BinanceService:
    """
    币安API服务类
    Binance API service class
    
    数据适配说明 / Data Adaptation Notes:
    =====================================
    
    此服务类现在提供两套方法：
    This service class now provides two sets of methods:
    
    1. 传统方法（向后兼容）/ Legacy Methods (Backward Compatible):
       - get_exchange_info(): 获取交易所信息
       - get_active_symbols(): 获取活跃交易对列表
       - get_24hr_ticker(): 获取24小时ticker数据
       - get_funding_rate(): 获取资金费率数据
       - 这些方法保持原有的数据格式和行为，确保现有代码正常工作
       
    2. 原始数据方法（用于适配器）/ Raw Data Methods (For Adapters):
       - get_raw_instruments(): 获取原始交易对数据
       - get_raw_ticker(): 获取原始ticker数据
       - get_raw_funding_rate(): 获取原始资金费率数据
       - 这些方法返回未转换的币安原生数据格式，供数据适配器使用
    
    迁移策略 / Migration Strategy:
    =============================
    
    现有业务服务应逐步迁移到使用混合服务（HybridService），
    混合服务内部使用原始数据方法和适配器来提供统一格式的数据。
    
    Existing business services should gradually migrate to use HybridService,
    which internally uses raw data methods and adapters to provide unified format data.
    """
    
    def __init__(self):
        self.api_key = settings.binance_api_key
        self.secret_key = settings.binance_secret_key
        self.base_url = settings.binance_base_url
        self.testnet = settings.binance_testnet
        self.http_manager = None  # 延迟初始化
        
        if self.testnet:
            self.base_url = "https://testnet.binancefuture.com"
            logger.warning("Using Binance testnet")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_http_manager()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"币安服务异常: {exc_type.__name__}: {exc_val}")
        # HTTP管理器由全局管理，这里不需要关闭
    
    async def _ensure_http_manager(self):
        """确保HTTP管理器可用"""
        if not self.http_manager:
            self.http_manager = await get_http_manager()
            logger.debug("✅ 币安服务已连接到统一HTTP连接池")
    
    def _generate_signature(self, params: dict) -> str:
        """生成API签名"""
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        }
    
    async def _make_request(self, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """发起API请求 - 使用统一HTTP连接池"""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        if params is None:
            params = {}
        
        if signed:
            timestamp = int(time.time() * 1000)
            params['timestamp'] = timestamp
            params['signature'] = self._generate_signature(params)
        
        try:
            # 使用统一的HTTP管理器
            if not self.http_manager:
                self.http_manager = await get_http_manager()
            
            async with self.http_manager.get_session() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 429:  # 限流处理
                        logger.warning(f"Binance API rate limit hit for {endpoint}")
                        await asyncio.sleep(2)
                        raise RateLimitError("API rate limit exceeded")
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"Binance API error {response.status}: {error_text}")
                        raise BinanceAPIError(f"API error {response.status}: {error_text}")
                    
                    return await response.json()
                    
        except (RateLimitError, BinanceAPIError):
            raise
        except Exception as e:
            logger.error(f"Binance API request failed: {e}")
            raise BinanceAPIError(f"API request failed: {e}")
    
    async def get_exchange_info(self) -> dict:
        """
        获取交易所信息
        Get exchange information
        
        Note: 此方法保持向后兼容性。如需原始数据，请使用 get_raw_instruments()
        This method maintains backward compatibility. Use get_raw_instruments() for raw data.
        
        Returns:
            dict: 交易所信息 / Exchange information
        """
        try:
            data = await self._make_request("/fapi/v1/exchangeInfo")
            trading_logger.info("Retrieved exchange info successfully")
            return data
        except Exception as e:
            logger.error(f"Failed to get exchange info: {e}")
            raise
    
    async def get_active_symbols(self) -> List[str]:
        """
        获取活跃的交易对列表
        Get active trading symbols list
        
        Note: 此方法保持向后兼容性，返回币安原生格式符号（如BTCUSDT）
        This method maintains backward compatibility, returns Binance native format symbols (e.g., BTCUSDT)
        
        Returns:
            List[str]: 活跃交易对符号列表 / List of active trading symbols
        """
        try:
            exchange_info = await self.get_exchange_info()
            symbols = []
            
            for symbol_info in exchange_info.get('symbols', []):
                if (symbol_info.get('status') == 'TRADING' and 
                    symbol_info.get('contractType') == 'PERPETUAL' and
                    symbol_info.get('symbol', '').endswith('USDT') and
                    'USDC' not in symbol_info.get('symbol', '')):
                    symbols.append(symbol_info['symbol'])
            
            logger.info(f"Found {len(symbols)} active USDT perpetual symbols")
            return symbols
        except Exception as e:
            logger.error(f"Failed to get active symbols: {e}")
            raise
    
    async def get_kline_data(self, symbol: str, interval: str, limit: int = 500, 
                           start_time: Optional[datetime] = None, 
                           end_time: Optional[datetime] = None) -> List[dict]:
        """获取K线数据"""
        # 币安API limit参数限制：1-1500
        if limit < 1 or limit > 1500:
            raise ValueError(f"Limit must be between 1 and 1500, got {limit}")
            
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        if start_time:
            params['startTime'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['endTime'] = int(end_time.timestamp() * 1000)
        
        try:
            data = await self._make_request("/fapi/v1/klines", params)
            
            # 转换数据格式
            klines = []
            for kline in data:
                klines.append({
                    'symbol': symbol,
                    'interval': interval,
                    'open_time': datetime.fromtimestamp(kline[0] / 1000),
                    'close_time': datetime.fromtimestamp(kline[6] / 1000),
                    'open_price': Decimal(str(kline[1])),
                    'high_price': Decimal(str(kline[2])),
                    'low_price': Decimal(str(kline[3])),
                    'close_price': Decimal(str(kline[4])),
                    'volume': Decimal(str(kline[5])),
                    'quote_volume': Decimal(str(kline[7])),
                    'trade_count': int(kline[8]),
                    'taker_buy_volume': Decimal(str(kline[9])),
                    'taker_buy_quote_volume': Decimal(str(kline[10]))
                })
            
            trading_logger.info(f"Retrieved {len(klines)} klines for {symbol} {interval}")
            return klines
            
        except Exception as e:
            logger.error(f"Failed to get kline data for {symbol}: {e}")
            raise
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> Optional[pd.DataFrame]:
        """
        获取K线数据并返回DataFrame格式（用于Kronos预测服务）
        """
        try:
            # 调用现有的get_kline_data方法
            klines_data = await self.get_kline_data(symbol, interval, limit)
            
            if not klines_data:
                return None
            
            # 转换为DataFrame格式，符合Kronos预测服务的期望
            df_data = []
            for kline in klines_data:
                df_data.append({
                    'open': float(kline['open_price']),
                    'high': float(kline['high_price']),
                    'low': float(kline['low_price']),
                    'close': float(kline['close_price']),
                    'volume': float(kline['volume'])
                })
            
            df = pd.DataFrame(df_data)
            
            # 设置时间索引
            timestamps = [kline['open_time'] for kline in klines_data]
            df.index = pd.DatetimeIndex(timestamps)
            
            logger.debug(f"转换K线数据为DataFrame: {symbol} {interval}, 形状: {df.shape}")
            return df
            
        except Exception as e:
            logger.error(f"获取K线DataFrame失败 {symbol}: {e}")
            return None
    
    async def get_funding_rate(self, symbol: Optional[str] = None, limit: int = 100) -> List[dict]:
        """
        获取资金费率数据
        Get funding rate data
        
        Note: 此方法保持向后兼容性，返回转换后的数据格式
        This method maintains backward compatibility, returns converted data format
        如需原始数据用于适配器处理，请使用 get_raw_funding_rate()
        Use get_raw_funding_rate() for raw data for adapter processing
        
        Args:
            symbol: 币安格式交易对符号（如BTCUSDT） / Binance format symbol (e.g., BTCUSDT)
            limit: 返回数据条数限制 / Limit of returned data
            
        Returns:
            List[dict]: 转换后的资金费率数据列表 / List of converted funding rate data
        """
        params = {'limit': limit}
        if symbol:
            params['symbol'] = symbol
        
        try:
            data = await self._make_request("/fapi/v1/fundingRate", params)
            
            # 转换数据格式
            funding_rates = []
            for rate in data:
                funding_rates.append({
                    'symbol': rate['symbol'],
                    'funding_time': datetime.fromtimestamp(rate['fundingTime'] / 1000),
                    'funding_rate': Decimal(str(rate['fundingRate'])),
                    'mark_price': Decimal(str(rate.get('markPrice', 0)))
                })
            
            trading_logger.info(f"Retrieved {len(funding_rates)} funding rates")
            return funding_rates
            
        except Exception as e:
            logger.error(f"Failed to get funding rate: {e}")
            raise
    
    async def get_open_interest_statistics(self, symbol: str, period: str = "5m", 
                                         limit: int = 30) -> List[dict]:
        """获取持仓量统计数据"""
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }
        
        try:
            data = await self._make_request("/futures/data/openInterestHist", params)
            
            # 转换数据格式
            open_interests = []
            for oi in data:
                open_interests.append({
                    'symbol': symbol,
                    'timestamp': datetime.fromtimestamp(oi['timestamp'] / 1000),
                    'open_interest': Decimal(str(oi['sumOpenInterest'])),
                    'open_interest_value': Decimal(str(oi['sumOpenInterestValue']))
                })
            
            trading_logger.info(f"Retrieved {len(open_interests)} open interest records for {symbol}")
            return open_interests
            
        except Exception as e:
            logger.error(f"Failed to get open interest for {symbol}: {e}")
            raise
    
    async def get_24hr_ticker(self, symbol: Optional[str] = None) -> List[dict]:
        """
        获取24小时价格变动统计
        Get 24hr ticker price change statistics
        
        Note: 此方法保持向后兼容性，返回币安原生数据格式
        This method maintains backward compatibility, returns Binance native data format
        如需原始数据用于适配器处理，请使用 get_raw_ticker()
        Use get_raw_ticker() for raw data for adapter processing
        
        Args:
            symbol: 币安格式交易对符号（如BTCUSDT） / Binance format symbol (e.g., BTCUSDT)
            
        Returns:
            List[dict]: 24小时ticker数据列表 / List of 24hr ticker data
        """
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        try:
            data = await self._make_request("/fapi/v1/ticker/24hr", params)
            if not isinstance(data, list):
                data = [data]
            
            trading_logger.info(f"Retrieved 24hr ticker data for {len(data)} symbols")
            return data
            
        except Exception as e:
            logger.error(f"Failed to get 24hr ticker: {e}")
            raise
    
    async def get_top_long_short_account_ratio(self, symbol: str, period: str = "5m", 
                                             limit: int = 30) -> List[dict]:
        """获取大户账户数多空比"""
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }
        
        try:
            data = await self._make_request("/futures/data/topLongShortAccountRatio", params)
            trading_logger.info(f"Retrieved long/short ratio for {symbol}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to get long/short ratio for {symbol}: {e}")
            raise
    
    async def get_multi_timeframe_klines(self, symbol: str, 
                                       intervals: List[str] = None,
                                       limit: int = 100) -> Dict[str, List[dict]]:
        """获取多时间周期K线数据"""
        if intervals is None:
            intervals = ['1d', '4h', '1h', '15m']
        
        try:
            tasks = []
            for interval in intervals:
                task = self.get_kline_data(symbol, interval, limit)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            
            timeframe_data = {}
            for i, interval in enumerate(intervals):
                timeframe_data[interval] = results[i]
            
            trading_logger.info(f"Retrieved multi-timeframe data for {symbol}")
            return timeframe_data
            
        except Exception as e:
            logger.error(f"Failed to get multi-timeframe data for {symbol}: {e}")
            raise
    
    async def batch_get_funding_rates(self, symbols: List[str]) -> Dict[str, List[dict]]:
        """批量获取资金费率"""
        try:
            # 获取所有资金费率数据
            all_rates = await self.get_funding_rate()
            
            # 按symbol分组
            rates_by_symbol = {}
            for rate in all_rates:
                symbol = rate['symbol']
                if symbol in symbols:
                    if symbol not in rates_by_symbol:
                        rates_by_symbol[symbol] = []
                    rates_by_symbol[symbol].append(rate)
            
            trading_logger.info(f"Retrieved funding rates for {len(rates_by_symbol)} symbols")
            return rates_by_symbol
            
        except Exception as e:
            logger.error(f"Failed to batch get funding rates: {e}")
            raise
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            await self._make_request("/fapi/v1/ping")
            return True
        except Exception as e:
            logger.error(f"Binance API health check failed: {e}")
            return False
    
    async def get_server_time(self) -> datetime:
        """获取服务器时间"""
        try:
            data = await self._make_request("/fapi/v1/time")
            return datetime.fromtimestamp(data['serverTime'] / 1000)
        except Exception as e:
            logger.error(f"Failed to get server time: {e}")
            raise
    
    async def get_raw_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """
        获取原始交易对数据（未转换格式）
        Get raw instruments data without format conversion
        
        Args:
            inst_type: 交易对类型 / Instrument type (SWAP for perpetual futures)
            
        Returns:
            List[Dict[str, Any]]: 币安原始交易对数据列表
        """
        try:
            logger.debug(f"🔍 获取币安原始交易对数据: {inst_type}")
            data = await self._make_request("/fapi/v1/exchangeInfo")
            
            if data and 'symbols' in data:
                # 返回原始数据，不进行格式转换
                raw_instruments = data['symbols']
                logger.info(f"✅ 获取币安原始交易对数据成功: {len(raw_instruments)} 个")
                return raw_instruments
            else:
                logger.warning("⚠️ 币安API返回空交易对数据")
                return []
                
        except Exception as e:
            logger.error(f"❌ 获取{inst_type}原始交易对数据失败: {e}")
            return []
    
    async def get_raw_ticker(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """
        获取原始ticker数据（未转换格式）
        Get raw ticker data without format conversion
        
        Args:
            symbol: 交易对符号，None表示获取所有 / Trading pair symbol, None for all
            
        Returns:
            Union[Dict[str, Any], List[Dict[str, Any]], None]: 币安原始ticker数据
        """
        try:
            params = {}
            if symbol:
                # 转换符号格式 (BTC-USDT-SWAP -> BTCUSDT)
                binance_symbol = symbol.replace('-USDT-SWAP', 'USDT').replace('-USDT', 'USDT')
                params['symbol'] = binance_symbol
                logger.debug(f"🔍 获取币安原始ticker数据: {symbol} -> {binance_symbol}")
            else:
                logger.debug("🔍 获取币安所有原始ticker数据")
            
            data = await self._make_request("/fapi/v1/ticker/24hr", params)
            
            if data:
                if symbol:
                    # 单个ticker数据，添加原始symbol信息用于适配器处理
                    data['original_symbol'] = symbol
                    logger.debug(f"✅ 获取币安原始ticker数据成功: {symbol}")
                else:
                    # 所有ticker数据
                    logger.info(f"✅ 获取币安所有原始ticker数据成功: {len(data)} 个")
                return data
            else:
                logger.warning(f"⚠️ 币安API返回空ticker数据: {symbol if symbol else '所有'}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 获取{symbol if symbol else '所有'}原始ticker数据失败: {e}")
            return None
    
    async def get_raw_funding_rate(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """
        获取原始资金费率数据（未转换格式）
        Get raw funding rate data without format conversion
        
        Args:
            symbol: 交易对符号，None表示获取所有 / Trading pair symbol, None for all
            
        Returns:
            Union[Dict[str, Any], List[Dict[str, Any]], None]: 币安原始资金费率数据
        """
        try:
            params = {}
            if symbol:
                # 转换符号格式 (BTC-USDT-SWAP -> BTCUSDT)
                binance_symbol = symbol.replace('-USDT-SWAP', 'USDT').replace('-USDT', 'USDT')
                params['symbol'] = binance_symbol
                logger.debug(f"🔍 获取币安原始资金费率数据: {symbol} -> {binance_symbol}")
            else:
                logger.debug("🔍 获取币安所有原始资金费率数据")
            
            data = await self._make_request("/fapi/v1/premiumIndex", params)
            
            if data:
                if symbol:
                    # 单个资金费率数据，添加原始symbol信息用于适配器处理
                    data['original_symbol'] = symbol
                    logger.debug(f"✅ 获取币安原始资金费率数据成功: {symbol}")
                else:
                    # 所有资金费率数据
                    logger.info(f"✅ 获取币安所有原始资金费率数据成功: {len(data)} 个")
                return data
            else:
                logger.warning(f"⚠️ 币安API返回空资金费率数据: {symbol if symbol else '所有'}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 获取{symbol if symbol else '所有'}原始资金费率数据失败: {e}")
            return None
