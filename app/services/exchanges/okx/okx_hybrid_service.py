# -*- coding: utf-8 -*-
"""
OKX混合服务
OKX Hybrid Service - 智能切换REST API和WebSocket，提供最佳性能
"""

import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from app.core.logging import get_logger
from app.services.exchanges.okx.okx_service import OKXService
from app.services.exchanges.okx.okx_realtime_data_manager import get_realtime_data_manager
from app.services.exchanges.base.exchange_interface import ExchangeInterface
from app.services.exchanges.base.hybrid_service_base import HybridServiceBase
from app.services.exchanges.adapters.okx_adapter import OKXDataAdapter
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class OKXHybridService(HybridServiceBase, ExchangeInterface):
    """
    OKX混合服务 - 智能选择最佳数据源
    
    策略：
    1. 实时ticker和资金费率使用WebSocket
    2. K线数据使用REST API（WebSocket频道不可用）
    3. 历史数据和复杂查询使用REST API
    4. 账户操作和交易执行使用REST API
    5. 自动回退机制：WebSocket不可用时使用REST API
    """
    
    def __init__(self):
        # 初始化基类
        super().__init__()
        
        self.rest_service = OKXService()
        self.data_adapter = OKXDataAdapter()  # 新增适配器
        self.realtime_manager = None
        self.is_websocket_enabled = settings.okx_config.get('enable_websocket', True)
        self.websocket_timeout = 5.0  # WebSocket数据超时时间
        
        # 主要交易对列表 (初始化时为预设列表，启动后会动态获取所有活跃SWAP合约)
        self.major_symbols = [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", 
            "DOGE-USDT-SWAP", "XRP-USDT-SWAP", "ADA-USDT-SWAP",
            "AVAX-USDT-SWAP", "DOT-USDT-SWAP", "LINK-USDT-SWAP",
            "UNI-USDT-SWAP"  # 预设列表，仅在无法获取完整列表时使用
        ]
        
        logger.info("🔄 OKX混合服务初始化完成")
    
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
            logger.error(f"OKX混合服务异常: {exc_type.__name__}: {exc_val}")
        # 注意：这里不需要关闭服务，因为它可能被其他地方使用

    async def initialize(self):
        """初始化混合服务"""
        if self.is_initialized:
            return
        
        try:
            if self.is_websocket_enabled:
                # 初始化实时数据管理器
                self.realtime_manager = await get_realtime_data_manager()
                
                # 预订阅主要交易对的实时数据
                await self._presubscribe_major_symbols()
                
                logger.info("✅ WebSocket实时数据服务已启用")
            else:
                logger.info("📴 WebSocket服务已禁用，使用REST API模式")
            
            self.is_initialized = True
            logger.info("✅ OKX混合服务初始化成功")
            
        except Exception as e:
            logger.error(f"❌ OKX混合服务初始化失败: {e}")
            # 回退到纯REST模式
            self.is_websocket_enabled = False
            self.realtime_manager = None
            self.is_initialized = True
            logger.warning("⚠️ 回退到REST API模式")

    async def _setup_websocket(self) -> None:
        """设置WebSocket连接"""
        try:
            if self.realtime_manager is None:
                self.realtime_manager = await get_realtime_data_manager()
            self.is_websocket_connected = True
            logger.info("✅ WebSocket连接设置完成")
        except Exception as e:
            logger.error(f"❌ WebSocket连接设置失败: {e}")
            self.is_websocket_connected = False
            raise

    async def _setup_rest_api(self) -> None:
        """设置REST API服务"""
        try:
            # REST API服务已在__init__中初始化
            logger.info("✅ REST API服务设置完成")
        except Exception as e:
            logger.error(f"❌ REST API服务设置失败: {e}")
            raise

    async def _validate_symbols(self, symbols: List[str]) -> List[str]:
        """验证交易对是否有效"""
        try:
            # 获取所有活跃的SWAP合约
            instruments = await self.rest_service.get_all_instruments('SWAP')
            if not instruments:
                logger.warning("无法获取交易对列表，使用原始列表")
                return symbols
            
            # 提取活跃的交易对ID
            active_symbols = {
                inst['instId'] for inst in instruments 
                if inst.get('state') == 'live'
            }
            
            # 过滤有效的交易对
            valid_symbols = [symbol for symbol in symbols if symbol in active_symbols]
            invalid_symbols = [symbol for symbol in symbols if symbol not in active_symbols]
            
            if invalid_symbols:
                logger.warning(f"⚠️ 发现无效或已下线的交易对: {invalid_symbols}")
            
            if valid_symbols:
                logger.info(f"✅ 验证通过的交易对: {len(valid_symbols)}/{len(symbols)} 个")
            
            return valid_symbols
            
        except Exception as e:
            logger.error(f"验证交易对时出错: {e}")
            return symbols  # 出错时返回原始列表

    async def _presubscribe_major_symbols(self):
        """预订阅所有USDT-SWAP交易对（批量订阅策略）"""
        try:
            if not self.realtime_manager:
                return
            
            logger.info("📡 批量订阅所有USDT-SWAP交易对...")
            
            # 获取所有活跃的SWAP合约
            instruments = await self.rest_service.get_all_instruments('SWAP')
            if not instruments:
                logger.warning("⚠️ 无法获取交易对列表，使用预设的主要交易对")
                # 回退到预设列表并验证
                valid_symbols = await self._validate_symbols(self.major_symbols)
                if valid_symbols:
                    self.major_symbols = valid_symbols
                else:
                    logger.error("❌ 无法获取任何有效的交易对")
                    return
            else:
                # 提取所有活跃的交易对
                all_active_symbols = [
                    inst['instId'] for inst in instruments 
                    if inst.get('state') == 'live'
                ]
                
                if not all_active_symbols:
                    logger.warning("⚠️ 没有找到活跃的SWAP交易对")
                    return
                
                # 批量订阅策略：订阅所有活跃的USDT-SWAP交易对
                usdt_swap_symbols = [
                    symbol for symbol in all_active_symbols 
                    if symbol.endswith('-USDT-SWAP')
                ]
                
                if not usdt_swap_symbols:
                    # 如果没有USDT-SWAP，则使用所有活跃交易对
                    usdt_swap_symbols = all_active_symbols
                
                self.major_symbols = usdt_swap_symbols
                logger.info(f"📋 批量订阅所有USDT-SWAP交易对: {len(usdt_swap_symbols)} 个（总共 {len(all_active_symbols)} 个可用）")
            
            # 批量订阅ticker数据
            ticker_success = await self.realtime_manager.subscribe_ticker(self.major_symbols)
            logger.info(f"📊 Ticker订阅完成: {len(self.major_symbols)} 个交易对")
            
            # 批量订阅资金费率
            funding_success = await self.realtime_manager.subscribe_funding_rates(self.major_symbols)
            logger.info(f"💰 资金费率订阅完成: {len(self.major_symbols)} 个交易对")
            
            if ticker_success and funding_success:
                logger.info(f"🎉 批量订阅成功: 总共 {len(self.major_symbols) * 2} 个频道")
            else:
                logger.warning(f"⚠️ 部分订阅失败: ticker={ticker_success}, funding={funding_success}")
            
            logger.info(f"✅ 批量预订阅完成: {len(self.major_symbols)} 个USDT-SWAP交易对")
            
        except Exception as e:
            logger.error(f"❌ 预订阅失败: {e}")
            # 出错时回退到预设的主要交易对
            try:
                valid_symbols = await self._validate_symbols(self.major_symbols)
                if valid_symbols:
                    self.major_symbols = valid_symbols
                    await self.realtime_manager.subscribe_ticker(self.major_symbols)
                    await self.realtime_manager.subscribe_funding_rates(self.major_symbols)
                    logger.info(f"🔄 回退订阅完成: {len(self.major_symbols)} 个交易对")
            except Exception as fallback_error:
                logger.error(f"❌ 回退订阅也失败: {fallback_error}")

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格 - 优先使用WebSocket"""
        if not self.is_initialized:
            await self.initialize()
        
        # 优先尝试WebSocket数据
        if self.is_websocket_enabled and self.realtime_manager:
            try:
                price = self.realtime_manager.get_latest_price(symbol)
                if price is not None:
                    logger.debug(f"🔌 WebSocket获取价格: {symbol} = ${price:.4f}")
                    return price
            except Exception as e:
                logger.warning(f"⚠️ WebSocket获取价格失败: {e}")
        
        # 回退到REST API
        try:
            async with self.rest_service:
                price = await self.rest_service.get_current_price(symbol)
                if price:
                    logger.debug(f"🌐 REST API获取价格: {symbol} = ${price:.4f}")
                return price
        except Exception as e:
            logger.error(f"❌ REST API获取价格失败: {e}")
            return None

    async def get_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ticker数据 - 优先使用WebSocket"""
        if not self.is_initialized:
            await self.initialize()
        
        # 优先尝试WebSocket数据
        if self.is_websocket_enabled and self.realtime_manager:
            try:
                ticker = self.realtime_manager.get_latest_ticker(symbol)
                if ticker:
                    # 转换为标准格式
                    return {
                        'instId': symbol,
                        'last': ticker.price,
                        'vol24h': ticker.volume_24h,
                        'sodUtc8': ticker.change_24h,
                        'bidPx': ticker.bid_price,
                        'askPx': ticker.ask_price,
                        'high24h': ticker.high_24h,
                        'low24h': ticker.low_24h,
                        'open24h': ticker.open_24h,
                        'ts': int(ticker.timestamp.timestamp() * 1000),
                        'source': 'websocket'
                    }
            except Exception as e:
                logger.warning(f"⚠️ WebSocket获取ticker失败: {e}")
        
        # 回退到REST API
        try:
            async with self.rest_service:
                result = await self.rest_service._make_request(
                    'GET', '/api/v5/market/ticker', 
                    params={'instId': symbol}
                )
                if result:
                    raw_ticker = result[0]
                    
                    # 使用适配器转换为统一格式
                    unified_ticker = self.data_adapter.adapt_ticker(raw_ticker)
                    
                    # 转换为字典格式（保持向后兼容）
                    ticker_data = unified_ticker.to_dict()
                    ticker_data['source'] = 'rest_api'
                    
                    return ticker_data
        except Exception as e:
            logger.error(f"❌ REST API获取ticker失败: {e}")
            return None

    async def get_kline_data(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据 - 完全使用REST API（WebSocket K线频道不可用）"""
        if not self.is_initialized:
            await self.initialize()
        
        # 直接使用REST API获取K线数据
        try:
            async with self.rest_service:
                klines = await self.rest_service.get_kline_data(symbol, timeframe, limit)
                for kline in klines:
                    kline['source'] = 'rest_api'
                
                logger.debug(f"🌐 REST API获取K线: {symbol} {timeframe} ({len(klines)}条)")
                return klines
        except Exception as e:
            logger.error(f"❌ REST API获取K线失败: {e}")
            return []

    async def get_multi_timeframe_klines(self, symbol: str, timeframes: List[str] = None, limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取多时间周期K线数据
        Get multi-timeframe kline data
        
        Args:
            symbol: 交易对符号
            timeframes: 时间周期列表，默认为['1m', '5m', '15m', '1H', '4H', '1D']
            limit: 每个时间周期的K线数量
            
        Returns:
            Dict[timeframe, klines]: 按时间周期分组的K线数据
        """
        if not self.is_initialized:
            await self.initialize()
        
        if timeframes is None:
            timeframes = ['1m', '5m', '15m', '1H', '4H', '1D']
        
        result = {}
        
        # 并发获取多个时间周期的数据
        tasks = []
        for timeframe in timeframes:
            task = asyncio.create_task(
                self.get_kline_data(symbol, timeframe, limit),
                name=f"kline_{symbol}_{timeframe}"
            )
            tasks.append((timeframe, task))
        
        # 等待所有任务完成
        for timeframe, task in tasks:
            try:
                klines = await task
                result[timeframe] = klines
                logger.debug(f"📊 获取 {symbol} {timeframe} K线: {len(klines)} 条")
            except Exception as e:
                logger.error(f"❌ 获取 {symbol} {timeframe} K线失败: {e}")
                result[timeframe] = []
        
        logger.debug(f"✅ 多时间周期K线获取完成: {symbol}, {len(timeframes)} 个周期")
        return result

    async def get_funding_rate(self, symbol: str = None) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """获取资金费率 - 智能选择数据源"""
        if not self.is_initialized:
            await self.initialize()
        
        # 单个交易对且在WebSocket订阅中
        if (symbol and self.is_websocket_enabled and 
            self.realtime_manager and symbol in self.major_symbols):
            try:
                funding_data = self.realtime_manager.get_funding_rate(symbol)
                if funding_data:
                    return {
                        'symbol': symbol,
                        'funding_rate': funding_data.funding_rate,
                        'next_funding_time': funding_data.next_funding_time,
                        'update_time': funding_data.timestamp,
                        'source': 'websocket'
                    }
            except Exception as e:
                logger.warning(f"⚠️ WebSocket获取资金费率失败: {e}")
        
        # 使用REST API
        try:
            async with self.rest_service:
                raw_result = await self.rest_service.get_funding_rate(symbol)
                
                if not raw_result:
                    return None
                
                # 处理单个或多个资金费率数据
                if isinstance(raw_result, dict):
                    # 单个资金费率
                    unified_rate = self.data_adapter.adapt_funding_rate(raw_result)
                    result = unified_rate.to_dict()
                    result['source'] = 'rest_api'
                    return result
                elif isinstance(raw_result, list):
                    # 多个资金费率
                    unified_rates = self.data_adapter.adapt_funding_rates(raw_result)
                    result = []
                    for rate in unified_rates:
                        rate_dict = rate.to_dict()
                        rate_dict['source'] = 'rest_api'
                        result.append(rate_dict)
                    return result
                
                return raw_result
        except Exception as e:
            logger.error(f"❌ REST API获取资金费率失败: {e}")
            return None

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近交易数据 - 优先使用WebSocket"""
        if not self.is_initialized:
            await self.initialize()
        
        # 优先使用WebSocket实时交易数据
        if (self.is_websocket_enabled and self.realtime_manager and 
            symbol in self.major_symbols):
            try:
                trades = self.realtime_manager.get_latest_trades(symbol, limit)
                if trades:
                    result = []
                    for trade in trades:
                        result.append({
                            'instId': symbol,
                            'side': trade.side,
                            'sz': str(trade.size),
                            'px': str(trade.price),
                            'tradeId': trade.trade_id,
                            'ts': str(trade.timestamp),
                            'source': 'websocket'
                        })
                    
                    logger.debug(f"🔌 WebSocket获取交易数据: {symbol} ({len(result)}条)")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ WebSocket获取交易数据失败: {e}")
        
        # 回退到REST API
        try:
            async with self.rest_service:
                trades = await self.rest_service.get_recent_trades(symbol, limit)
                for trade in trades:
                    trade['source'] = 'rest_api'
                
                logger.debug(f"🌐 REST API获取交易数据: {symbol} ({len(trades)}条)")
                return trades
        except Exception as e:
            logger.error(f"❌ REST API获取交易数据失败: {e}")
            return []

    # 以下方法直接使用REST API，因为WebSocket不支持或不适合
    
    async def get_account_balance(self) -> Dict[str, Any]:
        """获取账户余额 - 使用REST API"""
        try:
            async with self.rest_service:
                return await self.rest_service.get_account_balance()
        except Exception as e:
            logger.error(f"❌ 获取账户余额失败: {e}")
            return {}

    async def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓信息 - 使用REST API，返回统一格式"""
        try:
            async with self.rest_service:
                raw_positions = await self.rest_service.get_positions()
                
                if not raw_positions:
                    return []
                
                # 使用适配器转换为统一格式
                unified_positions = self.data_adapter.adapt_positions(raw_positions)
                
                # 转换为字典格式（保持向后兼容）
                result = [position.to_dict() for position in unified_positions]
                
                logger.debug(f"✅ OKX持仓适配完成: {len(result)} 个持仓")
                return result
                
        except Exception as e:
            logger.error(f"❌ 获取持仓信息失败: {e}")
            return []

    async def get_spot_balances(self) -> List[Dict[str, Any]]:
        """获取现货余额 - 使用REST API"""
        try:
            async with self.rest_service:
                return await self.rest_service.get_spot_balances()
        except Exception as e:
            logger.error(f"❌ 获取现货余额失败: {e}")
            return []

    async def get_tickers(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有ticker数据 - 使用REST API（批量数据），返回统一格式"""
        try:
            async with self.rest_service:
                raw_tickers = await self.rest_service.get_tickers(inst_type)
                
                if not raw_tickers:
                    return []
                
                # 使用适配器转换为统一格式
                unified_tickers = self.data_adapter.adapt_tickers(raw_tickers)
                
                # 转换为字典格式（保持向后兼容）
                result = []
                for ticker in unified_tickers:
                    ticker_dict = ticker.to_dict()
                    ticker_dict['source'] = 'rest_api'
                    result.append(ticker_dict)
                
                logger.debug(f"✅ OKX ticker批量适配完成: {len(result)} 个ticker")
                return result
                
        except Exception as e:
            logger.error(f"❌ 获取所有ticker失败: {e}")
            return []

    async def get_all_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取所有交易对列表 - 返回统一格式"""
        try:
            async with self.rest_service:
                # 获取OKX原始数据
                raw_data = await self.rest_service.get_all_instruments(inst_type)
                
                if not raw_data:
                    logger.warning(f"⚠️ 获取{inst_type}交易对列表为空")
                    return []
                
                # 使用适配器转换为统一格式
                unified_instruments = self.data_adapter.adapt_instruments(raw_data)
                
                # 转换为字典格式（保持向后兼容）
                result = [instrument.to_dict() for instrument in unified_instruments]
                
                logger.info(f"✅ OKX交易对适配完成: {len(result)} 个{inst_type}交易对")
                return result
                
        except Exception as e:
            logger.error(f"❌ 获取{inst_type}交易对列表失败: {e}")
            return []
    
    async def get_raw_instruments(self, inst_type: str = 'SWAP') -> List[Dict[str, Any]]:
        """获取原始交易对数据 - 不经过适配器处理"""
        try:
            async with self.rest_service:
                return await self.rest_service.get_all_instruments(inst_type)
        except Exception as e:
            logger.error(f"❌ 获取原始{inst_type}交易对列表失败: {e}")
            return []
    
    async def get_raw_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取原始ticker数据 - 不经过适配器处理"""
        try:
            async with self.rest_service:
                result = await self.rest_service._make_request(
                    'GET', '/api/v5/market/ticker', 
                    params={'instId': symbol}
                )
                return result[0] if result else None
        except Exception as e:
            logger.error(f"❌ 获取原始ticker失败: {e}")
            return None
    
    async def get_raw_funding_rate(self, symbol: str = None) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """获取原始资金费率数据 - 不经过适配器处理"""
        try:
            async with self.rest_service:
                return await self.rest_service.get_funding_rate(symbol)
        except Exception as e:
            logger.error(f"❌ 获取原始资金费率失败: {e}")
            return None

    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓量 - 使用REST API"""
        try:
            async with self.rest_service:
                return await self.rest_service.get_open_interest(symbol)
        except Exception as e:
            logger.error(f"❌ 获取持仓量失败: {e}")
            return None

    async def subscribe_symbols_realtime(self, symbols: List[str]) -> Dict[str, bool]:
        """
        批量订阅多个交易对的实时数据
        Batch subscribe multiple symbols for real-time data
        
        Args:
            symbols: 交易对列表 / List of trading symbols
            
        Returns:
            Dict[symbol, success]: 订阅结果 / Subscription results
        """
        if not self.is_websocket_enabled or not self.realtime_manager:
            logger.warning("⚠️ WebSocket服务未启用，无法订阅实时数据")
            return {symbol: False for symbol in symbols}
        
        results = {}
        
        try:
            # 批量验证交易对有效性
            valid_symbols = await self._validate_symbols(symbols)
            
            if not valid_symbols:
                logger.warning("⚠️ 没有有效的交易对可订阅")
                return {symbol: False for symbol in symbols}
            
            # 标记无效的交易对
            invalid_symbols = [s for s in symbols if s not in valid_symbols]
            for symbol in invalid_symbols:
                results[symbol] = False
                logger.warning(f"⚠️ 交易对 {symbol} 无效或已下线")
            
            # 批量订阅有效的交易对
            if valid_symbols:
                # 订阅ticker数据
                await self.realtime_manager.subscribe_ticker(valid_symbols)
                logger.info(f"📊 批量Ticker订阅成功: {len(valid_symbols)} 个交易对")
                
                # 订阅资金费率
                await self.realtime_manager.subscribe_funding_rates(valid_symbols)
                logger.info(f"💰 批量资金费率订阅成功: {len(valid_symbols)} 个交易对")
                
                # 更新主要交易对列表
                for symbol in valid_symbols:
                    if symbol not in self.major_symbols:
                        self.major_symbols.append(symbol)
                    results[symbol] = True
                
                logger.info(f"✅ 批量订阅完成: {len(valid_symbols)} 个有效交易对")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 批量订阅失败: {e}")
            return {symbol: False for symbol in symbols}

    async def subscribe_symbol_realtime(self, symbol: str) -> bool:
        """订阅单个交易对的实时数据"""
        if not self.is_websocket_enabled or not self.realtime_manager:
            logger.warning("⚠️ WebSocket服务未启用，无法订阅实时数据")
            return False
        
        try:
            # 先验证交易对是否有效
            valid_symbols = await self._validate_symbols([symbol])
            if not valid_symbols:
                logger.warning(f"⚠️ 交易对 {symbol} 无效或已下线，无法订阅")
                return False
            
            validated_symbol = valid_symbols[0]
            
            # 订阅ticker
            await self.realtime_manager.subscribe_ticker([validated_symbol])
            logger.debug(f"📊 Ticker订阅成功: {validated_symbol}")
            
            # K线数据使用REST API（WebSocket频道不可用）
            logger.debug(f"📈 {validated_symbol} K线数据将使用REST API获取")
            
            # 订阅资金费率
            await self.realtime_manager.subscribe_funding_rates([validated_symbol])
            logger.debug(f"💰 资金费率订阅成功: {validated_symbol}")
            
            # 添加到主要交易对列表
            if validated_symbol not in self.major_symbols:
                self.major_symbols.append(validated_symbol)
            
            logger.info(f"✅ 订阅实时数据成功: {validated_symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 订阅实时数据失败: {symbol}, 错误: {e}")
            return False

    def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        status = {
            'is_initialized': self.is_initialized,
            'websocket_enabled': self.is_websocket_enabled,
            'subscribed_symbols_count': len(self.major_symbols),
            'subscribed_symbols': self.major_symbols[:10] if len(self.major_symbols) > 10 else self.major_symbols,  # 只显示前10个
            'rest_api_available': True,
            'data_adapter': self.data_adapter.get_adapter_info() if self.data_adapter else None
        }
        
        if self.realtime_manager:
            status['realtime_stats'] = self.realtime_manager.get_statistics()
        
        return status

    def get_subscribed_symbols(self) -> List[str]:
        """获取当前订阅的交易对列表"""
        return self.major_symbols.copy()

    async def refresh_subscriptions(self) -> bool:
        """刷新订阅 - 重新获取活跃交易对并更新订阅"""
        if not self.is_websocket_enabled or not self.realtime_manager:
            logger.warning("⚠️ WebSocket服务未启用，无法刷新订阅")
            return False
        
        try:
            logger.info("🔄 刷新交易对订阅...")
            
            # 重新获取活跃交易对并订阅
            await self._presubscribe_major_symbols()
            
            logger.info(f"✅ 订阅刷新完成: {len(self.major_symbols)} 个交易对")
            return True
            
        except Exception as e:
            logger.error(f"❌ 刷新订阅失败: {e}")
            return False

    # ==================== 交易接口 Trading Interface ====================
    
    async def place_order(self, symbol: str, side: str, size: float, 
                         order_type: str = 'market', price: float = None,
                         leverage: float = None) -> Dict[str, Any]:
        """
        下单 - 使用REST API
        Place order using REST API
        """
        try:
            async with self.rest_service:
                # 这里需要实现具体的下单逻辑
                # 目前返回模拟结果，实际实现需要调用OKX REST API
                logger.warning("⚠️ 下单功能需要在OKXService中实现具体逻辑")
                return {
                    'order_id': 'mock_order_id',
                    'symbol': symbol,
                    'side': side,
                    'size': size,
                    'price': price,
                    'status': 'pending',
                    'timestamp': datetime.now()
                }
        except Exception as e:
            logger.error(f"❌ 下单失败: {e}")
            raise

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        取消订单 - 使用REST API
        Cancel order using REST API
        """
        try:
            async with self.rest_service:
                # 这里需要实现具体的取消订单逻辑
                logger.warning("⚠️ 取消订单功能需要在OKXService中实现具体逻辑")
                return {
                    'order_id': order_id,
                    'symbol': symbol,
                    'status': 'cancelled',
                    'timestamp': datetime.now()
                }
        except Exception as e:
            logger.error(f"❌ 取消订单失败: {e}")
            raise

    async def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        获取订单状态 - 使用REST API
        Get order status using REST API
        """
        try:
            async with self.rest_service:
                # 这里需要实现具体的订单状态查询逻辑
                logger.warning("⚠️ 订单状态查询功能需要在OKXService中实现具体逻辑")
                return {
                    'order_id': order_id,
                    'symbol': symbol,
                    'status': 'unknown',
                    'timestamp': datetime.now()
                }
        except Exception as e:
            logger.error(f"❌ 获取订单状态失败: {e}")
            raise

    async def cleanup(self):
        """清理资源"""
        logger.info("🧹 清理OKX混合服务...")
        
        if self.realtime_manager:
            await self.realtime_manager.cleanup()
        
        self.is_initialized = False
        logger.info("✅ OKX混合服务清理完成")


# 全局混合服务实例
_okx_hybrid_service = None

async def get_okx_hybrid_service() -> OKXHybridService:
    """获取OKX混合服务实例"""
    global _okx_hybrid_service
    if _okx_hybrid_service is None:
        _okx_hybrid_service = OKXHybridService()
        await _okx_hybrid_service.initialize()
    return _okx_hybrid_service

async def cleanup_okx_hybrid_service():
    """清理混合服务"""
    global _okx_hybrid_service
    if _okx_hybrid_service:
        await _okx_hybrid_service.cleanup()
        _okx_hybrid_service = None