# Python 交易分析工具

一个基于Python的智能量化交易分析工具，集成持仓分析、网格策略、机器学习预测等功能，为交易决策提供全方位支持。

## ✨ 功能亮点

🎯 **启动时自动分析** - 应用启动时自动分析账户持仓并推送风险提醒  
📊 **智能持仓评分** - 100分制评估持仓健康度，提供具体操作建议  
🎲 **网格机会发现** - 自动扫描13个品种，发现高收益网格交易机会  
🤖 **ML信号预测** - 专注ETH和SOL预测，避免BTC的高波动干扰  
⏰ **定期智能推送** - 每2-6小时自动分析，只推送重要发现  
🔔 **多渠道通知** - 支持飞书、微信、Telegram等多种推送方式

## 🚀 主要功能

### 🤖 统一交易决策系统 (NEW! 核心升级)
- **智能决策融合**：传统技术分析(60%) + 机器学习预测(40%)
- **动态止盈止损**：基于ATR和置信度的自适应计算，风险收益比1:2.5-1:4
- **全面中文化**：强烈买入、买入、持有、卖出、强烈卖出等中文信号
- **30+币种支持**：BTC、ETH、SOL、ADA、DOT、AVAX、LINK、UNI等全覆盖
- **综合决策推送**：不再单独推送传统和ML信号，融合后统一推送高质量建议
- **智能仓位管理**：根据置信度和波动性动态调整仓位大小(5%-25%)
- **风险等级评估**：极低、低、中等、高、极高五级风险分类

### 📊 智能持仓分析 (核心功能)
- **账户概况分析**：总权益、持仓数量、盈亏情况、资金利用率
- **持仓健康度评分**：100分制评估每个持仓的风险状况
- **风险评估系统**：集中度、杠杆、亏损、方向性风险全面评估
- **智能建议生成**：持有、减仓、加仓、平仓、对冲、重新平衡
- **风险警报机制**：自动识别严重亏损、高杠杆、集中度风险
- **定期分析推送**：每2小时自动分析并推送重要风险提醒

### 🎯 网格交易机会分析
- **多品种机会扫描**：分析BTC、ETH、SOL、XRP、OKB等主流币种
- **波动性评估**：基于7天历史数据计算波动率和价格区间
- **网格策略评分**：综合波动性、价格区间、流动性的100分制评分
- **收益预期计算**：预测网格策略的日收益和年化收益率
- **智能推荐排序**：按评分和收益潜力推荐最佳网格机会
- **定期机会更新**：每4小时扫描市场，发现新的网格机会

### 💎 市场交易机会分析
- **币本位合约分析**：趋势判断、波动性分析、资金费率信号
- **现货交易机会**：价格位置分析、技术指标、成交量变化
- **市场情绪评估**：综合多维度数据判断市场整体情绪
- **交易建议生成**：针对不同品种提供具体的交易策略建议
- **定期市场扫描**：每6小时分析市场机会并推送重要发现

### 📈 趋势分析
- **多周期SuperTrend指标分析**：支持日线、4小时、1小时、15分钟多时间周期
- **智能信号识别**：实现10种信号组合判断
- **分级通知推送**：根据信号强度提供不同级别的通知

### � 器资金费率监控
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

### 🤖 机器学习增强
- **智能信号预测**：只预测ETH和SOL，使用随机森林等算法
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
- **交易所API**：OKX API + python-binance (主要使用OKX)
- **任务调度**：APScheduler (支持多种定时任务)
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
ML_CONFIG__ENABLE_ADAPTIVE_OPTIMIZATION=true

# 预测模型配置
ML_CONFIG__PREDICTION_MODEL__MODEL_TYPE=random_forest
ML_CONFIG__PREDICTION_MODEL__MIN_ACCURACY_THRESHOLD=0.6

# 异常检测配置
ML_CONFIG__ANOMALY_DETECTION__ALGORITHM=isolation_forest
ML_CONFIG__ANOMALY_DETECTION__CONTAMINATION=0.1

# 监控币种 (只预测ETH和SOL)
MONITORED_SYMBOLS=["ETH-USDT-SWAP", "SOL-USDT-SWAP"]
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

# 新增分析任务间隔
POSITION_ANALYSIS_INTERVAL=120    # 持仓分析间隔(分钟)
GRID_OPPORTUNITIES_INTERVAL=240   # 网格机会分析间隔(分钟)
MARKET_OPPORTUNITIES_INTERVAL=360 # 市场机会分析间隔(分钟)
```

## 📡 API接口

### 持仓分析API
```bash
# 获取账户持仓分析
GET /api/trading/account-analysis

# 获取交易建议
GET /api/trading/advice/{symbol}

# 获取市场分析
GET /api/trading/market-analysis/{symbol}

# 策略对比分析
GET /api/trading/strategy-comparison/{symbol}
```

### 趋势分析
```bash
# 单个标的趋势分析
GET /api/trend/analyze/{symbol}

