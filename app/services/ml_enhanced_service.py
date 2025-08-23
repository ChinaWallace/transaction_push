# -*- coding: utf-8 -*-
"""
机器学习增强服务
ML Enhanced Service for signal prediction, anomaly detection and adaptive optimization
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import numpy as np
import pandas as pd
from dataclasses import dataclass
import pickle
import os
from pathlib import Path

# 免费的机器学习库
from sklearn.ensemble import RandomForestClassifier, IsolationForest, GradientBoostingClassifier
from sklearn.svm import SVC, OneClassSVM
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.pipeline import Pipeline
import joblib

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.binance_service import BinanceService
from app.services.trend_analysis_service import TrendAnalysisService
from app.utils.exceptions import MLModelError, DataNotFoundError

logger = get_logger(__name__)
settings = get_settings()


class PredictionSignal(Enum):
    """预测信号枚举"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class AnomalyType(Enum):
    """异常类型枚举"""
    PRICE_ANOMALY = "price_anomaly"
    VOLUME_ANOMALY = "volume_anomaly"
    TREND_ANOMALY = "trend_anomaly"
    PATTERN_ANOMALY = "pattern_anomaly"
    MARKET_ANOMALY = "market_anomaly"


@dataclass
class MLPrediction:
    """ML预测结果"""
    symbol: str
    timestamp: datetime
    signal: PredictionSignal
    confidence: float
    probability_distribution: Dict[str, float]
    features_importance: Dict[str, float]
    model_accuracy: float


@dataclass
class AnomalyDetection:
    """异常检测结果"""
    symbol: str
    timestamp: datetime
    anomaly_type: AnomalyType
    severity: float
    description: str
    affected_features: List[str]
    recommendation: str


