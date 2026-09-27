# 代码仓库与本地研究数据

本分支包含量化服务、策略、回测工具、测试、文档及精简研究结果。当前v12首选为三币底仓＋慢退出增强；实时执行尚未接入该策略，不能把研究通过理解为实盘就绪。

## 获取代码

```bash
git clone --recurse-submodules --branch feature/quant-core-overlay-research https://github.com/ChinaWallace/transaction_push.git
cd transaction_push
# 已有克隆可以使用：
git submodule update --init --recursive
```

NostalgiaForInfinity作为Git子模块固定在已核验的上游提交 `3cc57f3cb1d0775c78f6e01537a0de2272339326`，保留其上游许可证。项目研究适配器位于 `research/strategies`。

## 本地数据边界

Git中保留研究协议、汇总比较、筛选、验证摘要及公开候选资料；约2.2GB行情、每次回放明细、运行日志、虚拟账户数据库及WAL、连接配置和凭证不上传。

因此，新克隆可以阅读研究结论，但不会自动拥有本机已经生成的完整回测数据和逐笔明细。看板的历史明细需相应本地报告文件；冻结哈希不能替代文件内容。重放旧研究需要按各版本文档准备原数据，缺失或哈希不符会明确报错，不会用新数据假冒旧结果。

```bash
./scripts/quant.sh setup
./scripts/quant.sh start --research-only  # 只读查看已存在的研究结果
./scripts/quant.sh status
```

研究Python环境及数据准备见 [三币策略研究](quant_research.md)、[多币底仓研究](quant_expanded_core_research.md)。个人代理等配置放在被忽略的 `.env`，可参考 `env.example`，不要提交真实API凭证。只读看板不启动旧账户采集或模拟。
