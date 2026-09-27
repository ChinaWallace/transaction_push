> 当前运行规则已更新：请先看 [优选长期仓与普通策略仓](quant_policy.md)。本文保留旧版研究和迁移记录，旧版仓位、止损与回撤设置不代表当前优选仓。

# 全池合约策略 v3.2

## 一套命令启动

```bash
cd /Users/admin/Documents/workSpaces/transaction_push
./scripts/quant.sh setup    # 首次安装/恢复隔离依赖，已有环境可跳过
./scripts/quant.sh start    # 后台启动：行情采集 + 自动纸面模拟 + 看板
./scripts/quant.sh status   # 区分进程运行、行情失败、最近成功、下一轮时间
./scripts/quant.sh logs     # 跟随日志；Ctrl+C 只退出看日志
./scripts/quant.sh stop     # 停止服务，保留账户、仓位和全部流水
./scripts/quant.sh restart  # 重启且继承原账户，不重置本金
```

看板：http://127.0.0.1:8891/api/quant/dashboard 。同一项目只允许一个服务和一个写入周期；重复 `start` 不产生第二个模拟账户。这里不启动旧数据库/ML/通知进程，也不同时启动另一套 Freqtrade 模拟账本。默认只监听本机。

自定义：`./scripts/quant.sh start --port 8891 --interval 60 --refresh 300`。`once` 运行一个完整周期，`test` 运行策略/账户/服务相关测试，`backtest` 运行保留的 v3.1 六仓历史诊断。后台进程不依赖当前终端窗口，但电脑休眠和服务停机期间不观察；没有配置系统开机自启。

## 时间周期和扩仓

- 日线计算策略：7/20/60/120 日动量、EMA20/50、ATR14；每天 UTC 00:00（北京时间08:00）后首个完整周期固定当日目标。
- 默认每 60 秒采集公开报价并检查待入场、止损及资金费；每 300 秒更新交易规则、全池历史缺口和市值。网络变慢会延后，连续失败采用最长 300 秒重试间隔。
- 从候选池扩为最多 **10 个目标**，每目标计划止损风险额度降至 **2.5%**，不扩大组合保证金65%、名义敞口180%和止损风险25%的上限。入场时用实际标记价、成交价和费用再次限制风险。
- 日内只重试未成交目标，不重复买已完成的同日目标；跌破计划止损或趋势失效则当日取消等待。每天更新一次持仓配置，止损则逐轮检查。
- 没有固定持有天数；可能数小时至数周。新版为 `contracts-v3.2`，首次启用会重新分配原六仓资金，保留原有开仓时间和历史账本。

2026-09-24 23:20:20（北京时间），通过 Binance 连接器最新报价及真实资金费覆盖，新增 ENA、ARB、RAYSOL 三个模拟持仓；NIL 进入第10个目标，但报价低于入场区间，仍等待。原持仓按预算减仓，不增加本金。本机原生 REST 在本轮持续服务启动时又返回 HTTP 451，因此服务目前记录错误并重试，不能称为已连续获得有效行情。连接器完成的一轮不是自动后台循环成功。

## 看板与记录

看板展示：服务状态/错误/下一轮时间、账户权益曲线、实际持仓和入场时间、目标与待入场原因、逐笔入场/减仓/退出/资金费、完全退出交易的净贡献、最近20次观察、全池候选未入选原因。时间统一按北京时间显示；权益曲线不连接监控空档。

读取接口：`GET /api/quant/history?limit=100&before=<事件ID>` 分页查看流水，`/runtime` 查看服务，`/strategy` 查看周期及规则，`/paper` 查看账户。流水的卖出盈亏扣该笔退出手续费；完全退出交易的净贡献另计入开仓费用、历史部分减仓及资金费。费用补记保留真实结算时间，事件按写入顺序分页。

