# -*- coding: utf-8 -*-
"""
Windows服务包装器
Windows Service Wrapper for Trading Tool
"""

import sys
import os
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    WINDOWS_SERVICE_AVAILABLE = True
except ImportError:
    WINDOWS_SERVICE_AVAILABLE = False
    print("警告: pywin32未安装，无法创建Windows服务")
    print("请运行: pip install pywin32")


class TradingToolWindowsService(win32serviceutil.ServiceFramework):
    """交易工具Windows服务类"""
    
    _svc_name_ = "TradingToolService"
    _svc_display_name_ = "Python Trading Analysis Tool Service"
    _svc_description_ = "智能交易分析工具后台服务，提供24/7市场监控和交易信号推送"
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.is_running = True
        self.main_process: Optional[subprocess.Popen] = None
        
        # 设置日志
        self.setup_logging()
        
    def setup_logging(self):
        """设置服务日志"""
        log_dir = project_root / "logs"
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "service.log", encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('TradingService')
        
    def SvcStop(self):
        """停止服务"""
        self.logger.info("🛑 正在停止交易工具服务...")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        
        self.is_running = False
        
        # 优雅关闭主进程
        if self.main_process and self.main_process.poll() is None:
            try:
                self.logger.info("📤 发送停止信号给主进程...")
                self.main_process.terminate()
                
                # 等待进程结束
                try:
                    self.main_process.wait(timeout=30)
                    self.logger.info("✅ 主进程已正常退出")
                except subprocess.TimeoutExpired:
                    self.logger.warning("⚠️ 主进程未在30秒内退出，强制终止...")
                    self.main_process.kill()
                    self.main_process.wait()
                    
            except Exception as e:
                self.logger.error(f"❌ 停止主进程时出错: {e}")
        
        win32event.SetEvent(self.hWaitStop)
        self.logger.info("✅ 交易工具服务已停止")
        
    def SvcDoRun(self):
        """运行服务"""
        self.logger.info("🚀 启动交易工具服务...")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        try:
            self.main_loop()
        except Exception as e:
            self.logger.error(f"❌ 服务运行异常: {e}")
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_ERROR_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, str(e))
            )
        
    def main_loop(self):
        """主循环"""
        restart_count = 0
        max_restarts = 10
        restart_delay = 60  # 重启延迟60秒
        
        while self.is_running:
            try:
                self.logger.info("🎯 启动交易分析主程序...")
                
                # 构建启动命令
                python_exe = sys.executable
                main_script = project_root / "main.py"
                
                # 设置环境变量
                env = os.environ.copy()
                env['PYTHONPATH'] = str(project_root)
                
                # 启动主程序
                self.main_process = subprocess.Popen(
                    [python_exe, str(main_script)],
                    cwd=str(project_root),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                
                self.logger.info(f"✅ 主程序已启动 (PID: {self.main_process.pid})")
                restart_count = 0  # 重置重启计数
                
                # 监控主程序
                while self.is_running:
                    # 检查服务停止事件
                    if win32event.WaitForSingleObject(self.hWaitStop, 1000) == win32event.WAIT_OBJECT_0:
                        break
                    
                    # 检查主程序状态
                    if self.main_process.poll() is not None:
                        # 主程序已退出
                        stdout, stderr = self.main_process.communicate()
                        exit_code = self.main_process.returncode
                        
                        self.logger.warning(f"⚠️ 主程序退出 (退出码: {exit_code})")
                        if stdout:
                            self.logger.info(f"标准输出: {stdout[-500:]}")  # 只记录最后500字符
                        if stderr:
                            self.logger.error(f"错误输出: {stderr[-500:]}")
                        
                        if not self.is_running:
                            break
                        
                        # 检查是否需要重启
                        restart_count += 1
                        if restart_count > max_restarts:
                            self.logger.error(f"❌ 主程序重启次数超过限制 ({max_restarts})，停止服务")
                            self.is_running = False
                            break
                        
                        self.logger.info(f"🔄 {restart_delay}秒后重启主程序 (第{restart_count}次)")
                        time.sleep(restart_delay)
                        break
                    
                    time.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"❌ 主循环异常: {e}")
                if self.is_running:
                    time.sleep(restart_delay)
                    restart_count += 1
                    if restart_count > max_restarts:
                        self.logger.error("❌ 异常重启次数过多，停止服务")
                        break


