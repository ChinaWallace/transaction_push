# -*- coding: utf-8 -*-
"""
回退预测服务
Fallback Prediction Service - 基于简单技术分析的预测回退机制
Provides simple technical analysis-based predictions as fallback when Kronos is unavailable
"""

from typing import Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass
import pandas as pd
import numpy as np
from enum import Enum

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TechnicalIndicator(Enum):
    """技术指标枚举"""
    SMA = "简单移动平均"
    EMA = "指数移动平均"
    RSI = "相对强弱指数"
    MACD = "移动平均收敛发散"
    BOLLINGER = "布林带"


@dataclass
class FallbackPrediction:
    """回退预测结果"""
    symbol: str
    timestamp: datetime
    current_price: float
    predicted_price: float
    price_change_pct: float
    confidence: float
    prediction_horizon: int
    method: str
    indicators: Dict[str, float]
    raw_prediction: Optional[Dict] = None
    
    # 智能通知服务需要的额外属性
    signal: str = "hold"
    volatility: float = 0.0
    trend_direction: str = "sideways"
    
    def __post_init__(self):
        """初始化后处理，根据价格变化计算信号和趋势"""
        if self.price_change_pct > 0.03:  # 3%以上上涨
            self.signal = "strong_buy"
            self.trend_direction = "bullish"
        elif self.price_change_pct > 0.01:  # 1%以上上涨
            self.signal = "buy"
            self.trend_direction = "bullish"
        elif self.price_change_pct < -0.03:  # 3%以上下跌
            self.signal = "strong_sell"
            self.trend_direction = "bearish"
        elif self.price_change_pct < -0.01:  # 1%以上下跌
            self.signal = "sell"
            self.trend_direction = "bearish"
        else:
            self.signal = "hold"
            self.trend_direction = "sideways"
        
        # 根据价格变化幅度估算波动率
        self.volatility = abs(self.price_change_pct) * 0.8


