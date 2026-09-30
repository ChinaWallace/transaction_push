# v12 新行情模拟运行说明

## 交给诺诺或新服务器运行

代码分支为 `feature/quant-core-overlay-research`。这是公共行情和虚拟资金研究服务，不能发送交易订单。云端助手可以协调部署、运行命令和检查结果，但其“全天候助手”能力不等于任意后台进程具备持续运行保证；须实际验证任务结束后的进程存活、网络、持久磁盘和异常恢复。

### 环境与公共行情初始化

使用 Linux 或 macOS、Python 3.11（本机验证版本3.11.15），在新环境创建虚拟环境：

```bash
git clone --branch feature/quant-core-overlay-research https://github.com/ChinaWallace/transaction_push.git
cd transaction_push
python3.11 -m venv .venv.forward
.venv.forward/bin/python -m pip install -r requirements-forward.txt
.venv.forward/bin/python -m unittest tests.test_forward_runtime tests.test_expanded_forward tests.test_expanded_core tests.test_expanded_core_runner tests.test_forward_bootstrap tests.test_forward_public_start tests.test_forward_probe -q
```

本入口的测试不依赖NFI子模块。依赖清单记录本机已验证版本；新平台仍需确认安装和测试通过。`fcntl` 是POSIX依赖，本入口不直接支持原生Windows。以下公共初始化与跨会话检查命令为本次本地新增；部署前确认目标代码包含 `scripts/forward_bootstrap.py` 与 `scripts/check_forward_runtime.py`。尚未发布的本地改动不会因克隆旧分支而自动出现。

**新批次使用 `--bootstrap public`，无需上传本机数据或 `.env`。** 它从公开 USD-M 接口自行获取 BTC/ETH/ZEC 至少92天的5分钟成交价和标记价，以UTC日界为预热起点，只纳入已收盘行情。按1000根分页，逐页保存参数、首次获取时间和哈希，校验连续性及OHLC后，将三币数据与清单整体封存到批次的 `bootstrap/ready/`。这些历史数据只用于指标预热，不记为前向模拟成交。

下载期间尚未固定建仓时间；全部预热和补齐完成后，选择至少留30秒启动余量的未来5分钟边界，保存协议及封存时间。封存意外跨过该边界会明确失败并保留证据，不能重选旧批次种子。正式运行仍保留真实首次观察时间，延迟采集仍按补采标记。

每批源码、Python依赖版本和静态维护保证金分档仍独立封存。`--bootstrap historical`（未指定时的兼容默认值）仍要求旧研究协议匹配的三份feather文件；它不适用于只有源码的新云端环境。已创建批次不能切换模式。

默认可直连，`PROXY_ENABLED=false`。确需代理时由目标环境提供其可用配置；不要复制本机`.env`，不要把本机回环代理地址带到云端。先确认系统时间准确、磁盘持久且有足够空间，并能访问公开端点 `https://fapi.binance.com/fapi/v1/time`。地域拒绝或403/451应停止并报告，不自动绕过。

### 新建独立云端批次

以下示例采用新的输出目录，旧批次不迁移、不续写。`--until` 必须是未来、有时区的5分钟边界；正式观察应预留至少30自然日。示例到期后应由用户重新确定未来截止，不自动延期。

```bash
PROXY_ENABLED=false .venv.forward/bin/python scripts/forward_expanded_core.py start \
  --bootstrap public \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30 \
  --until 2026-10-31T00:00:00+08:00
.venv.forward/bin/python scripts/forward_expanded_core.py status \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30
```

输出目录须放在目标环境的持久磁盘；上例仅在仓库所在磁盘持久时适用。`start` 的首次下载在前台执行，`status` 的 `bootstrap` 字段显示下载进度，成功后确认后台worker PID。网络中断后重新执行同一条 `start` 命令，会复用已校验的分页；429/418的退避截止跨进程保留，403/451需人工处理，不会绕过。准备期间也可执行同批次的 `stop`，当前请求结束后会取消，不继续封存新种子或启动模拟。显式再次 `start` 才撤销停止标记；`prepare`、服务重启均不会撤销。

也可用 `prepare --bootstrap public --output ... --until ...` 完成准备，但它会冻结未来建仓时点，随后应立即启动同批次；隔很久才启动会标记延迟采集。禁止删除协议后重新初始化同一目录。

