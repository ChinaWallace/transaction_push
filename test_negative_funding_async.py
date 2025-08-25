#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试负费率监控服务的异步性能
Test async performance of negative funding monitor service
"""

import asyncio
import time
import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.negative_funding_monitor_service import NegativeFundingMonitorService


async def test_async_performance():
    """测试异步性能"""
    print("🚀 开始测试负费率监控服务的异步性能...")
    
    monitor = NegativeFundingMonitorService()
    
    start_time = time.time()
    
    try:
        # 测试异步方法
        print("\n1️⃣ 测试获取热门币种...")
        symbols = await monitor.get_top_volume_symbols(limit=20)
        print(f"   ✅ 获取到 {len(symbols)} 个币种")
        
        print("\n2️⃣ 测试批量获取费率数据...")
        test_symbols = symbols[:10]  # 只测试前10个
        funding_rates = await monitor.get_batch_funding_rates(test_symbols, batch_size=5)
        print(f"   ✅ 获取到 {len(funding_rates)} 个费率数据")
        
        print("\n3️⃣ 测试获取基础信息...")
        if funding_rates:
            symbol = funding_rates[0]['symbol']
            basic_info = await monitor.get_symbol_basic_info(symbol)
            print(f"   ✅ 获取到 {symbol} 的基础信息: 价格 ${basic_info.get('price', 0):.4f}")
        
        print("\n4️⃣ 测试完整监控周期...")
        result = await monitor.run_monitoring_cycle()
        
        if result['success']:
            print(f"   ✅ 监控周期完成")
            print(f"   📊 检查币种: {result.get('total_symbols_checked', 0)}")
            print(f"   💰 发现机会: {result.get('opportunities_found', 0)}")
            print(f"   ⏱️ 执行时间: {result.get('execution_time_seconds', 0):.2f}秒")
        else:
            print(f"   ❌ 监控周期失败: {result.get('error', 'unknown')}")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\n🏁 测试完成，总耗时: {total_time:.2f}秒")
    
    # 验证异步性能
    if total_time < 60:  # 如果在60秒内完成，说明异步性能良好
        print("✅ 异步性能良好 - 所有操作在合理时间内完成")
    else:
        print("⚠️ 异步性能需要优化 - 执行时间较长")


async def test_concurrent_operations():
    """测试并发操作"""
    print("\n🔄 测试并发操作性能...")
    
    monitor = NegativeFundingMonitorService()
    
    # 并发执行多个操作
    tasks = []
    
    # 创建多个并发任务
    for i in range(3):
        task = monitor.get_top_volume_symbols(limit=10)
        tasks.append(task)
    
    start_time = time.time()
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        concurrent_time = end_time - start_time
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        
        print(f"   ✅ 并发任务完成: {success_count}/{len(tasks)} 成功")
        print(f"   ⏱️ 并发执行时间: {concurrent_time:.2f}秒")
        
        if concurrent_time < 10:
            print("   🚀 并发性能优秀")
        else:
            print("   ⚠️ 并发性能需要优化")
            
    except Exception as e:
        print(f"   ❌ 并发测试失败: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("负费率监控服务异步性能测试")
    print("=" * 60)
    
    # 运行异步测试
    asyncio.run(test_async_performance())
    
    # 运行并发测试
    asyncio.run(test_concurrent_operations())
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)