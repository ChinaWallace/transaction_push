# -*- coding: utf-8 -*-
"""
币安数据适配器
Binance data adapter
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.logging import get_logger
from app.models.unified_exchange_data import (
    UnifiedInstrument, UnifiedTicker, UnifiedFundingRate, UnifiedPosition,
    validate_unified_instrument
)
from .base_adapter import ExchangeDataAdapter
from .performance_monitor import log_adapter_performance
from .batch_processor import adapter_batch_processor
from .cache_manager import cache_adapter_result

logger = get_logger(__name__)


class BinanceDataAdapter(ExchangeDataAdapter):
    """
    币安数据适配器
    Binance data adapter
    
    将币安交易所的原始数据格式转换为统一的数据格式
    """
    
    def __init__(self):
        super().__init__("binance")
        logger.info("🔧 币安数据适配器初始化完成")
    
    @log_adapter_performance("adapt_instruments")
    @cache_adapter_result("binance_instruments", ttl=3600, data_type="instruments")
    def adapt_instruments(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedInstrument]:
        """
        适配币安交易对数据
        Adapt Binance instruments data
        
        币安原始格式示例:
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "contractType": "PERPETUAL",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"}
            ]
        }
        
        转换为统一格式:
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "state": "live"
        }
        """
        if not raw_data:
            logger.warning("⚠️ 币安交易对数据为空")
            return []
        
        unified_instruments = []
        processed_count = 0
        error_count = 0
        
        logger.info(f"🔄 开始适配币安交易对数据，共 {len(raw_data)} 个交易对")
        
        for item in raw_data:
            try:
                # 验证必需字段
                self._validate_required_fields(
                    item, 
                    ["symbol", "status"], 
                    "币安交易对"
                )
                
                # 获取基础信息
                raw_symbol = self._safe_get(item, "symbol")
                status = self._safe_get(item, "status")
                base_asset = self._safe_get(item, "baseAsset")
                quote_asset = self._safe_get(item, "quoteAsset")
                contract_type = self._safe_get(item, "contractType")
                
                # 只处理USDT永续合约
                if not raw_symbol.endswith('USDT') or quote_asset != 'USDT':
                    continue
                
                # 只处理永续合约
                if contract_type != 'PERPETUAL':
                    continue
                
                # 只处理交易状态的合约
                if status.upper() != 'TRADING':
                    continue
                
                # 提取基础货币 - 使用baseAsset字段更准确
                base_currency = base_asset if base_asset else raw_symbol[:-4]
                
                # 过滤掉基础货币名称过长的交易对（数据库限制为10个字符）
                if len(base_currency) > 10:
                    logger.debug(f"跳过基础货币名称过长的交易对: {base_currency} (长度: {len(base_currency)})")
                    continue
                
                unified_symbol = f"{base_currency}-USDT-SWAP"
                
                # 提取过滤器信息用于精度设置
                filters = item.get('filters', [])
                min_qty = self._extract_min_qty_from_filters(filters)
                step_size = self._extract_step_size_from_filters(filters)
                tick_size = self._extract_tick_size_from_filters(filters)
                
                # 获取上线时间（如果有的话）
                list_time = self._safe_get_timestamp(item, "onboardDate", "0")
                
                # 创建统一交易对对象
                unified_instrument = UnifiedInstrument(
                    instId=unified_symbol,
                    instType='SWAP',
                    baseCcy=base_currency,
                    quoteCcy='USDT',
                    settleCcy='USDT',
                    ctVal='1',  # 币安永续合约面值为1
                    ctMult='1', # 币安永续合约乘数为1
                    ctValCcy=base_currency,
                    minSz=min_qty,
                    lotSz=step_size,
                    tickSz=tick_size,
                    state=self._normalize_state(status),
                    listTime=list_time,
                    expTime='0',   # 永续合约无到期时间，使用0而不是空字符串
                    source='binance',
                    raw_data=item
                )
                
                # 验证数据完整性
                if validate_unified_instrument(unified_instrument):
                    unified_instruments.append(unified_instrument)
                    processed_count += 1
                    logger.debug(f"✅ 成功适配交易对: {unified_symbol}")
                else:
                    logger.warning(f"⚠️ 币安交易对数据验证失败: {unified_symbol}")
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
                logger.warning(f"⚠️ 适配交易对失败: {e}")
                self._handle_adaptation_error(e, "币安交易对", item)
                continue
        
        logger.info(f"✅ 币安交易对适配完成: 成功 {processed_count} 个，失败 {error_count} 个")
        return unified_instruments
    
    @cache_adapter_result("binance_instruments_batch", ttl=1800, data_type="batch_instruments")
    async def adapt_instruments_batch(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedInstrument]:
        """
        批量适配币安交易对数据（异步优化版本）
        Batch adapt Binance instruments data (async optimized version)
        """
        if not raw_data:
            logger.warning("⚠️ 币安交易对数据为空")
            return []
        
        logger.info(f"🚀 开始批量适配币安交易对数据，共 {len(raw_data)} 个交易对")
        
        def progress_callback(processed: int, total: int):
            if processed % 100 == 0 or processed == total:
                logger.info(f"📊 批量适配进度: {processed}/{total} ({processed/total*100:.1f}%)")
        
        try:
            # 使用批处理器进行优化处理
            results = await adapter_batch_processor.batch_adapt_instruments(
                raw_data, 
                self._adapt_single_instrument,
                progress_callback
            )
            
            logger.info(f"✅ 币安交易对批量适配完成: {len(results)}/{len(raw_data)} 个")
            return results
            
        except Exception as e:
            logger.error(f"❌ 币安交易对批量适配失败: {e}")
            # 回退到串行处理
            logger.info("🔄 回退到串行处理模式")
            return self.adapt_instruments(raw_data)
    
    def _adapt_single_instrument(self, item: Dict[str, Any]) -> Optional[UnifiedInstrument]:
        """适配单个交易对数据（用于批处理）"""
        try:
            # 验证必需字段
            self._validate_required_fields(
                item, 
                ["symbol", "status"], 
                "币安交易对"
            )
            
            # 获取基础信息
            raw_symbol = self._safe_get(item, "symbol")
            status = self._safe_get(item, "status")
            base_asset = self._safe_get(item, "baseAsset")
            quote_asset = self._safe_get(item, "quoteAsset")
            contract_type = self._safe_get(item, "contractType")
            
            # 只处理USDT永续合约
            if not raw_symbol.endswith('USDT') or quote_asset != 'USDT':
                return None
            
            # 只处理永续合约
            if contract_type != 'PERPETUAL':
                return None
            
            # 只处理交易状态的合约
            if status.upper() != 'TRADING':
                return None
            
            # 提取基础货币 - 使用baseAsset字段更准确
            base_currency = base_asset if base_asset else raw_symbol[:-4]
            
            # 过滤掉基础货币名称过长的交易对（数据库限制为10个字符）
            if len(base_currency) > 10:
                return None
            
            unified_symbol = f"{base_currency}-USDT-SWAP"
            
            # 提取过滤器信息用于精度设置
            filters = item.get('filters', [])
            min_qty = self._extract_min_qty_from_filters(filters)
            step_size = self._extract_step_size_from_filters(filters)
            tick_size = self._extract_tick_size_from_filters(filters)
            
            # 获取上线时间（如果有的话）
            list_time = self._safe_get_timestamp(item, "onboardDate", "0")
            
            # 创建统一交易对对象
            unified_instrument = UnifiedInstrument(
                instId=unified_symbol,
                instType='SWAP',
                baseCcy=base_currency,
                quoteCcy='USDT',
                settleCcy='USDT',
                ctVal='1',  # 币安永续合约面值为1
                ctMult='1', # 币安永续合约乘数为1
                ctValCcy=base_currency,
                minSz=min_qty,
                lotSz=step_size,
                tickSz=tick_size,
                state=self._normalize_state(status),
                listTime=list_time,
                expTime='0',   # 永续合约无到期时间，使用0而不是空字符串
                source='binance',
                raw_data=item
            )
            
            # 验证数据完整性
            if validate_unified_instrument(unified_instrument):
                return unified_instrument
            else:
                logger.warning(f"⚠️ 币安交易对数据验证失败: {unified_symbol}")
                return None
                
        except Exception as e:
            logger.warning(f"⚠️ 适配交易对失败: {e}")
            return None
    
    @log_adapter_performance("adapt_ticker")
    @cache_adapter_result("binance_ticker", ttl=30, data_type="ticker")
    def adapt_ticker(self, raw_data: Dict[str, Any]) -> UnifiedTicker:
        """
        适配币安ticker数据
        Adapt Binance ticker data
        
        币安原始格式示例:
        {
            "symbol": "BTCUSDT",
            "lastPrice": "50000.00",
            "bidPrice": "49999.00",
            "askPrice": "50001.00",
            "bidQty": "1.5",
            "askQty": "2.0",
            "openPrice": "49500.00",
            "highPrice": "50500.00",
            "lowPrice": "49000.00",
            "volume": "1000.00",
            "quoteVolume": "50000000.00",
            "closeTime": 1640995200000
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["symbol"],
                "币安ticker"
            )
            
            # 标准化交易对符号
            raw_symbol = self._safe_get(raw_data, "symbol")
            unified_symbol = self._normalize_symbol(raw_symbol, "binance")
            
            # 获取时间戳，优先使用closeTime，否则使用当前时间
            timestamp = self._safe_get_timestamp(
                raw_data, 
                "closeTime", 
                str(int(datetime.now().timestamp() * 1000))
            )
            
            # 创建统一ticker对象
            unified_ticker = UnifiedTicker(
                instId=unified_symbol,
                last=self._safe_get_float(raw_data, "lastPrice", "0"),
                lastSz=self._safe_get_float(raw_data, "count", "0"),  # 交易次数作为最新成交量
                askPx=self._safe_get_float(raw_data, "askPrice", "0"),
                askSz=self._safe_get_float(raw_data, "askQty", "0"),
                bidPx=self._safe_get_float(raw_data, "bidPrice", "0"),
                bidSz=self._safe_get_float(raw_data, "bidQty", "0"),
                open24h=self._safe_get_float(raw_data, "openPrice", "0"),
                high24h=self._safe_get_float(raw_data, "highPrice", "0"),
                low24h=self._safe_get_float(raw_data, "lowPrice", "0"),
                vol24h=self._safe_get_float(raw_data, "volume", "0"),
                volCcy24h=self._safe_get_float(raw_data, "quoteVolume", "0"),
                ts=timestamp,
                source='binance',
                raw_data=raw_data
            )
            
            logger.debug(f"✅ 成功适配ticker数据: {unified_symbol}")
            return unified_ticker
            
        except Exception as e:
            self._handle_adaptation_error(e, "币安ticker", raw_data)
    
    @log_adapter_performance("adapt_tickers")
    @cache_adapter_result("binance_tickers", ttl=60, data_type="batch_tickers")
    def adapt_tickers(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedTicker]:
        """批量适配币安ticker数据"""
        if not raw_data:
            return []
        
        unified_tickers = []
        for item in raw_data:
            try:
                ticker = self.adapt_ticker(item)
                unified_tickers.append(ticker)
            except Exception as e:
                logger.warning(f"⚠️ 跳过无效的ticker数据: {e}")
                continue
        
        logger.info(f"✅ 币安ticker批量适配完成: {len(unified_tickers)}/{len(raw_data)}")
        return unified_tickers
    
    @cache_adapter_result("binance_tickers_batch", ttl=60, data_type="batch_tickers")
    async def adapt_tickers_batch(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedTicker]:
        """批量适配币安ticker数据（异步优化版本）"""
        if not raw_data:
            return []
        
        logger.info(f"🚀 开始批量适配币安ticker数据，共 {len(raw_data)} 个")
        
        try:
            results = await adapter_batch_processor.batch_adapt_tickers(
                raw_data, 
                self.adapt_ticker
            )
            
            logger.info(f"✅ 币安ticker批量适配完成: {len(results)}/{len(raw_data)}")
            return results
            
        except Exception as e:
            logger.error(f"❌ 币安ticker批量适配失败: {e}")
            # 回退到串行处理
            return self.adapt_tickers(raw_data)
    
    @log_adapter_performance("adapt_funding_rate")
    @cache_adapter_result("binance_funding_rate", ttl=300, data_type="funding_rate")
    def adapt_funding_rate(self, raw_data: Dict[str, Any]) -> UnifiedFundingRate:
        """
        适配币安资金费率数据
        Adapt Binance funding rate data
        
        币安原始格式示例:
        {
            "symbol": "BTCUSDT",
            "lastFundingRate": "0.0001",
            "fundingTime": 1640995200000,
            "nextFundingTime": 1641024000000
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["symbol"],
                "币安资金费率"
            )
            
            # 标准化交易对符号
            raw_symbol = self._safe_get(raw_data, "symbol")
            unified_symbol = self._normalize_symbol(raw_symbol, "binance")
            
            # 获取资金费率，币安API中可能是lastFundingRate或fundingRate
            funding_rate = self._safe_get_float(raw_data, "lastFundingRate", "0")
            if funding_rate == "0":
                funding_rate = self._safe_get_float(raw_data, "fundingRate", "0")
            
            # 获取时间戳
            next_funding_time = self._safe_get_timestamp(raw_data, "nextFundingTime", "")
            funding_time = self._safe_get_timestamp(raw_data, "fundingTime", "")
            
            # 如果没有fundingTime，使用当前时间
            if not funding_time:
                funding_time = str(int(datetime.now().timestamp() * 1000))
            
            # 创建统一资金费率对象
            unified_funding_rate = UnifiedFundingRate(
                instId=unified_symbol,
                fundingRate=funding_rate,
                nextFundingTime=next_funding_time,
                fundingTime=funding_time,
                source='binance',
                raw_data=raw_data
            )
            
            logger.debug(f"✅ 成功适配资金费率数据: {unified_symbol}, 费率: {funding_rate}")
            return unified_funding_rate
            
        except Exception as e:
            self._handle_adaptation_error(e, "币安资金费率", raw_data)
    
    @log_adapter_performance("adapt_funding_rates")
    @cache_adapter_result("binance_funding_rates", ttl=300, data_type="funding_rate")
    def adapt_funding_rates(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedFundingRate]:
        """批量适配币安资金费率数据"""
        if not raw_data:
            return []
        
        unified_rates = []
        for item in raw_data:
            try:
                rate = self.adapt_funding_rate(item)
                unified_rates.append(rate)
            except Exception as e:
                logger.warning(f"⚠️ 跳过无效的资金费率数据: {e}")
                continue
        
        logger.info(f"✅ 币安资金费率批量适配完成: {len(unified_rates)}/{len(raw_data)}")
        return unified_rates
    
    @cache_adapter_result("binance_funding_rates_batch", ttl=300, data_type="funding_rate")
    async def adapt_funding_rates_batch(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedFundingRate]:
        """批量适配币安资金费率数据（异步优化版本）"""
        if not raw_data:
            return []
        
        logger.info(f"🚀 开始批量适配币安资金费率数据，共 {len(raw_data)} 个")
        
        try:
            results = await adapter_batch_processor.batch_adapt_funding_rates(
                raw_data, 
                self.adapt_funding_rate
            )
            
            logger.info(f"✅ 币安资金费率批量适配完成: {len(results)}/{len(raw_data)}")
            return results
            
        except Exception as e:
            logger.error(f"❌ 币安资金费率批量适配失败: {e}")
            # 回退到串行处理
            return self.adapt_funding_rates(raw_data)
    
    @log_adapter_performance("adapt_position")
    @cache_adapter_result("binance_position", ttl=60, data_type="position")
    def adapt_position(self, raw_data: Dict[str, Any]) -> UnifiedPosition:
        """
        适配币安持仓数据
        Adapt Binance position data
        
        币安原始格式示例:
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.001",
            "entryPrice": "50000.0",
            "markPrice": "50100.0",
            "unRealizedProfit": "0.1",
            "positionSide": "LONG"
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["symbol"],
                "币安持仓"
            )
            
            # 调试：检查实际收到的数据字段
            logger.debug(f"🔍 币安原始持仓数据字段: {list(raw_data.keys())}")
            
            # 标准化交易对符号
            raw_symbol = self._safe_get(raw_data, "symbol")
            unified_symbol = self._normalize_symbol(raw_symbol, "binance")
            
            # 处理持仓方向
            position_side = self._safe_get(raw_data, "positionSide", "BOTH").upper()
            if position_side == "LONG":
                pos_side = "long"
            elif position_side == "SHORT":
                pos_side = "short"
            else:
                pos_side = "net"
            
            # 计算持仓名义价值
            position_amt = float(self._safe_get_float(raw_data, "positionAmt", "0"))
            mark_price = float(self._safe_get_float(raw_data, "markPrice", "0"))
            pos_notional = str(abs(position_amt * mark_price))
            
            # 创建统一持仓对象
            unified_position = UnifiedPosition(
                instId=unified_symbol,
                posSide=pos_side,
                pos=self._safe_get_float(raw_data, "positionAmt"),
                posNotional=pos_notional,
                avgPx=self._safe_get_float(raw_data, "entryPrice"),
                upl=self._safe_get_float(raw_data, "unRealizedProfit"),
                uplRatio=self._safe_get_float(raw_data, "percentage"),
                margin=self._safe_get_float(raw_data, "isolatedMargin"),
                source='binance',
                raw_data=raw_data
            )
            
            return unified_position
            
        except Exception as e:
            self._handle_adaptation_error(e, "币安持仓", raw_data)
    
    @log_adapter_performance("adapt_positions")
    @cache_adapter_result("binance_positions", ttl=60, data_type="position")
    def adapt_positions(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedPosition]:
        """批量适配币安持仓数据"""
        if not raw_data:
            return []
        
        unified_positions = []
        for item in raw_data:
            try:
                position = self.adapt_position(item)
                # 只返回有持仓的数据
                if position.has_position:
                    unified_positions.append(position)
            except Exception as e:
                logger.warning(f"⚠️ 跳过无效的持仓数据: {e}")
                continue
        
        logger.info(f"✅ 币安持仓批量适配完成: {len(unified_positions)}/{len(raw_data)}")
        return unified_positions
    
    @cache_adapter_result("binance_positions_batch", ttl=60, data_type="position")
    async def adapt_positions_batch(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedPosition]:
        """批量适配币安持仓数据（异步优化版本）"""
        if not raw_data:
            return []
        
        logger.info(f"🚀 开始批量适配币安持仓数据，共 {len(raw_data)} 个")
        
        try:
            results = await adapter_batch_processor.batch_adapt_positions(
                raw_data, 
                self.adapt_position
            )
            
            # 只返回有持仓的数据
            valid_positions = [pos for pos in results if pos.has_position]
            
            logger.info(f"✅ 币安持仓批量适配完成: {len(valid_positions)}/{len(raw_data)}")
            return valid_positions
            
        except Exception as e:
            logger.error(f"❌ 币安持仓批量适配失败: {e}")
            # 回退到串行处理
            return self.adapt_positions(raw_data)
    
    # 辅助方法
    def _extract_min_qty_from_filters(self, filters: List[Dict[str, Any]]) -> str:
        """从过滤器中提取最小下单数量"""
        for filter_item in filters:
            if filter_item.get('filterType') == 'LOT_SIZE':
                return self._safe_get_float(filter_item, 'minQty', '0.001')
        return '0.001'
    
    def _extract_step_size_from_filters(self, filters: List[Dict[str, Any]]) -> str:
        """从过滤器中提取下单数量精度"""
        for filter_item in filters:
            if filter_item.get('filterType') == 'LOT_SIZE':
                return self._safe_get_float(filter_item, 'stepSize', '0.001')
        return '0.001'
    
    def _extract_tick_size_from_filters(self, filters: List[Dict[str, Any]]) -> str:
        """从过滤器中提取价格精度"""
        for filter_item in filters:
            if filter_item.get('filterType') == 'PRICE_FILTER':
                return self._safe_get_float(filter_item, 'tickSize', '0.01')
        return '0.01'