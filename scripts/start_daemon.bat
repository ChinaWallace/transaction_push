@echo off
chcp 65001 >nul
echo 🚀 启动交易工具守护进程
echo ================================

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

echo 📂 项目目录: %PROJECT_ROOT%
echo.

:: 检查虚拟环境
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    echo 🐍 激活虚拟环境...
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
    echo ✅ 虚拟环境已激活
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

:: 启动守护进程
echo 🎯 正在启动守护进程...
cd /d "%PROJECT_ROOT%"
python scripts\daemon_runner.py start

echo.
echo 💡 守护进程已在后台运行
echo    查看状态: python scripts\daemon_runner.py status
echo    停止进程: python scripts\daemon_runner.py stop
echo    查看日志: type logs\daemon.log
echo.
pause