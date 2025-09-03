# -*- coding: utf-8 -*-
"""
OKX WebSocket服务
OKX WebSocket Service - 提供高效的实时数据流服务
"""

import asyncio
import json
import time
import hmac
import hashlib
import base64
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class ChannelType(Enum):
    """频道类型枚举"""
    TICKER = "tickers"
    KLINE = "candle"
    TRADES = "trades"
    ORDER_BOOK = "books"
    FUNDING_RATE = "funding-rate"
    OPEN_INTEREST = "open-interest"
    ACCOUNT = "account"
    POSITIONS = "positions"
    ORDERS = "orders"


@dataclass
class SubscriptionInfo:
    """订阅信息"""
    channel: str
    inst_id: str
    callback: Optional[Callable] = None
    last_update: Optional[datetime] = None


class OKXWebSocketService:
    """OKX WebSocket服务类"""
    
    def __init__(self):
        self.config = settings.okx_config
        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.passphrase = self.config["passphrase"]
        self.sandbox = self.config["sandbox"]
        
        # WebSocket端点 - 根据官方文档修正
        if self.sandbox:
            self.public_ws_url = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
            self.private_ws_url = "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999"
            self.business_ws_url = "wss://wspap.okx.com:8443/ws/v5/business?brokerId=9999"
        else:
            self.public_ws_url = "wss://ws.okx.com:8443/ws/v5/public"
            self.private_ws_url = "wss://ws.okx.com:8443/ws/v5/private"
            self.business_ws_url = "wss://ws.okx.com:8443/ws/v5/business"
        
        # 连接管理
        self.public_ws = None
        self.private_ws = None
        self.is_running = False
        self.reconnect_interval = 5
        self.max_reconnect_attempts = 10
        
        # 连接状态标志
        self._public_connected = False
        self._private_connected = False
        
        # 订阅管理
        self.subscriptions: Dict[str, SubscriptionInfo] = {}
        self.callbacks: Dict[str, List[Callable]] = {}
        
        # 数据缓存
        self.latest_data: Dict[str, Dict[str, Any]] = {}
        self.data_lock = asyncio.Lock()
        
        # 心跳管理
        current_time = time.time()
        self.last_ping_time = current_time
        self.ping_interval = 20  # 20秒发送一次ping，比OKX的30秒超时更频繁
        self.last_pong_time = current_time  # 记录最后收到pong的时间
        
        logger.info("🔌 OKX WebSocket服务初始化完成")

    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        current_time = time.time()
        
        return {
            "is_running": self.is_running,
            "public_connected": self.is_public_connected(),
            "private_connected": self.is_private_connected(),
            "last_ping_time": self.last_ping_time,
            "last_pong_time": self.last_pong_time,
            "ping_interval": self.ping_interval,
            "time_since_last_pong": current_time - self.last_pong_time,
            "subscriptions_count": len(self.subscriptions),
            "cached_data_count": len(self.latest_data)
        }

    async def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """等待WebSocket连接建立"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_public_connected():
                return True
            await asyncio.sleep(0.1)
        
        return False

    def is_public_connected(self) -> bool:
        """检查公共WebSocket是否已连接"""
        if not self._public_connected or self.public_ws is None:
            return False
        
        # 检查WebSocket连接状态 - 兼容不同的websockets库版本
        try:
            # 优先检查state属性（更可靠）
            if hasattr(self.public_ws, 'state'):
                try:
                    from websockets.protocol import State
                    return self.public_ws.state == State.OPEN
                except (ImportError, AttributeError):
                    pass
            
            # 检查closed属性
            if hasattr(self.public_ws, 'closed'):
                return not self.public_ws.closed
            
            # 检查close_code属性
            if hasattr(self.public_ws, 'close_code'):
                return self.public_ws.close_code is None
            
            # 如果都没有，依赖标志位
            return self._public_connected
            
        except Exception as e:
            logger.debug(f"🔍 检查WebSocket状态异常: {e}")
            return self._public_connected

    def is_private_connected(self) -> bool:
        """检查私有WebSocket是否已连接"""
        if not self._private_connected or self.private_ws is None:
            return False
        
        # 检查WebSocket连接状态 - 兼容不同的websockets库版本
        try:
            # 优先检查state属性（更可靠）
            if hasattr(self.private_ws, 'state'):
                try:
                    from websockets.protocol import State
                    return self.private_ws.state == State.OPEN
                except (ImportError, AttributeError):
                    pass
            
            # 检查closed属性
            if hasattr(self.private_ws, 'closed'):
                return not self.private_ws.closed
            
            # 检查close_code属性
            if hasattr(self.private_ws, 'close_code'):
                return self.private_ws.close_code is None
            
            # 如果都没有，依赖标志位
            return self._private_connected
            
        except Exception as e:
            logger.debug(f"🔍 检查WebSocket状态异常: {e}")
            return self._private_connected

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成签名"""
        message = timestamp + method.upper() + request_path + body
        signature = base64.b64encode(
            hmac.new(
                self.secret_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        return signature

    def _get_auth_message(self) -> Dict[str, Any]:
        """获取认证消息"""
        # 使用Unix时间戳（秒）
        timestamp = str(int(time.time()))
        signature = self._generate_signature(timestamp, 'GET', '/users/self/verify', '')
        
        return {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }

    async def start(self):
        """启动WebSocket服务"""
        if self.is_running:
            logger.warning("⚠️ WebSocket服务已在运行")
            return
        
        self.is_running = True
        logger.info("🚀 启动OKX WebSocket服务...")
        
        # 启动公共连接
        public_task = asyncio.create_task(self._maintain_public_connection())
        
        # 启动私有连接（如果需要）
        private_task = None
        if self.api_key and self.secret_key:
            private_task = asyncio.create_task(self._maintain_private_connection())
        
        # 启动心跳任务
        asyncio.create_task(self._heartbeat_task())
        
        # 等待连接建立 - 最多等待15秒，使用更严格的检查
        logger.info("⏳ 等待WebSocket连接建立...")
        connection_established = await self.wait_for_connection(timeout=15.0)
        
        if connection_established:
            logger.info("✅ 公共WebSocket连接已建立")
            # 连接建立后再等待一小段时间确保稳定
            await asyncio.sleep(1.0)
        else:
            logger.warning("⚠️ WebSocket连接建立超时，但服务将继续运行")
        
        logger.info("✅ OKX WebSocket服务启动成功")

    async def stop(self):
        """停止WebSocket服务"""
        logger.info("🛑 停止OKX WebSocket服务...")
        self.is_running = False
        
        # 关闭连接
        try:
            if self.public_ws:
                await self.public_ws.close()
        except Exception as e:
            logger.debug(f"关闭公共连接异常: {e}")
        
        try:
            if self.private_ws:
                await self.private_ws.close()
        except Exception as e:
            logger.debug(f"关闭私有连接异常: {e}")
        
        # 重置连接状态
        self._public_connected = False
        self._private_connected = False
        self.public_ws = None
        self.private_ws = None
        
        # 清理数据
        self.subscriptions.clear()
        self.callbacks.clear()
        self.latest_data.clear()
        
        logger.info("✅ OKX WebSocket服务已停止")

    async def _maintain_public_connection(self):
        """维护公共连接"""
        reconnect_count = 0
        
        while self.is_running:
            try:
                logger.info("🔗 连接OKX公共WebSocket...")
                
                async with websockets.connect(
                    self.public_ws_url,
                    ping_interval=None,  # 手动管理ping
                    ping_timeout=None,   # 禁用自动ping超时
                    close_timeout=10,
                    max_size=2**20       # 1MB消息大小限制
                ) as websocket:
                    self.public_ws = websocket
                    self._public_connected = True
                    reconnect_count = 0
                    logger.info("✅ OKX公共WebSocket连接成功")
                    
                    # 等待一小段时间确保连接稳定
                    await asyncio.sleep(0.5)
                    
                    # 重新订阅所有公共频道
                    if self.subscriptions:
                        logger.info(f"🔄 重新订阅 {len(self.subscriptions)} 个频道...")
                        await self._resubscribe_public_channels()
                    
                    # 处理消息
                    await self._handle_public_messages(websocket)
                    
            except (ConnectionClosed, WebSocketException) as e:
                logger.warning(f"⚠️ 公共WebSocket连接断开: {e}")
            except Exception as e:
                logger.error(f"❌ 公共WebSocket连接异常: {e}")
            finally:
                # 连接断开时重置状态
                self._public_connected = False
                self.public_ws = None
            
            if self.is_running:
                reconnect_count += 1
                if reconnect_count <= self.max_reconnect_attempts:
                    wait_time = min(self.reconnect_interval * reconnect_count, 60)
                    logger.info(f"🔄 {wait_time}秒后重连公共WebSocket (第{reconnect_count}次)")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("❌ 公共WebSocket重连次数超限，停止重连")
                    break

    async def _maintain_private_connection(self):
        """维护私有连接"""
        reconnect_count = 0
        
        while self.is_running:
            try:
                logger.info("🔗 连接OKX私有WebSocket...")
                
                async with websockets.connect(
                    self.private_ws_url,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=10,
                    max_size=2**20
                ) as websocket:
                    self.private_ws = websocket
                    reconnect_count = 0
                    
                    # 发送认证消息
                    auth_msg = self._get_auth_message()
                    await websocket.send(json.dumps(auth_msg))
                    
                    # 等待认证响应
                    auth_response = await websocket.recv()
                    auth_data = json.loads(auth_response)
                    
                    if auth_data.get('event') == 'login' and auth_data.get('code') == '0':
                        self._private_connected = True
                        logger.info("✅ OKX私有WebSocket认证成功")
                        
                        # 重新订阅所有私有频道
                        await self._resubscribe_private_channels()
                        
                        # 处理消息
                        await self._handle_private_messages(websocket)
                    else:
                        logger.error(f"❌ OKX私有WebSocket认证失败: {auth_data}")
                        
            except (ConnectionClosed, WebSocketException) as e:
                logger.warning(f"⚠️ 私有WebSocket连接断开: {e}")
            except Exception as e:
                logger.error(f"❌ 私有WebSocket连接异常: {e}")
            finally:
                # 连接断开时重置状态
                self._private_connected = False
                self.private_ws = None
            
            if self.is_running:
                reconnect_count += 1
                if reconnect_count <= self.max_reconnect_attempts:
                    wait_time = min(self.reconnect_interval * reconnect_count, 60)
                    logger.info(f"🔄 {wait_time}秒后重连私有WebSocket (第{reconnect_count}次)")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("❌ 私有WebSocket重连次数超限，停止重连")
                    break

    async def _handle_public_messages(self, websocket):
        """处理公共消息"""
        try:
            async for message in websocket:
                try:
                    # 处理字符串消息（如pong）
                    if isinstance(message, str) and message == "pong":
                        await self._process_message(message, is_private=False)
                        continue
                    
                    # 处理JSON消息
                    data = json.loads(message)
                    await self._process_message(data, is_private=False)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ 解析公共消息失败: {message[:100]}... - {e}")
                except Exception as e:
                    logger.error(f"❌ 处理公共消息异常: {e}")
        except ConnectionClosed as e:
            logger.info(f"🔌 公共WebSocket连接已关闭: {e}")
        except WebSocketException as e:
            logger.warning(f"⚠️ 公共WebSocket异常: {e}")
        except Exception as e:
            logger.error(f"❌ 公共消息处理循环异常: {e}")

    async def _handle_private_messages(self, websocket):
        """处理私有消息"""
        try:
            async for message in websocket:
                try:
                    # 处理字符串消息（如pong）
                    if isinstance(message, str) and message == "pong":
                        await self._process_message(message, is_private=True)
                        continue
                    
                    # 处理JSON消息
                    data = json.loads(message)
                    await self._process_message(data, is_private=True)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ 解析私有消息失败: {message[:100]}... - {e}")
                except Exception as e:
                    logger.error(f"❌ 处理私有消息异常: {e}")
        except ConnectionClosed as e:
            logger.info(f"🔌 私有WebSocket连接已关闭: {e}")
        except WebSocketException as e:
            logger.warning(f"⚠️ 私有WebSocket异常: {e}")
        except Exception as e:
            logger.error(f"❌ 私有消息处理循环异常: {e}")

    def _normalize_symbol(self, inst_id: str) -> str:
        """
        标准化交易对名称 - 直接返回原始名称
        Normalize symbol name - return original name as-is
        """
        return inst_id

    async def _process_message(self, data: Dict[str, Any], is_private: bool = False):
        """处理WebSocket消息"""
        try:
            # 处理字符串消息（如pong）
            if isinstance(data, str):
                if data == "pong":
                    self.last_pong_time = time.time()
                    logger.debug("💓 收到pong响应")
                return
            
            # 处理事件消息
            if 'event' in data:
                event = data['event']
                if event == 'subscribe':
                    logger.debug(f"✅ 订阅成功: {data}")
                elif event == 'unsubscribe':
                    logger.debug(f"✅ 取消订阅成功: {data}")
                elif event == 'error':
                    error_msg = data.get('msg', '未知错误')
                    error_code = data.get('code', '未知代码')
                    
                    # 特殊处理无效交易对错误 - 增强错误处理逻辑
                    if 'doesn\'t exist' in error_msg or error_code == '60018':
                        # 从错误消息中提取交易对信息
                        if 'instId:' in error_msg:
                            invalid_symbol = error_msg.split('instId:')[1].split(' ')[0].strip()
                            logger.warning(f"⚠️ 交易对订阅失败: {invalid_symbol} - {error_msg}")
                            
                            # 检查是否是临时错误，不立即移除订阅
                            # 只有在多次失败后才移除
                            if not hasattr(self, '_subscription_failures'):
                                self._subscription_failures = {}
                            
                            # 记录失败次数
                            failure_key = invalid_symbol
                            self._subscription_failures[failure_key] = self._subscription_failures.get(failure_key, 0) + 1
                            
                            # 增加失败阈值到5次，给更多重试机会
                            if self._subscription_failures[failure_key] >= 5:
                                logger.error(f"❌ 交易对 {invalid_symbol} 连续失败 {self._subscription_failures[failure_key]} 次，标记为问题交易对")
                                
                                # 不立即移除订阅，而是标记为有问题的交易对
                                if not hasattr(self, '_problematic_symbols'):
                                    self._problematic_symbols = set()
                                self._problematic_symbols.add(invalid_symbol)
                                
                                # 记录问题交易对，但保留订阅信息以便后续重试
                                logger.warning(f"⚠️ 将 {invalid_symbol} 标记为问题交易对，将在重连时重试")
                                
                                # 清理失败记录，给重连时重新机会
                                self._subscription_failures.pop(failure_key, None)
                            else:
                                logger.info(f"🔄 交易对 {invalid_symbol} 订阅失败 {self._subscription_failures[failure_key]} 次，稍后重试")
                        else:
                            logger.error(f"❌ WebSocket错误: {data}")
                    else:
                        # 只记录真正的错误，忽略一些常见的非关键错误
                        if error_code not in ['60012', '60013']:  # 忽略一些常见的非关键错误码
                            logger.error(f"❌ WebSocket错误: {data}")
                        else:
                            logger.debug(f"🔍 WebSocket信息: {data}")
                return
            
            # 处理数据消息
            if 'data' in data and 'arg' in data:
                arg = data['arg']
                channel = arg.get('channel', '')
                inst_id = arg.get('instId', '')
                
                # 标准化交易对名称
                normalized_inst_id = self._normalize_symbol(inst_id)
                
                # 更新数据缓存 - 使用标准化后的名称作为key
                async with self.data_lock:
                    cache_key = f"{channel}:{normalized_inst_id}"
                    self.latest_data[cache_key] = {
                        'channel': channel,
                        'inst_id': normalized_inst_id,  # 使用标准化后的名称
                        'original_inst_id': inst_id,    # 保留原始名称用于调试
                        'data': data['data'],
                        'timestamp': datetime.now(),
                        'is_private': is_private
                    }
                
                # 调用回调函数 - 使用标准化后的名称
                await self._trigger_callbacks(channel, normalized_inst_id, data['data'])             
                
        except Exception as e:
            logger.error(f"❌ 处理消息异常: {e}")

    async def _trigger_callbacks(self, channel: str, inst_id: str, data: List[Dict[str, Any]]):
        """触发回调函数"""
        try:
            callback_key = f"{channel}:{inst_id}"
            if callback_key in self.callbacks:
                for callback in self.callbacks[callback_key]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(channel, inst_id, data)
                        else:
                            callback(channel, inst_id, data)
                    except Exception as e:
                        logger.error(f"❌ 回调函数执行异常: {e}")
        except Exception as e:
            logger.error(f"❌ 触发回调异常: {e}")

    async def _heartbeat_task(self):
        """心跳任务 - 使用OKX标准的ping格式"""
        while self.is_running:
            try:
                current_time = time.time()
                
                # 检查是否需要发送ping
                if current_time - self.last_ping_time > self.ping_interval:
                    # OKX WebSocket使用特定的ping格式
                    ping_msg = "ping"
                    
                    # 发送ping到公共连接
                    if self.public_ws:
                        try:
                            await self.public_ws.send(ping_msg)
                            logger.debug("💓 发送公共WebSocket心跳包")
                        except Exception as e:
                            logger.warning(f"⚠️ 发送公共心跳失败: {e}")
                    
                    # 发送ping到私有连接
                    if self.private_ws:
                        try:
                            await self.private_ws.send(ping_msg)
                            logger.debug("💓 发送私有WebSocket心跳包")
                        except Exception as e:
                            logger.warning(f"⚠️ 发送私有心跳失败: {e}")
                    
                    self.last_ping_time = current_time
                
                # 检查连接健康状态 - 如果超过60秒没收到pong，认为连接有问题
                if current_time - self.last_pong_time > 60:
                    logger.warning("⚠️ 长时间未收到pong响应，可能连接异常")
                    # 主动关闭连接以触发重连
                    try:
                        if self.public_ws and self.is_public_connected():
                            await self.public_ws.close(code=1000, reason="健康检查失败")
                    except:
                        pass
                    
                    try:
                        if self.private_ws and self.is_private_connected():
                            await self.private_ws.close(code=1000, reason="健康检查失败")
                    except:
                        pass
                    
                    # 重置pong时间
                    self.last_pong_time = current_time
                
                await asyncio.sleep(5)  # 每5秒检查一次
                
            except Exception as e:
                logger.error(f"❌ 心跳任务异常: {e}")
                await asyncio.sleep(5)

    async def subscribe_ticker(self, inst_id: str, callback: Optional[Callable] = None) -> bool:
        """订阅ticker数据"""
        return await self._subscribe_channel(ChannelType.TICKER.value, inst_id, callback)

    async def subscribe_kline(self, inst_id: str, timeframe: str = "1m", callback: Optional[Callable] = None) -> bool:
        """订阅K线数据 - 优化错误检测逻辑"""
        # 先尝试正常订阅，只有在实际失败时才使用REST API
        channel = f"{ChannelType.KLINE.value}{timeframe}"
        return await self._subscribe_channel(channel, inst_id, callback)

    async def subscribe_trades(self, inst_id: str, callback: Optional[Callable] = None) -> bool:
        """订阅交易数据"""
        return await self._subscribe_channel(ChannelType.TRADES.value, inst_id, callback)

    async def subscribe_order_book(self, inst_id: str, callback: Optional[Callable] = None) -> bool:
        """订阅订单簿数据"""
        return await self._subscribe_channel(ChannelType.ORDER_BOOK.value, inst_id, callback)

    async def subscribe_funding_rate(self, inst_id: str, callback: Optional[Callable] = None) -> bool:
        """订阅资金费率"""
        return await self._subscribe_channel(ChannelType.FUNDING_RATE.value, inst_id, callback)

    async def subscribe_tickers_batch(self, inst_ids: List[str], callback: Optional[Callable] = None) -> Dict[str, bool]:
        """批量订阅ticker数据"""
        if not inst_ids:
            return {}
        
        logger.info(f"📡 批量订阅ticker: {len(inst_ids)} 个交易对")
        
        # 等待连接建立
        if not await self.wait_for_connection(timeout=10.0):
            logger.warning("⚠️ 等待WebSocket连接超时，无法批量订阅ticker")
            return {inst_id: False for inst_id in inst_ids}
        
        if not self.is_public_connected():
            logger.warning("⚠️ 公共WebSocket未连接，无法批量订阅ticker")
            return {inst_id: False for inst_id in inst_ids}
        
        # 分批处理，每批最多20个
        batch_size = 20
        all_results = {}
        
        for i in range(0, len(inst_ids), batch_size):
            batch = inst_ids[i:i + batch_size]
            
            # 构建批量订阅消息
            import time
            args = []
            for inst_id in batch:
                args.append({
                    "channel": ChannelType.TICKER.value,
                    "instId": inst_id
                })
            
            subscribe_msg = {
                "id": str(int(time.time() * 1000)),
                "op": "subscribe",
                "args": args
            }
            
            try:
                await self.public_ws.send(json.dumps(subscribe_msg))
                
                # 记录订阅信息
                for inst_id in batch:
                    sub_key = f"{ChannelType.TICKER.value}:{inst_id}"
                    self.subscriptions[sub_key] = SubscriptionInfo(
                        channel=ChannelType.TICKER.value,
                        inst_id=inst_id,
                        callback=callback,
                        last_update=datetime.now()
                    )
                    all_results[inst_id] = True
                
                logger.debug(f"📡 批量ticker订阅批次完成: {len(batch)} 个交易对")
                
                # 批次间短暂等待
                if i + batch_size < len(inst_ids):
                    await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.error(f"❌ 批量ticker订阅批次失败: {e}")
                for inst_id in batch:
                    all_results[inst_id] = False
        
        success_count = sum(1 for success in all_results.values() if success)
        logger.info(f"✅ 批量ticker订阅完成: {success_count}/{len(inst_ids)} 成功")
        return all_results

    async def subscribe_funding_rates_batch(self, inst_ids: List[str], callback: Optional[Callable] = None) -> Dict[str, bool]:
        """批量订阅资金费率"""
        if not inst_ids:
            return {}
        
        logger.info(f"💰 批量订阅资金费率: {len(inst_ids)} 个交易对")
        
        # 等待连接建立
        if not await self.wait_for_connection(timeout=10.0):
            logger.warning("⚠️ 等待WebSocket连接超时，无法批量订阅资金费率")
            return {inst_id: False for inst_id in inst_ids}
        
        if not self.is_public_connected():
            logger.warning("⚠️ 公共WebSocket未连接，无法批量订阅资金费率")
            return {inst_id: False for inst_id in inst_ids}
        
        # 分批处理，每批最多20个
        batch_size = 20
        all_results = {}
        
        for i in range(0, len(inst_ids), batch_size):
            batch = inst_ids[i:i + batch_size]
            
            # 构建批量订阅消息
            import time
            args = []
            for inst_id in batch:
                args.append({
                    "channel": ChannelType.FUNDING_RATE.value,
                    "instId": inst_id
                })
            
            subscribe_msg = {
                "id": str(int(time.time() * 1000)),
                "op": "subscribe",
                "args": args
            }
            
            try:
                await self.public_ws.send(json.dumps(subscribe_msg))
                
                # 记录订阅信息
                for inst_id in batch:
                    sub_key = f"{ChannelType.FUNDING_RATE.value}:{inst_id}"
                    self.subscriptions[sub_key] = SubscriptionInfo(
                        channel=ChannelType.FUNDING_RATE.value,
                        inst_id=inst_id,
                        callback=callback,
                        last_update=datetime.now()
                    )
                    all_results[inst_id] = True
                
                logger.debug(f"💰 批量资金费率订阅批次完成: {len(batch)} 个交易对")
                
                # 批次间短暂等待
                if i + batch_size < len(inst_ids):
                    await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.error(f"❌ 批量资金费率订阅批次失败: {e}")
                for inst_id in batch:
                    all_results[inst_id] = False
        
        success_count = sum(1 for success in all_results.values() if success)
        logger.info(f"✅ 批量资金费率订阅完成: {success_count}/{len(inst_ids)} 成功")
        return all_results

    async def _validate_instrument(self, inst_id: str) -> bool:
        """验证交易对是否存在且活跃"""
        try:
            # 使用REST API验证交易对
            from app.services.okx_service import OKXService
            async with OKXService() as okx_service:
                instruments = await okx_service.get_all_instruments('SWAP')
                for inst in instruments:
                    if inst.get('instId') == inst_id and inst.get('state') == 'live':
                        return True
            return False
        except Exception as e:
            logger.warning(f"⚠️ 验证交易对 {inst_id} 时出错: {e}")
            return True  # 验证失败时假设交易对有效，避免误判

    async def _subscribe_channel(self, channel: str, inst_id: str, callback: Optional[Callable] = None) -> bool:
        """订阅频道"""
        try:
            # 检查是否是已知的问题交易对
            if hasattr(self, '_problematic_symbols') and inst_id in self._problematic_symbols:
                logger.debug(f"🔍 跳过已知问题交易对: {inst_id}")
                # 仍然尝试订阅，但降低日志级别
            
            # 等待连接建立，最多等待10秒
            if not await self.wait_for_connection(timeout=10.0):
                logger.warning(f"⚠️ 等待WebSocket连接超时，无法订阅 {channel}:{inst_id}")
                return False
            
            if not self.is_public_connected():
                logger.warning(f"⚠️ 公共WebSocket未连接，无法订阅 {channel}:{inst_id}")
                return False
            
            # 对于K线订阅，先验证交易对是否存在
            if channel.startswith('candle'):
                is_valid = await self._validate_instrument(inst_id)
                if not is_valid:
                    logger.warning(f"⚠️ 交易对 {inst_id} 验证失败，跳过订阅")
                    return False
            
            # 构建订阅消息 - 根据官方文档添加id字段
            import time
            subscribe_msg = {
                "id": str(int(time.time() * 1000)),  # 简单的时间戳ID
                "op": "subscribe",
                "args": [{
                    "channel": channel,
                    "instId": inst_id
                }]
            }
            
            # 添加详细日志以调试问题
            logger.debug(f"🔍 构建订阅消息: channel={channel}, inst_id={inst_id}")
            logger.debug(f"🔍 完整订阅消息: {json.dumps(subscribe_msg)}")
            
            # 发送订阅消息，带重试机制
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if not self.is_public_connected():
                        logger.warning(f"⚠️ 连接已断开，重试订阅 {channel}:{inst_id} (第{attempt+1}次)")
                        await asyncio.sleep(1)
                        continue
                    
                    message_to_send = json.dumps(subscribe_msg)
                    logger.debug(f"🔍 发送消息: {message_to_send}")
                    await self.public_ws.send(message_to_send)
                    break
                    
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"❌ 发送订阅消息失败: {channel}:{inst_id} - {e}")
                        return False
                    else:
                        logger.warning(f"⚠️ 订阅重试 {channel}:{inst_id} (第{attempt+1}次): {e}")
                        await asyncio.sleep(0.5)
            
            # 记录订阅信息
            sub_key = f"{channel}:{inst_id}"
            self.subscriptions[sub_key] = SubscriptionInfo(
                channel=channel,
                inst_id=inst_id,
                callback=callback,
                last_update=datetime.now()
            )
            
            # 注册回调
            if callback:
                if sub_key not in self.callbacks:
                    self.callbacks[sub_key] = []
                self.callbacks[sub_key].append(callback)
            
            logger.debug(f"📡 订阅请求已发送: {channel} - {inst_id}")
            
            # 等待一小段时间让订阅生效，并检查是否有错误响应
            await asyncio.sleep(0.5)
            
            # 检查是否是已知的问题交易对
            if hasattr(self, '_problematic_symbols') and inst_id in self._problematic_symbols:
                logger.debug(f"🔍 交易对 {inst_id} 被标记为问题交易对，订阅可能失败")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 订阅失败: {channel} - {inst_id}, 错误: {e}")
            return False

    async def unsubscribe_channel(self, channel: str, inst_id: str) -> bool:
        """取消订阅频道"""
        try:
            if not self.public_ws:
                logger.warning("⚠️ 公共WebSocket未连接，无法取消订阅")
                return False
            
            # 构建取消订阅消息
            unsubscribe_msg = {
                "op": "unsubscribe",
                "args": [{
                    "channel": channel,
                    "instId": inst_id
                }]
            }
            
            # 发送取消订阅消息
            await self.public_ws.send(json.dumps(unsubscribe_msg))
            
            # 清理订阅信息
            sub_key = f"{channel}:{inst_id}"
            self.subscriptions.pop(sub_key, None)
            self.callbacks.pop(sub_key, None)
            
            # 清理缓存数据
            async with self.data_lock:
                self.latest_data.pop(sub_key, None)
            
            logger.info(f"📡 取消订阅成功: {channel} - {inst_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 取消订阅失败: {channel} - {inst_id}, 错误: {e}")
            return False

    async def _resubscribe_public_channels(self):
        """重新订阅所有公共频道"""
        if not self.subscriptions:
            return
        
        success_count = 0
        failed_count = 0
        
        # 清理失败记录，给交易对重新机会
        if hasattr(self, '_subscription_failures'):
            self._subscription_failures.clear()
            logger.info("🔄 清理订阅失败记录，重新尝试所有交易对")
        
        # 清理问题交易对标记，给重连时重新机会
        if hasattr(self, '_problematic_symbols'):
            problematic_count = len(self._problematic_symbols)
            self._problematic_symbols.clear()
            if problematic_count > 0:
                logger.info(f"🔄 清理 {problematic_count} 个问题交易对标记，重新尝试")
        
        # 分批重新订阅，避免服务器压力
        batch_size = 5
        subscription_items = list(self.subscriptions.items())
        
        for i in range(0, len(subscription_items), batch_size):
            batch = subscription_items[i:i + batch_size]
            
            for sub_key, sub_info in batch:
                try:
                    # 直接发送订阅消息，不使用_subscribe_channel避免重复等待
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [{
                            "channel": sub_info.channel,
                            "instId": sub_info.inst_id
                        }]
                    }
                    
                    if self.public_ws and self.is_public_connected():
                        await self.public_ws.send(json.dumps(subscribe_msg))
                        success_count += 1
                        logger.debug(f"🔄 重新订阅: {sub_info.channel}:{sub_info.inst_id}")
                    else:
                        failed_count += 1
                        logger.warning(f"⚠️ 连接不可用，跳过重新订阅: {sub_key}")
                    
                    await asyncio.sleep(0.2)  # 增加延迟避免频率限制
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ 重新订阅失败: {sub_key}, 错误: {e}")
                    # 记录详细的错误信息用于调试
                    logger.debug(f"🔍 重新订阅错误详情: {type(e).__name__}: {str(e)}")
            
            # 批次间等待更长时间
            if i + batch_size < len(subscription_items):
                await asyncio.sleep(1.0)
                logger.debug(f"🔄 完成批次 {i//batch_size + 1}/{(len(subscription_items)-1)//batch_size + 1}")
        
        # 移除原来的循环，因为已经在上面处理了
        
        if success_count > 0 or failed_count > 0:
            logger.info(f"🔄 重新订阅完成: {success_count} 成功, {failed_count} 失败")

    async def _resubscribe_private_channels(self):
        """重新订阅所有私有频道"""
        # 私有频道重订阅逻辑
        pass

    async def get_latest_ticker(self, inst_id: str) -> Optional[Dict[str, Any]]:
        """获取最新ticker数据"""
        async with self.data_lock:
            cache_key = f"{ChannelType.TICKER.value}:{inst_id}"
            if cache_key in self.latest_data:
                return self.latest_data[cache_key]['data'][0]
        return None

    async def get_latest_kline(self, inst_id: str, timeframe: str = "1m") -> Optional[Dict[str, Any]]:
        """获取最新K线数据 - 混合模式：优先使用WebSocket缓存，失败时使用REST API"""
        # 首先尝试从WebSocket缓存获取
        async with self.data_lock:
            cache_key = f"{ChannelType.KLINE.value}{timeframe}:{inst_id}"
            if cache_key in self.latest_data:
                cache_data = self.latest_data[cache_key]
                # 检查数据是否新鲜（5分钟内）
                from datetime import datetime, timedelta
                if datetime.now() - cache_data['timestamp'] < timedelta(minutes=5):
                    return cache_data['data'][0]
        
        # WebSocket数据不可用或过期，尝试使用REST API
        try:
            logger.debug(f"🔄 WebSocket数据不可用，使用REST API获取 {inst_id} {timeframe} K线")
            from app.services.okx_service import OKXService
            async with OKXService() as okx_service:
                klines = await okx_service.get_kline_data(inst_id, timeframe, limit=1)
                if klines and len(klines) > 0:
                    # 转换REST API数据格式为WebSocket格式
                    kline = klines[0]
                    return {
                        'ts': kline.get('ts'),
                        'o': kline.get('o'),
                        'h': kline.get('h'),
                        'l': kline.get('l'),
                        'c': kline.get('c'),
                        'vol': kline.get('vol'),
                        'volCcy': kline.get('volCcy')
                    }
        except Exception as e:
            logger.warning(f"⚠️ REST API获取K线数据失败: {e}")
        
        return None




# 全局WebSocket服务实例
_okx_ws_service = None

async def get_okx_websocket_service() -> OKXWebSocketService:
    """获取OKX WebSocket服务实例"""
    global _okx_ws_service
    if _okx_ws_service is None:
        _okx_ws_service = OKXWebSocketService()
        await _okx_ws_service.start()
    return _okx_ws_service

async def cleanup_okx_websocket_service():
    """清理WebSocket服务"""
    global _okx_ws_service
    if _okx_ws_service:
        await _okx_ws_service.stop()
        _okx_ws_service = None