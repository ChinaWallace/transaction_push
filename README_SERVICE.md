# 🚀 交易工具后台服务部署指南

本指南将帮你把交易工具配置为开机自启动的后台服务，实现24/7不间断运行。

## 📋 部署方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Windows服务** | 系统级服务，最稳定 | 需要管理员权限 | 生产环境，长期运行 |
| **守护进程** | 简单易用，无需管理员权限 | 用户登录后才启动 | 开发测试，个人使用 |
| **任务计划程序** | 灵活配置，系统集成好 | 配置相对复杂 | 定时任务，条件启动 |

## 🎯 推荐部署方案

### 方案一：Windows服务 (推荐)

**适合场景**: 生产环境、服务器、需要24/7运行

```bash
# 1. 以管理员身份运行命令提示符
# 2. 进入项目目录
cd /d "C:\path\to\your\trading-tool"

# 3. 激活虚拟环境 (如果使用)
.venv\Scripts\activate

# 4. 安装pywin32依赖
pip install pywin32

# 5. 安装服务
python scripts\windows_service.py install

# 6. 启动服务
net start TradingToolService
```

**或者使用一键安装脚本**:
```bash
# 右键点击 scripts\install_service.bat
# 选择"以管理员身份运行"
```

### 方案二：守护进程 (简单)

**适合场景**: 个人电脑、开发环境、不需要管理员权限

```bash
# 1. 进入项目目录
cd /d "C:\path\to\your\trading-tool"

# 2. 启动守护进程
python scripts\daemon_runner.py start

# 3. 添加到开机启动 (可选)
python scripts\startup_script.py add_registry
```

**或者使用批处理脚本**:
```bash
# 双击运行 scripts\start_daemon.bat
```

## 🛠️ 详细安装步骤

### Step 1: 环境准备

1. **确保Python环境正常**
   ```bash
   python --version
   # 应该显示 Python 3.8+
   ```

2. **激活虚拟环境** (如果使用)
   ```bash
   .venv\Scripts\activate
   ```

3. **安装必要依赖**
   ```bash
   pip install pywin32  # Windows服务支持
   ```

### Step 2: 选择部署方式

#### 🔧 方式A: 使用图形化管理器 (最简单)

1. **双击运行**: `scripts\service_manager.bat`
2. **选择操作**: 根据菜单提示选择安装方式
3. **完成配置**: 按照向导完成设置

#### 🔧 方式B: 使用命令行

**Windows服务部署**:
```bash
# 安装服务 (需要管理员权限)
python scripts\windows_service.py install

# 启动服务
net start TradingToolService

# 设置自动启动 (已默认设置)
sc config TradingToolService start= auto
```

**守护进程部署**:
```bash
# 启动守护进程
python scripts\daemon_runner.py start

# 添加到开机启动
python scripts\startup_script.py add_registry
```

### Step 3: 验证部署

1. **检查服务状态**
   ```bash
   # Windows服务
   sc query TradingToolService
   
   # 守护进程
   python scripts\daemon_runner.py status
   ```

2. **查看日志**
   ```bash
   # 服务日志
   type logs\service.log
   
   # 守护进程日志
   type logs\daemon.log
   
   # 应用日志
   type logs\app.log
   ```

3. **测试重启**
   - 重启电脑
   - 检查服务是否自动启动
   - 验证交易功能正常

## 📊 服务管理

### 启动/停止服务

**Windows服务**:
```bash
net start TradingToolService    # 启动
net stop TradingToolService     # 停止
net restart TradingToolService  # 重启 (需要先停止再启动)
```

**守护进程**:
```bash
python scripts\daemon_runner.py start    # 启动
python scripts\daemon_runner.py stop     # 停止
python scripts\daemon_runner.py restart  # 重启
```

### 查看状态和日志

```bash
# 查看服务状态
python scripts\daemon_runner.py status

# 实时查看日志
powershell "Get-Content logs\app.log -Wait -Tail 50"

# 查看错误日志
type logs\error.log
```

### 服务配置

