#!/usr/bin/env python3
"""
依赖安装脚本 - Dependency Installation Script
解决Windows下TA-Lib安装问题
"""

import subprocess
import sys
import platform
import os

def run_command(command, description):
    """运行命令并处理错误"""
    print(f"\n正在执行: {description}")
    print(f"命令: {command}")
    
    try:
        result = subprocess.run(command, shell=True, check=True, 
                              capture_output=True, text=True)
        print(f"✅ 成功: {description}")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 失败: {description}")
        print(f"错误: {e.stderr}")
        return False

def install_talib():
    """安装TA-Lib"""
    system = platform.system().lower()
    
    if system == "windows":
        print("检测到Windows系统，尝试安装预编译的TA-Lib...")
        
        # 尝试从GitHub releases安装
        commands = [
            "pip install --find-links https://github.com/cgohlke/talib-build/releases/download/v0.4.28/ TA-Lib",
            "pip install TA-Lib",  # 备用方案
        ]
        
        for cmd in commands:
            if run_command(cmd, "安装TA-Lib"):
                return True
        
        print("\n❌ TA-Lib安装失败，请手动安装:")
        print("1. 访问 https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib")
        print("2. 下载对应Python版本的.whl文件")
        print("3. 使用 pip install 下载的.whl文件名 安装")
        return False
    
    else:
        # Linux/Mac
        return run_command("pip install TA-Lib", "安装TA-Lib")

def main():
    """主安装流程"""
    print("🚀 开始安装交易系统依赖...")
    
    # 1. 升级pip
    run_command("python -m pip install --upgrade pip", "升级pip")
    
    # 2. 安装TA-Lib
    if not install_talib():
        print("\n⚠️  TA-Lib安装失败，但继续安装其他依赖...")
    
    # 3. 安装其他依赖
    if run_command("pip install -r requirements.txt", "安装其他依赖"):
        print("\n✅ 基础依赖安装完成!")
    else:
        print("\n❌ 依赖安装失败，请检查requirements.txt")
        return False
    
    # 4. 安装Windows服务依赖 (如果是Windows系统)
    if platform.system().lower() == "windows":
        print("\n🪟 检测到Windows系统，安装服务支持...")
        if run_command("pip install pywin32", "安装Windows服务支持"):
            print("✅ Windows服务支持安装成功!")
        else:
            print("⚠️  Windows服务支持安装失败，但不影响基本功能")
    
    # 5. 下载Kronos模型
    if os.path.exists("scripts/download_kronos_models.py"):
        if run_command("python scripts/download_kronos_models.py", "下载Kronos模型"):
            print("\n✅ Kronos模型下载完成!")
        else:
            print("\n⚠️  Kronos模型下载失败，请稍后手动运行: python scripts/download_kronos_models.py")
    else:
        print("\n⚠️  未找到Kronos模型下载脚本")
    
    print("\n🎉 安装完成!")
    print("\n🚀 接下来你可以:")
    print("   1. 直接运行: python main.py")
    print("   2. 后台运行: 双击 start_service.bat")
    print("   3. 安装服务: 以管理员身份运行 scripts\\install_service.bat")
    print("\n💡 推荐使用 start_service.bat 来选择运行方式")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)