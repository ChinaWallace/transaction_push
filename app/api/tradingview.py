# -*- coding: utf-8 -*-
"""
TradingView功能API路由
TradingView features API routes
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict, Any

from app.core.logging import get_logger
from app.core.config import get_settings
from app.data.data_provider import DataProvider
from app.utils.tradingview_indicators import (
    TradingViewIndicators, EnhancedSuperTrend, 
    VolumeProfileIndicator, OrderFlowIndicator, MarketStructureIndicator
)
from app.data.data_converter import DataConverter

logger = get_logger(__name__)
router = APIRouter()

# 获取配置
settings = get_settings()
converter = DataConverter()

def get_data_provider() -> DataProvider:
    """获取数据提供者实例"""
    return DataProvider()


@router.get("/indicators/supertrend/{symbol}",
           summary="增强版SuperTrend指标",
           response_model=Dict[str, Any])
async def get_enhanced_supertrend(
    symbol: str,
    timeframe: str = Query(default="1h", description="时间周期"),
    period: int = Query(default=10, description="ATR周期"),
    factor: float = Query(default=3.0, description="倍数因子"),
    limit: int = Query(default=100, description="数据条数")
):
    """
    获取增强版SuperTrend指标数据
    
    Args:
        symbol: 交易对名称
        timeframe: 时间周期
        period: ATR计算周期
        factor: SuperTrend倍数因子
        limit: 返回数据条数
        
    Returns:
        包含SuperTrend指标的数据
    """
    try:
        # 检查TradingView功能是否启用
        if not settings.tradingview_config.get('enable_pine_indicators', True):
            raise HTTPException(status_code=403, detail="TradingView indicators are disabled")
        
        # 获取OHLCV数据
        data_provider = get_data_provider()
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 计算增强版SuperTrend
        supertrend = EnhancedSuperTrend(atr_period=period, factor=factor)
        df_with_st = supertrend.calculate(df)
        
        # 转换为TradingView格式
        tv_data = converter.dataframe_to_tradingview_format(df_with_st)
        
        # 获取最新信号
        latest = df_with_st.iloc[-1]
        current_signal = {
            'trend_direction': 'up' if latest['supertrend_direction'] else 'down',
            'supertrend_value': float(latest['supertrend']),
            'current_price': float(latest['close']),
            'bullish_signal': bool(latest.get('bullish_signal', False)),
            'bearish_signal': bool(latest.get('bearish_signal', False)),
            'trend_change': bool(latest.get('trend_change', False))
        }
        
        return {
            'success': True,
            'data': {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'parameters': {'period': period, 'factor': factor},
                'chart_data': tv_data,
                'current_signal': current_signal,
                'data_points': len(df_with_st)
            },
            'message': f"SuperTrend indicator calculated for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"SuperTrend calculation failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Indicator calculation failed: {str(e)}")


@router.get("/indicators/volume-profile/{symbol}",
           summary="成交量分布分析",
           response_model=Dict[str, Any])
async def get_volume_profile(
    symbol: str,
    timeframe: str = Query(default="1h", description="时间周期"),
    lookback_periods: int = Query(default=100, description="回看周期数"),
    num_bins: int = Query(default=20, description="价格区间数量")
):
    """
    获取成交量分布分析
    
    Args:
        symbol: 交易对名称
        timeframe: 时间周期
        lookback_periods: 分析的历史周期数
        num_bins: 价格区间划分数量
        
    Returns:
        成交量分布数据
    """
    try:
        # 检查功能是否启用
        if not settings.tradingview_config.get('enable_volume_profile', True):
            raise HTTPException(status_code=403, detail="Volume Profile is disabled")
        
        # 获取数据
        data_provider = get_data_provider()
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=lookback_periods + 50)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 计算成交量分布
        vp_indicator = VolumeProfileIndicator(num_bins=num_bins)
        volume_profile = vp_indicator.calculate(df, lookback_periods)
        
        return {
            'success': True,
            'data': {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'parameters': {
                    'lookback_periods': lookback_periods,
                    'num_bins': num_bins
                },
                'volume_profile': volume_profile['volume_profile'],
                'key_levels': {
                    'poc_price': volume_profile['poc_price'],
                    'poc_volume': volume_profile['poc_volume'],
                    'value_area_high': volume_profile['value_area_high'],
                    'value_area_low': volume_profile['value_area_low']
                },
                'statistics': {
                    'total_volume': volume_profile['total_volume'],
                    'price_range': volume_profile['price_range']
                }
            },
            'message': f"Volume Profile calculated for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Volume Profile calculation failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Volume Profile calculation failed: {str(e)}")


@router.get("/indicators/order-flow/{symbol}",
           summary="订单流分析",
           response_model=Dict[str, Any])
async def get_order_flow(
    symbol: str,
    timeframe: str = Query(default="1h", description="时间周期"),
    limit: int = Query(default=100, description="数据条数")
):
    """
    获取订单流分析数据
    
    Args:
        symbol: 交易对名称
        timeframe: 时间周期
        limit: 数据条数
        
    Returns:
        订单流分析数据
    """
    try:
        # 检查功能是否启用
        if not settings.tradingview_config.get('enable_order_flow', False):
            raise HTTPException(status_code=403, detail="Order Flow analysis is disabled")
        
        # 获取数据
        data_provider = get_data_provider()
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 计算订单流
        df_with_flow = OrderFlowIndicator.calculate_delta(df)
        
        # 转换为TradingView格式
        tv_data = converter.dataframe_to_tradingview_format(df_with_flow)
        
        # 获取最新数据
        latest = df_with_flow.iloc[-1]
        current_flow = {
            'buy_volume': float(latest['buy_volume']),
            'sell_volume': float(latest['sell_volume']),
            'delta': float(latest['delta']),
            'cumulative_delta': float(latest['cumulative_delta']),
            'delta_divergence': bool(latest.get('delta_divergence', False))
        }
        
        # 计算统计数据
        total_buy_volume = df_with_flow['buy_volume'].sum()
        total_sell_volume = df_with_flow['sell_volume'].sum()
        
        return {
            'success': True,
            'data': {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'chart_data': tv_data,
                'current_flow': current_flow,
                'statistics': {
                    'total_buy_volume': float(total_buy_volume),
                    'total_sell_volume': float(total_sell_volume),
                    'buy_sell_ratio': float(total_buy_volume / total_sell_volume) if total_sell_volume > 0 else 0,
                    'data_points': len(df_with_flow)
                }
            },
            'message': f"Order Flow analysis completed for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Order Flow analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Order Flow analysis failed: {str(e)}")


@router.get("/indicators/market-structure/{symbol}",
           summary="市场结构分析",
           response_model=Dict[str, Any])
async def get_market_structure(
    symbol: str,
    timeframe: str = Query(default="1h", description="时间周期"),
    swing_window: int = Query(default=5, description="摆动点检测窗口"),
    min_touches: int = Query(default=2, description="支撑阻力最小触及次数"),
    limit: int = Query(default=200, description="数据条数")
):
    """
    获取市场结构分析
    
    Args:
        symbol: 交易对名称
        timeframe: 时间周期
        swing_window: 摆动点检测窗口大小
        min_touches: 支撑阻力位最小触及次数
        limit: 数据条数
        
    Returns:
        市场结构分析数据
    """
    try:
        # 获取数据
        data_provider = get_data_provider()
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 寻找摆动点
        df_with_swings = MarketStructureIndicator.find_swing_points(df, window=swing_window)
        
        # 计算支撑阻力位
        sr_levels = MarketStructureIndicator.calculate_support_resistance(
            df_with_swings, min_touches=min_touches
        )
        
        # 提取摆动点数据
        swing_highs = df_with_swings[df_with_swings['swing_high']].index.tolist()
        swing_lows = df_with_swings[df_with_swings['swing_low']].index.tolist()
        
        swing_high_prices = df_with_swings.loc[df_with_swings['swing_high'], 'high'].tolist()
        swing_low_prices = df_with_swings.loc[df_with_swings['swing_low'], 'low'].tolist()
        
        # 当前价格
        current_price = float(df['close'].iloc[-1])
        
        return {
            'success': True,
            'data': {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'parameters': {
                    'swing_window': swing_window,
                    'min_touches': min_touches
                },
                'swing_points': {
                    'highs': {
                        'timestamps': [ts.isoformat() for ts in swing_highs],
                        'prices': swing_high_prices
                    },
                    'lows': {
                        'timestamps': [ts.isoformat() for ts in swing_lows],
                        'prices': swing_low_prices
                    }
                },
                'support_resistance': {
                    'support_levels': sr_levels['support'],
                    'resistance_levels': sr_levels['resistance']
                },
                'current_analysis': {
                    'current_price': current_price,
                    'nearest_support': min(sr_levels['support'], key=lambda x: abs(x - current_price)) if sr_levels['support'] else None,
                    'nearest_resistance': min(sr_levels['resistance'], key=lambda x: abs(x - current_price)) if sr_levels['resistance'] else None
                }
            },
            'message': f"Market structure analysis completed for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Market structure analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Market structure analysis failed: {str(e)}")


@router.post("/indicators/pine-script",
            summary="Pine Script风格指标计算",
            response_model=Dict[str, Any])
async def calculate_pine_indicators(
    request: Dict[str, Any] = Body(...)
):
    """
    使用Pine Script风格计算自定义指标
    
    Request Body:
    {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "indicators": [
            {"type": "sma", "source": "close", "length": 20},
            {"type": "ema", "source": "close", "length": 20},
            {"type": "rma", "source": "close", "length": 14}
        ],
        "limit": 100
    }
    """
    try:
        # 检查功能是否启用
        if not settings.tradingview_config.get('enable_pine_indicators', True):
            raise HTTPException(status_code=403, detail="Pine Script indicators are disabled")
        
        symbol = request.get('symbol')
        timeframe = request.get('timeframe', '1h')
        indicators = request.get('indicators', [])
        limit = request.get('limit', 100)
        
        if not symbol or not indicators:
            raise HTTPException(status_code=400, detail="Symbol and indicators are required")
        
        # 获取数据
        data_provider = get_data_provider()
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 计算指标
        result_df = df.copy()
        
        for indicator in indicators:
            indicator_type = indicator.get('type')
            source = indicator.get('source', 'close')
            length = indicator.get('length', 20)
            
            if source not in df.columns:
                continue
            
            source_series = df[source]
            
            if indicator_type == 'sma':
                result_df[f'sma_{length}'] = TradingViewIndicators.pine_sma(source_series, length)
            elif indicator_type == 'ema':
                result_df[f'ema_{length}'] = TradingViewIndicators.pine_ema(source_series, length)
            elif indicator_type == 'rma':
                result_df[f'rma_{length}'] = TradingViewIndicators.pine_rma(source_series, length)
            elif indicator_type == 'highest':
                result_df[f'highest_{length}'] = TradingViewIndicators.pine_highest(source_series, length)
            elif indicator_type == 'lowest':
                result_df[f'lowest_{length}'] = TradingViewIndicators.pine_lowest(source_series, length)
            elif indicator_type == 'stdev':
                result_df[f'stdev_{length}'] = TradingViewIndicators.pine_stdev(source_series, length)
        
        # 转换为TradingView格式
        tv_data = converter.dataframe_to_tradingview_format(result_df)
        
        return {
            'success': True,
            'data': {
                'symbol': symbol.upper(),
                'timeframe': timeframe,
                'indicators_calculated': len(indicators),
                'chart_data': tv_data,
                'data_points': len(result_df)
            },
            'message': f"Pine Script indicators calculated for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Pine Script indicators calculation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Indicators calculation failed: {str(e)}")


@router.get("/config",
           summary="获取TradingView配置",
           response_model=Dict[str, Any])
async def get_tradingview_config():
    """获取当前TradingView功能配置"""
    try:
        return {
            'success': True,
            'data': {
                'tradingview_config': settings.tradingview_config,
                'strategy_config': settings.strategy_config,
                'cache_config': settings.cache_config,
                'supported_timeframes': settings.tradingview_config.get('chart_timeframes', []),
                'enabled_features': {
                    'pine_indicators': settings.tradingview_config.get('enable_pine_indicators', True),
                    'volume_profile': settings.tradingview_config.get('enable_volume_profile', True),
                    'order_flow': settings.tradingview_config.get('enable_order_flow', False)
                }
            },
            'message': "TradingView configuration retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to get TradingView config: {e}")
        raise HTTPException(status_code=500, detail="Failed to get configuration")