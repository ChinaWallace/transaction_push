# -*- coding: utf-8 -*-
"""
机器学习相关数据模型
ML-related data models for predictions, anomalies and optimizations
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.sql import func
from enum import Enum
from datetime import datetime

from app.models.base import BaseModel


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


class MLPrediction(BaseModel):
    """ML预测记录模型"""
    __tablename__ = "ml_predictions"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    signal = Column(String(20), nullable=False, comment="预测信号")
    confidence = Column(Float, nullable=False, comment="置信度")
    probability_distribution = Column(JSON, comment="概率分布")
    features_importance = Column(JSON, comment="特征重要性")
    model_accuracy = Column(Float, comment="模型准确率")
    model_version = Column(String(50), comment="模型版本")
    prediction_horizon = Column(Integer, default=5, comment="预测时间范围")
    
    # 实际结果验证
    actual_signal = Column(String(20), comment="实际信号")
    prediction_correct = Column(Boolean, comment="预测是否正确")
    verified_at = Column(DateTime, comment="验证时间")
    
    def __repr__(self):
        return f"<MLPrediction(symbol={self.symbol}, signal={self.signal}, confidence={self.confidence})>"


class AnomalyDetection(BaseModel):
    """异常检测记录模型"""
    __tablename__ = "anomaly_detections"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    anomaly_type = Column(String(30), nullable=False, comment="异常类型")
    severity = Column(Float, nullable=False, comment="严重程度")
    description = Column(Text, comment="异常描述")
    affected_features = Column(JSON, comment="受影响的特征")
    recommendation = Column(Text, comment="建议措施")
    
    # 异常详细信息
    anomaly_score = Column(Float, comment="异常分数")
    detection_algorithm = Column(String(50), comment="检测算法")
    threshold_used = Column(Float, comment="使用的阈值")
    
    # 处理状态
    is_resolved = Column(Boolean, default=False, comment="是否已解决")
    resolved_at = Column(DateTime, comment="解决时间")
    resolution_notes = Column(Text, comment="解决说明")
    
    def __repr__(self):
        return f"<AnomalyDetection(symbol={self.symbol}, type={self.anomaly_type}, severity={self.severity})>"


class ParameterOptimization(BaseModel):
    """参数优化记录模型"""
    __tablename__ = "parameter_optimizations"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    optimization_type = Column(String(30), nullable=False, comment="优化类型")
    original_parameters = Column(JSON, comment="原始参数")
    optimized_parameters = Column(JSON, comment="优化后参数")
    performance_improvement = Column(Float, comment="性能提升")
    
    # 优化详情
    optimization_algorithm = Column(String(50), comment="优化算法")
    data_period_start = Column(DateTime, comment="数据期间开始")
    data_period_end = Column(DateTime, comment="数据期间结束")
    evaluation_metric = Column(String(30), comment="评估指标")
    metric_value = Column(Float, comment="指标值")
    
    # 应用状态
    is_applied = Column(Boolean, default=False, comment="是否已应用")
    applied_at = Column(DateTime, comment="应用时间")
    
    def __repr__(self):
        return f"<ParameterOptimization(symbol={self.symbol}, type={self.optimization_type}, improvement={self.performance_improvement})>"


class ModelPerformance(BaseModel):
    """模型性能记录模型"""
    __tablename__ = "model_performances"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    model_type = Column(String(30), nullable=False, comment="模型类型")
    model_version = Column(String(50), comment="模型版本")
    
    # 性能指标
    accuracy = Column(Float, comment="准确率")
    precision = Column(Float, comment="精确率")
    recall = Column(Float, comment="召回率")
    f1_score = Column(Float, comment="F1分数")
    
    # 训练信息
    training_samples = Column(Integer, comment="训练样本数")
    test_samples = Column(Integer, comment="测试样本数")
    training_duration = Column(Float, comment="训练时长(秒)")
    
    # 数据期间
    data_start_date = Column(DateTime, comment="数据开始日期")
    data_end_date = Column(DateTime, comment="数据结束日期")
    
    # 模型参数
    model_parameters = Column(JSON, comment="模型参数")
    feature_count = Column(Integer, comment="特征数量")
    
    def __repr__(self):
        return f"<ModelPerformance(symbol={self.symbol}, model={self.model_type}, accuracy={self.accuracy})>"


class FeatureImportance(BaseModel):
    """特征重要性记录模型"""
    __tablename__ = "feature_importances"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    model_version = Column(String(50), nullable=False, comment="模型版本")
    feature_name = Column(String(100), nullable=False, comment="特征名称")
    importance_score = Column(Float, nullable=False, comment="重要性分数")
    feature_type = Column(String(30), comment="特征类型")
    
    # 特征统计
    feature_mean = Column(Float, comment="特征均值")
    feature_std = Column(Float, comment="特征标准差")
    feature_min = Column(Float, comment="特征最小值")
    feature_max = Column(Float, comment="特征最大值")
    
    def __repr__(self):
        return f"<FeatureImportance(symbol={self.symbol}, feature={self.feature_name}, importance={self.importance_score})>"


class MLModelMetadata(BaseModel):
    """ML模型元数据模型"""
    __tablename__ = "ml_model_metadata"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    model_type = Column(String(30), nullable=False, comment="模型类型")
    model_version = Column(String(50), nullable=False, comment="模型版本")
    model_path = Column(String(255), comment="模型文件路径")
    scaler_path = Column(String(255), comment="标准化器路径")
    
    # 模型状态
    is_active = Column(Boolean, default=True, comment="是否激活")
    last_trained_at = Column(DateTime, comment="最后训练时间")
    last_used_at = Column(DateTime, comment="最后使用时间")
    
    # 配置信息
    training_config = Column(JSON, comment="训练配置")
    feature_config = Column(JSON, comment="特征配置")
    
    # 性能摘要
    current_accuracy = Column(Float, comment="当前准确率")
    prediction_count = Column(Integer, default=0, comment="预测次数")
    correct_predictions = Column(Integer, default=0, comment="正确预测次数")
    
    def __repr__(self):
        return f"<MLModelMetadata(symbol={self.symbol}, model={self.model_type}, version={self.model_version})>"


class TradingSignalHistory(BaseModel):
    """交易信号历史记录模型"""
    __tablename__ = "trading_signal_history"
    
    symbol = Column(String(20), nullable=False, index=True, comment="交易对")
    signal_source = Column(String(30), nullable=False, comment="信号来源")  # traditional, ml, combined
    signal_type = Column(String(20), nullable=False, comment="信号类型")
    signal_strength = Column(String(20), comment="信号强度")
    
    # 价格信息
    price_at_signal = Column(Float, comment="信号时价格")
    price_after_1h = Column(Float, comment="1小时后价格")
    price_after_4h = Column(Float, comment="4小时后价格")
    price_after_24h = Column(Float, comment="24小时后价格")
    
    # 收益率
    return_1h = Column(Float, comment="1小时收益率")
    return_4h = Column(Float, comment="4小时收益率")
    return_24h = Column(Float, comment="24小时收益率")
    
    # 信号详情
    signal_details = Column(JSON, comment="信号详细信息")
    confidence_score = Column(Float, comment="置信度分数")
    
    # 验证状态
    is_verified = Column(Boolean, default=False, comment="是否已验证")
    verification_notes = Column(Text, comment="验证说明")
    
    def __repr__(self):
        return f"<TradingSignalHistory(symbol={self.symbol}, source={self.signal_source}, type={self.signal_type})>"