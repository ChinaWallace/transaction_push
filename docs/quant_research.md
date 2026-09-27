# 三币策略研究：数据、运行和结果

当前批次比较 BTC/ETH/ZEC USDT 永续的 13 个固定策略版本，结果见 [研究报告](../reports/quant_v5/REPORT.md)。这套研究只允许 Freqtrade BACKTEST，不启动交易 bot；它与运行中的模拟账户分开记账，使用项目统一 `.env` 代理设置，不读取账户权限、不发送交易请求。

## 当前电脑上的统一命令

```sh
./scripts/quant.sh start       # 行情采集、模拟循环和看板
./scripts/quant.sh status
./scripts/quant.sh research    # 校验来源、复用已完成回测、重建盯市报告
```

看板：[策略实验室](http://127.0.0.1:8891/api/quant/dashboard#research)。可以切换完整/筛选/留出/双倍费用区间，查看13策略比较、含浮亏曲线、每币净贡献以及每笔买卖时间、价格、数量、费用和触发原因。长持基准的终点卖出标注为回测结算，不冒充真实策略信号。

## 固定实验

- `reports/quant_v5/strategy_protocol.json` 固定币种、日期、杠杆、费用和源码版本。
- `selection_freeze.json` 记录看过筛选段后、运行留出段前选定的 Donchian55。筛选规则不是在看筛选数据前预注册；留出段不用于事后更换赢家。
- 完整区间为2026-01-01至09-24 UTC（结束日不含）；筛选段5–6月；留出段7–9月。各段独立从现金启动，不能相加。
- 初始10,000 USDT，仅多1x，可用预算70%，单币预算约23.33%。与当前服务的50币、优选70%动态上限、45%回撤规则不是同一实验。
- 5m为撮合和盯市分辨率；策略使用5m/15m/1h/4h及NFI所需的1d信息，所有信息在对应K线收盘后才可用。下一5m开盘模拟成交。
- 基础双边各10bps成本代理（5bps费+5bps执行预留），真实资金费另计；压力测试各20bps。不能当作真实深度或逐笔滑点重建。
- 收益必须与引擎逐笔利润对账；回撤按所有5m标记价和持仓浮亏计算。`equity_preview.json`只是绘图抽样，完整数据在`equity_5m.feather`。
- NFI X7/X8取自锁定提交`3cc57f3cb1d0775c78f6e01537a0de2272339326`，使用原始源码和退出/加减仓逻辑，包装层约束仅多1x及预算。不是上游默认3x与做空参数业绩。

`MTF72h`与`MTFNoTime`仅改变持仓期限，可以作因素对照。`MTFFourHourExit`也更换ATR周期和止损，必须按完整策略比较。MTF研究复刻没有全池排名、市值约束或优选豁免，不能称为当前模拟账户历史业绩。

## 环境与原始数据准备

本机环境已经就绪。重新准备时：

```sh
./scripts/quant.sh setup
uv venv --python 3.11 .venv.freqtrade-quant
uv pip sync --python .venv.freqtrade-quant/bin/python freqtrade/requirements.quant-v3.lock.txt
.venv.quant/bin/python scripts/prepare_quant_strategy_data.py
.venv.quant/bin/python scripts/prepare_quant_strategy_data.py --warmup-only
.venv.freqtrade-quant/bin/python scripts/prepare_freqtrade_comparison.py
```

转换器还要求现有已验收的真实资金费数据：`reports/quant_v3/futures_replay/funding/symbols/{BTC,ETH,ZEC}USDT.json`。它会检查完整性，缺失时不以0补齐。原始归档ZIP及官方CHECKSUM保存在`reports/quant_v5/data/raw`；补齐官方标记价档案缺口的真实REST响应和独立长期指标预热保留在`raw_rest`、`series/klines_warmup`。来源和哈希记录在各manifest中。NFI仓库及其原许可证在`research/vendor/NostalgiaForInfinity`保留。

## 单独运行与检查

```sh
.venv.quant/bin/python scripts/run_strategy_comparison.py --window validation
.venv.quant/bin/python scripts/run_strategy_comparison.py --window holdout
.venv.quant/bin/python scripts/run_strategy_comparison.py --window full --double-cost
.venv.freqtrade-quant/bin/python scripts/analyze_strategy_comparison.py
.venv.quant/bin/python scripts/report_strategy_comparison.py
.venv.freqtrade-quant/bin/python scripts/check_strategy_lookahead.py Donchian55 EMA4h NFI8Long1x
```

每组都有独立配置、用户目录和NFI缓存，保存原始Freqtrade ZIP、日志、交易、成交、盯市净值和资金对账。复用结果前验证冻结策略源码、NFI提交、原始来源和转换数据哈希；要改变策略或数据，应新建实验批次，不能把旧结果混入同一排名。

目前抽样前视检查覆盖 Donchian55 9个、EMA4h 12个、NFI X8 6个信号，未发现偏差；这不是全策略完整形式证明。三个用户指定的存续币种不能验证全池选币能力，当前开源源码也可能使用过这些历史时期调参。当前没有将研究结果自动替换为实盘或50币模拟策略。
