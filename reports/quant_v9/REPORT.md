# 2x持有：强平与重入必须分开

Margin2x用70%初始保证金（约140%敞口）；Notional2x用35%保证金（约70%敞口）。所有方案含费用及真实资金费。

**原始策略强平后可以再次入场。NoReentry仅保留各币最初一笔仓位，该币强平后永久停止买入。后者是相同初始成交的现金流反事实重建，不能称为独立引擎回测。**

静态维持保证金档位、5m撮合与采样回撤；引擎不计强平罚金，真实损失可能更高。

|区间|方案|净收益|5m含浮亏回撤|强平次数|强平后重入|
|---|---|---:|---:|---:|---|
|challenge2025|D55Margin2x|200.34%|64.61%|2|允许|
|challenge2025|D55Notional2x|214.19%|47.78%|2|允许|
|challenge2025|HoldMargin2x|284.03%|61.63%|2|允许|
|challenge2025|HoldNotional2x|291.99%|49.14%|2|允许|
|challenge2025_double_cost|D55Margin2x|198.33%|64.75%|2|允许|
|challenge2025_double_cost|D55Notional2x|213.42%|47.79%|2|允许|
|challenge2025_double_cost|HoldMargin2x|281.50%|61.77%|2|允许|
|challenge2025_double_cost|HoldNotional2x|291.04%|49.14%|2|允许|
|full|D55Margin2x|181.66%|59.20%|1|允许|
|full|D55Notional2x|95.09%|34.82%|1|允许|
|full|HoldMargin2x|42.96%|64.78%|2|允许|
|full|HoldNotional2x|57.49%|36.30%|2|允许|
|full_double_cost|D55Margin2x|181.11%|59.28%|1|允许|
|full_double_cost|D55Notional2x|94.82%|34.85%|1|允许|
|full_double_cost|HoldMargin2x|42.09%|64.87%|2|允许|
|full_double_cost|HoldNotional2x|57.10%|36.35%|2|允许|
|reused_holdout|D55Margin2x|149.68%|15.41%|0|允许|
|reused_holdout|D55Notional2x|74.83%|8.96%|0|允许|
|reused_holdout|HoldMargin2x|176.31%|15.29%|0|允许|
|reused_holdout|HoldNotional2x|88.15%|9.20%|0|允许|
|challenge2025|HoldMargin2xNoReentry|-48.49%|58.58%|2|禁止|
|challenge2025|HoldNotional2xNoReentry|-24.18%|31.05%|2|禁止|
|challenge2025_double_cost|HoldMargin2xNoReentry|-48.72%|58.70%|2|禁止|
|challenge2025_double_cost|HoldNotional2xNoReentry|-24.29%|31.09%|2|禁止|
|full|HoldMargin2xNoReentry|-44.18%|61.20%|2|禁止|
|full|HoldNotional2xNoReentry|-22.06%|31.84%|2|禁止|
|full_double_cost|HoldMargin2xNoReentry|-44.42%|61.33%|2|禁止|
|full_double_cost|HoldNotional2xNoReentry|-22.18%|31.89%|2|禁止|
|reused_holdout|HoldMargin2xNoReentry|176.31%|15.29%|0|禁止|
|reused_holdout|HoldNotional2xNoReentry|88.15%|9.20%|0|禁止|
