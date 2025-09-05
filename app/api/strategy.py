# -*- coding: utf-8 -*-
"""
策略分析API路由
Strategy analysis API routes
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import List, Dict, Any

from app.core.logging import get_logger
from app.core.config import get_settings
from app.data.data_provider import DataProvider
from app.strategies import SuperTrendStrategy
from app.strategies.base_strategy import MarketData, SignalStrength

logger = get_logger(__name__)
router = APIRouter()

# 获取配置和服务
settings = get_settings()
data_provider = DataProvider()


@router.get("/supertrend/analyze/{symbol}",
           summary="SuperTrend策略分析",
           response_model=Dict[str, Any])
async def analyze_supertrend_strategy(
    symbol: str,
    timeframe: str = Query(default="1h", description="时间周期"),
    period: int = Query(default=10, description="SuperTrend周期"),
    multiplier: float = Query(default=3.0, description="SuperTrend倍数"),
    limit: int = Query(default=100, description="数据条数")
):
    """
    使用SuperTrend策略分析单个交易对
    
    Args:
        symbol: 交易对名称
        timeframe: 时间周期
        period: SuperTrend计算周期
        multiplier: SuperTrend倍数因子
        limit: 数据条数
        
    Returns:
        SuperTrend策略分析结果
    """
    try:
        # 获取数据
        df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=limit)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
        # 创建策略
        strategy_config = {
            'period': period,
            'multiplier': multiplier,
            'timeframes': [timeframe]
        }
        strategy = SuperTrendStrategy(strategy_config)
        
        # 创建市场数据对象
        market_data = MarketData(
            symbol=symbol.upper(),
            timeframe=timeframe,
            ohlcv=df,
            indicators={},
            metadata={}
        )
        
        # 执行策略分析
        signal = strategy.analyze(market_data)
        
        # 格式化通知消息
        notification_message = strategy.format_signal_message(signal)
        
        return {
            'success': True,
            'data': {
                'signal': signal.to_dict(),
                'strategy_info': strategy.get_strategy_info(),
                'notification_message': notification_message,
                'should_notify': signal.strength in [SignalStrength.VERY_STRONG, SignalStrength.STRONG]
            },
            'message': f"SuperTrend strategy analysis completed for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"SuperTrend strategy analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Strategy analysis failed: {str(e)}")


@router.get("/supertrend/multi-timeframe/{symbol}",
           summary="SuperTrend多周期分析",
           response_model=Dict[str, Any])
async def analyze_multi_timeframe_supertrend(
    symbol: str,
    timeframes: List[str] = Query(default=["1d", "4h", "1h", "15m"], description="时间周期列表"),
    period: int = Query(default=10, description="SuperTrend周期"),
    multiplier: float = Query(default=3.0, description="SuperTrend倍数")
):
    """
    SuperTrend多周期策略分析
    
    Args:
        symbol: 交易对名称
        timeframes: 时间周期列表
        period: SuperTrend计算周期
        multiplier: SuperTrend倍数因子
        
    Returns:
        多周期SuperTrend分析结果
    """
    try:
        # 获取多周期数据
        timeframe_data = await data_provider.get_multi_timeframe_data(
            symbol=symbol.upper(),
            timeframes=timeframes
        )
        
        # 检查数据
        valid_timeframes = {tf: df for tf, df in timeframe_data.items() if not df.empty}
        
        if not valid_timeframes:
            raise HTTPException(status_code=404, detail=f"No valid data found for {symbol}")
        
        # 创建策略
        strategy_config = {
            'period': period,
            'multiplier': multiplier,
            'timeframes': list(valid_timeframes.keys())
        }
        strategy = SuperTrendStrategy(strategy_config)
        
        # 执行多周期分析
        signal = strategy.analyze_multi_timeframe(valid_timeframes)
        
        # 格式化通知消息
        notification_message = strategy.format_signal_message(signal)
        
        # 获取各周期的趋势状态
        trends_detail = {}
        for tf, df in valid_timeframes.items():
            if len(df) > 0:
                df_with_indicators = strategy.populate_indicators(df.copy())
                if not df_with_indicators.empty and 'supertrend_direction' in df_with_indicators.columns:
                    latest_trend = df_with_indicators['supertrend_direction'].iloc[-1]
                    trends_detail[tf] = {
                        'direction': 'up' if latest_trend else 'down',
                        'supertrend_value': float(df_with_indicators['supertrend'].iloc[-1]) if 'supertrend' in df_with_indicators.columns else None,
                        'current_price': float(df['close'].iloc[-1])
                    }
        
        return {
            'success': True,
            'data': {
                'signal': signal.to_dict(),
                'trends_detail': trends_detail,
                'strategy_info': strategy.get_strategy_info(),
                'notification_message': notification_message,
                'valid_timeframes': list(valid_timeframes.keys()),
                'should_notify': signal.strength in [SignalStrength.VERY_STRONG, SignalStrength.STRONG]
            },
            'message': f"Multi-timeframe SuperTrend analysis completed for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Multi-timeframe SuperTrend analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Multi-timeframe analysis failed: {str(e)}")


@router.post("/batch-analyze",
            summary="批量策略分析",
            response_model=Dict[str, Any])
async def batch_strategy_analysis(
    request: Dict[str, Any] = Body(...)
):
    """
    批量策略分析
    
    Request Body:
    {
        "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        "strategy": "supertrend",
        "timeframe": "1h",
        "config": {
            "period": 10,
            "multiplier": 3.0
        }
    }
    """
    try:
        symbols = request.get('symbols', [])
        strategy_type = request.get('strategy', 'supertrend')
        timeframe = request.get('timeframe', '1h')
        strategy_config = request.get('config', {})
        
        if not symbols:
            raise HTTPException(status_code=400, detail="Symbols list is required")
        
        if len(symbols) > 20:
            raise HTTPException(status_code=400, detail="Too many symbols (max 20)")
        
        # 创建策略
        if strategy_type == 'supertrend':
            default_config = settings.strategy_config.get('supertrend', {})
            default_config.update(strategy_config)
            strategy = SuperTrendStrategy(default_config)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy_type}")
        
        # 批量分析
        results = {}
        
        for symbol in symbols:
            try:
                # 获取数据
                df = await data_provider.get_ohlcv(symbol.upper(), timeframe, limit=100)
                
                if df.empty:
                    results[symbol] = {
                        'success': False,
                        'error': 'No data available'
                    }
                    continue
                
                # 创建市场数据对象
                market_data = MarketData(
                    symbol=symbol.upper(),
                    timeframe=timeframe,
                    ohlcv=df,
                    indicators={},
                    metadata={}
                )
                
                # 执行分析
                signal = strategy.analyze(market_data)
                
                results[symbol] = {
                    'success': True,
                    'signal': signal.to_dict(),
                    'should_notify': signal.strength in [SignalStrength.VERY_STRONG, SignalStrength.STRONG]
                }
                
            except Exception as e:
                logger.warning(f"Analysis failed for {symbol}: {e}")
                results[symbol] = {
                    'success': False,
                    'error': str(e)
                }
        
        # 统计结果
        successful_analyses = sum(1 for r in results.values() if r.get('success', False))
        strong_signals = sum(1 for r in results.values() 
                           if r.get('success', False) and r.get('should_notify', False))
        
        return {
            'success': True,
            'data': {
                'results': results,
                'statistics': {
                    'total_symbols': len(symbols),
                    'successful_analyses': successful_analyses,
                    'failed_analyses': len(symbols) - successful_analyses,
                    'strong_signals': strong_signals
                },
                'strategy_info': strategy.get_strategy_info()
            },
            'message': f"Batch analysis completed: {successful_analyses}/{len(symbols)} successful"
        }
        
    except Exception as e:
        logger.error(f"Batch strategy analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch analysis failed: {str(e)}")


@router.get("/backtest/{symbol}",
           summary="策略回测",
           response_model=Dict[str, Any])
async def backtest_strategy(
    symbol: str,
    strategy_type: str = Query(default="supertrend", description="策略类型"),
    timeframe: str = Query(default="1h", description="时间周期"),
    days: int = Query(default=30, ge=7, le=90, description="回测天数"),
    period: int = Query(default=10, description="SuperTrend周期"),
    multiplier: float = Query(default=3.0, description="SuperTrend倍数")
):
    """
    策略回测分析
    
    Args:
        symbol: 交易对名称
        strategy_type: 策略类型
        timeframe: 时间周期
        days: 回测天数
        period: SuperTrend周期
        multiplier: SuperTrend倍数
        
    Returns:
        回测结果
    """
    try:
        # 获取历史数据
        historical_df = await data_provider.get_historical_data(
            symbol=symbol.upper(),
            timeframe=timeframe,
            days=days
        )
        
        if historical_df.empty:
            raise HTTPException(status_code=404, detail=f"No historical data found for {symbol}")
        
        # 创建策略
        if strategy_type == 'supertrend':
            strategy_config = {
                'period': period,
                'multiplier': multiplier,
                'timeframes': [timeframe]
            }
            strategy = SuperTrendStrategy(strategy_config)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy_type}")
        
        # 准备回测数据
        window_size = max(50, period * 3)  # 确保有足够的数据计算指标
        historical_data = []
        
        # 每天创建一个数据点进行回测
        daily_step = 24 if timeframe == '1h' else 1
        
        for i in range(window_size, len(historical_df), daily_step):
            df_slice = historical_df.iloc[i-window_size:i]
            
            market_data = MarketData(
                symbol=symbol.upper(),
                timeframe=timeframe,
                ohlcv=df_slice,
                indicators={},
                metadata={'timestamp': df_slice.index[-1]}
            )
            historical_data.append(market_data)
        
        # 执行回测
        backtest_results = strategy.backtest(historical_data)
        
        # 计算额外的回测指标
        signals = [signal for signal in backtest_results.get('signals', []) if signal]
        
        if signals:
            # 信号分布分析
            signal_types = [s['signal_type'] for s in signals]
            buy_signals = sum(1 for st in signal_types if st in ['buy', 'strong_buy'])
            sell_signals = sum(1 for st in signal_types if st in ['sell', 'strong_sell'])
            
            # 强度分布
            strengths = [s['strength'] for s in signals]
            strong_signals = sum(1 for s in strengths if s >= 4)
            
            # 置信度统计
            confidences = [s['confidence'] for s in signals]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            enhanced_stats = {
                'signal_distribution': {
                    'buy_signals': buy_signals,
                    'sell_signals': sell_signals,
                    'hold_signals': len(signals) - buy_signals - sell_signals
                },
                'strength_analysis': {
                    'strong_signals': strong_signals,
                    'strong_signal_ratio': strong_signals / len(signals) if signals else 0
                },
                'confidence_analysis': {
                    'average_confidence': avg_confidence,
                    'high_confidence_signals': sum(1 for c in confidences if c >= 0.7)
                }
            }
            
            backtest_results['statistics'].update(enhanced_stats)
        
        return {
            'success': True,
            'data': {
                'backtest_results': backtest_results,
                'parameters': {
                    'symbol': symbol.upper(),
                    'strategy_type': strategy_type,
                    'timeframe': timeframe,
                    'backtest_days': days,
                    'data_points': len(historical_data)
                }
            },
            'message': f"Backtest completed for {symbol} using {strategy_type} strategy"
        }
        
    except Exception as e:
        logger.error(f"Strategy backtest failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(e)}")


@router.get("/available-strategies",
           summary="获取可用策略列表",
           response_model=Dict[str, Any])
async def get_available_strategies():
    """获取系统中可用的策略列表"""
    try:
        strategies = [
            {
                'name': 'supertrend',
                'display_name': 'SuperTrend多周期策略',
                'description': '基于SuperTrend指标的多时间周期趋势分析策略',
                'parameters': {
                    'period': {'type': 'int', 'default': 10, 'min': 5, 'max': 50},
                    'multiplier': {'type': 'float', 'default': 3.0, 'min': 1.0, 'max': 10.0},
                    'timeframes': {'type': 'list', 'default': ['1d', '4h', '1h', '15m']}
                },
                'supported_timeframes': ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'],
                'features': ['single_timeframe', 'multi_timeframe', 'backtest']
            }
        ]
        
        return {
            'success': True,
            'data': {
                'strategies': strategies,
                'total_strategies': len(strategies),
                'default_config': settings.strategy_config
            },
            'message': "Available strategies retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to get available strategies: {e}")
        raise HTTPException(status_code=500, detail="Failed to get strategies list")