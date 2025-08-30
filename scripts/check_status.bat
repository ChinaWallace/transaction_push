@echo off
chcp 65001 >nul
title 交易工具状态检查

echo 🔍 交易工具系统状态检查
echo ================================

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

:: 进入项目目录
cd /d "%PROJECT_ROOT%"

:: 检查虚拟环境
if exist ".venv\Scripts\activate.bat" (
    echo 🐍 激活虚拟环境...
    call ".venv\Scripts\activate.bat"
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

:: 运行状态检查
python scripts\check_status.py

echo.
echo 💡 更多管理选项请运行: scripts\service_manager.bat
pause