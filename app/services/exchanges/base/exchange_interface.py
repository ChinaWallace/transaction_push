# -*- coding: utf-8 -*-
"""
交易所抽象接口
Exchange Abstract Interface - 定义所有交易所必须实现的统一接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union

from app.core.logging import get_logger

logger = get_logger(__name__)


class ExchangeInterface(ABC):
    """
    交易所统一抽象接口
    Exchange Unified Abstract Interface
    
    定义所有交易所服务必须实现的标准方法，确保不同交易所之间的接口一致性
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        初始化交易所服务
        Initialize exchange service
        
        执行必要的初始化操作，如连接设置、认证验证等
        """
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        清理资源
        Cleanup resources
        
        释放连接、关闭WebSocket、清理缓存等
        """
    
    # ==================== 市场数据接口 Market Data Interface ====================
    
    @abstractmethod
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格
        Get current price for a trading symbol
        
        Args:
            symbol: 交易对符号 / Trading pair symbol (e.g., "BTC-USDT-SWAP")
            
        Returns:
            Optional[float]: 当前价格，获取失败时返回None / Current price or None if failed
        """
    
    @abstractmethod
    async def get_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取ticker数据
        Get ticker data for a trading symbol
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            
        Returns:
            Optional[Dict[str, Any]]: ticker数据字典，包含价格、成交量等信息
            Expected format:
            {
                'symbol': str,
                'price': float,
                'volume_24h': float,
                'change_24h': float,
                'change_percent_24h': float,
                'high_24h': float,
                'low_24h': float,
                'bid_price': float,
                'ask_price': float,
                'timestamp': datetime,
                'source': str  # 'websocket' or 'rest_api'
            }
        """
    
    @abstractmethod
    async def get_kline_data(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取K线数据
        Get kline/candlestick data
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            timeframe: 时间周期 / Timeframe ('1m', '5m', '15m', '1H', '4H', '1D', etc.)
            limit: 数据条数 / Number of data points
            
        Returns:
            List[Dict[str, Any]]: K线数据列表
            Expected format:
            [
                {
                    'timestamp': int,
                    'open': float,
                    'high': float,
                    'low': float,
                    'close': float,
                    'volume': float,
                    'source': str
                }
            ]
        """
    
    @abstractmethod
    async def get_funding_rate(self, symbol: str = None) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        获取资金费率
        Get funding rate data
        
        Args:
            symbol: 交易对符号，None时获取所有交易对 / Trading pair symbol, None for all symbols
            
        Returns:
            Union[Dict, List[Dict]]: 单个或多个资金费率数据
            Expected format for single symbol:
            {
                'symbol': str,
                'funding_rate': float,
                'next_funding_time': datetime,
                'timestamp': datetime,
                'source': str
            }
        """
    
    @abstractmethod
    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取持仓量数据
        Get open interest data
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            
        Returns:
            Optional[Dict[str, Any]]: 持仓量数据
            Expected format:
            {
                'symbol': str,
                'open_interest': float,
                'open_interest_value': float,
                'change_24h': float,
                'timestamp': datetime,
                'source': str
            }
        """
    
    @abstractmethod
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取最近交易数据
        Get recent trades data
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            limit: 交易记录数量 / Number of trade records
            
        Returns:
            List[Dict[str, Any]]: 交易数据列表
            Expected format:
            [
                {
                    'symbol': str,
                    'side': str,  # 'buy' or 'sell'
                    'size': float,
                    'price': float,
                    'trade_id': str,
                    'timestamp': datetime,
                    'source': str
                }
            ]
        """
    
    @abstractmethod
    async def get_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """
        获取所有ticker数据
        Get all tickers data
        
        Args:
            inst_type: 合约类型 / Instrument type ('SWAP', 'SPOT', etc.)
            
        Returns:
            List[Dict[str, Any]]: 所有ticker数据列表
        """
    
    @abstractmethod
    async def get_all_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """
        获取所有交易对列表
        Get all trading instruments
        
        Args:
            inst_type: 合约类型 / Instrument type
            
        Returns:
            List[Dict[str, Any]]: 交易对信息列表
            Expected format:
            [
                {
                    'symbol': str,
                    'base_currency': str,
                    'quote_currency': str,
                    'contract_type': str,
                    'status': str,  # 'active', 'inactive', etc.
                    'min_size': float,
                    'tick_size': float
                }
            ]
        """
    
    # ==================== 账户数据接口 Account Data Interface ====================
    
    @abstractmethod
    async def get_account_balance(self) -> Dict[str, Any]:
        """
        获取账户余额
        Get account balance
        
        Returns:
            Dict[str, Any]: 账户余额信息
            Expected format:
            {
                'total_equity': float,
                'balances': {
                    'USDT': {
                        'equity': float,
                        'available': float,
                        'frozen': float
                    }
                },
                'update_time': datetime
            }
        """
    
    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        获取持仓信息
        Get positions information
        
        Returns:
            List[Dict[str, Any]]: 持仓信息列表
            Expected format:
            [
                {
                    'symbol': str,
                    'side': str,  # 'long', 'short'
                    'size': float,
                    'avg_price': float,
                    'mark_price': float,
                    'unrealized_pnl': float,
                    'leverage': float,
                    'margin': float,
                    'update_time': datetime
                }
            ]
        """
    
    @abstractmethod
    async def get_spot_balances(self) -> List[Dict[str, Any]]:
        """
        获取现货余额
        Get spot balances
        
        Returns:
            List[Dict[str, Any]]: 现货余额列表
            Expected format:
            [
                {
                    'currency': str,
                    'equity': float,
                    'available': float,
                    'frozen': float,
                    'update_time': datetime
                }
            ]
        """
    
    # ==================== 交易接口 Trading Interface ====================
    
    @abstractmethod
    async def place_order(self, symbol: str, side: str, size: float, 
                         order_type: str = 'market', price: float = None,
                         leverage: float = None) -> Dict[str, Any]:
        """
        下单
        Place order
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            side: 交易方向 / Order side ('buy', 'sell')
            size: 交易数量 / Order size
            order_type: 订单类型 / Order type ('market', 'limit')
            price: 价格（限价单必需） / Price (required for limit orders)
            leverage: 杠杆倍数 / Leverage multiplier
            
        Returns:
            Dict[str, Any]: 订单结果
            Expected format:
            {
                'order_id': str,
                'symbol': str,
                'side': str,
                'size': float,
                'price': float,
                'status': str,  # 'filled', 'partial', 'pending', 'cancelled'
                'timestamp': datetime
            }
        """
    
    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        取消订单
        Cancel order
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            order_id: 订单ID / Order ID
            
        Returns:
            Dict[str, Any]: 取消结果
        """
    
    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        获取订单状态
        Get order status
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            order_id: 订单ID / Order ID
            
        Returns:
            Dict[str, Any]: 订单状态信息
        """
    
    # ==================== 实时数据订阅接口 Real-time Data Subscription Interface ====================
    
    @abstractmethod
    async def subscribe_symbol_realtime(self, symbol: str) -> bool:
        """
        订阅单个交易对的实时数据
        Subscribe to real-time data for a single symbol
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            
        Returns:
            bool: 订阅是否成功 / Whether subscription was successful
        """
    
    @abstractmethod
    async def subscribe_symbols_realtime(self, symbols: List[str]) -> Dict[str, bool]:
        """
        批量订阅多个交易对的实时数据
        Batch subscribe to real-time data for multiple symbols
        
        Args:
            symbols: 交易对符号列表 / List of trading pair symbols
            
        Returns:
            Dict[str, bool]: 每个交易对的订阅结果 / Subscription results for each symbol
        """
    
    # ==================== 服务状态接口 Service Status Interface ====================
    
    @abstractmethod
    def get_service_status(self) -> Dict[str, Any]:
        """
        获取服务状态
        Get service status
        
        Returns:
            Dict[str, Any]: 服务状态信息
            Expected format:
            {
                'is_initialized': bool,
                'websocket_enabled': bool,
                'rest_api_available': bool,
                'subscribed_symbols_count': int,
                'last_update': datetime
            }
        """
    
    @abstractmethod
    def get_subscribed_symbols(self) -> List[str]:
        """
        获取当前订阅的交易对列表
        Get currently subscribed symbols
        
        Returns:
            List[str]: 已订阅的交易对列表 / List of subscribed symbols
        """
    
    # ==================== 扩展方法 Extended Methods ====================
    
    async def get_multi_timeframe_klines(self, symbol: str, timeframes: List[str] = None, 
                                       limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取多时间周期K线数据（默认实现）
        Get multi-timeframe kline data (default implementation)
        
        Args:
            symbol: 交易对符号 / Trading pair symbol
            timeframes: 时间周期列表 / List of timeframes
            limit: 每个时间周期的数据条数 / Number of data points per timeframe
            
        Returns:
            Dict[str, List[Dict[str, Any]]]: 按时间周期分组的K线数据
        """
        if timeframes is None:
            timeframes = ['1m', '5m', '15m', '1H', '4H', '1D']
        
        result = {}
        for timeframe in timeframes:
            try:
                klines = await self.get_kline_data(symbol, timeframe, limit)
                result[timeframe] = klines
                logger.debug(f"📊 获取 {symbol} {timeframe} K线: {len(klines)} 条")
            except Exception as e:
                logger.error(f"❌ 获取 {symbol} {timeframe} K线失败: {e}")
                result[timeframe] = []
        
        return result
    
    async def refresh_subscriptions(self) -> bool:
        """
        刷新订阅（默认实现）
        Refresh subscriptions (default implementation)
        
        Returns:
            bool: 刷新是否成功 / Whether refresh was successful
        """
        try:
            # 获取当前订阅的交易对
            symbols = self.get_subscribed_symbols()
            if not symbols:
                logger.info("📭 没有需要刷新的订阅")
                return True
            
            # 重新订阅所有交易对
            results = await self.subscribe_symbols_realtime(symbols)
            success_count = sum(1 for success in results.values() if success)
            
            logger.info(f"🔄 订阅刷新完成: {success_count}/{len(symbols)} 成功")
            return success_count == len(symbols)
            
        except Exception as e:
            logger.error(f"❌ 刷新订阅失败: {e}")
            return False