**历史回放与当前模拟必须分开读**：2026-01-01～09-23 的 +88.70% 是旧 v3.1 六仓、日线成交假设的研究结果；没有用它宣称新10仓分钟执行模式的收益。当前账户跨版本延续，权益变化也不是新版本单独的成绩。

当前实现从币安交易规则动态发现全部 `TRADING + USDT + PERPETUAL/TRADIFI_PERPETUAL`，不再使用 BTC/ETH 或老币固定白名单。2026-09-24 早间快照为 728 个合约；晚间刷新为 727 个：527 个普通永续、200 个 TradFi 永续。流动性门槛变化后自动补数，日线覆盖扩至 361 个；历史回放固定使用先前冻结的 354 个，避免运行中悄悄改变样本。

UNI、ZEC、SKHY（海力士 ADR）和 SKHYNIX（韩国股票）均参加排名。股票合约不是持有股票；USDC、币本位合约尚未合入这个 USDT 账户。未知币种身份/市值和股票标的估值保留空值，不把缺失写成 0。

## 选币、入场与退出

1. 全池发现后检查报价与成交量时间、价差、标记/指数价偏离、上市年龄。24h 成交额至少 500 万 USDT，20 日成交额中位数至少 300 万；至少 30 根完整日线。未满足条件的合约仍显示在全池列表里。
2. 相对动量 40 分、趋势 25 分、成交额 15 分、市值 10 分、资金费 10 分。动量用可获得的 7/20/60/120 日窗口；30 日新币不把一段收益重复伪装成 60/120 日收益。加密资产和 TradFi 在各自组内排动量与流动性分位。
3. 市值只使用明确 CoinGecko ID，时间不能晚于决策，也不能过期超过一天。当前验证覆盖 66 个合约，其余降低评分与仓位；它不是覆盖全币种、全股票的基本面模型。市值分数是质量权重，不意味着市值越大未来涨幅越大。
4. 新建仓要求趋势票数至少 3/4、20 日收益为正、总分至少 65。已持有的合约在趋势票数至少 2/4、仍高于 EMA50、总分至少 50 时优先保留，减少轻微排名变化导致的卖出。
5. 只在前一收盘价减 1 ATR 至加 1.5 ATR 区间内入场，跳空不追。短线部分是执行时机和风险控制，目前没有独立验证的高频做空模型。中长线由日线趋势管理，没有固定收益目标截断上涨。
6. 初始止损为前一收盘价减 4 ATR，同时限制价格风险至 22%；随后使用只提高、不放宽的 5 ATR 跟踪止损。趋势/排名失效退出，止损后冷却 3 天；每个 UTC 日最多一次目标再平衡，日内重试未成交目标。缺报价或费用数据时冻结新增仓位，能获得有效报价的止损仍执行。

v3.2 最多 10 个持仓；保留的 v3.1 历史诊断仍为 6 仓。按止损距离、单币波动率、组合相关性分配风险；相关性超过 0.90 的候选不重复纳入，SKHY/SKHYNIX 按同一发行人限制。单币名义仓位不超过权益 35%，年轻币不超过 12%，估值缺失不超过 15%；总名义敞口上限 180%，保证金上限 65%，计划止损风险上限 25%，年化波动目标 80%。

用户允许的上限为 3 倍。低波动币最多 3 倍，中等波动最多 2 倍，极高波动、ATR/价格超过 12%、不足 90 日历史、估值缺失和 TradFi 使用 1 倍。杠杆是保证金使用参数，不直接乘组合收益。组合回撤触发线设为 45%，触发后暂停 28 天；跳空、滑点和行情中断仍可能超过用户 50% 容忍线。

## 费用与账户

`FuturesBook` 区分钱包、未实现盈亏、名义敞口和逐仓保证金。基础研究成本为单边手续费 5 bps、滑点 5 bps；资金费按真实事件的数量 × 标记价格 × 费率结算，正费率扣款，负费率收入。

