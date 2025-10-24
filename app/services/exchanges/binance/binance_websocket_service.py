# -*- coding: utf-8 -*-
"""
币安WebSocket服务 - 修复版本
Binance WebSocket Service - Fixed Version with Proxy Support
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import aiohttp
import websockets
from websockets.exceptions import WebSocketException

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
        
        # 合约符号缓存（仅期货合约，避免订阅不存在的合约导致超时）
        self.valid_futures_symbols: Set[str] = set()
        self.symbol_cache_last_update: float = 0.0
        self.symbol_cache_ttl: int = 3600  # 1小时缓存
        self.symbol_cache_lock = asyncio.Lock()

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
            # 转换符号格式（标准 -> Binance）
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@markPrice"
            
            # 期货合约有效性校验（避免订阅现货或不存在的合约）
            is_valid = await self._is_valid_futures_symbol(binance_symbol.upper())
            if not is_valid:
                logger.warning(f"⚠️ 跳过订阅标记价格: {symbol} -> {binance_symbol} 不是有效的USDT合约或已下架")
                return False

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
    
    async def subscribe_symbol_trades(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的聚合交易数据 (aggTrade)"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@aggTrade"
            # 校验期货合约（仅在USDT永续合约场景下需要）
            if binance_symbol.upper().endswith("USDT"):
                valid = await self._is_valid_futures_symbol(binance_symbol.upper())
                if not valid:
                    logger.warning(f"⚠️ 跳过订阅交易: {symbol} 非有效USDT永续合约")
                    return False
            if stream_name in self.subscribed_streams:
                logger.debug(f"💰 {symbol} 交易数据已订阅")
                return True
            success = await self._connect_stream(stream_name)
            if success:
                if callback:
                    self.callbacks.setdefault(stream_name, []).append(callback)
                self.subscriptions[stream_name] = SubscriptionInfo(stream=stream_name, symbol=symbol, callback=callback, last_update=datetime.now())
                self.subscribed_streams.add(stream_name)
                logger.info(f"✅ 成功订阅 {symbol} 交易数据")
                return True
            logger.error(f"❌ 订阅 {symbol} 交易数据失败")
            return False
        except Exception as e:
            logger.error(f"❌ 订阅交易异常: {e}")
            return False

    async def subscribe_symbol_kline(self, symbol: str, interval: str, callback: Optional[Callable] = None) -> bool:
        """订阅单个交易对的K线数据"""
        try:
            binance_symbol = self._convert_symbol_to_binance(symbol)
            stream_name = f"{binance_symbol.lower()}@kline_{interval}"
            if binance_symbol.upper().endswith("USDT"):
                valid = await self._is_valid_futures_symbol(binance_symbol.upper())
                if not valid:
                    logger.warning(f"⚠️ 跳过订阅K线: {symbol} 非有效USDT永续合约")
                    return False
            if stream_name in self.subscribed_streams:
                logger.debug(f"📈 {symbol} {interval} K线已订阅")
                return True
            success = await self._connect_stream(stream_name)
            if success:
                if callback:
                    self.callbacks.setdefault(stream_name, []).append(callback)
                self.subscriptions[stream_name] = SubscriptionInfo(stream=stream_name, symbol=symbol, callback=callback, last_update=datetime.now())
                self.subscribed_streams.add(stream_name)
                logger.info(f"✅ 成功订阅 {symbol} {interval} K线数据")
                return True
            logger.error(f"❌ 订阅 {symbol} {interval} K线失败")
            return False
        except Exception as e:
            logger.error(f"❌ 订阅K线异常: {e}")
            return False

    async def subscribe_all_mark_price(self, callback: Optional[Callable] = None) -> bool:
        """订阅所有USDT永续合约的标记价格 (使用全市场stream)"""
        try:
            # 币安期货支持 wss://fstream.binance.com/ws/!markPrice@arr  返回数组
            stream_name = "!markPrice@arr"
            if stream_name in self.subscribed_streams:
                logger.debug("📊 全市场标记价格已订阅")
                return True
            success = await self._connect_stream(stream_name)
            if success:
                if callback:
                    self.callbacks.setdefault(stream_name, []).append(callback)
                self.subscriptions[stream_name] = SubscriptionInfo(stream=stream_name, symbol="ALL", callback=callback, last_update=datetime.now())
                self.subscribed_streams.add(stream_name)
                logger.info("✅ 成功订阅全市场标记价格数组")
                return True
            logger.error("❌ 订阅全市场标记价格失败")
            return False
        except Exception as e:
            logger.error(f"❌ 订阅全市场标记价格异常: {e}")
            return False

    async def subscribe_multi_mark_price(self, symbols: List[str], callback: Optional[Callable] = None, batch_size: int = 30, delay: float = 0.05) -> Dict[str, bool]:
        """分批通过合并流订阅多个标记价格，减少连接数
        返回: {symbol: success}
        说明: 使用 /stream?streams=... 组合 URL，一次连接多个 stream
        """
        results: Dict[str, bool] = {}
        try:
            # 过滤与转换符号
            converted = [(s, self._convert_symbol_to_binance(s)) for s in symbols]
            # 期货有效性过滤
            valid_pairs = []
            for original, conv in converted:
                if await self._is_valid_futures_symbol(conv.upper()):
                    valid_pairs.append((original, conv))
                else:
                    logger.warning(f"⚠️ 跳过无效合约: {original} -> {conv}")
                    results[original] = False
            # 分批处理
            for i in range(0, len(valid_pairs), batch_size):
                batch = valid_pairs[i:i+batch_size]
                if not batch:
                    continue
                streams = [f"{conv.lower()}@markPrice" for _, conv in batch]
                combined = "/".join(streams)
                ws_url = f"{self.ws_base_url}/stream?streams={combined}"
                logger.debug(f"🔌 合并订阅标记价格: {len(batch)} streams -> {ws_url}")
                try:
                    # 建立连接（不使用单stream的 _connect_stream 以保持独立处理）
                    if self.use_proxy and self.http_session:
                        ws = await self.http_session.ws_connect(ws_url, proxy=self.proxy_url, heartbeat=self.ping_interval, timeout=self.connection_timeout)
                    else:
                        ws = await websockets.connect(ws_url, ping_interval=self.ping_interval, ping_timeout=15, close_timeout=10, max_size=2**20, compression=None, open_timeout=self.connection_timeout)
                    # 保存单一组合连接
                    combined_key = f"combined_markprice_{i//batch_size}"  # 唯一键
                    self.ws_connections[combined_key] = ws
                    self.connection_states[combined_key] = "connected"
                    self.is_connected = True
                    # 为每个子stream登记
                    now = datetime.now()
                    for original, conv in batch:
                        stream_name = f"{conv.lower()}@markPrice"
                        self.subscribed_streams.add(stream_name)
                        self.subscriptions[stream_name] = SubscriptionInfo(stream=stream_name, symbol=original, callback=callback, last_update=now)
                        results[original] = True
                    # 消息处理任务
                    message_task = asyncio.create_task(self._handle_messages_combined_mark_price(ws, batch, callback))
                    self.background_tasks.append(message_task)
                    logger.info(f"✅ 合并订阅成功: {len(batch)} 标记价格 streams")
                except Exception as e:
                    logger.error(f"❌ 合并订阅失败 (batch {i//batch_size}): {e}")
                    for original, _ in batch:
                        results[original] = False
                await asyncio.sleep(delay)
        except Exception as e:
            logger.error(f"❌ subscribe_multi_mark_price 异常: {e}")
        return results

    async def _handle_messages_combined_mark_price(self, ws, batch: List[tuple], callback: Optional[Callable]) -> None:
        """处理合并标记价格连接的消息 (返回 JSON {'stream': 'xxx', 'data': {...}})"""
        try:
            async for message in ws:
                if not self.is_running:
                    break
                try:
                    payload = json.loads(message) if isinstance(message, (str, bytes)) else message
                    stream = payload.get('stream')
                    data = payload.get('data')
                    if not stream or not data:
                        continue
                    # 直接使用单stream处理逻辑
                    await self._process_message(stream, data)
                    # 回调（统一回调每个标记价格）
                    if callback:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(data)
                        else:
                            callback(data)
                except Exception as e:
                    logger.error(f"❌ 合并标记价格消息处理异常: {e}")
        except Exception as e:
            logger.error(f"❌ 合并标记价格连接异常: {e}")
        finally:
            logger.debug("🔄 合并标记价格消息处理结束")

    async def _is_valid_futures_symbol(self, binance_symbol: str) -> bool:
        """检查是否为有效的USDT永续合约符号（使用缓存避免频繁请求）"""
        try:
            if not binance_symbol.endswith("USDT"):
                return False
            now = time.time()
            if (now - self.symbol_cache_last_update) > self.symbol_cache_ttl or not self.valid_futures_symbols:
                await self._refresh_futures_symbol_cache()
            return binance_symbol in self.valid_futures_symbols
        except Exception as e:
            logger.warning(f"⚠️ 合约符号校验异常 {binance_symbol}: {e}")
            return False

    async def _refresh_futures_symbol_cache(self) -> None:
        """刷新期货合约符号缓存"""
        async with self.symbol_cache_lock:
            try:
                base_url = "https://fapi.binance.com" if not self.testnet else "https://testnet.binancefuture.com"
                endpoint = f"{base_url}/fapi/v1/exchangeInfo"
                logger.debug("🔄 刷新期货合约符号缓存...")

                if not self.http_session:
                    await self._create_http_session()

                async with self.http_session.get(endpoint, proxy=self.proxy_url if self.use_proxy else None, timeout=30) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️ 获取期货合约信息失败 HTTP {resp.status}")
                        return
                    data = await resp.json()
                    symbols = data.get("symbols", [])
                    futures_symbols = set()
                    for item in symbols:
                        try:
                            if item.get("contractType") == "PERPETUAL" and item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT":
                                futures_symbols.add(item.get("symbol"))
                        except Exception:
                            continue
                    if futures_symbols:
                        self.valid_futures_symbols = futures_symbols
                        self.symbol_cache_last_update = time.time()
                        logger.info(f"✅ 期货合约缓存刷新完成, 有效USDT永续合约数量: {len(futures_symbols)}")
                    else:
                        logger.warning("⚠️ 期货合约缓存刷新未获取到有效合约列表")
            except Exception as e:
                logger.error(f"❌ 刷新期货合约符号缓存失败: {e}")

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
            
        except asyncio.TimeoutError:
            logger.error(f"⏱️ 连接数据流超时 {stream_name}: 打开握手未在 {self.connection_timeout}s 内完成")
            self.connection_states[stream_name] = "timeout"
            return False
        except WebSocketException as e:
            logger.error(f"❌ WebSocket协议异常 {stream_name}: {e}")
            self.connection_states[stream_name] = "failed"
            return False
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