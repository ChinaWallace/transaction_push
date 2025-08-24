# Python 交易分析工具

基于Python的智能量化交易分析工具，使用FastAPI构建，提供持仓分析、趋势监控、资金费率分析等核心功能。

## ✨ 核心特性

🎯 **智能持仓分析** - 100分制评估持仓健康度，提供具体操作建议  
� ***多周期趋势分析** - SuperTrend指标，支持日线/4H/1H/15分钟多时间周期  
💰 **资金费率监控** - 负费率机会发现和高费率预警  
📊 **持仓量异动检测** - 实时监控合约持仓量变化  
🔍 **交易量异常监控** - 庄神指标检测成交量异常放大  
🔔 **多渠道通知** - 支持飞书、微信、Telegram、邮件推送

## 🚀 主要功能

### 📊 智能持仓分析
- **账户概况分析**：总权益、持仓数量、盈亏情况、资金利用率
- **持仓健康度评分**：100分制评估每个持仓的风险状况
- **风险评估系统**：集中度、杠杆、亏损、方向性风险全面评估
- **智能建议生成**：持有、减仓、加仓、平仓、对冲、重新平衡
- **风险警报机制**：自动识别严重亏损、高杠杆、集中度风险

### 🤖 统一交易决策系统
- **智能决策融合**：传统技术分析 + 机器学习预测
- **动态止盈止损**：基于ATR和置信度的自适应计算
- **中文信号输出**：强烈买入、买入、持有、卖出、强烈卖出
- **多币种支持**：BTC、ETH、SOL、ADA、DOT、AVAX、LINK、UNI等
- **智能仓位管理**：根据置信度和波动性动态调整仓位大小

### 📈 多周期趋势分析
- **SuperTrend指标**：支持日线、4小时、1小时、15分钟多时间周期
- **智能信号识别**：10种信号组合判断，分级通知推送
- **趋势强度评估**：强势多头共振、回调中多头、强势空头共振等

### 💰 资金费率监控
- **负费率监控**：自动筛选负费率套利机会
- **高费率预警**：监控异常高费率情况
- **定时推送**：每4小时推送TOP5费率数据

### 📊 持仓量变化监控
- **异动检测**：监控合约持仓量的异常变化
- **实时提醒**：持仓量增长超过阈值时立即通知
- **历史趋势分析**：支持历史持仓量趋势分析

### 🔍 交易量异常监控
- **庄神指标**：检测成交量异常放大的标的
- **强势标的识别**：成交量连续3倍以上增长
- **价格配合分析**：结合价格走势判断有效性

### 📢 多渠道通知推送
- **飞书机器人**：支持飞书群组消息推送
- **企业微信**：支持企业微信机器人推送
- **Telegram**：支持Telegram Bot推送
- **邮件通知**：支持SMTP邮件通知

## 🛠 技术架构

- **Web框架**：FastAPI + Uvicorn
- **数据处理**：Pandas + NumPy + TA-Lib
- **机器学习**：Scikit-learn + Joblib
- **交易所API**：OKX API + python-binance
- **任务调度**：APScheduler
- **数据库**：MySQL + SQLAlchemy
- **异步处理**：asyncio + aiohttp

## 📦 快速开始

### 系统要求
- Python 3.9+
- MySQL 5.7+

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/ChinaWallace/transaction_push
cd transaction_push
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置环境变量** ⚠️ **重要**
```bash
# 复制环境配置文件
cp env.example .env

# 编辑 .env 文件，填入你的配置
# 必须配置的项目：
# - 币安API密钥
# - 数据库连接信息  
# - 至少一个通知渠道
```

4. **数据库初始化**
```bash
python scripts/init_db.py
```

5. **启动服务**
```bash
python main.py
```

## ⚙️ 环境配置详解

### OKX API配置（主要使用）
```env
# 在OKX获取API密钥
OKX_API_KEY=your_okx_api_key_here
OKX_SECRET_KEY=your_okx_secret_key_here
OKX_PASSPHRASE=your_okx_passphrase_here
OKX_SANDBOX=false  # 生产环境设为false
```

### 币安API配置（备用）
```env
# 在币安获取API密钥（可选配置）
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET_KEY=your_binance_secret_key_here
BINANCE_TESTNET=false  # 生产环境设为false
```

### 数据库配置（必需）
```env
# MySQL数据库连接
DATABASE_URL=mysql+pymysql://用户名:密码@localhost:3306/数据库名
# 例如：mysql+pymysql://root:123456@localhost:3306/trading_db
```