SQLite 使用事务保存账户、费用游标、信号 ID 和每轮结果。每次改变数量前结清之前区间费用，重复事件不重记。若费用数据缺失但发生止损，退出时的数量和待补区间仍会保留；补齐之前禁止再开仓。报价过期不模拟成交，旧时间戳不能重放进现有账户。模拟库不会访问交易凭证或发送真实订单。超过 5 分钟没有观察时记录监控空档，无法重建空档中的止损；本次继续前存在约 8 小时空档，不能把按当前报价更新的浮盈作为持续自动交易成绩。导入费用包时可使用与报价一致、且不超过 3 分钟的采集截止时刻，不能使用未来报价执行过去决策。

## 回测证据与限制

结果见 `reports/quant_v3/contracts/replay.json` 和 `reports/quant_v3/review.md`。2026-01-01 至 2026-09-23，354 合约有 191,072 根闭合日线和 404,005 笔资金费；552 个分页请求完整，8 币 744 笔归档抽样逐笔相符。不存在的结算事件没有补 0；不同的 1/4/8 小时间隔按真实时间保留。

该回放是**研究诊断**：

- 354 个合约来自当前仍上市、当前成交额较高的池子，有幸存偏差和筛选偏差。只按当时已有日线、成交额、资金费计算特征，不能消除样本本身的偏差。
- 没有历史市值，因此回放使用缺失市值的低权重和 1 倍规则；不能把今天的市值回填过去。它与当前有市值评分的模拟组合不同。
- 2 倍、3 倍场景仅覆盖保证金参数，专用于敏感性分析，并非用历史结果选出的实盘参数。两者敞口受仓位上限限制，结果可能相同。
- 日 K 无法还原盘中先后顺序。止损当天扣全部资金费支出、忽略该仓资金费收入，形成保守费用边界；盘中压力回撤按可能的同步高点到同步低点计算，是压力上界，不是真实逐笔最大回撤。
- 跳空强平检测采用保守近似，没有每个历史时刻的维持保证金阶梯和标记价 K 线，不能当作精确交易所强平仿真。模拟订单精度与成交队列也不能替代真实交易所验收。
- 候选方法和压力场景保存在 `replay_protocol.json`；发现资金费贡献较大后另加“不计负资金费收入”诊断，没有据此调参选最佳收益。未通过严格样本外/前向验证，`live_eligible=false`。

另外，早期 28 币现货研究也被保留在 `reports/quant_v3/research.json`：训练窗选出的 Donchian 后段收益为负，因此没有把那组失败结果作为合格生产策略。这与当前全池合约实验是两份不同的研究。

## 使用

在项目根目录先恢复隔离环境（已锁定依赖，避免临时目录清理导致看板失效）：

```bash
uv venv --python 3.14 .venv.quant
uv pip sync --python .venv.quant/bin/python config/requirements.quant-api.lock.txt
uv venv --python 3.11 .venv.freqtrade-quant
uv pip sync --python .venv.freqtrade-quant/bin/python freqtrade/requirements.quant-v3.lock.txt
```

API/测试用 `.venv.quant/bin/python`，Freqtrade 命令用 `.venv.freqtrade-quant/bin/freqtrade`。以下 `python3` 指相应虚拟环境的 Python。

运行：

```bash
# 用已收集的币安连接器快照生成排名与计划
python3 scripts/quant_portfolio.py scan

# 本地纸面账户；已有仓位需要导入费用覆盖包才能继续调仓
python3 scripts/quant_portfolio.py paper-step --funding /path/to/funding.json
python3 scripts/quant_portfolio.py paper-status

# 在能正常访问 Binance public REST 的运行环境采集并完成一轮纸面交易
python3 scripts/quant_portfolio.py cycle

# 固定历史样本回放
python3 scripts/prepare_quant_futures_replay.py assemble
python3 scripts/backtest_quant_contracts.py

# 独立启动看板，不启动原项目的数据库、ML 或通知任务
python3 -m uvicorn app.quant.api:app --host 127.0.0.1 --port 8891
```

