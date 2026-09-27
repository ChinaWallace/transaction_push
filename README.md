> 代码克隆、NFI子模块及本地数据说明见 [仓库使用说明](docs/quant_repository.md)。历史逐笔明细与行情文件保留在本机，不随Git上传。

> **三币与16币扩展研究（v12）**：42组同资金比较完成，当前历史首选为三币长期底仓＋4h慢退出增强；2026完整72.06%收益/36.07%回撤，2025全年374.68%/43.30%。新增UNI、SOL等13币已进研究池，全买未带来更高收益。`./scripts/quant.sh expanded-data` 准备公开数据，`expanded` 校验/运行冻结回放，`start --research-only` 查看结果。见 [首选方案、完整对照与边界](docs/quant_expanded_core_research.md)。未开启实盘或恢复旧模拟。

> **底仓保留＋趋势增强（v11）**：60组回放完成，历史候选为40%慢退出增强；2026完整区间72.28%收益/36.02%回撤，2025全年376.09%/43.30%，仍需新行情验证。`./scripts/quant.sh start --research-only` 打开只读研究看板；`overlay` 核验冻结回放。规则、亏损月份和执行压力见 [底仓增强研究](docs/quant_core_overlay_research.md)。没有替换旧模拟策略或开启实盘。

> **持有、浮盈加仓与2x对照（v7–v10）**：同资金持有基准、慢退出、浮盈加仓、逐仓与全仓独立比较；看板“持有与主动策略对照”可查看逐笔。命令 `holding` / `growth` / `leverage` / `cross`；说明见 [持有与加仓研究](docs/quant_holding_research.md)。

> **新增三币策略研究（v6）**：`./scripts/quant.sh start-all` 一次启动原模拟看板和三个独立虚拟账户；`forward-status` 查看新行情状态，`stop-all` 停止全部。20种止损版本、88组回测及逐笔明细见 [止损优化与持续模拟](docs/quant_stop_research.md)。保留 M4Structure / A1Fixed / D55ClosedTrail；仅模拟，原优选长期仓规则不变。

> **当前合约模拟入口（v4）**：`./scripts/quant.sh setup` 后运行 `./scripts/quant.sh start`。统一读取项目 `.env`（代理、Binance、QUANT_*），4h选币 / 1h确认 / 15m执行。`status` / `config` / `logs` / `restart` / `stop` / `backtest` 使用同一个脚本。看板：http://127.0.0.1:8891/api/quant/dashboard 。详细生命周期、策略和验证边界见 [合约服务文档](docs/quant_contracts.md#v4统一配置与多周期服务2026-09-25)。当前仅模拟，Binance HTTP451会明确报告并停止行情处理。

## 全池合约策略 v3.2（2026-09-24）

当前主研究入口已改为币安 USDT 永续全池，覆盖币种和股票等 TradFi 合约。动态评分 → 入场区间 → 组合风险预算 → 真实资金费 → 退出 → SQLite 模拟账户 → 合约回放；最多 3 倍杠杆，45% 回撤触发暂停。当前仅研究/模拟，实盘关闭。

- [运行说明与验证边界](docs/quant_contracts.md)
- [本轮研究结论](reports/quant_v3/review.md)
- 排名：`python3 scripts/quant_portfolio.py scan`
- 一键启动采集、自动模拟与看板：`./scripts/quant.sh start`（首次 `./scripts/quant.sh setup`）
- 管理：`./scripts/quant.sh status` / `logs` / `stop` / `restart`
- 看板：http://127.0.0.1:8891/api/quant/dashboard；日线策略、每分钟观察、最多10个目标，显示每笔入场/退出及等待原因。
- [策略与数据来源](docs/quant_sources.md)

下方 v2 现货功能作为历史版本保留。

## 选币、买卖与组合验证 v2（2026-09）

Binance现货动态选币 → 突破/回踩/中继入场 → 盈利加仓 → 部分止盈与退出 → 持久化模拟盘 → 跨年份组合回归，默认 `active` 档位。评分不是胜率，历史结果尚未证明收益优势。

- 最新可执行建议：`python3 scripts/market_advisory.py scan`
- 模拟盘：`python3 scripts/market_advisory.py paper --horizon short_term`
- 回归：`python3 scripts/market_advisory.py regression --input reports/advisory/v2_data/snapshot.json`

[使用说明](docs/market_advisory.md) · [24组回归验收](reports/advisory/v2_regression.md) · [最新扫描](reports/advisory/v2_live/latest.md)。核心汇总已接新报告；旧兼容回测占位实现明确报错，不返回虚假完成结果。

