#!/usr/bin/env python3
"""Frozen v6: strategy-specific stop ablations, offline only, resumable runs."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from run_strategy_comparison import config, load_result, verify_inputs, write
from stop_provenance import verify_run, verify_seal, engine_version

OUT = ROOT / "reports/quant_v6"
FAMILIES = {"D55": "Donchian55", "E4": "EMA4h", "A1": "ADXBreakout1h", "M4": "MTFFourHourExit"}
POLICIES = ["Legacy", "Wide", "Fixed", "ClosedTrail", "Structure"]
STRATEGIES = [family + policy for family in FAMILIES for policy in POLICIES]
WINDOWS = {"development": "20260101-20260501", "validation": "20260501-20260701",
           "reused_holdout": "20260701-20260924", "full": "20260101-20260924",
           "challenge2025": "20250101-20260101"}
SOURCES = ["research/strategies/ComparisonStrategies.py", "research/strategies/StopComparisonStrategies.py",
           "app/quant/stop_profiles.py"]


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in SOURCES}
    path = OUT / "protocol.json"
    if path.exists():
        if json.loads(path.read_text())["sources"] != sources:
            raise RuntimeError("v6 sources changed after freeze; do not mix experiment revisions")
        return
    write(path, {"frozen_ms": int(time.time() * 1000), "sources": sources, "strategies": STRATEGIES,
        "families": FAMILIES, "windows": WINDOWS, "fees": [.001, .002], "leverage": 1,
        "capital": 10000, "wallet_budget": .7, "max_retained": 3,
        "stop_profiles": {"Legacy": "Unchanged v5 intrabar high, initial2.5/trail3 ATR",
            "Wide": "Only ATR distances changed to initial4/trail5; same intrabar-high assumption",
            "Fixed": "Entry-time 3.5 strategy-frame ATR, no stop ratchet, same signal exits",
            "ClosedTrail": "Entry3.5ATR; activate after2 entryATR profit in completed strategy candles; closed-high minus4 currentATR",
            "Structure": "Previous10 completed strategy lows minus0.5ATR; monotone updates after completed strategy bars"},
        "selection_rule": "For each family choose at most one policy with positive net returns in development and validation, positive double-cost validation, <=35% sampled mark DD in each, >=12 combined development+validation trades, reconciled cash flows. Rank by minimum of per-day log return divided by (0.05+drawdown) across these 3 cases, then retain top3 families. If none qualify, retain watchlist without promoting.",
        "promotion_rule": "Selected candidates also need positive reused-holdout and challenge2025 returns under base and double cost, <=35% drawdown and >=10 trades in each independent period. These are historical research gates only; keep live disabled. New forward observations are still required.",
        "limitations": ["All 2026 data was inspected in v5: July-Sep is reused historical validation, NOT a new untouched holdout",
            "2025 is a newly inspected historical challenge, not true live forward performance",
            "20 fixed stop variants, no search or retuning after seeing results",
            "Same family entry and non-stop exits preserved; ClosedTrail/Structure differ in ratchet timing as disclosed",
            "OHLC fills retain Freqtrade gap and within-bar assumptions; no exchange tick reconstruction",
            "Three user-picked coins do not establish performance for the full Binance contract universe"]})


def run_one(strategy, window, fee):
    name = window + ("_double_cost" if fee > .001 else "")
    run = OUT / "runs" / name / strategy
    done = run / "summary.json"
    datadir = (OUT / "challenge_data/freqtrade_data") if window == "challenge2025" else ROOT / "reports/quant_v5/freqtrade_data"
    if not (datadir / "manifest.json").exists():
        raise RuntimeError("Verified dataset not ready: " + str(datadir))
    identity = {"sources": json.loads((OUT / "protocol.json").read_text())["sources"],
                "dataset_manifest": hashlib.sha256((datadir / "manifest.json").read_bytes()).hexdigest(),
                "strategy": strategy, "window": window, "fee": fee}
    if done.exists():
        cached = json.loads(done.read_text())
        if cached.get("identity") != identity:
            raise RuntimeError("Cached stop result identity mismatch: " + str(done))
        verify_run(run, json.loads((OUT / "protocol.json").read_text()),
                   expected_config=config(strategy, run, fee), version=engine_version())
        return cached
    run.mkdir(parents=True, exist_ok=True)
    (run / "result").mkdir(exist_ok=True)
    write(run / "config.json", config(strategy, run, fee))
    command = [str(ROOT / ".venv.freqtrade-quant/bin/freqtrade"), "backtesting", "-c", str(run / "config.json"),
        "--strategy-path", str(ROOT / "research/strategies"), "-s", strategy, "--datadir", str(datadir),
        "--userdir", str(run / "user_data"), "--timerange", WINDOWS[window], "--cache", "none",
        "--export", "trades", "--backtest-directory", str(run / "result"), "--breakdown", "month"]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("FREQTRADE__")
           and k.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env.update(PYTHONUNBUFFERED="1", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", NUMEXPR_MAX_THREADS="2")
    started = time.time()
    write(OUT / "progress.json", {"state": "running", "pid": os.getpid(), "strategy": strategy,
                                  "window": name, "started_ms": int(started * 1000)})
    print("RUN", name, strategy, flush=True)
    with (run / "run.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if result.returncode:
            raise ValueError("Process exit " + str(result.returncode))
        data, archive = load_result(run / "result", strategy)
        # Freqtrade catches strategy callback exceptions. Such a run is invalid.
        log = (run / "run.log").read_text()
        if "Traceback (most recent call last)" in log or " - ERROR - " in log:
            raise ValueError("Strategy/runtime error in run.log")
    except ValueError as exc:
        write(run / "failure.json", {"error": str(exc), "at_ms": int(time.time() * 1000)})
        raise RuntimeError(f"Invalid stop backtest: {run/'run.log'}") from exc
    write(run / "trades.json", data["trades"])
    summary = {k: data.get(k) for k in ["total_trades", "profit_total", "profit_total_abs", "max_drawdown_account",
        "profit_factor", "winrate", "holding_avg", "backtest_start", "backtest_end", "results_per_pair", "exit_reason_summary"]}
    summary.update(strategy=strategy, window=name, fee=fee, archive=archive, identity=identity,
                   duration_seconds=time.time()-started, drawdown_definition="Engine wallet balance; MTM reconstruction required")
    write(done, summary)
    (run / "failure.json").unlink(missing_ok=True)
    print("DONE", name, strategy, round(data["profit_total"]*100, 2), "%", data["total_trades"], "trades", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", nargs="+", choices=WINDOWS, default=["development", "validation"])
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=STRATEGIES)
    parser.add_argument("--double-cost", action="store_true")
    args = parser.parse_args()
    freeze()
    verify_seal()
    with (OUT / "runner.lock").open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit("A v6 research runner already holds the lock") from None
        verify_inputs()
        if "challenge2025" in args.windows:
            directory=OUT/"challenge_data/freqtrade_data"
            manifest=json.loads((directory/"manifest.json").read_text())
            for name,expected in manifest["output_hashes"].items():
                if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected:
                    raise RuntimeError("Challenge market data changed: "+name)
        for window in args.windows:
            for strategy in args.strategies:
                run_one(strategy, window, .002 if args.double_cost else .001)
        write(OUT / "progress.json", {"state": "complete", "windows": args.windows,
              "strategies": args.strategies, "double_cost": args.double_cost, "completed_ms": int(time.time()*1000)})


if __name__ == "__main__": main()
