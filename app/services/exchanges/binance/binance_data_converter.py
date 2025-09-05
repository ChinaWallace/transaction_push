# -*- coding: utf-8 -*-
"""
币安数据格式转换器
Binance Data Format Converter - 将币安数据转换为统一格式
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


class BinanceDataConverter:
    """
    币安数据格式转换器
    Binance Data Format Converter
    
    负责将币安交易所的数据格式转换为与OKX一致的统一格式
    确保不同交易所之间的数据格式完全兼容
    """
    
    @staticmethod
    def convert_symbol_to_standard(binance_symbol: str) -> str:
        """
        将币安符号转换为标准格式
        Convert Binance symbol to standard format
        
        Args:
            binance_symbol: 币安格式符号 (e.g., "BTCUSDT")
            
        Returns:
            str: 标准格式符号 (e.g., "BTC-USDT-SWAP")
        """
        try:
            if binance_symbol.endswith('USDT'):
                base = binance_symbol[:-4]  # 移除USDT
                return f"{base}-USDT-SWAP"
            return binance_symbol
        except Exception as e:
            logger.error(f"❌ 转换币安符号失败: {binance_symbol} - {e}")
            return binance_symbol
    
    @staticmethod
    def convert_symbol_to_binance(standard_symbol: str) -> str:
        """
        将标准符号转换为币安格式
        Convert standard symbol to Binance format
        
        Args:
            standard_symbol: 标准格式符号 (e.g., "BTC-USDT-SWAP")
            
        Returns:
            str: 币安格式符号 (e.g., "BTCUSDT")
        """
        try:
            if '-USDT-SWAP' in standard_symbol:
                return standard_symbol.replace('-USDT-SWAP', 'USDT')
            elif '-USDT' in standard_symbol:
                return standard_symbol.replace('-USDT', 'USDT')
            return standard_symbol
        except Exception as e:
            logger.error(f"❌ 转换标准符号失败: {standard_symbol} - {e}")
            return standard_symbol 
   
    @staticmethod
    def convert_ticker_data(binance_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> TickerData:
        """
        转换ticker数据为统一格式
        Convert ticker data to unified format
        
        Args:
            binance_data: 币安ticker数据
            data_source: 数据源类型
            
        Returns:
            TickerData: 统一格式的ticker数据
        """
        try:
            symbol = binance_data.get('symbol', '')
            standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
            
            # 处理时间戳
            timestamp_ms = binance_data.get('E', binance_data.get('closeTime', 0))
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return TickerData(
                symbol=standard_symbol,
                price=Decimal(str(binance_data.get('lastPrice', binance_data.get('c', '0')))),
                volume_24h=Decimal(str(binance_data.get('volume', binance_data.get('v', '0')))),
                change_24h=Decimal(str(binance_data.get('priceChange', binance_data.get('P', '0')))),
                change_percent_24h=Decimal(str(binance_data.get('priceChangePercent', binance_data.get('P', '0')))),
                high_24h=Decimal(str(binance_data.get('highPrice', binance_data.get('h', '0')))),
                low_24h=Decimal(str(binance_data.get('lowPrice', binance_data.get('l', '0')))),
                timestamp=timestamp,
                source=ExchangeType.BINANCE,
                data_source=data_source,
                bid_price=Decimal(str(binance_data.get('bidPrice', binance_data.get('b', '0')))) if binance_data.get('bidPrice') or binance_data.get('b') else None,
                ask_price=Decimal(str(binance_data.get('askPrice', binance_data.get('a', '0')))) if binance_data.get('askPrice') or binance_data.get('a') else None,
                bid_size=Decimal(str(binance_data.get('bidQty', '0'))) if binance_data.get('bidQty') else None,
                ask_size=Decimal(str(binance_data.get('askQty', '0'))) if binance_data.get('askQty') else None,
                open_price=Decimal(str(binance_data.get('openPrice', binance_data.get('o', '0')))) if binance_data.get('openPrice') or binance_data.get('o') else None,
                quote_volume_24h=Decimal(str(binance_data.get('quoteVolume', '0'))) if binance_data.get('quoteVolume') else None,
                trade_count_24h=int(binance_data.get('count', 0)) if binance_data.get('count') else None,
                raw_data=binance_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换ticker数据失败: {e}")
            raise ValueError(f"Failed to convert Binance ticker data: {e}")
    
    @staticmethod
    def convert_kline_data(binance_klines: List[List], symbol: str, timeframe: str, 
                          data_source: DataSource = DataSource.REST_API) -> List[KlineData]:
        """
        转换K线数据为统一格式
        Convert kline data to unified format
        
        Args:
            binance_klines: 币安K线数据列表
            symbol: 标准格式交易对符号
            timeframe: 时间周期
            data_source: 数据源类型
            
        Returns:
            List[KlineData]: 统一格式的K线数据列表
        """
        try:
            converted_klines = []
            
            for kline in binance_klines:
                if len(kline) >= 6:
                    converted_klines.append(KlineData(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=int(kline[0]),  # 开盘时间
                        open=Decimal(str(kline[1])),
                        high=Decimal(str(kline[2])),
                        low=Decimal(str(kline[3])),
                        close=Decimal(str(kline[4])),
                        volume=Decimal(str(kline[5])),
                        source=ExchangeType.BINANCE,
                        data_source=data_source,
                        quote_volume=Decimal(str(kline[7])) if len(kline) > 7 else None,
                        trade_count=int(kline[8]) if len(kline) > 8 else None,
                        taker_buy_volume=Decimal(str(kline[9])) if len(kline) > 9 else None,
                        taker_buy_quote_volume=Decimal(str(kline[10])) if len(kline) > 10 else None,
                        close_time=int(kline[6]) if len(kline) > 6 else None,
                        raw_data={'kline': kline}
                    ))
            
            return sorted(converted_klines, key=lambda x: x.timestamp)
            
        except Exception as e:
            logger.error(f"❌ 转换K线数据失败: {e}")
            raise ValueError(f"Failed to convert Binance kline data: {e}")  
  
    @staticmethod
    def convert_funding_rate_data(binance_data: Dict[str, Any], data_source: DataSource = DataSource.REST_API) -> FundingRateData:
        """
        转换资金费率数据为统一格式
        Convert funding rate data to unified format
        
        Args:
            binance_data: 币安资金费率数据
            data_source: 数据源类型
            
        Returns:
            FundingRateData: 统一格式的资金费率数据
        """
        try:
            symbol = binance_data.get('symbol', '')
            standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
            
            # 处理下次资金费率时间
            next_funding_time_ms = binance_data.get('nextFundingTime', 0)
            if isinstance(next_funding_time_ms, (int, float)) and next_funding_time_ms > 0:
                next_funding_time = datetime.fromtimestamp(next_funding_time_ms / 1000)
            else:
                next_funding_time = datetime.now()
            
            # 处理时间戳
            timestamp_ms = binance_data.get('time', binance_data.get('E', 0))
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return FundingRateData(
                symbol=standard_symbol,
                funding_rate=Decimal(str(binance_data.get('lastFundingRate', binance_data.get('r', '0')))),
                next_funding_time=next_funding_time,
                timestamp=timestamp,
                source=ExchangeType.BINANCE,
                data_source=data_source,
                mark_price=Decimal(str(binance_data.get('markPrice', '0'))) if binance_data.get('markPrice') else None,
                index_price=Decimal(str(binance_data.get('indexPrice', '0'))) if binance_data.get('indexPrice') else None,
                estimated_rate=Decimal(str(binance_data.get('estimatedSettlePrice', '0'))) if binance_data.get('estimatedSettlePrice') else None,
                funding_interval=8,  # 币安默认8小时
                raw_data=binance_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换资金费率数据失败: {e}")
            raise ValueError(f"Failed to convert Binance funding rate data: {e}")
    
    @staticmethod
    def convert_open_interest_data(binance_data: Dict[str, Any], symbol: str, 
                                  data_source: DataSource = DataSource.REST_API) -> OpenInterestData:
        """
        转换持仓量数据为统一格式
        Convert open interest data to unified format
        
        Args:
            binance_data: 币安持仓量数据
            symbol: 标准格式交易对符号
            data_source: 数据源类型
            
        Returns:
            OpenInterestData: 统一格式的持仓量数据
        """
        try:
            # 处理时间戳
            timestamp_ms = binance_data.get('time', 0)
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return OpenInterestData(
                symbol=symbol,
                open_interest=Decimal(str(binance_data.get('openInterest', '0'))),
                timestamp=timestamp,
                source=ExchangeType.BINANCE,
                data_source=data_source,
                open_interest_value=Decimal(str(binance_data.get('openInterestValue', '0'))) if binance_data.get('openInterestValue') else None,
                currency='USDT',
                raw_data=binance_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换持仓量数据失败: {e}")
            raise ValueError(f"Failed to convert Binance open interest data: {e}")
    
    @staticmethod
    def convert_trade_data(binance_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> TradeData:
        """
        转换交易数据为统一格式
        Convert trade data to unified format
        
        Args:
            binance_data: 币安交易数据
            data_source: 数据源类型
            
        Returns:
            TradeData: 统一格式的交易数据
        """
        try:
            symbol = binance_data.get('s', '')
            standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
            
            # 处理时间戳
            timestamp_ms = binance_data.get('T', binance_data.get('time', 0))
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            return TradeData(
                symbol=standard_symbol,
                trade_id=str(binance_data.get('a', binance_data.get('id', ''))),
                price=Decimal(str(binance_data.get('p', binance_data.get('price', '0')))),
                size=Decimal(str(binance_data.get('q', binance_data.get('qty', '0')))),
                side='sell' if binance_data.get('m', False) else 'buy',  # m表示是否为买方成交
                timestamp=timestamp,
                source=ExchangeType.BINANCE,
                data_source=data_source,
                is_maker=binance_data.get('m', None),
                raw_data=binance_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换交易数据失败: {e}")
            raise ValueError(f"Failed to convert Binance trade data: {e}")
    
    @staticmethod
    def convert_order_book_data(binance_data: Dict[str, Any], data_source: DataSource = DataSource.WEBSOCKET) -> OrderBookData:
        """
        转换订单簿数据为统一格式
        Convert order book data to unified format
        
        Args:
            binance_data: 币安订单簿数据
            data_source: 数据源类型
            
        Returns:
            OrderBookData: 统一格式的订单簿数据
        """
        try:
            symbol = binance_data.get('s', binance_data.get('symbol', ''))
            standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
            
            # 处理时间戳
            timestamp_ms = binance_data.get('E', binance_data.get('T', 0))
            if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                timestamp = datetime.now()
            
            # 转换买卖盘数据
            bids = [[Decimal(str(bid[0])), Decimal(str(bid[1]))] for bid in binance_data.get('bids', [])]
            asks = [[Decimal(str(ask[0])), Decimal(str(ask[1]))] for ask in binance_data.get('asks', [])]
            
            return OrderBookData(
                symbol=standard_symbol,
                bids=bids,
                asks=asks,
                timestamp=timestamp,
                source=ExchangeType.BINANCE,
                data_source=data_source,
                raw_data=binance_data
            )
            
        except Exception as e:
            logger.error(f"❌ 转换币安订单簿数据失败: {e}")
            raise ValueError(f"Failed to convert Binance order book data: {e}")   
 
    @staticmethod
    def convert_instrument_data(binance_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换交易对信息为统一格式
        Convert instrument data to unified format
        
        Args:
            binance_data: 币安交易对信息
            
        Returns:
            Dict[str, Any]: 统一格式的交易对信息
        """
        try:
            symbol = binance_data.get('symbol', '')
            standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
            
            # 获取过滤器信息
            filters = binance_data.get('filters', [])
            min_size = 0.0
            tick_size = 0.0
            
            for filter_info in filters:
                if filter_info.get('filterType') == 'LOT_SIZE':
                    min_size = float(filter_info.get('minQty', '0'))
                elif filter_info.get('filterType') == 'PRICE_FILTER':
                    tick_size = float(filter_info.get('tickSize', '0'))
            
            return {
                'symbol': standard_symbol,
                'base_currency': binance_data.get('baseAsset', ''),
                'quote_currency': binance_data.get('quoteAsset', ''),
                'contract_type': 'PERPETUAL' if binance_data.get('contractType') == 'PERPETUAL' else binance_data.get('contractType', ''),
                'status': 'active' if binance_data.get('status') == 'TRADING' else 'inactive',
                'min_size': min_size,
                'tick_size': tick_size,
                'source': 'binance'
            }
            
        except Exception as e:
            logger.error(f"❌ 转换交易对信息失败: {e}")
            return {}
    
    @staticmethod
    def convert_account_balance_data(binance_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换账户余额数据为统一格式
        Convert account balance data to unified format
        
        Args:
            binance_data: 币安账户余额数据
            
        Returns:
            Dict[str, Any]: 统一格式的账户余额数据
        """
        try:
            balances = {}
            total_equity = 0
            
            for asset in binance_data.get('assets', []):
                currency = asset.get('asset', '')
                equity = float(asset.get('walletBalance', '0'))
                available = float(asset.get('availableBalance', '0'))
                
                if equity > 0:
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
                'update_time': datetime.now(),
                'source': 'binance'
            }
            
        except Exception as e:
            logger.error(f"❌ 转换账户余额数据失败: {e}")
            return {}
    
    @staticmethod
    def convert_position_data(binance_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        转换持仓数据为统一格式
        Convert position data to unified format
        
        Args:
            binance_positions: 币安持仓数据列表
            
        Returns:
            List[Dict[str, Any]]: 统一格式的持仓数据列表
        """
        try:
            converted_positions = []
            
            for pos in binance_positions:
                pos_size = float(pos.get('positionAmt', '0'))
                if pos_size != 0:  # 只返回有持仓的
                    symbol = pos.get('symbol', '')
                    standard_symbol = BinanceDataConverter.convert_symbol_to_standard(symbol)
                    
                    converted_positions.append({
                        'symbol': standard_symbol,
                        'side': 'long' if pos_size > 0 else 'short',
                        'size': abs(pos_size),
                        'avg_price': float(pos.get('entryPrice', '0')),
                        'mark_price': float(pos.get('markPrice', '0')),
                        'unrealized_pnl': float(pos.get('unRealizedProfit', '0')),
                        'leverage': float(pos.get('leverage', '1')),
                        'margin': float(pos.get('isolatedMargin', '0')),
                        'update_time': datetime.now(),
                        'source': 'binance'
                    })
            
            return converted_positions
            
        except Exception as e:
            logger.error(f"❌ 转换持仓数据失败: {e}")
            return []    

    @staticmethod
    def convert_timeframe_to_binance(standard_timeframe: str) -> str:
        """
        转换时间周期为币安格式
        Convert timeframe to Binance format
        
        Args:
            standard_timeframe: 标准时间周期 (e.g., "1H", "4H", "1D")
            
        Returns:
            str: 币安时间周期格式 (e.g., "1h", "4h", "1d")
        """
        try:
            # 时间周期映射表
            timeframe_mapping = {
                '1m': '1m', '1M': '1m',
                '3m': '3m', '3M': '3m',
                '5m': '5m', '5M': '5m',
                '15m': '15m', '15M': '15m',
                '30m': '30m', '30M': '30m',
                '1h': '1h', '1H': '1h',
                '2h': '2h', '2H': '2h',
                '4h': '4h', '4H': '4h',
                '6h': '6h', '6H': '6h',
                '8h': '8h', '8H': '8h',
                '12h': '12h', '12H': '12h',
                '1d': '1d', '1D': '1d',
                '3d': '3d', '3D': '3d',
                '1w': '1w', '1W': '1w',
                '1M': '1M'  # 月线
            }
            
            return timeframe_mapping.get(standard_timeframe, '1h')
            
        except Exception as e:
            logger.error(f"❌ 转换时间周期失败: {standard_timeframe} - {e}")
            return '1h'
    
    @staticmethod
    def convert_timeframe_from_binance(binance_timeframe: str) -> str:
        """
        从币安时间周期转换为标准格式
        Convert from Binance timeframe to standard format
        
        Args:
            binance_timeframe: 币安时间周期 (e.g., "1h", "4h", "1d")
            
        Returns:
            str: 标准时间周期格式 (e.g., "1H", "4H", "1D")
        """
        try:
            # 反向映射表
            reverse_mapping = {
                '1m': '1m',
                '3m': '3m',
                '5m': '5m',
                '15m': '15m',
                '30m': '30m',
                '1h': '1H',
                '2h': '2H',
                '4h': '4H',
                '6h': '6H',
                '8h': '8H',
                '12h': '12H',
                '1d': '1D',
                '3d': '3D',
                '1w': '1W',
                '1M': '1M'
            }
            
            return reverse_mapping.get(binance_timeframe, '1H')
            
        except Exception as e:
            logger.error(f"❌ 从币安时间周期转换失败: {binance_timeframe} - {e}")
            return '1H'
    
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
    def batch_convert_symbols_to_standard(binance_symbols: List[str]) -> List[str]:
        """
        批量转换币安符号为标准格式
        Batch convert Binance symbols to standard format
        
        Args:
            binance_symbols: 币安符号列表
            
        Returns:
            List[str]: 标准格式符号列表
        """
        try:
            return [
                BinanceDataConverter.convert_symbol_to_standard(symbol)
                for symbol in binance_symbols
            ]
        except Exception as e:
            logger.error(f"❌ 批量转换符号失败: {e}")
            return []
    
    @staticmethod
    def batch_convert_symbols_to_binance(standard_symbols: List[str]) -> List[str]:
        """
        批量转换标准符号为币安格式
        Batch convert standard symbols to Binance format
        
        Args:
            standard_symbols: 标准格式符号列表
            
        Returns:
            List[str]: 币安格式符号列表
        """
        try:
            return [
                BinanceDataConverter.convert_symbol_to_binance(symbol)
                for symbol in standard_symbols
            ]
        except Exception as e:
            logger.error(f"❌ 批量转换符号失败: {e}")
            return []