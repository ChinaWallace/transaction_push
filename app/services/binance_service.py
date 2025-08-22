# -*- coding: utf-8 -*-
"""
币安API服务
Binance API service for fetching market data
"""

import asyncio
import aiohttp
import time
import hmac
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
from decimal import Decimal

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.models.market_data import KlineData, FundingRate, OpenInterest, VolumeData
from app.utils.http_client import HTTPClient
from app.utils.exceptions import BinanceAPIError, RateLimitError

logger = get_logger(__name__)
settings = get_settings()


class BinanceService:
    """币安API服务类"""
    
    def __init__(self):
        self.api_key = settings.binance_api_key
        self.secret_key = settings.binance_secret_key
        self.base_url = settings.binance_base_url
        self.testnet = settings.binance_testnet
        self.http_client = HTTPClient()
        
        if self.testnet:
            self.base_url = "https://testnet.binancefuture.com"
            logger.warning("Using Binance testnet")
    
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
        """发起API请求"""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        if params is None:
            params = {}
        
        if signed:
            timestamp = int(time.time() * 1000)
            params['timestamp'] = timestamp
            params['signature'] = self._generate_signature(params)
        
        try:
            response = await self.http_client.get(url, params=params, headers=headers)
            return response
        except Exception as e:
            logger.error(f"Binance API request failed: {e}")
            raise BinanceAPIError(f"API request failed: {e}")
    
    async def get_exchange_info(self) -> dict:
        """获取交易所信息"""
        try:
            data = await self._make_request("/fapi/v1/exchangeInfo")
            trading_logger.info("Retrieved exchange info successfully")
            return data
        except Exception as e:
            logger.error(f"Failed to get exchange info: {e}")
            raise
    
    async def get_active_symbols(self) -> List[str]:
        """获取活跃的交易对列表"""
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
    
    async def get_funding_rate(self, symbol: Optional[str] = None, limit: int = 100) -> List[dict]:
        """获取资金费率数据"""
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
        """获取24小时价格变动统计"""
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