def install_service():
    """安装Windows服务"""
    if not WINDOWS_SERVICE_AVAILABLE:
        print("❌ 无法安装服务: pywin32未安装")
        print("请先运行: pip install pywin32")
        return False
    
    try:
        print("📦 正在安装交易工具Windows服务...")
        
        # 安装服务
        win32serviceutil.InstallService(
            TradingToolWindowsService._svc_reg_class_,
            TradingToolWindowsService._svc_name_,
            TradingToolWindowsService._svc_display_name_,
            description=TradingToolWindowsService._svc_description_,
            startType=win32service.SERVICE_AUTO_START  # 自动启动
        )
        
        print("✅ 服务安装成功!")
        print(f"   服务名称: {TradingToolWindowsService._svc_name_}")
        print(f"   显示名称: {TradingToolWindowsService._svc_display_name_}")
        print("   启动类型: 自动启动")
        print("\n🎯 使用方法:")
        print("   启动服务: net start TradingToolService")
        print("   停止服务: net stop TradingToolService")
        print("   或者在服务管理器中操作")
        
        return True
        
    except Exception as e:
        print(f"❌ 服务安装失败: {e}")
        return False


def uninstall_service():
    """卸载Windows服务"""
    if not WINDOWS_SERVICE_AVAILABLE:
        print("❌ 无法卸载服务: pywin32未安装")
        return False
    
    try:
        print("🗑️ 正在卸载交易工具Windows服务...")
        
        # 先停止服务
        try:
            win32serviceutil.StopService(TradingToolWindowsService._svc_name_)
            print("🛑 服务已停止")
        except:
            pass
        
        # 卸载服务
        win32serviceutil.RemoveService(TradingToolWindowsService._svc_name_)
        print("✅ 服务卸载成功!")
        
        return True
        
    except Exception as e:
        print(f"❌ 服务卸载失败: {e}")
        return False


def start_service():
    """启动服务"""
    if not WINDOWS_SERVICE_AVAILABLE:
        print("❌ 无法启动服务: pywin32未安装")
        return False
    
    try:
        print("🚀 正在启动交易工具服务...")
        win32serviceutil.StartService(TradingToolWindowsService._svc_name_)
        print("✅ 服务启动成功!")
        return True
    except Exception as e:
        print(f"❌ 服务启动失败: {e}")
        return False


def stop_service():
    """停止服务"""
    if not WINDOWS_SERVICE_AVAILABLE:
        print("❌ 无法停止服务: pywin32未安装")
        return False
    
    try:
        print("🛑 正在停止交易工具服务...")
        win32serviceutil.StopService(TradingToolWindowsService._svc_name_)
        print("✅ 服务停止成功!")
        return True
    except Exception as e:
        print(f"❌ 服务停止失败: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # 作为服务运行
        if WINDOWS_SERVICE_AVAILABLE:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(TradingToolWindowsService)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            print("❌ pywin32未安装，无法运行Windows服务")
            sys.exit(1)
    else:
        # 命令行操作
        command = sys.argv[1].lower()
        
        if command == 'install':
            install_service()
        elif command == 'uninstall':
            uninstall_service()
        elif command == 'start':
            start_service()
        elif command == 'stop':
            stop_service()
        elif command == 'restart':
            stop_service()
            time.sleep(2)
            start_service()
        else:
            print("使用方法:")
            print("  python windows_service.py install    # 安装服务")
            print("  python windows_service.py uninstall  # 卸载服务")
            print("  python windows_service.py start      # 启动服务")
            print("  python windows_service.py stop       # 停止服务")
            print("  python windows_service.py restart    # 重启服务")