class MLEnhancedService:
    """机器学习增强服务类"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.trend_service = TrendAnalysisService()
        self.ml_config = settings.ml_config
        
        # 模型存储路径
        self.model_dir = Path("models")
        self.model_dir.mkdir(exist_ok=True)
        
        # 预测模型
        self.prediction_models = {}
        self.scalers = {}
        
        # 异常检测模型
        self.anomaly_detectors = {}
        
        # 特征工程器
        self.feature_engineer = FeatureEngineer()
        
        # 自适应优化器
        self.adaptive_optimizer = AdaptiveOptimizer()
    
    async def initialize_models(self, symbols: List[str]) -> None:
        """初始化ML模型"""
        try:
            for symbol in symbols:
                await self._load_or_create_models(symbol)
            
            logger.info(f"ML models initialized for {len(symbols)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to initialize ML models: {e}")
            raise MLModelError(f"Model initialization failed: {e}")
    
    async def predict_signal(self, symbol: str, 
                           historical_data: Optional[pd.DataFrame] = None) -> MLPrediction:
        """
        使用ML模型预测交易信号
        
        Args:
            symbol: 交易对
            historical_data: 历史数据，如果为None则自动获取
            
        Returns:
            ML预测结果
        """
        try:
            # 获取或使用历史数据
            if historical_data is None:
                historical_data = await self._get_historical_data(symbol)
            
            # 特征工程
            features = await self.feature_engineer.extract_features(historical_data)
            
            # 获取预测模型
            model = self.prediction_models.get(symbol)
            scaler = self.scalers.get(symbol)
            
            if model is None or scaler is None:
                await self._load_or_create_models(symbol)
                model = self.prediction_models[symbol]
                scaler = self.scalers[symbol]
            
            # 预处理特征
            latest_features = features.iloc[-1:].values
            scaled_features = scaler.transform(latest_features)
            
            # 预测
            prediction = model.predict(scaled_features)[0]
            probabilities = model.predict_proba(scaled_features)[0]
            
            # 获取特征重要性
            feature_importance = {}
            if hasattr(model, 'feature_importances_'):
                for i, importance in enumerate(model.feature_importances_):
                    feature_importance[f'feature_{i}'] = importance
            
            # 构建预测结果 - 根据实际模型输出调整
            num_classes = len(probabilities)
            
            if num_classes == 3:
                # 3分类模型：卖出、持有、买入
                signal_mapping = {
                    0: PredictionSignal.SELL,
                    1: PredictionSignal.HOLD,
                    2: PredictionSignal.BUY
                }
                probability_dist = {
                    'strong_sell': 0.0,
                    'sell': probabilities[0],
                    'hold': probabilities[1],
                    'buy': probabilities[2],
                    'strong_buy': 0.0
                }
            else:
                # 5分类模型：强烈卖出、卖出、持有、买入、强烈买入
                signal_mapping = {
                    0: PredictionSignal.STRONG_SELL,
                    1: PredictionSignal.SELL,
                    2: PredictionSignal.HOLD,
                    3: PredictionSignal.BUY,
                    4: PredictionSignal.STRONG_BUY
                }
                probability_dist = {
                    'strong_sell': probabilities[0] if len(probabilities) > 0 else 0.0,
                    'sell': probabilities[1] if len(probabilities) > 1 else 0.0,
                    'hold': probabilities[2] if len(probabilities) > 2 else 0.0,
                    'buy': probabilities[3] if len(probabilities) > 3 else 0.0,
                    'strong_buy': probabilities[4] if len(probabilities) > 4 else 0.0
                }
            
            result = MLPrediction(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=signal_mapping[prediction],
                confidence=max(probabilities),
                probability_distribution=probability_dist,
                features_importance=feature_importance,
                model_accuracy=getattr(model, '_accuracy', 0.0)
            )
            
            trading_logger.info(f"ML prediction for {symbol}: {result.signal.value} (confidence: {result.confidence:.3f})")
            
            return result
            
        except Exception as e:
            logger.error(f"ML prediction failed for {symbol}: {e}")
            raise MLModelError(f"Prediction failed: {e}")
    
    async def detect_anomalies(self, symbol: str, 
                             historical_data: Optional[pd.DataFrame] = None) -> List[AnomalyDetection]:
        """
        检测市场异常
        
        Args:
            symbol: 交易对
            historical_data: 历史数据
            
        Returns:
            异常检测结果列表
        """
        try:
            # 获取历史数据
            if historical_data is None:
                historical_data = await self._get_historical_data(symbol)
            
            anomalies = []
            
            # 价格异常检测
            price_anomalies = await self._detect_price_anomalies(symbol, historical_data)
            anomalies.extend(price_anomalies)
            
            # 成交量异常检测
            volume_anomalies = await self._detect_volume_anomalies(symbol, historical_data)
            anomalies.extend(volume_anomalies)
            
            # 模式异常检测
            pattern_anomalies = await self._detect_pattern_anomalies(symbol, historical_data)
            anomalies.extend(pattern_anomalies)
            
            if anomalies:
                trading_logger.info(f"Detected {len(anomalies)} anomalies for {symbol}")
            
            return anomalies
            
        except Exception as e:
            logger.error(f"Anomaly detection failed for {symbol}: {e}")
            raise MLModelError(f"Anomaly detection failed: {e}")
    
    async def optimize_parameters(self, symbol: str) -> Dict[str, Any]:
        """
        自适应参数优化
        
        Args:
            symbol: 交易对
            
        Returns:
            优化后的参数
        """
        try:
            # 获取历史数据
            historical_data = await self._get_historical_data(symbol, days=30)
            
            # 使用自适应优化器
            optimized_params = await self.adaptive_optimizer.optimize_strategy_parameters(
                symbol, historical_data
            )
            
            trading_logger.info(f"Parameters optimized for {symbol}: {optimized_params}")
            
            return optimized_params
            
        except Exception as e:
            logger.error(f"Parameter optimization failed for {symbol}: {e}")
            raise MLModelError(f"Parameter optimization failed: {e}")
    
    async def _load_or_create_models(self, symbol: str) -> None:
        """加载或创建模型"""
        model_path = self.model_dir / f"{symbol}_prediction_model.joblib"
        scaler_path = self.model_dir / f"{symbol}_scaler.joblib"
        
        if model_path.exists() and scaler_path.exists():
            # 加载现有模型
            self.prediction_models[symbol] = joblib.load(model_path)
            self.scalers[symbol] = joblib.load(scaler_path)
            logger.info(f"Loaded existing models for {symbol}")
        else:
            # 创建新模型
            await self._train_new_model(symbol)
    
    async def _train_new_model(self, symbol: str) -> None:
        """训练新模型"""
        try:
            # 获取训练数据
            historical_data = await self._get_historical_data(symbol, days=90)
            
            # 特征工程
            features = await self.feature_engineer.extract_features(historical_data)
            
            # 创建标签（基于未来价格变化）
            labels = self._create_labels(historical_data)
            
            # 确保特征和标签长度一致
            min_length = min(len(features), len(labels))
            features = features.iloc[:min_length]
            labels = labels[:min_length]
            
            # 分割数据
            X_train, X_test, y_train, y_test = train_test_split(
                features, labels, test_size=0.2, random_state=42
            )
            
            # 创建和训练模型
            scaler = RobustScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # 选择模型类型
            model_type = self.ml_config['prediction_model']['model_type']
            if model_type == 'random_forest':
                model = RandomForestClassifier(n_estimators=100, random_state=42)
            elif model_type == 'gradient_boosting':
                model = GradientBoostingClassifier(n_estimators=100, random_state=42)
            else:
                model = RandomForestClassifier(n_estimators=100, random_state=42)
            
            # 训练模型
            model.fit(X_train_scaled, y_train)
            
            # 评估模型
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            # 保存模型准确率
            model._accuracy = accuracy
            
            # 检查模型质量
            min_accuracy = self.ml_config['prediction_model']['min_accuracy_threshold']
            if accuracy < min_accuracy:
                logger.warning(f"Model accuracy {accuracy:.3f} below threshold {min_accuracy} for {symbol}")
            
            # 保存模型
            self.prediction_models[symbol] = model
            self.scalers[symbol] = scaler
            
            model_path = self.model_dir / f"{symbol}_prediction_model.joblib"
            scaler_path = self.model_dir / f"{symbol}_scaler.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)
            
            logger.info(f"Trained new model for {symbol} with accuracy: {accuracy:.3f}")
            
        except Exception as e:
            logger.error(f"Model training failed for {symbol}: {e}")
            raise MLModelError(f"Model training failed: {e}")
    
    async def _get_historical_data(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """获取历史数据"""
        try:
            # 计算limit，币安API最大限制为1000
            limit = min(24 * days, 1000)
            
            # 获取K线数据
            klines = await self.binance_service.get_kline_data(
                symbol, '1h', limit=limit
            )
            
            if not klines:
                raise DataNotFoundError(f"No historical data for {symbol}")
            
            # 转换为DataFrame
            df = pd.DataFrame(klines)
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # 转换数值列
            numeric_columns = ['open_price', 'high_price', 'low_price', 'close_price', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col])
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to get historical data for {symbol}: {e}")
            raise DataNotFoundError(f"Historical data retrieval failed: {e}")
    
    def _create_labels(self, data: pd.DataFrame) -> np.ndarray:
        """创建训练标签 - 使用3分类简化模型"""
        # 计算未来价格变化
        future_returns = data['close_price'].pct_change(periods=5).shift(-5)
        
        # 创建分类标签 (3分类)
        labels = np.ones(len(future_returns))  # 默认为持有(1)
        
        # 定义阈值
        threshold = 0.02  # 2%
        
        labels[future_returns > threshold] = 2   # BUY
        labels[future_returns < -threshold] = 0  # SELL
        # 其他情况保持为1 (HOLD)
        
        return labels[:-5]  # 移除最后5个无法计算未来收益的点
    
    async def _detect_price_anomalies(self, symbol: str, data: pd.DataFrame) -> List[AnomalyDetection]:
        """检测价格异常"""
        anomalies = []
        
        try:
            # 使用Isolation Forest检测价格异常
            price_features = data[['open_price', 'high_price', 'low_price', 'close_price']].values
            
            detector = IsolationForest(
                contamination=self.ml_config['anomaly_detection']['contamination'],
                random_state=42
            )
            
            anomaly_scores = detector.fit_predict(price_features)
            
            # 找出异常点
            anomaly_indices = np.where(anomaly_scores == -1)[0]
            
            for idx in anomaly_indices[-5:]:  # 只关注最近的5个异常
                severity = abs(detector.score_samples([price_features[idx]])[0])
                
                anomaly = AnomalyDetection(
                    symbol=symbol,
                    timestamp=data.index[idx],
                    anomaly_type=AnomalyType.PRICE_ANOMALY,
                    severity=severity,
                    description=f"价格异常波动检测到异常值",
                    affected_features=['price'],
                    recommendation="密切关注价格走势，可能存在异常波动"
                )
                anomalies.append(anomaly)
            
        except Exception as e:
            logger.warning(f"Price anomaly detection failed for {symbol}: {e}")
        
        return anomalies
    
    async def _detect_volume_anomalies(self, symbol: str, data: pd.DataFrame) -> List[AnomalyDetection]:
        """检测成交量异常"""
        anomalies = []
        
        try:
            # 计算成交量统计特征
            volume_mean = data['volume'].rolling(window=24).mean()
            volume_std = data['volume'].rolling(window=24).std()
            
            # 检测异常成交量
            z_scores = (data['volume'] - volume_mean) / volume_std
            anomaly_threshold = 3.0
            
            anomaly_indices = np.where(abs(z_scores) > anomaly_threshold)[0]
            
            for idx in anomaly_indices[-3:]:  # 最近3个异常
                severity = abs(z_scores.iloc[idx]) / anomaly_threshold
                
                anomaly = AnomalyDetection(
                    symbol=symbol,
                    timestamp=data.index[idx],
                    anomaly_type=AnomalyType.VOLUME_ANOMALY,
                    severity=severity,
                    description=f"成交量异常：{data['volume'].iloc[idx]:.0f} (正常范围: {volume_mean.iloc[idx]:.0f}±{volume_std.iloc[idx]:.0f})",
                    affected_features=['volume'],
                    recommendation="关注市场情绪变化，可能有重要消息或大资金进出"
                )
                anomalies.append(anomaly)
                
        except Exception as e:
            logger.warning(f"Volume anomaly detection failed for {symbol}: {e}")
        
        return anomalies
    
    async def _detect_pattern_anomalies(self, symbol: str, data: pd.DataFrame) -> List[AnomalyDetection]:
        """检测模式异常"""
        anomalies = []
        
        try:
            # 计算技术指标
            data['returns'] = data['close_price'].pct_change()
            data['volatility'] = data['returns'].rolling(window=24).std()
            
            # 检测波动率异常
            vol_mean = data['volatility'].rolling(window=168).mean()  # 7天均值
            vol_std = data['volatility'].rolling(window=168).std()
            
            vol_z_scores = (data['volatility'] - vol_mean) / vol_std
            vol_threshold = 2.5
            
            vol_anomaly_indices = np.where(abs(vol_z_scores) > vol_threshold)[0]
            
            for idx in vol_anomaly_indices[-2:]:  # 最近2个异常
                severity = abs(vol_z_scores.iloc[idx]) / vol_threshold
                
                anomaly = AnomalyDetection(
                    symbol=symbol,
                    timestamp=data.index[idx],
                    anomaly_type=AnomalyType.PATTERN_ANOMALY,
                    severity=severity,
                    description=f"波动率异常：当前{data['volatility'].iloc[idx]:.4f}，正常范围{vol_mean.iloc[idx]:.4f}±{vol_std.iloc[idx]:.4f}",
                    affected_features=['volatility'],
                    recommendation="市场波动率异常，注意风险控制"
                )
                anomalies.append(anomaly)
                
        except Exception as e:
            logger.warning(f"Pattern anomaly detection failed for {symbol}: {e}")
        
        return anomalies


class FeatureEngineer:
    """特征工程器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
    
    async def extract_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """提取特征"""
        try:
            features = pd.DataFrame(index=data.index)
            
            # 价格特征
            features['price_change'] = data['close_price'].pct_change()
            features['high_low_ratio'] = data['high_price'] / data['low_price']
            features['open_close_ratio'] = data['open_price'] / data['close_price']
            
            # 技术指标特征
            features['sma_5'] = data['close_price'].rolling(window=5).mean()
            features['sma_20'] = data['close_price'].rolling(window=20).mean()
            features['price_sma5_ratio'] = data['close_price'] / features['sma_5']
            features['price_sma20_ratio'] = data['close_price'] / features['sma_20']
            
            # 波动率特征
            features['volatility_5'] = data['close_price'].pct_change().rolling(window=5).std()
            features['volatility_20'] = data['close_price'].pct_change().rolling(window=20).std()
            
            # 成交量特征
            features['volume_sma'] = data['volume'].rolling(window=20).mean()
            features['volume_ratio'] = data['volume'] / features['volume_sma']
            
            # RSI特征
            features['rsi'] = self._calculate_rsi(data['close_price'])
            
            # 布林带特征
            bb_upper, bb_lower = self._calculate_bollinger_bands(data['close_price'])
            features['bb_position'] = (data['close_price'] - bb_lower) / (bb_upper - bb_lower)
            
            # 移除NaN值
            features = features.fillna(method='bfill').fillna(0)
            
            return features
            
        except Exception as e:
            self.logger.error(f"Feature extraction failed: {e}")
            raise MLModelError(f"Feature extraction failed: {e}")
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: int = 2) -> Tuple[pd.Series, pd.Series]:
        """计算布林带"""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        return upper_band, lower_band


