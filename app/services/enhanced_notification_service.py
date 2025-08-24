# -*- coding: utf-8 -*-
"""
增强通知服务
Enhanced Notification Service - 实现智能推送逻辑
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import asyncio

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.notification_service import NotificationService
from app.services.trading_decision_service import TradingRecommendation, TradingAction
from app.services.detailed_technical_analysis_service import DetailedTechnicalAnalysisService

logger = get_logger(__name__)
settings = get_settings()


class SignalStrength(Enum):
    """信号强度"""
    STRONG = "strong"      # 强信号 - 单独推送，包含具体点位
    NORMAL = "normal"      # 普通信号 - 合并推送，不含具体点位
    WEAK = "weak"          # 弱信号 - 不推送


class EnhancedNotificationService:
    """增强通知服务类"""
    
    def __init__(self):
        self.notification_service = NotificationService()
        self.detailed_analysis_service = DetailedTechnicalAnalysisService()
        
        # 推送配置
        self.config = {
            # 强信号配置
            'strong_signal_threshold': 80.0,  # 强信号置信度阈值
            'strong_signal_actions': ['strong_buy', 'strong_sell'],  # 强信号动作
            
            # 普通信号配置  
            'normal_signal_threshold': 65.0,  # 普通信号置信度阈值
            'normal_signal_actions': ['buy', 'sell'],  # 普通信号动作
            
            # 批量推送配置
            'batch_interval_minutes': 30,  # 批量推送间隔
            'max_batch_size': 3,  # 最大批量大小
            'batch_timeout_minutes': 60,  # 批量超时时间
            
            # 频率控制
            'max_notifications_per_hour': 6,  # 每小时最大通知数
            'strong_signal_cooldown_minutes': 15,  # 强信号冷却时间
            'normal_signal_cooldown_minutes': 60,  # 普通信号冷却时间
        }
        
        # 状态管理
        self.pending_normal_signals = []  # 待推送的普通信号
        self.last_batch_time = datetime.now()
        self.notification_history = {}  # 通知历史
        self.hourly_count = 0
        self.last_hour_reset = datetime.now().hour
    
    async def send_trading_signal(self, recommendation: TradingRecommendation) -> bool:
        """
        发送交易信号通知
        
        Args:
            recommendation: 交易建议
            
        Returns:
            是否发送成功
        """
        try:
            # 判断信号强度
            signal_strength = self._classify_signal_strength(recommendation)
            
            if signal_strength == SignalStrength.WEAK:
                logger.debug(f"{recommendation.symbol} 信号强度不足，跳过推送")
                return False
            
            # 检查推送限制
            if not self._should_send_notification(recommendation.symbol, signal_strength):
                return False
            
            if signal_strength == SignalStrength.STRONG:
                # 强信号立即单独推送
                return await self._send_strong_signal(recommendation)
            else:
                # 普通信号加入批量队列
                return await self._queue_normal_signal(recommendation)
                
        except Exception as e:
            logger.error(f"发送交易信号失败: {e}")
            return False
    
    async def _send_strong_signal(self, recommendation: TradingRecommendation) -> bool:
        """发送强信号通知（单独推送，包含具体点位）"""
        try:
            title, message = await self._build_strong_signal_message(recommendation)
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="high",
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                self._record_notification(recommendation.symbol, SignalStrength.STRONG)
                trading_logger.info(f"📢 已发送强信号: {recommendation.symbol} - {recommendation.action.value}")
            
            return success
            
        except Exception as e:
            logger.error(f"发送强信号失败: {e}")
            return False
    
    async def _queue_normal_signal(self, recommendation: TradingRecommendation) -> bool:
        """将普通信号加入批量队列"""
        try:
            # 添加到待推送队列
            signal_data = {
                'symbol': recommendation.symbol,
                'action': recommendation.action.value,
                'confidence': recommendation.confidence,
                'current_price': recommendation.current_price,
                'reasoning': recommendation.reasoning,
                'timestamp': datetime.now()
            }
            
            self.pending_normal_signals.append(signal_data)
            logger.debug(f"普通信号已加入队列: {recommendation.symbol}")
            
            # 检查是否需要立即推送批量消息
            should_send_batch = (
                len(self.pending_normal_signals) >= self.config['max_batch_size'] or
                (datetime.now() - self.last_batch_time).total_seconds() > 
                self.config['batch_interval_minutes'] * 60
            )
            
            if should_send_batch:
                return await self._send_batch_signals()
            
            return True
            
        except Exception as e:
            logger.error(f"普通信号入队失败: {e}")
            return False
    
    async def _send_batch_signals(self) -> bool:
        """发送批量普通信号（合并推送，不含具体点位）"""
        if not self.pending_normal_signals:
            return True
        
        try:
            title, message = self._build_batch_signal_message(self.pending_normal_signals)
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="medium",
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                # 记录通知历史
                for signal in self.pending_normal_signals:
                    self._record_notification(signal['symbol'], SignalStrength.NORMAL)
                
                trading_logger.info(f"📢 已发送批量信号: {len(self.pending_normal_signals)}个")
                
                # 清空队列
                self.pending_normal_signals.clear()
                self.last_batch_time = datetime.now()
            
            return success
            
        except Exception as e:
            logger.error(f"发送批量信号失败: {e}")
            return False
    
    def _classify_signal_strength(self, recommendation: TradingRecommendation) -> SignalStrength:
        """分类信号强度"""
        confidence = recommendation.confidence
        action = recommendation.action.value
        
        # 强信号判断
        if (confidence >= self.config['strong_signal_threshold'] or 
            action in self.config['strong_signal_actions']):
            return SignalStrength.STRONG
        
        # 普通信号判断
        elif (confidence >= self.config['normal_signal_threshold'] and 
              action in self.config['normal_signal_actions']):
            return SignalStrength.NORMAL
        
        # 弱信号
        else:
            return SignalStrength.WEAK
    
    def _should_send_notification(self, symbol: str, strength: SignalStrength) -> bool:
        """检查是否应该发送通知"""
        # 检查每小时限制
        current_hour = datetime.now().hour
        if current_hour != self.last_hour_reset:
            self.hourly_count = 0
            self.last_hour_reset = current_hour
        
        if self.hourly_count >= self.config['max_notifications_per_hour']:
            logger.warning(f"已达到每小时通知限制")
            return False
        
        # 检查冷却时间
        if symbol in self.notification_history:
            last_time, last_strength = self.notification_history[symbol]
            
            if strength == SignalStrength.STRONG:
                cooldown = self.config['strong_signal_cooldown_minutes']
            else:
                cooldown = self.config['normal_signal_cooldown_minutes']
            
            if (datetime.now() - last_time).total_seconds() < cooldown * 60:
                logger.debug(f"{symbol} 在冷却期内")
                return False
        
        return True
    
    def _record_notification(self, symbol: str, strength: SignalStrength) -> None:
        """记录通知历史"""
        self.notification_history[symbol] = (datetime.now(), strength)
        self.hourly_count += 1
    
    async def _build_strong_signal_message(self, recommendation: TradingRecommendation) -> tuple[str, str]:
        """构建强信号消息（包含具体点位建议和详细技术分析）"""
        # 动作图标
        action_icons = {
            'strong_buy': '🚀',
            'buy': '📈', 
            'strong_sell': '💥',
            'sell': '📉'
        }
        
        # 动作文本
        action_texts = {
            'strong_buy': '强烈买入',
            'buy': '买入',
            'strong_sell': '强烈卖出', 
            'sell': '卖出'
        }
        
        icon = action_icons.get(recommendation.action.value, '📊')
        action_text = action_texts.get(recommendation.action.value, recommendation.action.value)
        
        title = f"{icon} 强交易信号 - {recommendation.symbol}"
        
        message_parts = [
            f"🎯 交易对: {recommendation.symbol}",
            f"💰 当前价格: ${recommendation.current_price:.4f}",
            f"📊 操作建议: {action_text}",
            f"🎯 置信度: {recommendation.confidence:.1f}%",
            "",
            "💡 具体建议:",
            f"  📍 入场价格: ${recommendation.entry_price:.4f}",
            f"  🛡️ 止损价格: ${recommendation.stop_loss_price:.4f}",
            f"  🎯 止盈价格: ${recommendation.take_profit_price:.4f}",
            f"  📈 建议仓位: {recommendation.position_size_percent:.1f}%",
            f"  ⚖️ 杠杆倍数: {recommendation.leverage:.1f}x",
            ""
        ]
        
        # 添加详细技术分析
        try:
            analysis = await self.detailed_analysis_service.analyze_symbol_detailed(recommendation.symbol)
            
            message_parts.extend([
                "📈 技术分析构成:",
                f"  • 趋势指标(40%): {analysis.trend_score:.1f}分 {'🟢' if analysis.trend_score >= 60 else '🔴' if analysis.trend_score <= 40 else '🟡'}",
                f"  • 动量指标(30%): {analysis.momentum_score:.1f}分 {'🟢' if analysis.momentum_score >= 60 else '🔴' if analysis.momentum_score <= 40 else '🟡'}",
                f"  • 成交量指标(20%): {analysis.volume_score:.1f}分 {'🟢' if analysis.volume_score >= 60 else '🔴' if analysis.volume_score <= 40 else '🟡'}",
                f"  • 波动性指标(10%): {analysis.volatility_score:.1f}分 {'🟢' if analysis.volatility_score >= 60 else '🔴' if analysis.volatility_score <= 40 else '🟡'}",
                "",
                "🔍 关键技术指标:"
            ])
            
            # 添加关键指标详情
            all_indicators = (analysis.trend_indicators + analysis.momentum_indicators + 
                             analysis.volume_indicators + analysis.volatility_indicators)
            important_indicators = sorted(all_indicators, key=lambda x: x.weight, reverse=True)[:3]
            
            for indicator in important_indicators:
                signal_emoji = "📈" if indicator.signal == 'buy' else "📉" if indicator.signal == 'sell' else "⏸️"
                message_parts.append(f"  • {indicator.name}: {signal_emoji} {indicator.description}")
            
        except Exception as e:
            logger.warning(f"获取详细技术分析失败: {e}")
            message_parts.extend([
                "📈 技术分析:",
                f"  基于传统指标综合判断: {recommendation.reasoning}"
            ])
        
        message_parts.extend([
            "",
            f"⏰ 信号时间: {datetime.now().strftime('%H:%M:%S')}",
            "",
            "⚠️ 强信号建议立即关注，请结合实际情况谨慎操作！"
        ])
        
        return title, "\n".join(message_parts)
    
    def _build_batch_signal_message(self, signals: List[Dict[str, Any]]) -> tuple[str, str]:
        """构建批量信号消息（不含具体点位建议）"""
        title = f"📊 交易信号汇总 ({len(signals)}个)"
        
        # 按置信度排序
        sorted_signals = sorted(signals, key=lambda x: x['confidence'], reverse=True)
        
        message_parts = [
            f"⏰ 汇总时间: {datetime.now().strftime('%H:%M')}",
            f"📈 发现 {len(signals)} 个交易机会:",
            ""
        ]
        
        # 动作图标映射
        action_icons = {
            'buy': '📈',
            'sell': '📉',
            'hold': '⏸️'
        }
        
        # 动作文本映射
        action_texts = {
            'buy': '买入',
            'sell': '卖出', 
            'hold': '持有'
        }
        
        for i, signal in enumerate(sorted_signals, 1):
            icon = action_icons.get(signal['action'], '📊')
            action_text = action_texts.get(signal['action'], signal['action'])
            
            message_parts.append(
                f"{i}. {icon} {signal['symbol']} - {action_text}"
            )
            message_parts.append(
                f"   置信度: {signal['confidence']:.1f}% | 价格: ${signal['current_price']:.4f}"
            )
            
            # 简化的理由（只取第一个关键点）
            reasoning_parts = signal['reasoning'].split('|')
            if reasoning_parts:
                key_reason = reasoning_parts[0].strip()
                message_parts.append(f"   关键因素: {key_reason}")
            
            message_parts.append("")
        
        message_parts.extend([
            "💡 以上为普通强度信号汇总，不提供具体点位建议",
            "🔍 如需详细分析，请查看具体交易接口",
            "",
            "⚠️ 请结合自身风险承受能力，谨慎投资！"
        ])
        
        return title, "\n".join(message_parts)
    
    async def force_send_pending_signals(self) -> bool:
        """强制发送待推送的普通信号"""
        if self.pending_normal_signals:
            return await self._send_batch_signals()
        return True
    
    async def get_notification_stats(self) -> Dict[str, Any]:
        """获取通知统计信息"""
        return {
            'pending_normal_signals': len(self.pending_normal_signals),
            'hourly_count': self.hourly_count,
            'max_hourly_limit': self.config['max_notifications_per_hour'],
            'last_batch_time': self.last_batch_time,
            'notification_history_count': len(self.notification_history),
            'config': self.config
        }
    
    async def cleanup_old_history(self, hours: int = 24) -> None:
        """清理旧的通知历史"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        old_symbols = [
            symbol for symbol, (time, _) in self.notification_history.items()
            if time < cutoff_time
        ]
        
        for symbol in old_symbols:
            del self.notification_history[symbol]
        
        logger.info(f"清理了 {len(old_symbols)} 个旧通知记录")


# 定时任务：定期发送批量信号
async def periodic_batch_sender(service: EnhancedNotificationService):
    """定期发送批量信号的后台任务"""
    while True:
        try:
            await asyncio.sleep(30 * 60)  # 每30分钟检查一次
            
            # 检查是否有待发送的信号
            if service.pending_normal_signals:
                time_since_last = datetime.now() - service.last_batch_time
                if time_since_last.total_seconds() > service.config['batch_timeout_minutes'] * 60:
                    await service.force_send_pending_signals()
                    logger.info("定期发送了待推送的批量信号")
            
            # 清理旧历史
            await service.cleanup_old_history()
            
        except Exception as e:
            logger.error(f"定期批量发送任务失败: {e}")