看板 `/api/quant/dashboard`；完整快照 `/api/quant/contracts`；文字报告 `/api/quant/report`；回放 `/api/quant/replay`；模拟账户 `/api/quant/paper`。`POST /api/quant/paper/step` 只接受本机非浏览器客户端，可传 `{"funding":{...}}`。资金费覆盖格式：每个 symbol 对应 `start/end` 毫秒、`complete:true` 和包含 `fundingTime/fundingRate/markPrice` 的 `events` 数组，覆盖上次游标到本次决策时间。

主应用已挂载路由，核心汇总默认 `QUANT_CONTRACTS_ENABLED=true`。快照过期或不完整时返回明确失败，不退回旧现货结论。修改没有启动任何通知或旧交易任务。关闭该开关可以继续查看保留的旧版接口。

早先本机原生 `fapi.binance.com` 返回 HTTP 451，数据由已连接的 Binance 插件采集。2026-09-24 14:48 UTC 再验证时原生访问恢复，`cycle` 已完成一轮独立 REST 采集、全池评分、真实资金费核对和模拟账户更新：数据完整、无待补费用、同日信号没有重复建仓。该结果证明当时一次端到端纸面流程成功。后续 v3.2 持续服务已启动，但再次遇到 HTTP 451 并进入重试；Freqtrade 行情循环、断线恢复和持续有效前向表现仍需验证。

## Freqtrade 执行桥接

```bash
python3 scripts/quant_portfolio.py export-freqtrade
freqtrade list-strategies --userdir freqtrade/user_data \
  -c reports/quant_v3/contracts/freqtrade.dryrun.json -1
# 仅在已验收的数据环境启动 dry-run
freqtrade trade --userdir freqtrade/user_data \
  -c reports/quant_v3/contracts/freqtrade.dryrun.json
```

`QuantFuturesPortfolioStrategy` 在 Freqtrade 2026.8 已通过真实策略发现、配置 schema 和回调测试。独立 dry-run/SQLite 配置，逐仓模式，上限 3 倍，3 分钟过期阻止入场并取消旧入场挂单，原有止损继续运行；框架处理订单精度、撤单及交易所止损。外部日计划刷新后需要同步 pair whitelist；导出命令会保留纸面账户已持有的交易对。已持有的 Freqtrade 仓位仍由框架跟踪，但名单更新和重启流程尚未做交易所联调。

桥接器只做新建仓与减仓，暂不自动追加强仓；它不是纸面账本每一笔调仓的完全相同执行器。代码主动拒绝 live/spot/cross 模式，也拒绝把今天的外部计划拿去做历史回测。后续实盘需完成历史上市池、市值历史、精确保证金/强平、断线/重启/撤单及一段真实前向模拟验证。

## 验证

```bash
python3 -m unittest tests.test_market_advisory tests.test_market_advisory_api \
  tests.test_advisory_portfolio tests.test_quant_futures tests.test_quant_service \
  tests.test_quant_replay tests.test_quant_runtime -v
# 在包含 Freqtrade 的独立环境
python3 -m unittest tests.test_quant_freqtrade -v
```

当前 73 项项目相关测试与 5 项 Freqtrade 测试通过，含9项新增v3.2回归。包括未来数据隔离、资金费增减仓游标、退出后的费用补记、报价/计划过期、风险预算、杠杆换算、期末账户一致性及本机写入限制。原项目依赖数据库/ML/外部通知的完整启动未作为本次验证结果。

研究来源与身份依据见 [quant_sources.md](quant_sources.md)。

## v4：统一配置与多周期服务（2026-09-25）

当前入口是 `./scripts/quant.sh start`，API、采集、模拟账本由 `app/application.py` 的同一个应用工厂组装。`scripts/quant_service.py` 只负责启动、停止和命令分发。`app.quant.api:app` 兼容入口也使用同一生命周期。不要同时启动两个写账户的进程；`worker.lock` 和 `cycle.lock` 分别保护进程和账户写入。

