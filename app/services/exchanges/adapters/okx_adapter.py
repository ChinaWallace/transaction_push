# -*- coding: utf-8 -*-
"""
OKX数据适配器
OKX data adapter
"""

from typing import Dict, Any, List
from datetime import datetime

from app.core.logging import get_logger
from app.models.unified_exchange_data import (
    UnifiedInstrument, UnifiedTicker, UnifiedFundingRate, UnifiedPosition,
    validate_unified_instrument
)
from .base_adapter import ExchangeDataAdapter

logger = get_logger(__name__)


class OKXDataAdapter(ExchangeDataAdapter):
    """
    OKX数据适配器
    OKX data adapter
    
    将OKX交易所的原始数据格式转换为统一的数据格式
    由于OKX的数据格式已经接近统一格式，主要是直通处理
    """
    
    def __init__(self):
        super().__init__("okx")
        logger.info("🔧 OKX数据适配器初始化完成")
    
    def adapt_instruments(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedInstrument]:
        """
        适配OKX交易对数据
        Adapt OKX instruments data
        
        OKX原始格式已经接近统一格式:
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "state": "live"
        }
        """
        if not raw_data:
            logger.warning("⚠️ OKX交易对数据为空")
            return []
        
        unified_instruments = []
        processed_count = 0
        error_count = 0
        
        for item in raw_data:
            try:
                # 获取基础字段，提供默认值处理
                inst_id = self._safe_get(item, "instId")
                if not inst_id:
                    logger.warning(f"⚠️ OKX交易对缺少instId，跳过: {item}")
                    error_count += 1
                    continue
                
                # 解析交易对符号以提取baseCcy和quoteCcy（如果原数据缺失）
                base_ccy = self._safe_get(item, "baseCcy")
                quote_ccy = self._safe_get(item, "quoteCcy")
                
                if not base_ccy or not quote_ccy:
                    # 从instId解析（例如：BTC-USDT-SWAP）
                    parts = inst_id.split('-')
                    if len(parts) >= 2:
                        if not base_ccy:
                            base_ccy = parts[0]
                        if not quote_ccy:
                            quote_ccy = parts[1]
                    else:
                        logger.warning(f"⚠️ 无法解析交易对货币: {inst_id}")
                        error_count += 1
                        continue
                
                # 确保state字段不为空
                state = self._safe_get(item, "state")
                if not state:
                    state = "live"  # 默认为live状态
                
                # OKX数据基本可以直接使用，只需要添加source字段和默认值处理
                unified_instrument = UnifiedInstrument(
                    instId=inst_id,
                    instType=self._safe_get(item, "instType", "SWAP"),
                    baseCcy=base_ccy,
                    quoteCcy=quote_ccy,
                    settleCcy=self._safe_get(item, "settleCcy", quote_ccy),  # 默认用quoteCcy
                    ctVal=self._safe_get(item, "ctVal", "1"),
                    ctMult=self._safe_get(item, "ctMult", "1"),
                    ctValCcy=self._safe_get(item, "ctValCcy", base_ccy),  # 默认用baseCcy
                    minSz=self._safe_get(item, "minSz", "0.001"),
                    lotSz=self._safe_get(item, "lotSz", "0.001"),
                    tickSz=self._safe_get(item, "tickSz", "0.01"),
                    state=self._normalize_state(state),
                    listTime=self._safe_get(item, "listTime", "0"),
                    expTime=self._safe_get(item, "expTime", "0"),
                    source='okx',
                    raw_data=item
                )
                
                # 验证数据完整性
                if validate_unified_instrument(unified_instrument):
                    unified_instruments.append(unified_instrument)
                    processed_count += 1
                else:
                    logger.warning(f"⚠️ OKX交易对数据验证失败: {unified_instrument.instId}")
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
                self._handle_adaptation_error(e, "OKX交易对", item)
                continue
        
        logger.info(f"✅ OKX交易对适配完成: 成功 {processed_count} 个，失败 {error_count} 个")
        return unified_instruments
    
    def adapt_ticker(self, raw_data: Dict[str, Any]) -> UnifiedTicker:
        """
        适配OKX ticker数据
        Adapt OKX ticker data
        
        OKX原始格式已经是统一格式:
        {
            "instId": "BTC-USDT-SWAP",
            "last": "50000",
            "askPx": "50001",
            "bidPx": "49999"
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["instId"],
                "OKX ticker"
            )
            
            # OKX数据基本可以直接使用，只需要添加source字段
            unified_ticker = UnifiedTicker(
                instId=self._safe_get(raw_data, "instId"),
                last=self._safe_get_float(raw_data, "last"),
                lastSz=self._safe_get_float(raw_data, "lastSz"),
                askPx=self._safe_get_float(raw_data, "askPx"),
                askSz=self._safe_get_float(raw_data, "askSz"),
                bidPx=self._safe_get_float(raw_data, "bidPx"),
                bidSz=self._safe_get_float(raw_data, "bidSz"),
                open24h=self._safe_get_float(raw_data, "open24h"),
                high24h=self._safe_get_float(raw_data, "high24h"),
                low24h=self._safe_get_float(raw_data, "low24h"),
                vol24h=self._safe_get_float(raw_data, "vol24h"),
                volCcy24h=self._safe_get_float(raw_data, "volCcy24h"),
                ts=self._safe_get_timestamp(raw_data, "ts", str(int(datetime.now().timestamp() * 1000))),
                source='okx',
                raw_data=raw_data
            )
            
            return unified_ticker
            
        except Exception as e:
            self._handle_adaptation_error(e, "OKX ticker", raw_data)
    
    def adapt_tickers(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedTicker]:
        """批量适配OKX ticker数据"""
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
        
        logger.info(f"✅ OKX ticker批量适配完成: {len(unified_tickers)}/{len(raw_data)}")
        return unified_tickers
    
    def adapt_funding_rate(self, raw_data: Dict[str, Any]) -> UnifiedFundingRate:
        """
        适配OKX资金费率数据
        Adapt OKX funding rate data
        
        OKX原始格式已经是统一格式:
        {
            "instId": "BTC-USDT-SWAP",
            "fundingRate": "0.0001",
            "nextFundingTime": "1640995200000",
            "fundingTime": "1640966400000"
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["instId", "fundingRate"],
                "OKX资金费率"
            )
            
            # OKX数据基本可以直接使用，只需要添加source字段
            unified_funding_rate = UnifiedFundingRate(
                instId=self._safe_get(raw_data, "instId"),
                fundingRate=self._safe_get_float(raw_data, "fundingRate"),
                nextFundingTime=self._safe_get_timestamp(raw_data, "nextFundingTime"),
                fundingTime=self._safe_get_timestamp(raw_data, "fundingTime"),
                source='okx',
                raw_data=raw_data
            )
            
            return unified_funding_rate
            
        except Exception as e:
            self._handle_adaptation_error(e, "OKX资金费率", raw_data)
    
    def adapt_funding_rates(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedFundingRate]:
        """批量适配OKX资金费率数据"""
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
        
        logger.info(f"✅ OKX资金费率批量适配完成: {len(unified_rates)}/{len(raw_data)}")
        return unified_rates
    
    def adapt_position(self, raw_data: Dict[str, Any]) -> UnifiedPosition:
        """
        适配OKX持仓数据
        Adapt OKX position data
        
        OKX原始格式已经是统一格式:
        {
            "instId": "BTC-USDT-SWAP",
            "posSide": "long",
            "pos": "0.001",
            "avgPx": "50000",
            "upl": "0.1"
        }
        """
        try:
            # 验证必需字段
            self._validate_required_fields(
                raw_data,
                ["instId"],
                "OKX持仓"
            )
            
            # OKX数据基本可以直接使用，只需要添加source字段
            unified_position = UnifiedPosition(
                instId=self._safe_get(raw_data, "instId"),
                posSide=self._safe_get(raw_data, "posSide", "net"),
                pos=self._safe_get(raw_data, "pos", "0"),
                posNotional=self._safe_get(raw_data, "notionalUsd", "0"),
                avgPx=self._safe_get(raw_data, "avgPx", "0"),
                upl=self._safe_get(raw_data, "upl", "0"),
                uplRatio=self._safe_get(raw_data, "uplRatio", "0"),
                margin=self._safe_get(raw_data, "margin", "0"),
                source='okx',
                raw_data=raw_data
            )
            
            return unified_position
            
        except Exception as e:
            self._handle_adaptation_error(e, "OKX持仓", raw_data)
    
    def adapt_positions(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedPosition]:
        """批量适配OKX持仓数据"""
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
        
        logger.info(f"✅ OKX持仓批量适配完成: {len(unified_positions)}/{len(raw_data)}")
        return unified_positions
    
    def _normalize_state(self, state: str) -> str:
        """标准化交易对状态"""
        if not state:
            return 'live'
        
        state_lower = state.lower()
        if state_lower in ['trading', 'active', 'live']:
            return 'live'
        elif state_lower in ['break', 'suspend', 'inactive', 'halt']:
            return 'suspend'
        else:
            return 'live'  # 默认为live状态