# -*- coding: utf-8 -*-
"""
系统状态检查脚本
System Status Check Script
"""

import sys
import os
import subprocess
import requests
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_python_environment():
    """检查Python环境"""
    print("🐍 Python环境检查")
    print("-" * 30)
    
    # Python版本
    python_version = sys.version
    print(f"Python版本: {python_version.split()[0]}")
    
    # 虚拟环境
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✅ 虚拟环境: 已激活")
    else:
        print("⚠️ 虚拟环境: 未激活")
    
    # 关键依赖检查
    dependencies = [
        'fastapi', 'uvicorn', 'requests', 'pandas', 'numpy', 
        'aiohttp', 'pydantic', 'python-dotenv'
    ]
    
    missing_deps = []
    for dep in dependencies:
        try:
            __import__(dep.replace('-', '_'))
            print(f"✅ {dep}: 已安装")
        except ImportError:
            print(f"❌ {dep}: 未安装")
            missing_deps.append(dep)
    
    # Windows服务依赖
    try:
        print("✅ pywin32: 已安装 (Windows服务支持)")
    except ImportError:
        print("⚠️ pywin32: 未安装 (无Windows服务支持)")
    
    return len(missing_deps) == 0


def check_configuration():
    """检查配置文件"""
    print("\n⚙️ 配置文件检查")
    print("-" * 30)
    
    # .env文件
    env_file = project_root / ".env"
    if env_file.exists():
        print("✅ .env文件: 存在")
        
        # 检查关键配置
        try:
            from app.core.config import get_settings
            settings = get_settings()
            print(f"✅ 配置加载: 成功")
            
            # 检查API配置
            if hasattr(settings, 'binance_api_key') and settings.binance_api_key:
                print("✅ Binance API: 已配置")
            else:
                print("⚠️ Binance API: 未配置")
                
        except Exception as e:
            print(f"❌ 配置加载: 失败 - {e}")
            return False
    else:
        print("❌ .env文件: 不存在")
        print("💡 请复制 env.example 为 .env 并填入配置")
        return False
    
    return True


def check_services():
    """检查服务状态"""
    print("\n🔧 服务状态检查")
    print("-" * 30)
    
    # 检查守护进程
    pid_file = project_root / "logs" / "daemon.pid"
    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # 检查进程是否存在
            try:
                os.kill(pid, 0)
                print(f"✅ 守护进程: 运行中 (PID: {pid})")
            except OSError:
                print("❌ 守护进程: PID文件存在但进程已停止")
                pid_file.unlink()  # 清理无效PID文件
        except Exception as e:
            print(f"❌ 守护进程: 检查失败 - {e}")
    else:
        print("❌ 守护进程: 未运行")
    
    # 检查Windows服务
    try:
        result = subprocess.run(['sc', 'query', 'TradingToolService'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            if 'RUNNING' in result.stdout:
                print("✅ Windows服务: 运行中")
            else:
                print("❌ Windows服务: 已安装但未运行")
        else:
            print("❌ Windows服务: 未安装")
    except Exception as e:
        print(f"❌ Windows服务: 检查失败 - {e}")


def check_network():
    """检查网络连接"""
    print("\n🌐 网络连接检查")
    print("-" * 30)
    
    # 测试API连接
    test_urls = [
        ("Binance API", "https://fapi.binance.com/fapi/v1/time"),
        ("百度", "https://www.baidu.com"),
    ]
    
    for name, url in test_urls:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=10)
            end_time = time.time()
            
            if response.status_code == 200:
                latency = (end_time - start_time) * 1000
                print(f"✅ {name}: 连接正常 ({latency:.0f}ms)")
            else:
                print(f"⚠️ {name}: HTTP {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"❌ {name}: 连接超时")
        except requests.exceptions.ConnectionError:
            print(f"❌ {name}: 连接失败")
        except Exception as e:
            print(f"❌ {name}: 错误 - {e}")


def check_logs():
    """检查日志文件"""
    print("\n📝 日志文件检查")
    print("-" * 30)
    
    log_dir = project_root / "logs"
    if not log_dir.exists():
        print("❌ 日志目录: 不存在")
        return
    
    log_files = [
        "app.log", "trading.log", "error.log", 
        "service.log", "daemon.log"
    ]
    
    for log_file in log_files:
        log_path = log_dir / log_file
        if log_path.exists():
            stat = log_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            mod_time = datetime.fromtimestamp(stat.st_mtime)
            
            print(f"✅ {log_file}: {size_mb:.1f}MB, 更新于 {mod_time.strftime('%H:%M:%S')}")
            
            # 检查是否有最近的日志
            if (datetime.now() - mod_time).total_seconds() < 3600:  # 1小时内
                print(f"   📊 最近有活动")
            else:
                print(f"   ⚠️ 超过1小时无更新")
        else:
            print(f"❌ {log_file}: 不存在")


def check_disk_space():
    """检查磁盘空间"""
    print("\n💾 磁盘空间检查")
    print("-" * 30)
    
    try:
        import shutil
        total, used, free = shutil.disk_usage(str(project_root))
        
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        usage_percent = (used / total) * 100
        
        print(f"总空间: {total_gb:.1f}GB")
        print(f"已使用: {used_gb:.1f}GB ({usage_percent:.1f}%)")
        print(f"可用空间: {free_gb:.1f}GB")
        
        if free_gb < 1:
            print("⚠️ 磁盘空间不足 (<1GB)")
        elif free_gb < 5:
            print("⚠️ 磁盘空间较少 (<5GB)")
        else:
            print("✅ 磁盘空间充足")
            
    except Exception as e:
        print(f"❌ 磁盘空间检查失败: {e}")


def check_processes():
    """检查相关进程"""
    print("\n🔍 进程检查")
    print("-" * 30)
    
    try:
        # 查找Python进程
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            python_processes = [line for line in lines if 'python.exe' in line.lower()]
            
            if python_processes:
                print(f"✅ 发现 {len(python_processes)} 个Python进程")
                for proc in python_processes[:3]:  # 只显示前3个
                    parts = proc.split()
                    if len(parts) >= 2:
                        print(f"   PID: {parts[1]}")
            else:
                print("❌ 未发现Python进程")
        else:
            print("❌ 进程检查失败")
            
    except Exception as e:
        print(f"❌ 进程检查失败: {e}")


def main():
    """主检查函数"""
    print("🔍 交易工具系统状态检查")
    print("=" * 50)
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"项目目录: {project_root}")
    
    # 执行所有检查
    checks = [
        check_python_environment,
        check_configuration,
        check_services,
        check_network,
        check_logs,
        check_disk_space,
        check_processes
    ]
    
    for check_func in checks:
        try:
            check_func()
        except Exception as e:
            print(f"❌ 检查失败: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 检查完成!")
    print("\n💡 如果发现问题:")
    print("   1. 重新安装依赖: python install_dependencies.py")
    print("   2. 检查配置文件: 编辑 .env")
    print("   3. 重启服务: python scripts\\daemon_runner.py restart")
    print("   4. 查看日志: type logs\\app.log")


if __name__ == '__main__':
    main()
    input("\n按回车键退出...")
