# 底仓保留与趋势增强 v11

Same v7 HoldEqual seed quantities (~70% initial NOTIONAL). Never sell core for expiry, weak trend, coin weight or account drawdown; sample-end settlement only.

Completed 4h close exceeds previous 20 highs and EMA50, EMA50>EMA200. Priority by past 20-bar return. Price above original core average; each later buy within an overlay episode requires +10% vs last buy. New overlay notional <=2x current positive core unrealized profit less existing overlay notional, <=10% equity per fill. Combined overlay adds within declared 20/40/70% equity; appreciation drift is not trimmed. Postfill gross/equity<=1.4.

Two distinct completed 4h closes below EMA50 (EMA200 slow ablation) close only overlay at current 5m open. Four-hour cooldown after any overlay sale. Total gross/equity>1.5 closes overlay first; if its removal still leaves negative all-assets-zero cash floor, flag unresolved core risk and block further adds. No fictional core safety guarantee.

全部为事后研究。增强归因不改变整仓均价的钱包记账；底仓数量验证与现金流对账逐5m检查。

|区间|方案|净收益|5m回撤|共同低点压力回撤|增强净贡献USDT|加仓数|
|---|---|---:|---:|---:|---:|---:|
|development|70%底仓持续持有|-15.78%|34.80%|34.86%|0.00|0|
|development|底仓＋20%趋势增强|-15.96%|35.06%|35.12%|-17.84|5|
|development|底仓＋40%趋势增强|-15.96%|35.06%|35.12%|-17.84|5|
|development|底仓＋70%趋势增强|-15.96%|35.06%|35.12%|-17.84|5|
|development|底仓＋40%慢退出增强|-15.91%|35.02%|35.07%|-13.26|2|
|development_double_cost|70%底仓持续持有|-15.90%|34.83%|34.88%|0.00|0|
|development_double_cost|底仓＋20%趋势增强|-16.11%|35.11%|35.16%|-20.57|5|
|development_double_cost|底仓＋40%趋势增强|-16.11%|35.11%|35.16%|-20.57|5|
|development_double_cost|底仓＋70%趋势增强|-16.11%|35.11%|35.16%|-20.57|5|
|development_double_cost|底仓＋40%慢退出增强|-16.05%|35.05%|35.10%|-14.27|2|
|validation|70%底仓持续持有|-8.99%|32.14%|32.28%|0.00|0|
|validation|底仓＋20%趋势增强|-7.56%|34.74%|34.87%|143.81|10|
|validation|底仓＋40%趋势增强|-8.39%|36.01%|36.14%|59.97|12|
|validation|底仓＋70%趋势增强|-8.39%|36.01%|36.14%|59.97|12|
|validation|底仓＋40%慢退出增强|-12.24%|40.41%|40.54%|-324.63|9|
|validation_double_cost|70%底仓持续持有|-9.12%|32.16%|32.30%|0.00|0|
|validation_double_cost|底仓＋20%趋势增强|-7.82%|34.85%|34.98%|130.37|10|
|validation_double_cost|底仓＋40%趋势增强|-8.68%|36.14%|36.26%|44.64|12|
|validation_double_cost|底仓＋70%趋势增强|-8.68%|36.14%|36.26%|44.64|12|
|validation_double_cost|底仓＋40%慢退出增强|-12.44%|40.47%|40.60%|-331.94|9|
|reused_holdout|70%底仓持续持有|88.15%|9.20%|9.31%|0.00|0|
|reused_holdout|底仓＋20%趋势增强|106.12%|12.45%|12.57%|1797.56|14|
|reused_holdout|底仓＋40%趋势增强|113.52%|14.95%|15.07%|2537.58|20|
|reused_holdout|底仓＋70%趋势增强|117.48%|16.04%|16.15%|2933.17|26|
|reused_holdout|底仓＋40%慢退出增强|127.73%|12.55%|12.83%|3958.72|10|
|reused_holdout_double_cost|70%底仓持续持有|87.92%|9.20%|9.31%|0.00|0|
|reused_holdout_double_cost|底仓＋20%趋势增强|105.55%|12.49%|12.61%|1763.33|14|
|reused_holdout_double_cost|底仓＋40%趋势增强|112.68%|15.02%|15.13%|2476.15|20|
|reused_holdout_double_cost|底仓＋70%趋势增强|116.61%|16.14%|16.24%|2868.99|26|
|reused_holdout_double_cost|底仓＋40%慢退出增强|127.22%|12.55%|12.83%|3929.81|10|
|full|70%底仓持续持有|41.72%|34.80%|34.86%|0.00|0|
|full|底仓＋20%趋势增强|53.81%|35.06%|35.12%|1209.82|17|
|full|底仓＋40%趋势增强|54.99%|35.06%|35.12%|1327.26|21|
|full|底仓＋70%趋势增强|53.61%|35.06%|35.12%|1189.88|22|
|full|底仓＋40%慢退出增强|72.28%|36.02%|36.14%|3056.17|12|
|full_double_cost|70%底仓持续持有|41.53%|34.83%|34.88%|0.00|0|
|full_double_cost|底仓＋20%趋势增强|53.43%|35.11%|35.16%|1189.62|17|
|full_double_cost|底仓＋40%趋势增强|54.54%|35.11%|35.16%|1300.84|21|
|full_double_cost|底仓＋70%趋势增强|53.13%|35.11%|35.16%|1159.33|22|
|full_double_cost|底仓＋40%慢退出增强|71.95%|36.07%|36.19%|3041.02|12|
|full_execution_stress|70%底仓持续持有|41.35%|34.85%|34.90%|0.00|0|
|full_execution_stress|底仓＋20%趋势增强|52.68%|35.17%|35.27%|1132.63|17|
|full_execution_stress|底仓＋40%趋势增强|55.30%|35.17%|35.27%|1395.01|21|
|full_execution_stress|底仓＋70%趋势增强|54.91%|35.17%|35.27%|1355.74|21|
|full_execution_stress|底仓＋40%慢退出增强|71.10%|36.22%|36.34%|2974.42|12|
|challenge2025|70%底仓持续持有|199.46%|46.49%|46.60%|0.00|0|
|challenge2025|底仓＋20%趋势增强|255.02%|46.74%|46.83%|5555.44|32|
|challenge2025|底仓＋40%趋势增强|278.52%|48.60%|48.68%|7905.52|37|
|challenge2025|底仓＋70%趋势增强|257.95%|55.81%|55.88%|5848.59|46|
|challenge2025|底仓＋40%慢退出增强|376.09%|43.30%|43.37%|17662.93|22|
|challenge2025_double_cost|70%底仓持续持有|199.14%|46.50%|46.61%|0.00|0|
|challenge2025_double_cost|底仓＋20%趋势增强|253.72%|46.84%|46.93%|5458.72|32|
|challenge2025_double_cost|底仓＋40%趋势增强|276.96%|48.71%|48.79%|7781.95|37|
|challenge2025_double_cost|底仓＋70%趋势增强|256.10%|55.95%|56.02%|5696.45|46|
|challenge2025_double_cost|底仓＋40%慢退出增强|374.96%|43.35%|43.42%|17582.77|22|
|challenge2025_execution_stress|70%底仓持续持有|198.81%|46.50%|46.62%|0.00|0|
|challenge2025_execution_stress|底仓＋20%趋势增强|251.95%|46.96%|47.05%|5314.08|32|
|challenge2025_execution_stress|底仓＋40%趋势增强|273.36%|49.01%|49.09%|7455.12|37|
|challenge2025_execution_stress|底仓＋70%趋势增强|264.42%|53.72%|53.80%|6561.14|45|
|challenge2025_execution_stress|底仓＋40%慢退出增强|370.53%|43.46%|43.52%|17171.86|22|

