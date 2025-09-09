# -*- coding: utf-8 -*-
"""
数据转换器测试
Data converter tests
"""

from decimal import Decimal

from app.models.data_converters import OKXDataConverter, BinanceDataConverter, get_data_converter
from app.models.exchange_data import ExchangeType, DataSource
from app.core.logging import get_logger

logger = get_logger(__name__)


def test_okx_ticker_conversion():
    """测试OKX ticker数据转换"""
    logger.info("🔍 测试OKX ticker数据转换")
    
    # 模拟OKX ticker数据
    okx_ticker_data = {
        "instId": "BTC-USDT-SWAP",
        "last": "43250.1",
        "lastSz": "1",
        "askPx": "43250.2",
        "askSz": "25",
        "bidPx": "43250.1",
        "bidSz": "25",
        "open24h": "42800.0",
        "high24h": "43500.0",
        "low24h": "42500.0",
        "vol24h": "12345.67",
        "volCcy24h": "534567890.12",
        "ts": "1640995200000"
    }
    
    converter = OKXDataConverter()
    ticker = converter.convert_ticker(okx_ticker_data, DataSource.REST_API)
    
    assert ticker.symbol == "BTC-USDT-SWAP"
    assert ticker.price == Decimal("43250.1")
    assert ticker.source == ExchangeType.OKX
    assert ticker.change_24h == Decimal("450.1")  # 43250.1 - 42800.0
    
    logger.info(f"✅ OKX ticker转换成功: {ticker.symbol} @ {ticker.price}")
    return ticker


def test_binance_ticker_conversion():
    """测试币安ticker数据转换"""
    logger.info("🔍 测试币安ticker数据转换")
    
    # 模拟币安ticker数据
    binance_ticker_data = {
        "symbol": "BTCUSDT",
        "price": "43250.10",
        "priceChange": "450.10",
        "priceChangePercent": "1.05",
        "weightedAvgPrice": "43100.50",
        "prevClosePrice": "42800.00",
        "lastPrice": "43250.10",
        "bidPrice": "43250.00",
        "askPrice": "43250.20",
        "openPrice": "42800.00",
        "highPrice": "43500.00",
        "lowPrice": "42500.00",
        "volume": "12345.67000000",
        "quoteVolume": "534567890.12000000",
        "openTime": 1640908800000,
        "closeTime": 1640995200000,
        "count": 123456
    }
    
    converter = BinanceDataConverter()
    ticker = converter.convert_ticker(binance_ticker_data, DataSource.REST_API)
    
    assert ticker.symbol == "BTC-USDT-SWAP"
    assert ticker.price == Decimal("43250.10")
    assert ticker.source == ExchangeType.BINANCE
    assert ticker.change_24h == Decimal("450.10")
    
    logger.info(f"✅ 币安ticker转换成功: {ticker.symbol} @ {ticker.price}")
    return ticker


def test_okx_kline_conversion():
    """测试OKX K线数据转换"""
    logger.info("🔍 测试OKX K线数据转换")
    
    # 模拟OKX K线数据（数组格式）
    okx_kline_data = [
        "1640995200000",  # 开盘时间
        "43000.0",        # 开盘价
        "43500.0",        # 最高价
        "42500.0",        # 最低价
        "43250.1",        # 收盘价
        "12345.67",       # 成交量
        "534567890.12",   # 成交额
        "1640998800000",  # 收盘时间
        "1"               # 确认状态
    ]
    
    converter = OKXDataConverter()
    kline = converter.convert_kline(okx_kline_data, "BTC-USDT-SWAP", "1h", DataSource.REST_API)
    
    assert kline.symbol == "BTC-USDT-SWAP"
    assert kline.timeframe == "1h"
    assert kline.open == Decimal("43000.0")
    assert kline.close == Decimal("43250.1")
    assert kline.source == ExchangeType.OKX
    assert kline.is_green == True  # 收盘价 > 开盘价
    
    logger.info(f"✅ OKX K线转换成功: {kline.symbol} {kline.timeframe} OHLC({kline.open}, {kline.high}, {kline.low}, {kline.close})")
    return kline


def test_binance_kline_conversion():
    """测试币安K线数据转换"""
    logger.info("🔍 测试币安K线数据转换")
    
    # 模拟币安K线数据（数组格式）
    binance_kline_data = [
        1640995200000,      # 开盘时间
        "43000.00000000",   # 开盘价
        "43500.00000000",   # 最高价
        "42500.00000000",   # 最低价
        "43250.10000000",   # 收盘价
        "12345.67000000",   # 成交量
        1640998799999,      # 收盘时间
        "534567890.12000000", # 成交额
        123456,             # 成交笔数
        "6789.12000000",    # 主动买入成交量
        "293456789.01000000", # 主动买入成交额
        "0"                 # 忽略
    ]
    
    converter = BinanceDataConverter()
    kline = converter.convert_kline(binance_kline_data, "BTC-USDT-SWAP", "1h", DataSource.REST_API)
    
    assert kline.symbol == "BTC-USDT-SWAP"
    assert kline.timeframe == "1h"
    assert kline.open == Decimal("43000.00000000")
    assert kline.close == Decimal("43250.10000000")
    assert kline.source == ExchangeType.BINANCE
    assert kline.trade_count == 123456
    
    logger.info(f"✅ 币安K线转换成功: {kline.symbol} {kline.timeframe} OHLC({kline.open}, {kline.high}, {kline.low}, {kline.close})")
    return kline


def test_factory_function():
    """测试工厂函数"""
    logger.info("🔍 测试数据转换器工厂函数")
    
    okx_converter = get_data_converter(ExchangeType.OKX)
    binance_converter = get_data_converter(ExchangeType.BINANCE)
    
    assert isinstance(okx_converter, OKXDataConverter)
    assert isinstance(binance_converter, BinanceDataConverter)
    
    logger.info("✅ 工厂函数测试成功")


def run_all_tests():
    """运行所有测试"""
    logger.info("🚀 开始数据转换器测试")
    
    try:
        test_okx_ticker_conversion()
        test_binance_ticker_conversion()
        test_okx_kline_conversion()
        test_binance_kline_conversion()
        test_factory_function()
        
        logger.info("✅ 所有数据转换器测试通过")
        return True
        
    except Exception as e:
        logger.error(f"❌ 数据转换器测试失败: {e}")
        return False


if __name__ == "__main__":
    run_all_tests()