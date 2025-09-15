# -*- coding: utf-8 -*-
"""
核心币种推送配置管理
Core Symbols Push Configuration Management
"""

from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class PushMode(Enum):
    """推送模式"""
    SUMMARY_ONLY = "summary_only"      # 仅推送汇总报告
    INDIVIDUAL_ONLY = "individual_only"  # 仅推送单独信号
    BOTH = "both"                       # 推送汇总和单独信号
    DISABLED = "disabled"               # 禁用推送

@dataclass
class CoreSymbolsPushConfig:
    """核心币种推送配置"""
    
    # 推送模式设置
    push_mode: PushMode = PushMode.SUMMARY_ONLY
    
    # 推送间隔设置（分钟）
    push_interval_minutes: int = 30  # 30分钟
    
    # 核心币种列表
    core_symbols: List[str] = None
    
    # 推送条件设置
    min_confidence_threshold: float = 0.3  # 最低置信度阈值
    min_signals_for_push: int = 1          # 最少信号数量才推送
    
    def __post_init__(self):
        """初始化后处理"""
        if self.core_symbols is None:
            # 默认核心币种
            self.core_symbols = [
                "BTC-USDT-SWAP",
                "ETH-USDT-SWAP", 
                "SOL-USDT-SWAP",
                "DOGE-USDT-SWAP"
            ]

class PushConfigManager:
    """推送配置管理器"""
    
    def __init__(self):
        self._config = CoreSymbolsPushConfig()
    
    def get_config(self) -> CoreSymbolsPushConfig:
        """获取当前配置"""
        return self._config
    
    def update_push_mode(self, mode: PushMode) -> None:
        """更新推送模式"""
        self._config.push_mode = mode
    
    def should_push_summary(self) -> bool:
        """是否应该推送汇总报告"""
        return self._config.push_mode in [PushMode.SUMMARY_ONLY, PushMode.BOTH]
    
    def should_push_individual(self) -> bool:
        """是否应该推送单独信号"""
        return self._config.push_mode in [PushMode.INDIVIDUAL_ONLY, PushMode.BOTH]
    
    def is_push_enabled(self) -> bool:
        """推送是否启用"""
        return self._config.push_mode != PushMode.DISABLED
    
    def get_current_mode(self) -> PushMode:
        """获取当前推送模式"""
        return self._config.push_mode
    
    def get_push_config(self) -> Dict[str, Any]:
        """获取推送配置字典"""
        return {
            "push_mode": self._config.push_mode.value,
            "push_interval_minutes": self._config.push_interval_minutes,
            "core_symbols": self._config.core_symbols,
            "min_confidence_threshold": self._config.min_confidence_threshold,
            "min_signals_for_push": self._config.min_signals_for_push
        }

# 全局配置管理器实例
from typing import Optional
_push_config_manager: Optional[PushConfigManager] = None

def get_push_config_manager() -> PushConfigManager:
    """获取推送配置管理器实例"""
    global _push_config_manager
    if _push_config_manager is None:
        _push_config_manager = PushConfigManager()
    return _push_config_manager

def get_push_config() -> CoreSymbolsPushConfig:
    """获取推送配置"""
    return get_push_config_manager().get_config()

def set_summary_only_mode():
    """设置为仅汇总模式"""
    get_push_config_manager().update_push_mode(PushMode.SUMMARY_ONLY)