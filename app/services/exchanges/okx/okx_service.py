# -*- coding: utf-8 -*-
"""
OKX交易所服务
OKX Exchange Service - 提供OKX交易所数据获取和交易功能
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import aiohttp
import hmac
import hashlib
import base64
import json
import time

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError
from app.utils.okx_rate_limiter import get_okx_rate_limiter
from app.utils.http_manager import get_http_manager

logger = get_logger(__name__)
settings = get_settings()


# 全局请求间隔管理
_last_request_time = 0
_request_lock = asyncio.Lock()
_current_interval = 0.5  # 动态调整的请求间隔


class OKXService:
    """OKX交易所服务类"""
    def __init__(self):
        self.config = settings.okx_config
        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.passphrase = self.config["passphrase"]
        self.sandbox = self.config["sandbox"]
        
        # API端点
        if self.sandbox:
            self.base_url = "https://www.okx.com"  # OKX没有单独的沙盒URL
        else:
            self.base_url = self.config["base_url"]
        
        self.http_manager = None  # 使用统一HTTP连接池管理器
        self.rate_limiter = get_okx_rate_limiter()  # 使用专业的频率限制管理器
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_http_manager()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        # 不需要清理HTTP管理器，它由全局管理
        if exc_type:
            logger.error(f"OKX服务异常: {exc_type.__name__}: {exc_val}")
    
    async def _ensure_http_manager(self):
        """确保HTTP管理器可用"""
        if not self.http_manager:
            self.http_manager = await get_http_manager()
            logger.debug("✅ OKX服务已连接到统一HTTP连接池")
    
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成OKX API签名"""
        message = timestamp + method.upper() + request_path + body
        signature = base64.b64encode(
            hmac.new(
                self.secret_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        return signature
    

    
    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """获取请求头"""
        # OKX要求使用UTC时间戳，格式为ISO8601
        from datetime import timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        signature = self._generate_signature(timestamp, method, request_path, body)
        
        headers = {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
        
        if self.sandbox:
            headers['x-simulated-trading'] = '1'
        
        return headers
    
    async def _make_request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Dict[str, Any]:
        """发起API请求 - 使用专业频率限制管理器"""
        global _last_request_time, _request_lock, _current_interval
        
        # 全局请求间隔控制，避免频率限制
        async with _request_lock:
            current_time = time.time()
            time_since_last = current_time - _last_request_time
            
            if time_since_last < _current_interval:
                wait_time = _current_interval - time_since_last
                await asyncio.sleep(wait_time)
            
            _last_request_time = time.time()
        
        # 获取API调用许可
        permit_granted = await self.rate_limiter.acquire_permit(endpoint)
        if not permit_granted:
            # 如果无法获得许可，等待一段时间后重试
            await asyncio.sleep(2.0)  # 增加等待时间
            permit_granted = await self.rate_limiter.acquire_permit(endpoint)
            if not permit_granted:
                logger.warning(f"OKX API频率限制，跳过请求: {endpoint}")
                return []  # 返回空结果而不是抛出异常
        
        # 确保HTTP管理器可用
        await self._ensure_http_manager()
        
        url = f"{self.base_url}{endpoint}"
        
        # 处理查询参数
        if params:
            # 过滤掉空值参数
            filtered_params = {k: v for k, v in params.items() if v is not None and v != ''}
            if filtered_params:
                query_string = "&".join([f"{k}={v}" for k, v in filtered_params.items()])
                request_path = f"{endpoint}?{query_string}"
            else:
                request_path = endpoint
        else:
            request_path = endpoint
        
        # 处理请求体
        body = ""
        if data:
            body = json.dumps(data)
        
        headers = self._get_headers(method, request_path, body)
        
        # 重试机制处理频率限制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 使用统一HTTP连接池
                async with self.http_manager.get_session() as session:
                    # 配置代理
                    kwargs = {
                        'headers': headers,
                        'params': params
                    }
                    
                    if body:
                        kwargs['data'] = body
                    
                    if settings.proxy_enabled and settings.proxy_url:
                        kwargs['proxy'] = settings.proxy_url
                    
                    async with session.request(method, url, **kwargs) as response:
                        result = await response.json()
                    
                    if result.get('code') != '0':
                        error_msg = result.get('msg', 'Unknown error')
                        
                        # 特殊处理频率限制错误
                        if 'Too Many Requests' in error_msg or result.get('code') == '50011':
                            # 动态增加请求间隔
                            _current_interval = min(_current_interval * 1.5, 3.0)  # 最大3秒间隔
                            logger.warning(f"检测到频率限制，调整请求间隔至{_current_interval:.1f}秒")
                            
                            if attempt < max_retries - 1:
                                # 更长的等待时间，避免频率限制
                                wait_time = (2 ** attempt) * 3.0  # 3s, 6s, 12s
                                logger.warning(f"OKX频率限制，等待{wait_time}秒后重试 (尝试 {attempt + 1}/{max_retries})")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"OKX频率限制，已达最大重试次数")
                                # 不抛出异常，而是等待更长时间后返回空结果
                                await asyncio.sleep(15.0)  # 等待15秒冷却
                                return []
                        
                        logger.error(f"OKX API错误: {error_msg}")
                        raise TradingToolError(f"OKX API错误: {error_msg}")
                    
                    # 请求成功，逐渐降低请求间隔
                    if _current_interval > 0.5:
                        _current_interval = max(_current_interval * 0.95, 0.5)  # 逐渐降低到最小0.5秒
                    
                    return result.get('data', [])
                    
            except aiohttp.ClientError as e:
                # 改进网络错误日志
                error_type = type(e).__name__
                error_msg = str(e)
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 1.0
                    logger.warning(f"🌐 OKX网络请求失败 [{error_type}]，{wait_time}秒后重试: {error_msg}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ OKX API请求最终失败 [{error_type}]: {error_msg}")
                    logger.debug(f"🔍 网络请求详情 - 端点: {endpoint}, 重试次数: {max_retries}, 异常类型: {error_type}")
                    return []
                    
            except Exception as e:
                # 改进通用异常日志
                error_type = type(e).__name__
                error_msg = str(e)
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 1.0
                    logger.warning(f"🔄 OKX请求异常 [{error_type}]，{wait_time}秒后重试: {error_msg}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ OKX请求最终异常 [{error_type}]: {error_msg}")
                    logger.debug(f"🔍 请求异常详情 - 端点: {endpoint}, 参数: {params}, 异常类型: {error_type}")
                    return []

    
    async def get_account_balance(self) -> Dict[str, Any]:
        """获取账户余额"""
        try:
            result = await self._make_request('GET', '/api/v5/account/balance')
            
            if not result:
                return {}
            
            # 解析余额数据
            balance_info = result[0] if result else {}
            details = balance_info.get('details', [])
            
            balances = {}
            total_equity = 0
            
            for detail in details:
                currency = detail.get('ccy', '')
                equity = float(detail.get('eq', '0'))
                available = float(detail.get('availEq', '0'))
                
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
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓信息 - 修复币本位合约计算"""
        try:
            result = await self._make_request('GET', '/api/v5/account/positions')
            
            positions = []
            for pos in result:
                try:
                    pos_size = float(pos.get('pos', '0') or '0')
                    if pos_size != 0:  # 只返回有持仓的
                        inst_id = pos.get('instId', '')
                        
                        # 判断合约类型和计算方式
                        # 使用OKX API提供的notionalUsd字段作为持仓价值
                        notional_usd = float(pos.get('notionalUsd', '0') or '0')
                        current_price = float(pos.get('markPx', '0') or '0')
                        
                        if '-USD-SWAP' in inst_id:
                            contract_type = '币本位永续'
                            base_currency = inst_id.split('-')[0]  # 如BTC-USD-SWAP的BTC
                            position_value_usd = notional_usd
                            # 币数量 = USD价值 / 价格
                            position_value_base = position_value_usd / current_price if current_price > 0 else 0
                                
                        elif '-USDT-SWAP' in inst_id:
                            contract_type = 'U本位永续'
                            base_currency = 'USDT'
                            position_value_usd = notional_usd
                            position_value_base = position_value_usd
                            # 计算对应的币数量
                            position_value_usd / current_price if current_price > 0 else 0
                            
                        elif '-USDC-SWAP' in inst_id:
                            contract_type = 'C本位永续'
                            base_currency = 'USDC'
                            position_value_usd = notional_usd
                            position_value_base = position_value_usd
                        else:
                            contract_type = '现货'
                            base_currency = inst_id.split('-')[0] if '-' in inst_id else inst_id
                            position_value_usd = notional_usd if notional_usd > 0 else abs(pos_size) * current_price
                            position_value_base = abs(pos_size)
                        
                        # 计算盈亏 - 币本位特殊处理
                        unrealized_pnl = float(pos.get('upl', '0') or '0')
                        if contract_type == '币本位永续':
                            # 币本位的盈亏是以基础货币计价，需要转换为USD
                            unrealized_pnl_usd = unrealized_pnl * current_price
                        else:
                            # U本位的盈亏直接是USDT
                            unrealized_pnl_usd = unrealized_pnl
                        
                        positions.append({
                            'instId': inst_id,  # 使用统一的instId字段
                            'symbol': inst_id,  # 保留symbol字段用于向后兼容
                            'contract_type': contract_type,
                            'base_currency': base_currency,
                            'posSide': pos.get('posSide', ''),  # 使用统一的posSide字段
                            'side': pos.get('posSide', ''),  # 保留side字段用于向后兼容
                            'pos': str(pos_size),  # 添加统一的pos字段
                            'size': pos_size,
                            'size_abs': abs(pos_size),
                            'position_value_usd': position_value_usd,
                            'position_value_base': position_value_base,
                            'avgPx': str(float(pos.get('avgPx', '0') or '0')),  # 添加统一的avgPx字段
                            'avg_price': float(pos.get('avgPx', '0') or '0'),
                            'markPx': str(float(pos.get('markPx', '0') or '0')),  # 添加统一的markPx字段
                            'mark_price': float(pos.get('markPx', '0') or '0'),
                            'upl': str(unrealized_pnl),  # 添加统一的upl字段
                            'unrealized_pnl': unrealized_pnl,
                            'unrealized_pnl_usd': unrealized_pnl_usd,
                            'uplRatio': str(float(pos.get('uplRatio', '0') or '0')),  # 添加统一的uplRatio字段
                            'unrealized_pnl_ratio': float(pos.get('uplRatio', '0') or '0'),
                            'margin': str(float(pos.get('margin', '0') or '0')),  # 统一margin格式
                            'notionalUsd': str(position_value_usd),  # 添加统一的notionalUsd字段
                            'leverage': float(pos.get('lever', '1') or '1'),
                            'update_time': datetime.now()
                        })
                except (ValueError, TypeError) as e:
                    logger.warning(f"解析持仓数据失败: {pos}, 错误: {e}")
                    continue
            
            return positions
            
        except Exception as e:
            logger.error(f"获取持仓信息失败: {e}")
            raise TradingToolError(f"获取持仓信息失败: {e}")
    
    async def get_spot_balances(self) -> List[Dict[str, Any]]:
        """获取现货余额"""
        try:
            result = await self._make_request('GET', '/api/v5/account/balance')
            
            if not result:
                return []
            
            balance_info = result[0] if result else {}
            details = balance_info.get('details', [])
            
            spot_balances = []
            for detail in details:
                currency = detail.get('ccy', '')
                equity = float(detail.get('eq', '0') or '0')
                available = float(detail.get('availEq', '0') or '0')
                
                if equity > 0:  # 只返回有余额的
                    spot_balances.append({
                        'currency': currency,
                        'equity': equity,
                        'available': available,
                        'frozen': equity - available,
                        'update_time': datetime.now()
                    })
            
            return spot_balances
            
        except Exception as e:
            logger.error(f"获取现货余额失败: {e}")
            return []
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            params = {'instId': symbol}
            result = await self._make_request('GET', '/api/v5/market/ticker', params=params)
            
            if result:
                return float(result[0].get('last', '0'))
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol}价格失败: {e}")
            return None
    
    async def get_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据"""
        try:
            params = {'instType': inst_type}
            result = await self._make_request('GET', '/api/v5/market/tickers', params=params)
            
            tickers = []
            for ticker in result:
                tickers.append({
                    'instId': ticker.get('instId', ''),
                    'last': float(ticker.get('last', '0') or '0'),
                    'lastSz': float(ticker.get('lastSz', '0') or '0'),
                    'askPx': float(ticker.get('askPx', '0') or '0'),
                    'askSz': float(ticker.get('askSz', '0') or '0'),
                    'bidPx': float(ticker.get('bidPx', '0') or '0'),
                    'bidSz': float(ticker.get('bidSz', '0') or '0'),
                    'open24h': float(ticker.get('open24h', '0') or '0'),
                    'high24h': float(ticker.get('high24h', '0') or '0'),
                    'low24h': float(ticker.get('low24h', '0') or '0'),
                    'volCcy24h': float(ticker.get('volCcy24h', '0') or '0'),
                    'vol24h': float(ticker.get('vol24h', '0') or '0'),
                    'sodUtc0': float(ticker.get('sodUtc0', '0') or '0'),
                    'sodUtc8': float(ticker.get('sodUtc8', '0') or '0'),
                    'ts': ticker.get('ts', '0')
                })
            
            return tickers
            
        except Exception as e:
            logger.error(f"获取ticker数据失败: {e}")
            return []
    
    async def get_klines(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[List[str]]:
        """获取K线数据 - 兼容方法，返回原始格式"""
        try:
            kline_data = await self.get_kline_data(symbol, timeframe, limit)
            
            # 转换为原始格式 [timestamp, open, high, low, close, volume]
            klines = []
            for item in kline_data:
                # 验证数据完整性
                if not all(key in item for key in ['timestamp', 'open', 'high', 'low', 'close', 'volume']):
                    logger.warning(f"⚠️ K线数据字段不完整: {item}")
                    continue
                
                try:
                    klines.append([
                        str(item['timestamp']),
                        str(item['open']),
                        str(item['high']),
                        str(item['low']),
                        str(item['close']),
                        str(item['volume'])
                    ])
                except (KeyError, ValueError) as e:
                    logger.warning(f"⚠️ K线数据转换失败: {item}, 错误: {e}")
                    continue
            
            return klines
            
        except Exception as e:
            logger.error(f"获取{symbol} K线数据失败: {e}")
            return []
    
    async def get_kline_data(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据"""
        try:
            # OKX时间周期映射 - 支持大小写格式
            tf_mapping = {
                # 小写格式
                '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
                '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W',
                # 大写格式
                '1M': '1m', '5M': '5m', '15M': '15m', '30M': '30m',
                '1H': '1H', '4H': '4H', '1D': '1D', '1W': '1W'
            }
            
            okx_tf = tf_mapping.get(timeframe, tf_mapping.get(timeframe.lower(), '1H'))
            
            params = {
                'instId': symbol,
                'bar': okx_tf,
                'limit': str(limit)
            }
            
            result = await self._make_request('GET', '/api/v5/market/candles', params=params)
            
            # 验证API返回结果
            if not result:
                logger.warning(f"⚠️ OKX API返回空数据: {symbol} {timeframe}")
                return []
            
            if not isinstance(result, list):
                logger.error(f"❌ OKX API返回数据格式异常: {type(result)} - {result}")
                return []
            
            logger.debug(f"🔍 OKX API返回 {len(result)} 条K线数据: {symbol} {timeframe}")
            
            klines = []
            for item in result:
                # 验证数据完整性，OKX返回格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                if not item or len(item) < 7:
                    logger.warning(f"⚠️ OKX K线数据格式不完整: {item}")
                    continue
                
                try:
                    klines.append({
                        'timestamp': int(item[0]),
                        'open': float(item[1]),
                        'high': float(item[2]),
                        'low': float(item[3]),
                        'close': float(item[4]),
                        'volume': float(item[5]) if item[5] else 0.0,
                        'volume_currency': float(item[6]) if item[6] else 0.0
                    })
                except (ValueError, TypeError, IndexError) as e:
                    logger.warning(f"⚠️ OKX K线数据解析失败: {item}, 错误: {e}")
                    continue
            
            return sorted(klines, key=lambda x: x['timestamp'])
            
        except Exception as e:
            logger.error(f"获取{symbol} K线数据失败: {e}")
            return []
    
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近交易数据"""
        try:
            params = {
                'instId': symbol,
                'limit': str(min(limit, 500))  # OKX API限制最多500条
            }
            
            result = await self._make_request('GET', '/api/v5/market/trades', params=params)
            
            trades = []
            for trade in result:
                trades.append({
                    'instId': trade.get('instId', ''),
                    'side': trade.get('side', ''),
                    'sz': trade.get('sz', '0'),
                    'px': trade.get('px', '0'),
                    'tradeId': trade.get('tradeId', ''),
                    'ts': trade.get('ts', '0')
                })
            
            return trades
            
        except Exception as e:
            logger.error(f"获取{symbol}最近交易数据失败: {e}")
            return []

    async def get_funding_rate(self, symbol: str = None) -> Optional[Dict[str, Any]]:
        """获取资金费率"""
        try:
            if symbol:
                # 获取单个交易对的资金费率
                params = {'instId': symbol}
                result = await self._make_request('GET', '/api/v5/public/funding-rate', params=params)
                
                if result:
                    data = result[0]
                    
                    # 返回OKX原始格式，让适配器处理
                    return {
                        'instId': data.get('instId', symbol),
                        'fundingRate': data.get('fundingRate', '0'),
                        'nextFundingTime': data.get('nextFundingTime', '0'),
                        'fundingTime': data.get('fundingTime', '0')
                    }
            else:
                # 获取所有永续合约的资金费率 - 先获取所有SWAP交易对
                logger.debug("获取所有SWAP交易对列表...")
                instruments = await self.get_all_instruments('SWAP')
                
                if not instruments:
                    logger.error("获取交易对列表失败")
                    return []
                
                # 提取交易对符号
                symbols = [inst['instId'] for inst in instruments if inst.get('state') == 'live']
                logger.debug(f"找到 {len(symbols)} 个活跃的SWAP交易对")
                
                # 批量获取费率（优化批次处理）
                return await self.get_batch_funding_rates(symbols[:500])  # 增加到500个币种，50个一批处理
            
            return None
            
        except Exception as e:
            logger.error(f"获取{symbol if symbol else '所有'}资金费率失败: {e}")
            return None

    async def get_funding_rate_history(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取资金费率历史，用于计算费率间隔"""
        try:
            params = {
                'instId': symbol,
                'limit': str(limit)
            }
            
            result = await self._make_request('GET', '/api/v5/public/funding-rate-history', params=params)
            
            if not result:
                return []
            
            history = []
            for data in result:
                history.append({
                    'symbol': symbol,
                    'funding_rate': float(data.get('fundingRate', '0')),
                    'funding_time': int(data.get('fundingTime', '0')),
                    'realized_rate': float(data.get('realizedRate', '0'))
                })
            
            return history
            
        except Exception as e:
            logger.error(f"获取{symbol}资金费率历史失败: {e}")
            return []

    async def get_all_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有交易对列表"""
        try:
            params = {'instType': inst_type}
            result = await self._make_request('GET', '/api/v5/public/instruments', params=params)
            
            instruments = []
            for item in result:
                instruments.append({
                    'instId': item.get('instId', ''),
                    'instType': item.get('instType', ''),
                    'baseCcy': item.get('baseCcy', ''),
                    'quoteCcy': item.get('quoteCcy', ''),
                    'settleCcy': item.get('settleCcy', ''),
                    'ctVal': item.get('ctVal', ''),
                    'ctMult': item.get('ctMult', ''),
                    'ctValCcy': item.get('ctValCcy', ''),
                    'minSz': item.get('minSz', ''),
                    'lotSz': item.get('lotSz', ''),
                    'tickSz': item.get('tickSz', ''),
                    'state': item.get('state', ''),
                    'listTime': item.get('listTime', ''),
                    'expTime': item.get('expTime', '')
                })
            
            return instruments
            
        except Exception as e:
            logger.error(f"获取{inst_type}交易对列表失败: {e}")
            return []

    async def get_batch_funding_rates(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取资金费率 - 智能频率控制版本
        使用信号量严格控制并发数量，遵守OKX API限制
        """
        try:
            # OKX PUBLIC API限制: 20 req/s, 1200 req/min
            # 使用信号量控制最大并发数为10，确保不超过频率限制
            max_concurrent = 10
            semaphore = asyncio.Semaphore(max_concurrent)
            
            logger.debug(f"开始批量获取费率，总计 {len(symbols)} 个币种，最大并发数: {max_concurrent}")
            
            async def rate_limited_get_funding_rate(symbol: str) -> Optional[Dict[str, Any]]:
                """带频率限制的资金费率获取"""
                async with semaphore:
                    try:
                        # 每个请求间隔至少50ms，确保不超过20 req/s
                        await asyncio.sleep(0.05)
                        result = await self.get_funding_rate(symbol)
                        return result
                    except Exception as e:
                        logger.warning(f"获取 {symbol} 费率失败: {e}")
                        return None
            
            # 创建所有任务
            tasks = [rate_limited_get_funding_rate(symbol) for symbol in symbols]
            
            # 执行所有任务，使用信号量自动控制并发
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            all_rates = []
            success_count = 0
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"获取 {symbols[i]} 费率异常: {result}")
                    continue
                
                if result and isinstance(result, dict) and 'fundingRate' in result:
                    all_rates.append(result)
                    success_count += 1
            
            logger.debug(f"批量获取费率完成: {success_count}/{len(symbols)} 成功")
            return all_rates
            
        except Exception as e:
            logger.error(f"批量获取费率失败: {e}")
            return []

    def calculate_funding_interval(self, funding_history: List[Dict[str, Any]]) -> int:
        """根据费率历史计算费率间隔（小时）"""
        if len(funding_history) < 2:
            return 8  # 默认8小时
        
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
            return round(avg_interval)
        
        return 8  # 默认8小时
    
    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓量和24小时变化"""
        try:
            # 获取当前持仓量
            params = {'instId': symbol}
            current_result = await self._make_request('GET', '/api/v5/public/open-interest', params=params)
            
            if not current_result or len(current_result) == 0:
                logger.warning(f"无法获取{symbol}的当前持仓量数据")
                return None
            
            current_data = current_result[0]
            current_oi = float(current_data.get('oi', '0'))
            current_oiCcy = float(current_data.get('oiCcy', '0'))
            
            # 尝试获取24小时前的持仓量数据来计算变化
            oiCcy24h = 0.0
            try:
                # 获取24小时的持仓量历史数据
                history_params = {
                    'instId': symbol,
                    'period': '1H',  # 1小时周期
                    'limit': '25'    # 获取25个数据点（约24小时）
                }
                
                history_result = await self._make_request(
                    'GET', 
                    '/api/v5/rubik/stat/contracts/open-interest-history', 
                    params=history_params
                )
                
                if history_result and len(history_result) >= 2:
                    # 最新数据
                    latest_oi = float(history_result[0][2]) if len(history_result[0]) > 2 else current_oiCcy
                    # 24小时前数据（取最后一个数据点）
                    old_oi = float(history_result[-1][2]) if len(history_result[-1]) > 2 else current_oiCcy
                    
                    # 计算24小时变化
                    oiCcy24h = latest_oi - old_oi
                    
                    logger.debug(f"{symbol} 持仓量变化计算: 当前={latest_oi:.2f}, 24h前={old_oi:.2f}, 变化={oiCcy24h:.2f}")
                
            except Exception as e:
                logger.warning(f"获取{symbol}持仓量历史数据失败，使用默认值: {e}")
                oiCcy24h = 0.0
            
            return {
                'symbol': symbol,
                'oi': current_oi,  # 持仓量（张数）
                'oiCcy': current_oiCcy,  # 持仓量（币数）
                'oiCcy24h': oiCcy24h,  # 24小时变化（币数）
                'update_time': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"获取{symbol}持仓量失败: {e}")
            return None
    
    async def get_open_interest_statistics(self, symbol: str, period: str = "5m", limit: int = 2) -> List[Dict[str, Any]]:
        """获取持仓量统计数据（用于监控变化）"""
        try:
            # OKX的持仓量历史数据接口
            params = {
                'instId': symbol,
                'period': period,
                'limit': str(limit)
            }
            
            result = await self._make_request('GET', '/api/v5/rubik/stat/contracts/open-interest-history', params=params)
            
            statistics = []
            for item in result:
                statistics.append({
                    'symbol': symbol,
                    'timestamp': int(item[0]),  # 时间戳
                    'open_interest': float(item[1]),  # 持仓量
                    'open_interest_value': float(item[2]) if len(item) > 2 else 0  # 持仓量价值
                })
            
            # 按时间戳降序排列（最新的在前面）
            return sorted(statistics, key=lambda x: x['timestamp'], reverse=True)
            
        except Exception as e:
            logger.error(f"获取{symbol}持仓量统计失败: {e}")
            # 如果统计接口失败，尝试使用当前持仓量数据构造
            try:
                current_oi = await self.get_open_interest(symbol)
                if current_oi:
                    return [{
                        'symbol': symbol,
                        'timestamp': int(datetime.now().timestamp() * 1000),
                        'open_interest': current_oi['open_interest'],
                        'open_interest_value': current_oi.get('open_interest_currency', 0)
                    }]
            except:
                pass
            return []
    
    async def place_order(self, symbol: str, side: str, size: float, 
                         order_type: str = 'market', price: float = None,
                         leverage: float = None) -> Dict[str, Any]:
        """下单"""
        try:
            # 设置杠杆
            if leverage:
                await self.set_leverage(symbol, leverage)
            
            order_data = {
                'instId': symbol,
                'tdMode': 'cross',  # 全仓模式
                'side': side.lower(),
                'ordType': order_type.lower(),
                'sz': str(size)
            }
            
            if order_type.lower() == 'limit' and price:
                order_data['px'] = str(price)
            
            result = await self._make_request('POST', '/api/v5/trade/order', data=order_data)
            
            if result:
                return {
                    'order_id': result[0].get('ordId', ''),
                    'client_order_id': result[0].get('clOrdId', ''),
                    'symbol': symbol,
                    'side': side,
                    'size': size,
                    'status': 'submitted',
                    'create_time': datetime.now()
                }
            
            raise TradingToolError("下单失败，未返回订单信息")
            
        except Exception as e:
            logger.error(f"下单失败: {e}")
            raise TradingToolError(f"下单失败: {e}")
    
    async def set_leverage(self, symbol: str, leverage: float) -> bool:
        """设置杠杆"""
        try:
            data = {
                'instId': symbol,
                'lever': str(int(leverage)),
                'mgnMode': 'cross'  # 全仓模式
            }
            
            await self._make_request('POST', '/api/v5/account/set-leverage', data=data)
            return True
            
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
            return False
    
    async def get_order_status(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]:
        """获取订单状态"""
        try:
            params = {
                'instId': symbol,
                'ordId': order_id
            }
            
            result = await self._make_request('GET', '/api/v5/trade/order', params=params)
            
            if result:
                order = result[0]
                return {
                    'order_id': order.get('ordId', ''),
                    'symbol': symbol,
                    'side': order.get('side', ''),
                    'size': float(order.get('sz', '0')),
                    'filled_size': float(order.get('fillSz', '0')),
                    'avg_price': float(order.get('avgPx', '0')),
                    'status': order.get('state', ''),
                    'update_time': datetime.now()
                }
            return None
            
        except Exception as e:
            logger.error(f"获取订单状态失败: {e}")
            return None
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤销订单"""
        try:
            data = {
                'instId': symbol,
                'ordId': order_id
            }
            
            await self._make_request('POST', '/api/v5/trade/cancel-order', data=data)
            return True
            
        except Exception as e:
            logger.error(f"撤销订单失败: {e}")
            return False
    
    async def get_algo_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """获取策略委托订单"""
        try:
            params = {
                'ordType': 'conditional'  # 添加必需的订单类型参数
            }
            if symbol:
                params['instId'] = symbol
            
            result = await self._make_request('GET', '/api/v5/trade/orders-algo-pending', params=params)
            
            orders = []
            for order in result:
                orders.append({
                    'algo_id': order.get('algoId', ''),
                    'symbol': order.get('instId', ''),
                    'order_type': order.get('ordType', ''),
                    'side': order.get('side', ''),
                    'size': float(order.get('sz', '0') or '0'),
                    'trigger_price': float(order.get('triggerPx', '0') or '0'),
                    'order_price': float(order.get('orderPx', '0') or '0'),
                    'state': order.get('state', ''),
                    'create_time': order.get('cTime', ''),
                    'update_time': datetime.now()
                })
            
            return orders
            
        except Exception as e:
            logger.warning(f"获取策略订单失败: {e}")
            return []
    
    async def place_grid_order(self, symbol: str, grid_num: int, max_price: float, 
                              min_price: float, investment: float) -> Dict[str, Any]:
        """创建网格策略"""
        try:
            data = {
                'instId': symbol,
                'algoOrdType': 'grid',
                'maxPx': str(max_price),
                'minPx': str(min_price),
                'gridNum': str(grid_num),
                'quoteSz': str(investment)  # 投资金额
            }
            
            result = await self._make_request('POST', '/api/v5/tradingBot/grid/order-algo', data=data)
            
            if result:
                return {
                    'algo_id': result[0].get('algoId', ''),
                    'symbol': symbol,
                    'strategy_type': 'grid',
                    'status': 'created',
                    'create_time': datetime.now()
                }
            
            raise TradingToolError("网格策略创建失败")
            
        except Exception as e:
            logger.error(f"创建网格策略失败: {e}")
            raise TradingToolError(f"创建网格策略失败: {e}")
    
    async def place_dca_order(self, symbol: str, side: str, investment: float,
                             price_ratio: float = 0.05, take_profit_ratio: float = 0.1) -> Dict[str, Any]:
        """创建定投策略(类似马丁格尔)"""
        try:
            data = {
                'instId': symbol,
                'algoOrdType': 'dca',
                'side': side.lower(),
                'quoteSz': str(investment),
                'pxVar': str(price_ratio),  # 价格变动比例
                'tpRatio': str(take_profit_ratio)  # 止盈比例
            }
            
            result = await self._make_request('POST', '/api/v5/tradingBot/recurring/order-algo', data=data)
            
            if result:
                return {
                    'algo_id': result[0].get('algoId', ''),
                    'symbol': symbol,
                    'strategy_type': 'dca',
                    'side': side,
                    'status': 'created',
                    'create_time': datetime.now()
                }
            
            raise TradingToolError("定投策略创建失败")
            
        except Exception as e:
            logger.error(f"创建定投策略失败: {e}")
            raise TradingToolError(f"创建定投策略失败: {e}")
    
    async def get_trading_bot_orders(self, algo_ord_type: str = None) -> List[Dict[str, Any]]:
        """获取交易机器人订单 - 模拟版本（API权限不足时）"""
        try:
            # 由于API权限限制，返回模拟数据用于演示
            logger.info("交易机器人功能需要更高级别的API权限，当前返回模拟数据")
            
            return [
                {
                    'algo_id': 'demo_grid_001',
                    'symbol': 'BTC-USDT-SWAP',
                    'strategy_type': 'grid',
                    'state': 'running',
                    'investment': 1000.0,
                    'profit': 25.50,
                    'profit_rate': 0.0255,
                    'create_time': '2025-08-20T10:00:00Z',
                    'update_time': datetime.now()
                },
                {
                    'algo_id': 'demo_dca_001',
                    'symbol': 'ETH-USDT-SWAP',
                    'strategy_type': 'dca',
                    'state': 'running',
                    'investment': 500.0,
                    'profit': -12.30,
                    'profit_rate': -0.0246,
                    'create_time': '2025-08-21T15:30:00Z',
                    'update_time': datetime.now()
                }
            ]
            
        except Exception as e:
            logger.error(f"获取交易机器人订单失败: {e}")
            return []
    
    async def stop_trading_bot(self, algo_id: str, strategy_type: str) -> bool:
        """停止交易机器人"""
        try:
            data = {
                'algoId': algo_id
            }
            
            if strategy_type == 'grid':
                endpoint = '/api/v5/tradingBot/grid/stop-order-algo'
            elif strategy_type == 'dca':
                endpoint = '/api/v5/tradingBot/recurring/stop-order-algo'
            else:
                raise TradingToolError(f"不支持的策略类型: {strategy_type}")
            
            await self._make_request('POST', endpoint, data=data)
            return True
            
        except Exception as e:
            logger.error(f"停止交易机器人失败: {e}")
            return False
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            # 尝试获取服务器时间来检查API连接
            result = await self._make_request('GET', '/api/v5/public/time')
            return bool(result)
            
        except Exception as e:
            logger.error(f"OKX API健康检查失败: {e}")
            return False
    
    async def get_instrument_info(self, symbol: str = None, inst_type: str = 'SWAP') -> Dict[str, Any]:
        """获取合约详细信息，包括费率间隔"""
        try:
            params = {
                'instType': inst_type,
                'state': 'live'
            }
            
            if symbol:
                params['instId'] = symbol
            
            result = await self._make_request('GET', '/api/v5/public/instruments', params=params)
            
            if not result:
                return {}
            
            instruments_info = {}
            for instrument in result:
                inst_id = instrument.get('instId', '')
                if not inst_id:
                    continue
                
                # 计算费率间隔（小时），OKX默认8小时
                funding_interval_hours = 8
                
                # 特殊币种的费率间隔（根据实际情况调整）
                if 'BTC' in inst_id or 'ETH' in inst_id:
                    funding_interval_hours = 8
                elif any(x in inst_id for x in ['DOGE', 'SHIB', 'PEPE']):
                    funding_interval_hours = 4  # 某些meme币可能是4小时
                else:
                    funding_interval_hours = 8  # 默认8小时
                
                instruments_info[inst_id] = {
                    'symbol': inst_id,
                    'base_currency': instrument.get('baseCcy', ''),
                    'quote_currency': instrument.get('quoteCcy', ''),
                    'settle_currency': instrument.get('settleCcy', ''),
                    'contract_value': float(instrument.get('ctVal', '1')),
                    'min_size': float(instrument.get('minSz', '1')),
                    'tick_size': float(instrument.get('tickSz', '0.01')),
                    'funding_interval_hours': funding_interval_hours,
                    'funding_times_per_day': 24 // funding_interval_hours,
                    'state': instrument.get('state', ''),
                    'listing_time': instrument.get('listTime', ''),
                    'expiry_time': instrument.get('expTime', ''),
                }
            
            return instruments_info if not symbol else instruments_info.get(symbol, {})
            
        except Exception as e:
            logger.error(f"获取合约信息失败: {e}")
            return {}

    async def get_active_symbols(self, inst_type: str = 'SWAP') -> List[str]:
        """获取活跃交易对列表"""
        try:
            params = {
                'instType': inst_type,  # SWAP永续合约, SPOT现货
                'state': 'live'  # 只获取正常交易的
            }
            
            result = await self._make_request('GET', '/api/v5/public/instruments', params=params)
            
            symbols = []
            for instrument in result:
                if instrument.get('state') == 'live':
                    symbols.append(instrument.get('instId', ''))
            
            # 过滤掉空字符串并返回前50个活跃合约
            active_symbols = [s for s in symbols if s][:50]
            return active_symbols
            
        except Exception as e:
            logger.error(f"获取活跃交易对失败: {e}")
            # 返回一些常见的交易对作为备选（已移除无效的MATIC）
            return [
                'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP',
                'BNB-USDT-SWAP', 'XRP-USDT-SWAP', 'ADA-USDT-SWAP',
                'DOGE-USDT-SWAP', 'DOT-USDT-SWAP', 'AVAX-USDT-SWAP',
                'LINK-USDT-SWAP'
            ]
    
    async def get_all_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据 - 兼容方法名"""
        return await self.get_tickers(inst_type)
    
    async def get_multi_timeframe_klines(self, symbol: str, timeframes: List[str], limit: int = 100) -> Dict[str, List[dict]]:
        """
        获取多周期K线数据
        
        Args:
            symbol: 交易对
            timeframes: 时间周期列表，如['1d', '4h', '1h', '15m']
            limit: 每个周期的K线数量限制
            
        Returns:
            多周期K线数据字典
        """
        try:
            result = {}
            
            # 并发获取各周期数据
            tasks = []
            for timeframe in timeframes:
                task = self.get_kline_data(symbol, timeframe, limit)
                tasks.append(task)
            
            # 等待所有请求完成
            kline_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, klines in enumerate(kline_results):
                timeframe = timeframes[i]
                
                if isinstance(klines, Exception):
                    logger.warning(f"获取{symbol} {timeframe}周期K线失败: {klines}")
                    result[timeframe] = []
                elif klines:
                    result[timeframe] = klines
                else:
                    result[timeframe] = []
            
            return result
            
        except Exception as e:
            logger.error(f"获取{symbol}多周期K线数据失败: {e}")
            # 返回空数据结构
            return {timeframe: [] for timeframe in timeframes}