# -*- coding: utf-8 -*-
"""
Kronos 上下文决策服务
Context-aware decision service for Kronos AI predictions
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass

from app.services.ml.kronos_timeframe_manager import PredictionContext, TradingMode, MarketRegime
from app.services.ml.kronos_enhanced_decision import KronosEnhancedDecision, KronosSignalStrength, MarketRegime as LegacyMarketRegime
from app.services.analysis.position_analysis_service import PositionRecommendation, PositionRisk
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ContextIntegratedDecision:
    """上下文集成决策结果"""
    # 基础信息
    symbol: str
    timestamp: datetime
    trading_mode: TradingMode
    
    # Kronos 预测结果
    kronos_prediction: Optional[Any] = None
    kronos_confidence: float = 0.5
    kronos_signal_strength: KronosSignalStrength = KronosSignalStrength.WEAK
    
    # 技术分析结果
    technical_signal: Optional[str] = None
    technical_confidence: float = 0.5
    technical_reasoning: Optional[str] = None
    
    # 持仓分析结果
    position_recommendation: Optional[Any] = None
    position_risk: Optional[Any] = None
    
    # 综合决策
    final_action: str = "持有观望"
    final_confidence: float = 0.5
    signal_confluence: float = 0.5  # 信号一致性
    
    # 风险管理 - 设置默认值避免None格式化错误
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: float = 0.1
    
    # 决策依据
    reasoning: str = "暂无详细说明"
    market_regime: Optional[LegacyMarketRegime] = None


class KronosContextDecisionService:
    """Kronos 上下文决策服务 - 整合多维度信息生成最终决策"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
        # 决策权重配置
        self.decision_weights = {
            TradingMode.SHORT_TERM: {
                'kronos': 0.4,      # 短线更依赖AI预测
                'technical': 0.35,  # 技术分析重要
                'position': 0.25    # 持仓分析
            },
            TradingMode.MEDIUM_TERM: {
                'kronos': 0.35,     # 中线AI权重稍低
                'technical': 0.4,   # 技术分析更重要
                'position': 0.25    # 持仓分析
            }
        }
        
        # 信号强度阈值
        self.confidence_thresholds = {
            TradingMode.SHORT_TERM: {
                'strong_buy': 0.75,
                'buy': 0.6,
                'hold': 0.4,
                'sell': 0.6,
                'strong_sell': 0.75
            },
            TradingMode.MEDIUM_TERM: {
                'strong_buy': 0.7,
                'buy': 0.55,
                'hold': 0.45,
                'sell': 0.55,
                'strong_sell': 0.7
            }
        }
    
    async def generate_context_integrated_decision(
        self,
        symbol: str,
        kronos_prediction: Any,
        kronos_confidence: float,
        kronos_signal_strength: KronosSignalStrength,
        technical_result: Optional[Dict[str, Any]],
        position_analysis: Optional[Dict[str, Any]],
        prediction_context: PredictionContext
    ) -> Optional[KronosEnhancedDecision]:
        """生成上下文集成决策"""
        try:
            # 🎯 第一步：提取各模块信号
            signals = await self._extract_signals(
                kronos_prediction, technical_result, position_analysis
            )
            
            # 📊 第二步：计算信号一致性
            signal_confluence = self._calculate_signal_confluence(signals)
            
            # ⚖️ 第三步：根据交易模式调整权重
            weights = self.decision_weights.get(
                prediction_context.trading_mode, 
                self.decision_weights[TradingMode.SHORT_TERM]
            )
            
            # 🎯 第四步：生成综合决策
            final_action, final_confidence = await self._generate_final_decision(
                signals, weights, signal_confluence, prediction_context
            )
            
            # 🛡️ 第五步：风险管理建议
            risk_management = await self._generate_risk_management(
                symbol, final_action, final_confidence, prediction_context
            )
            
            # 📝 第六步：生成决策推理
            reasoning = self._generate_reasoning(
                signals, weights, signal_confluence, final_action, final_confidence
            )
            
            # 🎉 构建最终决策对象
            enhanced_decision = KronosEnhancedDecision(
                symbol=symbol,
                timestamp=datetime.now(),
                
                # Kronos预测结果
                kronos_prediction=kronos_prediction,
                kronos_signal_strength=kronos_signal_strength,
                kronos_confidence=kronos_confidence,
                
                # 技术分析结果
                technical_signal=technical_result.get('action', '持有') if technical_result else '持有',
                technical_confidence=technical_result.get('confidence', 0.5) if technical_result else 0.5,
                
                # 持仓分析结果
                position_recommendation=position_analysis,
                
                # 综合决策
                final_action=final_action,
                final_confidence=final_confidence,
                signal_confluence=signal_confluence,
                
                # 风险管理
                entry_price=risk_management.get('entry_price'),
                stop_loss=risk_management.get('stop_loss'),
                take_profit=risk_management.get('take_profit'),
                position_size=risk_management.get('position_size', 0.1),
                
                # 决策依据和上下文
                reasoning=reasoning,
                market_regime=prediction_context.market_regime if prediction_context else None
            )
            
            self.logger.info(
                f"🎯 {symbol} 上下文决策完成: {final_action} "
                f"(置信度: {final_confidence:.2f}, 一致性: {signal_confluence:.2f})"
            )
            
            return enhanced_decision
            
        except Exception as e:
            self.logger.error(f"生成 {symbol} 上下文决策失败: {e}")
            return None
    
    async def _extract_signals(
        self, 
        kronos_prediction: Any, 
        technical_result: Optional[Dict[str, Any]], 
        position_analysis: Optional[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """提取各模块信号"""
        signals = {}
        
        # Kronos 信号
        if kronos_prediction:
            signals['kronos'] = {
                'action': getattr(kronos_prediction, 'final_action', '持有'),
                'confidence': getattr(kronos_prediction, 'kronos_confidence', 0.5),
                'reasoning': getattr(kronos_prediction, 'reasoning', '')
            }
        
        # 技术分析信号
        if technical_result:
            signals['technical'] = {
                'action': technical_result.get('overall_signal', '持有'),
                'confidence': technical_result.get('confidence', 0.5),
                'reasoning': technical_result.get('reasoning', '')
            }
        
        # 持仓分析信号
        if position_analysis:
            signals['position'] = {
                'action': position_analysis.get('recommendation', '持有'),
                'confidence': position_analysis.get('confidence', 0.5),
                'reasoning': position_analysis.get('reasoning', '')
            }
        
        return signals
    
    def _calculate_signal_confluence(self, signals: Dict[str, Dict[str, Any]]) -> float:
        """计算信号一致性"""
        if len(signals) < 2:
            return 0.5
        
        actions = [signal['action'] for signal in signals.values()]
        
        # 计算动作一致性
        action_counts = {}
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1
        
        max_count = max(action_counts.values())
        confluence = max_count / len(actions)
        
        return confluence
    
    async def _generate_final_decision(
        self, 
        signals: Dict[str, Dict[str, Any]], 
        weights: Dict[str, float],
        signal_confluence: float,
        prediction_context: PredictionContext
    ) -> tuple[str, float]:
        """生成最终决策"""
        
        # 加权平均置信度
        weighted_confidence = 0.0
        total_weight = 0.0
        
        # 动作投票
        action_votes = {}
        
        for signal_type, signal in signals.items():
            weight = weights.get(signal_type, 0.0)
            if weight > 0:
                confidence = signal['confidence']
                action = signal['action']
                
                weighted_confidence += confidence * weight
                total_weight += weight
                
                # 动作投票（考虑权重和置信度）
                vote_strength = weight * confidence
                action_votes[action] = action_votes.get(action, 0) + vote_strength
        
        # 计算最终置信度
        if total_weight > 0:
            final_confidence = weighted_confidence / total_weight
        else:
            final_confidence = 0.5
        
        # 选择得票最高的动作
        if action_votes:
            final_action = max(action_votes.items(), key=lambda x: x[1])[0]
        else:
            final_action = "持有"
        
        # 根据信号一致性调整置信度
        final_confidence *= (0.5 + 0.5 * signal_confluence)
        
        # 确保置信度在合理范围内
        final_confidence = max(0.1, min(0.95, final_confidence))
        
        return final_action, final_confidence
    
    async def _generate_risk_management(
        self, 
        symbol: str, 
        action: str, 
        confidence: float,
        prediction_context: PredictionContext
    ) -> Dict[str, Any]:
        """生成风险管理建议"""
        
        risk_management = {
            'position_size': min(0.1, confidence * 0.2),  # 基于置信度的仓位大小
            'entry_price': None,
            'stop_loss': None,
            'take_profit': None
        }
        
        # 根据交易模式调整风险参数
        if prediction_context.trading_mode == TradingMode.SHORT_TERM:
            # 短线交易：更紧的止损止盈
            risk_management['stop_loss_pct'] = 0.02  # 2%
            risk_management['take_profit_pct'] = 0.04  # 4%
        else:
            # 中线交易：更宽的止损止盈
            risk_management['stop_loss_pct'] = 0.05  # 5%
            risk_management['take_profit_pct'] = 0.10  # 10%
        
        return risk_management
    
    def _generate_reasoning(
        self, 
        signals: Dict[str, Dict[str, Any]], 
        weights: Dict[str, float],
        signal_confluence: float,
        final_action: str,
        final_confidence: float
    ) -> str:
        """生成决策推理"""
        
        reasoning_parts = []
        
        # 信号一致性说明
        if signal_confluence > 0.7:
            reasoning_parts.append(f"✅ 多信号高度一致 ({signal_confluence:.1%})")
        elif signal_confluence > 0.5:
            reasoning_parts.append(f"⚖️ 信号部分一致 ({signal_confluence:.1%})")
        else:
            reasoning_parts.append(f"⚠️ 信号存在分歧 ({signal_confluence:.1%})")
        
        # 各模块贡献
        for signal_type, signal in signals.items():
            weight = weights.get(signal_type, 0)
            if weight > 0:
                reasoning_parts.append(
                    f"• {signal_type.title()}: {signal['action']} "
                    f"(置信度: {signal['confidence']:.1%}, 权重: {weight:.1%})"
                )
        
        # 最终决策说明
        reasoning_parts.append(f"🎯 综合决策: {final_action} (置信度: {final_confidence:.1%})")
        
        return " | ".join(reasoning_parts)