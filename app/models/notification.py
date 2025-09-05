# -*- coding: utf-8 -*-
"""
通知数据模型
Notification data models
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, Index
from sqlalchemy.dialects.mysql import JSON
from datetime import datetime

from .base import BaseModel, StatusMixin


class NotificationLog(BaseModel):
    """通知日志模型"""
    
    __tablename__ = "notification_log"
    
    channel = Column(String(20), nullable=False, comment="通知渠道")
    message_type = Column(String(50), nullable=False, comment="消息类型")
    recipient = Column(String(100), comment="接收者")
    subject = Column(String(200), comment="消息主题")
    content = Column(Text, nullable=False, comment="消息内容")
    
    # 发送状态
    status = Column(String(20), nullable=False, default="pending", comment="发送状态")
    sent_at = Column(DateTime, comment="发送时间")
    delivered_at = Column(DateTime, comment="送达时间")
    
    # 响应信息
    response_data = Column(JSON, comment="响应数据")
    error_message = Column(Text, comment="错误信息")
    retry_count = Column(Integer, default=0, comment="重试次数")
    
    # 关联信息
    source_type = Column(String(50), comment="来源类型")
    source_id = Column(String(100), comment="来源ID")
    
    # 创建索引
    __table_args__ = (
        Index('idx_channel_status', 'channel', 'status'),
        Index('idx_sent_at', 'sent_at'),
    )


class AlertRule(BaseModel, StatusMixin):
    """预警规则模型"""
    
    __tablename__ = "alert_rule"
    
    name = Column(String(100), nullable=False, comment="规则名称")
    rule_type = Column(String(50), nullable=False, comment="规则类型")
    description = Column(Text, comment="规则描述")
    
    # 条件配置
    conditions = Column(JSON, nullable=False, comment="触发条件")
    notification_template = Column(Text, comment="通知模板")
    
    # 通知配置
    notification_channels = Column(JSON, comment="通知渠道")
    priority = Column(String(20), default="normal", comment="优先级")
    
    # 限流配置
    cooldown_minutes = Column(Integer, default=5, comment="冷却时间(分钟)")
    last_triggered_at = Column(DateTime, comment="最后触发时间")
    
    # 统计信息
    trigger_count = Column(Integer, default=0, comment="触发次数")
    
    def can_trigger(self) -> bool:
        """检查是否可以触发"""
        if not self.is_active:
            return False
        
        if self.last_triggered_at and self.cooldown_minutes > 0:
            from datetime import datetime, timedelta
            cooldown_until = self.last_triggered_at + timedelta(minutes=self.cooldown_minutes)
            if datetime.now() < cooldown_until:
                return False
        
        return True
    
    def update_trigger(self):
        """更新触发信息"""
        self.last_triggered_at = datetime.now()
        self.trigger_count += 1
