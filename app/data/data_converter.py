# -*- coding: utf-8 -*-
"""
数据转换器
Data converter for different data formats
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class DataConverter:
    """数据格式转换器"""
    
    @staticmethod
    def klines_to_dataframe(klines: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        将K线数据转换为DataFrame
        
        Args:
            klines: K线数据列表
            
        Returns:
            OHLCV DataFrame
        """
        try:
            if not klines:
                return pd.DataFrame()
            
            # 提取数据
            data = []
            for kline in klines:
                row = {
                    'timestamp': kline.get('open_time') or kline.get('timestamp'),
                    'open': float(kline.get('open_price', 0)),
                    'high': float(kline.get('high_price', 0)),
                    'low': float(kline.get('low_price', 0)),
                    'close': float(kline.get('close_price', 0)),
                    'volume': float(kline.get('volume', 0)),
                    'quote_volume': float(kline.get('quote_volume', 0)),
                    'trade_count': int(kline.get('trade_count', 0)),
                    'taker_buy_volume': float(kline.get('taker_buy_volume', 0)),
                    'taker_buy_quote_volume': float(kline.get('taker_buy_quote_volume', 0))
                }
                data.append(row)
            
            # 创建DataFrame
            df = pd.DataFrame(data)
            
            # 设置时间索引
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            
            # 数据类型优化
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 
                             'quote_volume', 'taker_buy_volume', 'taker_buy_quote_volume']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if 'trade_count' in df.columns:
                df['trade_count'] = pd.to_numeric(df['trade_count'], errors='coerce').astype('Int64')
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to convert klines to DataFrame: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def dataframe_to_tradingview_format(df: pd.DataFrame) -> Dict[str, List]:
        """
        将DataFrame转换为TradingView格式
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            TradingView格式数据
        """
        try:
            if df.empty:
                return {}
            
            # 确保时间索引
            if not isinstance(df.index, pd.DatetimeIndex):
                if 'timestamp' in df.columns:
                    df = df.set_index('timestamp')
                else:
                    logger.warning("No timestamp column found")
                    return {}
            
            # 转换为TradingView格式
            tv_data = {
                'time': [int(ts.timestamp()) for ts in df.index],
                'open': df['open'].tolist(),
                'high': df['high'].tolist(),
                'low': df['low'].tolist(),
                'close': df['close'].tolist(),
                'volume': df['volume'].tolist()
            }
            
            # 添加其他指标（如果存在）
            indicator_columns = [col for col in df.columns 
                               if col not in ['open', 'high', 'low', 'close', 'volume']]
            
            for col in indicator_columns:
                if df[col].dtype in ['float64', 'int64']:
                    tv_data[col] = df[col].fillna(0).tolist()
                elif df[col].dtype == 'bool':
                    tv_data[col] = df[col].astype(int).tolist()
            
            return tv_data
            
        except Exception as e:
            logger.error(f"Failed to convert to TradingView format: {e}")
            return {}
    
    @staticmethod
    def normalize_symbol(symbol: str, exchange: str = 'binance') -> str:
        """
        标准化交易对名称
        
        Args:
            symbol: 原始交易对名称
            exchange: 交易所名称
            
        Returns:
            标准化的交易对名称
        """
        try:
            symbol = symbol.upper().strip()
            
            # 币安格式标准化
            if exchange.lower() == 'binance':
                # 移除分隔符
                symbol = symbol.replace('/', '').replace('-', '').replace('_', '')
                
                # 确保以USDT结尾（对于现货）或USDT永续合约
                if not symbol.endswith('USDT') and not symbol.endswith('BUSD'):
                    if 'USDT' in symbol:
                        # 重新排列
                        base = symbol.replace('USDT', '')
                        symbol = f"{base}USDT"
                    else:
                        symbol = f"{symbol}USDT"
            
            return symbol
            
        except Exception as e:
            logger.error(f"Failed to normalize symbol {symbol}: {e}")
            return symbol
    
    @staticmethod
    def calculate_returns(df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        计算收益率
        
        Args:
            df: OHLCV DataFrame
            periods: 计算周期列表
            
        Returns:
            包含收益率的DataFrame
        """
        try:
            if df.empty:
                return df
            
            result_df = df.copy()
            
            if periods is None:
                periods = [1, 5, 10, 20]
            
            for period in periods:
                # 价格收益率
                result_df[f'return_{period}'] = df['close'].pct_change(periods=period)
                
                # 对数收益率
                result_df[f'log_return_{period}'] = np.log(df['close'] / df['close'].shift(period))
                
                # 累积收益率
                result_df[f'cumulative_return_{period}'] = (1 + result_df[f'return_{period}']).cumprod() - 1
            
            return result_df
            
        except Exception as e:
            logger.error(f"Failed to calculate returns: {e}")
            return df
    
    @staticmethod
    def resample_ohlcv(df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """
        重采样OHLCV数据到目标时间周期
        
        Args:
            df: 原始OHLCV DataFrame
            target_timeframe: 目标时间周期 (如 '1H', '4H', '1D')
            
        Returns:
            重采样后的DataFrame
        """
        try:
            if df.empty:
                return df
            
            # 确保时间索引
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.error("DataFrame must have DatetimeIndex for resampling")
                return df
            
            # 重采样规则
            agg_dict = {
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }
            
            # 添加其他数值列的聚合规则
            for col in df.columns:
                if col not in agg_dict and df[col].dtype in ['float64', 'int64']:
                    if 'volume' in col.lower():
                        agg_dict[col] = 'sum'
                    else:
                        agg_dict[col] = 'last'
            
            # 执行重采样
            resampled_df = df.resample(target_timeframe).agg(agg_dict)
            
            # 删除空行
            resampled_df = resampled_df.dropna(subset=['open', 'high', 'low', 'close'])
            
            return resampled_df
            
        except Exception as e:
            logger.error(f"Failed to resample data to {target_timeframe}: {e}")
            return df
    
    @staticmethod
    def merge_multi_timeframe_data(timeframe_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        合并多时间周期数据
        
        Args:
            timeframe_data: 时间周期数据字典
            
        Returns:
            合并后的DataFrame
        """
        try:
            if not timeframe_data:
                return pd.DataFrame()
            
            # 以最小时间周期为基准
            timeframe_order = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '3d', '1w']
            
            base_timeframe = None
            base_df = None
            
            # 找到最小时间周期
            for tf in timeframe_order:
                if tf in timeframe_data and not timeframe_data[tf].empty:
                    base_timeframe = tf
                    base_df = timeframe_data[tf].copy()
                    break
            
            if base_df is None:
                return pd.DataFrame()
            
            # 合并其他时间周期的数据
            for timeframe, df in timeframe_data.items():
                if timeframe == base_timeframe or df.empty:
                    continue
                
                # 重命名列以避免冲突
                renamed_df = df.copy()
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    if col in renamed_df.columns:
                        renamed_df[f'{col}_{timeframe}'] = renamed_df[col]
                        renamed_df.drop(col, axis=1, inplace=True)
                
                # 前向填充合并
                base_df = pd.merge_asof(
                    base_df.sort_index(),
                    renamed_df.sort_index(),
                    left_index=True,
                    right_index=True,
                    direction='backward'
                )
            
            return base_df
            
        except Exception as e:
            logger.error(f"Failed to merge multi-timeframe data: {e}")
            return pd.DataFrame()