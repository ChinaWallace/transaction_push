# -*- coding: utf-8 -*-
"""
统一数据API
Unified Data API - 提供统一的数据访问接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
import pandas as pd

from app.core.logging import get_logger
from app.services.unified_data_service import (
    get_unified_data_service, 
    DataRequest, 
    DataSource,
    get_market_data
)
from app.services.data_sharing_service import (
    get_data_sharing_service,
    get_analysis_data,
    get_batch_funding_rates,
    get_technical_indicators
)
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/unified-data", tags=["统一数据服务"])


@router.get("/market-data/{symbol}")
async def get_market_data_endpoint(
    symbol: str,
    timeframe: str = Query("1h", description="时间周期"),
    limit: int = Query(500, description="数据条数"),
    source: str = Query("auto", description="数据源 (auto/binance/okx)"),
    use_cache: bool = Query(True, description="是否使用缓存")
):
    """
    获取市场数据
    
    支持多数据源自动切换和智能缓存
    """
    try:
        # 转换数据源参数
        source_mapping = {
            "auto": DataSource.AUTO,
            "binance": DataSource.BINANCE,
            "okx": DataSource.OKX
        }
        
        data_source = source_mapping.get(source.lower(), DataSource.AUTO)
        
        # 获取数据
        result = await get_market_data(symbol, timeframe, limit, data_source)
        
        # 转换DataFrame为字典格式
        if not result.data.empty:
            data_dict = result.data.reset_index().to_dict('records')
        else:
            data_dict = []
        
        return BaseResponse(
            success=True,
            message=f"成功获取 {symbol} {timeframe} 数据",
            data={
                "symbol": symbol,
                "timeframe": timeframe,
                "source": result.source,
                "cached": result.cached,
                "timestamp": result.timestamp.isoformat(),
                "count": len(data_dict),
                "data": data_dict
            }
        )
        
    except Exception as e:
        logger.error(f"获取市场数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场数据失败: {str(e)}")


@router.get("/analysis-data/{symbol}")
async def get_analysis_data_endpoint(
    symbol: str,
    timeframes: List[str] = Query(["1h", "4h"], description="时间周期列表")
):
    """
    获取分析数据
    
    优化的多周期数据获取，支持数据共享
    """
    try:
        data = await get_analysis_data(symbol, timeframes)
        
        # 转换数据格式
        result_data = {}
        for timeframe, df in data.items():
            if not df.empty:
                result_data[timeframe] = {
                    "count": len(df),
                    "latest": df.tail(1).reset_index().to_dict('records')[0] if len(df) > 0 else None,
                    "data": df.reset_index().to_dict('records')
                }
            else:
                result_data[timeframe] = {"count": 0, "latest": None, "data": []}
        
        return BaseResponse(
            success=True,
            message=f"成功获取 {symbol} 分析数据",
            data={
                "symbol": symbol,
                "timeframes": timeframes,
                "result": result_data
            }
        )
        
    except Exception as e:
        logger.error(f"获取分析数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取分析数据失败: {str(e)}")


@router.get("/funding-rates")
async def get_funding_rates_endpoint(
    symbols: List[str] = Query(..., description="币种列表")
):
    """
    批量获取资金费率
    
    支持数据共享和缓存优化
    """
    try:
        rates = await get_batch_funding_rates(symbols)
        
        # 格式化数据
        formatted_rates = []
        for symbol, rate_data in rates.items():
            if rate_data:
                formatted_rates.append({
                    "symbol": symbol,
                    "funding_rate": rate_data.get("funding_rate", 0),
                    "funding_rate_percent": f"{rate_data.get('funding_rate', 0) * 100:.4f}%",
                    "next_funding_time": rate_data.get("next_funding_time"),
                    "source": rate_data.get("source", "unknown"),
                    "timestamp": rate_data.get("timestamp").isoformat() if rate_data.get("timestamp") else None
                })
        
        # 统计信息
        negative_rates = [r for r in formatted_rates if r["funding_rate"] < 0]
        positive_rates = [r for r in formatted_rates if r["funding_rate"] > 0]
        
        return BaseResponse(
            success=True,
            message=f"成功获取 {len(formatted_rates)} 个币种的费率数据",
            data={
                "total_count": len(formatted_rates),
                "negative_count": len(negative_rates),
                "positive_count": len(positive_rates),
                "rates": formatted_rates,
                "summary": {
                    "negative_rates": negative_rates[:5],  # 前5个负费率
                    "highest_positive": sorted(positive_rates, key=lambda x: x["funding_rate"], reverse=True)[:3]
                }
            }
        )
        
    except Exception as e:
        logger.error(f"获取费率数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取费率数据失败: {str(e)}")


@router.get("/technical-indicators/{symbol}")
async def get_technical_indicators_endpoint(
    symbol: str,
    timeframe: str = Query("1h", description="时间周期")
):
    """
    获取技术指标
    
    支持指标共享，避免重复计算
    """
    try:
        indicators = await get_technical_indicators(symbol, timeframe)
        
        if not indicators:
            return BaseResponse(
                success=False,
                message=f"无法获取 {symbol} {timeframe} 的技术指标",
                data={}
            )
        
        # 格式化指标数据
        formatted_indicators = {}
        for key, value in indicators.items():
            if value is not None:
                if isinstance(value, float):
                    formatted_indicators[key] = round(value, 6)
                else:
                    formatted_indicators[key] = value
        
        # 计算一些附加信息
        analysis = {}
        if 'current_price' in indicators and 'ma_20' in indicators:
            if indicators['ma_20'] is not None:
                ma_diff = ((indicators['current_price'] - indicators['ma_20']) / indicators['ma_20']) * 100
                analysis['ma20_position'] = f"{'上方' if ma_diff > 0 else '下方'} {abs(ma_diff):.2f}%"
        
        if 'volume_ratio' in indicators:
            volume_ratio = indicators['volume_ratio']
            if volume_ratio > 2:
                analysis['volume_status'] = "成交量异常放大"
            elif volume_ratio > 1.5:
                analysis['volume_status'] = "成交量活跃"
            else:
                analysis['volume_status'] = "成交量正常"
        
        return BaseResponse(
            success=True,
            message=f"成功获取 {symbol} {timeframe} 技术指标",
            data={
                "symbol": symbol,
                "timeframe": timeframe,
                "indicators": formatted_indicators,
                "analysis": analysis
            }
        )
        
    except Exception as e:
        logger.error(f"获取技术指标失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取技术指标失败: {str(e)}")


@router.get("/hot-symbols")
async def get_hot_symbols_data_endpoint(
    count: int = Query(10, description="返回数量")
):
    """
    获取热门币种数据
    
    批量获取多个热门币种的多周期数据
    """
    try:
        data_service = await get_data_sharing_service()
        hot_data = await data_service.get_top_symbols_data(count)
        
        # 格式化数据
        result = []
        for symbol, timeframe_data in hot_data.items():
            symbol_info = {"symbol": symbol, "timeframes": {}}
            
            for timeframe, df in timeframe_data.items():
                if not df.empty:
                    latest = df.tail(1).iloc[0]
                    symbol_info["timeframes"][timeframe] = {
                        "current_price": latest['close'],
                        "high_24h": df['high'].max(),
                        "low_24h": df['low'].min(),
                        "volume": latest['volume'],
                        "data_points": len(df)
                    }
                else:
                    symbol_info["timeframes"][timeframe] = None
            
            result.append(symbol_info)
        
        return BaseResponse(
            success=True,
            message=f"成功获取 {len(result)} 个热门币种数据",
            data={
                "count": len(result),
                "symbols": result
            }
        )
        
    except Exception as e:
        logger.error(f"获取热门币种数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取热门币种数据失败: {str(e)}")


@router.get("/service-stats")
async def get_service_stats_endpoint():
    """
    获取统一数据服务统计信息
    
    显示缓存命中率、数据源状态等
    """
    try:
        # 获取统一数据服务统计
        unified_service = await get_unified_data_service()
        unified_stats = unified_service.get_stats()
        
        # 获取数据共享服务统计
        data_service = await get_data_sharing_service()
        sharing_stats = await data_service.get_service_stats()
        
        # 健康检查
        health_status = await unified_service.health_check()
        
        return BaseResponse(
            success=True,
            message="成功获取服务统计信息",
            data={
                "unified_service": unified_stats,
                "data_sharing": sharing_stats.get("data_sharing", {}),
                "health_status": health_status,
                "timestamp": pd.Timestamp.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"获取服务统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取服务统计失败: {str(e)}")


@router.post("/cache/clear")
async def clear_cache_endpoint():
    """
    清理缓存
    
    清理所有缓存数据，强制重新获取
    """
    try:
        # 清理统一数据服务缓存
        unified_service = await get_unified_data_service()
        await unified_service.cache.invalidate()
        
        # 清理数据共享服务缓存
        data_service = await get_data_sharing_service()
        await data_service.cleanup_cache()
        
        return BaseResponse(
            success=True,
            message="缓存清理完成",
            data={"cleared_at": pd.Timestamp.now().isoformat()}
        )
        
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理缓存失败: {str(e)}")


@router.get("/health")
async def health_check_endpoint():
    """
    健康检查
    
    检查所有数据源和服务的健康状态
    """
    try:
        unified_service = await get_unified_data_service()
        health_status = await unified_service.health_check()
        
        return BaseResponse(
            success=health_status["overall"] in ["healthy", "degraded"],
            message=f"服务状态: {health_status['overall']}",
            data=health_status
        )
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")
