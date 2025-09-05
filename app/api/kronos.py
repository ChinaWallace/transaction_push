# -*- coding: utf-8 -*-
"""
Kronos预测API路由
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from fastapi.responses import JSONResponse

from app.schemas.kronos import (
    KronosBatchPredictionRequest,
    KronosPredictionResponse,
    KronosBatchPredictionResponse,
    KronosConfigResponse,
    KronosHealthResponse,
    PredictionDataPoint
)
from app.services.ml.kronos_prediction_service import get_kronos_service, KronosPredictionService
from app.services.exchanges.okx.okx_service import OKXService
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health", response_model=KronosHealthResponse)
async def get_kronos_health(
    service: KronosPredictionService = Depends(get_kronos_service)
) -> KronosHealthResponse:
    """获取Kronos服务健康状态"""
    try:
        model_loaded = service.predictor is not None
        device = service.predictor.device if model_loaded else None
        model_name = service.predictor.model_name if model_loaded else None
        cache_size = len(service.prediction_cache)
        
        # 获取最后预测时间
        last_prediction_time = None
        if service.last_update:
            last_prediction_time = max(service.last_update.values())
        
        status = "healthy" if model_loaded else "model_not_loaded"
        
        return KronosHealthResponse(
            status=status,
            model_loaded=model_loaded,
            device=device,
            model_name=model_name,
            cache_size=cache_size,
            last_prediction_time=last_prediction_time
        )
        
    except Exception as e:
        logger.error(f"获取Kronos健康状态失败: {e}")
        return KronosHealthResponse(
            status="error",
            model_loaded=False
        )


@router.get("/config", response_model=KronosConfigResponse)
async def get_kronos_config(
    service: KronosPredictionService = Depends(get_kronos_service)
) -> KronosConfigResponse:
    """获取Kronos配置信息"""
    try:
        config_data = service.settings.kronos_config.copy()
        # 移除敏感信息
        if 'api_key' in config_data:
            config_data['api_key'] = "***"
        
        return KronosConfigResponse(data=config_data)
        
    except Exception as e:
        logger.error(f"获取Kronos配置失败: {e}")
        raise HTTPException(status_code=500, detail="获取配置失败")


@router.post("/predict/{symbol}", response_model=KronosPredictionResponse)
async def predict_symbol(
    symbol: str = Path(..., description="交易对符号"),
    lookback_periods: int = Query(default=200, description="历史数据回看期数"),
    prediction_horizon: int = Query(default=24, description="预测时间范围（小时）"),
    force_update: bool = Query(default=False, description="是否强制更新预测"),
    service: KronosPredictionService = Depends(get_kronos_service)
) -> KronosPredictionResponse:
    """生成单个交易对的Kronos预测"""
    try:
        # 获取历史数据
        async with OKXService() as okx_service:
            historical_data = await okx_service.get_kline_data(
                symbol=symbol,
                timeframe='1h',
                limit=lookback_periods + 50  # 多获取一些数据以确保足够
            )
        
        if historical_data is None or len(historical_data) < lookback_periods:
            raise HTTPException(
                status_code=400,
                detail=f"历史数据不足，需要至少{lookback_periods}条数据"
            )
        
        # 生成预测
        prediction = await service.get_prediction(
            symbol=symbol,
            historical_data=historical_data,
            force_update=force_update
        )
        
        if prediction is None:
            raise HTTPException(status_code=500, detail="预测生成失败")
        
        # 转换预测数据格式
        prediction_points = []
        for idx, row in prediction.predictions.iterrows():
            point = PredictionDataPoint(
                timestamp=idx,
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume'])
            )
            prediction_points.append(point)
        
        # 构建响应
        result = {
            "symbol": prediction.symbol,
            "timestamp": prediction.timestamp,
            "predictions": prediction_points,
            "confidence": prediction.confidence,
            "signal": prediction.signal,
            "price_change_pct": prediction.price_change_pct,
            "volatility": prediction.volatility,
            "trend_direction": prediction.trend_direction
        }
        
        return KronosPredictionResponse(
            status="success",
            message=f"{symbol}预测生成成功",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成{symbol}预测失败: {e}")
        raise HTTPException(status_code=500, detail=f"预测生成失败: {str(e)}")


@router.post("/predict/batch", response_model=KronosBatchPredictionResponse)
async def predict_batch(
    request: KronosBatchPredictionRequest,
    service: KronosPredictionService = Depends(get_kronos_service)
) -> KronosBatchPredictionResponse:
    """批量生成多个交易对的Kronos预测"""
    try:
        async with OKXService() as okx_service:
            symbols_data = {}
            
            # 获取所有交易对的历史数据
            for symbol in request.symbols:
                try:
                    historical_data = await okx_service.get_kline_data(
                        symbol=symbol,
                        timeframe='1h',
                        limit=request.lookback_periods + 50
                    )
                    
                    if historical_data is not None and len(historical_data) >= request.lookback_periods:
                        symbols_data[symbol] = historical_data
                    else:
                        logger.warning(f"{symbol}历史数据不足")
                        
                except Exception as e:
                    logger.error(f"获取{symbol}历史数据失败: {e}")
        
        if not symbols_data:
            raise HTTPException(status_code=400, detail="没有可用的历史数据")
        
        # 批量生成预测
        predictions = await service.get_batch_predictions(
            symbols_data=symbols_data,
            force_update=request.force_update
        )
        
        # 转换结果格式
        result_data = {}
        successful_count = 0
        failed_count = 0
        
        for symbol, prediction in predictions.items():
            if prediction is not None:
                # 转换预测数据格式
                prediction_points = []
                for idx, row in prediction.predictions.iterrows():
                    point = PredictionDataPoint(
                        timestamp=idx,
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=float(row['volume'])
                    )
                    prediction_points.append(point)
                
                result_data[symbol] = {
                    "symbol": prediction.symbol,
                    "timestamp": prediction.timestamp,
                    "predictions": prediction_points,
                    "confidence": prediction.confidence,
                    "signal": prediction.signal,
                    "price_change_pct": prediction.price_change_pct,
                    "volatility": prediction.volatility,
                    "trend_direction": prediction.trend_direction
                }
                successful_count += 1
            else:
                result_data[symbol] = None
                failed_count += 1
        
        return KronosBatchPredictionResponse(
            status="success",
            message=f"批量预测完成，成功{successful_count}个，失败{failed_count}个",
            data=result_data,
            successful_count=successful_count,
            failed_count=failed_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量预测失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量预测失败: {str(e)}")


@router.get("/prediction/{symbol}", response_model=KronosPredictionResponse)
async def get_cached_prediction(
    symbol: str = Path(..., description="交易对符号"),
    service: KronosPredictionService = Depends(get_kronos_service)
) -> KronosPredictionResponse:
    """获取缓存的预测结果"""
    try:
        prediction = service.get_cached_prediction(symbol)
        
        if prediction is None:
            raise HTTPException(
                status_code=404,
                detail=f"未找到{symbol}的缓存预测，请先生成预测"
            )
        
        # 转换预测数据格式
        prediction_points = []
        for idx, row in prediction.predictions.iterrows():
            point = PredictionDataPoint(
                timestamp=idx,
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume'])
            )
            prediction_points.append(point)
        
        result = {
            "symbol": prediction.symbol,
            "timestamp": prediction.timestamp,
            "predictions": prediction_points,
            "confidence": prediction.confidence,
            "signal": prediction.signal,
            "price_change_pct": prediction.price_change_pct,
            "volatility": prediction.volatility,
            "trend_direction": prediction.trend_direction
        }
        
        return KronosPredictionResponse(
            status="success",
            message=f"获取{symbol}缓存预测成功",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{symbol}缓存预测失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取缓存预测失败: {str(e)}")


@router.delete("/cache/{symbol}")
async def clear_prediction_cache(
    symbol: str = Path(..., description="交易对符号"),
    service: KronosPredictionService = Depends(get_kronos_service)
) -> JSONResponse:
    """清除指定交易对的预测缓存"""
    try:
        service.clear_cache(symbol)
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"已清除{symbol}的预测缓存",
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"清除{symbol}预测缓存失败: {e}")
        raise HTTPException(status_code=500, detail="清除缓存失败")


@router.delete("/cache")
async def clear_all_prediction_cache(
    service: KronosPredictionService = Depends(get_kronos_service)
) -> JSONResponse:
    """清除所有预测缓存"""
    try:
        service.clear_cache()
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "已清除所有预测缓存",
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"清除所有预测缓存失败: {e}")
        raise HTTPException(status_code=500, detail="清除缓存失败")