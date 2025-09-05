# -*- coding: utf-8 -*-
"""
适配器监控测试脚本
Adapter monitoring test script

测试适配器监控服务的功能
"""

import asyncio
import sys
import json
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

from app.core.logging import get_logger
from app.services.monitoring.adapter_monitoring_service import (
    get_adapter_monitoring_service
)

logger = get_logger(__name__)


async def test_adapter_monitoring():
    """测试适配器监控功能"""
    logger.info("🧪 开始测试适配器监控功能")
    
    try:
        # 获取监控服务实例
        monitoring_service = get_adapter_monitoring_service()
        
        # 1. 测试获取整体状态
        logger.info("📊 测试获取整体状态...")
        overall_status = await monitoring_service.get_overall_status()
        print("整体状态:")
        print(json.dumps(overall_status, indent=2, ensure_ascii=False))
        print()
        
        # 2. 测试获取所有交易所状态
        logger.info("📊 测试获取所有交易所状态...")
        all_statuses = await monitoring_service.get_all_statuses()
        print("所有交易所状态:")
        print(json.dumps(all_statuses, indent=2, ensure_ascii=False))
        print()
        
        # 3. 测试获取特定交易所状态
        logger.info("📊 测试获取币安交易所状态...")
        binance_status = await monitoring_service.get_exchange_status("binance")
        print("币安交易所状态:")
        print(json.dumps(binance_status, indent=2, ensure_ascii=False))
        print()
        
        # 4. 测试性能统计
        logger.info("📊 测试获取性能统计...")
        performance_summary = await monitoring_service.get_performance_summary()
        print("性能统计:")
        print(json.dumps(performance_summary, indent=2, ensure_ascii=False))
        print()
        
        # 5. 测试错误统计
        logger.info("📊 测试获取错误统计...")
        error_summary = await monitoring_service.get_error_summary()
        print("错误统计:")
        print(json.dumps(error_summary, indent=2, ensure_ascii=False))
        print()
        
        # 6. 测试综合诊断
        logger.info("🔍 测试运行综合诊断...")
        diagnostics_result = await monitoring_service.run_comprehensive_diagnostics("binance")
        print("综合诊断结果:")
        print(json.dumps(diagnostics_result, indent=2, ensure_ascii=False))
        print()
        
        # 7. 测试监控配置
        logger.info("⚙️ 测试监控配置...")
        config = monitoring_service.get_monitoring_config()
        print("当前监控配置:")
        print(json.dumps(config, indent=2, ensure_ascii=False))
        print()
        
        # 8. 测试更新监控配置
        logger.info("⚙️ 测试更新监控配置...")
        new_config = {
            "check_interval": 180,  # 3分钟
            "error_threshold": 5
        }
        monitoring_service.update_monitoring_config(new_config)
        updated_config = monitoring_service.get_monitoring_config()
        print("更新后的监控配置:")
        print(json.dumps(updated_config, indent=2, ensure_ascii=False))
        print()
        
        logger.info("✅ 适配器监控功能测试完成")
        
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {e}")
        raise


async def test_monitoring_lifecycle():
    """测试监控服务生命周期"""
    logger.info("🔄 测试监控服务生命周期")
    
    try:
        monitoring_service = get_adapter_monitoring_service()
        
        # 启动监控
        logger.info("🚀 启动监控服务...")
        await monitoring_service.start_monitoring()
        
        # 等待一段时间让监控运行
        logger.info("⏳ 等待监控运行 30 秒...")
        await asyncio.sleep(30)
        
        # 检查监控状态
        overall_status = await monitoring_service.get_overall_status()
        print("监控运行状态:")
        print(json.dumps(overall_status, indent=2, ensure_ascii=False))
        
        # 停止监控
        logger.info("🛑 停止监控服务...")
        await monitoring_service.stop_monitoring()
        
        logger.info("✅ 监控服务生命周期测试完成")
        
    except Exception as e:
        logger.error(f"❌ 生命周期测试失败: {e}")
        raise


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="适配器监控测试脚本")
    parser.add_argument("--lifecycle", action="store_true", help="测试监控服务生命周期")
    parser.add_argument("--quick", action="store_true", help="快速测试模式")
    
    args = parser.parse_args()
    
    try:
        if args.lifecycle:
            await test_monitoring_lifecycle()
        elif args.quick:
            # 快速测试模式，只测试基本功能
            monitoring_service = get_adapter_monitoring_service()
            overall_status = await monitoring_service.get_overall_status()
            print("快速测试结果:")
            print(json.dumps(overall_status, indent=2, ensure_ascii=False))
        else:
            await test_adapter_monitoring()
    
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())