# -*- coding: utf-8 -*-
"""
核心通知服务
Core Notification Service - 统一管理所有类型的通知推送
整合原有的所有通知功能，支持分类推送和智能过滤
"""

import asyncio
import json
import hmac
import hashlib
import base64
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from app.core.config import get_settings
from app.core.logging import get_logger, monitor_logger, trading_logger
from app.utils.http_manager import get_http_manager, safe_http_request
from app.utils.exceptions import NotificationError
from app.models.notification import NotificationLog, AlertRule

logger = get_logger(__name__)
settings = get_settings()


class NotificationType(Enum):
    """通知类型枚举"""
    TRADING_SIGNAL = "交易信号"
    POSITION_ANALYSIS = "持仓分析"
    FUNDING_RATE = "费率监控"
    GRID_OPPORTUNITY = "网格机会"
    KRONOS_PREDICTION = "Kronos预测"
    ML_PREDICTION = "ML预测"
    ANOMALY_ALERT = "异常警报"
    BACKTEST_RESULT = "回测结果"
    SYSTEM_ALERT = "系统警报"
    DAILY_REPORT = "每日报告"


class NotificationPriority(Enum):
    """通知优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class NotificationChannel(Enum):
    """通知渠道"""
    FEISHU = "feishu"
    WECHAT = "wechat"
    TELEGRAM = "telegram"
    EMAIL = "email"


@dataclass
class NotificationContent:
    """通知内容"""
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    channels: List[NotificationChannel] = None
    metadata: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


@dataclass 
class NotificationRule:
    """通知规则"""
    type: NotificationType
    enabled: bool = True
    min_priority: NotificationPriority = NotificationPriority.NORMAL
    channels: List[NotificationChannel] = None
    cooldown_minutes: int = 30
    filter_func: Optional[Callable] = None
    format_func: Optional[Callable] = None


class CoreNotificationService:
    """核心通知服务类 - 统一管理所有通知"""
    
    def __init__(self):
        self.http_manager = None  # 延迟初始化
        self.notification_config = settings.notification_config
        
        # 兼容旧的配置格式
        self.feishu_webhook = settings.feishu_webhook_url
        self.telegram_bot_token = settings.telegram_bot_token
        self.telegram_chat_id = settings.telegram_chat_id
        
        # 通知规则配置
        self.notification_rules = self._initialize_notification_rules()
        
        # 通知历史和频率控制
        self.notification_history = {}  # type -> last_sent_time
        self.symbol_notification_history = {}  # (type, symbol) -> last_sent_time (用于交易信号)
        self.hourly_counts = {}         # type -> count per hour
        self.last_hour_reset = datetime.now().hour
        
        # 批量处理配置
        self.batch_queue = {}           # type -> list of pending notifications
        self.batch_timers = {}          # type -> timer for batch processing
        self.batch_config = {
            # 交易信号不使用批量处理，立即发送
            # NotificationType.TRADING_SIGNAL: {'max_size': 3, 'timeout_minutes': 15},
            NotificationType.ML_PREDICTION: {'max_size': 5, 'timeout_minutes': 30},
            NotificationType.GRID_OPPORTUNITY: {'max_size': 10, 'timeout_minutes': 60},
        }
        
        # 最大通知限制
        self.max_notifications_per_hour = {
            NotificationType.TRADING_SIGNAL: 10,
            NotificationType.POSITION_ANALYSIS: 4,
            NotificationType.FUNDING_RATE: 6,
            NotificationType.GRID_OPPORTUNITY: 3,
            NotificationType.KRONOS_PREDICTION: 8,
            NotificationType.ML_PREDICTION: 6,
            NotificationType.ANOMALY_ALERT: 5,
            NotificationType.SYSTEM_ALERT: 20,
        }
    
    def _initialize_notification_rules(self) -> Dict[NotificationType, NotificationRule]:
        """初始化通知规则"""
        return {
            # 交易信号 - 降低最低优先级要求，支持更多强信号
            NotificationType.TRADING_SIGNAL: NotificationRule(
                type=NotificationType.TRADING_SIGNAL,
                min_priority=NotificationPriority.NORMAL,  # 从HIGH降低到NORMAL
                cooldown_minutes=5,  # 强信号冷却时间5分钟
                filter_func=self._filter_trading_signal,
                format_func=self._format_trading_signal
            ),
            
            # 持仓分析 - 中等优先级，批量推送
            NotificationType.POSITION_ANALYSIS: NotificationRule(
                type=NotificationType.POSITION_ANALYSIS,
                min_priority=NotificationPriority.NORMAL,
                cooldown_minutes=60,
                format_func=self._format_position_analysis
            ),
            
            # 费率监控 - 立即推送
            NotificationType.FUNDING_RATE: NotificationRule(
                type=NotificationType.FUNDING_RATE,
                min_priority=NotificationPriority.NORMAL,
                cooldown_minutes=30,
                format_func=self._format_funding_rate
            ),
            
            # 网格机会 - 批量推送
            NotificationType.GRID_OPPORTUNITY: NotificationRule(
                type=NotificationType.GRID_OPPORTUNITY,
                min_priority=NotificationPriority.NORMAL,
                cooldown_minutes=120,
                format_func=self._format_grid_opportunity
            ),
            
            # Kronos预测 - 高优先级，立即推送
            NotificationType.KRONOS_PREDICTION: NotificationRule(
                type=NotificationType.KRONOS_PREDICTION,
                min_priority=NotificationPriority.HIGH,
                cooldown_minutes=15,
                filter_func=self._filter_kronos_prediction,
                format_func=self._format_kronos_prediction
            ),
            
            # ML预测 - 批量推送
            NotificationType.ML_PREDICTION: NotificationRule(
                type=NotificationType.ML_PREDICTION,
                min_priority=NotificationPriority.NORMAL,
                cooldown_minutes=30,
                format_func=self._format_ml_prediction
            ),
            
            # 系统警报 - 添加过滤器，过滤系统启动状态信息
            NotificationType.SYSTEM_ALERT: NotificationRule(
                type=NotificationType.SYSTEM_ALERT,
                min_priority=NotificationPriority.HIGH,
                cooldown_minutes=5,
                filter_func=self._filter_system_alert,
            ),
        }
    
    async def send_notification(self, content: NotificationContent) -> Dict[str, bool]:
        """
        发送通知 - 统一入口
        
        Args:
            content: 通知内容
            
        Returns:
            各渠道发送结果
        """
        try:
            # 特别记录交易信号的处理过程
            if content.type == NotificationType.TRADING_SIGNAL:
                symbol = content.metadata.get('symbol', 'Unknown')
                confidence = content.metadata.get('confidence', 0)
                action = content.metadata.get('action', 'Unknown')
                logger.info(f"🔍 处理交易信号: {symbol} {action} (置信度: {confidence:.2f})")
            
            # 检查通知规则
            if not self._should_send_notification(content):
                if content.type == NotificationType.TRADING_SIGNAL:
                    logger.warning(f"❌ 交易信号被规则拦截: {content.metadata.get('symbol')} - 不满足发送条件")
                else:
                    logger.debug(f"跳过通知: {content.type.value} - 不满足发送条件")
                return {}
            
            # 应用过滤规则
            if not self._apply_filters(content):
                if content.type == NotificationType.TRADING_SIGNAL:
                    logger.warning(f"❌ 交易信号被过滤器拦截: {content.metadata.get('symbol')}")
                else:
                    logger.debug(f"跳过通知: {content.type.value} - 被过滤器拦截")
                return {}
            
            # 检查是否需要批量处理
            if self._should_batch_process(content):
                return await self._add_to_batch(content)
            
            # 立即发送
            if content.type == NotificationType.TRADING_SIGNAL:
                logger.info(f"✅ 交易信号通过所有检查，准备发送: {content.metadata.get('symbol')}")
            
            return await self._send_immediately(content)
            
        except Exception as e:
            logger.error(f"发送通知失败: {e}")
            return {}
    
    def _should_send_notification(self, content: NotificationContent) -> bool:
        """检查是否应该发送通知"""
        rule = self.notification_rules.get(content.type)
        if not rule or not rule.enabled:
            logger.debug(f"通知规则未启用: {content.type.value}")
            return False
        
        # 检查优先级
        if content.priority.value < rule.min_priority.value:
            logger.debug(f"通知优先级不足: {content.priority.name} ({content.priority.value}) < {rule.min_priority.name} ({rule.min_priority.value})")
            return False
        
        # 检查冷却时间 - 交易信号按交易对独立检查
        if content.type == NotificationType.TRADING_SIGNAL:
            symbol = content.metadata.get('symbol', 'Unknown')
            if not self._check_symbol_cooldown(content.type, symbol, rule.cooldown_minutes):
                logger.debug(f"交易信号冷却时间未到: {content.type.value} - {symbol}")
                return False
        else:
            if not self._check_cooldown(content.type, rule.cooldown_minutes):
                logger.debug(f"通知冷却时间未到: {content.type.value}")
                return False
        
        # 检查频率限制
        if not self._check_rate_limit(content.type):
            logger.debug(f"通知频率限制: {content.type.value}")
            return False
        
        logger.debug(f"通知检查通过: {content.type.value}")
        return True
    
    def _check_cooldown(self, notification_type: NotificationType, cooldown_minutes: int) -> bool:
        """检查冷却时间"""
        last_sent = self.notification_history.get(notification_type)
        if last_sent is None:
            return True
        
        time_since_last = datetime.now() - last_sent
        cooldown_passed = time_since_last >= timedelta(minutes=cooldown_minutes)
        
        # 如果冷却时间未到，记录详细信息
        if not cooldown_passed:
            remaining_seconds = (timedelta(minutes=cooldown_minutes) - time_since_last).total_seconds()
            logger.debug(f"冷却时间未到: {notification_type.value}, 还需等待 {remaining_seconds:.0f} 秒")
        
        return cooldown_passed
    
    def _check_symbol_cooldown(self, notification_type: NotificationType, symbol: str, cooldown_minutes: int) -> bool:
        """检查特定交易对的冷却时间"""
        key = (notification_type, symbol)
        last_sent = self.symbol_notification_history.get(key)
        if last_sent is None:
            return True
        
        time_since_last = datetime.now() - last_sent
        cooldown_passed = time_since_last >= timedelta(minutes=cooldown_minutes)
        
        if not cooldown_passed:
            remaining_seconds = (timedelta(minutes=cooldown_minutes) - time_since_last).total_seconds()
            logger.debug(f"交易对冷却时间未到: {symbol}, 还需等待 {remaining_seconds:.0f} 秒")
        
        return cooldown_passed
    
    def _check_rate_limit(self, notification_type: NotificationType) -> bool:
        """检查频率限制"""
        # 重置小时计数
        current_hour = datetime.now().hour
        if current_hour != self.last_hour_reset:
            self.hourly_counts.clear()
            self.last_hour_reset = current_hour
        
        # 检查当前小时的发送次数
        max_per_hour = self.max_notifications_per_hour.get(notification_type, 10)
        current_count = self.hourly_counts.get(notification_type, 0)
        
        return current_count < max_per_hour
    
    def _apply_filters(self, content: NotificationContent) -> bool:
        """应用过滤规则"""
        rule = self.notification_rules.get(content.type)
        if rule and rule.filter_func:
            return rule.filter_func(content)
        return True
    
    def _should_batch_process(self, content: NotificationContent) -> bool:
        """检查是否需要批量处理"""
        return content.type in self.batch_config
    
    async def _add_to_batch(self, content: NotificationContent) -> Dict[str, bool]:
        """添加到批量队列"""
        if content.type not in self.batch_queue:
            self.batch_queue[content.type] = []
        
        self.batch_queue[content.type].append(content)
        
        # 检查是否需要立即处理批量
        batch_cfg = self.batch_config[content.type]
        if len(self.batch_queue[content.type]) >= batch_cfg['max_size']:
            return await self._process_batch(content.type)
        
        # 设置定时器
        if content.type not in self.batch_timers:
            loop = asyncio.get_event_loop()
            self.batch_timers[content.type] = loop.call_later(
                batch_cfg['timeout_minutes'] * 60,
                lambda: asyncio.create_task(self._process_batch(content.type))
            )
        
        return {"batch": True}
    
    async def _process_batch(self, notification_type: NotificationType) -> Dict[str, bool]:
        """处理批量通知"""
        if notification_type not in self.batch_queue:
            return {}
        
        notifications = self.batch_queue.pop(notification_type)
        if not notifications:
            return {}
        
        # 取消定时器
        if notification_type in self.batch_timers:
            self.batch_timers[notification_type].cancel()
            del self.batch_timers[notification_type]
        
        # 合并成一个批量通知
        batch_content = self._merge_batch_notifications(notifications)
        return await self._send_immediately(batch_content)
    
    def _merge_batch_notifications(self, notifications: List[NotificationContent]) -> NotificationContent:
        """合并批量通知"""
        if not notifications:
            return None
        
        first = notifications[0]
        
        # 合并标题和内容
        title = f"📊 {first.type.value}汇总 ({len(notifications)}个)"
        
        message_parts = [f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        
        for i, notif in enumerate(notifications, 1):
            message_parts.append(f"【{i}】 {notif.title}")
            message_parts.append(notif.message)
            message_parts.append("")
        
        message = "\n".join(message_parts)
        
        return NotificationContent(
            type=first.type,
            priority=max(n.priority for n in notifications),
            title=title,
            message=message,
            channels=first.channels
        )
    
    async def _send_immediately(self, content: NotificationContent) -> Dict[str, bool]:
        """立即发送通知"""
        # 应用格式化规则
        formatted_content = self._apply_formatting(content)
        
        # 确定发送渠道
        channels = formatted_content.channels or self._get_default_channels(content.type)
        
        # 并发发送到各个渠道
        tasks = []
        for channel in channels:
            task = self._send_to_channel(
                channel, 
                formatted_content.message, 
                formatted_content.priority.value,
                formatted_content.title
            )
            tasks.append((channel.value, task))
        
        results = {}
        for channel_name, task in tasks:
            try:
                success = await task
                results[channel_name] = success
                if success:
                    monitor_logger.info(f"✅ 通知发送成功 - {channel_name}: {content.type.value}")
                else:
                    monitor_logger.error(f"❌ 通知发送失败 - {channel_name}: {content.type.value}")
            except Exception as e:
                logger.error(f"❌ 发送通知到{channel_name}失败: {e}")
                results[channel_name] = False
        
        # 更新发送历史
        symbol = content.metadata.get('symbol') if content.type == NotificationType.TRADING_SIGNAL else None
        self._update_notification_history(content.type, symbol)
        
        return results
    
    def _apply_formatting(self, content: NotificationContent) -> NotificationContent:
        """应用格式化规则"""
        rule = self.notification_rules.get(content.type)
        if rule and rule.format_func:
            return rule.format_func(content)
        return content
    
    def _get_default_channels(self, notification_type: NotificationType) -> List[NotificationChannel]:
        """获取默认通知渠道"""
        # 根据通知类型返回合适的渠道
        urgent_types = [
            NotificationType.TRADING_SIGNAL,
            NotificationType.KRONOS_PREDICTION,
            NotificationType.SYSTEM_ALERT
        ]
        
        if notification_type in urgent_types:
            return [NotificationChannel.FEISHU, NotificationChannel.TELEGRAM]
        else:
            return [NotificationChannel.FEISHU]
    
    def _update_notification_history(self, notification_type: NotificationType, symbol: str = None):
        """更新通知历史"""
        now = datetime.now()
        self.notification_history[notification_type] = now
        self.hourly_counts[notification_type] = self.hourly_counts.get(notification_type, 0) + 1
        
        # 如果是交易信号，也更新交易对特定的历史
        if notification_type == NotificationType.TRADING_SIGNAL and symbol:
            key = (notification_type, symbol)
            self.symbol_notification_history[key] = now
    
    async def _get_http_manager(self):
        """获取HTTP管理器实例"""
        if self.http_manager is None:
            self.http_manager = await get_http_manager()
        return self.http_manager
    
    async def _send_to_channel(self, 
                             channel: NotificationChannel, 
                             message: str, 
                             priority: str,
                             subject: str = None) -> bool:
        """向指定渠道发送消息"""
        try:
            if channel == NotificationChannel.FEISHU:
                return await self._send_feishu(message, priority)
            elif channel == NotificationChannel.WECHAT:
                return await self._send_wechat(message, priority)
            elif channel == NotificationChannel.TELEGRAM:
                return await self._send_telegram(message, priority)
            elif channel == NotificationChannel.EMAIL:
                return await self._send_email(message, subject, priority)
            else:
                logger.warning(f"未知通知渠道: {channel}")
                return False
                
        except Exception as e:
            logger.error(f"向{channel.value}发送消息失败: {e}")
            return False
    
    # ========== 专用通知方法 ==========
    
    async def send_trading_signal(self, signal_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送交易信号通知"""
        logger.info(f"收到交易信号通知请求: {signal_data.get('symbol')} - {signal_data.get('action')}")
        
        content = NotificationContent(
            type=NotificationType.TRADING_SIGNAL,
            priority=NotificationPriority.HIGH,
            title=f"🚀 交易信号 - {signal_data.get('symbol', 'Unknown')}",
            message="",  # 将在格式化函数中填充
            metadata=signal_data
        )
        
        result = await self.send_notification(content)
        logger.info(f"交易信号通知发送结果: {result}")
        
        return result
    
    async def send_position_analysis(self, analysis_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送持仓分析通知"""
        content = NotificationContent(
            type=NotificationType.POSITION_ANALYSIS,
            priority=NotificationPriority.NORMAL,
            title="💼 持仓分析报告",
            message="",
            metadata=analysis_data
        )
        return await self.send_notification(content)
    
    async def send_funding_rate_alert(self, funding_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送费率监控通知"""
        priority = NotificationPriority.HIGH if funding_data.get('is_urgent') else NotificationPriority.NORMAL
        content = NotificationContent(
            type=NotificationType.FUNDING_RATE,
            priority=priority,
            title="💰 负费率机会",
            message="",
            metadata=funding_data
        )
        return await self.send_notification(content)
    
    async def send_grid_opportunity(self, grid_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送网格机会通知"""
        content = NotificationContent(
            type=NotificationType.GRID_OPPORTUNITY,
            priority=NotificationPriority.NORMAL,
            title="🎯 网格交易机会",
            message="",
            metadata=grid_data
        )
        return await self.send_notification(content)
    
    async def send_kronos_prediction(self, kronos_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送Kronos预测通知"""
        content = NotificationContent(
            type=NotificationType.KRONOS_PREDICTION,
            priority=NotificationPriority.HIGH,
            title=f"🤖 Kronos预测 - {kronos_data.get('symbol', 'Unknown')}",
            message="",
            metadata=kronos_data
        )
        return await self.send_notification(content)
    
    async def send_ml_prediction(self, ml_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送ML预测通知"""
        content = NotificationContent(
            type=NotificationType.ML_PREDICTION,
            priority=NotificationPriority.NORMAL,
            title="🧠 ML预测信号",
            message="",
            metadata=ml_data
        )
        return await self.send_notification(content)
    
    async def send_backtest_result(self, backtest_data: Dict[str, Any]) -> Dict[str, bool]:
        """发送回测结果通知"""
        content = NotificationContent(
            type=NotificationType.BACKTEST_RESULT,
            priority=NotificationPriority.NORMAL,
            title="📈 回测结果",
            message="",
            metadata=backtest_data
        )
        return await self.send_notification(content)
    
    # ========== 过滤函数 ==========
    
    def _filter_trading_signal(self, content: NotificationContent) -> bool:
        """过滤交易信号"""
        signal_data = content.metadata
        confidence = signal_data.get('confidence', 0)
        action = signal_data.get('action', '').lower().strip()
        strength = signal_data.get('strength', '').lower()
        
        # 🚫 过滤掉HOLD动作 - 持有操作不需要推送通知
        hold_actions = ['hold', '持有', '观望', '持有观望', '等待', 'wait']
        if action in hold_actions:
            logger.debug(f"交易信号被过滤: HOLD动作不推送通知 - 动作: '{action}'")
            return False
        
        # 降低置信度要求，支持更多强信号
        min_confidence = 0.6  # 从0.75降低到0.6
        
        # 如果是强信号或很强信号，进一步降低置信度要求
        if strength in ['strong', 'very_strong', '强', '很强', 'moderate', '中等']:
            min_confidence = 0.5
        
        if confidence < min_confidence:
            logger.debug(f"交易信号被过滤: 置信度 {confidence:.2f} < {min_confidence:.2f}")
            return False
        
        # 扩展支持的动作名称，包括更多格式（移除hold相关动作）
        valid_actions = [
            # 英文格式
            'strong_buy', 'strong_sell', 'buy', 'sell',
            'strongbuy', 'strongsell',
            # 中文格式
            '强烈买入', '强烈卖出', '买入', '卖出',
            '强买入', '强卖出', '买', '卖',
            # 其他可能的格式
            'long', 'short', 'bullish', 'bearish'
        ]
        
        # 如果动作为空或无效，但置信度很高，也允许通过
        if not action or action not in valid_actions:
            if confidence >= 0.8:  # 高置信度信号即使动作不明确也推送
                logger.info(f"高置信度信号通过: 动作 '{action}', 置信度 {confidence:.2f}")
                return True
            else:
                logger.debug(f"交易信号被过滤: 动作 '{action}' 不在有效列表中，置信度不够高")
                return False
        
        logger.debug(f"交易信号通过过滤: 动作 '{action}', 置信度 {confidence:.2f}")
        return True
    
    def _filter_kronos_prediction(self, content: NotificationContent) -> bool:
        """过滤Kronos预测"""
        kronos_data = content.metadata
        confidence = kronos_data.get('confidence', 0)
        action = kronos_data.get('action', '').lower()
        
        # 过滤掉"持有观望"信号
        if action in ['持有观望', '观望', '持有', 'hold']:
            return False
        
        # 只推送高置信度预测
        return confidence >= 0.65
    
    def _filter_system_alert(self, content: NotificationContent) -> bool:
        """过滤系统警报"""
        # 🚫 过滤掉系统启动完成的状态信息
        title = content.title.lower()
        message = content.message.lower()
        
        # 检查是否为系统启动相关的状态信息
        startup_keywords = [
            '系统启动完成', '启动完成', '交易分析工具启动完成', '启动报告',
            '系统已就绪', '开始监控市场', '任务执行', '启动时间',
            'startup completed', 'system ready', '核心交易分析',
            '💰 负费率机会', '🤖 kronos扫描', '📊 任务执行'
        ]
        
        for keyword in startup_keywords:
            if keyword in title or keyword in message:
                logger.debug(f"系统警报被过滤: 系统启动状态信息不推送 - 标题: '{content.title}'")
                return False
        
        # 其他系统警报正常推送
        return True
    
    # ========== 格式化函数 ==========
    
    def _format_trading_signal(self, content: NotificationContent) -> NotificationContent:
        """格式化交易信号"""
        data = content.metadata
        symbol = data.get('symbol', 'Unknown')
        action = data.get('action', '未知')
        confidence = data.get('confidence', 0)
        strength = data.get('strength', '')
        
        # 获取价格信息
        current_price = data.get('current_price', 0) or data.get('price', 0) or data.get('entry_price', 0)
        
        # 智能处理置信度格式
        if confidence > 1.0:
            confidence_display = f"{confidence:.1f}%"
        else:
            confidence_display = f"{confidence:.1%}"
        
        # 获取详细信息
        stop_loss = data.get('stop_loss') or data.get('stop_loss_price')
        take_profit = data.get('take_profit') or data.get('take_profit_price') or data.get('target_price')
        reasoning = data.get('reasoning', '') or data.get('analysis', '') or data.get('description', '')
        key_factors = data.get('key_factors', []) or data.get('factors', [])
        
        # 获取额外的分析数据
        expected_return = data.get('expected_return') or data.get('expected_return_percent')
        risk_reward_ratio = data.get('risk_reward_ratio')
        win_probability = data.get('win_probability')
        position_size = data.get('position_size') or data.get('position_size_usdt')
        leverage = data.get('leverage')
        
        # 构建强信号标题
        strength_emoji = {
            'very_strong': '🔥🔥🔥',
            'strong': '🔥🔥',
            'moderate': '🔥',
            '很强': '🔥🔥🔥',
            '强': '🔥🔥',
            '中等': '🔥'
        }.get(strength.lower(), '🚀')
        
        message_parts = [
            f"{strength_emoji} 【强信号】{symbol} 交易机会",
            "=" * 40,
            f"📊 交易动作: {action.upper()}",
            f"🎯 信号强度: {strength or '强'} ({confidence_display})",
            f"💰 当前价格: ${current_price:.4f}" if current_price else "💰 价格: 待获取"
        ]
        
        # 添加风险管理信息
        if stop_loss or take_profit:
            message_parts.append("")
            message_parts.append("🎯 风险管理:")
            if stop_loss:
                loss_pct = ((current_price - stop_loss) / current_price * 100) if current_price else 0
                message_parts.append(f"  🛡️ 止损: ${stop_loss:.4f} ({loss_pct:+.1f}%)")
            if take_profit:
                profit_pct = ((take_profit - current_price) / current_price * 100) if current_price else 0
                message_parts.append(f"  🎯 止盈: ${take_profit:.4f} ({profit_pct:+.1f}%)")
        
        # 添加收益预期
        if expected_return or risk_reward_ratio or win_probability:
            message_parts.append("")
            message_parts.append("📈 收益预期:")
            if expected_return:
                if expected_return > 1:
                    message_parts.append(f"  💎 预期收益: {expected_return:.1f}%")
                else:
                    message_parts.append(f"  💎 预期收益: {expected_return:.1%}")
            if risk_reward_ratio:
                message_parts.append(f"  ⚖️ 风险收益比: 1:{risk_reward_ratio:.1f}")
            if win_probability:
                if win_probability > 1:
                    message_parts.append(f"  🎲 胜率: {win_probability:.1f}%")
                else:
                    message_parts.append(f"  🎲 胜率: {win_probability:.1%}")
        
        # 添加仓位建议
        if position_size or leverage:
            message_parts.append("")
            message_parts.append("💼 仓位建议:")
            if position_size:
                message_parts.append(f"  💵 建议仓位: ${position_size:.0f} USDT")
            if leverage:
                message_parts.append(f"  📊 建议杠杆: {leverage}x")
        
        # 添加时间信息
        message_parts.extend([
            "",
            f"⏰ 信号时间: {content.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        ])
        
        # 添加分析理由
        if reasoning:
            message_parts.extend([
                "",
                "📋 分析理由:",
                f"  {reasoning[:300]}{'...' if len(reasoning) > 300 else ''}"
            ])
        
        # 添加关键因素
        if key_factors:
            message_parts.extend([
                "",
                "🔍 关键因素:"
            ])
            for i, factor in enumerate(key_factors[:5], 1):  # 最多显示5个
                message_parts.append(f"  {i}. {factor}")
        
        # 添加风险提示
        message_parts.extend([
            "",
            "⚠️ 风险提示:",
            "  • 市场有风险，投资需谨慎",
            "  • 严格执行止损，控制仓位",
            "  • 本信号仅供参考，不构成投资建议"
        ])
        
        content.message = "\n".join(message_parts)
        return content
    
    def _format_position_analysis(self, content: NotificationContent) -> NotificationContent:
        """格式化持仓分析"""
        # 如果消息已经有详细内容，就不要覆盖它
        if content.message and len(content.message.strip()) > 50:
            return content
            
        # 只有在消息为空或很短时才使用默认格式
        data = content.metadata
        
        message = f"""💼 账户持仓分析报告

📊 分析时间: {content.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

详细分析结果请查看交易系统...
        """
        
        content.message = message
        return content
    
    def _format_funding_rate(self, content: NotificationContent) -> NotificationContent:
        """格式化费率通知"""
        data = content.metadata
        
        # 如果标记跳过格式化，直接返回原内容
        if data.get('skip_formatting'):
            return content
            
        opportunities = data.get('opportunities', [])
        
        if not opportunities:
            content.message = "💰 暂无负费率机会"
            return content
        
        message_parts = [
            "💰 负费率机会汇总",
            f"🕐 {content.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"📈 发现 {len(opportunities)} 个机会:",
            ""
        ]
        
        for i, opp in enumerate(opportunities[:5], 1):
            symbol = opp.get('symbol', 'Unknown')
            rate = opp.get('funding_rate', 0)
            message_parts.append(f"{i}. {symbol}: {rate:.4%}")
        
        message_parts.append("")
        message_parts.append("⚠️ 请注意市场风险，合理配置仓位！")
        
        content.message = "\n".join(message_parts)
        return content
    
    def _format_grid_opportunity(self, content: NotificationContent) -> NotificationContent:
        """格式化网格机会"""
        data = content.metadata
        opportunities = data.get('opportunities', [])
        
        message_parts = [
            "🎯 网格交易机会",
            f"🕐 {content.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"📊 发现 {len(opportunities)} 个网格机会",
            ""
        ]
        
        for opp in opportunities[:3]:
            symbol = opp.get('symbol', 'Unknown')
            score = opp.get('score', 0)
            message_parts.append(f"• {symbol} (评分: {score})")
        
        content.message = "\n".join(message_parts)
        return content
    
    def _format_kronos_prediction(self, content: NotificationContent) -> NotificationContent:
        """格式化Kronos预测"""
        data = content.metadata
        symbol = data.get('symbol', 'Unknown')
        action = data.get('action', '未知')
        confidence = data.get('confidence', 0)
        
        message = f"""🤖 Kronos AI预测

🏷️ 交易对: {symbol}
📈 预测动作: {action}
🎯 置信度: {confidence:.1%}

⏰ 预测时间: {content.timestamp.strftime('%H:%M:%S')}

🚀 基于Kronos AI模型的智能预测！"""
        
        content.message = message
        return content
    
    def _format_ml_prediction(self, content: NotificationContent) -> NotificationContent:
        """格式化ML预测"""
        data = content.metadata
        
        message = f"""🧠 机器学习预测

📊 分析结果: {data.get('prediction', '未知')}
🎲 置信度: {data.get('confidence', 0):.1%}

⏰ 预测时间: {content.timestamp.strftime('%H:%M:%S')}"""
        
        content.message = message
        return content
    
    # ========== 渠道发送方法 ==========
    
    async def _send_feishu(self, message: str, priority: str = "normal") -> bool:
        """发送飞书通知"""
        try:
            # 兼容新旧配置格式
            webhook_url = (
                self.feishu_webhook or 
                self.notification_config.get('feishu', {}).get('webhook_url') or
                self.notification_config.get('feishu_webhook')
            )
            
            if not webhook_url:
                logger.warning("飞书webhook未配置")
                return False
            
            # 根据优先级添加标识
            priority_icons = {
                1: "🔵",  # LOW
                2: "🟢",  # NORMAL
                3: "🟡",  # HIGH
                4: "🔴"   # URGENT
            }
            
            formatted_message = f"{priority_icons.get(priority, '🟢')} {message}"
            
            payload = {
                "msg_type": "text",
                "content": {
                    "text": formatted_message
                }
            }
            
            response = await safe_http_request(
                'POST',
                webhook_url,
                json=payload,
                timeout=10
            )
            
            return response and response.get('code') == 0
            
        except Exception as e:
            logger.error(f"发送飞书通知失败: {e}")
            return False
    
    async def _send_telegram(self, message: str, priority: str = "normal") -> bool:
        """发送Telegram通知"""
        try:
            # 兼容新旧配置格式
            bot_token = (
                self.telegram_bot_token or
                self.notification_config.get('telegram', {}).get('bot_token') or
                self.notification_config.get('telegram_bot_token')
            )
            chat_id = (
                self.telegram_chat_id or
                self.notification_config.get('telegram', {}).get('chat_id') or
                self.notification_config.get('telegram_chat_id')
            )
            
            if not bot_token or not chat_id:
                logger.warning("Telegram配置未完整")
                return False
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            response = await safe_http_request(
                'POST',
                url,
                json=payload,
                timeout=10
            )
            
            return response and response.get('ok')
            
        except Exception as e:
            logger.error(f"发送Telegram通知失败: {e}")
            return False
    
    async def _send_wechat(self, message: str, priority: str = "normal") -> bool:
        """发送微信通知"""
        # 微信企业号通知实现
        logger.warning("微信通知功能待实现")
        return False
    
    async def _send_email(self, message: str, subject: str = None, priority: str = "normal") -> bool:
        """发送邮件通知"""
        try:
            email_config = self.notification_config.get('email', {})
            if not email_config.get('enabled'):
                return False
            
            # 邮件发送逻辑
            logger.info("邮件通知功能待完善")
            return True
            
        except Exception as e:
            logger.error(f"发送邮件通知失败: {e}")
            return False
    
    def _get_enabled_channels(self) -> List[str]:
        """获取启用的通知渠道"""
        enabled_channels = []
        
        if self.notification_config.get('feishu_webhook'):
            enabled_channels.append('feishu')
        
        if (self.notification_config.get('telegram_bot_token') and 
            self.notification_config.get('telegram_chat_id')):
            enabled_channels.append('telegram')
        
        # 其他渠道检查...
        
        return enabled_channels if enabled_channels else ['feishu']  # 默认飞书


# 全局服务实例
_core_notification_service = None


async def get_core_notification_service() -> CoreNotificationService:
    """获取核心通知服务实例"""
    global _core_notification_service
    if _core_notification_service is None:
        _core_notification_service = CoreNotificationService()
    return _core_notification_service
