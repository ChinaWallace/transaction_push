# Python 交易分析工具

一个基于Python的量化交易分析工具，提供趋势分析、费率监控、持仓量变化监控等功能。

## 🚀 主要功能

### 📈 趋势分析
- **多周期SuperTrend指标分析**：支持日线、4小时、1小时、15分钟多时间周期
- **智能信号识别**：实现10种信号组合判断
- **分级通知推送**：根据信号强度提供不同级别的通知

### 💰 资金费率监控
- **负费率监控**：自动筛选负费率标的
- **高费率预警**：监控异常高费率情况
- **定时推送**：每4小时推送TOP5费率数据

### 📊 持仓量变化监控  
- **持仓量异动检测**：监控合约持仓量的异常变化
- **实时提醒**：持仓量增长超过阈值时立即通知
- **历史数据分析**：支持历史持仓量趋势分析

### 🔍 交易量异常监控
- **庄神指标**：检测成交量异常放大的标的
- **强势标的识别**：成交量连续3倍以上增长
- **价格配合分析**：结合价格走势判断有效性

### 🤖 机器学习增强 (新功能)
- **智能信号预测**：使用随机森林、梯度提升等算法预测交易信号
- **异常检测算法**：基于孤立森林等算法检测价格、成交量、模式异常
- **自适应参数优化**：自动优化SuperTrend、成交量等策略参数
- **特征工程**：提取技术指标、价格模式、成交量特征等
- **模型管理**：支持模型训练、保存、加载和性能评估

### 📢 多渠道通知推送
- **飞书机器人**：支持飞书群组消息推送  
- **企业微信**：支持企业微信机器人推送
- **Telegram**：支持Telegram Bot推送
- **邮件通知**：支持SMTP邮件通知

## 🛠 技术架构

- **Web框架**：FastAPI + Uvicorn
- **数据处理**：Pandas + NumPy + TA-Lib
- **机器学习**：Scikit-learn + Joblib (免费开源)
- **交易所API**：python-binance + CCXT
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

服务启动后访问：
- API文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## ⚙️ 环境配置详解

### 币安API配置（必需）
```env
# 在币安获取API密钥
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
ML_CONFIG__ENABLE_ADAPTIVE_OPTIMIZATION=true

# 预测模型配置
ML_CONFIG__PREDICTION_MODEL__MODEL_TYPE=random_forest
ML_CONFIG__PREDICTION_MODEL__MIN_ACCURACY_THRESHOLD=0.6

# 异常检测配置
ML_CONFIG__ANOMALY_DETECTION__ALGORITHM=isolation_forest
ML_CONFIG__ANOMALY_DETECTION__CONTAMINATION=0.1

# 监控币种 (已移除BNB和ADA，添加SOL)
MONITORED_SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT","XRPUSDT"]
```

### 监控参数配置（可选调整）
```env
# 持仓量变化阈值 (1.05表示5%增长触发提醒)
OPEN_INTEREST_THRESHOLD=1.05

# 成交量异常倍数
VOLUME_MULTIPLIER=3.0

# 各种监控间隔(分钟)
FUNDING_RATE_INTERVAL=240     # 费率监控间隔
TREND_ANALYSIS_INTERVAL=15    # 趋势分析间隔  
OPEN_INTEREST_INTERVAL=5      # 持仓量监控间隔
VOLUME_MONITOR_INTERVAL=60    # 交易量监控间隔
```

## 📡 API接口

### 趋势分析
```bash
# 单个标的趋势分析
GET /api/trend/analyze/{symbol}

# 批量趋势分析
POST /api/trend/batch-analyze
{
  "symbols": ["BTCUSDT", "ETHUSDT"]
}

# 历史信号分析
GET /api/trend/historical/{symbol}?days=30
```

### 监控服务
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

### 机器学习增强API
```bash
# ML信号预测
POST /api/ml/predict
{
  "symbol": "BTCUSDT",
  "include_features": true
}

# 异常检测
POST /api/ml/anomaly-detection
{
  "symbol": "ETHUSDT",
  "detection_types": ["volume_anomaly", "price_anomaly"]
}

# 参数优化
POST /api/ml/optimize
{
  "symbol": "SOLUSDT",
  "optimization_type": "all"
}

# 批量ML分析
POST /api/ml/batch-analysis
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
  "include_prediction": true,
  "include_anomaly_detection": true
}

# 模型状态
GET /api/ml/model-status/{symbol}

# ML配置
GET /api/ml/config
```

### 通知服务
```bash
# 发送测试通知
POST /api/notification/test
{
  "channel": "feishu",
  "message": "测试消息"
}

# 获取通知历史
GET /api/notification/history?limit=100
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


## 🤖 机器学习增强功能详解

### 信号预测模型
- **算法选择**：随机森林、梯度提升、SVM等免费算法
- **特征工程**：技术指标、价格模式、成交量特征、市场微观结构
- **预测信号**：强烈买入、买入、持有、卖出、强烈卖出
- **置信度评估**：模型输出概率分布和置信度分数
- **模型管理**：自动训练、保存、加载和性能评估

### 异常检测算法
- **价格异常**：基于孤立森林检测异常价格波动
- **成交量异常**：统计方法检测成交量异常放大
- **模式异常**：检测波动率、相关性等模式异常
- **市场异常**：综合多维度检测市场异常状态

### 自适应参数优化
- **SuperTrend优化**：自动优化周期和倍数参数
- **成交量阈值优化**：基于历史数据优化异常检测阈值
- **性能评估**：使用夏普比率等指标评估参数性能
- **动态调整**：根据市场变化自动调整参数

### ML增强监控
- **智能警报**：结合传统指标和ML预测生成增强警报
- **风险评估**：综合多个维度评估交易风险
- **置信度融合**：融合多种信号源的置信度
- **自适应阈值**：根据模型性能动态调整警报阈值

## 📁 项目结构

```
transaction_push/
├── app/                    # 应用主目录
│   ├── api/               # API路由
│   │   └── ml_enhanced.py # ML增强API
│   ├── core/              # 核心配置
│   ├── models/            # 数据模型
│   │   └── ml_models.py   # ML相关模型
│   ├── services/          # 业务逻辑
│   │   ├── ml_enhanced_service.py           # ML增强服务
│   │   └── ml_enhanced_monitor_service.py   # ML增强监控
│   ├── utils/             # 工具函数
│   └── schemas/           # Pydantic模型
│       └── ml_schemas.py  # ML相关Schema
├── models/                # ML模型存储目录
├── examples/              # 使用示例
│   └── ml_enhanced_usage.py # ML功能示例
├── scripts/               # 脚本文件
├── logs/                  # 日志目录
├── requirements.txt       # 依赖列表 (已添加scikit-learn)
├── env.example           # 环境变量示例
└── main.py               # 启动文件
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

**4. ML模型相关问题**
- 首次使用需要训练模型，可能需要较长时间
- 确保有足够的历史数据用于训练
- 检查模型文件是否正确保存在models/目录
- 模型准确率低于阈值时会有警告日志

**5. 查看日志**
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