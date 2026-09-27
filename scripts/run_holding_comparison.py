#!/usr/bin/env python3
"""Freeze and run v7 holding controls; no portfolio or live strategy changes."""
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
from run_strategy_comparison import config, load_result, write
from stop_provenance import verify_seal, dataset_hashes, economic_config, engine_version, sha

OUT = ROOT / "reports/quant_v7"
STRATEGIES = ["HoldEqual", "HoldZecSlice", "HoldZec70", "M4HoldEntry", "A1HoldEntry", "D55HoldEntry",
              "M4SlowHold", "A1SlowHold", "D55SlowHold"]
WINDOWS = {"development":"20260101-20260501", "validation":"20260501-20260701",
    "reused_holdout":"20260701-20260924", "full":"20260101-20260924", "challenge2025":"20250101-20260101"}


def freeze():
    verify_seal(required=True)
    data = dataset_hashes()
    sources = {p: sha(ROOT/p) for p in ["research/strategies/HoldingComparisonStrategies.py",
        "research/strategies/ComparisonStrategies.py", "scripts/run_holding_comparison.py",
        "scripts/run_strategy_comparison.py", "scripts/analyze_strategy_comparison.py"]}
    value = {"strategies": STRATEGIES, "windows": WINDOWS, "sources": sources, "data": data,
        "engine_version": engine_version(), "capital":10000, "direction":"long_only", "leverage":1,
        "fees":[.001,.002], "wallet_budget":.7,
        "allocation": {"HoldZec70":"70% initial ZEC / 30% cash; concentrated diagnostic, not current single-coin cap",
            "HoldZecSlice":"23.33% initial ZEC / remaining cash; budget_per_pair stays /3",
            "others":"70% total, <=23.33% per BTC/ETH/ZEC, no dynamic buy-and-hold weight rebalance"},
        "exit_rule":"HoldEntry keeps original entry then holds until window end. SlowHold exits after two closed 4h candles below EMA200. All six disable ATR trailing and time exits; engine emergency stop is 99%, still long 1x. This is a deliberate high-drawdown research control, not a forward deployment.",
        "assessment":"Passive holding is an eligible alternative. First compare same-window/same-capital equal-three holding with active candidates, returns AND full MTM drawdown. Report return gap and capture ratio. No requirement to earn in every short subperiod. 50% historical drawdown is the user's research tolerance, not a guaranteed future ceiling; reject candidates above it for promotion. Do not select winners by the July rally alone. No automatic replacement or live orders.",
        "limitations":["These periods have already been inspected; v7 is an explicitly post-hoc diagnostic responding to missed trends, not fresh OOS proof",
            "ZEC70 differs in concentration and is never ranked as risk-equivalent to three equal allocations",
            "Holding from a historical start is a benchmark, not proof the bot would have selected ZEC then",
            "No parameter grid search; retain original entries, compare only predeclared holding exits",
            "Three chosen survivors cannot validate full-universe selection; long-only holding can suffer large bear-market losses"]}
    path=OUT/"protocol.json"
    OUT.mkdir(parents=True,exist_ok=True)
    if path.exists():
        prior=json.loads(path.read_text())
        if {k:v for k,v in prior.items() if k!="frozen_ms"}!=value:
            raise ValueError("Holding protocol changed after freeze")
    else:write(path,{"frozen_ms":int(time.time()*1000),**value})
    return value


def run_one(strategy, window, fee, protocol):
    name=window+("_double_cost" if fee>.001 else "")
    run=OUT/"runs"/name/strategy
    run.mkdir(parents=True,exist_ok=True)
    cfg=config(strategy,run,fee)
    for key in ("ccxt_config","ccxt_async_config"):
        proxy=cfg["exchange"][key].pop("httpProxy",None)
        if proxy:cfg["exchange"][key]["httpsProxy"]=proxy
    if strategy in {"HoldZec70","HoldZecSlice"}:
        cfg["exchange"]["pair_whitelist"]=["ZEC/USDT:USDT"]
        if strategy=="HoldZec70":cfg["max_open_trades"]=1
    data=ROOT/("reports/quant_v6/challenge_data/freqtrade_data" if window=="challenge2025" else "reports/quant_v5/freqtrade_data")
    identity={"sources":protocol["sources"], "data_manifest":sha(data/"manifest.json"),
        "timerange":WINDOWS[window], "engine_version":protocol["engine_version"], "config":economic_config(cfg)}
    summary=run/"summary.json"
    if summary.exists():
        saved=json.loads(summary.read_text())
        if saved.get("identity")!=identity:raise ValueError("Cached holding result identity changed")
        for path,expected in saved["artifacts"].items():
            if sha(ROOT/path)!=expected:raise ValueError("Cached result artifact changed: "+path)
        return
    write(run/"config.json",cfg)
    (run/"result").mkdir(exist_ok=True)
    command=[str(ROOT/".venv.freqtrade-quant/bin/freqtrade"),"backtesting","-c",str(run/"config.json"),
        "--strategy-path",str(ROOT/"research/strategies"),"-s",strategy,"--datadir",str(data),
        "--timerange",WINDOWS[window],"--cache","none","--export","trades","--backtest-directory",str(run/"result")]
    env={k:v for k,v in os.environ.items() if not k.upper().startswith("FREQTRADE__")
         and k.lower() not in {"http_proxy","https_proxy","all_proxy"}}
    env.update(PYTHONUNBUFFERED="1",OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2")
    write(OUT/"progress.json",{"state":"running","pid":os.getpid(),"strategy":strategy,"window":name})
    print("RUN",name,strategy,flush=True)
    with (run/"run.log").open("w") as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    log=(run/"run.log").read_text()
    if result.returncode or " - ERROR - " in log or "Traceback (most recent call last)" in log:
        raise RuntimeError("Holding backtest failed: "+str(run/"run.log"))
    result, archive=load_result(run/"result",strategy)
    with zipfile.ZipFile(ROOT/archive) as z:
        source=z.read(next(n for n in z.namelist() if n.endswith("_"+strategy+".py")))
        if source!=(ROOT/"research/strategies/HoldingComparisonStrategies.py").read_bytes():
            raise ValueError("Engine archive source mismatch")
    if result["timerange"]!=WINDOWS[window]:raise ValueError("Timerange mismatch")
    write(run/"trades.json",result["trades"])
    data={k:result.get(k) for k in ["total_trades","profit_total","profit_total_abs","max_drawdown_account",
          "profit_factor","winrate","holding_avg","backtest_start","backtest_end","exit_reason_summary","results_per_pair"]}
    artifacts={str(p.relative_to(ROOT)):sha(p) for p in [run/"config.json",run/"trades.json",run/"run.log",ROOT/archive]}
    write(summary,{**data,"strategy":strategy,"window":name,"fee":fee,"archive":archive,"identity":identity,"artifacts":artifacts})
    print("DONE",name,strategy,round(result["profit_total"]*100,2),result["total_trades"],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows",nargs="+",choices=WINDOWS,default=list(WINDOWS))
    parser.add_argument("--strategies",nargs="+",choices=STRATEGIES,default=STRATEGIES)
    parser.add_argument("--double-cost",action="store_true")
    args=parser.parse_args()
    protocol=freeze()
    with (OUT/"runner.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("Holding study is already running") from None
        for window in args.windows:
            for strategy in args.strategies:run_one(strategy,window,.002 if args.double_cost else .001,protocol)
        write(OUT/"progress.json",{"state":"complete","windows":args.windows,"strategies":args.strategies})


if __name__=="__main__":main()
