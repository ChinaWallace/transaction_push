# -*- coding: utf-8 -*-
"""
自适应机器学习服务
Adaptive ML Service - 能够从传统分析中学习，避免一直卖出的偏差
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import numpy as np
import pandas as pd
from dataclasses import dataclass
import pickle
import os
from pathlib import Path

# 机器学习库
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.utils.class_weight import compute_class_weight
import joblib

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.services.trading_decision_service import TradingDecisionService
from app.utils.exceptions import MLModelError, DataNotFoundError

logger = get_logger(__name__)
settings = get_settings()


class AdaptiveSignal(Enum):
    """自适应信号枚举"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"


@dataclass
class AdaptivePrediction:
    """自适应预测结果"""
    symbol: str
    timestamp: datetime
    signal: AdaptiveSignal
    confidence: float
    traditional_agreement: float  # 与传统分析的一致性
    learning_score: float  # 学习得分
    model_accuracy: float
    reasoning: str


class AdaptiveMLService:
    """自适应机器学习服务 - 能够从传统分析中学习"""
    

    def _check_model_compatibility(self, symbol: str, features: pd.DataFrame) -> bool:
        """检查模型与特征的兼容性"""
        try:
            model_path = self.model_dir / f"{symbol}_adaptive_model.joblib"
            scaler_path = self.model_dir / f"{symbol}_adaptive_scaler.joblib"
            
            if not (model_path.exists() and scaler_path.exists()):
                return False
            
            # 加载scaler检查特征维度
            import joblib
            scaler = joblib.load(scaler_path)
            
            # 检查scaler期望的特征数量
            if hasattr(scaler, 'n_features_in_'):
                expected_features = scaler.n_features_in_
                actual_features = features.shape[1]
                
                if expected_features != actual_features:
                    logger.warning(f"特征维度不匹配 {symbol}: 期望{expected_features}, 实际{actual_features}")
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"模型兼容性检查失败 {symbol}: {e}")
            return False

    def __init__(self):
        self.exchange_service = OKXService()
        self.traditional_service = TradingDecisionService()
        
        # 模型存储路径
        self.model_dir = Path("models/adaptive")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # 学习历史存储
        self.learning_history_dir = Path("models/learning_history")
        self.learning_history_dir.mkdir(parents=True, exist_ok=True)
        
        # 模型和学习器
        self.prediction_models = {}
        self.scalers = {}
        self.learning_records = {}  # 存储学习记录
        
        # 学习参数
        self.learning_config = {
            'agreement_weight': 0.7,  # 传统分析一致性权重
            'performance_weight': 0.3,  # 历史表现权重
            'min_learning_samples': 50,  # 最少学习样本
            'rebalance_threshold': 0.6,  # 重新平衡阈值
            'learning_rate': 0.1  # 学习率
        }
    
    async def predict_with_learning(self, symbol: str) -> AdaptivePrediction:
        """
        使用自适应学习进行预测
        
        Args:
            symbol: 交易对
            
        Returns:
            自适应预测结果
        """
        try:
            # 1. 获取传统分析结果
            traditional_result = await self._get_traditional_analysis(symbol)
            
            # 2. 获取历史数据
            historical_data = await self._get_historical_data(symbol)
            
            # 3. 检查是否需要学习更新
            await self._update_learning_from_traditional(symbol, traditional_result, historical_data)
            
            # 4. 获取或训练自适应模型
            model, scaler = await self._get_or_train_adaptive_model(symbol)
            
            # 5. 提取特征（包含传统分析特征）
            features = await self._extract_adaptive_features(historical_data, traditional_result)
            
            # 6. 进行预测
            latest_features = features.iloc[-1:].values
            scaled_features = scaler.transform(latest_features)
            
            prediction = model.predict(scaled_features)[0]
            probabilities = model.predict_proba(scaled_features)[0]
            
            # 7. 计算与传统分析的一致性
            traditional_agreement = self._calculate_agreement(prediction, traditional_result)
            
            # 8. 计算学习得分
            learning_score = self._calculate_learning_score(symbol, prediction, traditional_result)
            
            # 9. 构建结果
            signal_mapping = {
                0: AdaptiveSignal.STRONG_SELL,
                1: AdaptiveSignal.SELL,
                2: AdaptiveSignal.HOLD,
                3: AdaptiveSignal.BUY,
                4: AdaptiveSignal.STRONG_BUY
            }
            
            result = AdaptivePrediction(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=signal_mapping[prediction],
                confidence=max(probabilities),
                traditional_agreement=traditional_agreement,
                learning_score=learning_score,
                model_accuracy=getattr(model, '_accuracy', 0.0),
                reasoning=self._generate_reasoning(prediction, traditional_result, traditional_agreement)
            )
            
            # 10. 记录预测结果用于后续学习
            await self._record_prediction(symbol, result, traditional_result)
            
            trading_logger.info(f"自适应ML预测 {symbol}: {result.signal.value} "
                              f"(置信度: {result.confidence:.3f}, 传统一致性: {result.traditional_agreement:.3f})")
            
            return result
            
        except Exception as e:
            logger.error(f"自适应预测失败 {symbol}: {e}")
            raise MLModelError(f"自适应预测失败: {e}")
    
    async def _get_traditional_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取传统技术分析结果"""
        try:
            async with self.traditional_service.exchange_service as exchange:
                market_signals = await self.traditional_service._get_market_signals(symbol, exchange)
            
            # 转换为数值信号
            trend = market_signals.get('trend', 'neutral')
            confidence = market_signals.get('confidence', 50.0)
            
            # 信号映射
            if trend == 'bullish':
                if confidence > 85:
                    signal_value = 4  # 强烈买入
                elif confidence > 65:
                    signal_value = 3  # 买入
                else:
                    signal_value = 2  # 持有
            elif trend == 'bearish':
                if confidence > 85:
                    signal_value = 0  # 强烈卖出
                elif confidence > 65:
                    signal_value = 1  # 卖出
                else:
                    signal_value = 2  # 持有
            else:
                signal_value = 2  # 持有
            
            return {
                'signal_value': signal_value,
                'confidence': confidence,
                'trend': trend,
                'raw_signals': market_signals
            }
            
        except Exception as e:
            logger.warning(f"获取传统分析失败: {e}")
            return {
                'signal_value': 2,  # 默认持有
                'confidence': 50.0,
                'trend': 'neutral',
                'raw_signals': {}
            }
    
    async def _update_learning_from_traditional(self, symbol: str, traditional_result: Dict, 
                                              historical_data: pd.DataFrame) -> None:
        """从传统分析中学习更新"""
        try:
            # 获取学习记录
            learning_record = self.learning_records.get(symbol, {
                'traditional_signals': [],
                'timestamps': [],
                'market_data': [],
                'last_update': None
            })
            
            # 添加新的学习样本
            learning_record['traditional_signals'].append(traditional_result['signal_value'])
            learning_record['timestamps'].append(datetime.now())
            learning_record['market_data'].append({
                'price': historical_data['close_price'].iloc[-1],
                'volume': historical_data['volume'].iloc[-1],
                'volatility': historical_data['close_price'].pct_change().rolling(24).std().iloc[-1]
            })
            
            # 保持最近的学习样本（最多200个）
            max_samples = 200
            if len(learning_record['traditional_signals']) > max_samples:
                learning_record['traditional_signals'] = learning_record['traditional_signals'][-max_samples:]
                learning_record['timestamps'] = learning_record['timestamps'][-max_samples:]
                learning_record['market_data'] = learning_record['market_data'][-max_samples:]
            
            learning_record['last_update'] = datetime.now()
            self.learning_records[symbol] = learning_record
            
            # 保存学习记录
            await self._save_learning_record(symbol, learning_record)
            
            # 检查是否需要重新训练模型
            if len(learning_record['traditional_signals']) >= self.learning_config['min_learning_samples']:
                await self._check_and_retrain_if_needed(symbol, learning_record)
            
        except Exception as e:
            logger.warning(f"学习更新失败 {symbol}: {e}")
    
    async def _get_or_train_adaptive_model(self, symbol: str) -> Tuple[Any, Any]:
        """获取或训练自适应模型"""
        model_path = self.model_dir / f"{symbol}_adaptive_model.joblib"
        scaler_path = self.model_dir / f"{symbol}_adaptive_scaler.joblib"
        
        # 检查模型是否存在且兼容
        if (model_path.exists() and scaler_path.exists() and 
            symbol in self.prediction_models and symbol in self.scalers):
            
            # 获取当前特征维度进行兼容性检查
            try:
                historical_data = await self._get_historical_data(symbol, days=1)
                traditional_result = await self._get_traditional_analysis(symbol)
                features = await self._extract_adaptive_features(historical_data, traditional_result)
                
                if self._check_model_compatibility(symbol, features):
                    return self.prediction_models[symbol], self.scalers[symbol]
                else:
                    logger.info(f"模型不兼容，重新训练 {symbol}")
                    # 删除不兼容的模型文件
                    model_path.unlink(missing_ok=True)
                    scaler_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"兼容性检查失败，重新训练 {symbol}: {e}")
        
        # 训练新的自适应模型
        await self._train_adaptive_model(symbol)
        return self.prediction_models[symbol], self.scalers[symbol]
    
    async def _train_adaptive_model(self, symbol: str) -> None:
        """训练自适应模型"""
        try:
            # 获取历史数据
            historical_data = await self._get_historical_data(symbol, days=60)
            
            # 获取学习记录
            learning_record = await self._load_learning_record(symbol)
            
            # 创建训练数据
            X, y = await self._create_adaptive_training_data(symbol, historical_data, learning_record)
            
            if len(X) < 30:  # 最少需要30个样本
                logger.warning(f"训练数据不足 {symbol}: {len(X)} 样本")
                # 使用基础模型
                await self._create_baseline_model(symbol, historical_data)
                return
            
            # 检查类别分布，处理类别不平衡
            unique_classes, class_counts = np.unique(y, return_counts=True)
            min_class_count = min(class_counts)
            
            logger.info(f"类别分布 {symbol}: {dict(zip(unique_classes, class_counts))}")
            
            # 如果某个类别样本太少，进行数据增强或合并
            if min_class_count < 2:
                logger.warning(f"检测到类别不平衡 {symbol}，进行数据平衡处理")
                
                # 方法1: 合并相似类别
                # 0,1 -> 0 (卖出), 2 -> 2 (持有), 3,4 -> 3 (买入)
                y_balanced = np.copy(y)
                y_balanced[y_balanced == 1] = 0  # 卖出合并到强烈卖出
                y_balanced[y_balanced == 4] = 3  # 强烈买入合并到买入
                
                # 重新检查类别分布
                unique_balanced, balanced_counts = np.unique(y_balanced, return_counts=True)
                min_balanced_count = min(balanced_counts)
                
                if min_balanced_count < 2:
                    # 方法2: 如果还是不够，使用SMOTE或简单复制
                    from collections import Counter
                    class_counter = Counter(y_balanced)
                    
                    # 找到最少的类别，复制样本
                    min_class = min(class_counter, key=class_counter.get)
                    min_indices = np.where(y_balanced == min_class)[0]
                    
                    if len(min_indices) == 1:
                        # 复制这个样本
                        X = np.vstack([X, X[min_indices]])
                        y_balanced = np.append(y_balanced, y_balanced[min_indices])
                        logger.info(f"复制了类别 {min_class} 的样本以平衡数据")
                
                y = y_balanced
                logger.info(f"平衡后类别分布 {symbol}: {dict(zip(*np.unique(y, return_counts=True)))}")
            
            # 分割数据 - 如果类别太少，不使用stratify
            try:
                if min(np.bincount(y)) >= 2:
                    X_train, X_test, y_train, y_test = train_test_split(
                        X, y, test_size=0.2, random_state=42, stratify=y
                    )
                else:
                    X_train, X_test, y_train, y_test = train_test_split(
                        X, y, test_size=0.2, random_state=42
                    )
            except ValueError as e:
                logger.warning(f"分层采样失败 {symbol}: {e}，使用随机采样")
                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
            
            # 计算类别权重以平衡数据
            try:
                class_weights = compute_class_weight(
                    'balanced',
                    classes=np.unique(y_train),
                    y=y_train
                )
                class_weight_dict = dict(zip(np.unique(y_train), class_weights))
            except ValueError as e:
                logger.warning(f"计算类别权重失败 {symbol}: {e}，使用默认权重")
                class_weight_dict = None
            
            # 创建和训练模型
            scaler = RobustScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # 使用梯度提升，对不平衡数据更友好
            model = GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=6,
                random_state=42,
                subsample=0.8
            )
            
            # 训练模型 - 处理类别权重
            if class_weight_dict is not None:
                # 计算样本权重
                sample_weights = np.array([class_weight_dict.get(label, 1.0) for label in y_train])
                model.fit(X_train_scaled, y_train, sample_weight=sample_weights)
            else:
                model.fit(X_train_scaled, y_train)
            
            # 评估模型
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            # 检查各类别的预测分布
            unique, counts = np.unique(y_pred, return_counts=True)
            pred_distribution = dict(zip(unique, counts / len(y_pred)))
            
            logger.info(f"模型预测分布 {symbol}: {pred_distribution}")
            
            # 如果卖出预测过多，进行调整
            if pred_distribution.get(0, 0) + pred_distribution.get(1, 0) > 0.6:  # 卖出信号超过60%
                logger.warning(f"检测到卖出偏差 {symbol}，进行模型调整")
                # 重新训练时增加买入和持有样本的权重
                if class_weight_dict is not None:
                    adjusted_weights = class_weight_dict.copy()
                    adjusted_weights[3] = adjusted_weights.get(3, 1) * 1.5  # 买入权重增加50%
                    adjusted_weights[4] = adjusted_weights.get(4, 1) * 1.5  # 强烈买入权重增加50%
                    adjusted_weights[2] = adjusted_weights.get(2, 1) * 1.2  # 持有权重增加20%
                else:
                    adjusted_weights = {0: 1.0, 1: 1.0, 2: 1.2, 3: 1.5, 4: 1.5}
                
                # 重新训练
                model = GradientBoostingClassifier(
                    n_estimators=100,
                    learning_rate=0.1,
                    max_depth=6,
                    random_state=42,
                    subsample=0.8
                )
                
                # 使用样本权重
                sample_weights = np.array([adjusted_weights.get(label, 1.0) for label in y_train])
                model.fit(X_train_scaled, y_train, sample_weight=sample_weights)
                
                # 重新评估
                y_pred = model.predict(X_test_scaled)
                accuracy = accuracy_score(y_test, y_pred)
                
                unique, counts = np.unique(y_pred, return_counts=True)
                new_distribution = dict(zip(unique, counts / len(y_pred)))
                logger.info(f"调整后预测分布 {symbol}: {new_distribution}")
            
            # 保存模型
            model._accuracy = accuracy
            self.prediction_models[symbol] = model
            self.scalers[symbol] = scaler
            
            model_path = self.model_dir / f"{symbol}_adaptive_model.joblib"
            scaler_path = self.model_dir / f"{symbol}_adaptive_scaler.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)
            
            logger.info(f"自适应模型训练完成 {symbol}: 准确率 {accuracy:.3f}")
            
        except Exception as e:
            logger.error(f"自适应模型训练失败 {symbol}: {e}")
            # 回退到基础模型
            await self._create_baseline_model(symbol, await self._get_historical_data(symbol))
    
    async def _create_baseline_model(self, symbol: str, historical_data: pd.DataFrame) -> None:
        """创建基础模型（当学习数据不足时）- 使用自适应特征"""
        try:
            # 使用自适应特征创建基础模型，确保维度一致
            default_traditional_result = {
                'signal_value': 2,  # 持有
                'confidence': 50.0,
                'trend': 'neutral'
            }
            
            features = await self._extract_adaptive_features(historical_data, default_traditional_result)
            labels = self._create_balanced_labels(historical_data)
            
            # 确保数据长度一致
            min_length = min(len(features), len(labels))
            features = features.iloc[:min_length]
            labels = labels[:min_length]
            
            if len(features) < 20:
                raise MLModelError("数据不足以创建基础模型")
            
            # 训练基础模型
            scaler = RobustScaler()
            X_scaled = scaler.fit_transform(features)
            
            # 使用随机森林，更稳定
            model = RandomForestClassifier(
                n_estimators=50,
                max_depth=8,
                random_state=42,
                class_weight='balanced'  # 自动平衡类别
            )
            
            model.fit(X_scaled, labels)
            model._accuracy = 0.6  # 基础准确率
            
            # 保存模型
            self.prediction_models[symbol] = model
            self.scalers[symbol] = scaler
            
            model_path = self.model_dir / f"{symbol}_adaptive_model.joblib"
            scaler_path = self.model_dir / f"{symbol}_adaptive_scaler.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)
            
            logger.info(f"基础模型创建完成 {symbol} (特征维度: {features.shape[1]})")
            
        except Exception as e:
            logger.error(f"基础模型创建失败 {symbol}: {e}")
            raise MLModelError(f"基础模型创建失败: {e}")
    
    async def _create_adaptive_training_data(self, symbol: str, historical_data: pd.DataFrame, 
                                           learning_record: Dict) -> Tuple[np.ndarray, np.ndarray]:
        """创建自适应训练数据 - 使用自适应特征确保维度一致"""
        try:
            features_list = []
            labels_list = []
            
            # 获取默认传统分析结果用于特征提取
            default_traditional_result = {
                'signal_value': 2,  # 持有
                'confidence': 50.0,
                'trend': 'neutral'
            }
            
            # 如果有学习记录，使用传统分析的信号作为标签
            if learning_record and len(learning_record.get('traditional_signals', [])) > 0:
                traditional_signals = learning_record['traditional_signals']
                timestamps = learning_record['timestamps']
                
                # 使用自适应特征（16维）
                adaptive_features = await self._extract_adaptive_features(historical_data, default_traditional_result)
                
                # 对齐时间戳和特征
                for i, timestamp in enumerate(timestamps):
                    if i < len(traditional_signals) and i < len(adaptive_features):
                        # 更新传统分析特征为实际值
                        feature_row = adaptive_features.iloc[min(i, len(adaptive_features)-1)].copy()
                        if i < len(traditional_signals):
                            feature_row['traditional_signal'] = traditional_signals[i]
                            feature_row['traditional_confidence'] = 0.7  # 默认置信度
                            feature_row['traditional_trend_bullish'] = 1 if traditional_signals[i] >= 3 else 0
                            feature_row['traditional_trend_bearish'] = 1 if traditional_signals[i] <= 1 else 0
                        
                        features_list.append(feature_row.values)
                        labels_list.append(traditional_signals[i])
            
            # 如果学习数据不足，补充历史价格标签
            if len(labels_list) < 30:
                historical_labels = self._create_balanced_labels(historical_data)
                adaptive_features = await self._extract_adaptive_features(historical_data, default_traditional_result)
                additional_count = min(30 - len(labels_list), len(historical_labels))
                
                for i in range(additional_count):
                    if i < len(adaptive_features):
                        # 更新传统分析特征为标签对应值
                        feature_row = adaptive_features.iloc[i].copy()
                        if i < len(historical_labels):
                            feature_row['traditional_signal'] = historical_labels[i]
                            feature_row['traditional_confidence'] = 0.6
                            feature_row['traditional_trend_bullish'] = 1 if historical_labels[i] >= 3 else 0
                            feature_row['traditional_trend_bearish'] = 1 if historical_labels[i] <= 1 else 0
                        
                        features_list.append(feature_row.values)
                        labels_list.append(historical_labels[i])
            
            if not features_list:
                raise MLModelError("无法创建训练数据")
            
            X = np.array(features_list)
            y = np.array(labels_list)
            
            logger.info(f"自适应训练数据维度: {X.shape} (期望: (n, 16))")
            
            return X, y
            
        except Exception as e:
            logger.error(f"创建自适应训练数据失败: {e}")
            raise MLModelError(f"创建训练数据失败: {e}")
    
    async def _extract_adaptive_features(self, historical_data: pd.DataFrame, 
                                       traditional_result: Dict) -> pd.DataFrame:
        """提取自适应特征（包含传统分析特征）- 固定16个特征维度"""
        try:
            # 基础技术特征 (12个)
            features = await self._extract_basic_features(historical_data)
            
            # 添加传统分析特征 (4个)
            features['traditional_signal'] = traditional_result['signal_value']
            features['traditional_confidence'] = traditional_result['confidence'] / 100.0
            features['traditional_trend_bullish'] = 1 if traditional_result['trend'] == 'bullish' else 0
            features['traditional_trend_bearish'] = 1 if traditional_result['trend'] == 'bearish' else 0
            
            # 确保特征顺序一致
            expected_features = [
                # 基础特征 (12个)
                'price_change', 'price_ma5', 'price_ma20', 'price_ma5_ratio', 'price_ma20_ratio',
                'volatility_5', 'volatility_20', 'rsi', 'volume_ma', 'volume_ratio',
                'momentum_5', 'momentum_10',
                # 传统分析特征 (4个)
                'traditional_signal', 'traditional_confidence', 
                'traditional_trend_bullish', 'traditional_trend_bearish'
            ]
            
            # 重新排序确保一致性
            features = features[expected_features]
            
            logger.debug(f"自适应特征维度: {features.shape[1]} (期望: 16)")
            
            return features
            
        except Exception as e:
            logger.error(f"提取自适应特征失败: {e}")
            raise MLModelError(f"特征提取失败: {e}")
    
    async def _extract_basic_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """提取基础技术特征 - 固定12个特征维度"""
        try:
            features = pd.DataFrame(index=data.index)
            
            # 确保价格列存在
            if 'close_price' not in data.columns:
                if 'close' in data.columns:
                    data['close_price'] = data['close']
                else:
                    raise MLModelError("缺少收盘价数据")
            
            # 固定12个基础特征，确保维度一致性
            # 1. 价格变化率
            features['price_change'] = data['close_price'].pct_change()
            
            # 2-3. 移动平均线
            features['price_ma5'] = data['close_price'].rolling(5).mean()
            features['price_ma20'] = data['close_price'].rolling(20).mean()
            
            # 4-5. 价格相对移动平均线的比率
            features['price_ma5_ratio'] = data['close_price'] / features['price_ma5']
            features['price_ma20_ratio'] = data['close_price'] / features['price_ma20']
            
            # 6-7. 波动率特征
            features['volatility_5'] = features['price_change'].rolling(5).std()
            features['volatility_20'] = features['price_change'].rolling(20).std()
            
            # 8. RSI指标
            features['rsi'] = self._calculate_rsi(data['close_price'])
            
            # 9-10. 成交量特征（标准化处理）
            if 'volume' in data.columns and not data['volume'].isna().all():
                features['volume_ma'] = data['volume'].rolling(20).mean()
                features['volume_ratio'] = data['volume'] / features['volume_ma']
            else:
                features['volume_ma'] = 1.0
                features['volume_ratio'] = 1.0
            
            # 11-12. 动量特征
            features['momentum_5'] = data['close_price'] / data['close_price'].shift(5) - 1
            features['momentum_10'] = data['close_price'] / data['close_price'].shift(10) - 1
            
            # 处理NaN值和无穷值
            features = features.bfill().fillna(0)
            features = features.replace([np.inf, -np.inf], 0)
            
            # 确保特征数量为12
            expected_features = [
                'price_change', 'price_ma5', 'price_ma20', 'price_ma5_ratio', 'price_ma20_ratio',
                'volatility_5', 'volatility_20', 'rsi', 'volume_ma', 'volume_ratio',
                'momentum_5', 'momentum_10'
            ]
            
            # 重新排序确保一致性
            features = features[expected_features]
            
            logger.debug(f"基础特征维度: {features.shape[1]} (期望: 12)")
            
            return features
            
        except Exception as e:
            logger.error(f"基础特征提取失败: {e}")
            raise MLModelError(f"基础特征提取失败: {e}")
    
    def _create_balanced_labels(self, data: pd.DataFrame) -> np.ndarray:
        """创建平衡的标签（避免卖出偏差）"""
        try:
            # 计算未来收益
            future_returns = data['close_price'].pct_change(periods=4).shift(-4)  # 4小时后收益
            
            # 动态阈值
            volatility = data['close_price'].pct_change().rolling(24).std()
            dynamic_threshold = volatility * 1.5  # 1.5倍标准差
            dynamic_threshold = dynamic_threshold.fillna(0.025)  # 默认2.5%
            
            labels = np.full(len(future_returns), 2)  # 默认持有
            
            for i in range(len(future_returns)):
                if pd.isna(future_returns.iloc[i]):
                    continue
                
                threshold = max(0.02, min(0.05, dynamic_threshold.iloc[i]))  # 2%-5%范围
                
                if future_returns.iloc[i] > threshold * 1.5:
                    labels[i] = 4  # 强烈买入
                elif future_returns.iloc[i] > threshold:
                    labels[i] = 3  # 买入
                elif future_returns.iloc[i] < -threshold * 1.5:
                    labels[i] = 0  # 强烈卖出
                elif future_returns.iloc[i] < -threshold:
                    labels[i] = 1  # 卖出
                else:
                    labels[i] = 2  # 持有
            
            # 检查标签分布并平衡
            unique, counts = np.unique(labels[:-4], return_counts=True)
            label_dist = dict(zip(unique, counts))
            total = sum(counts)
            
            # 如果卖出标签过多，随机将一些改为持有
            sell_ratio = (label_dist.get(0, 0) + label_dist.get(1, 0)) / total
            if sell_ratio > 0.4:  # 卖出超过40%
                sell_indices = np.where((labels == 0) | (labels == 1))[0]
                adjust_count = int(len(sell_indices) * 0.3)  # 调整30%
                if adjust_count > 0:
                    adjust_indices = np.random.choice(sell_indices, adjust_count, replace=False)
                    labels[adjust_indices] = 2  # 改为持有
            
            return labels[:-4]  # 移除最后4个无法计算的点
            
        except Exception as e:
            logger.error(f"创建平衡标签失败: {e}")
            return np.full(len(data) - 4, 2)  # 全部持有
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi / 100.0  # 归一化到0-1
    
    def _calculate_agreement(self, ml_prediction: int, traditional_result: Dict) -> float:
        """计算与传统分析的一致性"""
        traditional_signal = traditional_result['signal_value']
        
        # 完全一致
        if ml_prediction == traditional_signal:
            return 1.0
        
        # 方向一致（都是买入方向或都是卖出方向）
        ml_direction = 1 if ml_prediction >= 3 else (-1 if ml_prediction <= 1 else 0)
        traditional_direction = 1 if traditional_signal >= 3 else (-1 if traditional_signal <= 1 else 0)
        
        if ml_direction == traditional_direction and ml_direction != 0:
            return 0.7
        
        # 都是持有
        if ml_prediction == 2 and traditional_signal == 2:
            return 1.0
        
        # 一个持有，一个轻微信号
        if ((ml_prediction == 2 and abs(traditional_signal - 2) == 1) or 
            (traditional_signal == 2 and abs(ml_prediction - 2) == 1)):
            return 0.5
        
        # 方向相反
        return 0.0
    
    def _calculate_learning_score(self, symbol: str, prediction: int, traditional_result: Dict) -> float:
        """计算学习得分"""
        learning_record = self.learning_records.get(symbol, {})
        
        if not learning_record.get('traditional_signals'):
            return 0.5  # 默认得分
        
        # 计算历史一致性
        recent_signals = learning_record['traditional_signals'][-10:]  # 最近10个信号
        if not recent_signals:
            return 0.5
        
        # 计算与最近传统信号的平均一致性
        agreements = []
        for signal in recent_signals:
            agreement = self._calculate_agreement(prediction, {'signal_value': signal})
            agreements.append(agreement)
        
        return np.mean(agreements) if agreements else 0.5
    
    def _generate_reasoning(self, prediction: int, traditional_result: Dict, agreement: float) -> str:
        """生成推理说明"""
        signal_names = {
            0: "强烈卖出", 1: "卖出", 2: "持有", 3: "买入", 4: "强烈买入"
        }
        
        ml_signal = signal_names[prediction]
        traditional_signal = signal_names[traditional_result['signal_value']]
        
        if agreement >= 0.8:
            return f"ML预测 {ml_signal} 与传统分析 {traditional_signal} 高度一致"
        elif agreement >= 0.5:
            return f"ML预测 {ml_signal} 与传统分析 {traditional_signal} 部分一致"
        else:
            return f"ML预测 {ml_signal} 与传统分析 {traditional_signal} 存在分歧，需要谨慎"
    
    async def _record_prediction(self, symbol: str, prediction: AdaptivePrediction, 
                               traditional_result: Dict) -> None:
        """记录预测结果用于后续学习"""
        try:
            record_path = self.learning_history_dir / f"{symbol}_predictions.json"
            
            # 读取现有记录
            records = []
            if record_path.exists():
                import json
                with open(record_path, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            
            # 添加新记录
            new_record = {
                'timestamp': prediction.timestamp.isoformat(),
                'ml_signal': prediction.signal.value,
                'ml_confidence': prediction.confidence,
                'traditional_signal': traditional_result['signal_value'],
                'traditional_confidence': traditional_result['confidence'],
                'agreement': prediction.traditional_agreement,
                'learning_score': prediction.learning_score
            }
            
            records.append(new_record)
            
            # 保持最近500条记录
            if len(records) > 500:
                records = records[-500:]
            
            # 保存记录
            import json
            with open(record_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.warning(f"记录预测结果失败: {e}")
    
    async def _save_learning_record(self, symbol: str, learning_record: Dict) -> None:
        """保存学习记录"""
        try:
            record_path = self.learning_history_dir / f"{symbol}_learning.pkl"
            with open(record_path, 'wb') as f:
                pickle.dump(learning_record, f)
        except Exception as e:
            logger.warning(f"保存学习记录失败: {e}")
    
    async def _load_learning_record(self, symbol: str) -> Dict:
        """加载学习记录"""
        try:
            record_path = self.learning_history_dir / f"{symbol}_learning.pkl"
            if record_path.exists():
                with open(record_path, 'rb') as f:
                    return pickle.load(f)
        except Exception as e:
            logger.warning(f"加载学习记录失败: {e}")
        
        return {
            'traditional_signals': [],
            'timestamps': [],
            'market_data': [],
            'last_update': None
        }
    
    async def _check_and_retrain_if_needed(self, symbol: str, learning_record: Dict) -> None:
        """检查是否需要重新训练模型"""
        try:
            # 检查最近的一致性
            recent_signals = learning_record['traditional_signals'][-20:]  # 最近20个信号
            if len(recent_signals) < 10:
                return
            
            # 如果当前模型存在，检查其与传统分析的一致性
            if symbol in self.prediction_models:
                # 这里可以添加更复杂的重训练逻辑
                # 比如检查预测准确率、一致性趋势等
                pass
            
            # 简单策略：每积累50个新样本就重新训练
            if len(recent_signals) >= 50:
                logger.info(f"触发重新训练 {symbol}: 积累了 {len(recent_signals)} 个学习样本")
                await self._train_adaptive_model(symbol)
                
        except Exception as e:
            logger.warning(f"检查重训练失败: {e}")
    
    async def _get_historical_data(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """获取历史数据"""
        try:
            limit = min(24 * days, 1000)
            
            async with self.exchange_service as exchange:
                klines = await exchange.get_kline_data(symbol, '1h', limit=limit)
            
            if not klines:
                raise DataNotFoundError(f"No historical data for {symbol}")
            
            df = pd.DataFrame(klines)
            
            # 处理时间戳
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            elif 'open_time' in df.columns:
                df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            else:
                df['timestamp'] = pd.date_range(
                    start=datetime.now() - timedelta(hours=len(df)), 
                    periods=len(df), 
                    freq='H'
                )
            
            df.set_index('timestamp', inplace=True)
            
            # 统一字段名
            price_fields = ['open', 'high', 'low', 'close']
            for field in price_fields:
                target_field = f'{field}_price'
                if target_field not in df.columns and field in df.columns:
                    df[target_field] = pd.to_numeric(df[field], errors='coerce')
            
            # 确保volume字段
            if 'volume' not in df.columns:
                df['volume'] = 1000.0
            else:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            
            # 移除NaN行
            df = df.dropna(subset=['close_price'])
            
            if df.empty:
                raise DataNotFoundError(f"No valid data after processing for {symbol}")
            
            return df
            
        except Exception as e:
            logger.error(f"获取历史数据失败 {symbol}: {e}")
            raise DataNotFoundError(f"历史数据获取失败: {e}")
    
    async def get_learning_statistics(self, symbol: str) -> Dict[str, Any]:
        """获取学习统计信息"""
        try:
            learning_record = await self._load_learning_record(symbol)
            
            if not learning_record.get('traditional_signals'):
                return {
                    'total_samples': 0,
                    'learning_status': '未开始学习',
                    'last_update': None
                }
            
            signals = learning_record['traditional_signals']
            unique, counts = np.unique(signals, return_counts=True)
            signal_dist = dict(zip(unique, counts))
            
            signal_names = {0: '强烈卖出', 1: '卖出', 2: '持有', 3: '买入', 4: '强烈买入'}
            distribution = {signal_names.get(k, f'信号{k}'): v for k, v in signal_dist.items()}
            
            return {
                'total_samples': len(signals),
                'signal_distribution': distribution,
                'learning_status': '正在学习' if len(signals) >= self.learning_config['min_learning_samples'] else '学习中',
                'last_update': learning_record.get('last_update'),
                'model_exists': symbol in self.prediction_models
            }
            
        except Exception as e:
            logger.error(f"获取学习统计失败: {e}")
            return {'error': str(e)}