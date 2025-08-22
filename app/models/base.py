# -*- coding: utf-8 -*-
"""
基础数据模型
Base data models
"""

from sqlalchemy import Column, Integer, DateTime, String, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declared_attr
from app.core.database import Base
from typing import Any
import json


class TimestampMixin:
    """时间戳混入类"""
    
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")


class BaseModel(Base, TimestampMixin):
    """基础模型类"""
    
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    
    @declared_attr
    def __tablename__(cls):
        # 将类名转换为下划线命名
        import re
        return re.sub('(?<!^)(?=[A-Z])', '_', cls.__name__).lower()
    
    def to_dict(self) -> dict:
        """转换为字典"""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, DateTime):
                result[column.name] = value.isoformat() if value else None
            else:
                result[column.name] = value
        return result
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
    
    @classmethod
    def from_dict(cls, data: dict):
        """从字典创建实例"""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
    
    def update_from_dict(self, data: dict):
        """从字典更新实例"""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"


class LogModel(BaseModel):
    """日志模型基类"""
    
    __abstract__ = True
    
    log_id = Column(String(64), nullable=False, index=True, comment="日志ID")
    level = Column(String(20), nullable=False, default="INFO", comment="日志级别")
    message = Column(Text, comment="日志消息")
    extra_data = Column(Text, comment="额外数据(JSON格式)")
    
    def set_extra_data(self, data: dict):
        """设置额外数据"""
        self.extra_data = json.dumps(data, ensure_ascii=False, default=str)
    
    def get_extra_data(self) -> dict:
        """获取额外数据"""
        if self.extra_data:
            try:
                return json.loads(self.extra_data)
            except json.JSONDecodeError:
                return {}
        return {}


class StatusMixin:
    """状态混入类"""
    
    status = Column(String(20), nullable=False, default="active", comment="状态")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    
    def activate(self):
        """激活"""
        self.is_active = True
        self.status = "active"
    
    def deactivate(self):
        """停用"""
        self.is_active = False
        self.status = "inactive"
