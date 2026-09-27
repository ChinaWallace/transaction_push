#!/usr/bin/env python3
"""Read-only scan/replay command; does not load .env or start schedulers."""

import argparse
import hashlib
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.advisory.engine import policy_for, normalize_symbol
from app.advisory.market import BinancePublicClient, markdown_report, scan_market
from app.advisory.replay import replay_ranking, replay_symbol
from app.advisory.backtest import History, run_portfolio, regression_suite, regression_markdown
from app.advisory.paper import PaperLedger, DEFAULT_DB, paper_cycle


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["scan", "replay", "portfolio", "regression", "paper", "paper-status"])
    parser.add_argument("--watch", nargs="+", default=["ZECUSDT"])
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "LINKUSDT"])
    parser.add_argument("--top", type=int, default=60)
    parser.add_argument("--horizon", choices=["short_term", "long_term"], default="short_term")
    parser.add_argument("--output", type=Path, default=Path("reports/advisory"))
    parser.add_argument("--input", type=Path, help="Replay a previously saved public market snapshot")
    parser.add_argument("--profile", choices=["active", "balanced", "legacy"], default="active")
    parser.add_argument("--start", default="2024-01-01T00:00:00+00:00")
    parser.add_argument("--end", help="Exclusive UTC ISO timestamp; default snapshot cutoff")
    parser.add_argument("--cash", type=float, default=10000)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repeat-seconds", type=int, default=0, help="Paper only: poll >=60 seconds until Ctrl-C")
    args = parser.parse_args()
    if args.mode in {"portfolio", "regression"} and not args.input:
        parser.error("portfolio/regression requires --input with a historical snapshot")
    args.output.mkdir(parents=True, exist_ok=True)
    policy = policy_for(args.profile, max_candidates=args.top)
    if args.repeat_seconds and (args.mode != "paper" or args.repeat_seconds < 60):
        parser.error("--repeat-seconds requires paper and >=60")
    if args.mode == "paper-status":
        print(json.dumps(PaperLedger(args.ledger).status(args.profile, args.horizon), ensure_ascii=False, indent=2))
        return 0
    if args.mode == "paper":
        ledger = PaperLedger(args.ledger)
        while True:
            research, result = paper_cycle(args.watch, args.top, args.profile, args.horizon, ledger, args.cash)
            save_json(args.output / f"paper_{args.horizon}.json", result)
            save_json(args.output / "latest.json", research)
            (args.output / "latest.md").write_text(markdown_report(research), encoding="utf-8")
            print(f"PAPER {result['observed_at']}: equity={result['equity']:.2f}, positions={len(result['positions'])}, new fills={len(result['new_events'])}", flush=True)
            if not args.repeat_seconds:
                return 0
            time.sleep(args.repeat_seconds)
    if args.mode == "scan":
        report = scan_market(args.watch, policy)
        save_json(args.output / "latest.json", report)
        (args.output / "latest.md").write_text(markdown_report(report), encoding="utf-8")
        print(f"{report['status']}: {report['analyzed_count']}/{report['scan_count']} analyzed; {args.output / 'latest.md'}")
        return 0 if report["ranking"] else 1
    if args.input:
        snapshot = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        client = BinancePublicClient()
        snapshot = {"as_of": int(client.get("time")["serverTime"]), "source": client.base_url, "symbols": {}}
        for symbol in dict.fromkeys(["BTCUSDT", *(normalize_symbol(s) for s in args.symbols)]):
            snapshot["symbols"][symbol] = {
                interval: client.candles(symbol, interval, limit=1000, end_time=snapshot["as_of"])
                for interval in ("1d", "4h")}
        save_json(args.output / "replay_input.json", snapshot)
    if args.mode == "regression":
        source_paths = [Path(__file__).resolve().parents[1] / f"app/advisory/{name}.py" for name in ("engine", "portfolio", "backtest")]
        hashes = {str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
        result = regression_suite(snapshot)
        current = {str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
        if current != hashes:
            raise RuntimeError("Strategy changed during regression; rerun required")
        result["source_sha256"] = hashes
        result["snapshot_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        save_json(args.output / "v2_regression.json", result)
        (args.output / "v2_regression.md").write_text(regression_markdown(result), encoding="utf-8")
        return 0
    if args.mode == "portfolio":
        result = run_portfolio(History(snapshot), sorted(snapshot["symbols"]), policy, args.horizon,
                               args.start, args.end or snapshot["as_of"], args.cash)
        save_json(args.output / f"portfolio_{args.horizon}.json", result)
        print(f"{result['trade_count']} trades; return {result['net_return_pct']:.2f}%; drawdown {result['max_drawdown_pct']:.2f}%")
        return 0
    results = []
    for symbol in dict.fromkeys(normalize_symbol(s) for s in args.symbols):
        data = snapshot["symbols"][symbol]
        result = replay_symbol(symbol, data["1d"], data["4h"], snapshot["symbols"]["BTCUSDT"]["1d"],
                               snapshot["as_of"], args.horizon, policy)
        results.append(result)
        print(f"{symbol} {args.horizon}: {result['trade_count']} trades; return {result['net_return_pct']}%; drawdown {result['max_close_equity_drawdown_pct']}%")
    save_json(args.output / f"replay_{args.horizon}.json", {"results": results, "policy": asdict(policy)})
    ranking = replay_ranking(snapshot, [normalize_symbol(s) for s in args.symbols], policy)
    save_json(args.output / "ranking_replay.json", ranking)
    print(f"Ranking diagnostic: {ranking['matured_count']} matured weekly observations; survivor-selected universe, not out-of-sample")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
