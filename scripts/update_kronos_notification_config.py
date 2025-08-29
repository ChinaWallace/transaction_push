#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos持仓分析通知配置管理脚本
用于动态调整通知冷却时间和其他配置
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.kronos_position_analysis_service import KronosPositionAnalysisService
from app.core.logging import get_logger

logger = get_logger(__name__)

async def main():
    """主函数"""
    print("🔧 Kronos持仓分析通知配置管理")
    print("=" * 50)
    
    # 创建服务实例
    service = KronosPositionAnalysisService()
    
    # 显示当前配置
    current_config = service.get_notification_config()
    print("\n📋 当前配置:")
    for key, value in current_config.items():
        print(f"  {key}: {value}")
    
    print("\n🛠️ 可用操作:")
    print("1. 设置普通通知冷却时间（分钟）")
    print("2. 设置紧急通知冷却时间（分钟）")
    print("3. 设置高风险通知冷却时间（分钟）")
    print("4. 设置最小持仓价值阈值（USDT）")
    print("5. 启用/禁用通知")
    print("6. 查看当前配置")
    print("7. 重置为默认配置")
    print("0. 退出")
    
    while True:
        try:
            choice = input("\n请选择操作 (0-7): ").strip()
            
            if choice == "0":
                print("👋 退出配置管理")
                break
            elif choice == "1":
                minutes = int(input("请输入普通通知冷却时间（分钟，建议30-60）: "))
                service.update_notification_config(notification_cooldown_minutes=minutes)
            elif choice == "2":
                minutes = int(input("请输入紧急通知冷却时间（分钟，建议5-15）: "))
                service.update_notification_config(urgent_notification_cooldown_minutes=minutes)
            elif choice == "3":
                minutes = int(input("请输入高风险通知冷却时间（分钟，建议10-30）: "))
                service.update_notification_config(high_risk_notification_cooldown_minutes=minutes)
            elif choice == "4":
                value = float(input("请输入最小持仓价值阈值（USDT，建议50-200）: "))
                service.update_notification_config(min_position_value=value)
            elif choice == "5":
                enable = input("启用通知？(y/n): ").lower().startswith('y')
                service.update_notification_config(enable_notifications=enable)
            elif choice == "6":
                config = service.get_notification_config()
                print("\n📋 当前配置:")
                for key, value in config.items():
                    print(f"  {key}: {value}")
            elif choice == "7":
                service.update_notification_config(
                    notification_cooldown_minutes=30,
                    urgent_notification_cooldown_minutes=10,
                    high_risk_notification_cooldown_minutes=15,
                    min_position_value=100,
                    enable_notifications=True
                )
                print("✅ 已重置为默认配置")
            else:
                print("❌ 无效选择，请重试")
                
        except ValueError as e:
            print(f"❌ 输入错误: {e}")
        except KeyboardInterrupt:
            print("\n👋 退出配置管理")
            break
        except Exception as e:
            print(f"❌ 操作失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())