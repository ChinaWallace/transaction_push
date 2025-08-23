# -*- coding: utf-8 -*-
"""
交易通知服务
Trading Notification Service - 发送综合交易建议通知
"""

from typing import Dict, Any, List
from datetime import datetime

from app.core.logging import get_logger, trading_logger
from app.services.notification_service import NotificationService
from app.services.trading_decision_service import PositionRecommendation, MarketAnalysis, TradingAction, RiskLevel

logger = get_logger(__name__)


class TradingNotificationService:
    """交易通知服务类"""
    
    def __init__(self):
        self.notification_service = NotificationService()
    
    async def send_trading_recommendation(self, recommendation: PositionRecommendation) -> Dict[str, bool]:
        """
        发送交易建议通知
        
        Args:
            recommendation: 交易建议
            
        Returns:
            各渠道发送结果
        """
        try:
            # 构建消息内容
            message = self._format_recommendation_message(recommendation)
            
            # 根据交易动作确定优先级
            priority = self._get_recommendation_priority(recommendation)
            
            # 发送通知
            result = await self.notification_service.send_notification(
                message=message,
                priority=priority,
                subject=f"🎯 交易建议 - {recommendation.symbol}"
            )
            
            trading_logger.info(
                f"Trading recommendation sent for {recommendation.symbol}: "
                f"{recommendation.action.value} (confidence: {recommendation.confidence:.1f}%)"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send trading recommendation: {e}")
            return {}
    
    async def send_market_analysis(self, analysis: MarketAnalysis) -> Dict[str, bool]:
        """
        发送市场分析通知
        
        Args:
            analysis: 市场分析结果
            
        Returns:
            各渠道发送结果
        """
        try:
            # 构建消息内容
            message = self._format_analysis_message(analysis)
            
            # 发送通知
            result = await self.notification_service.send_notification(
                message=message,
                priority="normal",
                subject=f"📊 市场分析 - {analysis.symbol}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send market analysis: {e}")
            return {}
    
    def _format_recommendation_message(self, rec: PositionRecommendation) -> str:
        """格式化交易建议消息"""
        
        # 动作图标映射
        action_icons = {
            TradingAction.STRONG_BUY: "🚀",
            TradingAction.BUY: "📈",
            TradingAction.HOLD: "⏸️",
            TradingAction.SELL: "📉",
            TradingAction.STRONG_SELL: "💥",
            TradingAction.WAIT: "⏳"
        }
        
        # 动作描述映射
        action_descriptions = {
            TradingAction.STRONG_BUY: "强烈建议买入",
            TradingAction.BUY: "建议买入",
            TradingAction.HOLD: "建议持有",
            TradingAction.SELL: "建议卖出",
            TradingAction.STRONG_SELL: "强烈建议卖出",
            TradingAction.WAIT: "等待更好时机"
        }
        
        # 风险等级图标
        risk_icons = {
            RiskLevel.VERY_LOW: "🟢",
            RiskLevel.LOW: "🟡",
            RiskLevel.MEDIUM: "🟠",
            RiskLevel.HIGH: "🔴",
            RiskLevel.VERY_HIGH: "🚨"
        }
        
        icon = action_icons.get(rec.action, "🎯")
        description = action_descriptions.get(rec.action, "未知动作")
        risk_icon = risk_icons.get(rec.risk_level, "⚪")
        
        message = f"""🎯 **综合交易建议**

{icon} **交易对**: {rec.symbol}
📊 **建议动作**: {description}
🎯 **信号置信度**: {rec.confidence:.1f}%

💰 **仓位管理**:
📈 建议仓位: {rec.position_size_percent:.1f}%
⚡ 建议杠杆: {rec.leverage:.1f}x
🛡️ 止损位: -{rec.stop_loss_percent:.1f}%
🎯 止盈位: +{rec.take_profit_percent:.1f}%

{risk_icon} **风险等级**: {rec.risk_level.value.upper()}

🕐 **时机建议**:
⏰ 入场时机: {self._format_entry_timing(rec.entry_timing)}"""

        if rec.hold_duration_hours:
            message += f"\n⏱️ 建议持仓: {rec.hold_duration_hours}小时"

        # 添加支撑阻力位
        if rec.support_levels:
            support_str = " | ".join([f"{level:.2f}" for level in rec.support_levels[:3]])
            message += f"\n📉 支撑位: {support_str}"
        
        if rec.resistance_levels:
            resistance_str = " | ".join([f"{level:.2f}" for level in rec.resistance_levels[:3]])
            message += f"\n📈 阻力位: {resistance_str}"

        message += f"""

🧠 **决策依据**:
{rec.reasoning}

⚠️ **风险提示**: 
• 本建议仅供参考，请结合自身风险承受能力
• 严格执行止损，控制风险
• 市场有风险，投资需谨慎

⏰ **分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

        return message
    
    def _format_analysis_message(self, analysis: MarketAnalysis) -> str:
        """格式化市场分析消息"""
        
        # 市场状态图标
        regime_icons = {
            "trending": "📈",
            "ranging": "↔️",
            "volatile": "🌊",
            "calm": "😴"
        }
        
        regime_icon = regime_icons.get(analysis.market_regime, "📊")
        
        message = f"""📊 **市场深度分析**

📈 **交易对**: {analysis.symbol}
{regime_icon} **市场状态**: {analysis.market_regime.upper()}
💪 **趋势强度**: {analysis.trend_strength:.1%}

📊 **综合评分**:
🟢 看涨评分: {analysis.bullish_score:.1f}/100
🔴 看跌评分: {analysis.bearish_score:.1f}/100
🌊 波动评分: {analysis.volatility_score:.1f}/100

🔧 **技术指标**:"""

        # 传统技术分析
        if analysis.traditional_signals:
            signal = analysis.traditional_signals.get('overall_signal', 'unknown')
            strength = analysis.traditional_signals.get('signal_strength', 0)
            message += f"\n📈 技术信号: {signal.upper()} (强度: {strength:.1%})"
        
        # ML预测
        if analysis.ml_prediction:
            ml_signal = analysis.ml_prediction.get('signal', 'unknown')
            ml_confidence = analysis.ml_prediction.get('confidence', 0)
            message += f"\n🤖 ML预测: {ml_signal.upper()} (置信度: {ml_confidence:.1%})"
        
        # 异常检测
        if analysis.ml_anomalies:
            high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
            message += f"\n⚠️ 异常检测: {len(analysis.ml_anomalies)}个异常"
            if high_anomalies > 0:
                message += f" (其中{high_anomalies}个高风险)"

        message += f"""

⏰ **分析时间**: {analysis.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

💡 **使用建议**: 
• 结合多个时间周期确认信号
• 关注成交量配合情况
• 注意风险管理和资金管理"""

        return message
    
    def _format_entry_timing(self, timing: str) -> str:
        """格式化入场时机"""
        timing_map = {
            "immediate": "立即入场",
            "wait_for_dip": "等待回调",
            "wait_for_breakout": "等待突破",
            "wait_for_confirmation": "等待确认",
            "wait_for_signal": "等待信号",
            "wait_for_calm": "等待平静"
        }
        return timing_map.get(timing, timing)
    
    def _get_recommendation_priority(self, rec: PositionRecommendation) -> str:
        """获取建议优先级"""
        if rec.action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            return "high"
        elif rec.action in [TradingAction.BUY, TradingAction.SELL]:
            return "normal"
        elif rec.risk_level in [RiskLevel.HIGH, RiskLevel.VERY_HIGH]:
            return "high"
        else:
            return "low"
    
    async def send_risk_alert(self, symbol: str, risk_message: str) -> Dict[str, bool]:
        """
        发送风险警报
        
        Args:
            symbol: 交易对
            risk_message: 风险消息
            
        Returns:
            各渠道发送结果
        """
        try:
            message = f"""🚨 **风险警报**

📈 **交易对**: {symbol}
⚠️ **风险提示**: {risk_message}

🛡️ **建议措施**:
• 立即检查当前持仓
• 考虑降低杠杆或减仓
• 严格执行止损策略
• 暂停新开仓位

⏰ **警报时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

            result = await self.notification_service.send_notification(
                message=message,
                priority="urgent",
                subject=f"🚨 风险警报 - {symbol}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send risk alert: {e}")
            return {}