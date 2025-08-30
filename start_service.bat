@echo off
chcp 65001 >nul
title 交易工具快速启动

echo ╔══════════════════════════════════════╗
echo ║     🚀 交易工具快速启动脚本         ║
echo ╚══════════════════════════════════════╝
echo.

:: 检查是否在项目根目录
if not exist "main.py" (
    echo ❌ 请在项目根目录运行此脚本
    echo 当前目录: %CD%
    pause
    exit /b 1
)

:: 激活虚拟环境 (如果存在)
if exist ".venv\Scripts\activate.bat" (
    echo 🐍 激活虚拟环境...
    call ".venv\Scripts\activate.bat"
    echo ✅ 虚拟环境已激活
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

echo.
echo 🎯 选择启动方式:
echo   1. 🖥️  前台运行 (可以看到实时日志)
echo   2. 🔧 后台守护进程 (后台运行)
echo   3. 📦 Windows服务管理
echo   4. ⚙️  开机启动配置
echo   5. 🔍 系统状态检查
echo.

set /p choice="请选择 (1-5): "

if "%choice%"=="1" goto FOREGROUND
if "%choice%"=="2" goto DAEMON
if "%choice%"=="3" goto SERVICE
if "%choice%"=="4" goto STARTUP
if "%choice%"=="5" goto STATUS_CHECK
goto INVALID

:FOREGROUND
echo.
echo 🖥️ 前台运行模式
echo ================================
echo 💡 按 Ctrl+C 可以停止程序
echo.
python main.py
goto END

:DAEMON
echo.
echo 🔧 后台守护进程模式
echo ================================
python scripts\daemon_runner.py start
if %errorLevel% equ 0 (
    echo.
    echo ✅ 守护进程启动成功！
    echo 💡 使用以下命令管理:
    echo    查看状态: python scripts\daemon_runner.py status
    echo    停止进程: python scripts\daemon_runner.py stop
    echo    查看日志: type logs\daemon.log
) else (
    echo ❌ 守护进程启动失败
)
goto END

:SERVICE
echo.
echo 📦 Windows服务管理
echo ================================
call scripts\service_manager.bat
goto END

:STARTUP
echo.
echo ⚙️ 开机启动配置
echo ================================
echo 选择配置方式:
echo   1. 注册表启动项 (推荐)
echo   2. 任务计划程序
echo   3. 查看当前状态
echo.
set /p startup_choice="请选择 (1-3): "

if "%startup_choice%"=="1" (
    python scripts\startup_script.py add_registry
) else if "%startup_choice%"=="2" (
    python scripts\startup_script.py add_task
) else if "%startup_choice%"=="3" (
    python scripts\startup_script.py status
) else (
    echo ❌ 无效选择
)
goto END

:STATUS_CHECK
echo.
echo 🔍 系统状态检查
echo ================================
python scripts\check_status.py
goto END

:INVALID
echo ❌ 无效选择，请重新运行脚本
goto END

:END
echo.
pause