# 🚀 Python 智能量化交易分析工具 v1.2.0

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AI Powered](https://img.shields.io/badge/AI-Kronos%20Powered-purple.svg)](https://github.com/NeoQuasar/Kronos)

基于Python的**智能量化交易分析工具 v1.2.0**，完整支持Binance期货交易所，集成Kronos AI预测模型、技术分析和机器学习算法，专为加密货币市场设计的交易决策系统。

## 🆕 v1.2.0 更新内容

- ✅ **完整适配Binance期货API** - 全面支持币安期货交易所

## ✨ 核心特性

- **🧠 Kronos AI 预测** - 基于 Transformer 的金融预测模型
- **📊 多维度分析** - 技术分析 + 机器学习 + AI 预测
- **🔄 实时监控** - 负费率、异常波动、持仓量监控、Tradingview强势币推送
- **📱 智能通知** - 飞书、企业微信多渠道推送
- **⚡ 高性能架构** - FastAPI + 异步处理
- **🎯 策略回测** - 完整的策略验证和优化

## 🚀 快速开始

### 📋 环境要求

- Python 3.11+
- MySQL 8.0+
- 4GB+ 内存 (推荐 16GB)

### 🔧 安装配置

1. **克隆项目**
```bash
git clone https://github.com/ChinaWallace/transaction_push.git
cd transaction_push
```

2. **安装依赖**
```bash
# 1. 升级pip
python -m pip install --upgrade pip

# 2. 安装TA-Lib技术指标库
# Windows (推荐使用预编译版本):
pip install --find-links https://github.com/cgohlke/talib-build/releases/download/v0.4.28/ TA-Lib

# Linux/Ubuntu:
sudo apt-get install libta-lib-dev && pip install TA-Lib

# macOS:
brew install ta-lib && pip install TA-Lib

# 3. 安装其他Python依赖
pip install -r requirements.txt

# 4. 下载Kronos AI模型
python scripts/download_kronos_models.py
```

3. **配置环境变量**
```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
# 必须配置: 交易所 API、数据库连接、通知 Webhook
```

4. **启动服务**
```bash
python main.py
```

### 🎛️ 核心配置

```env
# 🔑 交易所API配置 (选择一个)
# 币安期货交易所 (推荐 - v1.2.0完整适配)
BINANCE_API_KEY=your_binance_api_key
BINANCE_SECRET_KEY=your_binance_secret_key
BINANCE_BASE_URL=https://fapi.binance.com
EXCHANGE_PROVIDER=binance

# 💾 数据库配置
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/trading_db

# 📢 通知配置（至少选择一个）
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook_key
# 或
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key

# 🤖 Kronos AI配置
KRONOS_CONFIG__ENABLE_KRONOS_PREDICTION=true
KRONOS_CONFIG__USE_GPU=false

# 📊 监控币种配置
MONITORED_SYMBOLS=["BTC-USDT-SWAP","ETH-USDT-SWAP","SOL-USDT-SWAP"]
```

### 🗄️ 数据库初始化

```bash
# 1. 确保MySQL服务运行
# Windows: net start mysql
# Linux: sudo systemctl start mysql

# 2. 创建数据库（如果不存在）
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS trading_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 3. 初始化数据库表结构
python scripts/init_db.py

# 4. 验证数据库连接
python -c "from app.core.database import db_manager; print('✅ 数据库连接成功' if db_manager.health_check() else '❌ 数据库连接失败')"
```

**🔧 数据库配置说明**
```env
# 标准MySQL配置
DATABASE_URL=mysql+pymysql://用户名:密码@localhost:3306/trading_db

# 示例配置
DATABASE_URL=mysql+pymysql://root:your_password@localhost:3306/trading_db

# 如果使用默认端口和本地连接
DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/trading_db
```

**⚙️ 配置验证**
```bash
# 验证配置文件
python -c "
from app.core.config import get_settings
try:
    settings = get_settings()
    print('✅ 配置文件加载成功')
    print(f'交易所: {settings.exchange_provider}')
    print(f'数据库: 已配置')
    print(f'通知: 已配置' if hasattr(settings, 'feishu_webhook_url') and settings.feishu_webhook_url else '未配置')
except Exception as e:
    print(f'❌ 配置文件错误: {e}')
"

# 测试API连接
python -c "
import asyncio
from app.services.exchanges.exchange_service_manager import get_exchange_service
async def test():
    try:
        service = await get_exchange_service()
        health = await service.health_check()
        print('✅ 交易所API连接成功' if health.get('overall_status') == 'healthy' else '❌ API连接失败')
    except Exception as e:
        print(f'❌ API连接失败: {e}')
asyncio.run(test())
"
```

### 🎯 启动服务

**🖥️ 开发模式（推荐新手）**
```bash
python main.py
```

**🚀 后台运行模式**
```bash
# Windows - 双击运行
start_service.bat

# 或使用命令行
python scripts/daemon_runner.py start
```

**🔧 Windows服务模式（可选）**
```bash
# 以管理员身份运行
scripts\install_service.bat

# 启动服务
net start TradingToolService
```

### ✅ 验证安装

**1. 检查服务状态**
```bash
# 运行状态检查脚本
python scripts/check_status.py

# 或手动检查API
curl http://localhost:8888/health
```

**2. 访问Web界面**
- **🌐 API文档**: http://localhost:8888/docs
- **❤️ 健康检查**: http://localhost:8888/health  
- **📊 服务统计**: http://localhost:8888/api/unified-data/service-stats

**3. 预期健康检查输出**
```json
{
  "status": "healthy",
  "services": {
    "database": "connected",
    "kronos_ai": "loaded",
    "scheduler": "running",
    "exchange_service": "connected"
  },
  "timestamp": "2025-01-01T12:00:00Z"
}
```



## 📡 API接口文档

### 🎯 核心交易API

**综合交易决策**
```http
POST /api/core-trading/analyze/{symbol}
# Kronos + 技术分析 + ML融合分析

GET /api/core-trading/signals  
# 获取所有交易信号

POST /api/core-trading/batch-analyze
{
  "symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
  "analysis_type": "integrated"
}

# 获取交易信号
GET /api/core-trading/signals/BTC-USDT-SWAP
```

### 📈 监控接口
```bash
# 负费率监控
GET /api/monitoring/funding-rates

# 异常检测
GET /api/monitoring/anomalies

# 系统健康检查
GET /health
```

## 🏗️ 项目架构

```
app/
├── api/                    # FastAPI 路由层
├── core/                   # 核心配置和基础设施
├── services/               # 业务逻辑层
│   ├── trading/           # 交易决策服务
│   ├── ml/                # AI/ML 服务
│   ├── monitoring/        # 监控服务
│   ├── notification/      # 通知服务
│   └── exchanges/         # 交易所接口
├── models/                # 数据模型
├── schemas/               # API 数据验证
└── utils/                 # 工具函数
```

## 🤖 AI 模型说明

### Kronos AI 预测
- **模型**: NeoQuasar/Kronos-Tokenizer-base
- **功能**: 基于历史数据预测价格趋势
- **置信度**: 0-1 评分系统
- **支持**: CPU/GPU 加速

### 机器学习增强
- **异常检测**: 识别市场异常波动
- **信号验证**: 验证 AI 预测结果
- **自适应优化**: 根据市场条件调整策略

## 📱 通知系统

支持多种通知渠道：
- **飞书机器人** - 实时交易信号推送
- **企业微信** - 重要事件通知
- **邮件通知** - 系统状态报告

## 🔧 开发指南

### 📝 代码规范
- 遵循 PEP 8 代码风格
- 使用类型注解
- 异步优先 (async/await)
- 完整的错误处理

### 🧪 测试
```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/unit/
pytest tests/integration/

# 查看覆盖率
pytest --cov=app
```

### 📊 性能监控
- 内置性能指标收集
- API 响应时间监控
- AI 模型预测延迟跟踪
- 系统资源使用监控

## 🛠️ 故障排除

### 常见问题

**Q: Kronos 模型加载失败**
```bash
# 检查模型文件
ls models/cache/models--NeoQuasar--Kronos-Tokenizer-base/

# 重新下载模型
python -c "from app.services.ml.kronos_service import download_model; download_model()"
```

**Q: 数据库连接失败**
```bash
# 检查数据库配置
python -c "from app.core.config import get_settings; print(get_settings().database_url)"

# 测试连接
python -c "from app.core.database import test_connection; test_connection()"
```

**Q: API 调用超时**
- 检查网络连接
- 验证 API 密钥配置
- 查看日志文件 `logs/app.log`

## 📈 性能优化

### 资源配置建议

| 环境 | CPU | 内存 | GPU | 并发数 |
|------|-----|------|-----|--------|
| 开发 | 4核+ | 8GB+ | 可选 | 2-4 |
| 生产 | 8核+ | 16GB+ | 推荐 | 8-16 |

### 优化配置
```env
# 高性能配置
KRONOS_CONFIG__USE_GPU=true
CACHE_CONFIG__MAX_CACHE_SIZE_MB=200
SERVICE_CONFIG__MAX_CONCURRENT_REQUESTS=16
```

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献指南

- 🐛 **发现Bug** - 提交Issue报告问题
- 💡 **功能建议** - 提出新功能想法
- 📝 **文档改进** - 完善文档和示例
- 🔧 **代码贡献** - 提交Pull

---

⭐ 如果这个项目对你有帮助，请给个 Star！
