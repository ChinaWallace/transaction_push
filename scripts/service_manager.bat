@echo off
chcp 65001 >nul
title 交易工具服务管理器

:MENU
cls
echo ╔══════════════════════════════════════╗
echo ║        🚀 交易工具服务管理器        ║
echo ╠══════════════════════════════════════╣
echo ║                                      ║
echo ║  1. 📦 安装Windows服务               ║
echo ║  2. 🗑️ 卸载Windows服务               ║
echo ║  3. ▶️ 启动服务                      ║
echo ║  4. ⏹️ 停止服务                      ║
echo ║  5. 🔄 重启服务                      ║
echo ║  6. 📊 查看服务状态                  ║
echo ║                                      ║
echo ║  7. 🐍 启动守护进程 (简单模式)       ║
echo ║  8. 🛑 停止守护进程                  ║
echo ║  9. 📈 查看守护进程状态              ║
echo ║                                      ║
echo ║  S. 🔧 打开服务管理器                ║
echo ║  L. 📝 查看日志                      ║
echo ║  Q. 🚪 退出                          ║
echo ║                                      ║
echo ╚══════════════════════════════════════╝

set /p choice="请选择操作 (1-9, S, L, Q): "

if /i "%choice%"=="1" goto INSTALL_SERVICE
if /i "%choice%"=="2" goto UNINSTALL_SERVICE
if /i "%choice%"=="3" goto START_SERVICE
if /i "%choice%"=="4" goto STOP_SERVICE
if /i "%choice%"=="5" goto RESTART_SERVICE
if /i "%choice%"=="6" goto STATUS_SERVICE
if /i "%choice%"=="7" goto START_DAEMON
if /i "%choice%"=="8" goto STOP_DAEMON
if /i "%choice%"=="9" goto STATUS_DAEMON
if /i "%choice%"=="S" goto OPEN_SERVICES
if /i "%choice%"=="L" goto VIEW_LOGS
if /i "%choice%"=="Q" goto EXIT

echo ❌ 无效选择，请重新输入
pause
goto MENU

:INSTALL_SERVICE
echo.
echo 📦 安装Windows服务...
call "%~dp0install_service.bat"
pause
goto MENU

:UNINSTALL_SERVICE
echo.
echo 🗑️ 卸载Windows服务...
call "%~dp0uninstall_service.bat"
pause
goto MENU

:START_SERVICE
echo.
echo ▶️ 启动Windows服务...
net start TradingToolService
if %errorLevel% equ 0 (
    echo ✅ 服务启动成功
) else (
    echo ❌ 服务启动失败
)
pause
goto MENU

:STOP_SERVICE
echo.
echo ⏹️ 停止Windows服务...
net stop TradingToolService
if %errorLevel% equ 0 (
    echo ✅ 服务停止成功
) else (
    echo ❌ 服务停止失败
)
pause
goto MENU

:RESTART_SERVICE
echo.
echo 🔄 重启Windows服务...
net stop TradingToolService
timeout /t 3 /nobreak >nul
net start TradingToolService
if %errorLevel% equ 0 (
    echo ✅ 服务重启成功
) else (
    echo ❌ 服务重启失败
)
pause
goto MENU

:STATUS_SERVICE
echo.
echo 📊 查看Windows服务状态...
sc query TradingToolService
echo.
echo 📝 最近的服务日志:
if exist "%~dp0..\logs\service.log" (
    powershell "Get-Content '%~dp0..\logs\service.log' -Tail 10"
) else (
    echo 未找到服务日志文件
)
pause
goto MENU

:START_DAEMON
echo.
echo 🐍 启动守护进程...
call "%~dp0start_daemon.bat"
pause
goto MENU

:STOP_DAEMON
echo.
echo 🛑 停止守护进程...
call "%~dp0stop_daemon.bat"
pause
goto MENU

:STATUS_DAEMON
echo.
echo 📈 查看守护进程状态...
cd /d "%~dp0.."
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)
python scripts\daemon_runner.py status
echo.
echo 📝 最近的守护进程日志:
if exist "logs\daemon.log" (
    powershell "Get-Content 'logs\daemon.log' -Tail 10"
) else (
    echo 未找到守护进程日志文件
)
pause
goto MENU

:OPEN_SERVICES
echo.
echo 🔧 打开Windows服务管理器...
services.msc
goto MENU

:VIEW_LOGS
echo.
echo 📝 查看日志文件...
echo.
echo 可用的日志文件:
if exist "%~dp0..\logs\app.log" echo   - app.log (应用日志)
if exist "%~dp0..\logs\service.log" echo   - service.log (服务日志)
if exist "%~dp0..\logs\daemon.log" echo   - daemon.log (守护进程日志)
if exist "%~dp0..\logs\trading.log" echo   - trading.log (交易日志)
if exist "%~dp0..\logs\error.log" echo   - error.log (错误日志)
echo.
set /p logfile="请输入要查看的日志文件名 (如 app.log): "
if exist "%~dp0..\logs\%logfile%" (
    echo.
    echo 📄 %logfile% 最近50行:
    powershell "Get-Content '%~dp0..\logs\%logfile%' -Tail 50"
) else (
    echo ❌ 日志文件不存在: %logfile%
)
pause
goto MENU

:EXIT
echo.
echo 👋 再见！
exit /b 0