### 通知配置（至少配置一个）

**飞书机器人**
```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook密钥
```

**企业微信机器人**
```env
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的密钥
```

**Telegram机器人**
```env
TELEGRAM_BOT_TOKEN=你的机器人token
TELEGRAM_CHAT_ID=你的聊天ID
```

**邮件通知**
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_email_password
SMTP_FROM=your_email@gmail.com
```

### 机器学习配置（可选）
```env
# 启用ML功能
ML_CONFIG__ENABLE_ML_PREDICTION=true
ML_CONFIG__ENABLE_ANOMALY_DETECTION=true

# 预测模型配置
ML_CONFIG__PREDICTION_MODEL__MODEL_TYPE=random_forest
ML_CONFIG__PREDICTION_MODEL__MIN_ACCURACY_THRESHOLD=0.6

# 监控币种
MONITORED_SYMBOLS=["ETH-USDT-SWAP", "SOL-USDT-SWAP", "BTC-USDT-SWAP"]
```

### 监控参数配置（可选调整）
```env
# 持仓量变化阈值 (1.05表示5%增长触发提醒)
OPEN_INTEREST_THRESHOLD=1.05

# 成交量异常倍数
VOLUME_MULTIPLIER=3.0

# 监控间隔(分钟)
FUNDING_RATE_INTERVAL=240     # 费率监控间隔
TREND_ANALYSIS_INTERVAL=15    # 趋势分析间隔  
OPEN_INTEREST_INTERVAL=5      # 持仓量监控间隔
VOLUME_MONITOR_INTERVAL=60    # 交易量监控间隔
POSITION_ANALYSIS_INTERVAL=120    # 持仓分析间隔
```

## 📡 API接口

### 交易决策API
```bash
# 获取账户持仓分析
GET /api/trading/account-analysis

# 获取交易建议
GET /api/trading/advice/{symbol}

# 获取市场分析
GET /api/trading/market-analysis/{symbol}
```

### 趋势分析API
```bash
# 单个标的趋势分析
GET /api/trend/analyze/{symbol}

# 批量趋势分析
POST /api/trend/batch-analyze
{
  "symbols": ["ETH-USDT-SWAP", "SOL-USDT-SWAP"]
}
```

### 监控服务API
```bash
# 费率监控
GET /api/monitor/funding-rate

# 持仓量监控  
GET /api/monitor/open-interest

# 交易量监控
GET /api/monitor/volume

