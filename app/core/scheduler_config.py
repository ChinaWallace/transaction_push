# -*- coding: utf-8 -*-
"""
调度器配置管理
Scheduler Configuration Management
"""

from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum

class SchedulerMode(Enum):
    """调度器模式"""
    LEGACY_SCHEDULER = "legacy_scheduler"      # 使用老的 SchedulerService
    CORE_SCHEDULER = "core_scheduler"          # 使用新的 CoreSchedulerService
    BOTH_DISABLED = "both_disabled"            # 禁用所有调度器

@dataclass
class SchedulerConfig:
    """调度器配置"""
    
    # 核心币种推送调度器选择
    core_symbols_push_scheduler: SchedulerMode = SchedulerMode.LEGACY_SCHEDULER
    
    # 是否启用重复推送检测
    enable_duplicate_detection: bool = True
    
    # 推送间隔设置
    legacy_push_interval_minutes: int = 30     # 老调度器间隔 (30分钟)
    core_push_interval_minutes: int = 120      # 核心调度器间隔 (2小时)
    
    def should_use_legacy_scheduler(self) -> bool:
        """是否应该使用老的调度器"""
        return self.core_symbols_push_scheduler == SchedulerMode.LEGACY_SCHEDULER
    
    def should_use_core_scheduler(self) -> bool:
        """是否应该使用核心调度器"""
        return self.core_symbols_push_scheduler == SchedulerMode.CORE_SCHEDULER
    
    def is_push_disabled(self) -> bool:
        """推送是否被禁用"""
        return self.core_symbols_push_scheduler == SchedulerMode.BOTH_DISABLED

class SchedulerConfigManager:
    """调度器配置管理器"""
    
    def __init__(self):
        self._config = SchedulerConfig()
    
    def get_config(self) -> SchedulerConfig:
        """获取当前配置"""
        return self._config
    
    def set_scheduler_mode(self, mode: SchedulerMode) -> None:
        """设置调度器模式"""
        self._config.core_symbols_push_scheduler = mode
    
    def get_active_scheduler_info(self) -> Dict[str, Any]:
        """获取当前活跃的调度器信息"""
        config = self._config
        
        if config.should_use_legacy_scheduler():
            return {
                "active_scheduler": "SchedulerService",
                "push_interval_minutes": config.legacy_push_interval_minutes,
                "description": "使用老的调度服务进行核心币种推送"
            }
        elif config.should_use_core_scheduler():
            return {
                "active_scheduler": "CoreSchedulerService", 
                "push_interval_minutes": config.core_push_interval_minutes,
                "description": "使用核心调度服务进行核心币种推送"
            }
        else:
            return {
                "active_scheduler": "None",
                "push_interval_minutes": 0,
                "description": "核心币种推送已禁用"
            }

# 全局配置管理器实例
from typing import Optional
_scheduler_config_manager: Optional[SchedulerConfigManager] = None

def get_scheduler_config_manager() -> SchedulerConfigManager:
    """获取调度器配置管理器实例"""
    global _scheduler_config_manager
    if _scheduler_config_manager is None:
        _scheduler_config_manager = SchedulerConfigManager()
    return _scheduler_config_manager

def get_scheduler_config() -> SchedulerConfig:
    """获取调度器配置"""
    return get_scheduler_config_manager().get_config()

# 便捷函数
def use_core_scheduler():
    """设置使用核心调度器"""
    get_scheduler_config_manager().set_scheduler_mode(SchedulerMode.CORE_SCHEDULER)

def use_legacy_scheduler():
    """设置使用老调度器"""
    get_scheduler_config_manager().set_scheduler_mode(SchedulerMode.LEGACY_SCHEDULER)

def disable_all_schedulers():
    """禁用所有调度器"""
    get_scheduler_config_manager().set_scheduler_mode(SchedulerMode.BOTH_DISABLED)