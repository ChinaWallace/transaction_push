# -*- coding: utf-8 -*-
"""
Kronos预测服务
提供基于Kronos模型的价格预测功能
"""

import asyncio
import sys
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import pandas as pd
import numpy as np

# 添加Kronos模型路径
sys.path.append(os.path.join(os.path.dirname(__file__), '../../Kronos-master'))

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

# 全局服务实例
_kronos_service = None


@dataclass
class KronosPrediction:
    """Kronos预测结果"""
    symbol: str
    timestamp: datetime
    current_price: float
    predicted_price: float
    price_change_pct: float
    confidence: float
    prediction_horizon: int  # 预测时间范围（小时）
    raw_prediction: Optional[Dict] = None


class KronosPredictionService:
    """Kronos预测服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # Kronos配置
        self.kronos_config = self.settings.kronos_config
        self.enable_kronos = self.kronos_config.get('enable_kronos_prediction', True)
        
        # 模型相关
        self.model = None
        self.tokenizer = None
        self.predictor = None
        self.model_loaded = False
        
        # 预测缓存
        self.prediction_cache = {}
        self.cache_ttl = 300  # 5分钟缓存
        
        # 预测配置
        self.prediction_timeout = self.kronos_config.get('prediction_timeout', 120)  # 2分钟超时
        self.max_retries = self.kronos_config.get('max_retries', 2)  # 最大重试次数
        
    async def initialize(self):
        """初始化Kronos模型"""
        if not self.enable_kronos:
            self.logger.info("Kronos预测功能已禁用")
            return False
            
        try:
            self.logger.info("开始初始化Kronos模型...")
            
            # 动态导入Kronos模型
            from model import Kronos, KronosTokenizer, KronosPredictor
            
            # 获取模型配置
            model_name = self.kronos_config.get('model_name', 'NeoQuasar/Kronos-small')
            tokenizer_name = self.kronos_config.get('tokenizer_name', 'NeoQuasar/Kronos-Tokenizer-base')
            device = self.kronos_config.get('device', 'cpu')
            max_context = self.kronos_config.get('max_context', 200)  # 减少上下文长度避免内存问题
            
            # 加载tokenizer和模型
            self.logger.info(f"初始化Kronos tokenizer...")
            # KronosTokenizer 参数配置
            tokenizer_params = {
                'd_in': 6,  # 输入维度 (OHLCV + amount)
                'd_model': 256,
                'n_heads': 8,
                'ff_dim': 1024,
                'n_enc_layers': 4,
                'n_dec_layers': 4,
                'ffn_dropout_p': 0.1,
                'attn_dropout_p': 0.1,
                'resid_dropout_p': 0.1,
                's1_bits': 8,
                's2_bits': 8,
                'beta': 0.25,
                'gamma0': 1.0,
                'gamma': 0.99,
                'zeta': 1e-4,
                'group_size': 1
            }
            self.tokenizer = KronosTokenizer(**tokenizer_params)
            
            self.logger.info(f"初始化Kronos模型...")
            # Kronos 模型参数配置
            model_params = {
                's1_bits': 8,
                's2_bits': 8,
                'n_layers': 6,  # 必需参数
                'd_model': 256,
                'n_heads': 8,
                'ff_dim': 1024,
                'ffn_dropout_p': 0.1,
                'attn_dropout_p': 0.1,
                'resid_dropout_p': 0.1,
                'token_dropout_p': 0.1,  # 必需参数
                'learn_te': True  # 必需参数
            }
            self.model = Kronos(**model_params)
            
            # 初始化预测器
            self.predictor = KronosPredictor(
                model=self.model,
                tokenizer=self.tokenizer,
                device=device,
                max_context=max_context
            )
            
            self.model_loaded = True
            self.logger.info("✅ Kronos模型初始化成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Kronos模型初始化失败: {e}")
            self.model_loaded = False
            return False
    
    async def predict_symbol(
        self,
        symbol: str,
        lookback_periods: int = 100,
        prediction_horizon: int = 12,
        force_update: bool = False
    ) -> Optional[Dict[str, Any]]:
        """预测指定交易对的价格变化"""
        try:
            # 获取历史数据
            from app.services.unified_data_service import get_unified_data_service, DataRequest
            data_service = await get_unified_data_service()
            
            # 创建数据请求
            request = DataRequest(
                symbol=symbol,
                timeframe='1h',
                limit=lookback_periods,
                use_cache=True
            )
            
            # 获取K线数据
            result = await data_service.get_kline_data(request)
            historical_data = result.data
            
            if historical_data is None or len(historical_data) < 50:
                self.logger.warning(f"历史数据不足，无法进行Kronos预测: {symbol}")
                return None
            
            # 执行预测
            prediction = await self.get_prediction(symbol, historical_data, force_update)
            
            if prediction is None:
                return None
            
            # 返回标准格式
            return {
                'symbol': prediction.symbol,
                'current_price': prediction.current_price,
                'predicted_price': prediction.predicted_price,
                'price_change_pct': prediction.price_change_pct,
                'confidence': prediction.confidence,
                'prediction_horizon': prediction.prediction_horizon,
                'predictions': [
                    {
                        'timestamp': prediction.timestamp,
                        'close': prediction.predicted_price,
                        'confidence': prediction.confidence
                    }
                ]
            }
            
        except Exception as e:
            self.logger.error(f"预测{symbol}失败: {e}")
            return None

    async def get_prediction(
        self,
        symbol: str,
        historical_data: pd.DataFrame,
        force_update: bool = False
    ) -> Optional[KronosPrediction]:
        """获取Kronos价格预测"""
        try:
            # 检查模型是否已加载
            if not self.model_loaded:
                if not await self.initialize():
                    return None
            
            # 检查缓存
            cache_key = f"{symbol}_{len(historical_data)}"
            if not force_update and cache_key in self.prediction_cache:
                cached_result, cache_time = self.prediction_cache[cache_key]
                if (datetime.now() - cache_time).seconds < self.cache_ttl:
                    self.logger.debug(f"使用缓存的Kronos预测: {symbol}")
                    return cached_result
            
            # 数据预处理
            processed_data = self._preprocess_data(historical_data)
            if processed_data is None or len(processed_data) < 50:
                self.logger.warning(f"历史数据不足，无法进行Kronos预测: {symbol}")
                return None
            
            # 执行预测
            prediction_result = await self._run_prediction(symbol, processed_data)
            
            # 缓存结果
            if prediction_result:
                self.prediction_cache[cache_key] = (prediction_result, datetime.now())
            
            return prediction_result
            
        except Exception as e:
            self.logger.error(f"获取{symbol}的Kronos预测失败: {e}")
            return None
    
    def _preprocess_data(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """预处理历史数据"""
        try:
            # 确保必要的列存在
            required_columns = ['open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_columns):
                self.logger.error(f"历史数据缺少必要列: {required_columns}")
                return None
            
            # 创建副本避免修改原数据
            processed_df = df.copy()
            
            # 确保数据类型正确
            for col in required_columns:
                processed_df[col] = pd.to_numeric(processed_df[col], errors='coerce')
            
            # 处理volume列（可选）
            if 'volume' in processed_df.columns:
                processed_df['volume'] = pd.to_numeric(processed_df['volume'], errors='coerce')
                processed_df['volume'] = processed_df['volume'].fillna(0)
            else:
                processed_df['volume'] = 0
            
            # 处理amount列（可选）
            if 'amount' not in processed_df.columns:
                processed_df['amount'] = processed_df['close'] * processed_df['volume']
            else:
                processed_df['amount'] = pd.to_numeric(processed_df['amount'], errors='coerce')
                processed_df['amount'] = processed_df['amount'].fillna(0)
            
            # 删除包含NaN的行
            processed_df = processed_df.dropna(subset=required_columns)
            
            # 确保数据质量
            if len(processed_df) < 20:
                self.logger.error(f"预处理后数据不足: {len(processed_df)} < 20")
                return None
            
            # 按时间排序（如果有时间索引）
            if isinstance(processed_df.index, pd.DatetimeIndex):
                processed_df = processed_df.sort_index()
            
            # 限制数据长度（Kronos模型的上下文限制）
            max_length = self.kronos_config.get('max_context', 200)  # 减少上下文长度避免内存问题
            if len(processed_df) > max_length:
                processed_df = processed_df.tail(max_length)
            
            # 确保数据连续性（检查是否有异常值）
            for col in required_columns:
                # 移除极端异常值（超过3个标准差）
                mean_val = processed_df[col].mean()
                std_val = processed_df[col].std()
                if std_val > 0:
                    lower_bound = mean_val - 3 * std_val
                    upper_bound = mean_val + 3 * std_val
                    processed_df = processed_df[
                        (processed_df[col] >= lower_bound) & 
                        (processed_df[col] <= upper_bound)
                    ]
            
            # 最终检查
            if len(processed_df) < 20:
                self.logger.error(f"异常值过滤后数据不足: {len(processed_df)} < 20")
                return None
            
            self.logger.debug(f"预处理完成，数据长度: {len(processed_df)}")
            return processed_df
            
        except Exception as e:
            self.logger.error(f"数据预处理失败: {e}")
            return None
    
    async def _run_prediction(
        self,
        symbol: str,
        historical_data: pd.DataFrame
    ) -> Optional[KronosPrediction]:
        """执行Kronos预测"""
        try:
            # 预测配置 - 使用更保守的设置
            pred_len = min(self.kronos_config.get('prediction_length', 12), 24)  # 最多预测24小时，默认12小时
            temperature = self.kronos_config.get('temperature', 0.8)  # 降低温度提高稳定性
            top_p = self.kronos_config.get('top_p', 0.95)  # 提高top_p提高稳定性
            sample_count = self.kronos_config.get('sample_count', 1)  # 保持单样本避免内存问题
            
            # 准备时间戳
            if isinstance(historical_data.index, pd.DatetimeIndex):
                x_timestamp = historical_data.index
                # 生成未来时间戳（假设1小时间隔）
                last_time = x_timestamp[-1]
                y_timestamp = pd.date_range(
                    start=last_time + timedelta(hours=1),
                    periods=pred_len,
                    freq='h'
                )
            else:
                # 如果没有时间索引，创建虚拟时间戳
                now = datetime.now()
                x_timestamp = pd.date_range(
                    end=now,
                    periods=len(historical_data),
                    freq='h'
                )
                y_timestamp = pd.date_range(
                    start=now + timedelta(hours=1),
                    periods=pred_len,
                    freq='h'
                )
            
            # 执行预测
            self.logger.debug(f"开始Kronos预测: {symbol}, 预测长度: {pred_len}")
            
            # 在线程池中运行预测（避免阻塞），添加超时控制
            loop = asyncio.get_event_loop()
            try:
                pred_df = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._sync_predict,
                        historical_data,
                        x_timestamp,
                        y_timestamp,
                        pred_len,
                        temperature,
                        top_p,
                        sample_count
                    ),
                    timeout=self.prediction_timeout
                )
            except asyncio.TimeoutError:
                self.logger.error(f"Kronos预测超时 ({self.prediction_timeout}秒): {symbol}")
                return None
            
            if pred_df is None or pred_df.empty:
                self.logger.warning(f"Kronos预测返回空结果: {symbol}")
                return None
            
            # 解析预测结果
            current_price = float(historical_data['close'].iloc[-1])
            predicted_price = float(pred_df['close'].iloc[-1])  # 取最后一个预测价格
            price_change_pct = (predicted_price - current_price) / current_price
            
            # 计算置信度（基于预测的稳定性）
            confidence = self._calculate_confidence(pred_df, historical_data)
            
            prediction = KronosPrediction(
                symbol=symbol,
                timestamp=datetime.now(),
                current_price=current_price,
                predicted_price=predicted_price,
                price_change_pct=price_change_pct,
                confidence=confidence,
                prediction_horizon=pred_len,
                raw_prediction={
                    'prediction_df': pred_df.to_dict(),
                    'prediction_length': pred_len,
                    'model_config': {
                        'temperature': temperature,
                        'top_p': top_p,
                        'sample_count': sample_count
                    }
                }
            )
            
            self.logger.info(
                f"Kronos预测完成 - {symbol}: "
                f"当前价格 {current_price:.4f} -> 预测价格 {predicted_price:.4f} "
                f"({price_change_pct*100:+.2f}%, 置信度: {confidence:.2f})"
            )
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"执行Kronos预测失败: {e}")
            return None
    
    def _sync_predict(
        self,
        df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        temperature: float,
        top_p: float,
        sample_count: int
    ) -> Optional[pd.DataFrame]:
        """同步预测方法（在线程池中执行）"""
        try:
            # 添加输入验证
            if df is None or len(df) == 0:
                self.logger.error("输入数据为空")
                return None
                
            if x_timestamp is None or y_timestamp is None:
                self.logger.error("时间戳数据为空")
                return None
            
            # 验证数据长度匹配
            if len(df) != len(x_timestamp):
                self.logger.error(f"数据长度不匹配: df={len(df)}, x_timestamp={len(x_timestamp)}")
                return None
                
            # 限制预测长度以避免内存问题
            max_pred_len = min(pred_len, len(y_timestamp), 50)  # 最多预测50步
            if max_pred_len != pred_len:
                self.logger.warning(f"预测长度从 {pred_len} 调整为 {max_pred_len}")
                pred_len = max_pred_len
                y_timestamp = y_timestamp[:pred_len]
            
            # 添加超时和重试机制
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    self.logger.debug(f"开始预测尝试 {attempt + 1}/{max_retries}")
                    
                    # 确保数据类型正确
                    df_clean = df.copy()
                    
                    # 验证必要列存在
                    required_cols = ['open', 'high', 'low', 'close']
                    if not all(col in df_clean.columns for col in required_cols):
                        self.logger.error(f"缺少必要列: {required_cols}")
                        return None
                    
                    # 确保数值类型
                    for col in required_cols + ['volume', 'amount']:
                        if col in df_clean.columns:
                            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
                    
                    # 删除NaN行
                    df_clean = df_clean.dropna(subset=required_cols)
                    if len(df_clean) < 10:
                        self.logger.error("清理后数据不足")
                        return None
                    
                    # 调整时间戳长度以匹配清理后的数据
                    if len(df_clean) != len(x_timestamp):
                        x_timestamp_clean = x_timestamp[-len(df_clean):]
                    else:
                        x_timestamp_clean = x_timestamp
                    
                    result = self.predictor.predict(
                        df=df_clean,
                        x_timestamp=x_timestamp_clean,
                        y_timestamp=y_timestamp,
                        pred_len=pred_len,
                        T=temperature,
                        top_p=top_p,
                        sample_count=sample_count,
                        verbose=True  # 显示进度条
                    )
                    
                    # 验证结果
                    if result is None:
                        self.logger.warning(f"预测尝试 {attempt + 1} 返回 None")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    # 检查结果类型和形状
                    if not isinstance(result, pd.DataFrame):
                        self.logger.error(f"预测结果类型错误: {type(result)}")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    if len(result) == 0:
                        self.logger.warning(f"预测尝试 {attempt + 1} 返回空结果")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    # 验证预测长度是否正确
                    if len(result) != pred_len:
                        self.logger.warning(f"预测长度不匹配: 期望 {pred_len}, 实际 {len(result)}")
                        # 截取或填充到正确长度
                        if len(result) > pred_len:
                            result = result.iloc[:pred_len]
                        elif len(result) < pred_len:
                            # 用最后一行填充
                            last_row = result.iloc[-1:].copy()
                            for _ in range(pred_len - len(result)):
                                result = pd.concat([result, last_row], ignore_index=True)
                    
                    # 确保时间戳正确
                    if len(result) == len(y_timestamp):
                        result.index = y_timestamp
                    
                    self.logger.debug(f"预测成功，结果长度: {len(result)}")
                    return result
                    
                except Exception as e:
                    self.logger.error(f"预测尝试 {attempt + 1} 失败: {e}")
                    if attempt < max_retries - 1:
                        # 短暂等待后重试
                        import time
                        time.sleep(1)
                        continue
                    raise e
            
            return None
            
        except Exception as e:
            self.logger.error(f"同步预测执行失败: {e}")
            return None
    
    def _calculate_confidence(
        self,
        pred_df: pd.DataFrame,
        historical_data: pd.DataFrame
    ) -> float:
        """计算预测置信度"""
        try:
            # 基于多个因素计算置信度
            confidence_factors = []
            
            # 1. 预测价格的稳定性（波动越小，置信度越高）
            if len(pred_df) > 1:
                price_volatility = pred_df['close'].std() / pred_df['close'].mean()
                volatility_confidence = max(0, 1 - price_volatility * 10)  # 波动率转置信度
                confidence_factors.append(volatility_confidence)
            
            # 2. 预测趋势的一致性
            if len(pred_df) > 2:
                price_changes = pred_df['close'].pct_change().dropna()
                trend_consistency = 1 - abs(price_changes.std())  # 变化率的标准差越小越好
                confidence_factors.append(max(0, min(1, trend_consistency)))
            
            # 3. 历史数据质量（数据越多越稳定，置信度越高）
            data_quality = min(1.0, len(historical_data) / 200)  # 200个数据点为满分
            confidence_factors.append(data_quality)
            
            # 4. 预测幅度合理性（过大的预测变化降低置信度）
            current_price = historical_data['close'].iloc[-1]
            predicted_price = pred_df['close'].iloc[-1]
            price_change = abs((predicted_price - current_price) / current_price)
            
            if price_change > 0.2:  # 超过20%变化
                magnitude_confidence = 0.3
            elif price_change > 0.1:  # 超过10%变化
                magnitude_confidence = 0.6
            elif price_change > 0.05:  # 超过5%变化
                magnitude_confidence = 0.8
            else:
                magnitude_confidence = 1.0
            
            confidence_factors.append(magnitude_confidence)
            
            # 综合置信度（加权平均）
            if confidence_factors:
                final_confidence = np.mean(confidence_factors)
                # 确保置信度在合理范围内
                return max(0.1, min(0.95, final_confidence))
            else:
                return 0.5  # 默认中等置信度
                
        except Exception as e:
            self.logger.error(f"计算置信度失败: {e}")
            return 0.5
    
    async def batch_predict(
        self,
        symbols_data: Dict[str, pd.DataFrame],
        force_update: bool = False
    ) -> Dict[str, Optional[KronosPrediction]]:
        """批量预测多个交易对"""
        results = {}
        
        for symbol, data in symbols_data.items():
            try:
                prediction = await self.get_prediction(symbol, data, force_update)
                results[symbol] = prediction
            except Exception as e:
                self.logger.error(f"批量预测{symbol}失败: {e}")
                results[symbol] = None
        
        return results
    
    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            'model_loaded': self.model_loaded,
            'enable_kronos': self.enable_kronos,
            'model_config': self.kronos_config,
            'cache_size': len(self.prediction_cache)
        }
    
    def clear_cache(self):
        """清空预测缓存"""
        self.prediction_cache.clear()
        self.logger.info("Kronos预测缓存已清空")


async def get_kronos_service() -> Optional[KronosPredictionService]:
    """获取Kronos预测服务实例"""
    global _kronos_service
    
    if _kronos_service is None:
        _kronos_service = KronosPredictionService()
        
        # 尝试初始化
        if not await _kronos_service.initialize():
            _kronos_service = None
            return None
    
    return _kronos_service