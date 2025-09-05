# -*- coding: utf-8 -*-
"""
OKX数据格式转换器
OKX Data Format Converter - 将OKX数据转换为统一格式
"""

from typing import Dict, Any, List, Union
from datetime import datetime
from decimal import Decimal

from app.models.exchange_data import (
    TickerData, KlineData, FundingRateData, OpenInterestData, 
    OrderBookData, TradeData, ExchangeType, DataSource
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class OKXDataConverter:
    """
    OKX数据格式转换器
    OKX Data Format Converter
    
    负责将OKX交易所的数据格式转换为统一的数据模型
    """
    
    @staticmethod
    def convert_symbol_to_standard(okx_symbol: str) -> str:
        """
        将OKX符号转换为标准格式
        Convert OKX symbol to standard format
        
        Args:
            okx_symbol: OKX格式符号 (e.g., "BTC-USDT-SWAP")
            
        Returns:
            str: 标准格式符号 (保持不变，OKX已是标准格式)
        """
        return okx_symbol
    
    @staticmethod
    def convert_symbol_to_okx(standard_symbol: str) -> str:
        """
        将标准符号转换为OKX格式
        Convert standard symbol to OKX format
        
        Args:
            standard_symbol: 标准格式符号 (e.g., "BTC-USDT-SWAP")
            
        Returns:
            str: OKX格式符号 (保持不变)
        """
        return standard_symbol
    
    @staticmethod
    def convert_ticker_data(okx_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> TickerData:
        """
        转换ticker数据为统一格式
        Convert ticker data to unified format
        
        Args:
            okx_data: OKX ticker数据
            data_source: 数据源类型
            
        Returns:
            TickerData: 统一格式的ticker数据
        """
        try:
            # 处理时间戳
            timestamp_ms = okx_data.get('ts', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return TickerData(
                symbol=okx_data.get('instId', ''),
                price=Decimal(str(okx_data.get('last', '0'))),
                volume_24h=Decimal(str(okx_data.get('vol24h', '0'))),
                change_24h=Decimal(str(okx_data.get('change24h', '0'))),
                change_percent_24h=Decimal(str(okx_data.get('changePct24h', '0'))),
                high_24h=Decimal(str(okx_data.get('high24h', '0'))),
                low_24h=Decimal(str(okx_data.get('low24h', '0'))),
                timestamp=timestamp,
                source=ExchangeType.OKX,
                data_source=data_source,
                bid_price=Decimal(str(okx_data.get('bidPx', '0'))) if okx_data.get('bidPx') else None,
                ask_price=Decimal(str(okx_data.get('askPx', '0'))) if okx_data.get('askPx') else None,
                bid_size=Decimal(str(okx_data.get('bidSz', '0'))) if okx_data.get('bidSz') else None,
                ask_size=Decimal(str(okx_data.get('askSz', '0'))) if okx_data.get('askSz') else None,
                open_price=Decimal(str(okx_data.get('open24h', '0'))) if okx_data.get('open24h') else None,
                quote_volume_24h=Decimal(str(okx_data.get('volCcy24h', '0'))) if okx_data.get('volCcy24h') else None,
                raw_data=okx_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换OKX ticker数据失败: {e}")
            raise ValueError(f"Failed to convert OKX ticker data: {e}")
    
    @staticmethod
    def convert_kline_data(okx_klines: List[List], symbol: str, timeframe: str, 
                          data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        """
        转换K线数据为统一格式
        Convert kline data to unified format
        
        Args:
            okx_klines: OKX K线数据列表
            symbol: 交易对符号
            timeframe: 时间周期
            data_source: 数据源类型
            
        Returns:
            List[KlineData]: 统一格式的K线数据列表
        """
        try:
            converted_klines = []
            
            for kline in okx_klines:
                if len(kline) >= 6:
                    converted_klines.append(KlineData(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=int(kline[0]),  # 时间戳
                        open=Decimal(str(kline[1])),
                        high=Decimal(str(kline[2])),
                        low=Decimal(str(kline[3])),
                        close=Decimal(str(kline[4])),
                        volume=Decimal(str(kline[5])),
                        source=ExchangeType.OKX,
                        data_source=data_source,
                        quote_volume=Decimal(str(kline[6])) if len(kline) > 6 else None,
                        raw_data={'kline': kline}
                    ))
            
            return sorted(converted_klines, key=lambda x: x.timestamp)
            
        except Exception as e:
            logger.error(f"❌ 转换OKX K线数据失败: {e}")
            raise ValueError(f"Failed to convert OKX kline data: {e}")
    
    @staticmethod
    def convert_funding_rate_data(okx_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        """
        转换资金费率数据为统一格式
        Convert funding rate data to unified format
        
        Args:
            okx_data: OKX资金费率数据
            data_source: 数据源类型
            
        Returns:
            FundingRateData: 统一格式的资金费率数据
        """
        try:
            # 处理下次资金费率时间
            next_funding_time_ms = okx_data.get('nextFundingTime', 0)
            if isinstance(next_funding_time_ms, (int, float)) and next_funding_time_ms > 0:
                next_funding_time = datetime.fromtimestamp(next_funding_time_ms / 1000)
            else:
                next_funding_time = datetime.now()
            
            # 处理时间戳
            timestamp_ms = okx_data.get('ts', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return FundingRateData(
                symbol=okx_data.get('instId', ''),
                funding_rate=Decimal(str(okx_data.get('fundingRate', '0'))),
                next_funding_time=next_funding_time,
                timestamp=timestamp,
                source=ExchangeType.OKX,
                data_source=data_source,
                mark_price=Decimal(str(okx_data.get('markPx', '0'))) if okx_data.get('markPx') else None,
                index_price=Decimal(str(okx_data.get('indexPx', '0'))) if okx_data.get('indexPx') else None,
                estimated_rate=Decimal(str(okx_data.get('nextFundingRate', '0'))) if okx_data.get('nextFundingRate') else None,
                funding_interval=8,  # OKX默认8小时
                raw_data=okx_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换OKX资金费率数据失败: {e}")
            raise ValueError(f"Failed to convert OKX funding rate data: {e}")
    
    @staticmethod
    def convert_open_interest_data(okx_data: Dict[str, Any], symbol: str, 
                                  data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        """
        转换持仓量数据为统一格式
        Convert open interest data to unified format
        
        Args:
            okx_data: OKX持仓量数据
            symbol: 交易对符号
            data_source: 数据源类型
            
        Returns:
            OpenInterestData: 统一格式的持仓量数据
        """
        try:
            # 处理时间戳
            timestamp_ms = okx_data.get('ts', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return OpenInterestData(
                symbol=symbol,
                open_interest=Decimal(str(okx_data.get('oi', '0'))),
                timestamp=timestamp,
                source=ExchangeType.OKX,
                data_source=data_source,
                open_interest_value=Decimal(str(okx_data.get('oiCcy', '0'))) if okx_data.get('oiCcy') else None,
                currency=okx_data.get('ccy', 'CONT'),
                raw_data=okx_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换OKX持仓量数据失败: {e}")
            raise ValueError(f"Failed to convert OKX open interest data: {e}")    

    @staticmethod
    def convert_order_book_data(okx_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        """
        转换订单簿数据为统一格式
        Convert order book data to unified format
        
        Args:
            okx_data: OKX订单簿数据
            data_source: 数据源类型
            
        Returns:
            OrderBookData: 统一格式的订单簿数据
        """
        try:
            # 处理时间戳
            timestamp_ms = okx_data.get('ts', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            # 转换买卖盘数据
            bids = [[Decimal(str(bid[0])), Decimal(str(bid[1]))] for bid in okx_data.get('bids', [])]
            asks = [[Decimal(str(ask[0])), Decimal(str(ask[1]))] for ask in okx_data.get('asks', [])]
            
            return OrderBookData(
                symbol=okx_data.get('instId', ''),
                bids=bids,
                asks=asks,
                timestamp=timestamp,
                source=ExchangeType.OKX,
                data_source=data_source,
                raw_data=okx_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换OKX订单簿数据失败: {e}")
            raise ValueError(f"Failed to convert OKX order book data: {e}")
    
    @staticmethod
    def convert_trade_data(okx_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        """
        转换交易数据为统一格式
        Convert trade data to unified format
        
        Args:
            okx_data: OKX交易数据
            data_source: 数据源类型
            
        Returns:
            TradeData: 统一格式的交易数据
        """
        try:
            # 处理时间戳
            timestamp_ms = okx_data.get('ts', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return TradeData(
                symbol=okx_data.get('instId', ''),
                trade_id=str(okx_data.get('tradeId', '')),
                price=Decimal(str(okx_data.get('px', '0'))),
                size=Decimal(str(okx_data.get('sz', '0'))),
                side=okx_data.get('side', 'buy').lower(),
                timestamp=timestamp,
                source=ExchangeType.OKX,
                data_source=data_source,
                raw_data=okx_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换OKX交易数据失败: {e}")
            raise ValueError(f"Failed to convert OKX trade data: {e}")
    
    @staticmethod
    def convert_timeframe_to_okx(standard_timeframe: str) -> str:
        """
        转换时间周期为OKX格式
        Convert timeframe to OKX format
        
        Args:
            standard_timeframe: 标准时间周期 (e.g., "1H", "4H", "1D")
            
        Returns:
            str: OKX时间周期格式 (e.g., "1H", "4H", "1D")
        """
        try:
            # OKX时间周期映射表
            timeframe_mapping = {
                '1m': '1m', '1M': '1m',
                '3m': '3m', '3M': '3m',
                '5m': '5m', '5M': '5m',
                '15m': '15m', '15M': '15m',
                '30m': '30m', '30M': '30m',
                '1h': '1H', '1H': '1H',
                '2h': '2H', '2H': '2H',
                '4h': '4H', '4H': '4H',
                '6h': '6H', '6H': '6H',
                '8h': '8H', '8H': '8H',
                '12h': '12H', '12H': '12H',
                '1d': '1D', '1D': '1D',
                '2d': '2D', '2D': '2D',
                '3d': '3D', '3D': '3D',
                '1w': '1W', '1W': '1W',
                '1M': '1M', '3M': '3M'
            }
            
            return timeframe_mapping.get(standard_timeframe, '1H')
            
        except Exception as e:
            logger.error(f"❌ 转换OKX时间周期失败: {standard_timeframe} - {e}")
            return '1H'
    
    @staticmethod
    def convert_timeframe_from_okx(okx_timeframe: str) -> str:
        """
        从OKX时间周期转换为标准格式
        Convert from OKX timeframe to standard format
        
        Args:
            okx_timeframe: OKX时间周期 (e.g., "1H", "4H", "1D")
            
        Returns:
            str: 标准时间周期格式 (保持不变，OKX已是标准格式)
        """
        return okx_timeframe
    
    @staticmethod
    def batch_convert_symbols_to_standard(okx_symbols: List[str]) -> List[str]:
        """
        批量转换OKX符号为标准格式
        Batch convert OKX symbols to standard format
        
        Args:
            okx_symbols: OKX符号列表
            
        Returns:
            List[str]: 标准格式符号列表
        """
        return okx_symbols  # OKX符号已是标准格式
    
    @staticmethod
    def batch_convert_symbols_to_okx(standard_symbols: List[str]) -> List[str]:
        """
        批量转换标准符号为OKX格式
        Batch convert standard symbols to OKX format
        
        Args:
            standard_symbols: 标准格式符号列表
            
        Returns:
            List[str]: OKX格式符号列表
        """
        return standard_symbols  # 标准格式即OKX格式
    
    @staticmethod
    def normalize_precision(value: Union[str, float, int], precision: int = 8) -> Decimal:
        """
        标准化数值精度
        Normalize numerical precision
        
        Args:
            value: 要标准化的数值
            precision: 精度位数
            
        Returns:
            Decimal: 标准化后的数值
        """
        try:
            if isinstance(value, str):
                if value == '' or value == 'null' or value == 'None':
                    return Decimal('0')
                value = Decimal(value)
            elif value is None:
                return Decimal('0')
            else:
                value = Decimal(str(value))
            
            # 使用Decimal进行精确计算
            quantizer = Decimal('0.' + '0' * precision)
            normalized = value.quantize(quantizer)
            
            return normalized
            
        except Exception as e:
            logger.error(f"❌ 标准化精度失败: {value} - {e}")
            return Decimal('0')
    
    @staticmethod
    def convert_instrument_data(okx_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换交易对信息为统一格式
        Convert instrument data to unified format
        
        Args:
            okx_data: OKX交易对信息
            
        Returns:
            Dict[str, Any]: 统一格式的交易对信息
        """
        try:
            return {
                'symbol': okx_data.get('instId', ''),
                'base_currency': okx_data.get('baseCcy', ''),
                'quote_currency': okx_data.get('quoteCcy', ''),
                'contract_type': okx_data.get('instType', ''),
                'status': 'active' if okx_data.get('state') == 'live' else 'inactive',
                'min_size': float(okx_data.get('minSz', '0')),
                'tick_size': float(okx_data.get('tickSz', '0')),
                'lot_size': float(okx_data.get('lotSz', '0')),
                'contract_value': float(okx_data.get('ctVal', '0')),
                'source': 'okx'
            }
            
        except Exception as e:
            logger.error(f"❌ 转换OKX交易对信息失败: {e}")
            return {}