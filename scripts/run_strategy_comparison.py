#!/usr/bin/env python3
"""Run a frozen offline Freqtrade comparison; never starts a trading bot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.core.runtime_config import get_runtime_settings

OUT=ROOT/"reports/quant_v5"
STRATEGIES=["MTF72h","MTFNoTime","MTFHourlyExit","MTFFourHourExit","Donchian20","Donchian55",
            "EMA4h","ADXBreakout1h","BollingerReversion15m","RSI2Pullback1h","BuyHold1x","NFI8Long1x","NFI7Long1x"]
WINDOWS={"full":"20260101-20260924","validation":"20260501-20260701","holdout":"20260701-20260924"}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(".tmp");temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n");temp.replace(path)


def config(strategy,run,fee):
    settings=get_runtime_settings()
    proxy={"httpProxy":settings.proxy_url} if settings.proxy_enabled else {}
    userdir=run/"user_data";userdir.mkdir(parents=True,exist_ok=True)
    return {"strategy":strategy,"max_open_trades":3,"stake_currency":"USDT","stake_amount":"unlimited",
            "tradable_balance_ratio":.7,"dry_run":True,"dry_run_wallet":10000,"fee":fee,
            "trading_mode":"futures","margin_mode":"isolated","timeframe":"5m","liquidation_buffer":.1,
            "dataformat_ohlcv":"feather","user_data_dir":str(userdir),"db_url":"sqlite://",
            "unfilledtimeout":{"entry":5,"exit":5,"unit":"minutes"},
            "entry_pricing":{"price_side":"other","use_order_book":True,"order_book_top":1},
            "exit_pricing":{"price_side":"other","use_order_book":True,"order_book_top":1},
            "order_types":{"entry":"market","exit":"market","emergency_exit":"market","stoploss":"market","stoploss_on_exchange":False},
            "exchange":{"name":"binance","key":"","secret":"","ccxt_config":{"enableRateLimit":True,**proxy},
                        "ccxt_async_config":{"enableRateLimit":True,**proxy},
                        "pair_whitelist":["BTC/USDT:USDT","ETH/USDT:USDT","ZEC/USDT:USDT"],"pair_blacklist":[]},
            "pairlists":[{"method":"StaticPairList"}],"telegram":{"enabled":False,"token":"","chat_id":""},
            "bot_name":"offline_strategy_comparison","force_entry_enable":False,
            "nfi_parameters":{"futures_mode_leverage":1.0,"futures_mode_leverage_rebuy_mode":1.0,"futures_mode_leverage_grind_mode":1.0}}


def load_result(directory,strategy):
    archives=sorted(directory.glob("*.zip"),key=lambda p:p.stat().st_mtime)
    if not archives:raise ValueError("No Freqtrade result archive")
    with zipfile.ZipFile(archives[-1]) as archive:
        names=[n for n in archive.namelist() if n.endswith(".json") and "_config" not in n and ".meta." not in n]
        for name in names:
            value=json.loads(archive.read(name))
            if "strategy" in value and strategy in value["strategy"]:
                return value["strategy"][strategy],str(archives[-1].relative_to(ROOT))
    raise ValueError("Strategy result absent")


def verify_inputs():
    protocol=json.loads((OUT/"strategy_protocol.json").read_text())
    source_hash=hashlib.sha256((ROOT/"research/strategies/ComparisonStrategies.py").read_bytes()).hexdigest()
    if source_hash!=protocol["source_sha256"]:
        raise RuntimeError("Frozen strategy changed: create a new experiment instead of mixing results")
    directory=OUT/"freqtrade_data"
    manifest=json.loads((directory/"manifest.json").read_text())
    for name,expected in manifest["output_hashes"].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError("Frozen market data changed: "+name)
    for name,expected in manifest["sources"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError("Source data changed: "+name)
    vendor=ROOT/"research/vendor/NostalgiaForInfinity"
    commit=subprocess.check_output(["git","-C",str(vendor),"rev-parse","HEAD"],text=True).strip()
    if commit!=protocol["nfi_commit"] or subprocess.call(["git","-C",str(vendor),"diff","--quiet","HEAD","--","NostalgiaForInfinityX7.py","NostalgiaForInfinityX8.py"]):
        raise RuntimeError("NFI source differs from the frozen commit")


def run_one(strategy,window,fee=.001):
    name=window+("_double_cost" if fee>.001 else "")
    run=OUT/"runs"/name/strategy
    done=run/"summary.json"
    if done.exists():
        cached=json.loads(done.read_text())
        with zipfile.ZipFile(ROOT/cached["archive"]) as archive:
            frozen_source=archive.read(next(n for n in archive.namelist() if n.endswith("_"+strategy+".py")))
        if frozen_source!=(ROOT/"research/strategies/ComparisonStrategies.py").read_bytes() or cached["fee"]!=fee:
            raise RuntimeError("Cached result identity mismatch: "+str(done))
        return cached
    run.mkdir(parents=True,exist_ok=True)
    (run/"result").mkdir(exist_ok=True)
    cfg=config(strategy,run,fee);write(run/"config.json",cfg)
    command=[str(ROOT/".venv.freqtrade-quant/bin/freqtrade"),"backtesting","-c",str(run/"config.json"),
             "--strategy-path",str(ROOT/"research/strategies"),"-s",strategy,
             "--datadir",str(OUT/"freqtrade_data"),"--userdir",str(run/"user_data"),
             "--timerange",WINDOWS[window],"--cache","none","--export","trades",
             "--backtest-directory",str(run/"result"),"--breakdown","month"]
    env={k:v for k,v in os.environ.items() if not k.upper().startswith("FREQTRADE__") and k.lower() not in {"http_proxy","https_proxy","all_proxy"}}
    env.update(PYTHONUNBUFFERED="1",OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",NUMEXPR_MAX_THREADS="2")
    started=time.time()
    write(OUT/"progress.json",{"phase":"backtesting","strategy":strategy,"window":name,"started_at_ms":int(started*1000),"log":str((run/"run.log").relative_to(ROOT))})
    print("RUN",name,strategy,flush=True)
    with (run/"run.log").open("w") as log:result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        write(run/"failure.json",{"exit_code":result.returncode,"duration_seconds":time.time()-started})
        raise RuntimeError(f"{strategy} {name} failed; see {run/'run.log'}")
    try:data,archive=load_result(run/"result",strategy)
    except ValueError as exc:
        write(run/"failure.json",{"exit_code":result.returncode,"duration_seconds":time.time()-started,"error":"No valid result archive; inspect run.log"})
        raise RuntimeError(f"No valid result for {strategy}; see {run/'run.log'}") from exc
    write(run/"trades.json",data["trades"])
    # Freqtrade's drawdown is based on realized trade returns; do not label it MTM.
    summary={k:data.get(k) for k in ["total_trades","profit_total","profit_total_abs","max_drawdown_account","max_relative_drawdown",
                 "profit_factor","winrate","holding_avg","backtest_start","backtest_end","results_per_pair","exit_reason_summary",
                 "market_change","total_volume","trades_per_day","sharpe","sortino"]}
    summary.update(strategy=strategy,window=name,fee=fee,archive=archive,duration_seconds=time.time()-started,
                   drawdown_definition="Freqtrade closed-trade metric; mark-to-market verification pending")
    write(done,summary)
    (run/"failure.json").unlink(missing_ok=True)
    print("DONE",name,strategy,round(100*data["profit_total"],2),"%",data["total_trades"],"trades",flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window",choices=[*WINDOWS,"all"],default="full")
    parser.add_argument("--strategies",nargs="+",choices=STRATEGIES,default=STRATEGIES)
    parser.add_argument("--double-cost",action="store_true")
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    protocol=OUT/"strategy_protocol.json"
    if not protocol.exists():
        source=ROOT/"research/strategies/ComparisonStrategies.py"
        write(protocol,{"frozen_before_first_run_ms":int(time.time()*1000),"strategies":STRATEGIES,"windows":WINDOWS,
              "capital":10000,"pairs":["BTC","ETH","ZEC"],"leverage":1,"direction":"long_only","wallet_budget":.7,
              "base_fee_including_execution_cost_allowance":.001,"double_cost":.002,
              "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"nfi_commit":"3cc57f3cb1d0775c78f6e01537a0de2272339326",
              "selection":"Compare fixed variants on validation, then inspect held-out July-Sep; no hyperparameter search. Full-window statistics are descriptive, not the selection score.",
              "limitations":["Three user-selected survivors; does not validate full-universe selection","External strategy authors may have optimized on these historical periods; calendar holdout is not proven novel to them",
                  "NFI wrappers constrain original futures defaults to long-only 1x and per-pair budget; this is not upstream default performance",
                  "NFI recommends a larger pair pool; three-pair test is a constrained diagnostic","5m OHLC fills, no order-book reconstruction; combined fee proxy is not true variable slippage",
                  "Candidates do not apply the live core holding exemptions because the experiment compares their exit rules"]})
    verify_inputs()
    windows=list(WINDOWS) if args.window=="all" else [args.window]
    for window in windows:
        for strategy in args.strategies:run_one(strategy,window,.002 if args.double_cost else .001)
    write(OUT/"progress.json",{"phase":"requested_runs_complete","window":args.window,"strategies":args.strategies})


if __name__=="__main__":main()
