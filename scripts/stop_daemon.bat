@echo off
chcp 65001 >nul
echo 🛑 停止交易工具守护进程
echo ================================

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

echo 📂 项目目录: %PROJECT_ROOT%
echo.

:: 检查虚拟环境
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

:: 停止守护进程
echo 🛑 正在停止守护进程...
cd /d "%PROJECT_ROOT%"
python scripts\daemon_runner.py stop

echo.
pause