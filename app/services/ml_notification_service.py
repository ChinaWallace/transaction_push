# -*- coding: utf-8 -*-
"""
机器学习通知服务
ML Notification Service for sending ML predictions and anomaly alerts
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.notification_service import NotificationService
from app.services.ml_enhanced_service import MLPrediction, AnomalyDetection, PredictionSignal, AnomalyType

logger = get_logger(__name__)
settings = get_settings()


class MLNotificationService:
    """机器学习通知服务类"""
    
    def __init__(self):
        self.notification_service = NotificationService()
    
    async def send_ml_prediction_alert(self, prediction: MLPrediction) -> Dict[str, bool]:
        """
        发送ML预测信号通知
        
        Args:
            prediction: ML预测结果
            
        Returns:
            各渠道发送结果
        """
        try:
            # 构建消息内容
            message = self._format_prediction_message(prediction)
            
            # 根据信号强度确定优先级
            priority = self._get_signal_priority(prediction.signal)
            
            # 发送通知
            result = await self.notification_service.send_notification(
                message=message,
                priority=priority,
                subject=f"🤖 ML预测信号 - {prediction.symbol}"
            )
            
            trading_logger.info(f"ML prediction alert sent for {prediction.symbol}: {prediction.signal.value}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send ML prediction alert: {e}")
            return {}
    
    async def send_anomaly_alert(self, anomalies: List[AnomalyDetection]) -> Dict[str, bool]:
        """
        发送异常检测通知
        
        Args:
            anomalies: 异常检测结果列表
            
        Returns:
            各渠道发送结果
        """
        try:
            if not anomalies:
                return {}
            
            # 构建消息内容
            message = self._format_anomaly_message(anomalies)
            
            # 根据异常严重程度确定优先级
            max_severity = max(anomaly.severity for anomaly in anomalies)
            priority = "urgent" if max_severity > 0.8 else "high" if max_severity > 0.5 else "normal"
            
            # 发送通知
            result = await self.notification_service.send_notification(
                message=message,
                priority=priority,
                subject=f"⚠️ 市场异常检测 - {len(anomalies)}个异常"
            )
            
            trading_logger.info(f"Anomaly alert sent: {len(anomalies)} anomalies detected")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send anomaly alert: {e}")
            return {}
    
    def _format_prediction_message(self, prediction: MLPrediction) -> str:
        """格式化预测信号消息"""
        
        # 信号图标映射
        signal_icons = {
            PredictionSignal.STRONG_BUY: "🚀",
            PredictionSignal.BUY: "📈",
            PredictionSignal.HOLD: "⏸️",
            PredictionSignal.SELL: "📉",
            PredictionSignal.STRONG_SELL: "💥"
        }
        
        # 信号描述映射
        signal_descriptions = {
            PredictionSignal.STRONG_BUY: "强烈买入",
            PredictionSignal.BUY: "买入",
            PredictionSignal.HOLD: "持有",
            PredictionSignal.SELL: "卖出",
            PredictionSignal.STRONG_SELL: "强烈卖出"
        }
        
        icon = signal_icons.get(prediction.signal, "🤖")
        description = signal_descriptions.get(prediction.signal, "未知")
        
        message = f"""🤖 **机器学习预测信号**

{icon} **交易对**: {prediction.symbol}
📊 **预测信号**: {description}
🎯 **置信度**: {prediction.confidence:.1%}
📈 **模型准确率**: {prediction.model_accuracy:.1%}

**概率分布**:
🚀 强烈买入: {prediction.probability_distribution.get('strong_buy', 0):.1%}
📈 买入: {prediction.probability_distribution.get('buy', 0):.1%}
⏸️ 持有: {prediction.probability_distribution.get('hold', 0):.1%}
📉 卖出: {prediction.probability_distribution.get('sell', 0):.1%}
💥 强烈卖出: {prediction.probability_distribution.get('strong_sell', 0):.1%}

⏰ **预测时间**: {prediction.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

💡 **投资建议**: 请结合其他技术指标和基本面分析做出投资决策"""

        return message
    
    def _format_anomaly_message(self, anomalies: List[AnomalyDetection]) -> str:
        """格式化异常检测消息"""
        
        # 异常类型图标映射
        anomaly_icons = {
            AnomalyType.PRICE_ANOMALY: "💰",
            AnomalyType.VOLUME_ANOMALY: "📊",
            AnomalyType.TREND_ANOMALY: "📈",
            AnomalyType.PATTERN_ANOMALY: "🔍"
        }
        
        # 异常类型描述映射
        anomaly_descriptions = {
            AnomalyType.PRICE_ANOMALY: "价格异常",
            AnomalyType.VOLUME_ANOMALY: "成交量异常",
            AnomalyType.TREND_ANOMALY: "趋势异常",
            AnomalyType.PATTERN_ANOMALY: "模式异常"
        }
        
        message = "⚠️ **市场异常检测报告**\n\n"
        
        # 按交易对分组
        symbol_anomalies = {}
        for anomaly in anomalies:
            if anomaly.symbol not in symbol_anomalies:
                symbol_anomalies[anomaly.symbol] = []
            symbol_anomalies[anomaly.symbol].append(anomaly)
        
        for symbol, symbol_anomaly_list in symbol_anomalies.items():
            message += f"📈 **{symbol}**:\n"
            
            for anomaly in symbol_anomaly_list:
                icon = anomaly_icons.get(anomaly.anomaly_type, "⚠️")
                description = anomaly_descriptions.get(anomaly.anomaly_type, "未知异常")
                
                message += f"{icon} {description} (严重程度: {anomaly.severity:.1%})\n"
                message += f"   📝 {anomaly.description}\n"
                message += f"   💡 {anomaly.recommendation}\n"
                message += f"   ⏰ {anomaly.timestamp.strftime('%H:%M:%S')}\n\n"
        
        message += "🔔 **注意**: 异常检测仅供参考，请结合市场情况谨慎决策"
        
        return message
    
    def _get_signal_priority(self, signal: PredictionSignal) -> str:
        """根据信号强度获取优先级"""
        if signal in [PredictionSignal.STRONG_BUY, PredictionSignal.STRONG_SELL]:
            return "high"
        elif signal in [PredictionSignal.BUY, PredictionSignal.SELL]:
            return "normal"
        else:
            return "low"
    
    async def send_model_performance_report(self, symbol: str, accuracy: float, 
                                          previous_accuracy: float = None) -> Dict[str, bool]:
        """
        发送模型性能报告
        
        Args:
            symbol: 交易对
            accuracy: 当前准确率
            previous_accuracy: 之前的准确率
            
        Returns:
            各渠道发送结果
        """
        try:
            message = f"""📊 **ML模型性能报告**

🎯 **交易对**: {symbol}
📈 **当前准确率**: {accuracy:.1%}"""

            if previous_accuracy is not None:
                change = accuracy - previous_accuracy
                change_icon = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                message += f"\n{change_icon} **准确率变化**: {change:+.1%}"
            
            # 根据准确率确定优先级
            if accuracy < 0.5:
                priority = "urgent"
                message += "\n\n⚠️ **警告**: 模型准确率过低，建议重新训练"
            elif accuracy < 0.6:
                priority = "high"
                message += "\n\n💡 **建议**: 模型准确率偏低，考虑优化参数"
            else:
                priority = "normal"
                message += "\n\n✅ **状态**: 模型性能良好"
            
            message += f"\n⏰ **报告时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            result = await self.notification_service.send_notification(
                message=message,
                priority=priority,
                subject=f"📊 ML模型性能报告 - {symbol}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send model performance report: {e}")
            return {}