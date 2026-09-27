"""Causal cross-sectional portfolio regression with fixed time splits."""

from bisect import bisect_left
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from statistics import mean

from .engine import DAY, INTERVALS, closed_candles, daily_result, features, iso, plan, policy_for
from .portfolio import Portfolio


def timestamp(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()*1000)


class History:
    def __init__(self, snapshot):
        self.as_of = snapshot["as_of"]
        self.data, self.times, self.open_index, self.cache = {}, {}, {}, {}
        for symbol, intervals in snapshot["symbols"].items():
            self.data[symbol], self.times[symbol], self.open_index[symbol] = {}, {}, {}
            for interval, rows in intervals.items():
                if interval not in INTERVALS:
                    continue
                bars = closed_candles(rows, interval, self.as_of, 1)
                self.data[symbol][interval] = bars
                self.times[symbol][interval] = [b.close_time for b in bars]
                self.open_index[symbol][interval] = {b.open_time: b for b in bars}
        if "BTCUSDT" not in self.data:
            raise ValueError("BTC benchmark is required")

    def before(self, symbol, interval, now, minimum):
        bars = self.data[symbol].get(interval, [])
        end = bisect_left(self.times[symbol].get(interval, []), now)
        if end < minimum or bars[end-1].close_time != (now//INTERVALS[interval])*INTERVALS[interval]-1:
            return None
        key = symbol, interval, end
        if key not in self.cache:
            self.cache[key] = features(bars[max(0,end-300):end])
        return self.cache[key], bars[end-1]

    def signals(self, now, policy, horizon, universe):
        btc = self.before("BTCUSDT", "1d", now, policy.min_daily_bars)
        if btc is None:
            return [], {"BTCUSDT": "benchmark_warmup_or_gap"}
        result, rejected = [], {}
        for symbol in universe:
            daily = self.before(symbol, "1d", now, policy.min_daily_bars)
            if daily is None:
                rejected[symbol] = "daily_warmup_or_gap"
                continue
            try:
                row = daily_result(symbol, daily[0], btc[0], daily[1].close_time, now, policy)
            except ValueError:
                rejected[symbol] = "historical_liquidity_filter"
                continue
            execution_bar = daily[1]
            if horizon == "short_term":
                four = self.before(symbol, "4h", now, 100)
                if four is None:
                    rejected[symbol] = "four_hour_warmup_or_gap"
                    continue
                row["short_term"] = plan("short_term", four[0], row["metrics"], row["metrics"]["rs30_btc_pct"],
                                          row["market_regime"], row["selection_score"], now, policy)
                execution_bar = four[1]
            row["signal_time"] = iso(execution_bar.close_time)
            row["execution_quote_volume"] = execution_bar.quote_volume
            result.append(row)
        result.sort(key=lambda r: (-r["selection_score"], r["symbol"]))
        return result, rejected


def buy_hold_benchmark(history, universe, interval, start, end, policy, exposure=1):
    returns, missing = {}, []
    factor = (1-policy.slippage_bps/10000)*(1-policy.fee_bps/10000)/((1+policy.slippage_bps/10000)*(1+policy.fee_bps/10000))
    for s in universe:
        bars = [b for b in history.data[s][interval] if start <= b.open_time < end]
        if not bars or bars[0].open_time != start:
            missing.append(s)
            continue
        returns[s] = (bars[-1].close/bars[0].open*factor-1)*100*exposure
    return {"return_pct": mean(returns.values()) if returns else None, "per_symbol": returns,
            "initial_exposure_pct": exposure*100, "missing_at_start": missing}


def run_portfolio(history, universe, policy, horizon, start, end, initial_cash=10000, details=True):
    start = timestamp(start) if isinstance(start, str) else start
    end = timestamp(end) if isinstance(end, str) else end
    interval = "4h" if horizon == "short_term" else "1d"
    reference = [b for b in history.data["BTCUSDT"][interval] if start <= b.open_time < end]
    if not reference:
        raise ValueError("Empty evaluation window")
    book = Portfolio(policy, horizon, initial_cash)
    eligibility, actions, by_symbol, selections = Counter(), Counter(), Counter(), []
    for ref in reference:
        signals, rejected = history.signals(ref.open_time, policy, horizon, universe)
        eligibility.update(rejected.values())
        actions.update(r[horizon]["action"] for r in signals)
        by_symbol.update(r["symbol"] for r in signals if r[horizon]["action"] == "buy_candidate")
        bars = {s: history.open_index[s][interval][ref.open_time] for s in universe
                if ref.open_time in history.open_index[s][interval]}
        if set(book.positions)-set(bars):
            raise ValueError("Incomplete valuation: missing bars for an open position")
        # Full OHLC values are not visible to on_open or any signal calculation.
        book.on_open(ref.open_time, signals, {s:b.open for s,b in bars.items()})
        book.on_close(ref.close_time, bars)
        if ref.open_time % (7*DAY) == 0:
            selections.append({"time": iso(ref.open_time), "leaders": [r["symbol"] for r in signals[:5]]})
    book.liquidate(reference[-1].close_time)
    result = book.summary()
    result.update(start=iso(reference[0].open_time), end=iso(reference[-1].close_time), universe=universe,
                  signal_actions=dict(actions), buy_signals_by_symbol=dict(by_symbol), data_exclusions=dict(eligibility),
                  rejection_counts=dict(Counter(r["reason"] for r in book.rejections)), weekly_selections=selections,
                  btc_buy_hold=buy_hold_benchmark(history, ["BTCUSDT"], interval, reference[0].open_time, end, policy),
                  equal_weight_buy_hold=buy_hold_benchmark(history, universe, interval, reference[0].open_time, end, policy),
                  exposure_matched_buy_hold=buy_hold_benchmark(history, universe, interval, reference[0].open_time, end, policy, policy.max_portfolio_pct/100),
                  limitations=["事后指定的存续币池，存在选择与幸存者偏差", "固定规则的时间切分回归，不等于独立未见样本",
                               "止损优先、次根开盘成交、无杠杆；收益已扣成本", "回撤基于 K 线收盘权益，非盘中最大回撤"])
    result["pnl_by_symbol"] = {s: sum(t["pnl_usdt"] for t in book.trades if t["symbol"] == s) for s in universe}
    result["activity"] = {"entry_fills": sum(e["side"] == "buy" and e["reason"] != "add_winner" for e in book.events),
                          "adds": sum(e["reason"] == "add_winner" for e in book.events),
                          "partial_exits": sum(e["reason"] == "partial_take_profit" for e in book.events),
                          "exits": dict(Counter(t["fills"][-1]["reason"] for t in book.trades)),
                          "mean_exposure_pct": mean(p["exposure_pct"] for p in book.equity_curve)}
    if not details:
        for key in ("events", "trades", "equity_curve", "rejections", "weekly_selections"):
            result.pop(key, None)
    return result


def selection_diagnostic(history, universe, policy):
    """Future outcomes are labels only, never inputs to ranking or execution."""
    observations = []
    for b in history.data["BTCUSDT"]["1d"]:
        now = b.open_time
        if now < timestamp("2024-01-01T00:00:00+00:00") or now % (7*DAY):
            continue
        rows, _ = history.signals(now, policy, "long_term", universe)
        outcomes = {}
        for row in rows:
            symbol = row["symbol"]
            entry = history.open_index[symbol]["1d"].get(now)
            final = history.open_index[symbol]["1d"].get(now+29*DAY)
            if entry and final:
                outcomes[symbol] = (final.close/entry.open-1)*100
        if len(outcomes) < 3 or "BTCUSDT" not in outcomes:
            continue
        selected = [r["symbol"] for r in rows if r["symbol"] in outcomes][:3]
        winners = sorted(outcomes, key=outcomes.get, reverse=True)[:3]
        observations.append({"time": iso(now), "selected": selected,
                             "selected_return30_pct": mean(outcomes[s] for s in selected),
                             "universe_return30_pct": mean(outcomes.values()),
                             "btc_return30_pct": outcomes["BTCUSDT"], "future_top3": winners,
                             "future_top3_capture_pct": len(set(selected)&set(winners))/3*100})
    return {"observations": observations, "count": len(observations),
            "mean_selected_return30_pct": mean(x["selected_return30_pct"] for x in observations) if observations else None,
            "mean_universe_return30_pct": mean(x["universe_return30_pct"] for x in observations) if observations else None,
            "mean_excess_btc_percentage_points": mean(x["selected_return30_pct"]-x["btc_return30_pct"] for x in observations) if observations else None,
            "mean_future_top3_capture_pct": mean(x["future_top3_capture_pct"] for x in observations) if observations else None,
            "limitation": "重叠30日窗口和存续币池的排序诊断，不是可复利收益或预测胜率"}


def regression_suite(snapshot, progress=print):
    history = History(snapshot)
    universe = sorted(snapshot["symbols"])
    end = history.as_of
    cases = []
    # Rules/profiles are fixed before this suite: no best-parameter selection.
    windows = [("2024", "2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
               ("2025", "2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
               ("2026_time_split", "2026-01-01T00:00:00+00:00", end)]
    for horizon in ("short_term", "long_term"):
        for profile in ("legacy", "balanced", "active"):
            policy = policy_for(profile)
            for label, start, finish in windows:
                progress(f"Regression {horizon} {profile} {label}")
                result = run_portfolio(history, universe, policy, horizon, start, finish, details=False)
                result["case"] = label
                cases.append(result)
    diagnostics = []
    for horizon in ("short_term", "long_term"):
        for label, symbols, policy in (
            ("active_full", universe, policy_for("active")),
            ("double_cost", universe, policy_for("active", fee_bps=20, slippage_bps=10)),
            ("without_zec", [s for s in universe if s != "ZECUSDT"], policy_for("active")),
        ):
            progress(f"Robustness {horizon} {label}")
            result = run_portfolio(history, symbols, policy, horizon, "2024-01-01T00:00:00+00:00", end,
                                   details=label == "active_full")
            result["case"] = label
            diagnostics.append(result)
    return {"snapshot_as_of": iso(snapshot["as_of"]), "universe": universe,
            "cases": cases, "robustness": diagnostics,
            "selection_diagnostic": selection_diagnostic(history, universe, policy_for("active")),
            "validation": "fixed_rules_temporal_regression_not_proven_out_of_sample"}


def regression_markdown(report):
    lines = ["# 选币与交易链路回归验收", "", f"数据截止 {report['snapshot_as_of']}，固定 {len(report['universe'])} 个 Binance USDT 现货。",
             "", "规则与档位固定后跑时间切分；2026 也包含设计者已知行情，不能当作独立未见样本。legacy 是旧入场规则在新组合执行器内的对照。",
             "", "| 周期 | 档位 | 时间段 | 净收益 | 最大收盘回撤 | 完整交易 | 加仓 | 分批止盈 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in report["cases"]:
        lines.append(f"| {r['horizon']} | {r['profile']} | {r['case']} | {r['net_return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['trade_count']} | {r['activity']['adds']} | {r['activity']['partial_exits']} |")
    lines += ["", "## 完整区间与压力测试", "", "| 周期 | 场景 | 净收益 | 最大收盘回撤 | 交易 | BTC买持 | 等权买持 | 初始60%等权买持 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in report["robustness"]:
        lines.append(f"| {r['horizon']} | {r['case']} | {r['net_return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['trade_count']} | {r['btc_buy_hold']['return_pct']:+.2f}% | {r['equal_weight_buy_hold']['return_pct']:+.2f}% | {r['exposure_matched_buy_hold']['return_pct']:+.2f}% |")
    diagnostic = report["selection_diagnostic"]
    lines += ["", "## 选币诊断", "", f"{diagnostic['count']} 个周度观察点：前三名随后30日平均收益 {diagnostic['mean_selected_return30_pct']:+.2f}%，同期可选池等权 {diagnostic['mean_universe_return30_pct']:+.2f}%；相对 BTC 平均差 {diagnostic['mean_excess_btc_percentage_points']:+.2f} 个百分点；事后前三名平均覆盖 {diagnostic['mean_future_top3_capture_pct']:.2f}%。",
              diagnostic["limitation"], "", "## 判读边界", "",
              "- 收益已扣单边10bps手续费和5bps滑点；双倍成本为20bps+10bps。没有搜索最佳参数或专门给ZEC加分。",
              "- 这是存续币池的历史验证，缺少已退市币，不能证明全市场长期有效。基准为固定初始仓位、无再平衡；60%基准不是逐时风险匹配。",
              "- 回撤暂停只限制新开仓，不是最大亏损保证；持仓仍可能亏损，跳空和市价漂移可越过风险额度。",
              "- 每笔成交、费用、现金权益、拒单和退出原因见同名JSON；active_full保存完整流水。",
              "- 短线成本翻倍后若转亏，应归为研究/模拟策略；长线相对更稳也不等于已获得可实盘盈利的证据。"]
    return "\n".join(lines)+"\n"
