@echo off
chcp 65001 >nul
echo 🗑️ 交易工具服务卸载脚本
echo ================================

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 需要管理员权限才能卸载Windows服务
    echo 请右键点击此脚本，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

echo 📂 项目目录: %PROJECT_ROOT%
echo.

:: 检查虚拟环境
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    echo 🐍 激活虚拟环境...
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

:: 卸载Windows服务
echo 🛑 正在卸载交易工具Windows服务...
cd /d "%PROJECT_ROOT%"
python scripts\windows_service.py uninstall

if %errorLevel% equ 0 (
    echo ✅ 服务卸载成功！
) else (
    echo ❌ 服务卸载失败
)

echo.
pause