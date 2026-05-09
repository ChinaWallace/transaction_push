# -*- coding: utf-8 -*-
"""
币安混合服务
Binance Hybrid Service - 智能选择最佳数据源的币安交易所服务
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.exchanges.base.exchange_interface import ExchangeInterface
from app.services.exchanges.base.hybrid_service_base import HybridServiceBase
from app.services.exchanges.binance.binance_service import BinanceService
from app.services.exchanges.binance.binance_realtime_data_manager import BinanceRealtimeDataManager
from app.services.exchanges.binance.binance_data_converter import BinanceDataConverter
from app.services.exchanges.binance.binance_error_handler import get_binance_error_handler
from app.utils.exceptions import TradingToolError, APIConnectionError

logger = get_logger(__name__)
settings = get_settings()


class BinanceHybridService(HybridServiceBase, ExchangeInterface):
    """
    币安混合服务 - 智能选择最佳数据源
    Binance Hybrid Service - Intelligently selects the best data source
    
    实现智能数据源选择策略：
    1. 优先使用WebSocket获取实时数据（ticker、资金费率等）
    2. WebSocket不可用时自动回退到REST API
    3. 历史数据、账户操作等直接使用REST API
    4. 提供统一的错误处理和重试机制
    """
    
    def __init__(self):
        super().__init__()
        
        # 服务组件
        self.rest_service = BinanceService()
        self.realtime_manager: Optional[BinanceRealtimeDataManager] = None
        self.error_handler = get_binance_error_handler()
        
        # 数据适配器
        # 主要交易对列表（用于预订阅）
        self.major_symbols = [
            'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'BNB-USDT-SWAP',
            'ADA-USDT-SWAP', 'SOL-USDT-SWAP', 'XRP-USDT-SWAP',
            'DOGE-USDT-SWAP', 'MATIC-USDT-SWAP', 'DOT-USDT-SWAP',
            'AVAX-USDT-SWAP'
        ]
        
        # 数据缓存配置
        self.cache_ttl = 30  # 缓存有效期（秒）
        self.last_cache_update: Dict[str, datetime] = {}
        
        logger.info("🔄 币安混合服务初始化完成")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        # 确保服务已初始化
        if not self.is_initialized:
            await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        # 清理资源（如果需要）
        if exc_type:
            logger.error(f"币安混合服务异常: {exc_type.__name__}: {exc_val}")
        # 注意：这里不需要关闭服务，因为它可能被其他地方使用
    
    async def initialize(self) -> None:
        """初始化币安混合服务"""
        if self.is_initialized:
            logger.debug("🔄 币安混合服务已初始化")
            return
        
        try:
            logger.info("🚀 初始化币安混合服务...")
            
            # 首先设置REST API服务
            await self._setup_rest_api()
            
            # 如果启用WebSocket，则设置WebSocket服务
            if self.is_websocket_enabled:
                await self._setup_websocket()
            
            # 预订阅主要交易对
            if self.is_websocket_enabled and self.is_websocket_connected:
                await self._presubscribe_major_symbols()
            
            self.is_initialized = True
            logger.info("✅ 币安混合服务初始化成功")
            
        except Exception as e:
            logger.error(f"❌ 币安混合服务初始化失败: {e}")
            # 如果WebSocket初始化失败，禁用WebSocket但继续使用REST API
            self.is_websocket_enabled = False
            self.is_websocket_connected = False
            
            # 确保REST API可用
            if not hasattr(self, 'rest_service') or not self.rest_service:
                raise TradingToolError(f"币安混合服务初始化失败: {e}")
            
            self.is_initialized = True
            logger.warning("⚠️ 币安混合服务以REST API模式初始化")
    
    async def _setup_websocket(self) -> None:
        """设置WebSocket连接"""
        try:
            logger.info("🔌 设置币安WebSocket服务...")
            
            # 检查WebSocket是否启用
            if not settings.binance_enable_websocket:
                logger.info("ℹ️ 币安WebSocket已禁用，跳过WebSocket设置")
                self.is_websocket_enabled = False
                self.is_websocket_connected = False
                return
            
            # 创建实时数据管理器
            self.realtime_manager = BinanceRealtimeDataManager()
            await self.realtime_manager.initialize()

            if self.realtime_manager.ws_service and not self.realtime_manager.ws_service.is_connected:
                await self.realtime_manager.ws_service.subscribe_symbol_ticker("BTCUSDT")
            
            # 检查WebSocket连接状态
            if self.realtime_manager.ws_service and self.realtime_manager.ws_service.is_connected:
                self.is_websocket_connected = True
                logger.info("✅ 币安WebSocket连接建立成功")
            else:
                logger.warning("⚠️ 币安WebSocket连接建立失败，将使用REST API模式")
                self.is_websocket_connected = False
                
        except Exception as e:
            logger.warning(f"⚠️ 设置币安WebSocket失败: {e}")
            logger.info("ℹ️ 将使用REST API模式继续运行")
            self.is_websocket_connected = False
            self.is_websocket_enabled = False
            # 不抛出异常，允许服务以REST API模式运行
    
    async def _setup_rest_api(self) -> None:
        """设置REST API服务"""
        try:
            logger.info("🌐 设置币安REST API服务...")
            
            # REST API服务已在__init__中创建，这里进行健康检查
            await self._check_rest_api_health()
            
            logger.info("✅ 币安REST API服务设置成功")
            
        except Exception as e:
            logger.error(f"❌ 设置币安REST API失败: {e}")
            raise TradingToolError(f"币安REST API服务不可用: {e}")
    
    async def _check_rest_api_health(self) -> None:
        """检查REST API健康状态"""
        try:
            # 尝试获取一个简单的数据来验证API可用性
            result = await self.rest_service.get_current_price('BTC-USDT-SWAP')
            if result is None:
                raise APIConnectionError("REST API返回空数据")
            
            logger.debug("✅ 币安REST API健康检查通过")
            
        except Exception as e:
            logger.error(f"❌ 币安REST API健康检查失败: {e}")
            raise APIConnectionError(f"币安REST API不可用: {e}")
    
    async def _presubscribe_major_symbols(self) -> None:
        """预订阅主要交易对的实时数据"""
        if not self.realtime_manager:
            return
        
        try:
            logger.info(f"📡 预订阅主要交易对: {len(self.major_symbols)} 个")
            
            # 订阅ticker数据
            await self.realtime_manager.subscribe_ticker(self.major_symbols)
            
            # 订阅资金费率数据
            await self.realtime_manager.subscribe_funding_rates(self.major_symbols)
            
            # 订阅所有交易对的资金费率（批量获取）
            await self.realtime_manager.subscribe_all_funding_rates()
            
            logger.info("✅ 主要交易对预订阅完成")
            
        except Exception as e:
            logger.error(f"❌ 预订阅主要交易对失败: {e}")
    
    async def cleanup(self) -> None:
        """清理资源"""
        try:
            logger.info("🧹 清理币安混合服务资源...")
            
            # 清理实时数据管理器
            if self.realtime_manager:
                await self.realtime_manager.cleanup()
                self.realtime_manager = None
            
            # 清理缓存
            self.last_cache_update.clear()
            
            # 重置状态
            self.is_initialized = False
            self.is_websocket_connected = False
            
            logger.info("✅ 币安混合服务资源清理完成")
            
        except Exception as e:
            logger.error(f"❌ 清理币安混合服务资源异常: {e}")
    
    # ==================== 市场数据接口实现 Market Data Interface Implementation ====================
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            # 优先使用WebSocket数据
            if await self._check_websocket_health() and self.realtime_manager:
                ticker_data = self.realtime_manager.get_latest_ticker(symbol)
                if ticker_data and self._is_data_fresh(f"ticker_{symbol}", ticker_data.timestamp):
                    logger.debug(f"🔌 WebSocket获取价格: {symbol} = {ticker_data.price}")
                    return ticker_data.price
            
            # 回退到REST API，使用错误处理器
            return await self.error_handler.handle_error_with_retry(
                self.rest_service.get_current_price,
                f"get_current_price_{symbol}",
                symbol
            )
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol}当前价格失败: {e}")
            return None
    
    async def get_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ticker数据 - 返回统一格式"""
        try:
            # 优先使用WebSocket数据
            if await self._check_websocket_health() and self.realtime_manager:
                ticker_data = self.realtime_manager.get_latest_ticker(symbol)
                if ticker_data and self._is_data_fresh(f"ticker_{symbol}", ticker_data.timestamp):
                    logger.debug(f"🔌 WebSocket获取ticker: {symbol}")
                    return {
                        'symbol': ticker_data.symbol,
                        'price': ticker_data.price,
                        'volume_24h': ticker_data.volume_24h,
                        'change_24h': ticker_data.change_24h,
                        'change_percent_24h': ticker_data.change_24h,
                        'high_24h': ticker_data.high_24h,
                        'low_24h': ticker_data.low_24h,
                        'bid_price': ticker_data.bid_price,
                        'ask_price': ticker_data.ask_price,
                        'timestamp': ticker_data.timestamp,
                        'source': 'websocket'
                    }
            
            # 回退到REST API，获取原始数据并使用适配器转换
            return await self._fallback_to_rest(
                self.rest_service.get_ticker_data,
                f"get_ticker_data_{symbol}",
                symbol
            )

            raw_data = await self._fallback_to_rest(
                self.rest_service.get_raw_ticker_data,
                f"get_raw_ticker_data_{symbol}",
                symbol
            )
            
            if not raw_data:
                logger.warning(f"⚠️ 获取{symbol}原始ticker数据为空")
                return None
            
            # 使用适配器转换为统一格式
            try:
                unified_ticker = None
                result = unified_ticker.to_dict()
                logger.debug(f"✅ 成功适配ticker数据: {symbol}")
                return result
            except Exception as adapter_error:
                logger.warning(f"⚠️ ticker数据适配失败，回退到原始方法: {adapter_error}")
                # 如果适配器失败，回退到原始方法
                return await self._fallback_to_rest(
                    self.rest_service.get_ticker_data,
                    f"get_ticker_data_{symbol}",
                    symbol
                )
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol} ticker数据失败: {e}")
            return None
    
    async def get_kline_data(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据"""
        try:
            # 转换时间周期格式
            binance_timeframe = BinanceDataConverter.convert_timeframe_to_binance(timeframe)
            
            # K线数据优先使用REST API（更可靠的历史数据）
            raw_data = await self._fallback_to_rest(
                self.rest_service.get_kline_data,
                f"get_kline_data_{symbol}_{timeframe}",
                symbol, binance_timeframe, limit
            )
            
            # 如果REST API返回的数据已经是转换后的格式，直接返回
            if raw_data and len(raw_data) > 0 and isinstance(raw_data[0], dict):
                return raw_data
            
            return raw_data
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol} K线数据失败: {e}")
            return []
    
    async def get_funding_rate(self, symbol: str = None) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """获取资金费率 - 返回统一格式"""
        try:
            # 对于批量获取费率，直接使用REST API，因为WebSocket数据通常不完整
            if symbol is None:
                logger.debug("📡 批量获取费率，直接使用REST API")
            else:
                # 单个交易对可以尝试WebSocket
                if await self._check_websocket_health() and self.realtime_manager:
                    funding_data = self.realtime_manager.get_latest_funding_rate(symbol)
                    if funding_data and self._is_data_fresh(f"funding_rate_{symbol}", funding_data.timestamp):
                        logger.debug(f"🔌 WebSocket获取资金费率: {symbol}")
                        return {
                            'symbol': funding_data.symbol,
                            'funding_rate': funding_data.funding_rate,
                            'next_funding_time': funding_data.next_funding_time,
                            'timestamp': funding_data.timestamp,
                            'source': 'websocket'
                        }
            
            # 回退到REST API，获取原始数据并使用适配器转换
            return await self._fallback_to_rest(
                self.rest_service.get_funding_rate,
                f"get_funding_rate_{symbol or 'all'}",
                symbol
            )

            raw_data = await self._fallback_to_rest(
                self.rest_service.get_raw_funding_rate,
                f"get_raw_funding_rate_{symbol or 'all'}",
                symbol
            )
            
            if not raw_data:
                logger.warning(f"⚠️ 获取{symbol if symbol else '所有'}原始资金费率数据为空")
                return None
            
            # 使用适配器转换为统一格式
            try:
                if isinstance(raw_data, list):
                    # 批量处理
                    unified_rates = []
                    result = [rate.to_dict() for rate in unified_rates]
                    logger.debug(f"✅ 成功适配资金费率数据: {len(result)} 个")
                    return result
                else:
                    # 单个处理
                    unified_rate = None
                    result = unified_rate.to_dict()
                    logger.debug(f"✅ 成功适配资金费率数据: {symbol}")
                    return result
            except Exception as adapter_error:
                logger.warning(f"⚠️ 资金费率数据适配失败，回退到原始方法: {adapter_error}")
                # 如果适配器失败，回退到原始方法
                return await self._fallback_to_rest(
                    self.rest_service.get_funding_rate,
                    f"get_funding_rate_{symbol or 'all'}",
                    symbol
                )
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol if symbol else '所有'}资金费率失败: {e}")
            return None
    
    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓量数据"""
        try:
            # 持仓量数据直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.get_open_interest,
                f"get_open_interest_{symbol}",
                symbol
            )
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol}持仓量失败: {e}")
            return None
    
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近交易数据"""
        try:
            # 优先使用WebSocket数据（如果有实时交易数据）
            if await self._check_websocket_health() and self.realtime_manager:
                trades_data = self.realtime_manager.get_latest_trades(symbol, limit)
                if trades_data:
                    logger.debug(f"🔌 WebSocket获取交易数据: {symbol} ({len(trades_data)} 条)")
                    return [
                        {
                            'symbol': trade.symbol,
                            'side': trade.side,
                            'size': trade.size,
                            'price': trade.price,
                            'trade_id': trade.trade_id,
                            'timestamp': datetime.fromtimestamp(trade.timestamp / 1000),
                            'source': 'websocket'
                        }
                        for trade in trades_data
                    ]
            
            # 回退到REST API
            return await self._fallback_to_rest(
                self.rest_service.get_recent_trades,
                f"get_recent_trades_{symbol}",
                symbol, limit
            )
            
        except Exception as e:
            logger.error(f"❌ 获取{symbol}最近交易数据失败: {e}")
            return []
    
    async def get_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据"""
        try:
            # 优先使用WebSocket数据
            if await self._check_websocket_health() and self.realtime_manager:
                all_tickers = self.realtime_manager.get_all_tickers()
                if all_tickers:
                    logger.debug(f"🔌 WebSocket获取所有ticker: {len(all_tickers)} 个")
                    return [
                        {
                            'symbol': ticker.symbol,
                            'price': ticker.price,
                            'volume_24h': ticker.volume_24h,
                            'change_24h': ticker.change_24h,
                            'change_percent_24h': ticker.change_24h,
                            'high_24h': ticker.high_24h,
                            'low_24h': ticker.low_24h,
                            'bid_price': ticker.bid_price,
                            'ask_price': ticker.ask_price,
                            'timestamp': ticker.timestamp,
                            'source': 'websocket'
                        }
                        for ticker in all_tickers.values()
                    ]
            
            # 回退到REST API
            return await self._fallback_to_rest(
                self.rest_service.get_tickers,
                f"get_tickers_{inst_type}",
                inst_type
            )
            
        except Exception as e:
            logger.error(f"❌ 获取{inst_type} ticker数据失败: {e}")
            return []

    async def get_all_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据 - get_tickers的别名"""
        return await self.get_tickers(inst_type)
    
    async def get_all_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有交易对列表 - 返回统一格式"""
        try:
            # 获取币安原始数据
            raw_data = await self._fallback_to_rest(
                self.rest_service.get_raw_instruments,
                f"get_raw_instruments_{inst_type}",
                inst_type
            )
            
            if not raw_data:
                logger.warning(f"⚠️ 获取币安原始交易对数据为空: {inst_type}")
                return []
            
            # Keep Binance exchangeInfo in its native shape.
            logger.info(f"Returning raw Binance instruments without adapter conversion: {len(raw_data)}")
            return raw_data
            
        except Exception as e:
            logger.error(f"❌ 获取{inst_type}交易对列表失败: {e}")
            # 如果适配器失败，尝试回退到原始方法
            try:
                logger.info("🔄 回退到原始方法获取交易对列表")
                return await self._fallback_to_rest(
                    self.rest_service.get_all_instruments,
                    f"get_all_instruments_{inst_type}",
                    inst_type
                )
            except Exception as fallback_error:
                logger.error(f"❌ 回退方法也失败: {fallback_error}")
                return []
    
    # ==================== 账户数据接口实现 Account Data Interface Implementation ====================
    
    async def get_account_balance(self) -> Dict[str, Any]:
        """获取账户余额"""
        try:
            # 账户数据直接使用REST API，使用错误处理器
            return await self.error_handler.handle_error_with_retry(
                self.rest_service.get_account_balance,
                "get_account_balance"
            )
            
        except Exception as e:
            logger.error(f"❌ 获取账户余额失败: {e}")
            raise TradingToolError(f"获取账户余额失败: {e}")
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓信息 - 返回统一格式"""
        try:
            # 获取原始持仓数据
            return await self._fallback_to_rest(
                self.rest_service.get_positions,
                "get_positions"
            )

            raw_data = await self._fallback_to_rest(
                self.rest_service.get_raw_positions,
                "get_raw_positions"
            )
            
            if not raw_data:
                logger.warning("⚠️ 获取原始持仓数据为空")
                return []
            
            # 使用适配器转换为统一格式
            try:
                unified_positions = []
                result = [position.to_dict() for position in unified_positions]
                logger.info(f"✅ 成功适配持仓数据: {len(result)} 个")
                return result
            except Exception as adapter_error:
                logger.warning(f"⚠️ 持仓数据适配失败，回退到原始方法: {adapter_error}")
                # 如果适配器失败，回退到原始方法
                return await self._fallback_to_rest(
                    self.rest_service.get_positions,
                    "get_positions"
                )
            
        except Exception as e:
            logger.error(f"❌ 获取持仓信息失败: {e}")
            raise TradingToolError(f"获取持仓信息失败: {e}")
    
    async def get_spot_balances(self) -> List[Dict[str, Any]]:
        """获取现货余额"""
        try:
            # 现货余额直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.get_spot_balances,
                "get_spot_balances"
            )
            
        except Exception as e:
            logger.error(f"❌ 获取现货余额失败: {e}")
            return []
    
    # ==================== 交易接口实现 Trading Interface Implementation ====================
    
    async def place_order(self, symbol: str, side: str, size: float, 
                         order_type: str = 'market', price: float = None,
                         leverage: float = None) -> Dict[str, Any]:
        """下单"""
        try:
            # 交易操作直接使用REST API，使用错误处理器
            return await self.error_handler.handle_error_with_retry(
                self.rest_service.place_order,
                f"place_order_{symbol}",
                symbol, side, size, order_type, price, leverage
            )
            
        except Exception as e:
            logger.error(f"❌ 下单失败: {symbol} {side} {size} - {e}")
            raise TradingToolError(f"下单失败: {e}")
    
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """取消订单"""
        try:
            # 交易操作直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.cancel_order,
                f"cancel_order_{symbol}",
                symbol, order_id
            )
            
        except Exception as e:
            logger.error(f"❌ 取消订单失败: {symbol} {order_id} - {e}")
            raise TradingToolError(f"取消订单失败: {e}")
    
    async def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """获取订单状态"""
        try:
            # 交易操作直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.get_order_status,
                f"get_order_status_{symbol}",
                symbol, order_id
            )
            
        except Exception as e:
            logger.error(f"❌ 获取订单状态失败: {symbol} {order_id} - {e}")
            raise TradingToolError(f"获取订单状态失败: {e}")
    
    # ==================== 实时数据订阅接口实现 Real-time Data Subscription Interface Implementation ====================
    
    async def subscribe_symbol_realtime(self, symbol: str) -> bool:
        """订阅单个交易对的实时数据"""
        try:
            if not await self._check_websocket_health() or not self.realtime_manager:
                logger.warning(f"⚠️ WebSocket不可用，无法订阅实时数据: {symbol}")
                return False
            
            # 订阅ticker和资金费率
            ticker_success = await self.realtime_manager.subscribe_ticker([symbol])
            funding_success = await self.realtime_manager.subscribe_funding_rates([symbol])
            
            success = ticker_success or funding_success
            if success:
                logger.info(f"✅ 订阅实时数据成功: {symbol}")
            else:
                logger.error(f"❌ 订阅实时数据失败: {symbol}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 订阅{symbol}实时数据异常: {e}")
            return False
    
    async def subscribe_symbols_realtime(self, symbols: List[str]) -> Dict[str, bool]:
        """批量订阅多个交易对的实时数据"""
        try:
            if not await self._check_websocket_health() or not self.realtime_manager:
                logger.warning("⚠️ WebSocket不可用，无法批量订阅实时数据")
                return {symbol: False for symbol in symbols}
            
            # 批量订阅ticker和资金费率
            ticker_success = await self.realtime_manager.subscribe_ticker(symbols)
            funding_success = await self.realtime_manager.subscribe_funding_rates(symbols)
            
            # 返回每个交易对的订阅结果
            results = {}
            for symbol in symbols:
                # 如果ticker或资金费率任一订阅成功，则认为该交易对订阅成功
                results[symbol] = ticker_success or funding_success
            
            success_count = sum(1 for success in results.values() if success)
            logger.info(f"📡 批量订阅完成: {success_count}/{len(symbols)} 成功")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 批量订阅实时数据异常: {e}")
            return {symbol: False for symbol in symbols}
    
    # ==================== 服务状态接口实现 Service Status Interface Implementation ====================
    
    def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        status = {
            'is_initialized': self.is_initialized,
            'websocket_enabled': self.is_websocket_enabled,
            'websocket_connected': self.is_websocket_connected,
            'rest_api_available': True,  # REST API总是可用的
            'subscribed_symbols_count': 0,
            'last_update': datetime.now(),
            'data_source_stats': self.get_data_source_statistics()
        }
        
        # 获取订阅信息
        if self.realtime_manager:
            status['subscribed_symbols_count'] = len(self.realtime_manager.get_subscribed_symbols())
            status['connection_status'] = self.realtime_manager.get_connection_status()
        
        return status
    
    def get_subscribed_symbols(self) -> List[str]:
        """获取当前订阅的交易对列表"""
        if self.realtime_manager:
            return self.realtime_manager.get_subscribed_symbols()
        return []
    
    # ==================== 辅助方法 Helper Methods ====================
    
    def _is_data_fresh(self, data_key: str, data_timestamp: datetime, ttl_seconds: int = None) -> bool:
        """检查数据是否新鲜"""
        if ttl_seconds is None:
            ttl_seconds = self.cache_ttl
        
        now = datetime.now()
        
        # 检查数据时间戳
        if (now - data_timestamp).total_seconds() > ttl_seconds:
            return False
        
        # 更新缓存时间
        self.last_cache_update[data_key] = now
        return True
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        获取错误统计信息
        Get error statistics
        
        Returns:
            Dict[str, Any]: 错误统计信息
        """
        stats = self.error_handler.get_error_statistics()
        stats.update({
            'websocket_error_count': self.websocket_error_count,
            'last_websocket_error': str(self.last_websocket_error) if self.last_websocket_error else None,
            'is_websocket_enabled': self.is_websocket_enabled,
            'is_websocket_connected': self.is_websocket_connected
        })
        return stats
    
    def reset_error_statistics(self) -> None:
        """
        重置错误统计
        Reset error statistics
        """
        self.error_handler.reset_statistics()
        self.websocket_error_count = 0
        self.last_websocket_error = None
    
    # ==================== 方法别名 Method Aliases ====================
    # 为了兼容测试脚本和其他调用方，提供方法别名
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ticker数据 - get_ticker_data的别名"""
        return await self.get_ticker_data(symbol)
    
    async def get_klines(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据 - get_kline_data的别名"""
        return await self.get_kline_data(symbol, timeframe, limit)
    
    async def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict[str, Any]]:
        """获取订单簿数据"""
        try:
            # 订单簿数据直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.get_order_book,
                f"get_order_book_{symbol}",
                symbol, limit
            )
        except Exception as e:
            logger.error(f"❌ 获取{symbol}订单簿失败: {e}")
            return None
    
    async def get_24hr_stats(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取24小时统计数据"""
        try:
            # 24小时统计数据直接使用REST API
            return await self._fallback_to_rest(
                self.rest_service.get_24hr_stats,
                f"get_24hr_stats_{symbol}",
                symbol
            )
        except Exception as e:
            logger.error(f"❌ 获取{symbol} 24小时统计失败: {e}")
            return None
        logger.info("📊 币安混合服务错误统计已重置")
