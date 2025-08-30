# -*- coding: utf-8 -*-
"""
开机启动脚本
Startup Script for Trading Tool - 开机自动启动解决方案
"""

import sys
import os
import winreg
import subprocess
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def add_to_startup():
    """添加到Windows开机启动项"""
    try:
        # 获取当前脚本路径
        script_path = Path(__file__).parent / "start_daemon.bat"
        
        if not script_path.exists():
            print(f"❌ 启动脚本不存在: {script_path}")
            return False
        
        # 打开注册表
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        
        # 添加启动项
        winreg.SetValueEx(
            key,
            "TradingToolDaemon",
            0,
            winreg.REG_SZ,
            str(script_path)
        )
        
        winreg.CloseKey(key)
        
        print("✅ 已添加到开机启动项")
        print(f"📂 启动脚本: {script_path}")
        print("💡 重启电脑后将自动启动交易工具")
        
        return True
        
    except Exception as e:
        print(f"❌ 添加开机启动项失败: {e}")
        return False


def remove_from_startup():
    """从Windows开机启动项中移除"""
    try:
        # 打开注册表
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        
        # 删除启动项
        try:
            winreg.DeleteValue(key, "TradingToolDaemon")
            print("✅ 已从开机启动项中移除")
        except FileNotFoundError:
            print("⚠️ 开机启动项不存在")
        
        winreg.CloseKey(key)
        return True
        
    except Exception as e:
        print(f"❌ 移除开机启动项失败: {e}")
        return False


def check_startup_status():
    """检查开机启动状态"""
    try:
        # 打开注册表
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ
        )
        
        try:
            value, _ = winreg.QueryValueEx(key, "TradingToolDaemon")
            print("📊 开机启动状态: ✅ 已启用")
            print(f"📂 启动脚本: {value}")
            
            # 检查脚本是否存在
            if Path(value).exists():
                print("✅ 启动脚本文件存在")
            else:
                print("❌ 启动脚本文件不存在")
                
            return True
            
        except FileNotFoundError:
            print("📊 开机启动状态: ❌ 未启用")
            return False
        
        winreg.CloseKey(key)
        
    except Exception as e:
        print(f"❌ 检查开机启动状态失败: {e}")
        return False


def create_desktop_shortcut():
    """创建桌面快捷方式"""
    try:
        import win32com.client
        
        # 获取桌面路径
        desktop = Path.home() / "Desktop"
        shortcut_path = desktop / "交易工具管理器.lnk"
        
        # 创建快捷方式
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(project_root / "scripts" / "service_manager.bat")
        shortcut.WorkingDirectory = str(project_root / "scripts")
        shortcut.IconLocation = str(project_root / "scripts" / "service_manager.bat")
        shortcut.Description = "交易工具服务管理器"
        shortcut.save()
        
        print(f"✅ 桌面快捷方式已创建: {shortcut_path}")
        return True
        
    except ImportError:
        print("⚠️ 需要安装pywin32才能创建快捷方式")
        print("运行: pip install pywin32")
        return False
    except Exception as e:
        print(f"❌ 创建桌面快捷方式失败: {e}")
        return False


def setup_task_scheduler():
    """使用任务计划程序设置开机启动"""
    try:
        # 构建任务计划程序命令
        task_name = "TradingToolAutoStart"
        script_path = project_root / "scripts" / "start_daemon.bat"
        
        # 创建任务的XML配置
        xml_config = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2024-01-01T00:00:00</Date>
    <Author>TradingTool</Author>
    <Description>交易工具自动启动任务</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{script_path}</Command>
      <WorkingDirectory>{script_path.parent}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
        
        # 保存XML配置到临时文件
        temp_xml = project_root / "temp_task.xml"
        with open(temp_xml, 'w', encoding='utf-16') as f:
            f.write(xml_config)
        
        # 使用schtasks命令创建任务
        cmd = [
            'schtasks', '/create',
            '/tn', task_name,
            '/xml', str(temp_xml),
            '/f'  # 强制覆盖已存在的任务
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 清理临时文件
        if temp_xml.exists():
            temp_xml.unlink()
        
        if result.returncode == 0:
            print("✅ 任务计划程序设置成功")
            print(f"📋 任务名称: {task_name}")
            print("💡 登录后30秒自动启动交易工具")
            return True
        else:
            print(f"❌ 任务计划程序设置失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 设置任务计划程序失败: {e}")
        return False


def remove_task_scheduler():
    """移除任务计划程序任务"""
    try:
        task_name = "TradingToolAutoStart"
        
        cmd = ['schtasks', '/delete', '/tn', task_name, '/f']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 任务计划程序任务已移除")
            return True
        else:
            print(f"❌ 移除任务失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 移除任务计划程序任务失败: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("🚀 交易工具开机启动配置")
        print("=" * 40)
        print("使用方法:")
        print("  python startup_script.py add_registry     # 添加到注册表启动项")
        print("  python startup_script.py remove_registry  # 从注册表启动项移除")
        print("  python startup_script.py add_task         # 添加到任务计划程序")
        print("  python startup_script.py remove_task      # 从任务计划程序移除")
        print("  python startup_script.py status           # 查看启动状态")
        print("  python startup_script.py shortcut         # 创建桌面快捷方式")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'add_registry':
        add_to_startup()
    elif command == 'remove_registry':
        remove_from_startup()
    elif command == 'add_task':
        setup_task_scheduler()
    elif command == 'remove_task':
        remove_task_scheduler()
    elif command == 'status':
        print("📊 开机启动状态检查")
        print("=" * 30)
        print("\n1. 注册表启动项:")
        check_startup_status()
        print("\n2. 任务计划程序:")
        # 检查任务是否存在
        result = subprocess.run(['schtasks', '/query', '/tn', 'TradingToolAutoStart'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("📊 任务计划程序: ✅ 已配置")
        else:
            print("📊 任务计划程序: ❌ 未配置")
    elif command == 'shortcut':
        create_desktop_shortcut()
    else:
        print(f"❌ 未知命令: {command}")
        sys.exit(1)