**修改服务参数**: 编辑 `scripts\windows_service.py`
```python
# 修改重启策略
max_restarts = 10        # 最大重启次数
restart_delay = 60       # 重启延迟(秒)

# 修改服务信息
_svc_display_name_ = "你的服务显示名称"
_svc_description_ = "你的服务描述"
```

## 🔧 开机启动配置

### 方法1: 注册表启动项
```bash
# 添加到启动项
python scripts\startup_script.py add_registry

# 移除启动项
python scripts\startup_script.py remove_registry

# 查看状态
python scripts\startup_script.py status
```

### 方法2: 任务计划程序
```bash
# 添加任务
python scripts\startup_script.py add_task

# 移除任务
python scripts\startup_script.py remove_task
```

### 方法3: 服务自动启动 (推荐)
Windows服务默认设置为自动启动，无需额外配置。

## 🚨 故障排除

### 常见问题

1. **服务安装失败**
   ```
   错误: 需要管理员权限
   解决: 以管理员身份运行命令提示符
   ```

2. **pywin32未安装**
   ```bash
   pip install pywin32
   # 如果还有问题，尝试:
   python -m pip install --upgrade pywin32
   ```

3. **服务启动失败**
   ```bash
   # 查看详细错误
   type logs\service.log
   type logs\error.log
   
   # 检查Python路径
   where python
   ```

4. **端口占用**
   ```bash
   # 检查端口占用
   netstat -ano | findstr :8000
   
   # 修改配置文件中的端口
   # 编辑 .env 文件
   ```

### 日志分析

**关键日志文件**:
- `logs\service.log` - 服务运行日志
- `logs\daemon.log` - 守护进程日志  
- `logs\app.log` - 应用主日志
- `logs\trading.log` - 交易相关日志
- `logs\error.log` - 错误日志

**常见日志关键词**:
- `✅` - 成功操作
- `❌` - 错误信息
- `⚠️` - 警告信息
- `🔄` - 重试操作
- `🚀` - 启动信息

## 📱 监控和通知

服务部署后，你将收到以下通知:

1. **启动通知** - 服务启动完成
2. **交易信号** - 发现交易机会
3. **异常警报** - 服务异常或重启
4. **市场机会** - Kronos AI发现的机会

**配置通知渠道**: 编辑 `.env` 文件
```env
# 企业微信通知
WECHAT_WEBHOOK_URL=your_webhook_url

# 邮件通知  
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_USERNAME=your_email
EMAIL_PASSWORD=your_password
```

## 🔄 更新和维护

### 更新代码
```bash
# 停止服务
net stop TradingToolService

# 更新代码
git pull origin main

# 重新安装依赖 (如果需要)
pip install -r requirements.txt

# 启动服务
net start TradingToolService
```

### 定期维护
```bash
# 清理旧日志 (保留最近7天)
forfiles /p logs /s /m *.log /d -7 /c "cmd /c del @path"

# 检查磁盘空间
dir logs

# 备份配置
copy .env .env.backup
```

## 🎯 性能优化

### 系统资源配置

**推荐配置**:
- CPU: 2核心以上
- 内存: 4GB以上  
- 磁盘: 10GB可用空间
- 网络: 稳定的互联网连接

**优化设置**:
```python
# 在 app/core/config.py 中调整
MAX_CONCURRENT_REQUESTS = 10  # 并发请求数
REQUEST_TIMEOUT = 30          # 请求超时时间
CACHE_TTL = 300              # 缓存时间
```

### 监控指标

定期检查以下指标:
- CPU使用率 < 50%
- 内存使用率 < 70%  
- 磁盘使用率 < 80%
- 网络延迟 < 100ms

## 📞 技术支持

如果遇到问题:

1. **查看日志**: 首先检查相关日志文件
2. **重启服务**: 尝试重启解决临时问题
3. **检查配置**: 确认配置文件正确
4. **更新依赖**: 确保所有依赖包是最新版本

**快速诊断脚本**:
```bash
# 运行诊断
python scripts\service_manager.bat
# 选择 "6. 查看服务状态"
```

---

🎉 **恭喜！** 你的交易工具现在可以24/7不间断运行了！

记得定期检查日志和系统状态，确保服务稳定运行。