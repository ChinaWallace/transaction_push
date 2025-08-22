@echo off
echo ================================
echo Python Trading Analysis Tool
echo ================================ 
echo.

echo 开始安装依赖...
echo.

REM 检查Python版本
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.9+
    pause
    exit /b 1
)

REM 创建虚拟环境
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo 激活虚拟环境...
call venv\Scripts\activate.bat

REM 升级pip
echo 升级pip...
python -m pip install --upgrade pip

REM 安装依赖
echo 安装项目依赖...
pip install -r requirements.txt

REM 检查配置文件
if not exist ".env" (
    echo 创建配置文件...
    copy env.example .env
    echo.
    echo 请编辑 .env 文件，填入你的API密钥和配置信息
)

echo.
echo ================================
echo 安装完成！
echo ================================
echo.
echo 下一步：
echo 1. 编辑 .env 文件，配置API密钥和数据库连接
echo 2. 运行 python scripts\init_db.py 初始化数据库
echo 3. 运行 scripts\start.bat 启动服务
echo.
pause
