# v12 新行情模拟运行说明

## 交给诺诺或新服务器运行

代码分支为 `feature/quant-core-overlay-research`。这是公共行情和虚拟资金研究服务，不能发送交易订单。云端助手可以协调部署、运行命令和检查结果，但其“全天候助手”能力不等于任意后台进程具备持续运行保证；须实际验证任务结束后的进程存活、网络、持久磁盘和异常恢复。

### 环境与预热数据

使用 Linux 或 macOS、Python 3.11（本机验证版本3.11.15），在新环境创建虚拟环境：

```bash
git clone --branch feature/quant-core-overlay-research https://github.com/ChinaWallace/transaction_push.git
cd transaction_push
python3.11 -m venv .venv.forward
.venv.forward/bin/python -m pip install -r requirements-forward.txt
.venv.forward/bin/python -m unittest tests.test_forward_runtime tests.test_expanded_forward tests.test_expanded_core tests.test_expanded_core_runner -q
```

本入口的45项测试不依赖NFI子模块。依赖清单记录本机已验证版本；新平台仍需确认安装和测试通过。`fcntl` 是POSIX依赖，本入口不直接支持原生Windows。

**仅克隆仓库不能直接启动完整模拟。** 三份公开历史预热文件被Git忽略：`reports/quant_v12/data/series/{BTCUSDT,ETHUSDT,ZECUSDT}.feather`。原文件须与仓库 `reports/quant_v12/protocol.json` 中的SHA256一致。本机已提供独立的 `v12-public-bootstrap.zip`（只含三份公开数据和SHA清单，不含凭证或账本），交给目标环境后先检查压缩包内容、确认以上目标文件不存在，再在仓库根目录解压；不覆盖任何现有批次。逐项验证 `protocol.json` 的 `data` 哈希后再继续。缺文件或哈希不符必须明确停止，不能改协议去迁就新下载的数据。

默认可直连，`PROXY_ENABLED=false`。确需代理时由目标环境提供其可用配置；不要复制本机`.env`，不要把本机回环代理地址带到云端。先确认系统时间准确、磁盘持久且有足够空间，并能访问公开端点 `https://fapi.binance.com/fapi/v1/time`。地域拒绝或403/451应停止并报告，不自动绕过。

### 新建独立云端批次

以下示例采用新的输出目录，旧批次不迁移、不续写。`--until` 必须是未来、有时区的5分钟边界；正式观察应预留至少30自然日。示例到期后应由用户重新确定未来截止，不自动延期。

```bash
PROXY_ENABLED=false .venv.forward/bin/python scripts/forward_expanded_core.py start \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30 \
  --until 2026-10-31T00:00:00+08:00
.venv.forward/bin/python scripts/forward_expanded_core.py status \
  --output reports/quant_v12_forward/nono-cloud-2026-09-30
```

`start` 将封存代码和输入，并固定初始化后的下一根未来5分钟边界。它启动普通后台进程；长时间托管需目标环境自己的服务管理器。使用服务管理器时必须先确保没有另一worker，再运行该批次 `code/scripts/forward_expanded_core.py run --output <批次绝对路径>`，显式传入网络配置，仅异常退出重启；停止标记必须保留。不把这台Mac的launchd配置直接用于Linux或云端沙箱。

验收必须看到：拥有正确命令的PID、连续两次新完成K线更新、三账户各3笔初始模型买入及其真实首次观察时间、账户对账通过、代码/协议哈希一致，并明确标记是否延迟补采。需要跨任务/会话结束验证存活与文件持久化，之后才能报告“云端已接管”。尚未验证这些条件时只报告“准备完成/环境受限”。

### 可直接交给诺诺的任务

> 请读取本仓库研究分支的本说明和 quant_forward_improvement_plan.md，先完成依赖测试、公开预热文件SHA验证和公共行情连通性检查，再在你可持续使用的环境启动独立公共行情模拟。仅使用虚拟资金，不接入交易凭证、不发送真实订单。保留现有Mac批次、冻结规则、首次观察时间和所有错误。确认两个新K线更新与独立账户对账，并报告进程能否跨任务持续运行、数据是否持久化；缺输入或平台不能托管时如实报告，不宣称已接管。初期重点修复连续性，研究候选使用独立批次，重要故障或新成交才通知我。

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
