# -*- coding: utf-8 -*-
"""
交易权重管理器
Trading Weight Manager - 统一管理各个交易组件的权重配置
"""

from typing import Dict, Any
from datetime import datetime
from app.core.logging import get_logger
from app.core.ml_weight_config import get_ml_weight_config, MLMode

logger = get_logger(__name__)


class TradingWeightManager:
    """交易权重管理器"""
    
    def __init__(self):
        self.ml_config = get_ml_weight_config()
        self.last_update = datetime.now()
        
        # 性能监控数据
        self.performance_history = {
            'ml_accuracy': [],
            'traditional_accuracy': [],
            'kronos_accuracy': []
        }
        
        logger.info("🔧 交易权重管理器初始化完成")
    
    def get_core_trading_weights(self) -> Dict[str, float]:
        """获取核心交易服务权重"""
        base_weights = self.ml_config.get_weights()
        
        return {
            'kronos': 0.50,                                    # Kronos保持稳定权重
            'technical': base_weights.get('traditional', 0.40), # 技术分析权重
            'ml': base_weights.get('ml', 0.05),                # ML权重(动态)
            'position': 0.05                                   # 持仓分析权重
        }
    
    def get_notification_ml_threshold(self) -> float:
        """获取通知服务的ML阈值"""
        mode = self.ml_config.current_mode
        
        thresholds = {
            MLMode.DISABLED: 1.0,    # 实际上禁用ML影响
            MLMode.TRAINING: 0.8,    # 高阈值，减少ML影响
            MLMode.BALANCED: 0.6,    # 中等阈值
            MLMode.ENHANCED: 0.4     # 低阈值，增加ML影响
        }
        
        return thresholds.get(mode, 0.8)
    
    def get_api_weights(self) -> Dict[str, float]:
        """获取API使用的权重"""
        return {
            'traditional': self.ml_config.get_traditional_weight_for_api(),
            'ml': self.ml_config.get_ml_weight_for_api()
        }
    
    def should_trust_ml_signal(self, ml_confidence: float) -> bool:
        """判断是否应该信任ML信号"""
        mode = self.ml_config.current_mode
        
        if mode == MLMode.DISABLED:
            return False
        elif mode == MLMode.TRAINING:
            # 训练模式下，只有极高置信度才信任
            return ml_confidence > 0.9
        elif mode == MLMode.BALANCED:
            return ml_confidence > 0.7
        elif mode == MLMode.ENHANCED:
            return ml_confidence > 0.6
        
        return False
    
    def get_ml_influence_factor(self) -> float:
        """获取ML影响因子"""
        mode = self.ml_config.current_mode
        
        factors = {
            MLMode.DISABLED: 0.0,
            MLMode.TRAINING: 0.1,    # 很低的影响
            MLMode.BALANCED: 0.3,
            MLMode.ENHANCED: 0.6
        }
        
        return factors.get(mode, 0.1)
    
    def update_performance(self, component: str, accuracy: float):
        """更新组件性能数据"""
        if component in self.performance_history:
            self.performance_history[component].append({
                'timestamp': datetime.now(),
                'accuracy': accuracy
            })
            
            # 只保留最近100条记录
            if len(self.performance_history[component]) > 100:
                self.performance_history[component] = self.performance_history[component][-100:]
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        summary = {}
        
        for component, history in self.performance_history.items():
            if history:
                recent_accuracy = [h['accuracy'] for h in history[-10:]]  # 最近10次
                summary[component] = {
                    'recent_avg_accuracy': sum(recent_accuracy) / len(recent_accuracy),
                    'total_records': len(history),
                    'last_update': history[-1]['timestamp'] if history else None
                }
        
        return summary
    
    def auto_adjust_weights(self) -> bool:
        """根据性能自动调整权重"""
        try:
            performance = self.get_performance_summary()
            
            # 如果ML表现持续不佳，自动降级到训练模式
            ml_perf = performance.get('ml_accuracy', {})
            if ml_perf.get('recent_avg_accuracy', 0) < 0.6 and self.ml_config.current_mode != MLMode.TRAINING:
                logger.warning("⚠️ ML表现不佳，自动切换到训练模式")
                self.ml_config.set_mode(MLMode.TRAINING)
                return True
            
            # 如果ML表现优异且稳定，可以考虑升级
            elif (ml_perf.get('recent_avg_accuracy', 0) > 0.8 and 
                  ml_perf.get('total_records', 0) > 50 and
                  self.ml_config.current_mode == MLMode.TRAINING):
                logger.info("✅ ML表现优异，建议考虑升级到平衡模式")
                # 不自动升级，需要手动确认
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"❌ 自动调整权重失败: {e}")
            return False
    
    def get_recommendation(self) -> str:
        """获取权重调整建议"""
        performance = self.get_performance_summary()
        current_mode = self.ml_config.current_mode
        
        ml_perf = performance.get('ml_accuracy', {}).get('recent_avg_accuracy', 0)
        traditional_perf = performance.get('traditional_accuracy', {}).get('recent_avg_accuracy', 0)
        
        if ml_perf < 0.5:
            return "建议禁用ML或保持训练模式，ML表现不佳"
        elif ml_perf > 0.8 and current_mode == MLMode.TRAINING:
            return "ML表现优异，可考虑升级到平衡模式"
        elif ml_perf > traditional_perf + 0.1 and current_mode == MLMode.BALANCED:
            return "ML表现超越传统分析，可考虑升级到增强模式"
        elif ml_perf < traditional_perf - 0.1 and current_mode != MLMode.TRAINING:
            return "ML表现不如传统分析，建议降级到训练模式"
        else:
            return f"当前{current_mode.value}模式表现良好，建议保持"


# 全局实例
trading_weight_manager = TradingWeightManager()


def get_trading_weight_manager() -> TradingWeightManager:
    """获取交易权重管理器实例"""
    return trading_weight_manager