`start` 启动普通后台进程；长时间托管需目标环境自己的服务管理器。使用服务管理器时必须先确保没有另一worker，再运行该批次 `code/scripts/forward_expanded_core.py run --output <批次绝对路径>`，显式传入网络配置，仅异常退出重启；停止标记必须保留。不把这台Mac的launchd配置直接用于Linux或云端沙箱。

验收必须看到：拥有正确命令的PID、连续两次新完成K线更新、三账户各3笔初始模型买入及其真实首次观察时间、账户对账通过、代码/协议哈希一致，并明确标记是否延迟补采。需要跨任务/会话结束验证存活与文件持久化，之后才能报告“云端已接管”。尚未验证这些条件时只报告“准备完成/环境受限”。

### 跨会话验证后台进程与数据

等首根建仓K线收盘、`runtime.json` 为 `observing` 后，在目标环境执行：

```bash
.venv.forward/bin/python scripts/check_forward_runtime.py checkpoint \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30
```

记下返回的 `checkpoint` 路径，结束该任务/会话。至少再经过两个完整5分钟更新后，从目标环境的新会话执行：

```bash
.venv.forward/bin/python scripts/check_forward_runtime.py check \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30 \
  --checkpoint /持久磁盘上的批次目录/checks/返回的编号.checkpoint.json
```

检查会验证磁盘随机标记仍存在、PID与命令匹配、心跳与成功行情新鲜、协议/源码/数据哈希、三账户逐笔现金流与持仓数量，以及原事件首次观察时间不变。基线之后每根K线须有独立快照、观察时间单调，并在收盘后120秒内采集；迟到补采、缺中间快照、对账失败不会通过。结果自动保存到 `checks/probe-*.json`。进程PID允许在正常恢复后变化，并单独披露；检查失败不自动重启、不改规则、不覆盖检查基线。

通过仅证明被测主机和观察窗口。在本机通过不能证明云端托管；云环境结束任务即回收容器、未挂载持久盘或不能保留后台进程时，必须改用实际可托管服务的机器。短时通过也不是24小时可用性保证。

### 可直接交给诺诺的任务

> 请读取本仓库研究分支的本说明和 quant_forward_improvement_plan.md，确认代码已包含公共初始化入口，通过依赖测试及公共行情连通性检查，然后在持久目录使用 `start --bootstrap public` 自行下载行情并建立独立模拟批次。不要索取或上传这台Mac的.env、缓存或账本。仅使用虚拟资金，不接入交易凭证、不发送真实订单。保留冻结规则、首次观察时间和所有错误。用checkpoint/check跨任务验证后台存活、至少两个新K线更新、磁盘持久化与三账户独立对账；平台不能托管时如实报告，不宣称已接管。研究候选使用独立批次，重要故障或新成交才通知我。

截至2026-09-30，已识别但尚未改入冻结批次的限制：样本天数目前按行情窗口计算，补采不能视作等量有效前向观察；首次预定资金费前的结算频率变化存在漏检窗口；模型价格仍为K线开盘价，需独立增加首次观察后的成交价格、滑点与部分成交对照。这些限制必须随报告披露，不因测试通过或短期盈利自动进入实盘。

## 2026-09-29：独立长期批次

用户要求继续模拟并改进方案，已准备新批次 `reports/quant_v12_forward/2026-09-29-continuous/`，观察截止为 **2026-10-30 00:00 Asia/Shanghai**。TriHold、TriEnhance（增强上限40%）与预注册对照 TriEnhance20（增强上限20%）各使用独立的10,000 USDT模拟资金。三者底仓、时点、成本及风险口径一致；新增对照尚无有效性结论。具体研究顺序见 [改进计划](quant_forward_improvement_plan.md)。

协议已冻结初始建仓边界为 **2026-09-29 17:20 +08:00**。这是模型成交时间；首次观察时间另行保留。若启动权限或网络造成延迟，必须标明延迟观察，不修改种子时间，也不把补采称为实时成交。

每批的 `code/` 保存运行源码、完整本地导入依赖和预热数据，`bundle.json` / `bundle.sha256` 封存哈希与依赖版本。后台使用冻结副本，后续主仓库优化不改变运行中的策略；Python虚拟环境仍为项目共享环境，依赖版本改变会使后续启动验证失败。公共网络配置只读取代理开关与地址，支持直连，不载入交易凭证。

查询与停止均针对同一批次：

```bash
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py status \
  --output reports/quant_v12_forward/2026-09-29-continuous
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py stop \
  --output reports/quant_v12_forward/2026-09-29-continuous
```

