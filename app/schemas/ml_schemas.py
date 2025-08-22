# -*- coding: utf-8 -*-
"""
机器学习相关Schema定义
ML-related Pydantic schemas for API requests and responses
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
from enum import Enum

from app.schemas.base import BaseResponse


class PredictionSignalEnum(str, Enum):
    """预测信号枚举"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class AnomalyTypeEnum(str, Enum):
    """异常类型枚举"""
    PRICE_ANOMALY = "price_anomaly"
    VOLUME_ANOMALY = "volume_anomaly"
    PATTERN_ANOMALY = "pattern_anomaly"
    MARKET_ANOMALY = "market_anomaly"


class ModelTypeEnum(str, Enum):
    """模型类型枚举"""
    RANDOM_FOREST = "random_forest"
    GRADIENT_BOOSTING = "gradient_boosting"
    SVM = "svm"


class OptimizationTypeEnum(str, Enum):
    """优化类型枚举"""
    ALL = "all"
    SUPERTREND = "supertrend"
    VOLUME = "volume"
    FUNDING_RATE = "funding_rate"


# ============================================================================
# 预测相关Schema
# ============================================================================

class PredictionRequest(BaseModel):
    """预测请求Schema"""
    symbol: str = Field(..., description="交易对", example="BTCUSDT")
    include_features: bool = Field(default=False, description="是否包含特征重要性")
    model_type: Optional[ModelTypeEnum] = Field(default=None, description="指定模型类型")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        if not v or len(v) < 3:
            raise ValueError('交易对格式无效')
        return v.upper()


class ProbabilityDistribution(BaseModel):
    """概率分布Schema"""
    strong_sell: float = Field(..., ge=0, le=1, description="强烈卖出概率")
    sell: float = Field(..., ge=0, le=1, description="卖出概率")
    hold: float = Field(..., ge=0, le=1, description="持有概率")
    buy: float = Field(..., ge=0, le=1, description="买入概率")
    strong_buy: float = Field(..., ge=0, le=1, description="强烈买入概率")


class PredictionResult(BaseModel):
    """预测结果Schema"""
    symbol: str = Field(..., description="交易对")
    signal: PredictionSignalEnum = Field(..., description="预测信号")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    probability_distribution: ProbabilityDistribution = Field(..., description="概率分布")
    model_accuracy: float = Field(..., ge=0, le=1, description="模型准确率")
    features_importance: Optional[Dict[str, float]] = Field(default=None, description="特征重要性")
    prediction_timestamp: datetime = Field(..., description="预测时间")


class PredictionResponse(BaseResponse):
    """预测响应Schema"""
    data: PredictionResult


class BatchPredictionRequest(BaseModel):
    """批量预测请求Schema"""
    symbols: List[str] = Field(..., min_items=1, max_items=20, description="交易对列表")
    include_features: bool = Field(default=False, description="是否包含特征重要性")
    
    @validator('symbols')
    def validate_symbols(cls, v):
        return [symbol.upper() for symbol in v]


class BatchPredictionResponse(BaseResponse):
    """批量预测响应Schema"""
    data: Dict[str, PredictionResult]
    summary: Dict[str, Any]


# ============================================================================
# 异常检测相关Schema
# ============================================================================

class AnomalyDetectionRequest(BaseModel):
    """异常检测请求Schema"""
    symbol: str = Field(..., description="交易对")
    detection_types: Optional[List[AnomalyTypeEnum]] = Field(default=None, description="检测类型列表")
    sensitivity: Optional[float] = Field(default=0.8, ge=0.1, le=1.0, description="检测敏感度")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()


class AnomalyResult(BaseModel):
    """异常结果Schema"""
    symbol: str = Field(..., description="交易对")
    anomaly_type: AnomalyTypeEnum = Field(..., description="异常类型")
    severity: float = Field(..., ge=0, le=1, description="严重程度")
    description: str = Field(..., description="异常描述")
    affected_features: List[str] = Field(..., description="受影响的特征")
    recommendation: str = Field(..., description="建议措施")
    detection_timestamp: datetime = Field(..., description="检测时间")
    anomaly_score: Optional[float] = Field(default=None, description="异常分数")


class AnomalyDetectionResponse(BaseResponse):
    """异常检测响应Schema"""
    data: List[AnomalyResult]
    summary: Dict[str, Any]


# ============================================================================
# 参数优化相关Schema
# ============================================================================

class OptimizationRequest(BaseModel):
    """参数优化请求Schema"""
    symbol: str = Field(..., description="交易对")
    optimization_type: OptimizationTypeEnum = Field(default=OptimizationTypeEnum.ALL, description="优化类型")
    performance_window_days: Optional[int] = Field(default=7, ge=1, le=30, description="性能评估窗口天数")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()


class SuperTrendParams(BaseModel):
    """SuperTrend参数Schema"""
    period: int = Field(..., ge=5, le=50, description="周期")
    multiplier: float = Field(..., ge=1.0, le=10.0, description="倍数")
    performance_score: Optional[float] = Field(default=None, description="性能分数")


