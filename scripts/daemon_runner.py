# -*- coding: utf-8 -*-
"""
后台守护进程运行器
Daemon Runner for Trading Tool - 简单的后台运行方案
"""

import sys
import os
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TradingDaemon:
    """交易工具守护进程"""
    
    def __init__(self):
        self.project_root = project_root
        self.pid_file = self.project_root / "logs" / "daemon.pid"
        self.log_file = self.project_root / "logs" / "daemon.log"
        self.is_running = True
        self.main_process: Optional[subprocess.Popen] = None
        
        # 确保日志目录存在
        self.log_file.parent.mkdir(exist_ok=True)
        
        # 设置日志
        self.setup_logging()
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('TradingDaemon')
        
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"🛑 收到停止信号 {signum}，正在关闭...")
        self.is_running = False
        
        # 停止主进程
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
        
        # 清理PID文件
        self.cleanup()
        sys.exit(0)
        
    def write_pid(self):
        """写入PID文件"""
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            self.logger.info(f"📝 PID文件已写入: {self.pid_file}")
        except Exception as e:
            self.logger.error(f"❌ 写入PID文件失败: {e}")
            
    def cleanup(self):
        """清理资源"""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.info("🗑️ PID文件已清理")
        except Exception as e:
            self.logger.error(f"❌ 清理PID文件失败: {e}")
            
    def is_already_running(self) -> bool:
        """检查是否已经在运行"""
        if not self.pid_file.exists():
            return False
            
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # 检查进程是否存在
            try:
                os.kill(pid, 0)  # 发送信号0检查进程是否存在
                return True
            except OSError:
                # 进程不存在，清理旧的PID文件
                self.pid_file.unlink()
                return False
                
        except (ValueError, FileNotFoundError):
            return False
            
    def start_main_process(self) -> subprocess.Popen:
        """启动主程序"""
        python_exe = sys.executable
        main_script = self.project_root / "main.py"
        
        # 设置环境变量
        env = os.environ.copy()
        env['PYTHONPATH'] = str(self.project_root)
        
        # 启动主程序
        process = subprocess.Popen(
            [python_exe, str(main_script)],
            cwd=str(self.project_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        
        self.logger.info(f"✅ 主程序已启动 (PID: {process.pid})")
        return process
        
    def run(self):
        """运行守护进程"""
        if self.is_already_running():
            self.logger.error("❌ 守护进程已在运行中")
            return False
            
        self.write_pid()
        self.logger.info("🚀 交易工具守护进程启动")
        
        restart_count = 0
        max_restarts = 10
        restart_delay = 60  # 重启延迟60秒
        
        try:
            while self.is_running:
                try:
                    self.logger.info("🎯 启动交易分析主程序...")
                    self.main_process = self.start_main_process()
                    restart_count = 0  # 重置重启计数
                    
                    # 监控主程序
                    while self.is_running:
                        if self.main_process.poll() is not None:
                            # 主程序已退出
                            stdout, stderr = self.main_process.communicate()
                            exit_code = self.main_process.returncode
                            
                            self.logger.warning(f"⚠️ 主程序退出 (退出码: {exit_code})")
                            if stdout:
                                self.logger.info(f"标准输出: {stdout[-500:]}")
                            if stderr:
                                self.logger.error(f"错误输出: {stderr[-500:]}")
                            
                            if not self.is_running:
                                break
                            
                            # 检查是否需要重启
                            restart_count += 1
                            if restart_count > max_restarts:
                                self.logger.error(f"❌ 主程序重启次数超过限制 ({max_restarts})，停止守护进程")
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
                            self.logger.error("❌ 异常重启次数过多，停止守护进程")
                            break
                            
        finally:
            self.cleanup()
            self.logger.info("✅ 交易工具守护进程已停止")
            
        return True


def start_daemon():
    """启动守护进程"""
    daemon = TradingDaemon()
    return daemon.run()


def stop_daemon():
    """停止守护进程"""
    pid_file = project_root / "logs" / "daemon.pid"
    
    if not pid_file.exists():
        print("❌ 守护进程未运行")
        return False
        
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        print(f"🛑 正在停止守护进程 (PID: {pid})...")
        
        # 发送终止信号
        try:
            os.kill(pid, signal.SIGTERM)
            
            # 等待进程结束
            for _ in range(30):  # 等待最多30秒
                try:
                    os.kill(pid, 0)
                    time.sleep(1)
                except OSError:
                    break
            else:
                # 强制终止
                print("⚠️ 进程未在30秒内退出，强制终止...")
                os.kill(pid, signal.SIGKILL)
            
            print("✅ 守护进程已停止")
            return True
            
        except OSError as e:
            if e.errno == 3:  # No such process
                print("⚠️ 进程已不存在，清理PID文件")
                pid_file.unlink()
                return True
            else:
                raise
                
    except Exception as e:
        print(f"❌ 停止守护进程失败: {e}")
        return False


def status_daemon():
    """查看守护进程状态"""
    pid_file = project_root / "logs" / "daemon.pid"
    
    if not pid_file.exists():
        print("📊 状态: 守护进程未运行")
        return False
        
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # 检查进程是否存在
        try:
            os.kill(pid, 0)
            print(f"📊 状态: 守护进程正在运行 (PID: {pid})")
            
            # 显示日志文件信息
            log_file = project_root / "logs" / "daemon.log"
            if log_file.exists():
                stat = log_file.stat()
                mod_time = datetime.fromtimestamp(stat.st_mtime)
                print(f"📝 日志文件: {log_file}")
                print(f"📅 最后更新: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"📏 文件大小: {stat.st_size} 字节")
            
            return True
            
        except OSError:
            print("⚠️ PID文件存在但进程已不存在，清理PID文件")
            pid_file.unlink()
            return False
            
    except Exception as e:
        print(f"❌ 检查状态失败: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python daemon_runner.py start    # 启动守护进程")
        print("  python daemon_runner.py stop     # 停止守护进程")
        print("  python daemon_runner.py restart  # 重启守护进程")
        print("  python daemon_runner.py status   # 查看状态")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'start':
        if start_daemon():
            print("✅ 守护进程启动成功")
        else:
            print("❌ 守护进程启动失败")
            sys.exit(1)
            
    elif command == 'stop':
        if stop_daemon():
            print("✅ 守护进程停止成功")
        else:
            print("❌ 守护进程停止失败")
            sys.exit(1)
            
    elif command == 'restart':
        print("🔄 重启守护进程...")
        stop_daemon()
        time.sleep(2)
        if start_daemon():
            print("✅ 守护进程重启成功")
        else:
            print("❌ 守护进程重启失败")
            sys.exit(1)
            
    elif command == 'status':
        status_daemon()
        
    else:
        print(f"❌ 未知命令: {command}")
        sys.exit(1)