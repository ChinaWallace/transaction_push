# 统一交易决策系统使用指南

## 🎯 系统概述

统一交易决策系统是一个融合传统技术分析和机器学习的综合交易决策平台，支持30+主流数字货币交易对，提供中文化的智能交易建议。

## ✨ 核心特性

### 1. 🤖 智能决策融合
- **传统技术分析**: SuperTrend多周期分析
- **机器学习预测**: 梯度提升模型 + 异常检测
- **综合权重决策**: 60%传统 + 40%ML（可配置）

### 2. 📊 动态止盈止损
- **ATR自适应**: 根据市场波动性动态调整
- **置信度调节**: 高置信度信号使用更宽止损
- **风险收益比**: 智能计算1:2.5到1:4的收益比

### 3. 🌍 全面中文化
- **信号描述**: 强烈买入、买入、持有、卖出、强烈卖出、等待
- **风险等级**: 极低风险、低风险、中等风险、高风险、极高风险
- **市场状态**: 上涨趋势、下跌趋势、震荡整理、高波动、平静

### 4. 🎯 支持币种扩展
支持30+主流币种，包括：
- **主流币**: BTC, ETH, BNB
- **Layer1**: SOL, ADA, DOT, AVAX, ATOM, NEAR
- **DeFi**: LINK, UNI, AAVE, SUSHI, CRV
- **Layer2**: MATIC, OP, ARB
- **热门币**: DOGE, SHIB, APT, SUI

## 🚀 API接口

### 1. 单个交易对分析
```http
POST /api/unified/recommendation
Content-Type: application/json

{
    "symbol": "ETH-USDT-SWAP",
    "send_notification": false
}
```

**响应示例**:
```json
{
    "status": "success",
    "symbol": "ETH-USDT-SWAP",
    "final_action": "买入",
    "confidence": 78.5,
    "traditional_signal": "买入",
    "traditional_confidence": 75.0,
    "ml_signal": "强烈买入",
    "ml_confidence": 82.0,
    "market_regime": "震荡整理",
    "volatility_level": "中等",
    "dynamic_stop_loss": 2180.50,
    "dynamic_take_profit": 2350.75,
    "risk_reward_ratio": 3.2,
    "position_size_percent": 12.5,
    "leverage": 2.1,
    "risk_level": "中等风险",
    "current_price": 2250.00,
    "entry_price": 2250.00,
    "reasoning": "技术分析: 买入 (75.0%) | 机器学习: 强烈买入 (82.0%) | 综合决策: 买入 (置信度: 78.5%)",
    "key_factors": [
        "技术形态: 短线反弹",
        "波动性: 中等"
    ],
    "entry_timing": "尽快执行",
    "hold_duration_hours": 12,
    "timestamp": "2025-08-24T12:00:00"
}
```

### 2. 批量分析
```http
POST /api/unified/batch-analysis
Content-Type: application/json

{
    "symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"],
    "send_notifications": false
}
```

### 3. 市场概览
```http
GET /api/unified/market-overview
```

### 4. 交易对比较
```http
GET /api/unified/symbol-comparison?symbols=BTC-USDT-SWAP&symbols=ETH-USDT-SWAP
```

## 📈 决策逻辑

### 1. 信号融合算法
```python
# 信号权重
traditional_weight = 0.6  # 传统分析60%
ml_weight = 0.4          # 机器学习40%

# 信号数值映射
signal_values = {
    '强烈买入': 2.0,
    '买入': 1.0,
    '持有': 0.0,
    '卖出': -1.0,
    '强烈卖出': -2.0,
    '等待': 0.0
}

# 加权平均
combined_value = (traditional_value * traditional_weight + 
                 ml_value * ml_weight)

# 最终决策
if combined_value >= 1.5: return "强烈买入"
elif combined_value >= 0.5: return "买入"
elif combined_value <= -1.5: return "强烈卖出"
elif combined_value <= -0.5: return "卖出"
else: return "持有" or "等待"
```

