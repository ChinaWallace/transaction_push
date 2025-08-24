# -*- coding: utf-8 -*-
"""
统一交易决策服务
Unified Trading Decision Service - 融合传统技术分析和机器学习的综合决策系统
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import numpy as np
import pandas as pd

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal
from app.services.adaptive_ml_service import AdaptiveMLService, AdaptivePrediction
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.trading_decision_service import TradingDecisionService, TradingAction, RiskLevel
from app.services.okx_service import OKXService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class MarketRegime(Enum):
    """市场状态枚举"""
    TRENDING_UP = "上涨趋势"
    TRENDING_DOWN = "下跌趋势"
    RANGING = "震荡整理"
    VOLATILE = "高波动"
    CALM = "平静"


@dataclass
class UnifiedTradingRecommendation:
    """统一交易建议"""
    symbol: str
    timestamp: datetime
    
    # 综合决策
    final_action: TradingAction
    confidence: float
    
    # 传统分析结果
    traditional_signal: str
    traditional_confidence: float
    
    # ML分析结果
    ml_signal: str
    ml_confidence: float
    
    # 市场状态
    market_regime: MarketRegime
    volatility_level: str
    
    # 动态止盈止损
    dynamic_stop_loss: float
    dynamic_take_profit: float
    risk_reward_ratio: float
    
    # 仓位管理
    position_size_percent: float
    leverage: float
    risk_level: RiskLevel
    
    # 价格信息
    current_price: float
    entry_price: float
    
    # 决策理由
    reasoning: str
    key_factors: List[str]
    
    # 时间建议
    entry_timing: str
    hold_duration_hours: Optional[int]


class UnifiedTradingService:
    """统一交易决策服务类"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.traditional_service = TradingDecisionService()
        # self.trend_service = TrendAnalysisService()  # 已禁用，有问题
        self.trend_service = None  # 不使用有问题的TrendAnalysisService
        
        # 初始化自适应ML服务（能够从传统分析中学习）
        try:
            self.adaptive_ml_service = AdaptiveMLService()
            self.adaptive_ml_enabled = True
            logger.info("✅ 自适应ML服务初始化成功，支持从传统分析学习")
        except Exception as e:
            logger.warning(f"⚠️ 自适应ML服务初始化失败: {e}")
            self.adaptive_ml_service = None
            self.adaptive_ml_enabled = False
        
        # 保留原有ML服务作为备用
        try:
            self.ml_service = MLEnhancedService()
            self.ml_enabled = True
            logger.info("✅ 传统ML服务初始化成功")
        except Exception as e:
            logger.warning(f"⚠️ 传统ML服务初始化失败: {e}")
            self.ml_service = None
            self.ml_enabled = False
    
    async def get_unified_recommendation(self, symbol: str) -> UnifiedTradingRecommendation:
        """
        获取统一交易建议 - 融合传统分析和机器学习
        
        Args:
            symbol: 交易对
            
        Returns:
            统一交易建议
        """
        try:
            # 并行获取各种分析
            tasks = []
            
            # 1. 传统技术分析
            tasks.append(self._get_traditional_analysis(symbol))
            
            # 2. 自适应ML分析（优先使用）
            if self.adaptive_ml_enabled:
                tasks.append(self._get_adaptive_ml_analysis(symbol))
            elif self.ml_enabled:
                tasks.append(self._get_ml_analysis(symbol))
            else:
                tasks.append(self._get_dummy_ml_analysis())
            
            # 3. 市场数据
            tasks.append(self._get_market_data(symbol))
            
            # 执行并行分析
            traditional_result, ml_result, market_data = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理异常结果
            if isinstance(traditional_result, Exception):
                logger.warning(f"传统分析失败: {traditional_result}")
                traditional_result = self._get_default_traditional_result()
            
            if isinstance(ml_result, Exception):
                logger.warning(f"ML分析失败: {ml_result}")
                ml_result = self._get_default_ml_result()
            
            if isinstance(market_data, Exception):
                logger.error(f"获取市场数据失败: {market_data}")
                raise TradingToolError(f"无法获取{symbol}市场数据")
            
            # 融合决策
            unified_decision = self._fuse_decisions(traditional_result, ml_result, market_data)
            
            # 计算动态止盈止损
            stop_loss, take_profit, risk_reward = await self._calculate_dynamic_levels(
                unified_decision, market_data
            )
            
            # 构建最终建议
            recommendation = UnifiedTradingRecommendation(
                symbol=symbol,
                timestamp=datetime.now(),
                
                # 综合决策
                final_action=unified_decision['action'],
                confidence=unified_decision['confidence'],
                
                # 分析结果
                traditional_signal=traditional_result.get('signal', '持有'),
                traditional_confidence=traditional_result.get('confidence', 50.0),
                ml_signal=ml_result.get('signal', '持有'),
                ml_confidence=ml_result.get('confidence', 50.0),
                
                # 市场状态
                market_regime=self._determine_market_regime(market_data),
                volatility_level=market_data.get('volatility_level', '中等'),
                
                # 动态止盈止损
                dynamic_stop_loss=stop_loss,
                dynamic_take_profit=take_profit,
                risk_reward_ratio=risk_reward,
                
                # 仓位管理
                position_size_percent=unified_decision['position_size'],
                leverage=unified_decision['leverage'],
                risk_level=unified_decision['risk_level'],
                
                # 价格信息
                current_price=market_data['current_price'],
                entry_price=unified_decision['entry_price'],
                
                # 决策理由
                reasoning=unified_decision['reasoning'],
                key_factors=unified_decision['key_factors'],
                
                # 时间建议
                entry_timing=unified_decision['entry_timing'],
                hold_duration_hours=unified_decision.get('hold_duration')
            )
            
            trading_logger.info(f"统一交易建议 {symbol}: {recommendation.final_action.value} (置信度: {recommendation.confidence:.1f}%)")
            
            return recommendation
            
        except Exception as e:
            logger.error(f"获取{symbol}统一交易建议失败: {e}")
            raise TradingToolError(f"统一交易建议失败: {e}")
    
    async def _get_traditional_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取传统技术分析 - 使用TradingDecisionService替代有问题的TrendAnalysisService"""
        try:
            # 使用TradingDecisionService的内置市场信号分析
            async with self.traditional_service.exchange_service as exchange:
                market_signals = await self.traditional_service._get_market_signals(symbol, exchange)
            
            # 转换为统一格式
            trend = market_signals.get('trend', 'neutral')
            confidence = market_signals.get('confidence', 50.0)
            
            # 根据趋势和置信度确定信号
            if trend == 'bullish':
                if confidence > 85:
                    signal = '强烈买入'
                    signal_name = '强势多头共振'
                elif confidence > 65:
                    signal = '买入'
                    signal_name = '回调中多头'
                else:
                    signal = '持有'
                    signal_name = '背离多头'
            elif trend == 'bearish':
                if confidence > 85:
                    signal = '强烈卖出'
                    signal_name = '强势空头共振'
                elif confidence > 65:
                    signal = '卖出'
                    signal_name = '短线反弹'
                else:
                    signal = '持有'
                    signal_name = '反转尝试'
            else:
                signal = '等待'
                signal_name = '信号混乱'
            
            return {
                'signal': signal,
                'confidence': confidence,
                'signal_name': signal_name,
                'trends': {
                    'overall': trend,
                    'volatility': market_signals.get('volatility', 'medium'),
                    'volume_anomaly': market_signals.get('volume_anomaly', False),
                    'funding_rate_signal': market_signals.get('funding_rate_signal', 'neutral')
                },
                'strategy_advice': f"基于{trend}趋势，置信度{confidence:.1f}%"
            }
            
        except Exception as e:
            logger.warning(f"传统分析失败: {e}")
            return self._get_default_traditional_result()
    
    async def _get_adaptive_ml_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取自适应ML分析"""
        try:
            # 使用自适应ML服务进行预测
            prediction = await self.adaptive_ml_service.predict_with_learning(symbol)
            
            # 转换信号格式
            signal = prediction.signal.value
            confidence = prediction.confidence * 100
            
            # 根据与传统分析的一致性调整置信度
            if prediction.traditional_agreement < 0.5:
                confidence = max(30.0, confidence * 0.7)  # 降低置信度
                logger.info(f"ML与传统分析分歧 {symbol}: 一致性 {prediction.traditional_agreement:.2f}")
            elif prediction.traditional_agreement > 0.8:
                confidence = min(95.0, confidence * 1.1)  # 提高置信度
                logger.info(f"ML与传统分析高度一致 {symbol}: 一致性 {prediction.traditional_agreement:.2f}")
            
            return {
                'signal': signal,
                'confidence': confidence,
                'traditional_agreement': prediction.traditional_agreement,
                'learning_score': prediction.learning_score,
                'model_accuracy': prediction.model_accuracy,
                'reasoning': prediction.reasoning,
                'is_adaptive': True
            }
            
        except Exception as e:
            logger.warning(f"自适应ML分析失败: {e}")
            # 回退到传统ML分析
            if self.ml_enabled:
                return await self._get_ml_analysis(symbol)
            else:
                return self._get_default_ml_result()
    
    async def _get_ml_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取传统ML分析"""
        try:
            # 预测信号
            prediction = await self.ml_service.predict_signal(symbol)
            
            # 异常检测
            anomalies = await self.ml_service.detect_anomalies(symbol)
            
            # 转换信号格式
            signal = prediction.signal.value
            confidence = prediction.confidence * 100
            
            # 异常调整置信度
            if anomalies:
                high_severity_count = sum(1 for a in anomalies if a.severity > 0.7)
                confidence = max(30.0, confidence - high_severity_count * 10)
            
            return {
                'signal': signal,
                'confidence': confidence,
                'probabilities': prediction.probability_distribution,
                'anomalies': len(anomalies),
                'model_accuracy': prediction.model_accuracy,
                'is_adaptive': False
            }
            
        except Exception as e:
            logger.warning(f"传统ML分析失败: {e}")
            return self._get_default_ml_result()
    
    async def _get_dummy_ml_analysis(self) -> Dict[str, Any]:
        """获取虚拟ML分析（当ML服务不可用时）"""
        return self._get_default_ml_result()
    
    async def _get_market_data(self, symbol: str) -> Dict[str, Any]:
        """获取市场数据"""
        async with self.okx_service as exchange:
            # 获取当前价格
            current_price = await exchange.get_current_price(symbol)
            
            # 获取K线数据计算波动率
            klines = await exchange.get_kline_data(symbol, '1H', 24)
            
            volatility_level = '中等'
            atr_percent = 0.03
            
            if klines and len(klines) >= 20:
                closes = [float(k['close']) for k in klines]
                highs = [float(k['high']) for k in klines]
                lows = [float(k['low']) for k in klines]
                
                # 计算ATR百分比
                true_ranges = []
                for i in range(1, len(klines)):
                    tr1 = highs[i] - lows[i]
                    tr2 = abs(highs[i] - closes[i-1])
                    tr3 = abs(lows[i] - closes[i-1])
                    true_ranges.append(max(tr1, tr2, tr3))
                
                if true_ranges:
                    atr = sum(true_ranges) / len(true_ranges)
                    atr_percent = atr / current_price
                    
                    if atr_percent > 0.05:
                        volatility_level = '高'
                    elif atr_percent < 0.02:
                        volatility_level = '低'
            
            return {
                'current_price': current_price,
                'volatility_level': volatility_level,
                'atr_percent': atr_percent,
                'symbol': symbol
            }
    
    def _fuse_decisions(self, traditional: Dict, ml: Dict, market: Dict) -> Dict[str, Any]:
        """融合决策"""
        # 动态权重调整
        if ml.get('is_adaptive', False):
            # 自适应ML：根据与传统分析的一致性动态调整权重
            agreement = ml.get('traditional_agreement', 0.5)
            if agreement > 0.8:
                # 高度一致：增加ML权重
                traditional_weight = 0.4
                ml_weight = 0.6
            elif agreement > 0.5:
                # 部分一致：平衡权重
                traditional_weight = 0.5
                ml_weight = 0.5
            else:
                # 分歧较大：降低ML权重，更信任传统分析
                traditional_weight = 0.7
                ml_weight = 0.3
            
            logger.info(f"自适应权重调整: 传统={traditional_weight:.1f}, ML={ml_weight:.1f} (一致性={agreement:.2f})")
        else:
            # 传统ML或无ML：固定权重
            traditional_weight = 0.6
            ml_weight = 0.4 if (self.ml_enabled or self.adaptive_ml_enabled) else 0.0
        
        # 如果ML不可用，传统分析权重100%
        if not self.ml_enabled and not self.adaptive_ml_enabled:
            traditional_weight = 1.0
            ml_weight = 0.0
        
        # 信号映射到数值
        signal_values = {
            '强烈买入': 2.0,
            '买入': 1.0,
            '持有': 0.0,
            '卖出': -1.0,
            '强烈卖出': -2.0,
            '等待': 0.0
        }
        
        # 计算综合信号强度
        traditional_value = signal_values.get(traditional['signal'], 0.0)
        ml_value = signal_values.get(ml['signal'], 0.0)
        
        # 加权平均
        combined_value = (traditional_value * traditional_weight + 
                         ml_value * ml_weight)
        
        # 综合置信度
        combined_confidence = (traditional['confidence'] * traditional_weight + 
                              ml['confidence'] * ml_weight)
        
        # 确定最终动作
        if combined_value >= 1.5:
            final_action = TradingAction.STRONG_BUY
        elif combined_value >= 0.5:
            final_action = TradingAction.BUY
        elif combined_value <= -1.5:
            final_action = TradingAction.STRONG_SELL
        elif combined_value <= -0.5:
            final_action = TradingAction.SELL
        elif abs(combined_value) < 0.3:
            final_action = TradingAction.HOLD
        else:
            final_action = TradingAction.WAIT
        
        # 计算仓位大小
        position_size = self._calculate_position_size(combined_confidence, market)
        
        # 计算杠杆
        leverage = self._calculate_leverage(final_action, market, combined_confidence)
        
        # 评估风险等级
        risk_level = self._assess_risk_level(final_action, market, combined_confidence)
        
        # 生成决策理由
        reasoning = self._generate_reasoning(traditional, ml, final_action, combined_confidence, traditional_weight, ml_weight)
        
        # 关键因素
        key_factors = self._identify_key_factors(traditional, ml, market)
        
        return {
            'action': final_action,
            'confidence': combined_confidence,
            'position_size': position_size,
            'leverage': leverage,
            'risk_level': risk_level,
            'entry_price': market['current_price'],
            'reasoning': reasoning,
            'key_factors': key_factors,
            'entry_timing': self._determine_entry_timing(final_action, combined_confidence),
            'hold_duration': self._estimate_hold_duration(final_action, market)
        }
    
    async def _calculate_dynamic_levels(self, decision: Dict, market: Dict) -> Tuple[float, float, float]:
        """计算动态止盈止损 - 基于技术分析的支撑位和压力位"""
        current_price = market['current_price']
        atr_percent = market.get('atr_percent', 0.03)
        action = decision['action']
        confidence = decision['confidence']
        symbol = market.get('symbol', '')
        
        # 获取技术分析的支撑位和压力位
        support_levels, resistance_levels = await self._get_support_resistance_levels(symbol, current_price)
        
        # 基础止损：根据ATR动态调整
        base_stop_loss_percent = max(0.02, atr_percent * 1.5)  # 最小2%，最大ATR的1.5倍
        
        # 根据置信度调整
        confidence_multiplier = 0.7 + (confidence / 100) * 0.6  # 0.7-1.3倍
        dynamic_stop_loss_percent = base_stop_loss_percent * confidence_multiplier
        
        # 根据市场波动性调整
        volatility = market.get('volatility_level', '中等')
        if volatility == '高':
            dynamic_stop_loss_percent *= 1.3
        elif volatility == '低':
            dynamic_stop_loss_percent *= 0.8
        
        # 计算止盈（风险收益比1:2.5到1:4）
        risk_reward_ratio = 2.5 + (confidence / 100) * 1.5  # 2.5-4倍
        
        # 根据交易方向和技术分析计算实际价格
        if action in [TradingAction.BUY, TradingAction.STRONG_BUY]:
            # 多头：使用支撑位作为止损，压力位作为止盈
            if support_levels:
                # 选择最近的支撑位作为止损
                valid_supports = [s for s in support_levels if s < current_price * 0.98]
                if valid_supports:
                    technical_stop_loss = max(valid_supports)
                    # 确保止损不超过风险限制
                    max_stop_loss = current_price * (1 - dynamic_stop_loss_percent)
                    stop_loss_price = max(technical_stop_loss, max_stop_loss)
                else:
                    stop_loss_price = current_price * (1 - dynamic_stop_loss_percent)
            else:
                stop_loss_price = current_price * (1 - dynamic_stop_loss_percent)
            
            if resistance_levels:
                # 选择合适的压力位作为止盈目标
                suitable_resistance = [r for r in resistance_levels if r > current_price * 1.02]
                if suitable_resistance:
                    technical_take_profit = min(suitable_resistance)
                    # 确保风险收益比合理
                    min_take_profit = current_price + (current_price - stop_loss_price) * risk_reward_ratio
                    take_profit_price = max(technical_take_profit, min_take_profit)
                else:
                    take_profit_price = current_price + (current_price - stop_loss_price) * risk_reward_ratio
            else:
                take_profit_price = current_price + (current_price - stop_loss_price) * risk_reward_ratio
                
        elif action in [TradingAction.SELL, TradingAction.STRONG_SELL]:
            # 空头：使用压力位作为止损，支撑位作为止盈
            if resistance_levels:
                # 选择最近的压力位作为止损
                valid_resistances = [r for r in resistance_levels if r > current_price * 1.02]
                if valid_resistances:
                    technical_stop_loss = min(valid_resistances)
                    # 确保止损不超过风险限制
                    max_stop_loss = current_price * (1 + dynamic_stop_loss_percent)
                    stop_loss_price = min(technical_stop_loss, max_stop_loss)
                else:
                    stop_loss_price = current_price * (1 + dynamic_stop_loss_percent)
            else:
                stop_loss_price = current_price * (1 + dynamic_stop_loss_percent)
            
            if support_levels:
                # 选择合适的支撑位作为止盈目标
                suitable_supports = [s for s in support_levels if s < current_price * 0.98]
                if suitable_supports:
                    technical_take_profit = max(suitable_supports)
                    # 确保风险收益比合理
                    min_take_profit = current_price - (stop_loss_price - current_price) * risk_reward_ratio
                    take_profit_price = min(technical_take_profit, min_take_profit)
                else:
                    take_profit_price = current_price - (stop_loss_price - current_price) * risk_reward_ratio
            else:
                take_profit_price = current_price - (stop_loss_price - current_price) * risk_reward_ratio
    
        else:
            # 持有或等待：设置保护性止损
            stop_loss_price = current_price * (1 - 0.05)  # 5%保护性止损
            take_profit_price = current_price * (1 + 0.05)  # 5%保护性止盈
            risk_reward_ratio = 1.0
        
        return stop_loss_price, take_profit_price, risk_reward_ratio
    
    async def _get_support_resistance_levels(self, symbol: str, current_price: float) -> Tuple[List[float], List[float]]:
        """获取技术分析的支撑位和压力位"""
        try:
            # 获取历史数据用于计算支撑压力位
            async with self.okx_service as exchange:
                klines = await exchange.get_kline_data(symbol, '4H', 168)  # 7天数据
                
                if not klines or len(klines) < 50:
                    # 如果数据不足，使用简单的百分比方法
                    support_levels = [
                        current_price * 0.98,  # 2%
                        current_price * 0.95,  # 5%
                        current_price * 0.92   # 8%
                    ]
                    resistance_levels = [
                        current_price * 1.02,  # 2%
                        current_price * 1.05,  # 5%
                        current_price * 1.08   # 8%
                    ]
                    return support_levels, resistance_levels
                
                # 转换为DataFrame格式
                import pandas as pd
                df = pd.DataFrame(klines)
                
                # 确保数据格式正确
                price_columns = ['open', 'high', 'low', 'close']
                for col in price_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # 计算支撑压力位
                from app.utils.indicators import calculate_support_resistance
                
                support_levels, resistance_levels = calculate_support_resistance(
                    df,  # 传入完整的DataFrame
                    lookback_periods=20
                )
                
                return support_levels, resistance_levels
                
        except Exception as e:
            logger.warning(f"获取{symbol}支撑压力位失败: {e}")
            # 回退到简单方法
            support_levels = [
                current_price * 0.98,  # 2%
                current_price * 0.95,  # 5%
                current_price * 0.92   # 8%
            ]
            resistance_levels = [
                current_price * 1.02,  # 2%
                current_price * 1.05,  # 5%
                current_price * 1.08   # 8%
            ]
            return support_levels, resistance_levels      
    
    def _calculate_position_size(self, confidence: float, market: Dict) -> float:
        """计算仓位大小"""
        base_size = 10.0  # 基础10%
        
        # 根据置信度调整
        confidence_multiplier = confidence / 100.0
        
        # 根据波动性调整
        volatility = market.get('volatility_level', '中等')
        if volatility == '高':
            volatility_multiplier = 0.6
        elif volatility == '低':
            volatility_multiplier = 1.3
        else:
            volatility_multiplier = 1.0
        
        position_size = base_size * confidence_multiplier * volatility_multiplier
        return min(position_size, 25.0)  # 最大25%
    
    def _calculate_leverage(self, action: TradingAction, market: Dict, confidence: float) -> float:
        """计算杠杆"""
        base_leverage = 2.0
        
        # 根据信号强度调整
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            leverage_multiplier = 1.2
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            leverage_multiplier = 1.0
        else:
            leverage_multiplier = 0.5
        
        # 根据置信度调整
        confidence_multiplier = 0.8 + (confidence / 100) * 0.4  # 0.8-1.2倍
        
        # 根据波动性调整
        volatility = market.get('volatility_level', '中等')
        if volatility == '高':
            volatility_multiplier = 0.7
        elif volatility == '低':
            volatility_multiplier = 1.2
        else:
            volatility_multiplier = 1.0
        
        leverage = base_leverage * leverage_multiplier * confidence_multiplier * volatility_multiplier
        return min(leverage, 3.0)  # 最大3倍杠杆
    
    def _assess_risk_level(self, action: TradingAction, market: Dict, confidence: float) -> RiskLevel:
        """评估风险等级"""
        risk_score = 0
        
        # 动作风险
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            risk_score += 2
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            risk_score += 1
        
        # 置信度风险
        if confidence < 60:
            risk_score += 2
        elif confidence < 75:
            risk_score += 1
        
        # 波动性风险
        volatility = market.get('volatility_level', '中等')
        if volatility == '高':
            risk_score += 2
        elif volatility == '中等':
            risk_score += 1
        
        # 风险等级映射
        if risk_score >= 5:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 4:
            return RiskLevel.HIGH
        elif risk_score >= 2:
            return RiskLevel.MEDIUM
        elif risk_score >= 1:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    def _determine_market_regime(self, market: Dict) -> MarketRegime:
        """确定市场状态"""
        volatility = market.get('volatility_level', '中等')
        
        if volatility == '高':
            return MarketRegime.VOLATILE
        elif volatility == '低':
            return MarketRegime.CALM
        else:
            return MarketRegime.RANGING  # 简化处理
    
    def _generate_reasoning(self, traditional: Dict, ml: Dict, action: TradingAction, 
                          confidence: float, traditional_weight: float, ml_weight: float) -> str:
        """生成决策理由"""
        reasons = []
        
        # 传统分析
        reasons.append(f"技术分析: {traditional['signal']} ({traditional['confidence']:.1f}%, 权重{traditional_weight:.1f})")
        
        # ML分析
        if self.adaptive_ml_enabled or self.ml_enabled:
            ml_type = "自适应ML" if ml.get('is_adaptive', False) else "传统ML"
            ml_info = f"{ml_type}: {ml['signal']} ({ml['confidence']:.1f}%, 权重{ml_weight:.1f})"
            
            # 如果是自适应ML，添加一致性信息
            if ml.get('is_adaptive', False):
                agreement = ml.get('traditional_agreement', 0.5)
                ml_info += f", 一致性{agreement:.2f}"
            
            reasons.append(ml_info)
        
        # 综合结果
        reasons.append(f"综合决策: {action.value} (置信度: {confidence:.1f}%)")
        
        return " | ".join(reasons)
    
    def _identify_key_factors(self, traditional: Dict, ml: Dict, market: Dict) -> List[str]:
        """识别关键因素"""
        factors = []
        
        # 技术分析因素
        if traditional.get('signal_name'):
            factors.append(f"技术形态: {traditional['signal_name']}")
        
        # ML因素
        if self.ml_enabled and ml.get('anomalies', 0) > 0:
            factors.append(f"检测到 {ml['anomalies']} 个异常")
        
        # 市场因素
        factors.append(f"波动性: {market['volatility_level']}")
        
        return factors
    
    def _determine_entry_timing(self, action: TradingAction, confidence: float) -> str:
        """确定入场时机"""
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            return "立即执行"
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            if confidence > 75:
                return "尽快执行"
            else:
                return "等待确认"
        else:
            return "暂不操作"
    
    def _estimate_hold_duration(self, action: TradingAction, market: Dict) -> Optional[int]:
        """估计持仓时间"""
        if action in [TradingAction.HOLD, TradingAction.WAIT]:
            return None
        
        volatility = market.get('volatility_level', '中等')
        
        if volatility == '高':
            return 4  # 4小时
        elif volatility == '低':
            return 24  # 24小时
        else:
            return 12  # 12小时
    
    def _get_default_traditional_result(self) -> Dict[str, Any]:
        """获取默认传统分析结果"""
        return {
            'signal': '持有',
            'confidence': 50.0,
            'signal_name': '信号不明',
            'trends': {},
            'strategy_advice': '等待更多信息'
        }
    
    def _get_default_ml_result(self) -> Dict[str, Any]:
        """获取默认ML分析结果"""
        return {
            'signal': '持有',
            'confidence': 50.0,
            'probabilities': {},
            'anomalies': 0,
            'model_accuracy': 0.5
        }
    
    async def batch_analyze_symbols(self, symbols: List[str]) -> Dict[str, UnifiedTradingRecommendation]:
        """批量分析多个交易对"""
        try:
            tasks = [self.get_unified_recommendation(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            recommendations = {}
            for i, result in enumerate(results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    logger.error(f"分析{symbol}失败: {result}")
                    continue
                recommendations[symbol] = result
            
            return recommendations
            
        except Exception as e:
            logger.error(f"批量分析失败: {e}")
            raise TradingToolError(f"批量分析失败: {e}")