# 综合监控状态
GET /api/monitor/status
```

### 通知服务API
```bash
# 发送测试通知
POST /api/notification/test
{
  "channel": "feishu",
  "message": "测试消息"
}
```

## 📊 信号说明

### SuperTrend信号组合

| 组合 | 日线 | 4H | 1H | 15min | 信号类型 | 级别 | 策略建议 |
|------|------|----|----|-------|----------|------|----------|
| ① | ↑ | ↑ | ↑ | ↑ | 强势多头共振 | 🔵 强烈 | 坚决做多，分批建仓 |
| ② | ↑ | ↑ | ↑ | ↓ | 回调中多头 | 🟡 中等 | 等待回调结束再做多 |
| ③ | ↑ | ↑ | ↓ | ↑ | 短线反弹 | 🟡 中等 | 快进快出短多单 |
| ④ | ↑ | ↓ | ↑ | ↑ | 背离多头 | 🟡 中等 | 快进快出或控制仓位 |
| ⑤ | ↓ | ↓ | ↓ | ↓ | 强势空头共振 | 🔵 强烈 | 做空为主，顺势操作 |
| ⑥ | ↓ | ↓ | ↓ | ↑ | 短线反弹 | 🟡 中等 | 反弹做空，设好止损 |
| ⑦ | ↓ | ↓ | ↑ | ↑ | 反转尝试 | 🟠 较弱 | 多单试探介入 |
| ⑧ | ↓ | ↑ | ↑ | ↑ | 底部反转 | 🟡 中等 | 尝试底部建仓 |
| ⑨ | ↑ | ↑ | ↓ | ↓ | 回调确认 | ⚪ 观望 | 等待趋势重转 |
| ⑩ | 其他 | - | - | - | 信号混乱 | ⚪ 观望 | 不建议操作 |


## 💼 持仓分析功能详解

### 持仓健康度评估 (100分制)
- **盈亏情况** (30分)：亏损超过15%扣30分，盈利超过15%加10分
- **杠杆风险** (25分)：杠杆>20x扣25分，杠杆>10x扣15分
- **市场趋势一致性** (25分)：逆势持仓扣25分，趋势不明扣10分
- **波动率风险** (20分)：高波动率扣20分，中等波动率扣5分

### 投资组合风险评估
- **集中度风险**：单一持仓占比>30%触发警报
- **杠杆风险**：总杠杆>10x触发高风险警报
- **未实现亏损风险**：亏损比例>15%触发紧急风险控制
- **方向性风险**：同向持仓>80%提示缺乏对冲

### 智能建议系统
- **持有**：持仓状态良好，继续持有
- **减仓**：亏损过大或杠杆过高，建议减仓
- **加仓**：健康持仓且顺应趋势，可适当加仓
- **平仓**：危险持仓，风险过大，建议平仓
- **对冲**：逆势持仓，建议对冲或调整
- **重新平衡**：投资组合需要重新配置

## 📁 项目结构

```
transaction_push/
├── app/                    # 应用主目录
│   ├── api/               # API路由
│   ├── core/              # 核心配置
│   │   ├── config.py      # 应用配置
│   │   └── logging.py     # 日志配置
│   ├── models/            # 数据模型
│   ├── services/          # 业务逻辑
│   ├── utils/             # 工具函数
│   ├── schemas/           # Pydantic模型
│   └── strategies/        # 交易策略
├── tests/                 # 测试文件
│   ├── test_config.py     # 配置测试
│   └── test_services.py   # 服务测试
├── docs/                  # 文档目录
├── logs/                  # 日志目录
├── scripts/               # 部署脚本
│   ├── init_db.py         # 数据库初始化
│   ├── install.bat        # Windows安装脚本
│   ├── start.bat          # Windows启动脚本
│   └── update_env_symbols.py # 更新币种配置
├── requirements.txt       # 依赖列表
├── env.example           # 环境变量示例
├── .env                  # 环境变量配置
└── main.py               # 启动文件
```

## 📈 使用示例

### 持仓分析示例
```
✅ 持仓分析完成 (评分: 55/100)
📊 账户概况:
   总权益: $8,234.55 USDT
   持仓数量: 3 个
   未实现盈亏: $-221.65 USDT (-2.7%)
   资金利用率: 7.7%

⚠️ 风险评估:
   风险等级: low
   集中度风险: 3.5%

🚨 风险警报 (2 个):
   • ETH-USD-SWAP: 严重亏损 46.1%
   • SOON-USDT-SWAP: 严重亏损 218.1%

💡 主要建议:
   • 持仓平衡建议: 持仓方向过于单一，缺乏对冲
```

### 趋势分析示例
```
📈 ETH-USDT-SWAP 趋势分析:
   信号组合: 强势多头共振 (①)
   信号强度: 🔵 强烈
   策略建议: 坚决做多，分批建仓
   
   各周期状态:
   • 日线: ↑ 多头
   • 4小时: ↑ 多头  
   • 1小时: ↑ 多头
   • 15分钟: ↑ 多头
```

## 🔍 故障排查

### 常见问题

**1. 数据库连接失败**
- 检查MySQL服务是否启动
- 确认DATABASE_URL配置正确
- 检查数据库用户权限

**2. 币安API连接失败**
- 确认API密钥配置正确
- 检查网络连接和代理设置
- 验证API权限是否足够

**3. 通知推送失败**
- 检查Webhook URL是否正确
- 确认机器人权限配置
- 查看日志文件获取详细错误信息

**4. OKX API连接问题**
- 检查OKX API密钥、密码和Passphrase配置
- 确认API权限包含交易和数据读取权限
- 检查网络连接，可能需要配置代理

**5. 持仓分析问题**
- 确保OKX账户有持仓数据
- 检查账户API权限是否包含持仓查询
- 持仓分析需要一定的计算时间，请耐心等待

**6. ML模型相关问题**
- 首次使用需要训练模型，可能需要较长时间
- 确保有足够的历史数据用于训练
- 检查模型文件是否正确保存在models/目录

**7. 查看日志**
```bash
# 应用日志
tail -f logs/app.log

# 错误日志
tail -f logs/error.log

# 监控日志
tail -f logs/monitor.log

# 交易日志
tail -f logs/trading.log
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issues 和 Pull Requests！

## 📞 联系方式

如有问题，请创建 Issue 或联系维护者。