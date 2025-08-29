#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ML模式设置脚本
Quick ML Mode Setting Script
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.ml_weight_config import get_ml_weight_config, MLMode, set_ml_mode
from app.core.logging import get_logger

logger = get_logger(__name__)


async def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("使用方法: python set_ml_mode.py <mode>")
        print("可用模式:")
        print("  disabled  - 禁用ML")
        print("  training  - 训练模式 (推荐)")
        print("  balanced  - 平衡模式")
        print("  enhanced  - 增强模式")
        return
    
    mode_str = sys.argv[1].lower()
    
    mode_map = {
        "disabled": MLMode.DISABLED,
        "training": MLMode.TRAINING,
        "balanced": MLMode.BALANCED,
        "enhanced": MLMode.ENHANCED
    }
    
    if mode_str not in mode_map:
        print(f"❌ 无效模式: {mode_str}")
        print(f"可用模式: {list(mode_map.keys())}")
        return
    
    try:
        # 设置新模式
        new_mode = mode_map[mode_str]
        set_ml_mode(new_mode)
        
        # 获取配置信息
        ml_config = get_ml_weight_config()
        weights = ml_config.get_weights()
        
        print(f"✅ ML模式已设置为: {new_mode.value}")
        print(f"📊 当前权重配置:")
        for key, value in weights.items():
            print(f"  {key}: {value:.1%}")
        print(f"🎯 影响程度: {ml_config.get_ml_influence_level()}")
        
        # 根据模式给出建议
        if new_mode == MLMode.TRAINING:
            print("\n💡 训练模式建议:")
            print("  - ML权重很低，主要跟随传统信号学习")
            print("  - 适合当前ML表现不稳定的情况")
            print("  - 建议观察ML表现后再考虑升级")
        elif new_mode == MLMode.DISABLED:
            print("\n💡 禁用模式建议:")
            print("  - 完全禁用ML影响")
            print("  - 仅使用传统技术分析")
            print("  - 适合ML表现很差的情况")
        elif new_mode == MLMode.ENHANCED:
            print("\n⚠️ 增强模式警告:")
            print("  - ML权重很高，需要密切监控表现")
            print("  - 确保ML模型表现稳定可靠")
            print("  - 建议定期检查交易结果")
        
    except Exception as e:
        print(f"❌ 设置失败: {e}")
        logger.error(f"设置ML模式失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())