系统托管配置记录在该批次 `service.json`，macOS LaunchAgent 标签为 `com.transactionpush.quant-forward-20260929`。配置采用登录后启动、异常退出重启与空闲防休眠；它不能保障关机、断网、合盖或手动睡眠期间运行。Python首次从后台访问“文稿”文件夹需要系统授权；**服务状态为running不等于已开始采集**，以 `runtime.json`、`latest.json` 的成功观察时间和真实新增事件为准。AI定时巡检目前保持用户此前要求的暂停状态。

如改用普通后台进程，须先核实系统托管进程已退出、锁空闲，再显式启动同一批次；不要同时启用两种托管：

```bash
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py start \
  --output reports/quant_v12_forward/2026-09-29-continuous
```

TLS/连接池错误会丢弃失效客户端并有限重试；429遵守退避，418保守暂停，403/451停止请求等待人工处理。全量观察快照为 `snapshots/*.json.gz`，`latest.json` 保持可读。停止时间 `stopped_ms` 与最后成功观察时间 `observed_ms` 分开记录。30自然日和10笔完全闭合增强持仓只是开始评价的最低门槛，不自动认定策略有效或授权真实接入。

9月28日批次最后数据止于 **19:30 +08:00**，19:36:05收到停止信号，无法据现有证据判断信号来源。至原定午夜缺54根5分钟K线；不补造隔夜执行。两账户各3笔初始买入、0笔卖出、6笔资金费事件，期末权益均为 **9,910.9314 USDT（-0.8907%）**。审计记录在旧批次 `checks/end-of-day-2026-09-29.json`，旧账本保留。

## 2026-09-28 原始运行安排（历史记录，不再启动）

用户选择新行情模拟与历史结果核验后，单独运行 TriEnhance 和同资金 TriHold。历史 v12 的源码、协议、旧模拟账本保持原状；新批次文件在 `reports/quant_v12_forward/2026-09-28-now/`。最初等待 12:00 的批次已停止，尚无成交，其协议、预热数据和源码副本保留在 `reports/quant_v12_forward/2026-09-28/`，不与新批次混算。

两账户各使用 10,000 USDT 模拟资金，BTC / ETH / ZEC 合计约 70% 初始名义底仓，增强上限为权益 40%。沿用完成 4h 信号、5m 成交模型、0.1% 每边成本、真实资金费和共享全仓会计。用户要求现在开始，初始建仓采用完成初始化后的下一根未来 5m 边界；04:00 UTC 只是历史窗口的起点，不是策略必须等待的条件。建仓时点在价格出现前冻结，不回溯采用已经知道的开盘价。新批次冻结当前公开数量过滤和资金费周期，维持保证金仍采用原研究静态分档。

进程每分钟检查公开数据，以完成的 5m K 线更新。成交时间是模型假设的 K 线开盘时间，记录在 K 线完成之后，同时保存首次观察时间及延迟；这不是实时盘口执行。断线补采明确记录为延迟观察，不伪称实时成交。观察截止为北京时间 9 月 29 日 00:00，最多留两分钟尾部采集宽限，不处理截止后的 K 线。截止只盯市并保留模拟持仓，不自动卖出底仓；尾部数据不足会标记不完整。

```bash
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py start \
  --output reports/quant_v12_forward/2026-09-28-now \
  --until 2026-09-29T00:00:00+08:00
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py status \
  --output reports/quant_v12_forward/2026-09-28-now
.venv.freqtrade-quant/bin/python scripts/forward_expanded_core.py stop \
  --output reports/quant_v12_forward/2026-09-28-now
```

`REPORT.md` 为摘要，`latest.json` 保存账户、成交、资金费、风险、5m 权益及归因；`snapshots/` 保留观察快照，`raw/` 与 `requests.jsonl` 保存公开响应、哈希和获取时间，`errors.jsonl` 保留失败。协议或源码哈希改变、行情缺口、资金费缺失会明确失败；不会按零填充，也不会重选历史最优参数。

历史复核记录在 `reports/quant_v12/maintenance/2026-09-28/`：43 项既有回归测试、42 组冻结历史回放、1492 个来源文件 SHA256 校验通过。新增前向测试覆盖历史引擎逐笔一致性、结束时保仓、期末低点风险、跨窗口与重启事件一致、预定建仓、真实资金费缺失和公开端点限制。

今日只形成运行观察，不能证明策略有效。至少 30 自然日、主动策略至少 10 笔闭合交易后才开始评价；若要继续到明天，需明确延长运行安排，并保留当前批次与原始证据。扩展 13 币本次仍只做历史核验。
