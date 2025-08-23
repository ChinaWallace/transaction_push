# 综合交易策略使用指南

## 概述

综合交易策略系统整合了传统技术分析、机器学习预测、风险管理和自动通知功能，为交易者提供全面的决策支持。

## 核心功能

### 1. 交易决策服务 (`/api/trading`)

#### 获取单个交易对建议
```bash
POST /api/trading/recommendation
{
    "symbol": "BTCUSDT",
    "account_balance": 10000,
    "current_positions": {"ETHUSDT": 2000},
    "send_notification": true
}
```

**响应示例：**
```json
{
    "status": "success",
    "symbol": "BTCUSDT",
    "action": "strong_buy",
    "confidence": 85.2,
    "position_size_percent": 15.0,
    "leverage": 3.0,
    "stop_loss_percent": 3.5,
    "take_profit_percent": 8.0,
    "risk_level": "medium",
    "reasoning": "技术指标: strong_buy (强度: 82%) | ML预测: buy (置信度: 88%) | 市场状态: trending",
    "support_levels": [42500.0, 41800.0, 41000.0],
    "resistance_levels": [44200.0, 45000.0, 46500.0],
    "entry_timing": "immediate",
    "hold_duration_hours": 72
}
```

#### 市场分析
```bash
POST /api/trading/analysis
{
    "symbol": "ETHUSDT",
    "send_notification": false
}
```

#### 批量分析
```bash
POST /api/trading/batch-analysis
{
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "account_balance": 10000,
    "send_notifications": true
}
```

### 2. 综合交易策略服务 (`/api/comprehensive`)

#### 启动交易会话
```bash
POST /api/comprehensive/session/start
{
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT"],
    "session_config": {
        "auto_analysis": true,
        "analysis_interval_minutes": 30
    }
}
```

#### 综合市场扫描
```bash
POST /api/comprehensive/market-scan
{
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"],
    "account_balance": 10000,
    "send_notifications": true
}
```

**响应包含：**
- 每个交易对的详细分析
- 市场摘要统计
- 顶级交易机会
- 风险警报

#### 投资组合分析
```bash
POST /api/comprehensive/portfolio/analyze
{
    "positions": {
        "BTCUSDT": 3000,
        "ETHUSDT": 2000,
        "BNBUSDT": 1500
    },
    "account_balance": 10000
}
```

**分析内容：**
- 投资组合指标（利用率、集中度、风险评分）
- 单个仓位分析
- 优化建议
- 风险评估

#### 启动实时监控
```bash
POST /api/comprehensive/monitoring/start
{
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "monitoring_config": {
        "interval_minutes": 15,
        "alert_thresholds": {
            "high_volatility_threshold": 85,
            "strong_signal_confidence_threshold": 80
        }
    }
}
```

### 3. 快速分析和市场概览

#### 快速分析
```bash
POST /api/comprehensive/quick-analysis
{
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "analysis_type": "comprehensive",
    "send_notifications": false
}
```

#### 市场概览
```bash
GET /api/comprehensive/market-overview?top_symbols=20
```

## 使用场景

### 场景1：日常交易决策

1. **获取单个交易对建议**
   ```python
   import requests
   
   response = requests.post("http://localhost:8000/api/trading/recommendation", json={
       "symbol": "BTCUSDT",
       "account_balance": 10000,
       "send_notification": True
   })
   
   recommendation = response.json()
   print(f"建议动作: {recommendation['action']}")
   print(f"置信度: {recommendation['confidence']}%")
   ```

2. **检查投资组合风险**
   ```python
   portfolio_response = requests.post("http://localhost:8000/api/comprehensive/portfolio/analyze", json={
       "positions": {"BTCUSDT": 3000, "ETHUSDT": 2000},
       "account_balance": 10000
   })
   
   risk_assessment = portfolio_response.json()["risk_assessment"]
   print(f"整体风险等级: {risk_assessment['risk_level']}")
   ```

