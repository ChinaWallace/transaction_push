# -*- coding: utf-8 -*-
"""
Kronos专用通知服务
专门处理Kronos AI预测的强信号通知
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.notification_service import NotificationService
from app.services.kronos_integrated_decision_service import KronosEnhancedDecision, KronosSignalStrength


@dataclass
class KronosNotificationRecord:
    """Kronos通知记录"""
    symbol: str
    timestamp: datetime
    signal_type: str
    confidence: float
    sent: bool = False


class KronosNotificationService:
    """Kronos专用通知服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.notification_service = NotificationService()
        
        # 通知配置
        self.kronos_notification_config = self.settings.kronos_config.get('notification_config', {})
        self.enable_notifications = self.kronos_notification_config.get('enable_strong_signal_notification', True)
        self.strong_signal_threshold = self.kronos_notification_config.get('strong_signal_threshold', 0.65)
        self.medium_signal_threshold = self.kronos_notification_config.get('medium_signal_threshold', 0.5)
        self.max_notifications_per_hour = self.kronos_notification_config.get('max_notifications_per_hour', 10)
        
        # 通知记录（防止重复通知）
        self.notification_history: List[KronosNotificationRecord] = []
        
    async def send_kronos_signal_notification(
        self,
        decision: KronosEnhancedDecision,
        signal_type: str = "strong"
    ) -> bool:
        """
        发送Kronos信号通知
        
        Args:
            decision: Kronos增强决策结果
            signal_type: 信号类型 ("strong", "medium", "batch")
            
        Returns:
            是否发送成功
        """
        if not self.enable_notifications:
            self.logger.info("Kronos通知已禁用")
            return False
        
        # 过滤掉"持有观望"信号，只推送有明确交易建议的信号
        if decision.final_action in ["持有观望", "观望", "持有"]:
            self.logger.info(f"跳过持有观望信号: {decision.symbol} - {decision.final_action}")
            return False
        
        try:
            # 检查通知频率限制
            if not self._check_notification_rate_limit():
                self.logger.warning("Kronos通知频率超限，跳过发送")
                return False
            
            # 检查是否重复通知
            if self._is_duplicate_notification(decision.symbol, signal_type):
                self.logger.info(f"跳过重复的Kronos通知: {decision.symbol}")
                return False
            
            # 生成通知内容
            notification_content = self._generate_notification_content(decision, signal_type)
            
            # 发送通知
            success = await self.notification_service.send_notification(
                message=notification_content["message"],
                priority=notification_content["priority"],
                subject=notification_content["title"]
            )
            
            if success:
                # 记录通知历史
                self._record_notification(decision.symbol, signal_type, decision.final_confidence)
                self.logger.info(f"✅ Kronos通知发送成功: {decision.symbol} {signal_type}")
                
                # 记录到交易日志
                trading_logger.info(
                    f"Kronos通知 - {decision.symbol}: {decision.final_action} "
                    f"(Kronos: {decision.kronos_confidence:.2f}, 强度: {decision.kronos_signal_strength.value})"
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"发送Kronos通知失败: {e}")
            return False
    
    async def send_batch_kronos_notification(
        self,
        decisions: List[KronosEnhancedDecision],
        notification_type: str = "strong_signals"
    ) -> bool:
        """
        发送批量Kronos信号通知
        
        Args:
            decisions: Kronos决策列表
            notification_type: 通知类型
            
        Returns:
            是否发送成功
        """
        if not self.enable_notifications or not decisions:
            return False
        
        try:
            # 筛选符合条件的信号
            strong_signals = []
            medium_signals = []
            
            for decision in decisions:
                # 过滤掉"持有观望"信号，只推送有明确交易建议的信号
                if decision.final_action in ["持有观望", "观望", "持有"]:
                    continue
                    
                if decision.kronos_confidence >= self.strong_signal_threshold:
                    if decision.kronos_signal_strength in [KronosSignalStrength.STRONG, KronosSignalStrength.VERY_STRONG]:
                        strong_signals.append(decision)
                elif decision.kronos_confidence >= self.medium_signal_threshold:
                    medium_signals.append(decision)
            
            # 发送强信号汇总
            if strong_signals:
                await self._send_batch_notification(strong_signals, "strong")
            
            # 发送中等信号汇总（如果没有强信号）
            if not strong_signals and medium_signals:
                await self._send_batch_notification(medium_signals[:5], "medium")  # 最多5个
            
            return True
            
        except Exception as e:
            self.logger.error(f"发送批量Kronos通知失败: {e}")
            return False
    
    def _generate_notification_content(
        self,
        decision: KronosEnhancedDecision,
        signal_type: str
    ) -> Dict[str, str]:
        """生成通知内容"""
        symbol = decision.symbol
        action = decision.final_action
        kronos_conf = decision.kronos_confidence
        signal_strength = decision.kronos_signal_strength.value
        confluence = decision.signal_confluence
        
        # 根据信号类型设置标题和优先级
        if signal_type == "strong":
            title = f"🚀 强Kronos信号: {symbol}"
            emoji = "🔥"
            priority = "high"
        elif signal_type == "medium":
            title = f"📊 Kronos信号: {symbol}"
            emoji = "🤖"
            priority = "medium"
        else:
            title = f"💡 Kronos提醒: {symbol}"
            emoji = "💡"
            priority = "low"
        
        # 生成详细消息 - 修复None值格式化错误
        try:
            # 安全获取各个字段值，避免None值格式化错误
            entry_price = decision.entry_price if decision.entry_price is not None else 0.0
            stop_loss = decision.stop_loss if decision.stop_loss is not None else 0.0
            take_profit = decision.take_profit if decision.take_profit is not None else 0.0
            position_size = decision.position_size if decision.position_size is not None else 0.0
            reasoning = decision.reasoning if decision.reasoning else "暂无详细说明"
            
            # 安全获取枚举值
            position_rec = getattr(decision.position_recommendation, 'value', '未知') if decision.position_recommendation else '未知'
            market_regime = getattr(decision.market_regime, 'value', '未知') if decision.market_regime else '未知'
            
            message = f"""
{emoji} **{title}**

📈 **交易行动**: {action}
🤖 **Kronos置信度**: {kronos_conf:.2f}
💪 **信号强度**: {signal_strength}
🤝 **信号一致性**: {confluence:.2f}
💼 **持仓建议**: {position_rec}
🌊 **市场状态**: {market_regime}

💰 **当前价格**: ${entry_price:.2f}
🛑 **止损价格**: ${stop_loss:.2f}
🎯 **止盈价格**: ${take_profit:.2f}
📊 **建议仓位**: {position_size:.1%}

💡 **决策依据**: {reasoning}

⏰ 时间: {decision.timestamp.strftime('%H:%M:%S')}
"""
        except Exception as e:
            self.logger.error(f"生成通知消息失败: {e}")
            # 使用简化的消息格式
            message = f"""
{emoji} **{title}**

📈 **交易行动**: {action}
🤖 **Kronos置信度**: {kronos_conf:.2f}
💪 **信号强度**: {signal_strength}

⏰ 时间: {decision.timestamp.strftime('%H:%M:%S')}
"""
        
        return {
            "title": title,
            "message": message,
            "priority": priority
        }
    
    async def _send_batch_notification(
        self,
        decisions: List[KronosEnhancedDecision],
        signal_type: str
    ) -> bool:
        """发送批量通知"""
        try:
            count = len(decisions)
            
            if signal_type == "strong":
                title = f"🔥 发现 {count} 个强Kronos信号"
                emoji = "🚀"
            else:
                title = f"📊 发现 {count} 个Kronos信号"
                emoji = "🤖"
            
            message = f"{emoji} **Kronos AI集成分析汇总**\n\n"
            
            for i, decision in enumerate(decisions[:5], 1):  # 最多显示5个
                symbol = decision.symbol
                action = decision.final_action
                kronos_conf = decision.kronos_confidence
                strength = decision.kronos_signal_strength.value
                
                message += f"{i}. **{symbol}**: {action}\n"
                message += f"   🤖 Kronos: {kronos_conf:.2f} | 💪 {strength}\n\n"
            
            if count > 5:
                message += f"... 还有 {count - 5} 个信号\n\n"
            
            message += f"⏰ 分析时间: {datetime.now().strftime('%H:%M:%S')}\n"
            message += f"💡 建议优先关注Kronos置信度最高的信号"
            
            success = await self.notification_service.send_notification(
                message=message,
                priority="high" if signal_type == "strong" else "medium",
                subject=title
            )
            
            if success:
                # 记录批量通知
                for decision in decisions:
                    self._record_notification(decision.symbol, f"batch_{signal_type}", decision.kronos_confidence)
            
            return success
            
        except Exception as e:
            self.logger.error(f"发送批量Kronos通知失败: {e}")
            return False
    
    def _check_notification_rate_limit(self) -> bool:
        """检查通知频率限制"""
        try:
            current_time = datetime.now()
            one_hour_ago = current_time - timedelta(hours=1)
            
            # 清理过期记录
            self.notification_history = [
                record for record in self.notification_history
                if record.timestamp > one_hour_ago
            ]
            
            # 检查是否超过限制
            recent_notifications = len(self.notification_history)
            return recent_notifications < self.max_notifications_per_hour
            
        except Exception as e:
            self.logger.error(f"检查通知频率限制失败: {e}")
            return True  # 出错时允许发送
    
    def _is_duplicate_notification(self, symbol: str, signal_type: str) -> bool:
        """检查是否重复通知 - 强信号优化版"""
        try:
            current_time = datetime.now()
            
            # 根据信号类型设置不同的重复检查窗口
            if signal_type == "strong":
                duplicate_window = timedelta(minutes=5)   # 强信号5分钟内不重复
            elif signal_type == "medium":
                duplicate_window = timedelta(minutes=15)  # 中等信号15分钟内不重复
            else:
                duplicate_window = timedelta(minutes=30)  # 其他信号30分钟内不重复
            
            for record in self.notification_history:
                if (record.symbol == symbol and 
                    record.signal_type == signal_type and
                    current_time - record.timestamp < duplicate_window):
                    
                    # 如果是强信号且置信度显著提升，允许重新推送
                    if (signal_type == "strong" and 
                        hasattr(record, 'confidence') and 
                        record.confidence < 0.8):  # 之前置信度较低
                        self.logger.info(f"强信号置信度提升，允许重新推送: {symbol}")
                        return False
                    
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"检查重复通知失败: {e}")
            return False  # 出错时允许发送
    
    def _record_notification(self, symbol: str, signal_type: str, confidence: float):
        """记录通知历史"""
        try:
            record = KronosNotificationRecord(
                symbol=symbol,
                timestamp=datetime.now(),
                signal_type=signal_type,
                confidence=confidence,
                sent=True
            )
            
            self.notification_history.append(record)
            
            # 保持历史记录在合理范围内
            if len(self.notification_history) > 100:
                self.notification_history = self.notification_history[-50:]
                
        except Exception as e:
            self.logger.error(f"记录通知历史失败: {e}")
    
    def get_notification_stats(self) -> Dict[str, Any]:
        """获取通知统计信息"""
        try:
            current_time = datetime.now()
            one_hour_ago = current_time - timedelta(hours=1)
            one_day_ago = current_time - timedelta(days=1)
            
            # 统计最近1小时和24小时的通知
            recent_hour = [r for r in self.notification_history if r.timestamp > one_hour_ago]
            recent_day = [r for r in self.notification_history if r.timestamp > one_day_ago]
            
            return {
                "total_notifications": len(self.notification_history),
                "last_hour": len(recent_hour),
                "last_24_hours": len(recent_day),
                "rate_limit_remaining": max(0, self.max_notifications_per_hour - len(recent_hour)),
                "enabled": self.enable_notifications,
                "strong_signal_threshold": self.strong_signal_threshold,
                "medium_signal_threshold": self.medium_signal_threshold
            }
            
        except Exception as e:
            self.logger.error(f"获取通知统计失败: {e}")
            return {}


# 全局服务实例
_kronos_notification_service = None

async def get_kronos_notification_service() -> KronosNotificationService:
    """获取Kronos通知服务实例"""
    global _kronos_notification_service
    if _kronos_notification_service is None:
        _kronos_notification_service = KronosNotificationService()
    return _kronos_notification_service