# -*- coding: utf-8 -*-
"""
机器学习权重配置管理
ML Weight Configuration Management
"""

from typing import Dict
from enum import Enum
from app.core.logging import get_logger

logger = get_logger(__name__)


class MLMode(Enum):
    """ML模式"""
    DISABLED = "disabled"      # 禁用ML
    TRAINING = "training"      # 训练模式 - ML跟随传统信号学习
    BALANCED = "balanced"      # 平衡模式 - ML与传统信号平衡
    ENHANCED = "enhanced"      # 增强模式 - ML主导决策


class MLWeightConfig:
    """ML权重配置类"""
    
    def __init__(self):
        # 不同模式下的权重配置
        self.weight_configs = {
            MLMode.DISABLED: {
                'traditional': 0.95,
                'ml': 0.0,
                'kronos': 0.05
            },
            MLMode.TRAINING: {
                'traditional': 0.80,  # 传统信号主导
                'ml': 0.10,           # ML仅作参考，跟随学习
                'kronos': 0.10
            },
            MLMode.BALANCED: {
                'traditional': 0.60,
                'ml': 0.30,
                'kronos': 0.10
            },
            MLMode.ENHANCED: {
                'traditional': 0.30,
                'ml': 0.60,           # ML主导
                'kronos': 0.10
            }
        }
        
        # 当前模式 - 默认为训练模式
        self.current_mode = MLMode.TRAINING
        
        logger.info(f"🤖 ML权重配置初始化: 当前模式={self.current_mode.value}")
    
    def get_weights(self, mode: MLMode = None) -> Dict[str, float]:
        """
        获取指定模式的权重配置
        
        Args:
            mode: ML模式，None则使用当前模式
            
        Returns:
            权重配置字典
        """
        if mode is None:
            mode = self.current_mode
        
        weights = self.weight_configs.get(mode, self.weight_configs[MLMode.TRAINING])
        logger.debug(f"🔧 获取权重配置: 模式={mode.value}, 权重={weights}")
        return weights.copy()
    
    def set_mode(self, mode: MLMode):
        """
        设置ML模式
        
        Args:
            mode: 新的ML模式
        """
        old_mode = self.current_mode
        self.current_mode = mode
        
        logger.info(f"🔄 ML模式切换: {old_mode.value} -> {mode.value}")
        logger.info(f"📊 新权重配置: {self.get_weights()}")
    
    def get_ml_weight_for_api(self) -> float:
        """获取API使用的ML权重"""
        weights = self.get_weights()
        return weights.get('ml', 0.1)
    
    def get_traditional_weight_for_api(self) -> float:
        """获取API使用的传统权重"""
        weights = self.get_weights()
        return weights.get('traditional', 0.8)
    
    def should_use_ml(self) -> bool:
        """判断是否应该使用ML"""
        return self.current_mode != MLMode.DISABLED
    
    def get_ml_influence_level(self) -> str:
        """获取ML影响程度描述"""
        influence_map = {
            MLMode.DISABLED: "禁用",
            MLMode.TRAINING: "跟随学习",
            MLMode.BALANCED: "平衡参与", 
            MLMode.ENHANCED: "主导决策"
        }
        return influence_map.get(self.current_mode, "未知")


# 全局配置实例
ml_weight_config = MLWeightConfig()


def get_ml_weight_config() -> MLWeightConfig:
    """获取ML权重配置实例"""
    return ml_weight_config


def set_ml_mode(mode: MLMode):
    """设置全局ML模式"""
    ml_weight_config.set_mode(mode)


def get_current_ml_weights() -> Dict[str, float]:
    """获取当前ML权重配置"""
    return ml_weight_config.get_weights()