class VolumeParams(BaseModel):
    """成交量参数Schema"""
    threshold_multiplier: float = Field(..., ge=1.0, le=10.0, description="阈值倍数")
    base_volume: Optional[float] = Field(default=None, description="基础成交量")
    volume_std: Optional[float] = Field(default=None, description="成交量标准差")


class OptimizationResult(BaseModel):
    """优化结果Schema"""
    symbol: str = Field(..., description="交易对")
    optimization_type: str = Field(..., description="优化类型")
    original_parameters: Dict[str, Any] = Field(..., description="原始参数")
    optimized_parameters: Dict[str, Any] = Field(..., description="优化后参数")
    performance_improvement: Optional[float] = Field(default=None, description="性能提升")
    optimization_timestamp: datetime = Field(..., description="优化时间")
    data_period: str = Field(..., description="数据期间")


class OptimizationResponse(BaseResponse):
    """参数优化响应Schema"""
    data: OptimizationResult


# ============================================================================
# 模型管理相关Schema
# ============================================================================

class ModelStatus(BaseModel):
    """模型状态Schema"""
    symbol: str = Field(..., description="交易对")
    model_loaded: bool = Field(..., description="模型是否已加载")
    scaler_loaded: bool = Field(..., description="标准化器是否已加载")
    model_accuracy: Optional[float] = Field(default=None, description="模型准确率")
    last_updated: Optional[datetime] = Field(default=None, description="最后更新时间")
    prediction_count: Optional[int] = Field(default=None, description="预测次数")
    status: str = Field(..., description="状态")


class ModelStatusResponse(BaseResponse):
    """模型状态响应Schema"""
    data: ModelStatus


class ModelInitializationRequest(BaseModel):
    """模型初始化请求Schema"""
    symbols: Optional[List[str]] = Field(default=None, description="交易对列表")
    force_retrain: bool = Field(default=False, description="是否强制重新训练")
    
    @validator('symbols')
    def validate_symbols(cls, v):
        if v is not None:
            return [symbol.upper() for symbol in v]
        return v


class ModelInitializationResponse(BaseResponse):
    """模型初始化响应Schema"""
    symbols: List[str]
    initialization_started: bool


# ============================================================================
# 综合分析相关Schema
# ============================================================================

class MLAnalysisRequest(BaseModel):
    """ML综合分析请求Schema"""
    symbols: List[str] = Field(..., min_items=1, max_items=10, description="交易对列表")
    include_prediction: bool = Field(default=True, description="是否包含预测")
    include_anomaly_detection: bool = Field(default=True, description="是否包含异常检测")
    include_optimization: bool = Field(default=False, description="是否包含参数优化")
    analysis_depth: str = Field(default="standard", description="分析深度: quick, standard, deep")
    
    @validator('symbols')
    def validate_symbols(cls, v):
        return [symbol.upper() for symbol in v]
    
    @validator('analysis_depth')
    def validate_analysis_depth(cls, v):
        if v not in ['quick', 'standard', 'deep']:
            raise ValueError('分析深度必须是 quick, standard 或 deep')
        return v


class SymbolAnalysisResult(BaseModel):
    """单个交易对分析结果Schema"""
    symbol: str = Field(..., description="交易对")
    prediction: Optional[PredictionResult] = Field(default=None, description="预测结果")
    anomalies: Optional[List[AnomalyResult]] = Field(default=None, description="异常检测结果")
    optimization: Optional[OptimizationResult] = Field(default=None, description="参数优化结果")
    analysis_timestamp: datetime = Field(..., description="分析时间")
    error: Optional[str] = Field(default=None, description="错误信息")


class MLAnalysisSummary(BaseModel):
    """ML分析摘要Schema"""
    total_symbols: int = Field(..., description="总交易对数")
    successful_analyses: int = Field(..., description="成功分析数")
    total_anomalies: int = Field(..., description="总异常数")
    signals_distribution: Dict[str, int] = Field(..., description="信号分布")
    average_confidence: Optional[float] = Field(default=None, description="平均置信度")
    high_risk_symbols: List[str] = Field(default=[], description="高风险交易对")
    recommended_actions: List[str] = Field(default=[], description="建议操作")


class MLAnalysisResponse(BaseResponse):
    """ML综合分析响应Schema"""
    data: Dict[str, SymbolAnalysisResult]
    summary: MLAnalysisSummary


# ============================================================================
# 配置相关Schema
# ============================================================================

class MLConfig(BaseModel):
    """ML配置Schema"""
    enable_ml_prediction: bool = Field(..., description="启用ML预测")
    enable_anomaly_detection: bool = Field(..., description="启用异常检测")
    enable_adaptive_optimization: bool = Field(..., description="启用自适应优化")
    prediction_model: Dict[str, Any] = Field(..., description="预测模型配置")
    anomaly_detection: Dict[str, Any] = Field(..., description="异常检测配置")
    adaptive_optimization: Dict[str, Any] = Field(..., description="自适应优化配置")
    feature_engineering: Dict[str, Any] = Field(..., description="特征工程配置")


class MLConfigResponse(BaseResponse):
    """ML配置响应Schema"""
    config: MLConfig
    monitored_symbols: List[str]