# -*- coding: utf-8 -*-
"""
Kronos前置集成决策服务
将Kronos预测前置到持仓分析和统一交易决策的核心服务
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import pandas as pd
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.kronos_prediction_service import get_kronos_service, KronosPrediction
from app.services.position_analysis_service import PositionAnalysisService, PositionRecommendation, PositionRisk
from app.services.unified_trading_service import UnifiedTradingRecommendation, MarketRegime
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.okx_service import OKXService
from app.utils.exceptions import TradingToolError


# 全局服务实例
_kronos_integrated_service = None


async def get_kronos_integrated_service() -> "KronosIntegratedDecisionService":
    """获取Kronos集成决策服务实例"""
    global _kronos_integrated_service
    if _kronos_integrated_service is None:
        _kronos_integrated_service = KronosIntegratedDecisionService()
    return _kronos_integrated_service


class KronosSignalStrength(Enum):
    """Kronos信号强度"""
    VERY_STRONG = "极强"
    STRONG = "强"
    MODERATE = "中等"
    WEAK = "弱"
    VERY_WEAK = "极弱"


@dataclass
class KronosEnhancedDecision:
    """Kronos增强决策结果"""
    symbol: str
    timestamp: datetime
    
    # Kronos预测结果
    kronos_prediction: Optional[KronosPrediction]
    kronos_signal_strength: KronosSignalStrength
    kronos_confidence: float
    
    # 传统分析结果
    technical_signal: str
    technical_confidence: float
    
    # 持仓分析结果
    position_recommendation: Optional[PositionRecommendation] = None
    position_risk: Optional[PositionRisk] = None
    
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
    market_regime: Optional[MarketRegime] = None


class KronosIntegratedDecisionService:
    """Kronos集成决策服务 - 将Kronos预测前置到所有决策流程"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 初始化依赖服务
        self.position_service = PositionAnalysisService()
        self.trend_service = TrendAnalysisService()
        self.okx_service = OKXService()
        
        # Kronos配置
        self.kronos_config = self.settings.kronos_config
        self.enable_kronos = self.kronos_config.get('enable_kronos_prediction', True)
        
    async def get_kronos_enhanced_decision(
        self,
        symbol: str,
        force_update: bool = False
    ) -> Optional[KronosEnhancedDecision]:
        """获取Kronos增强的交易决策"""
        try:
            self.logger.info(f"开始为{symbol}生成Kronos增强决策")
            
            # 第一步：获取Kronos预测（前置）
            kronos_prediction = None
            kronos_confidence = 0.0
            kronos_signal_strength = KronosSignalStrength.VERY_WEAK
            
            if self.enable_kronos:
                kronos_prediction = await self._get_kronos_prediction(symbol, force_update)
                if kronos_prediction:
                    kronos_confidence = kronos_prediction.confidence
                    kronos_signal_strength = self._evaluate_kronos_signal_strength(kronos_prediction)
                    self.logger.info(f"{symbol} Kronos预测: 置信度{kronos_confidence:.2f}, 强度{kronos_signal_strength.value}")
            
            # 第二步：基于Kronos预测调整技术分析权重
            technical_result = await self._get_weighted_technical_analysis(
                symbol, kronos_prediction
            )
            
            # 第三步：基于Kronos预测进行持仓分析
            position_analysis = await self._get_kronos_weighted_position_analysis(
                symbol, kronos_prediction
            )
            
            # 第四步：生成综合决策
            enhanced_decision = await self._generate_integrated_decision(
                symbol=symbol,
                kronos_prediction=kronos_prediction,
                kronos_confidence=kronos_confidence,
                kronos_signal_strength=kronos_signal_strength,
                technical_result=technical_result,
                position_analysis=position_analysis
            )
            
            # 记录决策日志
            trading_logger.info(
                f"Kronos增强决策 - {symbol}: {enhanced_decision.final_action} "
                f"(置信度: {enhanced_decision.final_confidence:.2f}, "
                f"信号一致性: {enhanced_decision.signal_confluence:.2f})"
            )
            
            return enhanced_decision
            
        except Exception as e:
            self.logger.error(f"生成{symbol}的Kronos增强决策失败: {e}")
            return None
    
    async def _get_kronos_prediction(
        self,
        symbol: str,
        force_update: bool = False
    ) -> Optional[KronosPrediction]:
        """获取Kronos预测"""
        try:
            kronos_service = await get_kronos_service()
            if not kronos_service:
                self.logger.warning("Kronos服务不可用")
                return None
                
            # 获取历史数据并转换为DataFrame
            from app.services.okx_service import OKXService
            import pandas as pd
            
            okx_service = OKXService()
            historical_data_raw = await okx_service.get_kline_data(symbol, "1H", 200)
            
            if historical_data_raw is not None and len(historical_data_raw) > 0:
                # 将OKX返回的字典列表转换为DataFrame
                historical_data = self._convert_kline_to_dataframe(historical_data_raw)
                
                if historical_data is not None and not historical_data.empty:
                    prediction = await kronos_service.get_prediction(
                        symbol=symbol,
                        historical_data=historical_data,
                        force_update=force_update
                    )
                else:
                    self.logger.warning(f"转换{symbol}历史数据为DataFrame失败")
                    prediction = None
            else:
                self.logger.warning(f"无法获取{symbol}的历史数据")
                prediction = None
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"获取{symbol}的Kronos预测失败: {e}")
            return None
    
    def _evaluate_kronos_signal_strength(
        self,
        prediction: KronosPrediction
    ) -> KronosSignalStrength:
        """评估Kronos信号强度 - 进一步优化的阈值"""
        confidence = prediction.confidence
        price_change = abs(prediction.price_change_pct)
        
        # 进一步优化的信号强度评估 - 大幅降低阈值以适应当前市场条件
        if confidence >= 0.70 and price_change >= 0.025:  # 70%置信度 + 2.5%变化
            return KronosSignalStrength.VERY_STRONG
        elif confidence >= 0.60 and price_change >= 0.015:  # 60%置信度 + 1.5%变化
            return KronosSignalStrength.STRONG
        elif confidence >= 0.50 and price_change >= 0.01:   # 50%置信度 + 1%变化
            return KronosSignalStrength.MODERATE
        elif confidence >= 0.40 and price_change >= 0.005:  # 40%置信度 + 0.5%变化
            return KronosSignalStrength.WEAK
        else:
            return KronosSignalStrength.VERY_WEAK
    
    async def _get_weighted_technical_analysis(
        self,
        symbol: str,
        kronos_prediction: Optional[KronosPrediction]
    ) -> Dict[str, Any]:
        """基于Kronos预测调整技术分析权重"""
        try:
            # 获取基础技术分析
            technical_result = await self.trend_service.analyze_symbol(symbol)
            
            if not kronos_prediction:
                return technical_result
            
            # 根据Kronos预测调整技术分析权重
            kronos_direction = "bullish" if kronos_prediction.price_change_pct > 0 else "bearish"
            kronos_confidence = kronos_prediction.confidence
            
            # 如果Kronos预测与技术分析一致，增强信号
            technical_signal = technical_result.get('overall_signal', 'neutral')
            
            if (kronos_direction == "bullish" and technical_signal in ["bullish", "strong_bullish"]) or \
               (kronos_direction == "bearish" and technical_signal in ["bearish", "strong_bearish"]):
                # 信号一致，增强置信度
                original_confidence = technical_result.get('confidence', 0.5)
                enhanced_confidence = min(0.95, original_confidence + kronos_confidence * 0.3)
                technical_result['confidence'] = enhanced_confidence
                technical_result['kronos_enhanced'] = True
                
            return technical_result
            
        except Exception as e:
            self.logger.error(f"获取{symbol}加权技术分析失败: {e}")
            return {}
    
    async def _get_kronos_weighted_position_analysis(
        self,
        symbol: str,
        kronos_prediction: Optional[KronosPrediction]
    ) -> Dict[str, Any]:
        """基于Kronos预测进行持仓分析"""
        try:
            # 获取基础持仓分析 - 使用账户整体分析
            position_analysis = await self.position_service.analyze_account_positions()
            
            if not kronos_prediction:
                return position_analysis
            
            # 根据Kronos预测调整持仓建议 - 降低阈值，增加敏感度
            kronos_confidence = kronos_prediction.confidence
            predicted_change = kronos_prediction.price_change_pct
            
            # 降低Kronos预测阈值，增加持仓调整建议
            if kronos_confidence >= 0.6:  # 从0.7降低到0.6
                if predicted_change > 0.03:  # 从5%降低到3%
                    if position_analysis.get('recommendation') == PositionRecommendation.HOLD:
                        position_analysis['recommendation'] = PositionRecommendation.INCREASE
                        position_analysis['kronos_adjustment'] = f"Kronos预测上涨{predicted_change*100:.1f}%，建议加仓"
                elif predicted_change < -0.03:  # 从-5%调整到-3%
                    if position_analysis.get('recommendation') == PositionRecommendation.HOLD:
                        position_analysis['recommendation'] = PositionRecommendation.REDUCE
                        position_analysis['kronos_adjustment'] = f"Kronos预测下跌{abs(predicted_change)*100:.1f}%，建议减仓"
            
            # 新增：中等置信度的温和调整建议
            elif kronos_confidence >= 0.5:
                if predicted_change > 0.02:
                    position_analysis['kronos_suggestion'] = f"Kronos预测温和上涨{predicted_change*100:.1f}%，可考虑小幅加仓"
                elif predicted_change < -0.02:
                    position_analysis['kronos_suggestion'] = f"Kronos预测温和下跌{abs(predicted_change)*100:.1f}%，可考虑小幅减仓"
            
            # 添加Kronos持仓分析报告
            position_analysis['kronos_analysis'] = {
                'confidence': kronos_confidence,
                'predicted_change_pct': predicted_change,
                'predicted_direction': '看涨' if predicted_change > 0 else '看跌',
                'risk_assessment': self._assess_kronos_risk(kronos_confidence, predicted_change),
                'position_impact': self._evaluate_position_impact(symbol, predicted_change)
            }
            
            return position_analysis
            
        except Exception as e:
            self.logger.error(f"获取{symbol}Kronos加权持仓分析失败: {e}")
            return {}
    
    def _assess_kronos_risk(self, confidence: float, predicted_change: float) -> str:
        """评估Kronos预测的风险等级"""
        risk_score = abs(predicted_change) * confidence
        
        if risk_score > 0.05:
            return "高风险"
        elif risk_score > 0.03:
            return "中等风险"
        else:
            return "低风险"
    
    def _evaluate_position_impact(self, symbol: str, predicted_change: float) -> str:
        """评估对持仓的影响"""
        abs_change = abs(predicted_change)
        
        if abs_change > 0.05:
            return f"对{symbol}持仓影响显著，建议密切关注"
        elif abs_change > 0.03:
            return f"对{symbol}持仓有一定影响，建议适度调整"
        else:
            return f"对{symbol}持仓影响较小，可保持现状"    

    async def _generate_integrated_decision(
        self,
        symbol: str,
        kronos_prediction: Optional[KronosPrediction],
        kronos_confidence: float,
        kronos_signal_strength: KronosSignalStrength,
        technical_result: Dict[str, Any],
        position_analysis: Dict[str, Any]
    ) -> KronosEnhancedDecision:
        """生成综合决策"""
        try:
            current_time = datetime.now()
            
            # 提取技术分析结果
            technical_signal = technical_result.get('overall_signal', 'neutral')
            technical_confidence = technical_result.get('confidence', 0.5)
            
            # 提取持仓分析结果 - 安全处理可能的None值
            position_recommendation = position_analysis.get('recommendation')
            if position_recommendation is None:
                position_recommendation = PositionRecommendation.HOLD
            
            position_risk = position_analysis.get('risk_level')
            if position_risk is None:
                position_risk = PositionRisk.MEDIUM
            
            # 计算信号一致性
            signal_confluence = self._calculate_signal_confluence(
                kronos_prediction, technical_signal, position_recommendation
            )
            
            # 生成最终决策
            final_action, final_confidence = self._determine_final_action(
                kronos_prediction, kronos_confidence, technical_signal, 
                technical_confidence, position_recommendation, signal_confluence
            )
            
            # 计算风险管理参数
            risk_params = await self._calculate_risk_management(
                symbol, kronos_prediction, final_action, final_confidence
            )
            
            # 判断市场状态
            market_regime = self._determine_market_regime(
                kronos_prediction, technical_result
            )
            
            # 生成决策依据
            reasoning = self._generate_reasoning(
                kronos_prediction, kronos_signal_strength, technical_signal,
                position_recommendation, signal_confluence, final_action
            )
            
            return KronosEnhancedDecision(
                symbol=symbol,
                timestamp=current_time,
                kronos_prediction=kronos_prediction,
                kronos_signal_strength=kronos_signal_strength,
                kronos_confidence=kronos_confidence,
                technical_signal=technical_signal,
                technical_confidence=technical_confidence,
                position_recommendation=position_recommendation,
                position_risk=position_risk,
                final_action=final_action,
                final_confidence=final_confidence,
                signal_confluence=signal_confluence,
                entry_price=risk_params.get('entry_price'),
                stop_loss=risk_params.get('stop_loss'),
                take_profit=risk_params.get('take_profit'),
                position_size=risk_params.get('position_size', 0.1),
                reasoning=reasoning,
                market_regime=market_regime
            )
            
        except Exception as e:
            self.logger.error(f"生成{symbol}综合决策失败: {e}")
            raise TradingToolError(f"决策生成失败: {str(e)}")
    
    def _calculate_signal_confluence(
        self,
        kronos_prediction: Optional[KronosPrediction],
        technical_signal: str,
        position_recommendation: PositionRecommendation
    ) -> float:
        """计算信号一致性评分 - 动态计算，不固定基础分"""
        confluence_score = 0.0
        
        if not kronos_prediction:
            return 0.5  # 没有Kronos预测时返回中性评分
        
        kronos_direction = "bullish" if kronos_prediction.price_change_pct > 0 else "bearish"
        kronos_confidence = kronos_prediction.confidence
        
        # Kronos与技术分析一致性 (权重40%)
        if (kronos_direction == "bullish" and technical_signal in ["bullish", "strong_bullish"]) or \
           (kronos_direction == "bearish" and technical_signal in ["bearish", "strong_bearish"]):
            confluence_score += 0.4 * kronos_confidence  # 根据Kronos置信度调整
        elif technical_signal == "neutral":
            confluence_score += 0.2  # 中性信号给予部分分数
        
        # Kronos与持仓建议一致性 (权重30%)
        if kronos_direction == "bullish" and position_recommendation in [PositionRecommendation.INCREASE, PositionRecommendation.HOLD]:
            confluence_score += 0.3 * kronos_confidence
        elif kronos_direction == "bearish" and position_recommendation in [PositionRecommendation.REDUCE, PositionRecommendation.CLOSE]:
            confluence_score += 0.3 * kronos_confidence
        elif position_recommendation == PositionRecommendation.HOLD:
            confluence_score += 0.15  # 持有建议给予部分分数
        
        # 信号强度加成 (权重30%)
        predicted_change = abs(kronos_prediction.price_change_pct)
        if predicted_change >= 0.05:  # 预测变化>=5%
            confluence_score += 0.3
        elif predicted_change >= 0.03:  # 预测变化>=3%
            confluence_score += 0.2
        elif predicted_change >= 0.01:  # 预测变化>=1%
            confluence_score += 0.1
        
        return min(1.0, confluence_score)
    
    async def batch_analyze_symbols(
        self,
        symbols: List[str],
        force_update: bool = False
    ) -> Dict[str, Optional[KronosEnhancedDecision]]:
        """批量分析多个交易对"""
        results = {}
        
        for symbol in symbols:
            try:
                # 确保symbol格式正确
                if not symbol.endswith("-SWAP"):
                    symbol = f"{symbol}-USDT-SWAP"
                
                decision = await self.get_kronos_enhanced_decision(symbol, force_update)
                results[symbol] = decision
                
            except Exception as e:
                self.logger.error(f"批量分析{symbol}失败: {e}")
                results[symbol] = None
        
        return results
    
    def _determine_final_action(
        self,
        kronos_prediction: Optional[KronosPrediction],
        kronos_confidence: float,
        technical_signal: str,
        technical_confidence: float,
        position_recommendation: PositionRecommendation,
        signal_confluence: float
    ) -> Tuple[str, float]:
        """确定最终交易行动"""
        
        # 如果没有Kronos预测，主要依赖技术分析
        if not kronos_prediction:
            return self._fallback_to_technical_decision(technical_signal, technical_confidence)
        
        # 动态权重计算 - 根据Kronos置信度调整权重
        if kronos_confidence >= 0.8:
            kronos_weight = 0.8  # 高置信度时给Kronos 80%权重
            technical_weight = 0.2
        elif kronos_confidence >= 0.6:
            kronos_weight = 0.7  # 中等置信度时给Kronos 70%权重
            technical_weight = 0.3
        else:
            kronos_weight = 0.5  # 低置信度时平衡权重
            technical_weight = 0.5
        
        # 优化的综合置信度计算
        base_confidence = (kronos_confidence * kronos_weight + 
                          technical_confidence * technical_weight)
        
        # 信号一致性加成 - 一致性越高，置信度越高
        confluence_bonus = signal_confluence * 0.2  # 最多20%加成
        combined_confidence = min(0.95, base_confidence + confluence_bonus)
        
        # 决策逻辑 - 优化：考虑当前趋势和预测的一致性
        kronos_direction = "bullish" if kronos_prediction.price_change_pct > 0 else "bearish"
        predicted_change = abs(kronos_prediction.price_change_pct)
        
        # 检查技术分析和Kronos预测的一致性
        tech_bullish = technical_signal in ["bullish", "strong_bullish"]
        tech_bearish = technical_signal in ["bearish", "strong_bearish"]
        
        # 特殊处理：对于回调预测要更谨慎 - 优先级最高
        if kronos_direction == "bearish":
            # 大幅回调预测时，除非技术分析也确认看跌，否则建议观望
            if not tech_bearish:
                return "谨慎观望", combined_confidence * 0.7
            # 即使技术分析确认看跌，也要给出更温和的建议
            elif predicted_change >= 0.05:  # 预测下跌超过5%
                return "谨慎减仓", combined_confidence * 0.8
        
        # 特殊处理：如果技术分析显示强势上涨，即使Kronos预测回调也要谨慎
        if technical_signal == "strong_bullish" and kronos_direction == "bearish":
            # 强势上涨中的回调预测，降级为持有观望而不是卖出
            return "持有观望", combined_confidence * 0.8
        
        # 强信号判断 - 需要Kronos和技术分析方向一致
        if kronos_confidence >= 0.7 and predicted_change >= 0.03:
            if kronos_direction == "bullish" and (tech_bullish or technical_signal == "neutral"):
                return "强烈买入", min(0.95, combined_confidence)
            elif kronos_direction == "bearish" and (tech_bearish or technical_signal == "neutral"):
                return "强烈卖出", min(0.95, combined_confidence)
            # 如果方向不一致，降级为中等信号
            elif kronos_direction == "bullish":
                return "买入", combined_confidence * 0.8
            else:
                return "卖出", combined_confidence * 0.8
        
        # 中等信号判断 - 降低要求但增加方向一致性检查
        elif kronos_confidence >= 0.55 and predicted_change >= 0.02:
            if kronos_direction == "bullish" and not tech_bearish:  # Kronos看涨且技术分析不看跌
                return "买入", combined_confidence
            elif kronos_direction == "bearish" and not tech_bullish:  # Kronos看跌且技术分析不看涨
                return "卖出", combined_confidence
            # 方向冲突时，倾向于持有观望
            else:
                return "持有观望", combined_confidence * 0.7
        
        # 弱信号判断 - 要求方向一致
        elif signal_confluence >= 0.6:
            if kronos_direction == "bullish" and tech_bullish:
                return "谨慎买入", combined_confidence
            elif kronos_direction == "bearish" and tech_bearish:
                return "谨慎卖出", combined_confidence
        
        # 新增：基于技术分析的补充信号
        elif technical_signal in ["strong_bullish", "strong_bearish"] and kronos_confidence >= 0.4:
            if technical_signal == "strong_bullish":
                return "技术买入", combined_confidence
            else:
                return "技术卖出", combined_confidence
        
        return "持有观望", combined_confidence
    
    def _fallback_to_technical_decision(
        self,
        technical_signal: str,
        technical_confidence: float
    ) -> Tuple[str, float]:
        """回退到技术分析决策"""
        signal_mapping = {
            "strong_bullish": "强烈买入",
            "bullish": "买入",
            "neutral": "持有观望",
            "bearish": "卖出",
            "strong_bearish": "强烈卖出"
        }
        
        action = signal_mapping.get(technical_signal, "持有观望")
        return action, technical_confidence
    
    async def _calculate_risk_management(
        self,
        symbol: str,
        kronos_prediction: Optional[KronosPrediction],
        final_action: str,
        final_confidence: float
    ) -> Dict[str, Any]:
        """计算风险管理参数"""
        try:
            # 获取当前价格
            current_price = await self.okx_service.get_current_price(symbol)
            if not current_price:
                return {}
            
            risk_params = {
                'entry_price': current_price,
                'position_size': self._calculate_position_size(final_confidence)
            }
            
            # 如果有Kronos预测，使用预测价格计算止损止盈
            if kronos_prediction:
                predicted_price = current_price * (1 + kronos_prediction.price_change_pct)
                
                if "买入" in final_action:
                    # 买入信号的止损止盈
                    risk_params['stop_loss'] = current_price * 0.97  # 3%止损
                    risk_params['take_profit'] = max(predicted_price, current_price * 1.05)  # 至少5%止盈
                elif "卖出" in final_action:
                    # 卖出信号的止损止盈
                    risk_params['stop_loss'] = current_price * 1.03  # 3%止损
                    risk_params['take_profit'] = min(predicted_price, current_price * 0.95)  # 至少5%止盈
            else:
                # 没有Kronos预测时的默认风险管理
                if "买入" in final_action:
                    risk_params['stop_loss'] = current_price * 0.95  # 5%止损
                    risk_params['take_profit'] = current_price * 1.10  # 10%止盈
                elif "卖出" in final_action:
                    risk_params['stop_loss'] = current_price * 1.05  # 5%止损
                    risk_params['take_profit'] = current_price * 0.90  # 10%止盈
            
            return risk_params
            
        except Exception as e:
            self.logger.error(f"计算{symbol}风险管理参数失败: {e}")
            return {'position_size': 0.05}  # 默认小仓位
    
    def _calculate_position_size(self, confidence: float) -> float:
        """根据置信度计算仓位大小"""
        base_size = 0.1  # 基础仓位10%
        
        if confidence >= 0.9:
            return min(0.3, base_size * 3)  # 最大30%
        elif confidence >= 0.8:
            return min(0.25, base_size * 2.5)
        elif confidence >= 0.7:
            return min(0.2, base_size * 2)
        elif confidence >= 0.6:
            return min(0.15, base_size * 1.5)
        else:
            return min(0.05, base_size * 0.5)  # 最小5%
    
    def _determine_market_regime(
        self,
        kronos_prediction: Optional[KronosPrediction],
        technical_result: Dict[str, Any]
    ) -> MarketRegime:
        """判断市场状态"""
        # 基于技术分析判断基础市场状态
        volatility = technical_result.get('volatility', 'medium')
        trend_strength = technical_result.get('trend_strength', 0.5)
        
        # 如果有Kronos预测，结合预测结果
        if kronos_prediction:
            predicted_change = abs(kronos_prediction.price_change_pct)
            
            if predicted_change >= 0.1:  # 预测10%以上变化
                return MarketRegime.VOLATILE
            elif predicted_change >= 0.05:
                if kronos_prediction.price_change_pct > 0:
                    return MarketRegime.TRENDING_UP
                else:
                    return MarketRegime.TRENDING_DOWN
        
        # 回退到技术分析判断
        if volatility == 'high':
            return MarketRegime.VOLATILE
        elif trend_strength >= 0.7:
            technical_signal = technical_result.get('overall_signal', 'neutral')
            if 'bullish' in technical_signal:
                return MarketRegime.TRENDING_UP
            elif 'bearish' in technical_signal:
                return MarketRegime.TRENDING_DOWN
        elif volatility == 'low':
            return MarketRegime.CALM
        
        return MarketRegime.RANGING
    
    def _convert_kline_to_dataframe(self, kline_data: List[Dict]) -> Optional[pd.DataFrame]:
        """
        将OKX返回的K线数据转换为Kronos需要的DataFrame格式
        
        Args:
            kline_data: OKX返回的K线数据列表
            
        Returns:
            转换后的DataFrame，包含Kronos需要的列
        """
        try:
            import pandas as pd
            from datetime import datetime
            
            if not kline_data:
                return None
            
            # 转换为DataFrame
            df_data = []
            for item in kline_data:
                df_data.append({
                    'timestamp': pd.to_datetime(item['timestamp'], unit='ms'),
                    'open': float(item['open']),
                    'high': float(item['high']),
                    'low': float(item['low']),
                    'close': float(item['close']),
                    'volume': float(item['volume'])
                })
            
            df = pd.DataFrame(df_data)
            
            # 按时间排序（确保时间序列正确）
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # 设置timestamp为索引（Kronos可能需要）
            df.set_index('timestamp', inplace=True)
            
            self.logger.debug(f"成功转换K线数据为DataFrame: {len(df)}行数据")
            return df
            
        except Exception as e:
            self.logger.error(f"转换K线数据为DataFrame失败: {e}")
            return None
    
    def _generate_reasoning(
        self,
        kronos_prediction: Optional[KronosPrediction],
        kronos_signal_strength: KronosSignalStrength,
        technical_signal: str,
        position_recommendation: PositionRecommendation,
        signal_confluence: float,
        final_action: str
    ) -> str:
        """生成决策依据说明"""
        reasoning_parts = []
        
        # Kronos预测部分
        if kronos_prediction:
            change_pct = kronos_prediction.price_change_pct * 100
            reasoning_parts.append(
                f"Kronos预测: {change_pct:+.2f}% (置信度: {kronos_prediction.confidence:.2f}, "
                f"信号强度: {kronos_signal_strength.value})"
            )
        else:
            reasoning_parts.append("Kronos预测: 不可用")
        
        # 技术分析部分
        reasoning_parts.append(f"技术分析: {technical_signal}")
        
        # 持仓建议部分
        reasoning_parts.append(f"持仓建议: {position_recommendation.value}")
        
        # 信号一致性
        reasoning_parts.append(f"信号一致性: {signal_confluence:.2f}")
        
        # 最终决策
        reasoning_parts.append(f"综合决策: {final_action}")
        
        return " | ".join(reasoning_parts)
    
    async def batch_analyze_symbols(
        self,
        symbols: List[str],
        force_update: bool = False
    ) -> Dict[str, Optional[KronosEnhancedDecision]]:
        """批量分析多个交易对"""
        try:
            self.logger.info(f"开始批量分析{len(symbols)}个交易对")
            
            # 并发分析所有交易对
            tasks = [
                self.get_kronos_enhanced_decision(symbol, force_update)
                for symbol in symbols
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 整理结果
            analysis_results = {}
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    self.logger.error(f"分析{symbol}失败: {result}")
                    analysis_results[symbol] = None
                else:
                    analysis_results[symbol] = result
            
            successful_count = sum(1 for r in analysis_results.values() if r is not None)
            self.logger.info(f"批量分析完成: {successful_count}/{len(symbols)}个成功")
            
            return analysis_results
            
        except Exception as e:
            self.logger.error(f"批量分析失败: {e}")
            return {}