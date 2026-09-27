# 全仓2x灵活加减仓研究 v10

Identical v7 seed fills: Notional70 keeps quantities; other arms double quantities (70% initial margin / 140% notional). Flex reduces proportionally at the next known 5m open when current gross/equity >1.6 to 0.9 AFTER execution drag. This creates a positive all-assets-zero cash floor, before future costs. Add variant requires a completed 4h breakout above previous 20 highs and EMA50, price >=1.2x last purchase and above current average entry. Added margin <=50% current positive marked position PnL minus prior added margin, <=5% equity per fill, postfill account exposure <=1.4. No coin weight trims, ordinary stops, expiry, or drawdown breaker.

全部结果含实际资金费、每边0.1%费用/滑点预留，另有双倍成本。任何保证金风险越界的收益只能看作未执行强平的假设值，不参与策略评比。未接入实盘。

|区间|方案|净收益|5m收盘回撤|5m共同低点压力回撤|加仓/减仓轮数|保证金模型|
|---|---|---:|---:|---:|---:|---|
|development|全仓2x · 70%初始名义仓位持有|-15.78%|34.80%|34.86%|0/0|未触发边界|
|development|全仓2x · 70%初始保证金持有|-31.56%|66.57%|66.67%|0/0|未触发边界|
|development|全仓2x · 风险上升减仓|-33.28%|55.39%|55.45%|0/1|未触发边界|
|development|全仓2x · 浮盈加仓＋风险减仓|-33.28%|55.39%|55.45%|0/1|未触发边界|
|development_double_cost|全仓2x · 70%初始名义仓位持有|-15.90%|34.83%|34.88%|0/0|未触发边界|
|development_double_cost|全仓2x · 70%初始保证金持有|-31.81%|66.65%|66.75%|0/0|未触发边界|
|development_double_cost|全仓2x · 风险上升减仓|-33.53%|55.47%|55.52%|0/1|未触发边界|
|development_double_cost|全仓2x · 浮盈加仓＋风险减仓|-33.53%|55.47%|55.52%|0/1|未触发边界|
|validation|全仓2x · 70%初始名义仓位持有|-8.99%|32.14%|32.28%|0/0|未触发边界|
|validation|全仓2x · 70%初始保证金持有|-17.99%|54.66%|54.89%|0/0|未触发边界|
|validation|全仓2x · 风险上升减仓|-25.83%|54.66%|54.89%|0/1|未触发边界|
|validation|全仓2x · 浮盈加仓＋风险减仓|-15.05%|51.20%|51.34%|3/1|未触发边界|
|validation_double_cost|全仓2x · 70%初始名义仓位持有|-9.12%|32.16%|32.30%|0/0|未触发边界|
|validation_double_cost|全仓2x · 70%初始保证金持有|-18.25%|54.71%|54.95%|0/0|未触发边界|
|validation_double_cost|全仓2x · 风险上升减仓|-26.11%|54.71%|54.95%|0/1|未触发边界|
|validation_double_cost|全仓2x · 浮盈加仓＋风险减仓|-15.29%|51.18%|51.33%|3/1|未触发边界|
|reused_holdout|全仓2x · 70%初始名义仓位持有|88.15%|9.20%|9.31%|0/0|未触发边界|
|reused_holdout|全仓2x · 70%初始保证金持有|176.30%|15.29%|15.38%|0/0|未触发边界|
|reused_holdout|全仓2x · 风险上升减仓|176.30%|15.29%|15.38%|0/0|未触发边界|
|reused_holdout|全仓2x · 浮盈加仓＋风险减仓|216.66%|16.91%|17.01%|9/0|未触发边界|
|reused_holdout_double_cost|全仓2x · 70%初始名义仓位持有|87.92%|9.20%|9.31%|0/0|未触发边界|
|reused_holdout_double_cost|全仓2x · 70%初始保证金持有|175.84%|15.31%|15.40%|0/0|未触发边界|
|reused_holdout_double_cost|全仓2x · 风险上升减仓|175.84%|15.31%|15.40%|0/0|未触发边界|
|reused_holdout_double_cost|全仓2x · 浮盈加仓＋风险减仓|215.53%|16.90%|16.99%|9/0|未触发边界|
|full|全仓2x · 70%初始名义仓位持有|41.72%|34.80%|34.86%|0/0|未触发边界|
|full|全仓2x · 70%初始保证金持有|83.43%|66.57%|66.67%|0/0|未触发边界|
|full|全仓2x · 风险上升减仓|31.24%|55.39%|55.45%|0/1|未触发边界|
|full|全仓2x · 浮盈加仓＋风险减仓|53.48%|55.39%|55.53%|5/1|未触发边界|
|full_double_cost|全仓2x · 70%初始名义仓位持有|41.53%|34.83%|34.88%|0/0|未触发边界|
|full_double_cost|全仓2x · 70%初始保证金持有|83.07%|66.65%|66.75%|0/0|未触发边界|
|full_double_cost|全仓2x · 风险上升减仓|30.74%|55.47%|55.52%|0/1|未触发边界|
|full_double_cost|全仓2x · 浮盈加仓＋风险减仓|52.64%|55.47%|55.58%|5/1|未触发边界|
|challenge2025|全仓2x · 70%初始名义仓位持有|199.46%|46.49%|46.60%|0/0|未触发边界|
|challenge2025|全仓2x · 70%初始保证金持有|398.92%|64.89%|65.24%|0/0|未触发边界|
|challenge2025|全仓2x · 风险上升减仓|204.32%|55.71%|55.91%|0/1|未触发边界|
|challenge2025|全仓2x · 浮盈加仓＋风险减仓|217.58%|66.66%|66.75%|13/3|未触发边界|
|challenge2025_double_cost|全仓2x · 70%初始名义仓位持有|199.14%|46.50%|46.61%|0/0|未触发边界|
|challenge2025_double_cost|全仓2x · 70%初始保证金持有|398.27%|64.97%|65.32%|0/0|未触发边界|
|challenge2025_double_cost|全仓2x · 风险上升减仓|203.15%|55.79%|55.98%|0/1|未触发边界|
|challenge2025_double_cost|全仓2x · 浮盈加仓＋风险减仓|215.35%|66.69%|66.78%|13/3|未触发边界|

## 适用边界
- Chosen coins and reused windows are retrospective, not new out-of-sample validation
- Static bundled maintenance tiers, not historical/account-specific tiers; no real account keys/orders
- 5m OHLC does not prove exchange execution; gap, latency, order failure and liquidation penalty stress are not modeled
- Conditional no-positive liquidation price holds other coin marks fixed; future funding/fees/shared losses change it
- 2x label is not effective leverage; 70% margin and 70% notional are both shown, no live/paper allocation silently changed

减仓明细附前后账户权益、有效杠杆、全币归零余额下界与条件强平价。参数在本轮首次运行前冻结，后续调整必须新版本，不能覆盖原结果。
