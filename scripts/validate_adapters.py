#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
适配器验证脚本
Adapter validation script

用于验证数据适配器系统的正确性和性能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.logging import get_logger
from app.services.exchanges.adapters.adapter_diagnostics import (
    run_adapter_diagnostics, 
    quick_check_all_adapters,
    print_diagnostic_report
)
from app.services.exchanges.adapters.adapter_factory import AdapterFactory

logger = get_logger(__name__)


async def main():
    """主函数"""
    print("🔍 开始适配器系统验证...")
    logger.info("🚀 启动适配器验证脚本")
    
    try:
        # 1. 快速健康检查
        print("\n1. 快速健康检查...")
        quick_results = await quick_check_all_adapters()
        
        print("快速检查结果:")
        for exchange, is_healthy in quick_results.items():
            status_icon = "✅" if is_healthy else "❌"
            print(f"  {status_icon} {exchange}: {'健康' if is_healthy else '异常'}")
        
        # 2. 综合诊断
        print("\n2. 运行综合诊断...")
        diagnostics_result = await run_adapter_diagnostics()
        
        # 3. 生成并显示报告
        print("\n3. 诊断报告:")
        print_diagnostic_report(diagnostics_result)
        
        # 4. 测试适配器工厂功能
        print("\n4. 测试适配器工厂功能...")
        test_factory_functionality()
        
        # 5. 性能基准测试
        print("\n5. 性能基准测试...")
        await run_performance_benchmark()
        
        print("\n✅ 适配器系统验证完成!")
        
        # 返回退出码
        overall_status = diagnostics_result.get("overall_status", "unknown")
        if overall_status == "all_healthy":
            return 0
        elif overall_status == "partially_healthy":
            return 1
        else:
            return 2
            
    except Exception as e:
        logger.error(f"❌ 验证过程中发生错误: {e}")
        print(f"❌ 验证失败: {e}")
        return 3


def test_factory_functionality():
    """测试适配器工厂功能"""
    try:
        # 测试支持的交易所列表
        supported_exchanges = AdapterFactory.get_supported_exchanges()
        print(f"  支持的交易所: {supported_exchanges}")
        
        # 测试缓存信息
        cache_info = AdapterFactory.get_cache_info()
        print(f"  缓存信息: {cache_info}")
        
        # 测试每个支持的交易所
        for exchange in supported_exchanges:
            try:
                # 测试适配器获取
                adapter = AdapterFactory.get_adapter(exchange)
                adapter_info = adapter.get_adapter_info()
                print(f"  ✅ {exchange} 适配器正常: {adapter_info['adapter_class']}")
                
                # 测试错误处理
                error_info = AdapterFactory.handle_adapter_error(
                    ValueError("测试错误"), exchange, "test_operation"
                )
                print(f"  ✅ {exchange} 错误处理正常")
                
            except Exception as e:
                print(f"  ❌ {exchange} 适配器测试失败: {e}")
        
        print("  ✅ 适配器工厂功能测试完成")
        
    except Exception as e:
        print(f"  ❌ 适配器工厂功能测试失败: {e}")


async def run_performance_benchmark():
    """运行性能基准测试"""
    try:
        import time
        
        supported_exchanges = AdapterFactory.get_supported_exchanges()
        
        # 测试适配器创建性能
        print("  测试适配器创建性能...")
        for exchange in supported_exchanges:
            # 清空缓存
            AdapterFactory.clear_cache()
            
            # 测试首次创建时间
            start_time = time.time()
            adapter1 = AdapterFactory.get_adapter(exchange, use_cache=True)
            first_creation_time = time.time() - start_time
            
            # 测试缓存命中时间
            start_time = time.time()
            adapter2 = AdapterFactory.get_adapter(exchange, use_cache=True)
            cache_hit_time = time.time() - start_time
            
            # 验证缓存是否生效
            cache_effective = adapter1 is adapter2
            
            print(f"    {exchange}:")
            print(f"      首次创建: {first_creation_time:.4f}秒")
            print(f"      缓存命中: {cache_hit_time:.4f}秒")
            print(f"      缓存生效: {'是' if cache_effective else '否'}")
            print(f"      性能提升: {(first_creation_time - cache_hit_time) / first_creation_time * 100:.1f}%")
        
        print("  ✅ 性能基准测试完成")
        
    except Exception as e:
        print(f"  ❌ 性能基准测试失败: {e}")


def print_usage():
    """打印使用说明"""
    print("""
适配器验证脚本使用说明:

python scripts/validate_adapters.py

该脚本将执行以下验证:
1. 快速健康检查 - 检查所有适配器的基本状态
2. 综合诊断 - 详细测试适配器功能
3. 诊断报告 - 生成详细的诊断报告
4. 工厂功能测试 - 测试适配器工厂的各项功能
5. 性能基准测试 - 测试适配器的性能表现

退出码:
0 - 所有适配器健康
1 - 部分适配器健康
2 - 所有适配器异常
3 - 验证过程出错
""")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print_usage()
        sys.exit(0)
    
    # 运行验证
    exit_code = asyncio.run(main())
    sys.exit(exit_code)