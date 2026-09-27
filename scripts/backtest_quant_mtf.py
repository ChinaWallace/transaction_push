#!/usr/bin/env python3
"""Replay locally collected multi-timeframe history with real funding coverage."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.quant.mtf_replay import replay
from app.quant.service import ROOT, atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=ROOT/'reports/quant_v4/sample')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/quant_v4/sample_replay.json')
    args=parser.parse_args()
    result={'base':replay(args.data),'double_cost':replay(args.data,10,10)}
    atomic_json(args.output,result)
    for name,r in result.items():
        print(f"{name}: {r['from']} → {r['through']}; {len(r['symbols'])} symbols; {r['fills']} fills; return {r['net_return_pct']:.2f}%; sampled DD {r['sampled_close_drawdown_pct']:.2f}%")
    print('Short integration sample only; not strategy profitability validation. '+str(args.output))

if __name__=='__main__':main()
