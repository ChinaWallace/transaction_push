# 选币、买卖与组合验证 v2

默认 `active` 档位。Binance USDT 现货，短线 4h/1–7 天，长线日线/1–3 个月。这里的长线是趋势持有，尚不包含完整的项目估值、解锁和基本面打分。

## 已打通的链路

1. **选币**：实时成交额前60名加自选，过滤不可交易、稳定币、价差、历史长度与持续成交额。评分由趋势、相对 BTC 强度、动量、持续性及回撤组成，不是上涨概率。ZEC 没有专门加分。
2. **买入**：突破、EMA20回踩确认、趋势中继三条独立入口。中继先用半份风险预算试仓；去掉旧版“必须同时过多重入口”的漏单结构。价格离开区间、信号过期或数据缺失仍不能入场。
3. **配仓**：同一个周期内所有币共用现金。主动档每次初始风险预算0.75%，中继0.375%；单币20%、组合60%、最多4币、组合到止损的风险3%上限。按实际成交价与止损距离计算数量，并受上一根成交额0.1%的容量约束。限额在新增成交时检查，市场变动和跳空可能导致超过限额。
4. **加仓**：初始持仓浮盈至少1R、仍有有效买入信号、未到第一次止盈且未加过仓，最多加一次。亏损不补仓，原持仓计时不重置，止损不下移。
5. **卖出**：硬止损优先；短线目标1.5R、长线2R先卖三分之一，余仓按已收盘高点减ATR跟踪，止盈后逐步保本。另有趋势退出、排名轮换、42根4h/90根日线的时间退出。R目标不是价格预测。
6. **组合控制**：止损后冷却3根；收盘权益从风险峰值回撤15%后暂停开仓7天，持仓仍执行退出。这是开仓暂停线，不是最大亏损保证。
7. **模拟盘**：SQLite保存现金、持仓、成交、费用、权益、信号与原始报告；重复信号不重复买，重启保留持仓。实际观察到的 ask 买入、bid 卖出，再扣滑点与手续费。全市场扫描失败时仍单独查持仓报价处理退出；持仓也缺价时标明权益不完整并冻结新增。
8. **回归**：信号只读此前已收盘K线，次根开盘成交；同根止损与止盈同时触发按止损优先，跳空按更差开盘价。手续费与滑点覆盖所有买卖和期末清仓。实时和回归共用规则及组合状态机。

`balanced` 每笔风险0.5%、单币15%、总仓45%、总止损风险2%；`legacy` 保留旧入口用于对照。长短线是两个独立研究账户，仓位不能直接叠加成一个真实账户。

## 运行入口

CLI只需Python 3.11+标准库，不读取交易密钥，不提交订单。仓库现有 `.venv` 是Windows环境，Mac应使用可用的Python环境。

```bash
# 即时建议，包含当前可买候选、入场、止损、分批止盈、加仓和退出条件
python3 scripts/market_advisory.py scan --profile active --watch ZEC

# 组合回测与24组固定回归：3档 × 2周期 × 3年段，加成本/去ZEC测试
python3 scripts/market_advisory.py portfolio --input reports/advisory/v2_data/snapshot.json --horizon long_term
python3 scripts/market_advisory.py regression --input reports/advisory/v2_data/snapshot.json

# 推进一次本地模拟盘；后续命令继续同一账本
python3 scripts/market_advisory.py paper --horizon short_term
python3 scripts/market_advisory.py paper-status --horizon short_term

# 本机持续前瞻记录，Ctrl-C结束；只在运行期间观察市场
python3 scripts/market_advisory.py paper --horizon short_term --repeat-seconds 300
```

默认账本 `data/advisory_paper.sqlite3`，可用 `--ledger` 指定独立实验。已有账本不能被新参数覆盖或重置资金；更换策略参数请使用新账本。`--cash` 只对首次建账生效。轮询无法还原两次观察间的实际触发，也不等同于交易所托管止损。

历史下载脚本 `reports/advisory/v2_data/download_snapshot.py` 分页获取公开K线；已有快照约15万根，覆盖2023年至2026-09-24的16币日线/4h。回归开始于2024年以预留特征暖机。

API可独立运行，不启动旧数据库/模型/通知调度：

```bash
python -m uvicorn app.advisory.api:app --host 127.0.0.1 --port 8890
```

- `GET /api/market-advisory/scan?profile=active&watch=ZEC`
- `GET /api/market-advisory/report?profile=active`：Markdown建议。
- `GET /api/market-advisory/paper?profile=active&horizon=short_term`
- `POST /api/market-advisory/paper/step?profile=active&horizon=short_term`：仅允许本机非浏览器客户端，推进模拟账户。若部署反向代理，仍需在代理层限制写接口。

核心汇总任务和手动报告已接新报告，当前可买候选优先展示；不启动应用就不会发送通知。配置 `ADVISORY_ENABLED=true`、`ADVISORY_PROFILE=active`、`ADVISORY_MAX_CANDIDATES=60`、`ADVISORY_WATCHLIST=["ZECUSDT"]`。关闭enabled可回到旧汇总。原独立Kronos/TradingView接口及真实交易执行器仍是旧系统，不应把其输出当作v2已验证结果。

## 回归结果如何使用

详见 `reports/advisory/v2_regression.md` 和同名JSON。JSON包含完整成交、拒单、费用与权益轨迹。`legacy`对照使用新组合执行器，不等于旧应用曾报告的历史业绩。

- 24个场景覆盖年度切分、双倍交易成本、剔除ZEC；另有周度选币的未来30日诊断。
- 当前结果支持“链路能够交易、能够重现和核查”，**尚不支持“选币准确率显著提升”或“可盈利实盘策略”**。主动短线在成本压力下转亏，完整区间主动长短线均明显跑输固定买持基准。
- 2026行情已被用于理解问题，时间切分不是独立未见样本。币池是事后指定的存续币，存在选择/幸存者偏差。周度30日诊断窗口重叠，不能当作独立样本胜率或复利收益。
- 回撤按收盘权益计算，不包含更坏的盘中路径；OHLC回测无法复原真实队列、点差和逐笔滑点。实时模拟会使用bid/ask。
- [Binance行情接口](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)；[Freqtrade前视检查](https://www.freqtrade.io/en/stable/lookahead-analysis/)；[回测撮合假设](https://www.freqtrade.io/en/stable/backtesting/)。

## 验证

```bash
python3 -m unittest tests.test_market_advisory tests.test_advisory_portfolio -v
# 装有项目FastAPI/httpx依赖的环境
python -m unittest tests.test_market_advisory tests.test_market_advisory_api tests.test_advisory_portfolio -v
```

覆盖未来数据不改变过去信号、实时与回归决策一致、现金/风险约束、盈利加仓、部分止盈、止损优先、跳空、时间退出、报价过期、扫描失败仍退出、重启幂等、API与旧汇总桥接。未启动完整旧应用、未发送通知、未实盘下单。
