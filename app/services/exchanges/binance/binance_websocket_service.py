# -*- coding: utf-8 -*-
"""
币安WebSocket服务
Binance WebSocket Service - 提供高效的实时数据流服务
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class StreamType(Enum):
    """数据流类型枚举"""
    TICKER = "ticker"
    KLINE = "kline"
    TRADES = "aggTrade"
    DEPTH = "depth"
    BOOK_TICKER = "bookTicker"
    MARK_PRICE = "markPrice"
    FUNDING_RATE = "markPrice"  # 币安通过markPrice获取资金费率


@dataclass
class SubscriptionInfo:
    """订阅信息"""
    stream: str
    symbol: str
    callback: Optional[Callable] = None
    last_update: Optional[datetime] = None


class BinanceWebSocketService:
    """币安WebSocket服务类 - 增强版本"""
    
    def __init__(self):
        self.config = settings.binance_config
        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.testnet = self.config["testnet"]
        
        # WebSocket端点
        if self.testnet:
            self.ws_base_url = "wss://stream.binancefuture.com"
        else:
            self.ws_base_url = "wss://fstream.binance.com"
        
        # 增强的连接管理
        self.ws_connections: Dict[str, Any] = {}  # 支持多连接
        self.connection_states: Dict[str, str] = {}  # 连接状态跟踪
        self.is_running = False
        self.reconnect_interval = 5
        self.max_reconnect_attempts = 10
        
        # 指数退避重连配置
        self.reconnect_config = {
            'base_delay': 1.0,
            'max_delay': 60.0,
            'multiplier': 2.0,
            'jitter': True
        }
        
        # 连接健康监控
        self.connection_health: Dict[str, Dict[str, Any]] = {}
        self.health_check_interval = 30  # 30秒健康检查
        self.connection_timeout = 30     # 30秒连接超时
        
        # 订阅管理
        self.subscriptions: Dict[str, SubscriptionInfo] = {}
        self.callbacks: Dict[str, List[Callable]] = {}
        self.subscribed_streams: Set[str] = set()
        
        # 数据缓存
        self.latest_data: Dict[str, Dict[str, Any]] = {}
        self.data_lock = asyncio.Lock()
        
        # 心跳管理 - 增强版本
        self.last_ping_time = time.time()
        self.ping_interval = 20  # 币安建议20秒
        self.last_pong_time = time.time()
        self.heartbeat_timeout = 120  # 心跳超时时间增加到120秒
        
        # 错误统计
        self.error_stats = {
            'connection_errors': 0,
            'message_errors': 0,
            'reconnection_attempts': 0,
            'successful_reconnections': 0,
            'last_error_time': None
        }
        
        # 后台任务管理
        self.background_tasks: List[asyncio.Task] = []
        
        logger.info("🔌 币安WebSocket服务初始化完成 (增强版本)")
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态 - 增强版本"""
        current_time = time.time()
        
        # 统计活跃连接
        active_connections = 0
        connection_details = {}
        
        for stream_name, conn in self.ws_connections.items():
            is_active = conn and self._is_connection_alive(conn)
            active_connections += 1 if is_active else 0
            
            connection_details[stream_name] = {
                'active': is_active,
                'state': self.connection_states.get(stream_name, 'unknown'),
                'health': self.connection_health.get(stream_name, {}),
                'subscription': self.subscriptions.get(stream_name, None)
            }
        
        return {
            "is_running": self.is_running,
            "connections_count": len(self.ws_connections),
            "active_connections": active_connections,
            "connection_details": connection_details,
            "last_ping_time": self.last_ping_time,
            "last_pong_time": self.last_pong_time,
            "ping_interval": self.ping_interval,
            "heartbeat_timeout": self.heartbeat_timeout,
            "time_since_last_pong": current_time - self.last_pong_time,
            "subscriptions_count": len(self.subscriptions),
            "cached_data_count": len(self.latest_data),
            "error_stats": self.error_stats.copy(),
            "reconnect_config": self.reconnect_config.copy(),
            "health_check_interval": self.health_check_interval
        }
    
    async def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """等待WebSocket连接建立"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_connected():
                return True
            await asyncio.sleep(0.1)
        
        return False
    
    def is_connected(self) -> bool:
        """检查是否有活跃的WebSocket连接"""
        if not self.ws_connections:
            return False
        
        try:
            for conn in self.ws_connections.values():
                if conn and self._is_connection_alive(conn):
                    return True
            return False
        except Exception as e:
            logger.debug(f"🔍 检查WebSocket状态异常: {e}")
            return False
    
    def _is_connection_alive(self, conn) -> bool:
        """安全检查WebSocket连接是否存活"""
        try:
            # 检查不同类型的WebSocket连接对象
            if hasattr(conn, 'closed'):
                return not conn.closed
            elif hasattr(conn, 'state'):
                # websockets库的连接状态检查
                from websockets.protocol import State
                return conn.state == State.OPEN
            elif hasattr(conn, 'open'):
                return conn.open
            else:
                # 如果无法确定状态，假设连接是活跃的
                return True
        except Exception as e:
            logger.debug(f"🔍 检查连接状态异常: {e}")
            return False
    
    async def _initialize_connection_health(self, stream: str):
        """初始化连接健康监控"""
        self.connection_health[stream] = {
            'created_time': datetime.now(),
            'last_message_time': datetime.now(),
            'message_count': 0,
            'error_count': 0,
            'reconnect_count': 0,
            'last_reconnect_time': None,
            'consecutive_failures': 0,
            'is_healthy': True
        }
        self.connection_states[stream] = 'connecting'
    
    async def _update_connection_health(self, stream: str, event_type: str, success: bool = True):
        """更新连接健康状态"""
        if stream not in self.connection_health:
            await self._initialize_connection_health(stream)
        
        health = self.connection_health[stream]
        current_time = datetime.now()
        
        if event_type == 'message_received':
            health['last_message_time'] = current_time
            health['message_count'] += 1
            if success:
                health['consecutive_failures'] = 0
                health['is_healthy'] = True
                self.connection_states[stream] = 'connected'
            else:
                health['error_count'] += 1
                health['consecutive_failures'] += 1
        
        elif event_type == 'connection_established':
            health['last_message_time'] = current_time
            health['consecutive_failures'] = 0
            health['is_healthy'] = True
            self.connection_states[stream] = 'connected'
        
        elif event_type == 'connection_failed':
            health['error_count'] += 1
            health['consecutive_failures'] += 1
            health['is_healthy'] = False
            self.connection_states[stream] = 'failed'
        
        elif event_type == 'reconnecting':
            health['reconnect_count'] += 1
            health['last_reconnect_time'] = current_time
            self.connection_states[stream] = 'reconnecting'
        
        # 判断连接是否不健康
        if health['consecutive_failures'] > 3:
            health['is_healthy'] = False
        
        # 检查消息超时
        time_since_last_message = (current_time - health['last_message_time']).total_seconds()
        if time_since_last_message > self.heartbeat_timeout:
            health['is_healthy'] = False
            self.connection_states[stream] = 'timeout'
    
    async def _perform_health_check(self):
        """执行健康检查"""
        current_time = datetime.now()
        
        for stream, health in self.connection_health.items():
            # 检查消息超时
            time_since_last_message = (current_time - health['last_message_time']).total_seconds()
            
            if time_since_last_message > self.heartbeat_timeout:
                logger.warning(f"⚠️ WebSocket连接超时: {stream} (已 {time_since_last_message:.1f} 秒无消息)")
                health['is_healthy'] = False
                self.connection_states[stream] = 'timeout'
                
                # 触发重连
                if self.is_running:
                    asyncio.create_task(self._handle_reconnect(stream))
            
            # 检查连接状态
            conn = self.ws_connections.get(stream)
            if conn and not self._is_connection_alive(conn):
                logger.warning(f"⚠️ WebSocket连接已关闭: {stream}")
                health['is_healthy'] = False
                self.connection_states[stream] = 'closed'
                
                # 触发重连
                if self.is_running:
                    asyncio.create_task(self._handle_reconnect(stream))
    
    async def start(self) -> None:
        """启动WebSocket服务 - 增强版本"""
        if self.is_running:
            logger.warning("⚠️ WebSocket服务已在运行")
            return
        
        self.is_running = True
        logger.info("🚀 启动币安WebSocket服务 (增强版本)")
        
        # 启动后台任务
        tasks = [
            asyncio.create_task(self._heartbeat_task()),
            asyncio.create_task(self._health_monitor_task()),
            asyncio.create_task(self._connection_monitor_task())
        ]
        
        self.background_tasks.extend(tasks)
        
        logger.info("✅ 币安WebSocket服务启动完成，已启动健康监控")
    
    async def stop(self) -> None:
        """停止WebSocket服务 - 增强版本"""
        if not self.is_running:
            return
        
        logger.info("🛑 停止币安WebSocket服务")
        self.is_running = False
        
        # 取消后台任务
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        
        self.background_tasks.clear()
        
        # 关闭所有连接
        for stream_name, ws in self.ws_connections.items():
            try:
                if ws and self._is_connection_alive(ws):
                    await ws.close()
                    logger.debug(f"🔌 关闭连接: {stream_name}")
            except Exception as e:
                logger.warning(f"⚠️ 关闭连接异常: {e}")
        
        # 清理状态
        self.ws_connections.clear()
        self.connection_states.clear()
        self.connection_health.clear()
        self.subscriptions.clear()
        self.subscribed_streams.clear()
        
        logger.info("✅ 币安WebSocket服务已停止")
    
    async def subscribe_symbol_ticker(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的ticker数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream = f"{binance_symbol.lower()}@ticker"
            
            success = await self._subscribe_stream(stream, symbol, callback)
            if success:
                logger.info(f"✅ 订阅ticker成功: {symbol}")
            else:
                logger.error(f"❌ 订阅ticker失败: {symbol}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅{symbol} ticker异常: {e}")
            return False
    
    async def subscribe_symbol_kline(self, symbol: str, interval: str = '1h', 
                                   callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的K线数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream = f"{binance_symbol.lower()}@kline_{interval}"
            
            success = await self._subscribe_stream(stream, symbol, callback)
            if success:
                logger.info(f"✅ 订阅K线成功: {symbol} {interval}")
            else:
                logger.error(f"❌ 订阅K线失败: {symbol} {interval}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅{symbol} K线异常: {e}")
            return False
    
    async def subscribe_symbol_trades(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的交易数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream = f"{binance_symbol.lower()}@aggTrade"
            
            success = await self._subscribe_stream(stream, symbol, callback)
            if success:
                logger.info(f"✅ 订阅交易数据成功: {symbol}")
            else:
                logger.error(f"❌ 订阅交易数据失败: {symbol}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅{symbol}交易数据异常: {e}")
            return False
    
    async def subscribe_symbol_mark_price(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的标记价格和资金费率"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream = f"{binance_symbol.lower()}@markPrice"
            
            success = await self._subscribe_stream(stream, symbol, callback)
            if success:
                logger.info(f"✅ 订阅标记价格成功: {symbol}")
            else:
                logger.error(f"❌ 订阅标记价格失败: {symbol}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅{symbol}标记价格异常: {e}")
            return False
    
    async def subscribe_all_mark_price(self, callback: Optional[Callable] = None) -> bool:
        """订阅所有交易对的标记价格"""
        try:
            stream = "!markPrice@arr"
            
            success = await self._subscribe_stream(stream, "ALL", callback)
            if success:
                logger.info("✅ 订阅所有标记价格成功")
            else:
                logger.error("❌ 订阅所有标记价格失败")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅所有标记价格异常: {e}")
            return False
    
    async def _subscribe_stream(self, stream: str, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅数据流 - 增强版本"""
        try:
            if stream in self.subscribed_streams:
                logger.debug(f"🔄 数据流已订阅: {stream}")
                return True
            
            # 初始化连接健康监控
            await self._initialize_connection_health(stream)
            
            # 创建WebSocket连接
            ws_url = f"{self.ws_base_url}/ws/{stream}"
            
            logger.info(f"🔌 建立WebSocket连接: {stream}")
            
            # 建立连接 - 增强配置
            ws = await websockets.connect(
                ws_url,
                ping_interval=self.ping_interval,
                ping_timeout=15,
                close_timeout=10,
                max_size=2**20,  # 1MB消息大小限制
                compression=None,  # 禁用压缩以提高性能
                open_timeout=self.connection_timeout
            )
            
            # 保存连接
            self.ws_connections[stream] = ws
            self.subscribed_streams.add(stream)
            
            # 保存订阅信息
            subscription = SubscriptionInfo(
                stream=stream,
                symbol=symbol,
                callback=callback,
                last_update=datetime.now()
            )
            self.subscriptions[stream] = subscription
            
            # 更新连接健康状态
            await self._update_connection_health(stream, 'connection_established')
            
            # 启动消息处理任务
            message_task = asyncio.create_task(self._handle_messages(stream, ws))
            self.background_tasks.append(message_task)
            
            logger.info(f"✅ WebSocket连接建立成功: {stream}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 订阅数据流失败: {stream} - {e}")
            await self._update_connection_health(stream, 'connection_failed')
            self.error_stats['connection_errors'] += 1
            self.error_stats['last_error_time'] = datetime.now()
            return False
    
    async def _handle_messages(self, stream: str, ws) -> None:
        """处理WebSocket消息 - 增强版本"""
        try:
            logger.debug(f"🔄 开始处理消息: {stream}")
            
            async for message in ws:
                if not self.is_running:
                    logger.debug(f"🛑 服务已停止，退出消息处理: {stream}")
                    break
                
                try:
                    # 解析JSON消息
                    data = json.loads(message)
                    
                    # 处理消息
                    await self._process_message(stream, data)
                    
                    # 更新连接健康状态
                    await self._update_connection_health(stream, 'message_received', success=True)
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ JSON解析失败 {stream}: {e}")
                    await self._update_connection_health(stream, 'message_received', success=False)
                    self.error_stats['message_errors'] += 1
                    
                except Exception as e:
                    logger.error(f"❌ 处理消息异常 {stream}: {e}")
                    await self._update_connection_health(stream, 'message_received', success=False)
                    self.error_stats['message_errors'] += 1
                    
        except ConnectionClosed as e:
            logger.warning(f"🔌 WebSocket连接关闭: {stream} - {e}")
            await self._update_connection_health(stream, 'connection_failed')
            await self._handle_reconnect(stream)
            
        except WebSocketException as e:
            logger.error(f"❌ WebSocket异常: {stream} - {e}")
            await self._update_connection_health(stream, 'connection_failed')
            self.error_stats['connection_errors'] += 1
            await self._handle_reconnect(stream)
            
        except Exception as e:
            logger.error(f"❌ 消息处理异常: {stream} - {e}")
            await self._update_connection_health(stream, 'connection_failed')
            self.error_stats['connection_errors'] += 1
            await self._handle_reconnect(stream)
            
        finally:
            logger.debug(f"🔚 消息处理结束: {stream}")
            # 清理连接
            if stream in self.ws_connections:
                del self.ws_connections[stream]
            if stream in self.subscribed_streams:
                self.subscribed_streams.remove(stream)
            
            # 更新连接状态
            self.connection_states[stream] = 'disconnected'
    
    async def _process_message(self, stream: str, data: Dict[str, Any]) -> None:
        """处理接收到的消息"""
        try:
            # 更新最后接收时间
            self.last_pong_time = time.time()
            
            # 根据数据类型处理
            if 'e' in data:  # 事件类型
                event_type = data['e']
                
                if event_type == '24hrTicker':
                    await self._process_ticker_data(stream, data)
                elif event_type == 'kline':
                    await self._process_kline_data(stream, data)
                elif event_type == 'aggTrade':
                    await self._process_trade_data(stream, data)
                elif event_type == 'markPriceUpdate':
                    await self._process_mark_price_data(stream, data)
                else:
                    logger.debug(f"🔍 未处理的事件类型: {event_type}")
            
            elif isinstance(data, list):  # 数组数据（如所有标记价格）
                await self._process_array_data(stream, data)
            
            # 调用回调函数
            subscription = self.subscriptions.get(stream)
            if subscription and subscription.callback:
                try:
                    await subscription.callback(data)
                except Exception as e:
                    logger.error(f"❌ 回调函数执行异常: {e}")
            
        except Exception as e:
            logger.error(f"❌ 处理消息异常: {e}")
    
    async def _process_ticker_data(self, stream: str, data: Dict[str, Any]) -> None:
        """处理ticker数据"""
        try:
            symbol = data.get('s', '')
            standard_symbol = self._convert_symbol_from_binance(symbol)
            
            ticker_data = {
                'symbol': standard_symbol,
                'price': float(data.get('c', '0')),
                'volume_24h': float(data.get('v', '0')),
                'change_24h': float(data.get('P', '0')),
                'change_percent_24h': float(data.get('P', '0')),
                'high_24h': float(data.get('h', '0')),
                'low_24h': float(data.get('l', '0')),
                'bid_price': float(data.get('b', '0')),
                'ask_price': float(data.get('a', '0')),
                'timestamp': datetime.fromtimestamp(int(data.get('E', '0')) / 1000),
                'source': 'websocket'
            }
            
            async with self.data_lock:
                self.latest_data[f"ticker_{standard_symbol}"] = ticker_data
            
            logger.debug(f"📊 更新ticker数据: {standard_symbol} = {ticker_data['price']}")
            
        except Exception as e:
            logger.error(f"❌ 处理ticker数据异常: {e}")
    
    async def _process_kline_data(self, stream: str, data: Dict[str, Any]) -> None:
        """处理K线数据"""
        try:
            kline = data.get('k', {})
            symbol = kline.get('s', '')
            standard_symbol = self._convert_symbol_from_binance(symbol)
            
            kline_data = {
                'symbol': standard_symbol,
                'timestamp': int(kline.get('t', '0')),
                'open': float(kline.get('o', '0')),
                'high': float(kline.get('h', '0')),
                'low': float(kline.get('l', '0')),
                'close': float(kline.get('c', '0')),
                'volume': float(kline.get('v', '0')),
                'is_closed': kline.get('x', False),  # K线是否结束
                'source': 'websocket'
            }
            
            async with self.data_lock:
                self.latest_data[f"kline_{standard_symbol}"] = kline_data
            
            if kline_data['is_closed']:
                logger.debug(f"📈 K线结束: {standard_symbol} = {kline_data['close']}")
            
        except Exception as e:
            logger.error(f"❌ 处理K线数据异常: {e}")
    
    async def _process_trade_data(self, stream: str, data: Dict[str, Any]) -> None:
        """处理交易数据"""
        try:
            symbol = data.get('s', '')
            standard_symbol = self._convert_symbol_from_binance(symbol)
            
            trade_data = {
                'symbol': standard_symbol,
                'side': 'buy' if data.get('m', False) else 'sell',
                'size': float(data.get('q', '0')),
                'price': float(data.get('p', '0')),
                'trade_id': str(data.get('a', '')),
                'timestamp': datetime.fromtimestamp(int(data.get('T', '0')) / 1000),
                'source': 'websocket'
            }
            
            async with self.data_lock:
                self.latest_data[f"trade_{standard_symbol}"] = trade_data
            
            logger.debug(f"💰 交易数据: {standard_symbol} {trade_data['side']} {trade_data['size']}@{trade_data['price']}")
            
        except Exception as e:
            logger.error(f"❌ 处理交易数据异常: {e}")
    
    async def _process_mark_price_data(self, stream: str, data: Dict[str, Any]) -> None:
        """处理标记价格数据"""
        try:
            symbol = data.get('s', '')
            standard_symbol = self._convert_symbol_from_binance(symbol)
            
            mark_price_data = {
                'symbol': standard_symbol,
                'mark_price': float(data.get('p', '0')),
                'index_price': float(data.get('i', '0')),
                'funding_rate': float(data.get('r', '0')),
                'next_funding_time': datetime.fromtimestamp(int(data.get('T', '0')) / 1000),
                'timestamp': datetime.fromtimestamp(int(data.get('E', '0')) / 1000),
                'source': 'websocket'
            }
            
            async with self.data_lock:
                self.latest_data[f"mark_price_{standard_symbol}"] = mark_price_data
                # 同时更新资金费率数据
                self.latest_data[f"funding_rate_{standard_symbol}"] = {
                    'symbol': standard_symbol,
                    'funding_rate': mark_price_data['funding_rate'],
                    'next_funding_time': mark_price_data['next_funding_time'],
                    'timestamp': mark_price_data['timestamp'],
                    'source': 'websocket'
                }
            
            logger.debug(f"🏷️ 标记价格: {standard_symbol} = {mark_price_data['mark_price']}, 费率: {mark_price_data['funding_rate']}")
            
        except Exception as e:
            logger.error(f"❌ 处理标记价格数据异常: {e}")
    
    async def _process_array_data(self, stream: str, data: List[Dict[str, Any]]) -> None:
        """处理数组数据（如所有标记价格）"""
        try:
            for item in data:
                if 's' in item:  # 有交易对信息
                    symbol = item.get('s', '')
                    standard_symbol = self._convert_symbol_from_binance(symbol)
                    
                    mark_price_data = {
                        'symbol': standard_symbol,
                        'mark_price': float(item.get('p', '0')),
                        'index_price': float(item.get('i', '0')),
                        'funding_rate': float(item.get('r', '0')),
                        'next_funding_time': datetime.fromtimestamp(int(item.get('T', '0')) / 1000),
                        'timestamp': datetime.now(),
                        'source': 'websocket'
                    }
                    
                    async with self.data_lock:
                        self.latest_data[f"mark_price_{standard_symbol}"] = mark_price_data
                        self.latest_data[f"funding_rate_{standard_symbol}"] = {
                            'symbol': standard_symbol,
                            'funding_rate': mark_price_data['funding_rate'],
                            'next_funding_time': mark_price_data['next_funding_time'],
                            'timestamp': mark_price_data['timestamp'],
                            'source': 'websocket'
                        }
            
            logger.debug(f"📊 批量更新标记价格数据: {len(data)} 个交易对")
            
        except Exception as e:
            logger.error(f"❌ 处理数组数据异常: {e}")
    
    async def _handle_reconnect(self, stream: str) -> None:
        """处理重连 - 指数退避算法"""
        if not self.is_running:
            logger.debug(f"🛑 服务已停止，取消重连: {stream}")
            return
        
        # 更新重连统计
        self.error_stats['reconnection_attempts'] += 1
        await self._update_connection_health(stream, 'reconnecting')
        
        logger.warning(f"🔄 开始重连: {stream}")
        
        base_delay = self.reconnect_config['base_delay']
        max_delay = self.reconnect_config['max_delay']
        multiplier = self.reconnect_config['multiplier']
        jitter = self.reconnect_config['jitter']
        
        for attempt in range(self.max_reconnect_attempts):
            if not self.is_running:
                logger.debug(f"🛑 服务已停止，中断重连: {stream}")
                return
            
            try:
                # 计算延迟时间 - 指数退避
                delay = min(base_delay * (multiplier ** attempt), max_delay)
                
                # 添加随机抖动
                if jitter:
                    import random
                    delay = delay * (0.5 + random.random() * 0.5)
                
                logger.info(f"⏰ 等待 {delay:.1f} 秒后重连 {stream} (尝试 {attempt + 1}/{self.max_reconnect_attempts})")
                await asyncio.sleep(delay)
                
                # 清理旧连接
                if stream in self.ws_connections:
                    old_ws = self.ws_connections[stream]
                    try:
                        if old_ws and self._is_connection_alive(old_ws):
                            await old_ws.close()
                    except Exception as e:
                        logger.debug(f"🔍 关闭旧连接异常: {e}")
                    del self.ws_connections[stream]
                
                if stream in self.subscribed_streams:
                    self.subscribed_streams.remove(stream)
                
                # 获取原订阅信息
                subscription = self.subscriptions.get(stream)
                if not subscription:
                    logger.warning(f"⚠️ 找不到订阅信息: {stream}")
                    return
                
                # 重新订阅
                success = await self._subscribe_stream(
                    subscription.stream,
                    subscription.symbol,
                    subscription.callback
                )
                
                if success:
                    logger.info(f"✅ 重连成功: {stream} (尝试 {attempt + 1} 次)")
                    self.error_stats['successful_reconnections'] += 1
                    return
                else:
                    logger.warning(f"⚠️ 重连失败: {stream} (尝试 {attempt + 1}/{self.max_reconnect_attempts})")
                    
            except Exception as e:
                logger.error(f"❌ 重连异常: {stream} - {e}")
        
        logger.error(f"❌ 重连失败，已达最大尝试次数: {stream}")
        
        # 标记连接为失败状态
        self.connection_states[stream] = 'failed'
        if stream in self.connection_health:
            self.connection_health[stream]['is_healthy'] = False
    
    async def _handle_global_reconnect(self) -> None:
        """处理全局重连 - 重连所有连接"""
        if not self.is_running:
            logger.debug("🛑 服务已停止，取消全局重连")
            return
        
        logger.warning("🔄 开始全局重连所有WebSocket连接")
        
        # 重置心跳时间
        self.last_pong_time = time.time()
        
        # 获取所有活跃的连接流
        active_streams = list(self.ws_connections.keys())
        
        if not active_streams:
            logger.info("📊 没有活跃连接需要重连")
            return
        
        # 并发重连所有流
        reconnect_tasks = []
        for stream in active_streams:
            task = asyncio.create_task(self._handle_reconnect(stream))
            reconnect_tasks.append(task)
        
        # 等待所有重连完成
        try:
            await asyncio.gather(*reconnect_tasks, return_exceptions=True)
            logger.info("✅ 全局重连完成")
        except Exception as e:
            logger.error(f"❌ 全局重连异常: {e}")
    
    async def _heartbeat_task(self) -> None:
        """心跳任务 - 增强版本"""
        logger.debug("💓 启动心跳任务")
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # 检查全局连接状态
                time_since_last_pong = current_time - self.last_pong_time
                if time_since_last_pong > self.heartbeat_timeout:
                    logger.warning(f"⚠️ 长时间未收到数据 ({time_since_last_pong:.1f}秒)，尝试重连")
                    # 触发重连所有连接
                    await self._handle_global_reconnect()
                elif time_since_last_pong > self.heartbeat_timeout * 0.7:  # 84秒时发出预警
                    logger.info(f"🔔 WebSocket连接预警: 已 {time_since_last_pong:.1f}秒未收到数据")
                
                # 更新ping时间
                self.last_ping_time = current_time
                
                # 检查各个连接的心跳
                for stream, conn in self.ws_connections.items():
                    try:
                        if conn and self._is_connection_alive(conn):
                            # WebSocket库会自动处理ping/pong
                            pass
                        else:
                            logger.warning(f"⚠️ 检测到连接异常: {stream}")
                            if self.is_running:
                                asyncio.create_task(self._handle_reconnect(stream))
                    except Exception as e:
                        logger.debug(f"🔍 检查连接心跳异常: {stream} - {e}")
                
                await asyncio.sleep(self.ping_interval)
                
            except Exception as e:
                logger.error(f"❌ 心跳任务异常: {e}")
                await asyncio.sleep(5)
        
        logger.debug("💓 心跳任务结束")
    
    async def _health_monitor_task(self) -> None:
        """健康监控任务"""
        logger.debug("🏥 启动健康监控任务")
        
        while self.is_running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.health_check_interval)
                
            except Exception as e:
                logger.error(f"❌ 健康监控任务异常: {e}")
                await asyncio.sleep(10)
        
        logger.debug("🏥 健康监控任务结束")
    
    async def _connection_monitor_task(self) -> None:
        """连接监控任务"""
        logger.debug("📡 启动连接监控任务")
        
        while self.is_running:
            try:
                # 监控连接状态
                total_connections = len(self.ws_connections)
                active_connections = sum(1 for conn in self.ws_connections.values() 
                                       if conn and self._is_connection_alive(conn))
                
                if total_connections > 0 and active_connections == 0:
                    logger.warning("⚠️ 所有WebSocket连接都已断开")
                
                # 检查错误率
                if self.error_stats['connection_errors'] > 10:
                    logger.warning(f"⚠️ 连接错误率过高: {self.error_stats['connection_errors']} 次")
                
                # 定期重置错误统计
                current_time = datetime.now()
                if (self.error_stats['last_error_time'] and 
                    (current_time - self.error_stats['last_error_time']).total_seconds() > 3600):
                    # 1小时后重置错误统计
                    self.error_stats['connection_errors'] = 0
                    self.error_stats['message_errors'] = 0
                
                await asyncio.sleep(60)  # 每分钟检查一次
                
            except Exception as e:
                logger.error(f"❌ 连接监控任务异常: {e}")
                await asyncio.sleep(10)
        
        logger.debug("📡 连接监控任务结束")
    
    async def get_latest_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新ticker数据"""
        async with self.data_lock:
            return self.latest_data.get(f"ticker_{symbol}")
    
    async def get_latest_kline(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新K线数据"""
        async with self.data_lock:
            return self.latest_data.get(f"kline_{symbol}")
    
    async def get_latest_trade(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新交易数据"""
        async with self.data_lock:
            return self.latest_data.get(f"trade_{symbol}")
    
    async def get_latest_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新资金费率数据"""
        async with self.data_lock:
            return self.latest_data.get(f"funding_rate_{symbol}")
    
    async def get_latest_mark_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新标记价格数据"""
        async with self.data_lock:
            return self.latest_data.get(f"mark_price_{symbol}")
    
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
    
    def get_subscribed_symbols(self) -> List[str]:
        """获取已订阅的交易对列表"""
        symbols = set()
        for subscription in self.subscriptions.values():
            if subscription.symbol != "ALL":
                symbols.add(subscription.symbol)
        return list(symbols)
    
    async def unsubscribe_stream(self, stream: str) -> bool:
        """取消订阅数据流"""
        try:
            if stream in self.ws_connections:
                ws = self.ws_connections[stream]
                if ws and self._is_connection_alive(ws):
                    await ws.close()
                del self.ws_connections[stream]
            
            if stream in self.subscribed_streams:
                self.subscribed_streams.remove(stream)
            
            if stream in self.subscriptions:
                del self.subscriptions[stream]
            
            # 清理健康监控数据
            if stream in self.connection_health:
                del self.connection_health[stream]
            
            if stream in self.connection_states:
                del self.connection_states[stream]
            
            logger.info(f"✅ 取消订阅成功: {stream}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 取消订阅失败: {stream} - {e}")
            return False
    
    def get_health_report(self) -> Dict[str, Any]:
        """获取详细健康报告"""
        current_time = datetime.now()
        
        # 统计健康连接
        healthy_connections = 0
        unhealthy_connections = 0
        
        connection_summary = {}
        for stream, health in self.connection_health.items():
            is_healthy = health.get('is_healthy', False)
            if is_healthy:
                healthy_connections += 1
            else:
                unhealthy_connections += 1
            
            connection_summary[stream] = {
                'healthy': is_healthy,
                'state': self.connection_states.get(stream, 'unknown'),
                'message_count': health.get('message_count', 0),
                'error_count': health.get('error_count', 0),
                'reconnect_count': health.get('reconnect_count', 0),
                'consecutive_failures': health.get('consecutive_failures', 0),
                'last_message_age_seconds': (
                    (current_time - health.get('last_message_time', current_time)).total_seconds()
                    if health.get('last_message_time') else None
                )
            }
        
        return {
            'service_status': {
                'is_running': self.is_running,
                'total_connections': len(self.ws_connections),
                'healthy_connections': healthy_connections,
                'unhealthy_connections': unhealthy_connections,
                'subscriptions_count': len(self.subscriptions)
            },
            'connection_summary': connection_summary,
            'error_statistics': self.error_stats.copy(),
            'configuration': {
                'ping_interval': self.ping_interval,
                'heartbeat_timeout': self.heartbeat_timeout,
                'health_check_interval': self.health_check_interval,
                'max_reconnect_attempts': self.max_reconnect_attempts,
                'reconnect_config': self.reconnect_config.copy()
            },
            'performance_metrics': {
                'total_cached_data': len(self.latest_data),
                'last_ping_time': self.last_ping_time,
                'last_pong_time': self.last_pong_time,
                'time_since_last_pong': current_time.timestamp() - self.last_pong_time
            },
            'report_timestamp': current_time.isoformat()
        }
    
    async def diagnose_connection(self, stream: str) -> Dict[str, Any]:
        """诊断特定连接"""
        if stream not in self.subscriptions:
            return {'error': f'Stream {stream} not found'}
        
        conn = self.ws_connections.get(stream)
        health = self.connection_health.get(stream, {})
        state = self.connection_states.get(stream, 'unknown')
        
        diagnosis = {
            'stream': stream,
            'subscription_info': {
                'symbol': self.subscriptions[stream].symbol,
                'last_update': self.subscriptions[stream].last_update.isoformat() if self.subscriptions[stream].last_update else None
            },
            'connection_status': {
                'exists': conn is not None,
                'alive': self._is_connection_alive(conn) if conn else False,
                'state': state
            },
            'health_metrics': health.copy(),
            'recommendations': []
        }
        
        # 生成诊断建议
        if not health.get('is_healthy', False):
            diagnosis['recommendations'].append('连接不健康，建议重连')
        
        if health.get('consecutive_failures', 0) > 3:
            diagnosis['recommendations'].append('连续失败次数过多，检查网络连接')
        
        if health.get('error_count', 0) > 10:
            diagnosis['recommendations'].append('错误次数过多，检查API配置')
        
        current_time = datetime.now()
        last_message_time = health.get('last_message_time')
        if last_message_time:
            time_since_last = (current_time - last_message_time).total_seconds()
            if time_since_last > self.heartbeat_timeout:
                diagnosis['recommendations'].append(f'长时间无消息 ({time_since_last:.1f}秒)，可能需要重连')
        
        return diagnosis