## 冻结筛选

{
  "kind": "retrospective_frozen_rule_screen_not_new_oos",
  "candidates": [
    "Enhance40Slow",
    "Enhance40",
    "Enhance20"
  ],
  "details": {
    "Enhance20": {
      "passed": true,
      "failed": [],
      "worst_full_window_excess_pp": 11.326250053693698,
      "worst_drawdown_pct": 46.95670481620623
    },
    "Enhance40": {
      "passed": true,
      "failed": [],
      "worst_full_window_excess_pp": 13.008367328525352,
      "worst_drawdown_pct": 49.0053955527011
    },
    "Enhance70": {
      "passed": false,
      "failed": [
        "challenge2025: drawdown>50",
        "challenge2025_double_cost: drawdown>50",
        "challenge2025_execution_stress: drawdown>50"
      ],
      "worst_full_window_excess_pp": 11.59327295577237,
      "worst_drawdown_pct": 55.94741916115774
    },
    "Enhance40Slow": {
      "passed": true,
      "failed": [],
      "worst_full_window_excess_pp": 29.744248669136525,
      "worst_drawdown_pct": 43.45609838229312
    }
  },
  "execution_changed": false,
  "requires_new_forward_comparison": true,
  "selected": "Enhance40Slow"
}

## 限制

All source periods and coins already observed; neither 60 comparisons nor monthly return summaries constitute independent samples or genuine new OOS.
Only BTC/ETH/ZEC; no historical contract selection or ordinary-position portfolio tested.
Static maintenance tiers; conditional liquidation depends on other coins. Mark OHLC and stress are approximations.
Core may retain large losses; enhanced trading losses can consume shared collateral. Core-preservation failure is reported, never silently liquidated or rescued.
