# -*- coding: utf-8 -*-
"""
交易决策服务
Trading Decision Service - 融合传统技术分析和机器学习的综合交易决策系统
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
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.binance_service import BinanceService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class TradingAction(Enum):
    """交易动作枚举"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    WAIT = "wait"  # 等待更好的入场时机


class RiskLevel(Enum):
    """风险等级枚举"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class PositionRecommendation:
    """仓位建议"""
    symbol: str
    action: TradingAction
    confidence: float
    position_size_percent: float  # 建议仓位百分比 (0-100)
    leverage: float              # 建议杠杆倍数
    stop_loss_percent: float     # 止损百分比
    take_profit_percent: float   # 止盈百分比
    risk_level: RiskLevel
    reasoning: str               # 决策理由
    
    # 支撑阻力位
    support_levels: List[float]
    resistance_levels: List[float]
    
    # 时间建议
    hold_duration_hours: Optional[int]
    entry_timing: str  # "immediate", "wait_for_dip", "wait_for_breakout"


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    symbol: str
    timestamp: datetime
    
    # 传统技术分析
    traditional_signals: Dict[str, Any]
    
    # 机器学习分析
    ml_prediction: Dict[str, Any]
    ml_anomalies: List[Dict[str, Any]]
    
    # 综合评分
    bullish_score: float    # 看涨评分 (0-100)
    bearish_score: float    # 看跌评分 (0-100)
    volatility_score: float # 波动性评分 (0-100)
    
    # 市场状态
    market_regime: str      # "trending", "ranging", "volatile", "calm"
    trend_strength: float   # 趋势强度 (0-1)


class TradingDecisionService:
    """交易决策服务类"""
    
    def __init__(self):
        self.ml_service = MLEnhancedService()
        self.trend_service = TrendAnalysisService()
        self.binance_service = BinanceService()
        
        # 风险管理参数
        self.max_position_size = 0.3  # 单个交易对最大仓位30%
        self.max_leverage = 5.0       # 最大杠杆5倍
        self.base_stop_loss = 0.02    # 基础止损2%
        self.base_take_profit = 0.06  # 基础止盈6%
    
    async def analyze_market(self, symbol: str) -> MarketAnalysis:
        """
        综合市场分析
        
        Args:
            symbol: 交易对
            
        Returns:
            市场分析结果
        """
        try:
            # 并行获取各种分析
            traditional_task = self.trend_service.analyze_symbol(symbol)
            ml_prediction_task = self.ml_service.predict_signal(symbol)
            ml_anomaly_task = self.ml_service.detect_anomalies(symbol)
            
            traditional_analysis, ml_prediction, ml_anomalies = await asyncio.gather(
                traditional_task, ml_prediction_task, ml_anomaly_task,
                return_exceptions=True
            )
            
            # 处理异常结果
            if isinstance(traditional_analysis, Exception):
                logger.warning(f"Traditional analysis failed for {symbol}: {traditional_analysis}")
                traditional_analysis = {}
            
            if isinstance(ml_prediction, Exception):
                logger.warning(f"ML prediction failed for {symbol}: {ml_prediction}")
                ml_prediction = None
            
            if isinstance(ml_anomalies, Exception):
                logger.warning(f"ML anomaly detection failed for {symbol}: {ml_anomalies}")
                ml_anomalies = []
            
            # 计算综合评分
            bullish_score, bearish_score, volatility_score = self._calculate_scores(
                traditional_analysis, ml_prediction, ml_anomalies
            )
            
            # 判断市场状态
            market_regime, trend_strength = self._analyze_market_regime(
                traditional_analysis, volatility_score
            )
            
            return MarketAnalysis(
                symbol=symbol,
                timestamp=datetime.now(),
                traditional_signals=traditional_analysis,
                ml_prediction=self._format_ml_prediction(ml_prediction),
                ml_anomalies=self._format_ml_anomalies(ml_anomalies),
                bullish_score=bullish_score,
                bearish_score=bearish_score,
                volatility_score=volatility_score,
                market_regime=market_regime,
                trend_strength=trend_strength
            )
            
        except Exception as e:
            logger.error(f"Market analysis failed for {symbol}: {e}")
            raise TradingToolError(f"Market analysis failed: {e}")
    
    async def get_trading_recommendation(self, symbol: str, 
                                       account_balance: float = 10000,
                                       current_positions: Dict[str, float] = None) -> PositionRecommendation:
        """
        获取交易建议
        
        Args:
            symbol: 交易对
            account_balance: 账户余额
            current_positions: 当前持仓 {symbol: position_size}
            
        Returns:
            仓位建议
        """
        try:
            # 获取市场分析
            analysis = await self.analyze_market(symbol)
            
            # 获取当前价格
            current_price = await self.binance_service.get_current_price(symbol)
            if not current_price:
                raise TradingToolError(f"Failed to get current price for {symbol}")
            
            current_price = float(current_price)
            
            # 计算交易动作
            action = self._determine_trading_action(analysis)
            
            # 计算仓位大小
            position_size = self._calculate_position_size(
                analysis, account_balance, current_positions or {}
            )
            
            # 计算杠杆
            leverage = self._calculate_leverage(analysis, action)
            
            # 计算止损止盈
            stop_loss, take_profit = self._calculate_stop_loss_take_profit(
                analysis, action, current_price
            )
            
            # 评估风险等级
            risk_level = self._assess_risk_level(analysis, leverage, position_size)
            
            # 生成决策理由
            reasoning = self._generate_reasoning(analysis, action)
            
            # 计算支撑阻力位
            support_levels, resistance_levels = self._calculate_support_resistance(
                analysis, current_price
            )
            
            # 入场时机建议
            entry_timing = self._determine_entry_timing(analysis, action)
            
            # 持仓时间建议
            hold_duration = self._estimate_hold_duration(analysis, action)
            
            return PositionRecommendation(
                symbol=symbol,
                action=action,
                confidence=analysis.bullish_score if action in [TradingAction.BUY, TradingAction.STRONG_BUY] 
                          else analysis.bearish_score if action in [TradingAction.SELL, TradingAction.STRONG_SELL]
                          else 50.0,
                position_size_percent=position_size,
                leverage=leverage,
                stop_loss_percent=stop_loss,
                take_profit_percent=take_profit,
                risk_level=risk_level,
                reasoning=reasoning,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                hold_duration_hours=hold_duration,
                entry_timing=entry_timing
            )
            
        except Exception as e:
            logger.error(f"Trading recommendation failed for {symbol}: {e}")
            raise TradingToolError(f"Trading recommendation failed: {e}")
    
    def _calculate_scores(self, traditional: Dict, ml_prediction, ml_anomalies: List) -> Tuple[float, float, float]:
        """计算综合评分"""
        bullish_score = 0.0
        bearish_score = 0.0
        volatility_score = 50.0
        
        # 传统技术分析评分 (权重40%)
        if traditional:
            traditional_signal = traditional.get('overall_signal', 'hold')
            signal_strength = traditional.get('signal_strength', 0.5)
            
            if traditional_signal in ['strong_buy', 'buy']:
                bullish_score += 40 * signal_strength
            elif traditional_signal in ['strong_sell', 'sell']:
                bearish_score += 40 * signal_strength
            
            # 波动性评分
            volatility_score = traditional.get('volatility_score', 50.0)
        
        # ML预测评分 (权重50%)
        if ml_prediction:
            ml_signal = ml_prediction.signal.value
            ml_confidence = ml_prediction.confidence
            
            if ml_signal in ['strong_buy', 'buy']:
                bullish_score += 50 * ml_confidence
            elif ml_signal in ['strong_sell', 'sell']:
                bearish_score += 50 * ml_confidence
        
        # 异常检测调整 (权重10%)
        if ml_anomalies:
            high_severity_count = sum(1 for a in ml_anomalies if a.severity > 0.7)
            if high_severity_count > 0:
                # 异常增加不确定性，降低信号强度
                adjustment = min(10, high_severity_count * 3)
                bullish_score = max(0, bullish_score - adjustment)
                bearish_score = max(0, bearish_score - adjustment)
                volatility_score = min(100, volatility_score + adjustment)
        
        return bullish_score, bearish_score, volatility_score
    
    def _analyze_market_regime(self, traditional: Dict, volatility_score: float) -> Tuple[str, float]:
        """分析市场状态"""
        trend_strength = traditional.get('trend_strength', 0.5) if traditional else 0.5
        
        if volatility_score > 80:
            regime = "volatile"
        elif volatility_score < 30:
            regime = "calm"
        elif trend_strength > 0.7:
            regime = "trending"
        else:
            regime = "ranging"
        
        return regime, trend_strength
    
    def _determine_trading_action(self, analysis: MarketAnalysis) -> TradingAction:
        """确定交易动作"""
        bullish = analysis.bullish_score
        bearish = analysis.bearish_score
        
        # 强信号阈值
        if bullish > 80 and bullish > bearish * 1.5:
            return TradingAction.STRONG_BUY
        elif bearish > 80 and bearish > bullish * 1.5:
            return TradingAction.STRONG_SELL
        elif bullish > 60 and bullish > bearish * 1.2:
            return TradingAction.BUY
        elif bearish > 60 and bearish > bullish * 1.2:
            return TradingAction.SELL
        elif analysis.volatility_score > 70:
            return TradingAction.WAIT  # 高波动时等待
        else:
            return TradingAction.HOLD
    
    def _calculate_position_size(self, analysis: MarketAnalysis, 
                               balance: float, positions: Dict[str, float]) -> float:
        """计算建议仓位大小"""
        base_size = 10.0  # 基础仓位10%
        
        # 根据信号强度调整
        confidence = max(analysis.bullish_score, analysis.bearish_score)
        size_multiplier = confidence / 100.0
        
        # 根据市场状态调整
        if analysis.market_regime == "volatile":
            size_multiplier *= 0.5  # 高波动减半仓位
        elif analysis.market_regime == "trending":
            size_multiplier *= 1.2  # 趋势市场增加仓位
        
        # 根据风险调整
        if analysis.volatility_score > 80:
            size_multiplier *= 0.3
        elif analysis.volatility_score < 30:
            size_multiplier *= 1.5
        
        position_size = base_size * size_multiplier
        
        # 限制最大仓位
        return min(position_size, self.max_position_size * 100)
    
    def _calculate_leverage(self, analysis: MarketAnalysis, action: TradingAction) -> float:
        """计算建议杠杆"""
        base_leverage = 2.0
        
        # 根据信号强度调整
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            leverage = base_leverage * 1.5
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            leverage = base_leverage
        else:
            leverage = 1.0
        
        # 根据波动性调整
        if analysis.volatility_score > 70:
            leverage *= 0.5  # 高波动降低杠杆
        elif analysis.volatility_score < 30:
            leverage *= 1.2  # 低波动可适当增加杠杆
        
        return min(leverage, self.max_leverage)
    
    def _calculate_stop_loss_take_profit(self, analysis: MarketAnalysis, 
                                       action: TradingAction, price: float) -> Tuple[float, float]:
        """计算止损止盈"""
        # 基础止损止盈
        stop_loss = self.base_stop_loss
        take_profit = self.base_take_profit
        
        # 根据波动性调整
        volatility_multiplier = analysis.volatility_score / 50.0
        stop_loss *= volatility_multiplier
        take_profit *= volatility_multiplier
        
        # 根据趋势强度调整
        if analysis.trend_strength > 0.8:
            take_profit *= 1.5  # 强趋势扩大止盈
        
        return stop_loss * 100, take_profit * 100  # 转换为百分比
    
    def _assess_risk_level(self, analysis: MarketAnalysis, 
                          leverage: float, position_size: float) -> RiskLevel:
        """评估风险等级"""
        risk_score = 0
        
        # 波动性风险
        if analysis.volatility_score > 80:
            risk_score += 3
        elif analysis.volatility_score > 60:
            risk_score += 2
        elif analysis.volatility_score > 40:
            risk_score += 1
        
        # 杠杆风险
        if leverage > 4:
            risk_score += 3
        elif leverage > 2:
            risk_score += 2
        elif leverage > 1:
            risk_score += 1
        
        # 仓位风险
        if position_size > 25:
            risk_score += 2
        elif position_size > 15:
            risk_score += 1
        
        # 异常风险
        high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
        if high_anomalies > 3:
            risk_score += 2
        elif high_anomalies > 1:
            risk_score += 1
        
        # 风险等级映射
        if risk_score >= 8:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 6:
            return RiskLevel.HIGH
        elif risk_score >= 4:
            return RiskLevel.MEDIUM
        elif risk_score >= 2:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    def _generate_reasoning(self, analysis: MarketAnalysis, action: TradingAction) -> str:
        """生成决策理由"""
        reasons = []
        
        # 传统技术分析
        if analysis.traditional_signals:
            signal = analysis.traditional_signals.get('overall_signal', 'hold')
            strength = analysis.traditional_signals.get('signal_strength', 0.5)
            reasons.append(f"技术指标: {signal} (强度: {strength:.1%})")
        
        # ML预测
        if analysis.ml_prediction:
            ml_signal = analysis.ml_prediction.get('signal', 'hold')
            ml_confidence = analysis.ml_prediction.get('confidence', 0.5)
            reasons.append(f"ML预测: {ml_signal} (置信度: {ml_confidence:.1%})")
        
        # 市场状态
        reasons.append(f"市场状态: {analysis.market_regime}")
        reasons.append(f"趋势强度: {analysis.trend_strength:.1%}")
        
        # 异常情况
        if analysis.ml_anomalies:
            high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
            if high_anomalies > 0:
                reasons.append(f"检测到{high_anomalies}个高风险异常")
        
        # 综合评分
        reasons.append(f"看涨评分: {analysis.bullish_score:.1f}")
        reasons.append(f"看跌评分: {analysis.bearish_score:.1f}")
        
        return " | ".join(reasons)
    
    def _calculate_support_resistance(self, analysis: MarketAnalysis, 
                                    current_price: float) -> Tuple[List[float], List[float]]:
        """计算支撑阻力位"""
        # 简化实现，实际可以基于更复杂的算法
        support_levels = []
        resistance_levels = []
        
        # 基于当前价格的百分比计算
        for pct in [0.02, 0.05, 0.10]:
            support_levels.append(current_price * (1 - pct))
            resistance_levels.append(current_price * (1 + pct))
        
        return support_levels, resistance_levels
    
    def _determine_entry_timing(self, analysis: MarketAnalysis, action: TradingAction) -> str:
        """确定入场时机"""
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            return "wait_for_signal"
        elif analysis.volatility_score > 80:
            return "wait_for_calm"
        elif analysis.trend_strength > 0.8:
            return "immediate"
        else:
            return "wait_for_confirmation"
    
    def _estimate_hold_duration(self, analysis: MarketAnalysis, action: TradingAction) -> Optional[int]:
        """估计持仓时间"""
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            return None
        
        base_hours = 24  # 基础24小时
        
        if analysis.market_regime == "trending":
            return base_hours * 3  # 趋势市场持有更久
        elif analysis.market_regime == "volatile":
            return base_hours // 2  # 波动市场快进快出
        else:
            return base_hours
    
    def _format_ml_prediction(self, prediction) -> Dict[str, Any]:
        """格式化ML预测结果"""
        if not prediction:
            return {}
        
        return {
            'signal': prediction.signal.value,
            'confidence': prediction.confidence,
            'model_accuracy': prediction.model_accuracy,
            'probability_distribution': prediction.probability_distribution
        }
    
    def _format_ml_anomalies(self, anomalies: List) -> List[Dict[str, Any]]:
        """格式化ML异常结果"""
        if not anomalies:
            return []
        
        return [
            {
                'type': anomaly.anomaly_type.value,
                'severity': anomaly.severity,
                'description': anomaly.description,
                'recommendation': anomaly.recommendation
            }
            for anomaly in anomalies
        ]