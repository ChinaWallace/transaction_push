# -*- coding: utf-8 -*-
"""
数据转换器工厂
Data Converter Factory - 统一管理不同交易所的数据转换器
"""

from typing import Dict, Any, List
from abc import ABC, abstractmethod

from app.models.exchange_data import (
    TickerData, KlineData, FundingRateData, OpenInterestData, 
    OrderBookData, TradeData, ExchangeType, DataSource
)
from app.services.exchanges.okx.okx_data_converter import OKXDataConverter
from app.services.exchanges.binance.binance_data_converter import BinanceDataConverter
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseDataConverter(ABC):
    """
    数据转换器基类
    Base Data Converter Interface
    """
    
    @abstractmethod
    def convert_ticker_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> TickerData:
        """转换ticker数据"""
    
    @abstractmethod
    def convert_kline_data(self, raw_data: List[List], symbol: str, timeframe: str, 
                          data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        """转换K线数据"""
    
    @abstractmethod
    def convert_funding_rate_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        """转换资金费率数据"""
    
    @abstractmethod
    def convert_open_interest_data(self, raw_data: Dict[str, Any], symbol: str, 
                                  data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        """转换持仓量数据"""
    
    @abstractmethod
    def convert_order_book_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        """转换订单簿数据"""
    
    @abstractmethod
    def convert_trade_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        """转换交易数据"""
    
    @abstractmethod
    def convert_symbol_to_standard(self, exchange_symbol: str) -> str:
        """转换交易所符号为标准格式"""
    
    @abstractmethod
    def convert_symbol_from_standard(self, standard_symbol: str) -> str:
        """转换标准符号为交易所格式"""


class OKXDataConverterWrapper(BaseDataConverter):
    """
    OKX数据转换器包装类
    OKX Data Converter Wrapper
    """
    
    def __init__(self):
        self.converter = OKXDataConverter()
    
    def convert_ticker_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> TickerData:
        return self.converter.convert_ticker_data(raw_data, data_source)
    
    def convert_kline_data(self, raw_data: List[List], symbol: str, timeframe: str, 
                          data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        return self.converter.convert_kline_data(raw_data, symbol, timeframe, data_source)
    
    def convert_funding_rate_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        return self.converter.convert_funding_rate_data(raw_data, data_source)
    
    def convert_open_interest_data(self, raw_data: Dict[str, Any], symbol: str, 
                                  data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        return self.converter.convert_open_interest_data(raw_data, symbol, data_source)
    
    def convert_order_book_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        return self.converter.convert_order_book_data(raw_data, data_source)
    
    def convert_trade_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        return self.converter.convert_trade_data(raw_data, data_source)
    
    def convert_symbol_to_standard(self, exchange_symbol: str) -> str:
        return self.converter.convert_symbol_to_standard(exchange_symbol)
    
    def convert_symbol_from_standard(self, standard_symbol: str) -> str:
        return self.converter.convert_symbol_to_okx(standard_symbol)


class BinanceDataConverterWrapper(BaseDataConverter):
    """
    币安数据转换器包装类
    Binance Data Converter Wrapper
    """
    
    def __init__(self):
        self.converter = BinanceDataConverter()
    
    def convert_ticker_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> TickerData:
        return self.converter.convert_ticker_data(raw_data, data_source)
    
    def convert_kline_data(self, raw_data: List[List], symbol: str, timeframe: str, 
                          data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        return self.converter.convert_kline_data(raw_data, symbol, timeframe, data_source)
    
    def convert_funding_rate_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        return self.converter.convert_funding_rate_data(raw_data, data_source)
    
    def convert_open_interest_data(self, raw_data: Dict[str, Any], symbol: str, 
                                  data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        return self.converter.convert_open_interest_data(raw_data, symbol, data_source)
    
    def convert_order_book_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        return self.converter.convert_order_book_data(raw_data, data_source)
    
    def convert_trade_data(self, raw_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        return self.converter.convert_trade_data(raw_data, data_source)
    
    def convert_symbol_to_standard(self, exchange_symbol: str) -> str:
        return self.converter.convert_symbol_to_standard(exchange_symbol)
    
    def convert_symbol_from_standard(self, standard_symbol: str) -> str:
        return self.converter.convert_symbol_to_binance(standard_symbol)


class DataConverterFactory:
    """
    数据转换器工厂类
    Data Converter Factory
    
    根据交易所类型提供相应的数据转换器
    """
    
    _converters: Dict[ExchangeType, BaseDataConverter] = {}
    
    @classmethod
    def get_converter(cls, exchange_type: ExchangeType) -> BaseDataConverter:
        """
        获取指定交易所的数据转换器
        Get data converter for specified exchange
        
        Args:
            exchange_type: 交易所类型
            
        Returns:
            BaseDataConverter: 数据转换器实例
        """
        if exchange_type not in cls._converters:
            if exchange_type == ExchangeType.OKX:
                cls._converters[exchange_type] = OKXDataConverterWrapper()
            elif exchange_type == ExchangeType.BINANCE:
                cls._converters[exchange_type] = BinanceDataConverterWrapper()
            else:
                raise ValueError(f"Unsupported exchange type: {exchange_type}")
        
        return cls._converters[exchange_type]
    
    @classmethod
    def convert_ticker_data(cls, exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                           data_source: DataSource = DataSource.REST_API) -> TickerData:
        """
        转换ticker数据
        Convert ticker data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_ticker_data(raw_data, data_source)
    
    @classmethod
    def convert_kline_data(cls, exchange_type: ExchangeType, raw_data: List[List], 
                          symbol: str, timeframe: str, data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        """
        转换K线数据
        Convert kline data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_kline_data(raw_data, symbol, timeframe, data_source)
    
    @classmethod
    def convert_funding_rate_data(cls, exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                                 data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        """
        转换资金费率数据
        Convert funding rate data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_funding_rate_data(raw_data, data_source)
    
    @classmethod
    def convert_open_interest_data(cls, exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                                  symbol: str, data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        """
        转换持仓量数据
        Convert open interest data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_open_interest_data(raw_data, symbol, data_source)
    
    @classmethod
    def convert_order_book_data(cls, exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                               data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        """
        转换订单簿数据
        Convert order book data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_order_book_data(raw_data, data_source)
    
    @classmethod
    def convert_trade_data(cls, exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                          data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        """
        转换交易数据
        Convert trade data
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_trade_data(raw_data, data_source)
    
    @classmethod
    def convert_symbol_to_standard(cls, exchange_type: ExchangeType, exchange_symbol: str) -> str:
        """
        转换交易所符号为标准格式
        Convert exchange symbol to standard format
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_symbol_to_standard(exchange_symbol)
    
    @classmethod
    def convert_symbol_from_standard(cls, exchange_type: ExchangeType, standard_symbol: str) -> str:
        """
        转换标准符号为交易所格式
        Convert standard symbol to exchange format
        """
        converter = cls.get_converter(exchange_type)
        return converter.convert_symbol_from_standard(standard_symbol)
    
    @classmethod
    def batch_convert_symbols_to_standard(cls, exchange_type: ExchangeType, exchange_symbols: List[str]) -> List[str]:
        """
        批量转换交易所符号为标准格式
        Batch convert exchange symbols to standard format
        """
        converter = cls.get_converter(exchange_type)
        return [converter.convert_symbol_to_standard(symbol) for symbol in exchange_symbols]
    
    @classmethod
    def batch_convert_symbols_from_standard(cls, exchange_type: ExchangeType, standard_symbols: List[str]) -> List[str]:
        """
        批量转换标准符号为交易所格式
        Batch convert standard symbols to exchange format
        """
        converter = cls.get_converter(exchange_type)
        return [converter.convert_symbol_from_standard(symbol) for symbol in standard_symbols]
    
    @classmethod
    def clear_cache(cls):
        """
        清理转换器缓存
        Clear converter cache
        """
        cls._converters.clear()
        logger.info("✅ 数据转换器缓存已清理")


# 便捷函数
def get_data_converter(exchange_type: ExchangeType) -> BaseDataConverter:
    """
    获取数据转换器的便捷函数
    Convenience function to get data converter
    """
    return DataConverterFactory.get_converter(exchange_type)


def convert_ticker_data(exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                       data_source: DataSource = DataSource.REST_API) -> TickerData:
    """
    转换ticker数据的便捷函数
    Convenience function to convert ticker data
    """
    return DataConverterFactory.convert_ticker_data(exchange_type, raw_data, data_source)


def convert_kline_data(exchange_type: ExchangeType, raw_data: List[List], 
                      symbol: str, timeframe: str, data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
    """
    转换K线数据的便捷函数
    Convenience function to convert kline data
    """
    return DataConverterFactory.convert_kline_data(exchange_type, raw_data, symbol, timeframe, data_source)


def convert_funding_rate_data(exchange_type: ExchangeType, raw_data: Dict[str, Any], 
                             data_source: DataSource = DataSource.REST_API) -> FundingRateData:
    """
    转换资金费率数据的便捷函数
    Convenience function to convert funding rate data
    """
    return DataConverterFactory.convert_funding_rate_data(exchange_type, raw_data, data_source)