### 2. 动态止损计算
```python
# 基础止损：ATR的1.5倍，最小2%
base_stop_loss = max(0.02, atr_percent * 1.5)

# 置信度调整：0.7-1.3倍
confidence_multiplier = 0.7 + (confidence / 100) * 0.6

# 波动性调整
if volatility == '高': multiplier = 1.3
elif volatility == '低': multiplier = 0.8
else: multiplier = 1.0

# 最终止损
dynamic_stop_loss = base_stop_loss * confidence_multiplier * volatility_multiplier
```

### 3. 仓位计算
```python
# 基础仓位10%
base_size = 10.0

# 置信度调整
confidence_multiplier = confidence / 100.0

# 波动性调整
if volatility == '高': volatility_multiplier = 0.6
elif volatility == '低': volatility_multiplier = 1.3
else: volatility_multiplier = 1.0

# 最终仓位（最大25%）
position_size = min(base_size * confidence_multiplier * volatility_multiplier, 25.0)
```

## 🔧 配置说明

### 1. 监控币种配置
在 `app/core/config.py` 中配置：
```python
monitored_symbols: List[str] = [
    # 主流币种
    'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'BNB-USDT-SWAP',
    # Layer1 公链
    'SOL-USDT-SWAP', 'ADA-USDT-SWAP', 'DOT-USDT-SWAP',
    # ... 更多币种
]
```

### 2. ML配置
```python
ml_config = {
    'enable_ml_prediction': True,
    'enable_anomaly_detection': True,
    'prediction_model': {
        'model_type': 'gradient_boosting',
        'lookback_periods': 30,
        'prediction_horizon': 3,
        'retrain_interval_hours': 12,
        'min_accuracy_threshold': 0.65
    }
}
```

### 3. 风险管理配置
```python
# 最大仓位25%
max_position_percent = 25.0

# 最大杠杆3倍
max_leverage = 3.0

# 基础止损3%
base_stop_loss = 0.03

# 基础止盈9% (1:3风险收益比)
base_take_profit = 0.09
```

## 📊 通知功能

### 1. 统一交易通知
系统会发送包含以下信息的通知：
- 🎯 综合交易建议
- 📊 置信度评分
- 💰 当前价格
- 🛑 动态止损价格
- 🎯 动态止盈价格
- 📈 建议仓位百分比
- ⚠️ 风险等级评估
- 💡 决策依据说明

### 2. 通知触发条件
- 置信度 > 65%
- 强信号（强烈买入/卖出）
- 高风险警报
- 异常检测警报

## 🧪 测试使用

### 1. 运行测试脚本
```bash
python test_unified_trading.py
```

### 2. API测试
```bash
# 启动服务
python main.py

# 测试单个交易对
curl -X POST "http://localhost:8000/api/unified/recommendation" \
     -H "Content-Type: application/json" \
     -d '{"symbol": "ETH-USDT-SWAP", "send_notification": false}'

# 测试市场概览
curl "http://localhost:8000/api/unified/market-overview"
```

## ⚠️ 风险提示

1. **仅供参考**: 所有交易建议仅供参考，不构成投资建议
2. **风险管理**: 请严格执行止损，控制仓位大小
3. **市场风险**: 数字货币市场波动巨大，请谨慎投资
4. **技术风险**: 模型预测存在不确定性，请结合多方信息判断
5. **资金安全**: 请使用闲余资金，不要借贷投资

## 🔄 更新日志

### v2.0.0 (2025-08-24)
- ✅ 新增统一交易决策系统
- ✅ 支持30+主流币种
- ✅ 动态止盈止损计算
- ✅ 全面中文化界面
- ✅ ML模型扩展到所有交易对
- ✅ 综合决策推送功能

### 下一步计划
- 🔄 增加更多技术指标
- 🔄 优化ML模型准确率
- 🔄 添加回测功能
- 🔄 支持自定义策略参数
- 🔄 增加移动端推送