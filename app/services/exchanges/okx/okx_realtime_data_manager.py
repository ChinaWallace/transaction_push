# -*- coding: utf-8 -*-
"""
OKX实时数据管理器
OKX Real-time Data Manager - 统一管理WebSocket实时数据
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.exchanges.okx.okx_websocket_service import get_okx_websocket_service

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
    next_funding_time: int
    timestamp: datetime


class OKXRealtimeDataManager:
    """OKX实时数据管理器"""
    
    def __init__(self, max_history_size: int = 1000):
        self.max_history_size = max_history_size
        
        # 数据存储
        self.tickers: Dict[str, MarketData] = {}
        self.klines: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=max_history_size)))
        self.trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history_size))
        self.funding_rates: Dict[str, FundingRateData] = {}
        
        # 订阅管理
        self.subscribed_symbols: set = set()
        self.subscribed_timeframes: Dict[str, set] = defaultdict(set)
        
        # WebSocket服务
        self.ws_service = None
        self.is_initialized = False
        
        # 数据更新回调
        self.data_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
        logger.info("📊 OKX实时数据管理器初始化完成")

    async def initialize(self):
        """初始化数据管理器"""
        if self.is_initialized:
            return
        
        try:
            logger.info("🚀 初始化实时数据管理器...")
            
            # 获取WebSocket服务
            self.ws_service = await get_okx_websocket_service()
            
            # 等待WebSocket连接建立，最多等待20秒
            logger.info("⏳ 等待WebSocket连接建立...")
            connection_ready = await self.ws_service.wait_for_connection(timeout=20.0)
            
            if not connection_ready:
                logger.error("❌ WebSocket连接建立超时")
                raise TradingToolError("WebSocket连接建立失败")
            
            # 连接建立后再等待一段时间确保稳定
            await asyncio.sleep(2.0)
            
            self.is_initialized = True
            logger.info("✅ 实时数据管理器初始化成功")
            
        except Exception as e:
            logger.error(f"❌ 实时数据管理器初始化失败: {e}")
            raise

    async def subscribe_ticker(self, symbols: List[str]) -> bool:
        """订阅ticker数据（批量优化）"""
        if not self.is_initialized:
            await self.initialize()
        
        # 检查WebSocket连接状态
        if not self.ws_service.is_public_connected():
            logger.error("❌ WebSocket未连接，无法订阅ticker")
            return False
        
        if not symbols:
            return True
        
        logger.info(f"📡 开始批量订阅ticker: {len(symbols)} 个交易对")
        
        # 使用WebSocket服务的批量订阅方法
        try:
            results = await self.ws_service.subscribe_tickers_batch(
                symbols, 
                callback=self._on_ticker_update
            )
            
            success_count = 0
            failed_symbols = []
            
            for symbol, success in results.items():
                if success:
                    self.subscribed_symbols.add(symbol)
                    success_count += 1
                else:
                    failed_symbols.append(symbol)
            
            # 对失败的符号进行重试（限制重试数量）
            if failed_symbols and len(failed_symbols) <= 10:
                logger.info(f"🔄 重试订阅失败的ticker: {len(failed_symbols)} 个")
                await asyncio.sleep(1)
                
                for symbol in failed_symbols:
                    try:
                        success = await self._subscribe_single_ticker(symbol)
                        if success:
                            self.subscribed_symbols.add(symbol)
                            success_count += 1
                    except Exception as e:
                        logger.debug(f"🔍 重试订阅{symbol}失败: {e}")
        
        except Exception as e:
            logger.error(f"❌ 批量ticker订阅异常: {e}")
            return False
            
            for symbol in failed_symbols[:]:  # 使用切片避免修改正在迭代的列表
                try:
                    success = await self.ws_service.subscribe_ticker(
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
                logger.warning(f"⚠️ 订阅失败的ticker: {len(failed_symbols)} 个 (前5个: {failed_symbols[:5]})")
        
        return success_count > 0

    async def subscribe_klines(self, symbols: List[str], timeframes: List[str] = None) -> bool:
        """订阅K线数据 - 已禁用WebSocket，使用REST API轮询"""
        if timeframes is None:
            timeframes = ["1m", "5m", "15m", "1H"]
        
        logger.info(f"📈 K线订阅已禁用WebSocket，将使用REST API轮询模式")
        logger.info(f"📊 配置REST API轮询: {len(symbols)} 个交易对 × {len(timeframes)} 个时间周期")
        
        # 直接设置为REST API轮询模式
        if not hasattr(self, '_rest_api_klines'):
            self._rest_api_klines = set()
        
        for symbol in symbols:
            for timeframe in timeframes:
                self._rest_api_klines.add((symbol, timeframe))
                self.subscribed_timeframes[symbol].add(timeframe)
        
        # 启动REST API轮询任务
        if self._rest_api_klines:
            logger.info(f"🔄 启动REST API轮询任务，覆盖 {len(self._rest_api_klines)} 个K线订阅")
            asyncio.create_task(self._rest_api_kline_polling())
        
        total_subscriptions = len(symbols) * len(timeframes)
        logger.info(f"📡 K线订阅完成: {total_subscriptions}/{total_subscriptions} 成功 (REST API模式)")
        
        return True


    async def subscribe_trades(self, symbols: List[str]) -> bool:
        """订阅交易数据"""
        if not self.is_initialized:
            await self.initialize()
        
        success_count = 0
        for symbol in symbols:
            try:
                success = await self.ws_service.subscribe_trades(
                    symbol,
                    callback=self._on_trade_update
                )
                if success:
                    success_count += 1
                    logger.debug(f"📡 订阅交易数据成功: {symbol}")
                else:
                    logger.warning(f"⚠️ 订阅交易数据失败: {symbol}")
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ 订阅{symbol}交易数据异常: {e}")
        
        logger.info(f"📡 交易数据订阅完成: {success_count}/{len(symbols)} 成功")
        return success_count > 0

    async def subscribe_funding_rates(self, symbols: List[str]) -> bool:
        """订阅资金费率（批量优化）"""
        if not self.is_initialized:
            await self.initialize()
        
        if not symbols:
            return True
        
        logger.info(f"💰 开始批量订阅资金费率: {len(symbols)} 个交易对")
        
        # 使用WebSocket服务的批量订阅方法
        try:
            results = await self.ws_service.subscribe_funding_rates_batch(
                symbols,
                callback=self._on_funding_rate_update
            )
            
            success_count = 0
            failed_symbols = []
            
            for symbol, success in results.items():
                if success:
                    success_count += 1
                else:
                    failed_symbols.append(symbol)
            
            # 对失败的符号进行重试（限制重试数量）
            if failed_symbols and len(failed_symbols) <= 10:
                logger.info(f"🔄 重试订阅失败的资金费率: {len(failed_symbols)} 个")
                await asyncio.sleep(1)
                
                for symbol in failed_symbols:
                    try:
                        success = await self._subscribe_single_funding_rate(symbol)
                        if success:
                            success_count += 1
                    except Exception as e:
                        logger.debug(f"🔍 重试订阅{symbol}资金费率失败: {e}")
            
            logger.info(f"💰 资金费率订阅完成: {success_count}/{len(symbols)} 成功")
            
            if failed_symbols:
                if len(failed_symbols) <= 5:
                    logger.warning(f"⚠️ 资金费率订阅失败: {failed_symbols}")
                else:
                    logger.warning(f"⚠️ 资金费率订阅失败: {len(failed_symbols)} 个 (前5个: {failed_symbols[:5]})")
            
            return success_count > 0
        
        except Exception as e:
            logger.error(f"❌ 批量资金费率订阅异常: {e}")
            return False

    async def _subscribe_single_ticker(self, symbol: str) -> bool:
        """订阅单个ticker（内部方法）"""
        try:
            return await self.ws_service.subscribe_ticker(
                symbol, 
                callback=self._on_ticker_update
            )
        except Exception as e:
            logger.debug(f"🔍 订阅{symbol} ticker失败: {e}")
            return False

    async def _subscribe_single_funding_rate(self, symbol: str) -> bool:
        """订阅单个资金费率（内部方法）"""
        try:
            return await self.ws_service.subscribe_funding_rate(
                symbol,
                callback=self._on_funding_rate_update
            )
        except Exception as e:
            logger.debug(f"🔍 订阅{symbol} 资金费率失败: {e}")
            return False

    def _normalize_symbol(self, inst_id: str) -> str:
        """
        标准化交易对名称 - 直接返回原始名称
        Normalize symbol name - return original name as-is
        """
        return inst_id

    async def _on_ticker_update(self, channel: str, inst_id: str, data: List[Dict[str, Any]]):
        """处理ticker更新"""
        try:
            # 标准化交易对名称
            normalized_symbol = self._normalize_symbol(inst_id)
            
            for item in data:
                ticker_data = MarketData(
                    symbol=normalized_symbol,  # 使用标准化后的名称
                    price=float(item.get('last', 0)),
                    volume_24h=float(item.get('vol24h', 0)),
                    change_24h=float(item.get('sodUtc8', 0)),
                    timestamp=datetime.now(),
                    bid_price=float(item.get('bidPx', 0)),
                    ask_price=float(item.get('askPx', 0)),
                    high_24h=float(item.get('high24h', 0)),
                    low_24h=float(item.get('low24h', 0)),
                    open_24h=float(item.get('open24h', 0))
                )
                
                self.tickers[normalized_symbol] = ticker_data
                
                # 触发回调
                await self._trigger_callbacks('ticker', normalized_symbol, ticker_data)
                
                logger.debug(f"📊 更新ticker: {normalized_symbol} = ${ticker_data.price:.4f}")
                
        except Exception as e:
            logger.error(f"❌ 处理ticker更新异常: {e}")

    async def _on_kline_update(self, channel: str, inst_id: str, data: List[Dict[str, Any]]):
        """处理K线更新"""
        try:
            # 标准化交易对名称
            normalized_symbol = self._normalize_symbol(inst_id)
            
            # 从channel中提取timeframe
            timeframe = channel.replace('candle', '')
            
            for item in data:
                kline_data = KlineData(
                    symbol=normalized_symbol,  # 使用标准化后的名称
                    timeframe=timeframe,
                    timestamp=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    confirm=item[8] == '1'  # 1表示确认的K线
                )
                
                # 存储K线数据
                self.klines[normalized_symbol][timeframe].append(kline_data)
                
                # 触发回调
                await self._trigger_callbacks('kline', normalized_symbol, kline_data)
                
                logger.debug(f"📈 更新K线: {normalized_symbol} {timeframe} = {kline_data.close:.4f}")
                
        except Exception as e:
            logger.error(f"❌ 处理K线更新异常: {e}")

    async def _on_trade_update(self, channel: str, inst_id: str, data: List[Dict[str, Any]]):
        """处理交易更新"""
        try:
            # 标准化交易对名称
            normalized_symbol = self._normalize_symbol(inst_id)
            
            for item in data:
                trade_data = TradeData(
                    symbol=normalized_symbol,  # 使用标准化后的名称
                    price=float(item.get('px', 0)),
                    size=float(item.get('sz', 0)),
                    side=item.get('side', ''),
                    timestamp=int(item.get('ts', 0)),
                    trade_id=item.get('tradeId', '')
                )
                
                # 存储交易数据
                self.trades[normalized_symbol].append(trade_data)
                
                # 触发回调
                await self._trigger_callbacks('trade', normalized_symbol, trade_data)
                
                logger.debug(f"💰 新交易: {normalized_symbol} {trade_data.side} {trade_data.size}@{trade_data.price}")
                
        except Exception as e:
            logger.error(f"❌ 处理交易更新异常: {e}")

    async def _on_funding_rate_update(self, channel: str, inst_id: str, data: List[Dict[str, Any]]):
        """处理资金费率更新"""
        try:
            # 标准化交易对名称
            normalized_symbol = self._normalize_symbol(inst_id)
            
            for item in data:
                funding_data = FundingRateData(
                    symbol=normalized_symbol,  # 使用标准化后的名称
                    funding_rate=float(item.get('fundingRate', 0)),
                    next_funding_time=int(item.get('nextFundingTime', 0)),
                    timestamp=datetime.now()
                )
                
                self.funding_rates[normalized_symbol] = funding_data
                
                # 触发回调
                await self._trigger_callbacks('funding_rate', normalized_symbol, funding_data)
                
                rate_percent = funding_data.funding_rate * 100
                logger.debug(f"💸 更新费率: {normalized_symbol} = {rate_percent:.4f}%")
                
        except Exception as e:
            logger.error(f"❌ 处理资金费率更新异常: {e}")

    async def _trigger_callbacks(self, data_type: str, symbol: str, data: Any):
        """触发数据更新回调"""
        callback_key = f"{data_type}:{symbol}"
        if callback_key in self.data_callbacks:
            for callback in self.data_callbacks[callback_key]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data_type, symbol, data)
                    else:
                        callback(data_type, symbol, data)
                except Exception as e:
                    logger.error(f"❌ 数据回调异常: {e}")

    def register_callback(self, data_type: str, symbol: str, callback: Callable):
        """注册数据更新回调"""
        callback_key = f"{data_type}:{symbol}"
        self.data_callbacks[callback_key].append(callback)
        logger.debug(f"📝 注册回调: {callback_key}")

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """获取最新价格"""
        if symbol in self.tickers:
            return self.tickers[symbol].price
        return None

    def get_latest_ticker(self, symbol: str) -> Optional[MarketData]:
        """获取最新ticker数据"""
        return self.tickers.get(symbol)

    def get_latest_klines(self, symbol: str, timeframe: str, limit: int = 100) -> List[KlineData]:
        """获取最新K线数据"""
        if symbol in self.klines and timeframe in self.klines[symbol]:
            klines = list(self.klines[symbol][timeframe])
            return klines[-limit:] if len(klines) > limit else klines
        return []

    def get_latest_trades(self, symbol: str, limit: int = 100) -> List[TradeData]:
        """获取最新交易数据"""
        if symbol in self.trades:
            trades = list(self.trades[symbol])
            return trades[-limit:] if len(trades) > limit else trades
        return []

    def get_funding_rate(self, symbol: str) -> Optional[FundingRateData]:
        """获取资金费率"""
        return self.funding_rates.get(symbol)

    def get_price_change_24h(self, symbol: str) -> Optional[float]:
        """获取24小时价格变化"""
        if symbol in self.tickers:
            return self.tickers[symbol].change_24h
        return None

    def get_volume_24h(self, symbol: str) -> Optional[float]:
        """获取24小时成交量"""
        if symbol in self.tickers:
            return self.tickers[symbol].volume_24h
        return None

    def get_statistics(self) -> Dict[str, Any]:
        """获取数据统计信息"""
        total_klines = sum(
            sum(len(timeframe_data) for timeframe_data in symbol_data.values())
            for symbol_data in self.klines.values()
        )
        
        total_trades = sum(len(trades) for trades in self.trades.values())
        
        return {
            'subscribed_symbols': len(self.subscribed_symbols),
            'ticker_count': len(self.tickers),
            'total_klines': total_klines,
            'total_trades': total_trades,
            'funding_rates_count': len(self.funding_rates),
            'ws_status': self.ws_service.get_connection_status() if self.ws_service else None
        }

    async def _rest_api_kline_polling(self):
        """REST API K线轮询任务"""
        try:
            logger.info("🔄 启动REST API K线轮询任务...")
            
            while hasattr(self, '_rest_api_klines') and self._rest_api_klines:
                try:
                    # 获取OKX服务
                    from app.services.exchanges.okx.okx_service import OKXService
                    
                    async with OKXService() as okx_service:
                        for symbol, timeframe in list(self._rest_api_klines):
                            try:
                                # 获取K线数据
                                klines = await okx_service.get_klines(symbol, timeframe, limit=1)
                                
                                if klines:
                                    # 模拟WebSocket数据格式
                                    kline_item = klines[0]
                                    mock_data = [[
                                        str(kline_item['ts']),
                                        str(kline_item['o']),
                                        str(kline_item['h']),
                                        str(kline_item['l']),
                                        str(kline_item['c']),
                                        str(kline_item['vol']),
                                        str(kline_item['volCcy']),
                                        str(kline_item['volCcyQuote']),
                                        '1'  # 确认的K线
                                    ]]
                                    
                                    # 调用K线更新处理
                                    await self._on_kline_update(f"candle{timeframe}", symbol, mock_data)
                                    
                            except Exception as e:
                                logger.debug(f"REST API获取K线失败 {symbol} {timeframe}: {e}")
                    
                    # 每30秒轮询一次
                    await asyncio.sleep(30)
                    
                except Exception as e:
                    logger.error(f"❌ REST API轮询异常: {e}")
                    await asyncio.sleep(60)  # 出错时等待更长时间
                    
        except Exception as e:
            logger.error(f"❌ REST API轮询任务异常: {e}")

    async def cleanup(self):
        """清理资源"""
        logger.info("🧹 清理实时数据管理器...")
        
        # 清理数据
        self.tickers.clear()
        self.klines.clear()
        self.trades.clear()
        self.funding_rates.clear()
        self.data_callbacks.clear()
        
        # 清理订阅
        self.subscribed_symbols.clear()
        self.subscribed_timeframes.clear()
        
        # 清理REST API轮询
        if hasattr(self, '_rest_api_klines'):
            self._rest_api_klines.clear()
        
        self.is_initialized = False
        logger.info("✅ 实时数据管理器清理完成")


# 全局实时数据管理器实例
_realtime_data_manager = None

async def get_realtime_data_manager() -> OKXRealtimeDataManager:
    """获取实时数据管理器实例"""
    global _realtime_data_manager
    if _realtime_data_manager is None:
        _realtime_data_manager = OKXRealtimeDataManager()
        await _realtime_data_manager.initialize()
    return _realtime_data_manager

async def cleanup_realtime_data_manager():
    """清理实时数据管理器"""
    global _realtime_data_manager
    if _realtime_data_manager:
        await _realtime_data_manager.cleanup()
        _realtime_data_manager = None