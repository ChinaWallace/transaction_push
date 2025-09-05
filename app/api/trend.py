# -*- coding: utf-8 -*-
"""
趋势分析API路由
Trend analysis API routes
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any

from app.services.analysis.trend_analysis_service import TrendAnalysisService
from app.core.logging import get_logger
from app.schemas.trend import TrendAnalysisRequest, TrendAnalysisResponse, BatchAnalysisRequest

logger = get_logger(__name__)
router = APIRouter()

# 创建趋势分析服务实例
trend_service = TrendAnalysisService()


@router.get("/analyze/{symbol}", 
           summary="单个交易对趋势分析",
           response_model=TrendAnalysisResponse)
async def analyze_symbol_trend(symbol: str):
    """
    分析单个交易对的多周期趋势信号
    
    Args:
        symbol: 交易对名称，如 BTCUSDT
        
    Returns:
        趋势分析结果
    """
    try:
        logger.info(f"Starting trend analysis for {symbol}")
        
        # 验证交易对格式
        if not symbol or not symbol.endswith('USDT'):
            raise HTTPException(status_code=400, detail="Invalid symbol format")
        
        # 执行趋势分析
        result = await trend_service.analyze_multi_timeframe_signal(symbol.upper())
        
        return TrendAnalysisResponse(
            success=True,
            data=result,
            message=f"Trend analysis completed for {symbol}"
        )
        
    except Exception as e:
        logger.error(f"Trend analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/batch-analyze",
            summary="批量趋势分析", 
            response_model=Dict[str, Any])
async def batch_analyze_trends(request: BatchAnalysisRequest):
    """
    批量分析多个交易对的趋势信号
    
    Args:
        request: 批量分析请求
        
    Returns:
        批量分析结果
    """
    try:
        symbols = [s.upper() for s in request.symbols]
        logger.info(f"Starting batch trend analysis for {len(symbols)} symbols")
        
        # 验证交易对数量
        if len(symbols) > 20:
            raise HTTPException(status_code=400, detail="Too many symbols (max 20)")
        
        # 执行批量分析
        results = await trend_service.analyze_batch_symbols(symbols)
        
        # 统计结果
        success_count = sum(1 for r in results.values() if 'error' not in r)
        error_count = len(results) - success_count
        
        return {
            "success": True,
            "data": results,
            "statistics": {
                "total": len(symbols),
                "success": success_count,
                "error": error_count
            },
            "message": f"Batch analysis completed: {success_count}/{len(symbols)} successful"
        }
        
    except Exception as e:
        logger.error(f"Batch trend analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch analysis failed: {str(e)}")


@router.get("/historical/{symbol}",
           summary="历史信号分析",
           response_model=Dict[str, Any])
async def analyze_historical_signals(
    symbol: str,
    days: int = Query(default=7, ge=1, le=30, description="回溯天数(1-30)")
):
    """
    分析交易对的历史信号变化
    
    Args:
        symbol: 交易对名称
        days: 回溯天数
        
    Returns:
        历史信号分析结果
    """
    try:
        logger.info(f"Starting historical analysis for {symbol}, {days} days")
        
        # 验证交易对格式
        if not symbol or not symbol.endswith('USDT'):
            raise HTTPException(status_code=400, detail="Invalid symbol format")
        
        # 执行历史分析
        historical_signals = await trend_service.analyze_historical_signals(
            symbol.upper(), days
        )
        
        return {
            "success": True,
            "data": {
                "symbol": symbol.upper(),
                "period_days": days,
                "signal_changes": historical_signals,
                "total_changes": len(historical_signals)
            },
            "message": f"Historical analysis completed for {symbol}"
        }
        
    except Exception as e:
        logger.error(f"Historical analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Historical analysis failed: {str(e)}")


@router.post("/analyze-with-data/{symbol}",
            summary="使用自定义数据分析趋势",
            response_model=TrendAnalysisResponse)
async def analyze_with_custom_data(
    symbol: str,
    request: TrendAnalysisRequest
):
    """
    使用自定义K线数据分析趋势信号
    
    Args:
        symbol: 交易对名称
        request: 包含自定义K线数据的请求
        
    Returns:
        趋势分析结果
    """
    try:
        logger.info(f"Starting custom data analysis for {symbol}")
        
        # 验证数据
        if not request.timeframe_data:
            raise HTTPException(status_code=400, detail="No timeframe data provided")
        
        # 执行分析
        result = await trend_service.analyze_multi_timeframe_signal(
            symbol.upper(), 
            request.timeframe_data
        )
        
        return TrendAnalysisResponse(
            success=True,
            data=result,
            message=f"Custom data analysis completed for {symbol}"
        )
        
    except Exception as e:
        logger.error(f"Custom data analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/signal-combinations",
           summary="获取信号组合定义",
           response_model=Dict[str, Any])
async def get_signal_combinations():
    """
    获取所有信号组合的定义
    
    Returns:
        信号组合定义列表
    """
    try:
        combinations = {}
        for combo_id, combo in trend_service.SIGNAL_COMBINATIONS.items():
            combinations[combo_id] = {
                "id": combo.combination_id,
                "name": combo.name,
                "strategy": combo.strategy,
                "level": combo.level.value,
                "description": combo.description
            }
        
        return {
            "success": True,
            "data": combinations,
            "message": "Signal combinations retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to get signal combinations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get signal combinations")


@router.get("/format-notification/{symbol}",
           summary="格式化信号通知",
           response_model=Dict[str, Any])
async def format_signal_notification(symbol: str):
    """
    格式化交易对的信号通知消息
    
    Args:
        symbol: 交易对名称
        
    Returns:
        格式化的通知消息
    """
    try:
        # 先分析信号
        signal_data = await trend_service.analyze_multi_timeframe_signal(symbol.upper())
        
        # 格式化通知消息
        notification_message = trend_service.format_signal_notification(signal_data)
        
        return {
            "success": True,
            "data": {
                "symbol": symbol.upper(),
                "notification_message": notification_message,
                "should_send": signal_data.get('should_notify', False),
                "signal_level": signal_data.get('signal_level', 'watch')
            },
            "message": "Notification formatted successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to format notification for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Notification formatting failed: {str(e)}")
