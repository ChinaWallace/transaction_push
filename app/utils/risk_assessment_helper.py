# -*- coding: utf-8 -*-
"""
风险评估助手
Risk Assessment Helper - 智能风险提示和仓位建议
"""

from typing import Dict, Any, Optional
from enum import Enum

class RiskLevel(Enum):
    """风险等级"""
    LOW = "低风险"
    MEDIUM = "中等风险"
    HIGH = "高风险"
    EXTREME = "极高风险"

class PositionSizeRecommendation(Enum):
    """仓位建议"""
    LIGHT = "轻仓"
    NORMAL = "正常仓位"
    HEAVY = "重仓"
    AVOID = "避免交易"

class RiskAssessmentHelper:
    """风险评估助手"""
    
    @staticmethod
    def assess_trading_risk(
        action: str,
        confidence: float,
        signal_strength: str,
        market_volatility: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        评估交易风险
        
        Args:
            action: 交易动作 (买入/卖出/持有)
            confidence: 置信度 (0-1)
            signal_strength: 信号强度
            market_volatility: 市场波动率
            
        Returns:
            Dict: 风险评估结果
        """
        
        # 基础风险评估
        risk_level = RiskAssessmentHelper._calculate_base_risk(action, confidence, signal_strength)
        
        # 仓位建议
        position_recommendation = RiskAssessmentHelper._calculate_position_size(
            action, confidence, risk_level, market_volatility
        )
        
        # 风险提示文本
        risk_message = RiskAssessmentHelper._generate_risk_message(
            action, confidence, risk_level, position_recommendation
        )
        
        return {
            "risk_level": risk_level,
            "position_recommendation": position_recommendation,
            "risk_message": risk_message,
            "confidence_assessment": RiskAssessmentHelper._assess_confidence_level(confidence)
        }
    
    @staticmethod
    def _calculate_base_risk(action: str, confidence: float, signal_strength: str) -> RiskLevel:
        """计算基础风险等级"""
        
        # 持有/观望的风险最低
        if "持有" in action or "观望" in action:
            return RiskLevel.LOW
        
        # 根据置信度和信号强度评估风险
        if confidence >= 0.8 and "强" in signal_strength:
            return RiskLevel.LOW
        elif confidence >= 0.6 and ("中" in signal_strength or "强" in signal_strength):
            return RiskLevel.MEDIUM
        elif confidence >= 0.4:
            return RiskLevel.HIGH
        else:
            return RiskLevel.EXTREME
    
    @staticmethod
    def _calculate_position_size(
        action: str, 
        confidence: float, 
        risk_level: RiskLevel,
        market_volatility: Optional[float] = None
    ) -> PositionSizeRecommendation:
        """计算仓位建议"""
        
        # 持有/观望不涉及仓位调整
        if "持有" in action or "观望" in action:
            return PositionSizeRecommendation.NORMAL
        
        # 根据风险等级和置信度确定仓位
        if risk_level == RiskLevel.EXTREME:
            return PositionSizeRecommendation.AVOID
        elif risk_level == RiskLevel.HIGH:
            return PositionSizeRecommendation.LIGHT
        elif risk_level == RiskLevel.MEDIUM:
            if confidence >= 0.7:
                return PositionSizeRecommendation.NORMAL
            else:
                return PositionSizeRecommendation.LIGHT
        else:  # LOW risk
            if confidence >= 0.8:
                return PositionSizeRecommendation.HEAVY
            else:
                return PositionSizeRecommendation.NORMAL
    
    @staticmethod
    def _generate_risk_message(
        action: str,
        confidence: float, 
        risk_level: RiskLevel,
        position_recommendation: PositionSizeRecommendation
    ) -> str:
        """生成风险提示消息"""
        
        # 持有/观望的特殊处理
        if "持有" in action or "观望" in action:
            if confidence >= 0.8:
                return "⚠️ 高置信度观望信号，建议耐心等待更明确的交易机会"
            elif confidence >= 0.6:
                return "📊 中等置信度观望，市场信号不够明确，建议继续观察"
            else:
                return "🔍 低置信度信号，市场方向不明，建议谨慎观望"
        
        # 交易信号的风险提示
        confidence_desc = RiskAssessmentHelper._get_confidence_description(confidence)
        
        if risk_level == RiskLevel.LOW:
            if position_recommendation == PositionSizeRecommendation.HEAVY:
                return f"✅ {confidence_desc}，信号质量较高，可适当加大仓位"
            else:
                return f"✅ {confidence_desc}，建议正常仓位操作"
        elif risk_level == RiskLevel.MEDIUM:
            return f"⚠️ {confidence_desc}，建议控制仓位，注意风险管理"
        elif risk_level == RiskLevel.HIGH:
            return f"🚨 {confidence_desc}，建议轻仓操作，严格止损"
        else:  # EXTREME
            return f"❌ {confidence_desc}，信号不可靠，建议避免交易"
    
    @staticmethod
    def _assess_confidence_level(confidence: float) -> str:
        """评估置信度等级"""
        if confidence >= 0.8:
            return "高置信度"
        elif confidence >= 0.6:
            return "中等置信度"
        elif confidence >= 0.4:
            return "低置信度"
        else:
            return "极低置信度"
    
    @staticmethod
    def _get_confidence_description(confidence: float) -> str:
        """获取置信度描述"""
        if confidence >= 0.8:
            return "高置信度信号"
        elif confidence >= 0.6:
            return "中等置信度信号"
        elif confidence >= 0.4:
            return "低置信度信号"
        else:
            return "极低置信度信号"