`app/core/runtime_config.py` 是公共配置层，旧 `Settings` 继承它。读取项目根目录的绝对 `.env` 路径，优先级为进程环境 > 项目 `.env` > 默认值，不依赖运行目录。API Key、Secret、代理地址不会进入公开配置响应。公共行情不用 API 密钥；存在密钥不代表账户鉴权通过。

```bash
./scripts/quant.sh setup
./scripts/quant.sh start
./scripts/quant.sh status
./scripts/quant.sh config
./scripts/quant.sh doctor
./scripts/quant.sh restart
./scripts/quant.sh stop
./scripts/quant.sh backtest
```

服务配置在 `.env`：`QUANT_PORT=8891`、`QUANT_OBSERVATION_SECONDS=60`、`QUANT_REFRESH_SECONDS=300`、`QUANT_MAX_POSITIONS=10`、`QUANT_MAX_LEVERAGE=3`、`QUANT_POSITION_RISK=0.025`。`BINANCE_BASE_URL`、`BINANCE_TESTNET`、`PROXY_ENABLED`、`PROXY_URL` 与旧主程序共享；显式关闭系统代理继承。`APP_PROFILE=quant` 启动这条量化链路；统一工厂只有在显式配置 `legacy` 时才加载旧数据库/ML/通知业务。`quant.sh` 固定选择 quant 服务组合。配置修改后需 restart。

行情历史后台任务与报价/止损任务分开运行。默认从 Binance REST 拉取 `4h`、`1h`、`15m` 各240根，缓存到 `mtf/<timeframe>/<symbol>.json`，只补充尚未有最新闭合K线的周期。WebSocket 字段保留供旧服务使用；v4明确使用REST轮询，没有宣称已接WebSocket。行情、买卖价和资金费均通过同一配置客户端访问；HTTP451/限流/连接错误不会变成成功状态。

策略：4h的1/3/10日动量与EMA趋势进行选币，每4h冻结目标权重；1h收盘高于EMA20、EMA20>EMA50并上行；15m放量突破前20根最高价，或回踩EMA20收复才允许入场。每个周期必须闭合、连续、时间对齐。成交用确认后的新报价，不在信号K线内提前买入。初始止损为2.5倍1h ATR（价格距离至多10%），3倍1h ATR追踪；1h跌破EMA50、15m跌破前10根低点、72h到期退出，止损/信号退出冷却1h。每4h每币至多加仓一次，重启后仍保持去重。

旧日线持仓不会偷偷改成小时ATR。首个数据及资金费都完整的v4计划执行时，旧仓先以真实新报价模拟平仓，原因 `strategy_migration_exit`，再按新信号评估入场。保留初始资金、钱包、历史成交和费用；迁移前仍按旧止损保护。网络不可用时不做迁移。

`backtest` 现在运行 v4 多周期样本回放；旧版日线实验用 `python scripts/backtest_quant_contracts.py` 单独执行。v4样本来自 Binance connector，BTC/ZEC/UNI 共4920根已闭合K线和93条资金费事件，原始来源/哈希在 `reports/quant_v4/sample/manifest.json`。约9天、3币的集成回放不能证明全币池策略长期有效，也不是经过样本外验证的收益承诺。当前没有v4全池长期回测，也没有实盘自动下单。

部署验证：本机 `.env` 代理端口已按用户要求改为7897；可到达Binance，但公开接口返回HTTP451地区访问限制。服务与看板可启动，自动行情采集仍受该限制影响；旧快照明确标为过期。

`doctor` 通过项目配置进行只读连接测试，区分代理连接错误、Binance地区拒绝和公开API成功，不测试或输出账户密钥。2026-09-25复查：7897 HTTP CONNECT成功，Clash已为GLOBAL，fapi.binance.com匹配GLOBAL自动线路；经同一代理的诊断站识别为US/LAX。原生接口仍451，不能宣称自动采集已恢复。
