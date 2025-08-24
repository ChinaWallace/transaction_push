#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行测试脚本
Test runner script
"""

import subprocess
import sys
import os

def run_tests():
    """运行所有测试"""
    print("🧪 开始运行测试...")
    print("=" * 50)
    
    # 检查是否安装了pytest
    try:
        import pytest
        print("✅ 使用pytest运行测试")
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"], 
                              capture_output=False)
        return result.returncode == 0
    except ImportError:
        print("⚠️ 未安装pytest，使用直接运行方式")
        
        # 直接运行测试文件
        test_files = [
            "tests/test_config.py",
            "tests/test_services.py"
        ]
        
        all_passed = True
        for test_file in test_files:
            if os.path.exists(test_file):
                print(f"\n📋 运行 {test_file}...")
                result = subprocess.run([sys.executable, test_file], 
                                      capture_output=False)
                if result.returncode != 0:
                    all_passed = False
            else:
                print(f"⚠️ 测试文件不存在: {test_file}")
        
        return all_passed

def main():
    """主函数"""
    success = run_tests()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 所有测试通过！")
    else:
        print("❌ 部分测试失败，请检查错误信息")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())