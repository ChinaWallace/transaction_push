#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
适配器性能测试脚本
Adapter performance testing script
"""

import asyncio
import time
import json
import sys
import os
from typing import Dict, Any, List
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.services.exchanges.adapters.binance_adapter import BinanceDataAdapter
from app.services.exchanges.adapters.performance_monitor import performance_monitor
from app.services.exchanges.adapters.cache_manager import adapter_cache_manager
from app.services.exchanges.adapters.cache_monitor import cache_monitor

logger = get_logger(__name__)


class AdapterPerformanceTester:
    """适配器性能测试器"""
    
    def __init__(self):
        self.adapter = BinanceDataAdapter()
        self.test_results = {}
        
    def generate_test_data(self, count: int = 1000) -> List[Dict[str, Any]]:
        """生成测试数据"""
        test_data = []
        
        for i in range(count):
            # 模拟币安交易对数据
            symbol = f"TEST{i}USDT"
            base_asset = f"TEST{i}"
            
            test_data.append({
                "symbol": symbol,
                "status": "TRADING",
                "baseAsset": base_asset,
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"}
                ],
                "onboardDate": str(int(time.time() * 1000))
            })
        
        return test_data
    
    def generate_ticker_data(self, count: int = 100) -> List[Dict[str, Any]]:
        """生成ticker测试数据"""
        test_data = []
        
        for i in range(count):
            symbol = f"TEST{i}USDT"
            
            test_data.append({
                "symbol": symbol,
                "lastPrice": f"{50000 + i}.00",
                "bidPrice": f"{49999 + i}.00",
                "askPrice": f"{50001 + i}.00",
                "bidQty": "1.5",
                "askQty": "2.0",
                "openPrice": f"{49500 + i}.00",
                "highPrice": f"{50500 + i}.00",
                "lowPrice": f"{49000 + i}.00",
                "volume": "1000.00",
                "quoteVolume": "50000000.00",
                "closeTime": int(time.time() * 1000)
            })
        
        return test_data
    
    async def test_instruments_performance(self, data_sizes: List[int]):
        """测试交易对适配性能"""
        logger.info("🚀 开始测试交易对适配性能")
        
        results = {}
        
        for size in data_sizes:
            logger.info(f"📊 测试数据量: {size}")
            
            # 生成测试数据
            test_data = self.generate_test_data(size)
            
            # 测试串行处理
            start_time = time.time()
            serial_result = self.adapter.adapt_instruments(test_data)
            serial_duration = time.time() - start_time
            
            # 测试批量处理
            start_time = time.time()
            batch_result = await self.adapter.adapt_instruments_batch(test_data)
            batch_duration = time.time() - start_time
            
            # 计算性能指标
            serial_throughput = len(serial_result) / serial_duration if serial_duration > 0 else 0
            batch_throughput = len(batch_result) / batch_duration if batch_duration > 0 else 0
            
            improvement = ((serial_duration - batch_duration) / serial_duration * 100) if serial_duration > 0 else 0
            
            results[size] = {
                "serial": {
                    "duration": serial_duration,
                    "throughput": serial_throughput,
                    "result_count": len(serial_result)
                },
                "batch": {
                    "duration": batch_duration,
                    "throughput": batch_throughput,
                    "result_count": len(batch_result)
                },
                "improvement_percent": improvement
            }
            
            logger.info(
                f"✅ 数据量 {size}: 串行 {serial_duration:.3f}s ({serial_throughput:.1f} items/s), "
                f"批量 {batch_duration:.3f}s ({batch_throughput:.1f} items/s), "
                f"提升 {improvement:.1f}%"
            )
        
        self.test_results["instruments"] = results
        return results
    
    async def test_cache_performance(self, data_sizes: List[int]):
        """测试缓存性能"""
        logger.info("🚀 开始测试缓存性能")
        
        results = {}
        
        for size in data_sizes:
            logger.info(f"📊 测试缓存数据量: {size}")
            
            # 生成测试数据
            test_data = self.generate_test_data(size)
            
            # 清空缓存
            adapter_cache_manager.clear()
            
            # 第一次调用（缓存未命中）
            start_time = time.time()
            first_result = self.adapter.adapt_instruments(test_data)
            first_duration = time.time() - start_time
            
            # 第二次调用（缓存命中）
            start_time = time.time()
            second_result = self.adapter.adapt_instruments(test_data)
            second_duration = time.time() - start_time
            
            # 计算缓存效果
            cache_speedup = (first_duration / second_duration) if second_duration > 0 else 0
            cache_improvement = ((first_duration - second_duration) / first_duration * 100) if first_duration > 0 else 0
            
            results[size] = {
                "first_call": {
                    "duration": first_duration,
                    "result_count": len(first_result)
                },
                "cached_call": {
                    "duration": second_duration,
                    "result_count": len(second_result)
                },
                "cache_speedup": cache_speedup,
                "cache_improvement_percent": cache_improvement
            }
            
            logger.info(
                f"✅ 缓存测试 {size}: 首次 {first_duration:.3f}s, "
                f"缓存 {second_duration:.3f}s, "
                f"加速 {cache_speedup:.1f}x, 提升 {cache_improvement:.1f}%"
            )
        
        self.test_results["cache"] = results
        return results
    
    async def test_memory_usage(self):
        """测试内存使用情况"""
        logger.info("🚀 开始测试内存使用情况")
        
        import psutil
        import gc
        
        process = psutil.Process()
        
        # 记录初始内存
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # 生成大量测试数据
        large_test_data = self.generate_test_data(5000)
        
        # 执行适配
        start_memory = process.memory_info().rss / 1024 / 1024
        result = await self.adapter.adapt_instruments_batch(large_test_data)
        end_memory = process.memory_info().rss / 1024 / 1024
        
        # 获取缓存统计
        cache_stats = adapter_cache_manager.get_stats()
        
        # 强制垃圾回收
        gc.collect()
        after_gc_memory = process.memory_info().rss / 1024 / 1024
        
        memory_results = {
            "initial_memory_mb": initial_memory,
            "start_memory_mb": start_memory,
            "end_memory_mb": end_memory,
            "after_gc_memory_mb": after_gc_memory,
            "memory_increase_mb": end_memory - start_memory,
            "cache_memory_mb": cache_stats.get("current_state", {}).get("memory_usage_mb", 0),
            "result_count": len(result)
        }
        
        self.test_results["memory"] = memory_results
        
        logger.info(
            f"✅ 内存测试: 初始 {initial_memory:.1f}MB, "
            f"处理后 {end_memory:.1f}MB, "
            f"增加 {memory_results['memory_increase_mb']:.1f}MB, "
            f"缓存 {memory_results['cache_memory_mb']:.1f}MB"
        )
        
        return memory_results
    
    async def run_comprehensive_test(self):
        """运行综合性能测试"""
        logger.info("🎯 开始综合性能测试")
        
        # 启动缓存监控
        await cache_monitor.start_monitoring()
        
        try:
            # 测试不同数据量
            data_sizes = [10, 50, 100, 500, 1000, 2000]
            
            # 测试交易对适配性能
            await self.test_instruments_performance(data_sizes)
            
            # 测试缓存性能
            await self.test_cache_performance([100, 500, 1000])
            
            # 测试内存使用
            await self.test_memory_usage()
            
            # 获取性能统计
            perf_stats = performance_monitor.get_performance_stats()
            self.test_results["performance_stats"] = perf_stats
            
            # 获取缓存统计
            cache_stats = adapter_cache_manager.get_stats()
            self.test_results["cache_stats"] = cache_stats
            
            # 获取缓存健康报告
            health_report = cache_monitor.get_health_report(1)  # 最近1小时
            self.test_results["cache_health"] = health_report
            
        finally:
            # 停止缓存监控
            await cache_monitor.stop_monitoring()
        
        return self.test_results
    
    def save_results(self, filename: str = None):
        """保存测试结果"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"adapter_performance_test_{timestamp}.json"
        
        filepath = os.path.join("logs", filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.test_results, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"📄 测试结果已保存到: {filepath}")
        return filepath
    
    def print_summary(self):
        """打印测试摘要"""
        logger.info("📊 性能测试摘要")
        logger.info("=" * 60)
        
        # 交易对适配性能摘要
        if "instruments" in self.test_results:
            logger.info("🔧 交易对适配性能:")
            for size, result in self.test_results["instruments"].items():
                improvement = result["improvement_percent"]
                logger.info(
                    f"  数据量 {size}: 批量处理提升 {improvement:.1f}% "
                    f"({result['batch']['throughput']:.1f} items/s)"
                )
        
        # 缓存性能摘要
        if "cache" in self.test_results:
            logger.info("💾 缓存性能:")
            for size, result in self.test_results["cache"].items():
                speedup = result["cache_speedup"]
                logger.info(f"  数据量 {size}: 缓存加速 {speedup:.1f}x")
        
        # 内存使用摘要
        if "memory" in self.test_results:
            memory = self.test_results["memory"]
            logger.info(
                f"🧠 内存使用: 增加 {memory['memory_increase_mb']:.1f}MB, "
                f"缓存占用 {memory['cache_memory_mb']:.1f}MB"
            )
        
        # 整体性能统计
        if "performance_stats" in self.test_results:
            perf = self.test_results["performance_stats"]
            if "operations" in perf:
                logger.info("⚡ 整体性能统计:")
                for op_name, op_stats in perf["operations"].items():
                    if "duration_stats" in op_stats:
                        avg_duration = op_stats["duration_stats"]["avg"]
                        total_calls = op_stats["total_calls"]
                        logger.info(f"  {op_name}: 平均 {avg_duration:.3f}s, 调用 {total_calls} 次")
        
        logger.info("=" * 60)


async def main():
    """主函数"""
    logger.info("🚀 启动适配器性能测试")
    
    tester = AdapterPerformanceTester()
    
    try:
        # 运行综合测试
        await tester.run_comprehensive_test()
        
        # 打印摘要
        tester.print_summary()
        
        # 保存结果
        result_file = tester.save_results()
        
        logger.info("✅ 性能测试完成")
        return result_file
        
    except Exception as e:
        logger.error(f"❌ 性能测试失败: {e}")
        raise
    finally:
        # 清理资源
        await adapter_cache_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())