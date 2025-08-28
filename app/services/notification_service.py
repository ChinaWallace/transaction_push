# -*- coding: utf-8 -*-
"""
通知推送服务
Notification service for sending alerts and notifications
"""

import asyncio
import json
import hmac
import hashlib
import base64
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from app.core.config import get_settings
from app.core.logging import get_logger, monitor_logger
from app.utils.http_manager import get_http_manager, safe_http_request
from app.utils.exceptions import NotificationError
from app.models.notification import NotificationLog, AlertRule

logger = get_logger(__name__)
settings = get_settings()


class NotificationService:
    """通知推送服务类"""
    
    def __init__(self):
        self.http_manager = None  # 延迟初始化
        self.notification_config = settings.notification_config
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._get_http_manager()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"通知服务异常: {exc_type.__name__}: {exc_val}")
        # HTTP管理器由全局管理，这里不需要关闭
    
    async def _get_http_manager(self):
        """获取HTTP管理器实例"""
        if self.http_manager is None:
            self.http_manager = await get_http_manager()
        return self.http_manager
    
    async def send_notification(self, 
                              message: str, 
                              channels: List[str] = None,
                              priority: str = "normal",
                              subject: str = None,
                              title: str = None,
                              notification_type: str = "general") -> Dict[str, bool]:
        """
        发送通知到指定渠道
        
        Args:
            message: 通知消息内容
            channels: 通知渠道列表，如果为None则使用所有启用的渠道
            priority: 优先级 (low/normal/high/urgent)
            subject: 消息主题（用于邮件）
            title: 通知标题（兼容性参数，与subject相同）
            notification_type: 通知类型
            
        Returns:
            各渠道发送结果
        """
        # 兼容性处理：如果提供了title但没有subject，使用title作为subject
        if title and not subject:
            subject = title
        if channels is None:
            channels = self._get_enabled_channels()
        
        results = {}
        tasks = []
        
        for channel in channels:
            task = self._send_to_channel(channel, message, priority, subject)
            tasks.append((channel, task))
        
        # 并发发送到各个渠道
        for channel, task in tasks:
            try:
                success = await task
                results[channel] = success
                if success:
                    monitor_logger.info(f"Notification sent successfully to {channel}")
                else:
                    monitor_logger.error(f"Failed to send notification to {channel}")
            except Exception as e:
                logger.error(f"Error sending notification to {channel}: {e}")
                results[channel] = False
        
        return results
    
    async def _send_to_channel(self, 
                             channel: str, 
                             message: str, 
                             priority: str,
                             subject: str = None) -> bool:
        """向指定渠道发送消息"""
        try:
            if channel == "feishu":
                return await self._send_feishu(message, priority)
            elif channel == "wechat":
                return await self._send_wechat(message, priority)
            elif channel == "telegram":
                return await self._send_telegram(message, priority)
            elif channel == "email":
                return await self._send_email(message, subject, priority)
            else:
                logger.warning(f"Unknown notification channel: {channel}")
                return False
        except Exception as e:
            logger.error(f"Error in _send_to_channel for {channel}: {e}")
            return False
    
    async def _send_feishu(self, message: str, priority: str = "normal") -> bool:
        """发送飞书消息"""
        config = self.notification_config["feishu"]
        if not config["enabled"]:
            logger.warning("Feishu notification is disabled")
            return False
        
        webhook_url = config["webhook_url"]
        
        # 根据优先级添加表情符号
        priority_emojis = {
            "low": "ℹ️",
            "normal": "📊", 
            "high": "⚠️",
            "urgent": "🚨"
        }
        
        formatted_message = f"{priority_emojis.get(priority, '📊')} {message}"
        
        payload = {
            "msg_type": "text",
            "content": {
                "text": formatted_message
            }
        }
        
        try:
            response = await safe_http_request(
                'POST',
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            # 飞书API成功响应应该包含 StatusCode: 0
            if response.get("StatusCode") == 0:
                return True
            else:
                logger.error(f"Feishu API error: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Feishu message: {e}")
            return False
    
    async def _send_wechat(self, message: str, priority: str = "normal") -> bool:
        """发送企业微信消息"""
        config = self.notification_config["wechat"]
        if not config["enabled"]:
            logger.warning("WeChat notification is disabled")
            return False
        
        webhook_url = config["webhook_url"]
        
        payload = {
            "msgtype": "text",
            "text": {
                "content": message
            }
        }
        
        try:
            response = await safe_http_request(
                'POST',
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.get("errcode") == 0:
                return True
            else:
                logger.error(f"WeChat API error: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send WeChat message: {e}")
            return False
    
    async def _send_telegram(self, message: str, priority: str = "normal") -> bool:
        """发送Telegram消息"""
        config = self.notification_config["telegram"]
        if not config["enabled"]:
            logger.warning("Telegram notification is disabled")
            return False
        
        bot_token = config["bot_token"]
        chat_id = config["chat_id"]
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = await safe_http_request(
                'POST',
                url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.get("ok"):
                return True
            else:
                logger.error(f"Telegram API error: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def _send_email(self, message: str, subject: str = None, priority: str = "normal") -> bool:
        """发送邮件通知"""
        config = self.notification_config["email"]
        if not config["enabled"]:
            logger.warning("Email notification is disabled")
            return False
        
        try:
            # 在线程池中执行同步邮件发送
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, 
                self._send_email_sync, 
                message, 
                subject or "交易分析工具通知",
                priority
            )
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def _send_email_sync(self, message: str, subject: str, priority: str) -> bool:
        """同步发送邮件"""
        config = self.notification_config["email"]
        
        msg = MIMEMultipart()
        msg['From'] = config["smtp_from"]
        msg['To'] = config["smtp_from"]  # 发送给自己
        msg['Subject'] = f"[{priority.upper()}] {subject}"
        
        # 添加消息内容
        body = MIMEText(message, 'plain', 'utf-8')
        msg.attach(body)
        
        try:
            # 连接SMTP服务器
            server = smtplib.SMTP(config["smtp_host"], config["smtp_port"])
            server.starttls()
            server.login(config["smtp_user"], config["smtp_password"])
            
            # 发送邮件
            text = msg.as_string()
            server.sendmail(config["smtp_from"], [config["smtp_from"]], text)
            server.quit()
            
            return True
            
        except Exception as e:
            logger.error(f"SMTP error: {e}")
            return False
    
    def _get_enabled_channels(self) -> List[str]:
        """获取所有启用的通知渠道"""
        enabled_channels = []
        for channel, config in self.notification_config.items():
            if config.get("enabled", False):
                enabled_channels.append(channel)
        return enabled_channels
    
    async def send_funding_rate_alert(self, 
                                    symbols_data: List[Dict[str, Any]],
                                    alert_type: str = "negative_rate") -> bool:
        """发送资金费率预警"""
        try:
            if alert_type == "negative_rate":
                message = self._format_funding_rate_message(symbols_data, "负费率")
            elif alert_type == "high_rate":
                message = self._format_funding_rate_message(symbols_data, "高费率")
            else:
                message = self._format_funding_rate_message(symbols_data, "费率异常")
            
            results = await self.send_notification(
                message,
                priority="high" if alert_type != "negative_rate" else "normal"
            )
            
            return any(results.values())
            
        except Exception as e:
            logger.error(f"Failed to send funding rate alert: {e}")
            return False
    
    async def send_open_interest_alert(self, 
                                     symbols_data: List[Dict[str, Any]]) -> bool:
        """发送持仓量变化预警"""
        try:
            message = self._format_open_interest_message(symbols_data)
            
            results = await self.send_notification(
                message,
                priority="high"
            )
            
            return any(results.values())
            
        except Exception as e:
            logger.error(f"Failed to send open interest alert: {e}")
            return False
    
    async def send_volume_alert(self, 
                              symbols_data: List[Dict[str, Any]]) -> bool:
        """发送交易量异常预警"""
        try:
            message = self._format_volume_message(symbols_data)
            
            results = await self.send_notification(
                message,
                priority="normal"
            )
            
            return any(results.values())
            
        except Exception as e:
            logger.error(f"Failed to send volume alert: {e}")
            return False
    
    def _format_funding_rate_message(self, 
                                   symbols_data: List[Dict[str, Any]], 
                                   alert_type: str) -> str:
        """格式化资金费率消息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        message = f"""📊 【资金费率监控 - {alert_type}】

⏰ 监控时间：{timestamp}

"""
        
        if alert_type == "负费率":
            message += "💰 负费率TOP5标的：\n"
            for i, data in enumerate(symbols_data[:5], 1):
                rate_percent = float(data['funding_rate']) * 100
                message += f"{i}. {data['symbol']}: {rate_percent:.4f}%\n"
        else:
            message += f"⚠️ {alert_type}标的：\n"
            for data in symbols_data:
                rate_percent = float(data['funding_rate']) * 100
                message += f"• {data['symbol']}: {rate_percent:.4f}%\n"
        
        message += f"\n💡 说明：资金费率反映市场情绪，负费率表示做空需要向做多支付费用"
        
        return message
    
    def _format_open_interest_message(self, symbols_data: List[Dict[str, Any]]) -> str:
        """格式化持仓量变化消息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        message = f"""📈 【持仓量变化监控】

⏰ 监控时间：{timestamp}

🔄 持仓量异常增长标的：
"""
        
        for data in symbols_data:
            change_percent = (data['change_ratio'] - 1) * 100
            message += f"• {data['symbol']}: +{change_percent:.1f}%\n"
            message += f"  当前持仓量: {data['current_oi']:,.0f}\n"
        
        message += f"\n💡 说明：持仓量大幅增长可能表示市场活动加剧"
        
        return message
    
    def _format_volume_message(self, symbols_data: List[Dict[str, Any]]) -> str:
        """格式化交易量异常消息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        message = f"""📊 【交易量异常监控 - 庄神指标】

⏰ 监控时间：{timestamp}

说明：使用最近三根已收盘的K线数据，收盘价需高于前一根K线的收盘价
强势标的：成交量连续是前一根K线的3倍及以上
一般标的：最近一根收盘K线的成交量是前一根K线的3倍及以上

"""
        
        strong_symbols = [s for s in symbols_data if s.get('anomaly_type') == 'strong']
        normal_symbols = [s for s in symbols_data if s.get('anomaly_type') == 'normal']
        
        if strong_symbols:
            message += "🚀 强势标的：\n"
            for data in strong_symbols:
                message += f"• {data['symbol']}: {data['volume_ratio']:.1f}倍放量\n"
            message += "\n"
        
        if normal_symbols:
            message += "📈 一般标的：\n"
            for data in normal_symbols:
                message += f"• {data['symbol']}: {data['volume_ratio']:.1f}倍放量\n"
        
        return message
    
    async def test_notifications(self) -> Dict[str, bool]:
        """测试所有通知渠道"""
        test_message = f"""🧪 通知测试

这是一条测试消息，用于验证通知渠道是否正常工作。

⏰ 测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔧 系统状态：运行正常
📊 功能：Python交易分析工具"""
        
        return await self.send_notification(
            test_message,
            priority="low",
            subject="通知系统测试"
        )