class AdaptiveOptimizer:
    """自适应优化器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
    
    async def optimize_strategy_parameters(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """优化策略参数"""
        try:
            # SuperTrend参数优化
            best_supertrend_params = await self._optimize_supertrend_parameters(data)
            
            # 成交量阈值优化
            best_volume_params = await self._optimize_volume_parameters(data)
            
            optimized_params = {
                'supertrend': best_supertrend_params,
                'volume': best_volume_params,
                'optimization_timestamp': datetime.now(),
                'data_period': f"{data.index[0]} to {data.index[-1]}"
            }
            
            return optimized_params
            
        except Exception as e:
            self.logger.error(f"Parameter optimization failed for {symbol}: {e}")
            raise MLModelError(f"Parameter optimization failed: {e}")
    
    async def _optimize_supertrend_parameters(self, data: pd.DataFrame) -> Dict[str, Any]:
        """优化SuperTrend参数"""
        best_params = {'period': 10, 'multiplier': 3.0}
        best_score = 0
        
        # 参数搜索范围
        periods = [7, 10, 14, 21]
        multipliers = [2.0, 2.5, 3.0, 3.5, 4.0]
        
        for period in periods:
            for multiplier in multipliers:
                try:
                    # 计算SuperTrend
                    score = self._evaluate_supertrend_performance(data, period, multiplier)
                    
                    if score > best_score:
                        best_score = score
                        best_params = {'period': period, 'multiplier': multiplier}
                        
                except Exception as e:
                    continue
        
        best_params['performance_score'] = best_score
        return best_params
    
    def _evaluate_supertrend_performance(self, data: pd.DataFrame, period: int, multiplier: float) -> float:
        """评估SuperTrend性能"""
        try:
            # 简化的SuperTrend计算
            hl2 = (data['high_price'] + data['low_price']) / 2
            atr = self._calculate_atr(data, period)
            
            upper_band = hl2 + (multiplier * atr)
            lower_band = hl2 - (multiplier * atr)
            
            # 简化的趋势判断
            trend = pd.Series(index=data.index, dtype=float)
            for i in range(1, len(data)):
                if data['close_price'].iloc[i] > upper_band.iloc[i-1]:
                    trend.iloc[i] = 1  # 上涨
                elif data['close_price'].iloc[i] < lower_band.iloc[i-1]:
                    trend.iloc[i] = -1  # 下跌
                else:
                    trend.iloc[i] = trend.iloc[i-1] if i > 0 else 0
            
            # 计算收益率
            returns = data['close_price'].pct_change()
            strategy_returns = trend.shift(1) * returns
            
            # 计算夏普比率作为性能指标
            if strategy_returns.std() > 0:
                sharpe_ratio = strategy_returns.mean() / strategy_returns.std() * np.sqrt(24)  # 小时数据
                return max(0, sharpe_ratio)
            else:
                return 0
                
        except Exception:
            return 0
    
    def _calculate_atr(self, data: pd.DataFrame, period: int) -> pd.Series:
        """计算ATR"""
        high_low = data['high_price'] - data['low_price']
        high_close = np.abs(data['high_price'] - data['close_price'].shift())
        low_close = np.abs(data['low_price'] - data['close_price'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    async def _optimize_volume_parameters(self, data: pd.DataFrame) -> Dict[str, Any]:
        """优化成交量参数"""
        # 计算最优成交量阈值
        volume_mean = data['volume'].mean()
        volume_std = data['volume'].std()
        
        # 基于统计分布确定阈值
        optimal_threshold = volume_mean + 2 * volume_std
        threshold_multiplier = optimal_threshold / volume_mean
        
        return {
            'threshold_multiplier': round(threshold_multiplier, 2),
            'base_volume': volume_mean,
            'volume_std': volume_std
        }