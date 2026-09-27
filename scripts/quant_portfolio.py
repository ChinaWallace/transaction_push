#!/usr/bin/env python3
"""All-contract research and local futures paper portfolio. Never sends exchange orders."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.quant.service import DATA, OUTPUT, FuturesLedger, atomic_json, read, scan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["collect","cycle","scan","paper-step","paper-status","export-freqtrade"])
    parser.add_argument("--data",type=Path,default=DATA)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--capital",type=float,default=10000)
    parser.add_argument("--funding",type=Path,help="Actual funding events plus per-symbol start/end/complete coverage envelopes")
    args=parser.parse_args()
    if args.command=="cycle":
        from app.quant.runtime import cycle
        print(json.dumps(cycle(directory=args.data,output=args.output,capital=args.capital),ensure_ascii=False,indent=2,allow_nan=False))
        return
    if args.command=="paper-status":
        result=FuturesLedger(args.output/"paper.sqlite3",args.capital).status()
    else:
        from app.quant.runtime import writer_lock
        with writer_lock(args.output):result=run_command(args)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


def run_command(args):
    ledger=FuturesLedger(args.output/"paper.sqlite3",args.capital)
    if args.command=="collect":
        from app.quant.market import collect
        return collect(args.data)
    if args.command=="scan":
        report=scan(args.data,args.output,args.capital)
        return {"coverage":report["coverage"],"plan":report["plan"],"snapshot_fresh":report["snapshot_fresh"]}
    if args.command=="paper-step":
        report=scan(args.data,args.output,args.capital)
        result=ledger.step(report,funding=read(args.funding) if args.funding else None)
        atomic_json(args.output/"paper_latest.json",result)
        return result
    report=scan(args.data,args.output,args.capital)
    if report["plan"].get("strategy_schema")==4:
        raise ValueError("The legacy Freqtrade bridge only supports daily v3 plans; use quant.sh for v4 paper execution")
    root=Path(__file__).resolve().parents[1]
    config=read(root/"freqtrade/user_data/config.quant_v3.dryrun.example.json")
    config["quant_plan_path"]=str((args.output/"plan.json").resolve())
    pair_by_symbol={r["symbol"]:r["base_asset"]+"/USDT:USDT" for r in report["ranking"]}
    config["exchange"]["pair_whitelist"]=sorted({t["pair"] for t in report["plan"]["targets"]}|{pair_by_symbol[s] for s in ledger.status()["positions"] if s in pair_by_symbol})
    atomic_json(args.output/"freqtrade.dryrun.json",config)
    return {"config":str(args.output/"freqtrade.dryrun.json"),"dry_run":True,"pairs":config["exchange"]["pair_whitelist"]}


if __name__=="__main__":main()
