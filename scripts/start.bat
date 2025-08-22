@echo off
echo ================================
echo Python Trading Analysis Tool
echo ================================
echo.

echo 启动交易分析工具...
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo 错误: 未找到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查配置文件
if not exist ".env" (
    echo 错误: 未找到配置文件 .env，请先配置环境变量
    echo 可以参考 env.example 文件创建 .env 配置
    pause
    exit /b 1
)

REM 启动应用
echo 正在启动服务器...
python main.py

pause
