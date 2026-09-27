#!/usr/bin/env python3
"""Reconcile stop ablations, freeze shortlists, maintain a small research registry."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import analyze_strategy_comparison as accounting
from stop_provenance import dataset_hashes, verify_run, verify_seal

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_v6"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    accounting.write(path, value)


def challenge_data():
    directory = OUT / "challenge_data"
    data = {}
    for pair in accounting.PAIRS:
        symbol = pair.split("/")[0] + "USDT"
        rows = json.loads((directory / f"series/markPriceKlines/5m/{symbol}.json").read_text())["rows"]
        raw = json.loads((directory / f"funding/{symbol}.json").read_text())["rates"]
        data[pair] = ({int(r[0]): float(r[4]) for r in rows},
            [(int(r["fundingTime"]) // 3_600_000 * 3_600_000, float(r["fundingRate"]) * float(r["markPrice"])) for r in raw])
    return data


def checked(row):
    m = row["mark_metrics"]
    return m["reconciled"] and m["return_pct"] > 0 and m["sampled_mark_drawdown_pct"] <= 35


def select(rows, protocol):
    by_key = {(r["window"], r["strategy"]): r for r in rows}
    cases = ["development", "validation", "validation_double_cost"]
    if any((w, s) not in by_key for w in cases for s in protocol["strategies"]):
        raise ValueError("All 20 candidates need development, validation and validation double-cost results before selecting")
    selections = []
    decisions = []
    for strategy in protocol["strategies"]:
        evaluated = [by_key[(w, strategy)] for w in cases]
        enough = evaluated[0]["total_trades"] + evaluated[1]["total_trades"] >= 12
        eligible = all(map(checked, evaluated)) and enough
        score = min(math.log1p(r["mark_metrics"]["return_pct"] / 100)
            / (120 if r["window"] == "development" else 61)
            / (.05 + r["mark_metrics"]["sampled_mark_drawdown_pct"] / 100) for r in evaluated) if eligible else None
        reason = [r["window"] + ": nonpositive return, >35% DD or failed reconciliation"
                  for r in evaluated if not checked(r)]
        if not enough: reason.append("fewer than12 combined development/validation trades")
        decisions.append({"strategy": strategy, "family": strategy[:2] if strategy[:2] != "D5" else "D55",
                          "eligible": eligible, "score": score, "rejections": reason})
    for family in protocol["families"]:
        family_rows = [d for d in decisions if d["family"] == family and d["eligible"]]
        if family_rows:
            selections.append(max(family_rows, key=lambda d: (d["score"], d["strategy"])))
    retained = sorted(selections, key=lambda d: (-d["score"], d["strategy"]))[:protocol["max_retained"]]
    return {"selected_ms": int(time.time()*1000), "rules": protocol["selection_rule"],
            "selection_windows": cases, "retained": retained, "decisions": decisions,
            "sources": protocol["sources"], "not_used_for_selection": ["reused_holdout", "challenge2025", "full"],
            "status": "historical_screen_complete" if retained else "no_candidate_passed; do not relax criteria after seeing results"}


def registry(rows, shortlist, protocol):
    by_key = {(r["window"], r["strategy"]): r for r in rows}
    required = ["reused_holdout", "reused_holdout_double_cost", "challenge2025", "challenge2025_double_cost"]
    entries = []
    for selected in shortlist["retained"]:
        strategy = selected["strategy"]
        missing = [w for w in required if (w, strategy) not in by_key]
        failed = [w for w in required if (w, strategy) in by_key and
                  (not checked(by_key[(w, strategy)]) or by_key[(w, strategy)]["total_trades"] < 10)]
        status = "historical_gates_failed" if failed else "awaiting_challenge" if missing else "historical_gates_passed"
        entries.append({**selected, "status": status, "missing": missing, "failed": failed,
                        "execution": "research_only", "forward_status": "not_started",
                        "note": "This is a retained research candidate, not permission to replace the paper or live account"})
    return {"updated_ms": int(time.time()*1000), "limit": protocol["max_retained"], "entries": entries,
            "live_enabled": False, "paper_strategy_replaced": False,
            "promotion_rule": protocol["promotion_rule"]}


def report(rows, shortlisted, registered):
    by_key = {(r["window"], r["strategy"]): r for r in rows}
    text = ["# 策略级止损优化 v6", "", f"已完成 {len(rows)} 组可复查回测。所有回撤按5m标记价并包含浮亏重建；收益为净账户收益。", "",
        "20个预先固定版本：4种入场/趋势退出逻辑 × 5种止损。Legacy保留原引擎追踪，Wide仅放宽到4/5ATR；Fixed固定初始3.5ATR；ClosedTrail等待闭合策略周期盈利2ATR后以4ATR追踪；Structure按10根结构低点加0.5ATR缓冲。后三者不使用当前5m高点抬止损，跳空低于有效止损时按开盘退出。", "",
        "初始10,000 USDT，仅多1x，70%预算；双边各10bps综合成本代理，压力20bps，真实资金费另计。与当前优选70%上限/免止损持有政策不同。", "",
        "2026年数据已经在v5看过，7–9月是重复历史检验，不再称为未见过的样本外数据。2025年为另外下载的历史压力区间，也不能替代未来真实模拟。", "",
        "| 策略 | 1–4月净收益 / 回撤 | 5–6月净收益 / 回撤 | 5–6月双倍费用 | 7–9月再检验 | 2025压力 |", "|---|---:|---:|---:|---:|---:|"]
    def cell(window, strategy, dd=False):
        r = by_key.get((window, strategy))
        if r is None: return "待跑"
        m = r["mark_metrics"]
        value = f'{m["return_pct"]:.2f}%'
        return value + (f' / {m["sampled_mark_drawdown_pct"]:.2f}%' if dd else "")
    for strategy in json.loads((OUT / "protocol.json").read_text())["strategies"]:
        text.append("| " + strategy + " | " + " | ".join([cell("development", strategy, True), cell("validation", strategy, True),
            cell("validation_double_cost", strategy), cell("reused_holdout", strategy), cell("challenge2025", strategy)]) + " |")
    text += ["", "## 筛选保留", ""]
    if shortlisted is None:
        text.append("筛选段和成本压力尚未跑齐，暂不选赢家。")
    elif not shortlisted["retained"]:
        text.append("本批没有策略通过预设筛选条件；没有在看到结果后降低标准。")
    else:
        for entry in registered["entries"]:
            text.append(f'- {entry["strategy"]}：{entry["status"]}；待完成 {entry["missing"]}；未通过 {entry["failed"]}。')
    text += ["", "研究尚未替换原模拟策略或启用实盘。每组`runs/<window>/<strategy>`保留订单、费用、止损原因和完整盯市曲线；`selection.json`锁定筛选决定，`registry.json`记录最多3个保留版本和挑战关卡。", "",
             "`invalidated/pre_gap_fix`保留发现跳空处理缺陷后废弃的早期试跑，完全不参与本报告。", ""]
    (OUT / "REPORT.md").write_text("\n".join(text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", action="store_true")
    args = parser.parse_args()
    protocol = json.loads((OUT / "protocol.json").read_text())
    verify_seal()
    dataset_hashes(include_challenge=any((OUT / "runs").glob("challenge2025*/*/summary.json")))
    for name, expected in protocol["sources"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen source changed: " + name)
    data2026 = accounting.load_data()
    data2025 = None
    accounting.WINDOWS = {name: tuple(datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d") for s in window.split("-"))
                          for name, window in protocol["windows"].items()}
    rows = []
    for summary in sorted((OUT / "runs").glob("*/*/summary.json")):
        verify_run(summary.parent, protocol)
        if summary.parent.parent.name.startswith("challenge2025"):
            if data2025 is None: data2025 = challenge_data()
            data = data2025
        else: data = data2026
        row = accounting.analyze(summary.parent, data)
        rows.append(row)
        m = row["mark_metrics"]
        print(row["window"], row["strategy"], round(m["return_pct"], 2),
              "DD", round(m["sampled_mark_drawdown_pct"], 2), m["reconciled"], flush=True)
    write(OUT / "comparison.json", {"rows": rows, "protocol": protocol})
    selected = json.loads((OUT / "selection.json").read_text()) if (OUT / "selection.json").exists() else None
    # Re-derive the original decision on every analysis, never use later challenge
    # returns to silently choose a different winner from the existing shortlist.
    if selected is not None:
        derived = select(rows, protocol)
        for field in ("sources", "rules", "retained", "decisions", "selection_windows"):
            if selected[field] != derived[field]:
                raise ValueError("Frozen selection no longer matches verified inputs: " + field)
    if args.select:
        if selected is None:
            selected = select(rows, protocol)
            write(OUT / "selection.json", selected)
        elif selected["sources"] != protocol["sources"]:
            raise ValueError("Selection source mismatch")
    registered = registry(rows, selected, protocol) if selected else None
    if registered: write(OUT / "registry.json", registered)
    report(rows, selected, registered)


if __name__ == "__main__": main()
