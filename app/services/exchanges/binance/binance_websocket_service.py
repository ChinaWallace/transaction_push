# -*- coding: utf-8 -*-
"""
币安WebSocket服务 - 修复版本
Binance WebSocket Service - Fixed Version with Proxy Support
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Callable, Set, Union
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import aiohttp
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
    FUNDING_RATE = "markPrice"


@dataclass
class SubscriptionInfo:
    """订阅信息"""
    stream: str
    symbol: str
    callback: Optional[Callable[..., Any]] = None
    last_update: Optional[datetime] = None


class BinanceWebSocketService:
    """币安WebSocket服务类 - 支持代理连接"""
    
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
        
        # 连接管理
        self.ws_connections: Dict[str, Any] = {}
        self.connection_states: Dict[str, str] = {}
        self.is_running = False
        self.is_connected = False  # 添加缺失的属性
        self.reconnect_interval = 5
        self.max_reconnect_attempts = 10
        
        # HTTP会话管理（用于WebSocket代理连接）
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.use_proxy = hasattr(settings, 'proxy_enabled') and settings.proxy_enabled and hasattr(settings, 'proxy_url')
        self.proxy_url = getattr(settings, 'proxy_url', None) if self.use_proxy else None
        
        # 连接健康监控
        self.connection_health: Dict[str, Dict[str, Any]] = {}
        self.health_check_interval = 30
        self.connection_timeout = 30
        
        # 订阅管理
        self.subscriptions: Dict[str, SubscriptionInfo] = {}
        self.callbacks: Dict[str, List[Callable[..., Any]]] = {}
        self.subscribed_streams: Set[str] = set()
        
        # 数据缓存
        self.latest_data: Dict[str, Dict[str, Any]] = {}
        self.data_lock = asyncio.Lock()
        
        # 心跳管理
        self.last_ping_time = time.time()
        self.ping_interval = 20
        self.last_pong_time = time.time()
        self.heartbeat_timeout = 120
        
        # 后台任务
        self.background_tasks: List[asyncio.Task[Any]] = []
        
        # 错误统计
        self.error_stats = {
            'connection_errors': 0,
            'message_errors': 0,
            'reconnect_attempts': 0
        }
        
        logger.info(f"🔧 币安WebSocket服务初始化完成")
        if self.use_proxy:
            logger.info(f"🔌 已配置代理: {self.proxy_url}")
        else:
            logger.info("📡 使用直连模式")
    
    async def start(self) -> None:
        """启动WebSocket服务"""
        if self.is_running:
            logger.warning("⚠️ WebSocket服务已在运行")
            return
        
        logger.info("🚀 启动币安WebSocket服务")
        self.is_running = True
        self.is_connected = False  # 初始化连接状态
        
        try:
            # 创建HTTP会话
            await self._create_http_session()
            
            # 启动健康监控
            health_task = asyncio.create_task(self._health_monitor())
            self.background_tasks.append(health_task)
            
            logger.info("✅ 币安WebSocket服务启动完成")
            
        except Exception as e:
            logger.error(f"❌ 启动WebSocket服务失败: {e}")
            self.is_running = False
            raise
    
    async def _create_http_session(self) -> None:
        """创建HTTP会话（支持代理）"""
        try:
            if self.http_session:
                await self.http_session.close()
            
            # 创建连接器
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60,
                enable_cleanup_closed=True
            )
            
            # 创建会话
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
            
            if self.use_proxy:
                logger.info(f"🔌 WebSocket会话已配置代理: {self.proxy_url}")
            else:
                logger.info("🔌 WebSocket会话使用直连模式")
                
        except Exception as e:
            logger.error(f"❌ 创建HTTP会话失败: {e}")
            raise
    
    async def stop(self) -> None:
        """停止WebSocket服务"""
        if not self.is_running:
            return
        
        logger.info("🛑 停止币安WebSocket服务")
        self.is_running = False
        self.is_connected = False
        
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
        
        # 关闭HTTP会话
        if self.http_session:
            await self.http_session.close()
            self.http_session = None
        
        # 清理状态
        self.ws_connections.clear()
        self.connection_states.clear()
        self.connection_health.clear()
        self.subscriptions.clear()
        self.subscribed_streams.clear()
        
        logger.info("✅ 币安WebSocket服务已停止")
    
    def _convert_symbol_to_binance(self, symbol: str) -> str:
        """将标准符号转换为币安期货格式"""
        try:
            if '-USDT-SWAP' in symbol:
                return symbol.replace('-USDT-SWAP', 'USDT')
            elif '-USD-SWAP' in symbol:
                return symbol.replace('-USD-SWAP', 'USD')
            elif '-' in symbol:
                # 处理其他格式，如 BTC-USDT -> BTCUSDT
                return symbol.replace('-', '')
            return symbol
        except Exception as e:
            logger.error(f"❌ 符号转换失败: {symbol} -> {e}")
            return symbol

    async def subscribe_ticker(self, symbol: str, callback: Optional[Callable[..., Any]] = None) -> bool:
        """订阅价格数据"""
        try:
            # 转换符号格式
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@ticker"
            
            if stream_name in self.subscribed_streams:
                logger.debug(f"📊 {symbol} ticker已订阅")
                return True
            
            # 建立连接
            success = await self._connect_stream(stream_name)
            if success:
                # 注册回调
                if callback:
                    if stream_name not in self.callbacks:
                        self.callbacks[stream_name] = []
                    self.callbacks[stream_name].append(callback)
                
                # 记录订阅
                self.subscriptions[stream_name] = SubscriptionInfo(
                    stream=stream_name,
                    symbol=symbol,
                    callback=callback,
                    last_update=datetime.now()
                )
                
                self.subscribed_streams.add(stream_name)
                logger.info(f"✅ 成功订阅 {symbol} ticker数据")
                return True
            else:
                logger.error(f"❌ 订阅 {symbol} ticker失败")
                return False
                
        except Exception as e:
            logger.error(f"❌ 订阅ticker异常: {e}")
            return False
    
    async def subscribe_symbol_ticker(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的ticker数据 - 兼容方法"""
        return await self.subscribe_ticker(symbol, callback)
    
    async def subscribe_symbol_mark_price(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的标记价格数据"""
        try:
            # 转换符号格式
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@markPrice"
            
            if stream_name in self.subscribed_streams:
                logger.debug(f"📊 {symbol} 标记价格已订阅")
                return True
            
            # 建立连接
            success = await self._connect_stream(stream_name)
            if success:
                # 注册回调
                if callback:
                    if stream_name not in self.callbacks:
                        self.callbacks[stream_name] = []
                    self.callbacks[stream_name].append(callback)
                
                # 记录订阅
                self.subscriptions[stream_name] = SubscriptionInfo(
                    stream=stream_name,
                    symbol=symbol,
                    callback=callback,
                    last_update=datetime.now()
                )
                
                self.subscribed_streams.add(stream_name)
                logger.info(f"✅ 成功订阅 {symbol} 标记价格数据")
                return True
            else:
                logger.error(f"❌ 订阅 {symbol} 标记价格失败")
                return False
                
        except Exception as e:
            logger.error(f"❌ 订阅标记价格异常: {e}")
            return False
    
    async def _connect_stream(self, stream_name: str) -> bool:
        """连接数据流"""
        try:
            ws_url = f"{self.ws_base_url}/ws/{stream_name}"
            logger.debug(f"🔌 连接数据流: {ws_url}")
            
            # 建立连接 - 支持代理
            if self.use_proxy and self.http_session:
                # 使用aiohttp WebSocket客户端（支持代理）
                logger.debug(f"🔌 通过代理建立WebSocket连接: {self.proxy_url}")
                ws = await self.http_session.ws_connect(
                    ws_url,
                    proxy=self.proxy_url,
                    heartbeat=self.ping_interval,
                    timeout=self.connection_timeout
                )
            else:
                # 使用websockets库（直连）
                logger.debug("🔌 直连建立WebSocket连接")
                ws = await websockets.connect(
                    ws_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=15,
                    close_timeout=10,
                    max_size=2**20,
                    compression=None,
                    open_timeout=self.connection_timeout
                )
            
            # 保存连接
            self.ws_connections[stream_name] = ws
            self.connection_states[stream_name] = "connected"
            
            # 更新连接状态
            self.is_connected = True
            
            # 启动消息处理任务
            message_task = asyncio.create_task(self._handle_messages(stream_name, ws))
            self.background_tasks.append(message_task)
            
            logger.info(f"✅ 成功连接数据流: {stream_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 连接数据流失败 {stream_name}: {e}")
            self.connection_states[stream_name] = "failed"
            return False
    
    async def _handle_messages(self, stream: str, ws) -> None:
        """处理WebSocket消息"""
        try:
            logger.debug(f"🔄 开始处理消息: {stream}")
            
            # 检查连接类型并相应处理消息
            if hasattr(ws, 'receive'):
                # aiohttp WebSocket连接
                await self._handle_aiohttp_messages(stream, ws)
            else:
                # websockets库连接
                await self._handle_websockets_messages(stream, ws)
        
        except Exception as e:
            logger.error(f"❌ 消息处理异常 {stream}: {e}")
            await self._update_connection_health(stream, 'message_processing', success=False)
            self.error_stats['connection_errors'] += 1
        
        finally:
            logger.debug(f"🔄 消息处理结束: {stream}")
    
    async def _handle_aiohttp_messages(self, stream: str, ws) -> None:
        """处理aiohttp WebSocket消息"""
        try:
            async for msg in ws:
                if not self.is_running:
                    logger.debug(f"🛑 服务已停止，退出消息处理: {stream}")
                    break
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        # 解析JSON消息
                        data = json.loads(msg.data)
                        
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
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"❌ WebSocket错误 {stream}: {ws.exception()}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.warning(f"🔌 WebSocket连接关闭 {stream}")
                    break
                    
        except Exception as e:
            logger.error(f"❌ aiohttp消息处理异常 {stream}: {e}")
            raise
    
    async def _handle_websockets_messages(self, stream: str, ws) -> None:
        """处理websockets库消息"""
        try:
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
                    
        except Exception as e:
            logger.error(f"❌ websockets消息处理异常 {stream}: {e}")
            raise
    
    async def _process_message(self, stream: str, data: Dict[str, Any]) -> None:
        """处理接收到的消息"""
        try:
            # 缓存最新数据
            async with self.data_lock:
                self.latest_data[stream] = data
            
            # 调用回调函数
            if stream in self.callbacks:
                for callback in self.callbacks[stream]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(data)
                        else:
                            callback(data)
                    except Exception as e:
                        logger.error(f"❌ 回调函数执行异常: {e}")
            
            # 更新订阅信息
            if stream in self.subscriptions:
                self.subscriptions[stream].last_update = datetime.now()
            
            logger.debug(f"📨 处理消息完成: {stream}")
            
        except Exception as e:
            logger.error(f"❌ 处理消息异常: {e}")
            raise
    
    async def _update_connection_health(self, stream: str, event: str, success: bool = True) -> None:
        """更新连接健康状态"""
        try:
            if stream not in self.connection_health:
                self.connection_health[stream] = {
                    'last_message': None,
                    'message_count': 0,
                    'error_count': 0,
                    'last_error': None,
                    'connected_at': datetime.now(),
                    'status': 'healthy'
                }
            
            health = self.connection_health[stream]
            
            if success:
                health['last_message'] = datetime.now()
                health['message_count'] += 1
                health['status'] = 'healthy'
            else:
                health['error_count'] += 1
                health['last_error'] = datetime.now()
                if health['error_count'] > 5:
                    health['status'] = 'unhealthy'
                    
        except Exception as e:
            logger.error(f"❌ 更新连接健康状态异常: {e}")
    
    def _is_connection_alive(self, conn) -> bool:
        """检查WebSocket连接是否存活"""
        try:
            # 检查aiohttp WebSocket连接
            if hasattr(conn, 'closed') and callable(conn.closed):
                return not conn.closed
            elif hasattr(conn, 'closed'):
                return not conn.closed
            # 检查websockets库连接
            elif hasattr(conn, 'state'):
                from websockets.protocol import State
                return conn.state == State.OPEN
            elif hasattr(conn, 'open'):
                return conn.open
            else:
                return True
        except Exception as e:
            logger.debug(f"🔍 检查连接状态异常: {e}")
            return False
    
    async def _health_monitor(self) -> None:
        """健康监控任务"""
        while self.is_running:
            try:
                await asyncio.sleep(self.health_check_interval)
                
                if not self.is_running:
                    break
                
                # 检查所有连接健康状态
                for stream_name in list(self.ws_connections.keys()):
                    ws = self.ws_connections.get(stream_name)
                    if not ws or not self._is_connection_alive(ws):
                        logger.warning(f"⚠️ 检测到连接异常: {stream_name}")
                        # 这里可以添加重连逻辑
                
                logger.debug("💓 健康检查完成")
                
            except Exception as e:
                logger.error(f"❌ 健康监控异常: {e}")
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取最新ticker数据"""
        try:
            # 转换符号格式
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@ticker"
            async with self.data_lock:
                return self.latest_data.get(stream_name)
        except Exception as e:
            logger.error(f"❌ 获取ticker数据异常: {e}")
            return None
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        try:
            total_connections = len(self.ws_connections)
            active_connections = sum(
                1 for ws in self.ws_connections.values() 
                if self._is_connection_alive(ws)
            )
            
            return {
                "connected": self.is_connected,
                "is_running": self.is_running,
                "total_connections": total_connections,
                "active_connections": active_connections,
                "subscribed_streams": len(self.subscribed_streams),
                "use_proxy": self.use_proxy,
                "proxy_url": self.proxy_url if self.use_proxy else None,
                "error_stats": self.error_stats.copy(),
                "last_ping_time": self.last_ping_time,
                "last_pong_time": self.last_pong_time
            }
        except Exception as e:
            logger.error(f"❌ 获取连接状态异常: {e}")
            return {
                "connected": False,
                "error": str(e)
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """服务健康检查"""
        try:
            total_connections = len(self.ws_connections)
            active_connections = sum(
                1 for ws in self.ws_connections.values() 
                if self._is_connection_alive(ws)
            )
            
            return {
                "status": "healthy" if self.is_running and active_connections > 0 else "unhealthy",
                "is_running": self.is_running,
                "total_connections": total_connections,
                "active_connections": active_connections,
                "subscribed_streams": len(self.subscribed_streams),
                "use_proxy": self.use_proxy,
                "proxy_url": self.proxy_url if self.use_proxy else None,
                "error_stats": self.error_stats.copy(),
                "connection_health": {
                    stream: {
                        "status": health.get("status", "unknown"),
                        "message_count": health.get("message_count", 0),
                        "error_count": health.get("error_count", 0),
                        "last_message": health.get("last_message").isoformat() if health.get("last_message") and hasattr(health.get("last_message"), 'isoformat') else None
                    }
                    for stream, health in self.connection_health.items()
                }
            }
        except Exception as e:
            logger.error(f"❌ 健康检查异常: {e}")
            return {
                "status": "error",
                "error": str(e)
            }


# 全局服务实例
_binance_websocket_service: Optional[BinanceWebSocketService] = None

async def get_binance_websocket_service() -> BinanceWebSocketService:
    """获取币安WebSocket服务实例"""
    global _binance_websocket_service
    if _binance_websocket_service is None:
        _binance_websocket_service = BinanceWebSocketService()
    return _binance_websocket_service