class FallbackPredictionService:
    """
    回退预测服务
    Fallback prediction service using technical analysis
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 预测缓存
        self.prediction_cache = {}
        self.cache_ttl = 180  # 3分钟缓存（比Kronos短）
        
        # 技术指标配置
        self.indicator_config = {
            'sma_short_period': 5,
            'sma_long_period': 20,
            'ema_period': 12,
            'rsi_period': 14,
            'bollinger_period': 20,
            'bollinger_std': 2.0
        }
        
        self.initialized = False
    
    async def initialize(self):
        """
        初始化回退预测服务
        Initialize fallback prediction service
        """
        try:
            self.logger.info("🔄 初始化回退预测服务...")
            
            # 验证配置
            self._validate_config()
            
            self.initialized = True
            self.logger.info("✅ 回退预测服务初始化成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 回退预测服务初始化失败: {e}")
            return False
    
    def _validate_config(self):
        """验证配置参数"""
        if self.indicator_config['sma_short_period'] >= self.indicator_config['sma_long_period']:
            self.logger.warning("⚠️ 短期SMA周期应小于长期SMA周期，使用默认值")
            self.indicator_config['sma_short_period'] = 5
            self.indicator_config['sma_long_period'] = 20
        
        if self.indicator_config['rsi_period'] < 2:
            self.logger.warning("⚠️ RSI周期过小，使用默认值14")
            self.indicator_config['rsi_period'] = 14
    
    async def predict(
        self,
        symbol: str,
        historical_data: pd.DataFrame,
        prediction_horizon: int = 12
    ) -> Optional[FallbackPrediction]:
        """
        执行回退预测
        Execute fallback prediction using technical analysis
        """
        try:
            if not self.initialized:
                await self.initialize()
            
            # 检查缓存
            cache_key = f"fallback_{symbol}_{len(historical_data)}"
            if cache_key in self.prediction_cache:
                cached_result, cache_time = self.prediction_cache[cache_key]
                if (datetime.now() - cache_time).seconds < self.cache_ttl:
                    self.logger.debug(f"🔍 使用缓存的回退预测: {symbol}")
                    return cached_result
            
            # 数据验证
            if historical_data is None or len(historical_data) < 20:
                self.logger.warning(f"⚠️ 历史数据不足，无法进行回退预测: {symbol}")
                return None
            
            # 计算技术指标
            indicators = await self._calculate_indicators(historical_data)
            
            # 执行预测
            prediction = await self._generate_prediction(
                symbol, historical_data, indicators, prediction_horizon
            )
            
            # 缓存结果
            if prediction:
                self.prediction_cache[cache_key] = (prediction, datetime.now())
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"❌ 回退预测失败 {symbol}: {e}")
            return None
    
    async def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        计算技术指标
        Calculate technical indicators
        """
        try:
            indicators = {}
            close_prices = df['close'].values
            df['high'].values
            df['low'].values
            
            # 简单移动平均线
            sma_short = np.mean(close_prices[-self.indicator_config['sma_short_period']:])
            sma_long = np.mean(close_prices[-self.indicator_config['sma_long_period']:])
            indicators['sma_short'] = sma_short
            indicators['sma_long'] = sma_long
            indicators['sma_ratio'] = sma_short / sma_long if sma_long > 0 else 1.0
            
            # 指数移动平均线
            ema_period = self.indicator_config['ema_period']
            if len(close_prices) >= ema_period:
                ema = self._calculate_ema(close_prices, ema_period)
                indicators['ema'] = ema
                indicators['price_ema_ratio'] = close_prices[-1] / ema if ema > 0 else 1.0
            
            # RSI
            rsi_period = self.indicator_config['rsi_period']
            if len(close_prices) >= rsi_period + 1:
                rsi = self._calculate_rsi(close_prices, rsi_period)
                indicators['rsi'] = rsi
            
            # 布林带
            bollinger_period = self.indicator_config['bollinger_period']
            if len(close_prices) >= bollinger_period:
                bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(
                    close_prices, bollinger_period, self.indicator_config['bollinger_std']
                )
                indicators['bb_upper'] = bb_upper
                indicators['bb_middle'] = bb_middle
                indicators['bb_lower'] = bb_lower
                indicators['bb_position'] = (close_prices[-1] - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
            
            # 价格动量
            if len(close_prices) >= 5:
                momentum_5 = (close_prices[-1] - close_prices[-5]) / close_prices[-5]
                indicators['momentum_5'] = momentum_5
            
            if len(close_prices) >= 10:
                momentum_10 = (close_prices[-1] - close_prices[-10]) / close_prices[-10]
                indicators['momentum_10'] = momentum_10
            
            # 波动率
            if len(close_prices) >= 20:
                returns = np.diff(close_prices[-20:]) / close_prices[-20:-1]
                volatility = np.std(returns)
                indicators['volatility'] = volatility
            
            return indicators
            
        except Exception as e:
            self.logger.error(f"❌ 计算技术指标失败: {e}")
            return {}
    
    def _calculate_ema(self, prices: np.ndarray, period: int) -> float:
        """计算指数移动平均线"""
        alpha = 2.0 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema
    
    def _calculate_rsi(self, prices: np.ndarray, period: int) -> float:
        """计算RSI"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int, std_dev: float) -> tuple:
        """计算布林带"""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        
        return upper, sma, lower
    
    async def _generate_prediction(
        self,
        symbol: str,
        historical_data: pd.DataFrame,
        indicators: Dict[str, float],
        prediction_horizon: int
    ) -> Optional[FallbackPrediction]:
        """
        基于技术指标生成预测
        Generate prediction based on technical indicators
        """
        try:
            current_price = float(historical_data['close'].iloc[-1])
            
            # 多因子预测模型
            prediction_factors = []
            confidence_factors = []
            
            # 1. 移动平均线信号
            if 'sma_ratio' in indicators:
                sma_signal = (indicators['sma_ratio'] - 1.0) * 2  # 转换为-2到2的信号
                prediction_factors.append(sma_signal * 0.3)  # 权重30%
                confidence_factors.append(min(1.0, abs(sma_signal)))
            
            # 2. EMA信号
            if 'price_ema_ratio' in indicators:
                ema_signal = (indicators['price_ema_ratio'] - 1.0) * 3
                prediction_factors.append(ema_signal * 0.2)  # 权重20%
                confidence_factors.append(min(1.0, abs(ema_signal)))
            
            # 3. RSI信号
            if 'rsi' in indicators:
                rsi = indicators['rsi']
                if rsi > 70:
                    rsi_signal = -0.5  # 超买，看跌
                elif rsi < 30:
                    rsi_signal = 0.5   # 超卖，看涨
                else:
                    rsi_signal = (50 - rsi) / 100  # 中性区域
                prediction_factors.append(rsi_signal * 0.25)  # 权重25%
                confidence_factors.append(0.8 if rsi > 70 or rsi < 30 else 0.4)
            
            # 4. 布林带信号
            if 'bb_position' in indicators:
                bb_pos = indicators['bb_position']
                if bb_pos > 0.8:
                    bb_signal = -0.3  # 接近上轨，看跌
                elif bb_pos < 0.2:
                    bb_signal = 0.3   # 接近下轨，看涨
                else:
                    bb_signal = (0.5 - bb_pos) * 0.4  # 中性区域
                prediction_factors.append(bb_signal * 0.15)  # 权重15%
                confidence_factors.append(0.7 if bb_pos > 0.8 or bb_pos < 0.2 else 0.3)
            
            # 5. 动量信号
            if 'momentum_5' in indicators and 'momentum_10' in indicators:
                momentum_avg = (indicators['momentum_5'] + indicators['momentum_10']) / 2
                momentum_signal = np.tanh(momentum_avg * 10)  # 限制在-1到1之间
                prediction_factors.append(momentum_signal * 0.1)  # 权重10%
                confidence_factors.append(min(1.0, abs(momentum_avg) * 5))
            
            # 综合预测
            if prediction_factors:
                predicted_change = np.sum(prediction_factors)
                # 限制预测幅度
                predicted_change = np.clip(predicted_change, -0.05, 0.05)  # 最大5%变化
            else:
                predicted_change = 0.0
            
            # 计算置信度
            if confidence_factors:
                base_confidence = np.mean(confidence_factors)
                # 根据数据质量调整置信度
                data_quality = min(1.0, len(historical_data) / 100)
                final_confidence = base_confidence * data_quality * 0.8  # 回退预测置信度较低
                final_confidence = max(0.2, min(0.8, final_confidence))
            else:
                final_confidence = 0.4
            
            predicted_price = current_price * (1 + predicted_change)
            
            # 创建预测结果
            prediction = FallbackPrediction(
                symbol=symbol,
                timestamp=datetime.now(),
                current_price=current_price,
                predicted_price=predicted_price,
                price_change_pct=predicted_change,
                confidence=final_confidence,
                prediction_horizon=prediction_horizon,
                method="multi_factor_technical_analysis",
                indicators=indicators,
                raw_prediction={
                    'prediction_factors': prediction_factors,
                    'confidence_factors': confidence_factors,
                    'factor_weights': {
                        'sma': 0.3,
                        'ema': 0.2,
                        'rsi': 0.25,
                        'bollinger': 0.15,
                        'momentum': 0.1
                    }
                }
            )
            
            self.logger.info(
                f"📊 回退预测完成 - {symbol}: "
                f"当前价格 {current_price:.4f} -> 预测价格 {predicted_price:.4f} "
                f"({predicted_change*100:+.2f}%, 置信度: {final_confidence:.2f})"
            )
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"❌ 生成回退预测失败: {e}")
            return None
    
    def get_service_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        return {
            'initialized': self.initialized,
            'cache_size': len(self.prediction_cache),
            'indicator_config': self.indicator_config,
            'cache_ttl': self.cache_ttl,
            'supported_indicators': [indicator.value for indicator in TechnicalIndicator]
        }
    
    def clear_cache(self):
        """清空预测缓存"""
        self.prediction_cache.clear()
        self.logger.info("🔄 回退预测缓存已清空")


# 全局服务实例
_fallback_service = None


async def get_fallback_service() -> Optional[FallbackPredictionService]:
    """获取回退预测服务实例"""
    global _fallback_service
    
    if _fallback_service is None:
        _fallback_service = FallbackPredictionService()
        if not await _fallback_service.initialize():
            _fallback_service = None
            return None
    
    return _fallback_service