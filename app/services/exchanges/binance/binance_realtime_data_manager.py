# -*- coding: utf-8 -*-
"""
币安实时数据管理器
Binance Real-time Data Manager - 统一管理WebSocket实时数据
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.exchanges.binance.binance_websocket_service import BinanceWebSocketService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


@dataclass
class MarketData:
    """市场数据结构"""
    symbol: str
    price: float
    volume_24h: float
    change_24h: float
    timestamp: datetime
    bid_price: float = 0.0
    ask_price: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    open_24h: float = 0.0


@dataclass
class KlineData:
    """K线数据结构"""
    symbol: str
    timeframe: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirm: bool = True  # 是否确认（完成的K线）


@dataclass
class TradeData:
    """交易数据结构"""
    symbol: str
    price: float
    size: float
    side: str  # buy/sell
    timestamp: int
    trade_id: str


@dataclass
class FundingRateData:
    """资金费率数据结构"""
    symbol: str
    funding_rate: float
    next_funding_time: datetime
    timestamp: datetime


class BinanceRealtimeDataManager:
    """币安实时数据管理器"""
    
    def __init__(self, max_history_size: int = 1000):
        self.max_history_size = max_history_size
        
        # 数据存储
        self.tickers: Dict[str, MarketData] = {}
        self.klines: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=max_history_size)))
        self.trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history_size))
        self.funding_rates: Dict[str, FundingRateData] = {}
        self.mark_prices: Dict[str, Dict[str, Any]] = {}
        
        # 订阅管理
        self.subscribed_symbols: set = set()
        self.subscribed_timeframes: Dict[str, set] = defaultdict(set)
        
        # WebSocket服务
        self.ws_service = None
        self.is_initialized = False
        
        # 数据更新回调
        self.data_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
        # REST API轮询任务
        self._rest_api_tasks: List[asyncio.Task] = []
        self._rest_api_klines: set = set()
        
        logger.info("📊 币安实时数据管理器初始化完成")
    
    async def initialize(self):
        """初始化数据管理器"""
        if self.is_initialized:
            return
        
        try:
            logger.info("🚀 初始化币安实时数据管理器...")
            
            # 创建WebSocket服务
            self.ws_service = BinanceWebSocketService()
            await self.ws_service.start()
            
            # 等待WebSocket服务启动
            await asyncio.sleep(2.0)
            
            self.is_initialized = True
            logger.info("✅ 币安实时数据管理器初始化成功")
            
        except Exception as e:
            logger.error(f"❌ 币安实时数据管理器初始化失败: {e}")
            raise TradingToolError(f"币安实时数据管理器初始化失败: {e}")
    
    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("🧹 清理币安实时数据管理器...")
            
            # 停止REST API轮询任务
            for task in self._rest_api_tasks:
                if not task.done():
                    task.cancel()
            
            # 停止WebSocket服务
            if self.ws_service:
                await self.ws_service.stop()
            
            # 清理数据
            self.tickers.clear()
            self.klines.clear()
            self.trades.clear()
            self.funding_rates.clear()
            self.mark_prices.clear()
            self.subscribed_symbols.clear()
            self.subscribed_timeframes.clear()
            
            self.is_initialized = False
            logger.info("✅ 币安实时数据管理器清理完成")
            
        except Exception as e:
            logger.error(f"❌ 清理币安实时数据管理器异常: {e}")
    
    async def subscribe_ticker(self, symbols: List[str]) -> bool:
        """订阅ticker数据"""
        if not self.is_initialized:
            await self.initialize()
        
        if not symbols:
            return True
        
        logger.info(f"📡 开始订阅ticker: {len(symbols)} 个交易对")
        
        success_count = 0
        failed_symbols = []
        
        for symbol in symbols:
            try:
                success = await self.ws_service.subscribe_symbol_ticker(
                    symbol,
                    callback=self._on_ticker_update
                )
                
                if success:
                    self.subscribed_symbols.add(symbol)
                    success_count += 1
                    logger.debug(f"📡 订阅ticker成功: {symbol}")
                else:
                    failed_symbols.append(symbol)
                    logger.warning(f"⚠️ 订阅ticker失败: {symbol}")
                
                # 避免频率限制
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ 订阅{symbol} ticker异常: {e}")
                failed_symbols.append(symbol)
        
        # 重试失败的订阅
        if failed_symbols and len(failed_symbols) <= 10:
            logger.info(f"🔄 重试订阅失败的ticker: {len(failed_symbols)} 个")
            await asyncio.sleep(1)
            
            for symbol in failed_symbols[:]:
                try:
                    success = await self.ws_service.subscribe_symbol_ticker(
                        symbol,
                        callback=self._on_ticker_update
                    )
                    if success:
                        self.subscribed_symbols.add(symbol)
                        success_count += 1
                        failed_symbols.remove(symbol)
                        logger.info(f"✅ 重试订阅ticker成功: {symbol}")
                    
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.warning(f"⚠️ 重试订阅{symbol} ticker仍失败: {e}")
        
        logger.info(f"📡 Ticker订阅完成: {success_count}/{len(symbols)} 成功")
        if failed_symbols:
            if len(failed_symbols) <= 5:
                logger.warning(f"⚠️ 订阅失败的ticker: {failed_symbols}")
            else:
                logger.warning(f"⚠️ 订阅失败的ticker: {len(failed_symbols)} 个")
        
        return success_count > 0
    
    async def subscribe_klines(self, symbols: List[str], timeframes: List[str] = None) -> bool:
        """订阅K线数据"""
        if not self.is_initialized:
            await self.initialize()
        
        if timeframes is None:
            timeframes = ["1m", "5m", "15m", "1h"]
        
        if not symbols:
            return True
        
        logger.info(f"📈 开始订阅K线: {len(symbols)} 个交易对 × {len(timeframes)} 个时间周期")
        
        success_count = 0
        total_subscriptions = len(symbols) * len(timeframes)
        
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    success = await self.ws_service.subscribe_symbol_kline(
                        symbol,
                        interval=timeframe,
                        callback=self._on_kline_update
                    )
                    
                    if success:
                        self.subscribed_timeframes[symbol].add(timeframe)
                        success_count += 1
                        logger.debug(f"📈 订阅K线成功: {symbol} {timeframe}")
                    else:
                        logger.warning(f"⚠️ 订阅K线失败: {symbol} {timeframe}")
                    
                    # 避免频率限制
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"❌ 订阅{symbol} {timeframe} K线异常: {e}")
        
        logger.info(f"📈 K线订阅完成: {success_count}/{total_subscriptions} 成功")
        return success_count > 0
    
    async def subscribe_trades(self, symbols: List[str]) -> bool:
        """订阅交易数据"""
        if not self.is_initialized:
            await self.initialize()
        
        if not symbols:
            return True
        
        logger.info(f"💰 开始订阅交易数据: {len(symbols)} 个交易对")
        
        success_count = 0
        for symbol in symbols:
            try:
                success = await self.ws_service.subscribe_symbol_trades(
                    symbol,
                    callback=self._on_trade_update
                )
                if success:
                    success_count += 1
                    logger.debug(f"💰 订阅交易数据成功: {symbol}")
                else:
                    logger.warning(f"⚠️ 订阅交易数据失败: {symbol}")
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ 订阅{symbol}交易数据异常: {e}")
        
        logger.info(f"💰 交易数据订阅完成: {success_count}/{len(symbols)} 成功")
        return success_count > 0
    
    async def subscribe_funding_rates(self, symbols: List[str]) -> bool:
        """订阅资金费率（通过标记价格获取）
        优化: 过滤无效USDT永续合约，批量/全市场订阅以减少连接次数"""
        if not self.is_initialized:
            await self.initialize()
        
        if not symbols:
            return True
        
        logger.info(f"💸 开始订阅资金费率: {len(symbols)} 个交易对 (优化模式)")

        # 过滤有效合约
        valid_symbols: List[str] = []
        invalid_symbols: List[str] = []
        for sym in symbols:
            try:
                conv = self.ws_service._convert_symbol_to_binance(sym)
                if await self.ws_service._is_valid_futures_symbol(conv.upper()):
                    valid_symbols.append(sym)
                else:
                    invalid_symbols.append(sym)
            except Exception:
                invalid_symbols.append(sym)

        if invalid_symbols:
            logger.warning(f"⚠️ 跳过无效/非永续合约符号: {invalid_symbols[:10]}{'...' if len(invalid_symbols)>10 else ''}")

        if not valid_symbols:
            logger.error("❌ 无有效USDT永续合约可订阅资金费率")
            return False

        success_total = 0

        # 策略: 大量使用全市场 (!markPrice@arr) ; 中等使用批量合并 ; 少量逐个
        if len(valid_symbols) >= 80:
            logger.info("🔀 使用全市场标记价格订阅 !markPrice@arr")
            success = await self.ws_service.subscribe_all_mark_price(callback=self._on_all_funding_rates_update)
            if success:
                success_total = len(valid_symbols)
            else:
                logger.error("❌ 全市场资金费率订阅失败，回退到批量模式")
                batch_result = await self.ws_service.subscribe_multi_mark_price(valid_symbols, callback=self._on_funding_rate_update)
                success_total = sum(1 for v in batch_result.values() if v)
        elif len(valid_symbols) >= 25:
            logger.info("🔀 使用合并批量订阅标记价格 streams")
            batch_result = await self.ws_service.subscribe_multi_mark_price(valid_symbols, callback=self._on_funding_rate_update)
            success_total = sum(1 for v in batch_result.values() if v)
        else:
            logger.info("🔀 使用单流订阅模式")
            for sym in valid_symbols:
                try:
                    success = await self.ws_service.subscribe_symbol_mark_price(sym, callback=self._on_funding_rate_update)
                    if success:
                        success_total += 1
                    else:
                        logger.warning(f"⚠️ 订阅资金费率失败: {sym}")
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"❌ 订阅{sym}资金费率异常: {e}")

        logger.info(f"💸 资金费率订阅完成: {success_total}/{len(valid_symbols)} 有效合约成功 (原始请求 {len(symbols)})")
        return success_total > 0

    async def subscribe_all_funding_rates(self) -> bool:
        """订阅所有交易对的资金费率"""
        if not self.is_initialized:
            await self.initialize()
        
        logger.info("💸 订阅所有交易对的资金费率")
        
        try:
            success = await self.ws_service.subscribe_all_mark_price(
                callback=self._on_all_funding_rates_update
            )
            
            if success:
                logger.info("✅ 订阅所有资金费率成功")
            else:
                logger.error("❌ 订阅所有资金费率失败")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅所有资金费率异常: {e}")
            return False
    
    # 数据更新回调函数
    async def _on_ticker_update(self, data: Dict[str, Any]) -> None:
        """处理ticker数据更新"""
        try:
            if 'e' in data and data['e'] == '24hrTicker':
                symbol = data.get('s', '')
                standard_symbol = self._convert_symbol_from_binance(symbol)
                
                market_data = MarketData(
                    symbol=standard_symbol,
                    price=float(data.get('c', '0')),
                    volume_24h=float(data.get('v', '0')),
                    change_24h=float(data.get('P', '0')),
                    timestamp=datetime.fromtimestamp(int(data.get('E', '0')) / 1000),
                    bid_price=float(data.get('b', '0')),
                    ask_price=float(data.get('a', '0')),
                    high_24h=float(data.get('h', '0')),
                    low_24h=float(data.get('l', '0')),
                    open_24h=float(data.get('o', '0'))
                )
                
                self.tickers[standard_symbol] = market_data
                
                # 调用回调函数
                await self._call_callbacks('ticker', standard_symbol, market_data)
                
                logger.debug(f"📊 更新ticker: {standard_symbol} = {market_data.price}")
                
        except Exception as e:
            logger.error(f"❌ 处理ticker更新异常: {e}")
    
    async def _on_kline_update(self, data: Dict[str, Any]) -> None:
        """处理K线数据更新"""
        try:
            if 'e' in data and data['e'] == 'kline':
                kline = data.get('k', {})
                symbol = kline.get('s', '')
                standard_symbol = self._convert_symbol_from_binance(symbol)
                interval = kline.get('i', '')
                
                kline_data = KlineData(
                    symbol=standard_symbol,
                    timeframe=interval,
                    timestamp=int(kline.get('t', '0')),
                    open=float(kline.get('o', '0')),
                    high=float(kline.get('h', '0')),
                    low=float(kline.get('l', '0')),
                    close=float(kline.get('c', '0')),
                    volume=float(kline.get('v', '0')),
                    confirm=kline.get('x', False)  # K线是否结束
                )
                
                # 存储K线数据
                self.klines[standard_symbol][interval].append(kline_data)
                
                # 调用回调函数
                await self._call_callbacks('kline', standard_symbol, kline_data)
                
                if kline_data.confirm:
                    logger.debug(f"📈 K线结束: {standard_symbol} {interval} = {kline_data.close}")
                
        except Exception as e:
            logger.error(f"❌ 处理K线更新异常: {e}")
    
    async def _on_trade_update(self, data: Dict[str, Any]) -> None:
        """处理交易数据更新"""
        try:
            if 'e' in data and data['e'] == 'aggTrade':
                symbol = data.get('s', '')
                standard_symbol = self._convert_symbol_from_binance(symbol)
                
                trade_data = TradeData(
                    symbol=standard_symbol,
                    price=float(data.get('p', '0')),
                    size=float(data.get('q', '0')),
                    side='buy' if not data.get('m', False) else 'sell',
                    timestamp=int(data.get('T', '0')),
                    trade_id=str(data.get('a', ''))
                )
                
                # 存储交易数据
                self.trades[standard_symbol].append(trade_data)
                
                # 调用回调函数
                await self._call_callbacks('trade', standard_symbol, trade_data)
                
                logger.debug(f"💰 交易更新: {standard_symbol} {trade_data.side} {trade_data.size}@{trade_data.price}")
                
        except Exception as e:
            logger.error(f"❌ 处理交易更新异常: {e}")
    
    async def _on_funding_rate_update(self, data: Dict[str, Any]) -> None:
        """处理资金费率更新"""
        try:
            if 'e' in data and data['e'] == 'markPriceUpdate':
                symbol = data.get('s', '')
                standard_symbol = self._convert_symbol_from_binance(symbol)
                
                funding_data = FundingRateData(
                    symbol=standard_symbol,
                    funding_rate=float(data.get('r', '0')),
                    next_funding_time=datetime.fromtimestamp(int(data.get('T', '0')) / 1000),
                    timestamp=datetime.fromtimestamp(int(data.get('E', '0')) / 1000)
                )
                
                # 存储资金费率数据
                self.funding_rates[standard_symbol] = funding_data
                
                # 同时存储标记价格数据
                self.mark_prices[standard_symbol] = {
                    'mark_price': float(data.get('p', '0')),
                    'index_price': float(data.get('i', '0')),
                    'funding_rate': funding_data.funding_rate,
                    'next_funding_time': funding_data.next_funding_time,
                    'timestamp': funding_data.timestamp
                }
                
                # 调用回调函数
                await self._call_callbacks('funding_rate', standard_symbol, funding_data)
                
                logger.debug(f"💸 资金费率更新: {standard_symbol} = {funding_data.funding_rate}")
                
        except Exception as e:
            logger.error(f"❌ 处理资金费率更新异常: {e}")
    
    async def _on_all_funding_rates_update(self, data: List[Dict[str, Any]]) -> None:
        """处理所有资金费率更新"""
        try:
            if isinstance(data, list):
                for item in data:
                    symbol = item.get('s', '')
                    standard_symbol = self._convert_symbol_from_binance(symbol)
                    
                    funding_data = FundingRateData(
                        symbol=standard_symbol,
                        funding_rate=float(item.get('r', '0')),
                        next_funding_time=datetime.fromtimestamp(int(item.get('T', '0')) / 1000),
                        timestamp=datetime.now()
                    )
                    
                    self.funding_rates[standard_symbol] = funding_data
                    
                    # 同时存储标记价格数据
                    self.mark_prices[standard_symbol] = {
                        'mark_price': float(item.get('p', '0')),
                        'index_price': float(item.get('i', '0')),
                        'funding_rate': funding_data.funding_rate,
                        'next_funding_time': funding_data.next_funding_time,
                        'timestamp': funding_data.timestamp
                    }
                
                logger.debug(f"💸 批量更新资金费率: {len(data)} 个交易对")
                
        except Exception as e:
            logger.error(f"❌ 处理批量资金费率更新异常: {e}")
    
    async def _call_callbacks(self, data_type: str, symbol: str, data: Any) -> None:
        """调用数据更新回调函数"""
        try:
            callbacks = self.data_callbacks.get(f"{data_type}_{symbol}", [])
            callbacks.extend(self.data_callbacks.get(data_type, []))
            
            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    logger.error(f"❌ 回调函数执行异常: {e}")
                    
        except Exception as e:
            logger.error(f"❌ 调用回调函数异常: {e}")
    
    # 数据获取方法
    def get_latest_ticker(self, symbol: str) -> Optional[MarketData]:
        """获取最新ticker数据"""
        return self.tickers.get(symbol)
    
    def get_latest_klines(self, symbol: str, timeframe: str, limit: int = 100) -> List[KlineData]:
        """获取最新K线数据"""
        klines = self.klines.get(symbol, {}).get(timeframe, deque())
        return list(klines)[-limit:] if klines else []
    
    def get_latest_trades(self, symbol: str, limit: int = 100) -> List[TradeData]:
        """获取最新交易数据"""
        trades = self.trades.get(symbol, deque())
        return list(trades)[-limit:] if trades else []
    
    def get_latest_funding_rate(self, symbol: str) -> Optional[FundingRateData]:
        """获取最新资金费率数据"""
        return self.funding_rates.get(symbol)
    
    def get_latest_mark_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新标记价格数据"""
        return self.mark_prices.get(symbol)
    
    def get_all_tickers(self) -> Dict[str, MarketData]:
        """获取所有ticker数据"""
        return self.tickers.copy()
    
    def get_all_funding_rates(self) -> Dict[str, FundingRateData]:
        """获取所有资金费率数据"""
        return self.funding_rates.copy()
    
    # 回调管理
    def add_callback(self, data_type: str, callback: Callable, symbol: str = None) -> None:
        """添加数据更新回调"""
        key = f"{data_type}_{symbol}" if symbol else data_type
        self.data_callbacks[key].append(callback)
    
    def remove_callback(self, data_type: str, callback: Callable, symbol: str = None) -> None:
        """移除数据更新回调"""
        key = f"{data_type}_{symbol}" if symbol else data_type
        if key in self.data_callbacks and callback in self.data_callbacks[key]:
            self.data_callbacks[key].remove(callback)
    
    # 工具方法
    def _convert_symbol_from_binance(self, binance_symbol: str) -> str:
        """将币安符号转换为标准格式"""
        # BTCUSDT -> BTC-USDT-SWAP
        if binance_symbol.endswith('USDT'):
            base = binance_symbol[:-4]  # 移除USDT
            return f"{base}-USDT-SWAP"
        return binance_symbol
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        if not self.ws_service:
            return {"status": "not_initialized"}
        
        return {
            "status": "initialized" if self.is_initialized else "not_initialized",
            "websocket_status": self.ws_service.get_connection_status(),
            "subscribed_symbols": len(self.subscribed_symbols),
            "cached_tickers": len(self.tickers),
            "cached_funding_rates": len(self.funding_rates),
            "cached_mark_prices": len(self.mark_prices)
        }
    
    def get_subscribed_symbols(self) -> List[str]:
        """获取已订阅的交易对列表"""
        return list(self.subscribed_symbols)


# 全局实例
_binance_realtime_manager = None


async def get_binance_realtime_manager() -> BinanceRealtimeDataManager:
    """获取币安实时数据管理器实例"""
    global _binance_realtime_manager
    
    if _binance_realtime_manager is None:
        _binance_realtime_manager = BinanceRealtimeDataManager()
        await _binance_realtime_manager.initialize()
    
    return _binance_realtime_manager