# 批量趋势分析
POST /api/trend/batch-analyze
{
  "symbols": ["ETH-USDT-SWAP", "SOL-USDT-SWAP"]
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
# ML信号预测 (仅支持ETH和SOL)
POST /api/ml/predict
{
  "symbol": "ETH-USDT-SWAP",
  "include_features": true
}

# 异常检测
POST /api/ml/anomaly-detection
{
  "symbol": "SOL-USDT-SWAP",
  "detection_types": ["volume_anomaly", "price_anomaly"]
}

# 参数优化
POST /api/ml/optimize
{
  "symbol": "ETH-USDT-SWAP",
  "optimization_type": "all"
}

# 批量ML分析
POST /api/ml/batch-analysis
{
  "symbols": ["ETH-USDT-SWAP", "SOL-USDT-SWAP"],
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
- **HEDGE**：逆势持仓，建议对冲
- **REBALANCE**：投资组合需要重新平衡

## 🎯 网格交易机会分析

### 评分体系 (100分制)
- **波动性评分** (60%)：波动率>5%得60分，3-5%得40分，2-3%得20分
- **价格区间评分** (30%)：区间>15%得30分，10-15%得20分，5-10%得10分
- **流动性评分** (10%)：BTC/ETH得10分，SOL/XRP得5分

### 机会发现
- **强烈推荐** (≥80分)：如OKB现货，波动率29.6%，预期年化489%
- **推荐** (60-79分)：如ETH合约，波动率3.9%，预期年化378%
- **谨慎考虑** (40-59分)：中等机会，需要仔细评估
- **不推荐** (<40分)：波动性不足，不适合网格策略

### 收益预期计算
- **网格数量**：根据价格区间自动计算最优网格数(10-30个)
- **交易频率**：基于波动率预测每日交易次数
- **单次收益**：按0.2%的网格利润计算
- **年化收益**：综合考虑交易频率和单次收益

## 🤖 机器学习增强功能详解

### 信号预测模型 (仅ETH和SOL)
- **算法选择**：随机森林、梯度提升等免费算法
- **特征工程**：技术指标、价格模式、成交量特征
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

## 📁 项目结构

```
transaction_push/
├── app/                    # 应用主目录
│   ├── api/               # API路由
│   │   ├── trading_decision.py      # 交易决策API
│   │   └── ml_enhanced.py          # ML增强API
│   ├── core/              # 核心配置
│   │   ├── config.py      # 应用配置
│   │   └── logging.py     # 日志配置
│   ├── models/            # 数据模型
│   ├── services/          # 业务逻辑
│   │   ├── position_analysis_service.py     # 持仓分析服务
│   │   ├── okx_service.py                   # OKX交易所服务
│   │   ├── ml_enhanced_service.py           # ML增强服务
│   │   ├── scheduler_service.py             # 任务调度服务
│   │   └── startup_trading_service.py       # 启动交易服务
│   ├── utils/             # 工具函数
│   └── schemas/           # Pydantic模型
├── models/                # ML模型存储目录
├── scripts/               # 脚本文件
├── logs/                  # 日志目录
├── requirements.txt       # 依赖列表
├── env.example           # 环境变量示例
├── .env                  # 环境变量配置
└── main.py               # 启动文件
```

## 📈 实际使用效果

### 持仓分析示例
```
✅ 持仓分析完成 (评分: 55/100)
📊 账户概况:
   总权益: $8,234.55 USDT
   持仓数量: 3 个
   未实现盈亏: $-221.65 USDT (-2.7%)
   资金利用率: 7.7%
   整体杠杆: 0.1x

⚠️ 风险评估:
   风险等级: low
   风险评分: 15/100
   集中度风险: 3.5%

🚨 风险警报 (2 个):
   • ETH-USD-SWAP: 严重亏损 46.1%
   • SOON-USDT-SWAP: 严重亏损 218.1%

💡 主要建议:
   • 持仓平衡建议: 持仓方向过于单一，缺乏对冲
```

### 网格机会分析示例
```
🏆 推荐网格机会:
   1. OKB (现货)
      推荐度: 强烈推荐 (评分: 90/100)
      波动率: 29.6%
      预期年化收益: 489.0%
   
   2. ETH (U本位永续)
      推荐度: 强烈推荐 (评分: 80/100)
      波动率: 3.9%
      预期年化收益: 378.8%
```

### 市场分析示例
```
🪙 币本位合约机会:
   • ETH: 上涨 (波动率: 4.3%) - 适合做多，可考虑网格策略
   • SOL: 上涨 (波动率: 4.6%) - 适合做多，可考虑网格策略

💰 现货交易机会:
   • BTC: 价格位置 38.7% (震荡) - 适合网格交易
   • ETH: 价格位置 100.0% (上涨趋势) - 高位风险，建议减仓

📈 市场情绪: 偏乐观
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

**5. ML模型相关问题**
- 首次使用需要训练模型，可能需要较长时间
- 确保有足够的历史数据用于训练
- 检查模型文件是否正确保存在models/目录
- 模型准确率低于阈值时会有警告日志

**6. 持仓分析问题**
- 确保OKX账户有持仓数据
- 检查账户API权限是否包含持仓查询
- 持仓分析需要一定的计算时间，请耐心等待

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