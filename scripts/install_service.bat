@echo off
chcp 65001 >nul
echo 🚀 交易工具服务安装脚本
echo ================================

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 需要管理员权限才能安装Windows服务
    echo 请右键点击此脚本，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

echo 📂 项目目录: %PROJECT_ROOT%
echo.

:: 检查Python环境
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 未找到Python环境
    echo 请确保Python已安装并添加到PATH环境变量
    pause
    exit /b 1
)

echo ✅ Python环境检查通过

:: 检查虚拟环境
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    echo 🐍 检测到虚拟环境，正在激活...
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
    echo ✅ 虚拟环境已激活
) else (
    echo ⚠️ 未检测到虚拟环境，使用系统Python
)

:: 安装pywin32（如果需要）
echo 📦 检查pywin32依赖...
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo 📥 正在安装pywin32...
    pip install pywin32
    if %errorLevel% neq 0 (
        echo ❌ pywin32安装失败
        pause
        exit /b 1
    )
    echo ✅ pywin32安装成功
) else (
    echo ✅ pywin32已安装
)

:: 安装Windows服务
echo.
echo 🔧 正在安装交易工具Windows服务...
cd /d "%PROJECT_ROOT%"
python scripts\windows_service.py install

if %errorLevel% equ 0 (
    echo.
    echo ✅ 服务安装成功！
    echo.
    echo 🎯 接下来你可以：
    echo    1. 启动服务: net start TradingToolService
    echo    2. 停止服务: net stop TradingToolService
    echo    3. 在服务管理器中管理服务 ^(services.msc^)
    echo.
    echo 💡 服务已设置为自动启动，重启电脑后会自动运行
    echo.
    
    :: 询问是否立即启动服务
    set /p START_NOW="是否立即启动服务？(Y/N): "
    if /i "%START_NOW%"=="Y" (
        echo 🚀 正在启动服务...
        net start TradingToolService
        if %errorLevel% equ 0 (
            echo ✅ 服务启动成功！
        ) else (
            echo ❌ 服务启动失败，请检查日志
        )
    )
) else (
    echo ❌ 服务安装失败
)

echo.
pause