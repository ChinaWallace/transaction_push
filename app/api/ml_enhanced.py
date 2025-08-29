# -*- coding: utf-8 -*-
"""
机器学习增强API
ML Enhanced API endpoints for prediction, anomaly detection and optimization
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.ml_weight_config import get_ml_weight_config
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal, AnomalyType
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()


class StrategyOverviewResponse(BaseResponse):
    """策略概览响应模型"""
    symbol: str
    traditional_signals: Dict[str, Any]  # 传统技术指标
    ml_prediction: Dict[str, Any]        # ML预测
    anomaly_detection: List[Dict[str, Any]]  # 异常检测
    combined_recommendation: str         # 综合建议
    confidence_score: float             # 综合置信度


class PredictionRequest(BaseModel):
    """预测请求模型"""
    symbol: str = Field(..., description="交易对")
    include_features: bool = Field(default=False, description="是否包含特征重要性")


class PredictionResponse(BaseResponse):
    """预测响应模型"""
    symbol: str
    signal: str
    confidence: float
    probability_distribution: Dict[str, float]
    features_importance: Optional[Dict[str, float]] = None
    model_accuracy: float
    timestamp: datetime


class AnomalyDetectionRequest(BaseModel):
    """异常检测请求模型"""
    symbol: str = Field(..., description="交易对")
    detection_types: Optional[List[str]] = Field(default=None, description="检测类型列表")


class AnomalyResponse(BaseModel):
    """异常响应模型"""
    symbol: str
    anomaly_type: str
    severity: float
    description: str
    affected_features: List[str]
    recommendation: str
    timestamp: datetime


class AnomalyDetectionResponse(BaseResponse):
    """异常检测响应模型"""
    symbol: str
    anomalies: List[AnomalyResponse]
    total_anomalies: int
    timestamp: datetime


class OptimizationRequest(BaseModel):
    """参数优化请求模型"""
    symbol: str = Field(..., description="交易对")
    optimization_type: str = Field(default="all", description="优化类型: all, supertrend, volume")


class OptimizationResponse(BaseResponse):
    """参数优化响应模型"""
    symbol: str
    optimized_parameters: Dict[str, Any]
    performance_improvement: Optional[float] = None
    timestamp: datetime


class BatchAnalysisRequest(BaseModel):
    """批量分析请求模型"""
    symbols: List[str] = Field(..., description="交易对列表")
    include_prediction: bool = Field(default=True, description="是否包含预测")
    include_anomaly_detection: bool = Field(default=True, description="是否包含异常检测")
    include_optimization: bool = Field(default=False, description="是否包含参数优化")


class BatchAnalysisResponse(BaseResponse):
    """批量分析响应模型"""
    results: Dict[str, Dict[str, Any]]
    summary: Dict[str, Any]
    timestamp: datetime


# 创建ML服务实例
ml_service = MLEnhancedService()


@router.post("/predict", response_model=PredictionResponse)
async def predict_signal(request: PredictionRequest) -> PredictionResponse:
    """
    ML信号预测
    
    使用机器学习模型预测交易信号
    """
    try:
        # 执行预测
        prediction = await ml_service.predict_signal(request.symbol)
        
        # 构建响应
        response_data = {
            "status": "success",
            "message": f"预测完成: {prediction.signal.value}",
            "symbol": prediction.symbol,
            "signal": prediction.signal.value,
            "confidence": prediction.confidence,
            "probability_distribution": prediction.probability_distribution,
            "model_accuracy": prediction.model_accuracy,
            "timestamp": prediction.timestamp
        }
        
        if request.include_features:
            response_data["features_importance"] = prediction.features_importance
        
        return PredictionResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Prediction API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"预测失败: {str(e)}")


@router.post("/anomaly-detection", response_model=AnomalyDetectionResponse)
async def detect_anomalies(request: AnomalyDetectionRequest) -> AnomalyDetectionResponse:
    """
    异常检测
    
    检测市场数据中的异常模式
    """
    try:
        # 执行异常检测
        anomalies = await ml_service.detect_anomalies(request.symbol)
        
        # 过滤检测类型
        if request.detection_types:
            anomalies = [
                anomaly for anomaly in anomalies
                if anomaly.anomaly_type.value in request.detection_types
            ]
        
        # 构建异常响应列表
        anomaly_responses = []
        for anomaly in anomalies:
            anomaly_responses.append(AnomalyResponse(
                symbol=anomaly.symbol,
                anomaly_type=anomaly.anomaly_type.value,
                severity=anomaly.severity,
                description=anomaly.description,
                affected_features=anomaly.affected_features,
                recommendation=anomaly.recommendation,
                timestamp=anomaly.timestamp
            ))
        
        return AnomalyDetectionResponse(
            status="success",
            message=f"检测到 {len(anomaly_responses)} 个异常",
            symbol=request.symbol,
            anomalies=anomaly_responses,
            total_anomalies=len(anomaly_responses),
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Anomaly detection API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"异常检测失败: {str(e)}")


@router.post("/optimize", response_model=OptimizationResponse)
async def optimize_parameters(request: OptimizationRequest) -> OptimizationResponse:
    """
    参数优化
    
    使用机器学习优化策略参数
    """
    try:
        # 执行参数优化
        optimized_params = await ml_service.optimize_parameters(request.symbol)
        
        return OptimizationResponse(
            status="success",
            message="参数优化完成",
            symbol=request.symbol,
            optimized_parameters=optimized_params,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Parameter optimization API failed for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"参数优化失败: {str(e)}")


@router.post("/batch-analysis", response_model=BatchAnalysisResponse)
async def batch_analysis(request: BatchAnalysisRequest) -> BatchAnalysisResponse:
    """
    批量ML分析
    
    对多个交易对进行批量ML分析
    """
    try:
        results = {}
        summary = {
            "total_symbols": len(request.symbols),
            "successful_predictions": 0,
            "total_anomalies": 0,
            "optimized_symbols": 0,
            "signals_distribution": {
                "strong_buy": 0,
                "buy": 0,
                "hold": 0,
                "sell": 0,
                "strong_sell": 0
            }
        }
        
        for symbol in request.symbols:
            symbol_result = {}
            
            try:
                # 预测分析
                if request.include_prediction:
                    prediction = await ml_service.predict_signal(symbol)
                    symbol_result["prediction"] = {
                        "signal": prediction.signal.value,
                        "confidence": prediction.confidence,
                        "model_accuracy": prediction.model_accuracy
                    }
                    summary["successful_predictions"] += 1
                    summary["signals_distribution"][prediction.signal.value] += 1
                
                # 异常检测
                if request.include_anomaly_detection:
                    anomalies = await ml_service.detect_anomalies(symbol)
                    symbol_result["anomalies"] = [
                        {
                            "type": anomaly.anomaly_type.value,
                            "severity": anomaly.severity,
                            "description": anomaly.description
                        }
                        for anomaly in anomalies
                    ]
                    summary["total_anomalies"] += len(anomalies)
                
                # 参数优化
                if request.include_optimization:
                    optimized_params = await ml_service.optimize_parameters(symbol)
                    symbol_result["optimization"] = optimized_params
                    summary["optimized_symbols"] += 1
                
                results[symbol] = symbol_result
                
            except Exception as e:
                logger.error(f"Batch analysis failed for {symbol}: {e}")
                results[symbol] = {"error": str(e)}
        
        return BatchAnalysisResponse(
            status="success",
            message=f"批量分析完成，处理了 {len(request.symbols)} 个交易对",
            results=results,
            summary=summary,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Batch analysis API failed: {e}")
        raise HTTPException(status_code=500, detail=f"批量分析失败: {str(e)}")


@router.get("/model-status/{symbol}")
async def get_model_status(symbol: str) -> Dict[str, Any]:
    """
    获取模型状态
    
    查看指定交易对的ML模型状态
    """
    try:
        # 检查模型是否存在
        model_exists = symbol in ml_service.prediction_models
        scaler_exists = symbol in ml_service.scalers
        
        status = {
            "symbol": symbol,
            "model_loaded": model_exists,
            "scaler_loaded": scaler_exists,
            "model_accuracy": getattr(ml_service.prediction_models.get(symbol), '_accuracy', None),
            "last_updated": None,  # 可以从文件修改时间获取
            "status": "ready" if (model_exists and scaler_exists) else "not_initialized"
        }
        
        return {
            "status": "success",
            "data": status,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Model status check failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"模型状态检查失败: {str(e)}")


@router.post("/initialize-models")
async def initialize_models(background_tasks: BackgroundTasks, 
                          symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    初始化ML模型
    
    为指定的交易对初始化或重新训练ML模型
    """
    try:
        if symbols is None:
            symbols = settings.monitored_symbols
        
        # 在后台任务中初始化模型
        background_tasks.add_task(ml_service.initialize_models, symbols)
        
        return {
            "status": "success",
            "message": f"开始初始化 {len(symbols)} 个交易对的ML模型",
            "symbols": symbols,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Model initialization failed: {e}")
        raise HTTPException(status_code=500, detail=f"模型初始化失败: {str(e)}")


@router.get("/config")
async def get_ml_config() -> Dict[str, Any]:
    """
    获取ML配置
    
    返回当前的机器学习配置参数
    """
    return {
        "status": "success",
        "config": settings.ml_config,
        "monitored_symbols": settings.monitored_symbols,
        "timestamp": datetime.now()
    }


@router.get("/strategy-overview/{symbol}", response_model=StrategyOverviewResponse)
async def get_strategy_overview(symbol: str) -> StrategyOverviewResponse:
    """
    综合策略概览
    
    结合传统技术指标和机器学习分析，提供综合投资建议
    """
    try:
        # 导入其他服务
        from app.services.trend_analysis_service import TrendAnalysisService
        from app.services.binance_service import BinanceService
        
        trend_service = TrendAnalysisService()
        binance_service = BinanceService()
        
        # 获取传统技术指标分析
        traditional_analysis = await trend_service.analyze_symbol(symbol)
        
        # 获取ML预测
        ml_prediction = await ml_service.predict_signal(symbol)
        
        # 获取异常检测
        anomalies = await ml_service.detect_anomalies(symbol)
        
        # 获取当前价格
        current_price = await binance_service.get_current_price(symbol)
        
        # 构建传统信号数据
        traditional_signals = {
            "supertrend_signals": traditional_analysis.get("supertrend_analysis", {}),
            "current_price": float(current_price) if current_price else None,
            "trend_strength": traditional_analysis.get("trend_strength", "unknown"),
            "support_resistance": traditional_analysis.get("support_resistance", {}),
            "volume_analysis": traditional_analysis.get("volume_analysis", {})
        }
        
        # 构建ML预测数据
        ml_data = {
            "signal": ml_prediction.signal.value,
            "confidence": ml_prediction.confidence,
            "probability_distribution": ml_prediction.probability_distribution,
            "model_accuracy": ml_prediction.model_accuracy,
            "features_importance": ml_prediction.features_importance or {}
        }
        
        # 构建异常检测数据
        anomaly_data = []
        for anomaly in anomalies:
            anomaly_data.append({
                "type": anomaly.anomaly_type.value,
                "severity": anomaly.severity,
                "description": anomaly.description,
                "recommendation": anomaly.recommendation,
                "timestamp": anomaly.timestamp
            })
        
        # 综合分析生成建议
        combined_recommendation, confidence_score = _generate_combined_recommendation(
            traditional_analysis, ml_prediction, anomalies
        )
        
        return StrategyOverviewResponse(
            status="success",
            symbol=symbol,
            traditional_signals=traditional_signals,
            ml_prediction=ml_data,
            anomaly_detection=anomaly_data,
            combined_recommendation=combined_recommendation,
            confidence_score=confidence_score,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Strategy overview API failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"策略分析失败: {str(e)}")


def _generate_combined_recommendation(traditional_analysis: Dict, ml_prediction, anomalies: List) -> tuple:
    """
    生成综合投资建议
    
    Args:
        traditional_analysis: 传统技术分析结果
        ml_prediction: ML预测结果
        anomalies: 异常检测结果
        
    Returns:
        (建议文本, 置信度分数)
    """
    try:
        # 使用动态权重配置
        ml_config = get_ml_weight_config()
        traditional_weight = ml_config.get_traditional_weight_for_api()
        ml_weight = ml_config.get_ml_weight_for_api()
        
        logger.debug(f"🔧 动态权重: 传统={traditional_weight}, ML={ml_weight}, 模式={ml_config.current_mode.value}")
        
        # 获取传统信号强度
        traditional_signal = traditional_analysis.get("overall_signal", "hold")
        traditional_strength = traditional_analysis.get("signal_strength", 0.5)
        
        # 获取ML信号强度
        ml_signal = ml_prediction.signal.value
        ml_confidence = ml_prediction.confidence
        
        # 信号映射到数值 (-2到2)
        signal_mapping = {
            "strong_sell": -2,
            "sell": -1,
            "hold": 0,
            "buy": 1,
            "strong_buy": 2
        }
        
        traditional_score = signal_mapping.get(traditional_signal, 0) * traditional_strength
        ml_score = signal_mapping.get(ml_signal, 0) * ml_confidence
        
        # 计算综合分数
        combined_score = (traditional_score * traditional_weight + ml_score * ml_weight)
        
        # 异常检测调整
        high_severity_anomalies = [a for a in anomalies if a.severity > 0.7]
        if high_severity_anomalies:
            combined_score *= 0.7  # 降低置信度
        
        # 生成建议
        if combined_score >= 1.5:
            recommendation = "🚀 强烈建议买入"
            confidence = min(0.9, abs(combined_score) / 2)
        elif combined_score >= 0.5:
            recommendation = "📈 建议买入"
            confidence = min(0.8, abs(combined_score) / 2)
        elif combined_score <= -1.5:
            recommendation = "💥 强烈建议卖出"
            confidence = min(0.9, abs(combined_score) / 2)
        elif combined_score <= -0.5:
            recommendation = "📉 建议卖出"
            confidence = min(0.8, abs(combined_score) / 2)
        else:
            recommendation = "⏸️ 建议持有观望"
            confidence = 0.6
        
        # 添加详细说明
        details = []
        details.append(f"传统技术指标: {traditional_signal} (强度: {traditional_strength:.1%})")
        details.append(f"ML预测信号: {ml_signal} (置信度: {ml_confidence:.1%})")
        
        if high_severity_anomalies:
            details.append(f"⚠️ 检测到{len(high_severity_anomalies)}个高严重度异常，建议谨慎操作")
        
        recommendation += "\n\n" + "\n".join(details)
        
        return recommendation, confidence
        
    except Exception as e:
        logger.error(f"Failed to generate combined recommendation: {e}")
        return "⚠️ 分析失败，请稍后重试", 0.0


@router.get("/model-status", response_model=BaseResponse)
async def get_model_status() -> BaseResponse:
    """
    获取ML模型状态
    
    返回所有交易对的模型训练状态和性能指标
    """
    try:
        model_status = {}
        
        for symbol in settings.monitored_symbols:
            model = ml_service.prediction_models.get(symbol)
            scaler = ml_service.scalers.get(symbol)
            
            if model and scaler:
                accuracy = getattr(model, '_accuracy', 0.0)
                model_status[symbol] = {
                    "model_loaded": True,
                    "accuracy": accuracy,
                    "status": "good" if accuracy >= 0.6 else "needs_improvement" if accuracy >= 0.5 else "poor",
                    "last_trained": "unknown"  # 可以从文件修改时间获取
                }
            else:
                model_status[symbol] = {
                    "model_loaded": False,
                    "accuracy": 0.0,
                    "status": "not_trained",
                    "last_trained": "never"
                }
        
        return BaseResponse(
            status="success",
            data={
                "models": model_status,
                "total_models": len(model_status),
                "trained_models": sum(1 for s in model_status.values() if s["model_loaded"]),
                "good_performance": sum(1 for s in model_status.values() if s["status"] == "good")
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Model status API failed: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型状态失败: {str(e)}")