# -*- coding: utf-8 -*-
"""
核心通知服务
Core Notification Service - 统一管理所有类型的通知推送
整合原有的所有通知功能，支持分类推送和智能过滤
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, List, Optional, Callable, Union
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError
from app.utils.feishu_table_card import FeishuTableCardBuilder

logger = get_logger(__name__)

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
    MARKET_ANALYSIS = "市场分析"

class NotificationChannel(Enum):
    """通知渠道"""
    FEISHU = "feishu"
    WECHAT = "wechat"
    TELEGRAM = "telegram"
    EMAIL = "email"

class NotificationPriority(Enum):
    """通知优先级"""
    LOW = 1
    NORMAL = 2
    MEDIUM = 3
    HIGH = 4
    URGENT = 5

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
    """核心通知服务"""
    
    def __init__(self):
        """初始化通知服务"""
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 通知配置 - 使用 getattr 避免配置不存在的问题
        self.feishu_webhook_url = getattr(self.settings, 'feishu_webhook_url', None)
        self.wechat_webhook_url = getattr(self.settings, 'wechat_webhook_url', None)
        self.enable_notifications = getattr(self.settings, 'enable_notifications', True)
        
        # HTTP 会话
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
        
        try:
            # 创建 HTTP 会话
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            
            self.initialized = True
            self.logger.info("✅ 核心通知服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 核心通知服务初始化失败: {e}")
            raise TradingToolError(f"通知服务初始化失败: {str(e)}") from e
    
    async def cleanup(self) -> None:
        """清理资源"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.initialized = False
        self.logger.info("🧹 核心通知服务资源已清理")
    
    async def send_notification(
        self,
        message: Union[str, NotificationContent, Dict[str, Any]],
        priority: Union[NotificationPriority, int] = NotificationPriority.NORMAL,
        channels: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        发送通知消息 - 支持字符串和 NotificationContent 对象
        Send notification message - supports both string and NotificationContent objects
        
        Args:
            message: 通知消息内容或 NotificationContent 对象
            priority: 通知优先级
            channels: 指定通知渠道，None 表示所有渠道
            
        Returns:
            Dict[str, bool]: 各渠道发送结果
        """
        if not self.initialized:
            await self.initialize()
        
        if not self.enable_notifications:
            self.logger.info("📴 通知功能已禁用")
            return {"disabled": True}
        
        # 处理不同类型的消息
        if isinstance(message, NotificationContent):
            actual_message = message.message
            priority_value = self._coerce_priority(message.priority)
        elif isinstance(message, dict):
            # 预构建的卡片数据，直接使用
            actual_message = "预构建卡片"
            priority_value = self._coerce_priority(priority)
        else:
            actual_message = str(message)
            priority_value = self._coerce_priority(priority)
        
        # 默认使用所有可用渠道
        if channels is None:
            channels = []
            if self.feishu_webhook_url:
                channels.append("feishu")
            if self.wechat_webhook_url:
                channels.append("wechat")
        
        results = {}
        
        # 并发发送到各个渠道
        tasks = []
        for channel in channels:
            if channel == "feishu" and self.feishu_webhook_url:
                tasks.append(self._send_feishu(message, priority_value))
            elif channel == "wechat" and self.wechat_webhook_url:
                tasks.append(self._send_wechat(actual_message, priority_value))
        
        if tasks:
            channel_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(channel_results):
                channel_name = channels[i] if i < len(channels) else f"channel_{i}"
                if isinstance(result, Exception):
                    self.logger.error(f"❌ {channel_name} 发送失败: {result}")
                    results[channel_name] = False
                else:
                    results[channel_name] = result
        
        return results

    @staticmethod
    def _coerce_priority(priority: Union[NotificationPriority, int, str, None]) -> NotificationPriority:
        if isinstance(priority, NotificationPriority):
            return priority
        if isinstance(priority, int):
            try:
                return NotificationPriority(priority)
            except ValueError:
                return NotificationPriority.NORMAL
        if isinstance(priority, str):
            normalized = priority.strip().lower()
            name_map = {
                "low": NotificationPriority.LOW,
                "normal": NotificationPriority.NORMAL,
                "medium": NotificationPriority.MEDIUM,
                "high": NotificationPriority.HIGH,
                "urgent": NotificationPriority.URGENT,
            }
            if normalized in name_map:
                return name_map[normalized]
            try:
                return NotificationPriority(int(normalized))
            except (TypeError, ValueError):
                return NotificationPriority.NORMAL
        return NotificationPriority.NORMAL
    
    async def _send_feishu(self, message: Union[str, NotificationContent, Dict[str, Any]], priority: NotificationPriority) -> bool:
        """发送飞书卡片消息 - 支持 NotificationContent 对象和预构建卡片"""
        try:
            # 检查是否是预构建的卡片数据
            if isinstance(message, dict) and "header" in message and "elements" in message:
                # 直接使用预构建的卡片数据
                card_data = message
                self.logger.info("📋 使用预构建的专用卡片数据")
            else:
                # 构建飞书卡片 - 传递原始消息对象
                card_data = self._build_feishu_card(message, priority.value)
                self.logger.info("🔧 使用通用卡片构建器")
            
            payload = {
                "msg_type": "interactive",
                "card": card_data
            }
            
            # 第一次尝试发送
            success = await self._try_send_feishu_message(payload)
            if success:
                return True
            
            # 如果失败，等待1秒后重试一次
            self.logger.warning("⚠️ 飞书消息发送失败，1秒后重试...")
            await asyncio.sleep(1)
            
            # 第二次尝试发送
            success = await self._try_send_feishu_message(payload)
            if success:
                self.logger.info("✅ 飞书消息重试发送成功")
                return True
            else:
                self.logger.error("❌ 飞书消息重试后仍然失败")
                return False
                    
        except Exception as e:
            self.logger.error(f"❌ 飞书消息发送异常: {e}")
            return False
    
    async def _try_send_feishu_message(self, payload: Dict[str, Any]) -> bool:
        """尝试发送飞书消息的具体实现"""
        try:
            async with self.session.post(
                self.feishu_webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == 0:
                        self.logger.info("✅ 飞书卡片消息发送成功")
                        return True
                    elif result.get("code") == 11232:
                        # 频率限制错误
                        self.logger.warning(f"⚠️ 飞书消息发送频率限制 (错误码11232): {result.get('msg', '未知错误')}")
                        return False
                    else:
                        self.logger.error(f"❌ 飞书消息发送失败: {result}")
                        return False
                else:
                    self.logger.error(f"❌ 飞书 HTTP 请求失败: {response.status}")
                    return False
        except Exception as e:
            self.logger.error(f"❌ 飞书消息发送请求异常: {e}")
            return False
    
    async def _send_wechat(self, message: str, priority: NotificationPriority) -> bool:
        """发送企业微信消息"""
        try:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }
            
            async with self.session.post(
                self.wechat_webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("errcode") == 0:
                        self.logger.info("✅ 企业微信消息发送成功")
                        return True
                    else:
                        self.logger.error(f"❌ 企业微信消息发送失败: {result}")
                        return False
                else:
                    self.logger.error(f"❌ 企业微信 HTTP 请求失败: {response.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"❌ 企业微信消息发送异常: {e}")
            return False
    
    def _build_feishu_card(self, message: Union[str, NotificationContent], priority: int = 2) -> Dict[str, Any]:
        """构建飞书卡片消息 - 修复版本，支持 NotificationContent 对象"""
        try:
            # 处理 NotificationContent 对象
            if isinstance(message, NotificationContent):
                actual_message = message.message
                title = message.title
                priority = message.priority.value if hasattr(message.priority, 'value') else priority
            else:
                # 处理字符串消息
                actual_message = str(message)
                lines = actual_message.split('\n')
                title = lines[0] if lines else "交易通知"
            
            # 解析消息内容，提取关键信息
            lines = actual_message.split('\n')
            
            # 根据优先级设置颜色主题
            priority_colors = {
                1: "blue",     # LOW - 蓝色
                2: "green",    # NORMAL - 绿色  
                3: "orange",   # HIGH - 橙色
                4: "red"       # URGENT - 红色
            }
            
            theme_color = priority_colors.get(priority, "green")
            
            # 检测消息类型
            is_tradingview_scanner = "TV强势标的筛选器" in actual_message
            is_position_analysis = any(keyword in actual_message for keyword in ["持仓分析", "账户持仓", "持仓报告", "持仓建议", "持仓风险"])
            is_trading_signal = (not is_tradingview_scanner and not is_position_analysis and 
                               any(keyword in actual_message for keyword in ["交易信号", "强信号", "买入", "卖出", "BTC", "ETH"]))
            is_funding_rate = "负费率" in actual_message or "funding" in actual_message.lower()
            is_system_alert = "系统" in actual_message or "启动" in actual_message
            
            if is_tradingview_scanner:
                return FeishuTableCardBuilder.build_tradingview_table_card(actual_message, lines)
            elif is_position_analysis:
                return self._build_position_analysis_card(actual_message, lines, theme_color)
            elif is_trading_signal:
                return self._build_trading_signal_card(actual_message, lines, theme_color)
            elif is_funding_rate:
                return self._build_funding_rate_card(actual_message, lines, theme_color, {})
            elif is_system_alert:
                return self._build_system_alert_card(actual_message, lines, theme_color)
            else:
                return self._build_general_card(actual_message, lines, theme_color)
                
        except Exception as e:
            self.logger.error(f"构建飞书卡片失败: {e}")
            # 降级到简单卡片
            message_str = message.message if isinstance(message, NotificationContent) else str(message)
            return self._build_simple_card(message_str)
    
    def _build_trading_signal_card(self, message: str, lines: List[str], theme_color: str) -> Dict[str, Any]:
        """构建交易信号卡片"""
        # 提取交易信号关键信息
        symbol = "Unknown"
        action = "Unknown"
        confidence = "0%"
        price = "N/A"
        
        for line in lines:
            if "交易动作:" in line or "交易方向:" in line:
                action = line.split(":")[-1].strip()
            elif "信号强度:" in line or "置信度:" in line:
                confidence = line.split(":")[-1].strip()
            elif "当前价格:" in line:
                price = line.split(":")[-1].strip()
            elif any(crypto in line for crypto in ["BTC", "ETH", "SOL", "DOGE"]):
                # 提取交易对
                for word in line.split():
                    if any(crypto in word for crypto in ["BTC", "ETH", "SOL", "DOGE"]):
                        symbol = word.replace("【", "").replace("】", "")
                        break
        
        # 构建卡片内容
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": theme_color,
                "title": {
                    "content": f"🚀 交易信号 - {symbol}",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**交易对**\n{symbol}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**交易动作**\n{action}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**信号强度**\n{confidence}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**当前价格**\n{price}",
                                "tag": "lark_md"
                            }
                        }
                    ]
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "content": self._format_message_for_card(message),
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ 信号时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        
        return card
    
    def _build_position_analysis_card(self, message: str, lines: List[str], theme_color: str) -> Dict[str, Any]:
        """构建持仓分析卡片"""
        # 提取持仓分析关键信息
        total_positions = "0"
        total_pnl = "0%"
        risk_level = "未知"
        overall_score = "0"
        
        for line in lines:
            if "总持仓:" in line or "持仓数量:" in line:
                total_positions = line.split(":")[-1].strip()
            elif "总盈亏:" in line or "整体盈亏:" in line:
                total_pnl = line.split(":")[-1].strip()
            elif "风险等级:" in line or "风险评级:" in line:
                risk_level = line.split(":")[-1].strip()
            elif "评分:" in line or "得分:" in line:
                overall_score = line.split(":")[-1].strip().replace("/100", "")
        
        # 根据风险等级设置颜色
        risk_color = "green"
        if "高风险" in risk_level or "危险" in risk_level:
            risk_color = "red"
        elif "中等风险" in risk_level:
            risk_color = "orange"
        
        # 构建卡片内容
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "blue",  # 持仓分析使用蓝色主题
                "title": {
                    "content": "💼 持仓分析报告",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**持仓数量**\n{total_positions}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**整体盈亏**\n{total_pnl}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**风险等级**\n<font color='{risk_color}'>{risk_level}</font>",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**健康评分**\n{overall_score}/100",
                                "tag": "lark_md"
                            }
                        }
                    ]
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "content": self._format_message_for_card(message),
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        
        return card
    
    def _build_funding_rate_card(self, message: str, lines: List[str], theme_color: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """构建负费率卡片"""
        # 优先从 metadata 中获取机会数量
        opportunities_count = 0
        if metadata and 'opportunities_count' in metadata:
            opportunities_count = metadata.get('opportunities_count', 0)
        else:
            # 备用方案：从消息文本中提取
            for line in lines:
                if "发现" in line and ("个机会" in line or "个负费率" in line):
                    try:
                        opportunities_count = int(''.join(filter(str.isdigit, line)))
                    except:
                        opportunities_count = 0
                    break
        
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "orange",
                "title": {
                    "content": "💰 负费率机会",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**机会数量**\n{opportunities_count} 个",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**扫描时间**\n{datetime.now().strftime('%H:%M:%S')}",
                                "tag": "lark_md"
                            }
                        }
                    ]
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "content": self._format_message_for_card(message),
                        "tag": "lark_md"
                    }
                }
            ]
        }
        
        return card
    
    def _build_system_alert_card(self, message: str, lines: List[str], theme_color: str) -> Dict[str, Any]:
        """构建系统警报卡片"""
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "blue",
                "title": {
                    "content": "🔔 系统通知",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": self._format_message_for_card(message),
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ 通知时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        
        return card
    
    def _build_general_card(self, message: str, lines: List[str], theme_color: str) -> Dict[str, Any]:
        """构建通用卡片"""
        title = lines[0] if lines else "交易通知"
        
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": theme_color,
                "title": {
                    "content": title,
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": self._format_message_for_card(message),
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"⏰ 通知时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        
        return card
    
    def _build_simple_card(self, message: str) -> Dict[str, Any]:
        """构建简单卡片（降级方案）"""
        return {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "blue",
                "title": {
                    "content": "📢 交易通知",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": message,
                        "tag": "plain_text"
                    }
                }
            ]
        }
    
    async def send_core_symbols_report(self, signals: List[Any]) -> bool:
        """发送增强版核心币种分析报告 - 包含详细技术分析和操作建议"""
        try:
            if not self.initialized:
                await self.initialize()
            
            if not signals:
                self.logger.warning("⚠️ 没有分析信号，跳过核心币种报告推送")
                return False
            
            # 导入增强版卡片构建器
            from app.utils.enhanced_core_symbols_card_builder import EnhancedCoreSymbolsCardBuilder
            
            # 构建增强版卡片 (包含详细技术分析和操作建议)
            card_content = EnhancedCoreSymbolsCardBuilder.build_enhanced_core_symbols_card(
                signals=signals,
                notification_type="核心币种增强分析"
            )
            
            # 发送卡片通知
            result = await self.send_notification(
                message=card_content,
                priority=NotificationPriority.NORMAL
            )
            
            # 检查发送结果
            success = any(result.values()) if isinstance(result, dict) else bool(result)
            
            if success:
                self.logger.info(f"✅ 增强版核心币种报告推送成功 ({len(signals)}个币种) - 包含详细操作建议")
            else:
                self.logger.warning("❌ 增强版核心币种报告推送失败")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ 发送增强版核心币种报告失败: {e}")
            # 回退到基础版本
            try:
                from app.utils.core_symbols_card_builder import CoreSymbolsCardBuilder
                card_builder = CoreSymbolsCardBuilder()
                card_content = card_builder.build_core_symbols_card(signals)
                
                result = await self.send_notification(
                    message=card_content,
                    priority=NotificationPriority.NORMAL
                )
                
                success = any(result.values()) if isinstance(result, dict) else bool(result)
                if success:
                    self.logger.info(f"✅ 基础版核心币种报告推送成功 (回退模式)")
                return success
            except Exception as fallback_e:
                self.logger.error(f"❌ 回退推送也失败: {fallback_e}")
                return False
    
    def _format_message_for_card(self, message: str) -> str:
        """格式化消息内容适配卡片显示"""
        # 移除过长的分隔线
        message = message.replace("=" * 40, "---")
        message = message.replace("=" * 35, "---")
        
        # 转换为 Markdown 格式
        lines = message.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                formatted_lines.append("")
                continue
                
            # 处理标题行
            if line.startswith("🎯") or line.startswith("💰") or line.startswith("🚀"):
                formatted_lines.append(f"**{line}**")
            # 处理分类标题
            elif line.endswith(":") and any(keyword in line for keyword in ["风险管理", "收益预期", "仓位建议", "技术分析", "分析评分"]):
                formatted_lines.append(f"**{line}**")
            # 处理列表项
            elif line.startswith("  •") or line.startswith("  ✓"):
                formatted_lines.append(line)
            # 处理普通内容
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "service": "CoreNotificationService",
            "initialized": self.initialized,
            "notifications_enabled": self.enable_notifications,
            "channels": {
                "feishu": bool(self.feishu_webhook_url),
                "wechat": bool(self.wechat_webhook_url)
            },
            "session_active": self.session is not None and not self.session.closed if self.session else False
        }

# 全局服务实例
_core_notification_service: Optional[CoreNotificationService] = None

async def get_core_notification_service() -> CoreNotificationService:
    """获取核心通知服务实例 - 全局单例"""
    global _core_notification_service
    if _core_notification_service is None:
        _core_notification_service = CoreNotificationService()
        await _core_notification_service.initialize()
    return _core_notification_service