### 场景2：市场扫描和机会发现

```python
# 扫描多个交易对寻找机会
scan_response = requests.post("http://localhost:8000/api/comprehensive/market-scan", json={
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"],
    "account_balance": 10000,
    "send_notifications": True
})

market_summary = scan_response.json()["market_summary"]
print(f"强买入信号: {market_summary['strong_buy_signals']}个")
print(f"强卖出信号: {market_summary['strong_sell_signals']}个")

# 查看顶级机会
for opportunity in market_summary["top_opportunities"]:
    print(f"{opportunity['symbol']}: {opportunity['action']} ({opportunity['confidence']}%)")
```

### 场景3：自动化交易会话

```python
# 启动自动化交易会话
session_response = requests.post("http://localhost:8000/api/comprehensive/session/start", json={
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "session_config": {
        "auto_analysis": True,
        "analysis_interval_minutes": 30
    }
})

session_id = session_response.json()["session_id"]
print(f"交易会话已启动: {session_id}")

# 稍后检查会话状态
status_response = requests.get(f"http://localhost:8000/api/comprehensive/session/{session_id}/status")
status = status_response.json()["data"]
print(f"分析次数: {status['total_analyses']}")
print(f"成功率: {status['successful_analyses']}/{status['total_analyses']}")
```

## 通知配置

系统支持多种通知渠道：

### 飞书通知
```bash
# 在.env文件中配置
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook-url
```

### 微信通知
```bash
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-key
```

### Telegram通知
```bash
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

### 邮件通知
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=recipient@gmail.com
```

## 风险管理

### 风险等级说明

- **VERY_LOW**: 风险极低，适合保守投资者
- **LOW**: 风险较低，适合稳健投资者
- **MEDIUM**: 风险适中，适合平衡投资者
- **HIGH**: 风险较高，需要密切监控
- **VERY_HIGH**: 风险极高，建议谨慎操作

### 仓位管理建议

1. **单个交易对最大仓位**: 30%
2. **最大杠杆倍数**: 5倍
3. **现金储备**: 至少保持10%
4. **高风险仓位占比**: 不超过30%

### 止损止盈设置

- **基础止损**: 2%
- **基础止盈**: 6%
- **根据波动性调整**: 高波动性增加止损止盈幅度
- **根据趋势强度调整**: 强趋势扩大止盈空间

## 最佳实践

### 1. 定期监控
- 设置自动化交易会话进行定期分析
- 启用实时监控检测异常情况
- 定期查看投资组合分析报告

### 2. 分散投资
- 不要将所有资金投入单个交易对
- 关注不同类型的加密货币
- 保持适当的现金储备

### 3. 风险控制
- 严格执行止损策略
- 根据风险等级调整仓位大小
- 定期评估和调整投资组合

### 4. 信号确认
- 结合多个时间周期确认信号
- 关注传统技术分析和ML预测的一致性
- 考虑市场整体环境和趋势

## 故障排除

### 常见问题

1. **API调用失败**
   - 检查网络连接
   - 验证API端点和参数
   - 查看服务器日志

2. **通知未收到**
   - 检查通知配置
   - 验证webhook URL或邮件设置
   - 查看通知服务日志

3. **分析结果异常**
   - 检查数据源连接
   - 验证交易对符号格式
   - 查看ML模型状态

### 日志查看
```bash
# 查看应用日志
tail -f logs/app.log

# 查看交易日志
tail -f logs/trading.log

# 查看错误日志
tail -f logs/error.log
```

## 性能优化

### 批量处理
- 使用批量分析API处理多个交易对
- 合理设置并发数量避免过载
- 使用缓存减少重复计算

### 监控频率
- 根据交易策略调整监控间隔
- 高频交易使用较短间隔（5-15分钟）
- 长期投资使用较长间隔（1-4小时）

### 资源管理
- 定期清理历史数据
- 监控内存和CPU使用情况
- 合理配置数据库连接池