#!/usr/bin/env python3
"""Compare MTF rotation and the requested core/satellite policy on one frozen sample."""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.runtime_config import get_runtime_settings
from app.quant.mtf_replay import replay
from app.quant.policy import load_policy
from app.quant.service import ROOT, atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data",type=Path,default=ROOT/"reports/quant_v4/policy_sample")
    parser.add_argument("--output",type=Path,default=ROOT/"reports/quant_v4/policy_comparison.json")
    args=parser.parse_args()
    policy=load_policy(get_runtime_settings())
    available={p.stem for p in (args.data/"15m").glob("*.json")}
    if set(policy.preferred_symbols)-available:raise SystemExit("Missing preferred histories; comparison not run")
    cases={}
    for name,p,cost in (("mtf_rotation",None,5),("core_satellite",policy,5),("core_satellite_double_cost",policy,10)):
        result=replay(args.data,cost,cost,policy=p)
        cases[name]=result
        print(f"{name}: {result['fills']} fills; net {result['net_return_pct']:.2f}%; sampled DD {result['sampled_close_drawdown_pct']:.2f}%")
    atomic_json(args.output,{"purpose":"short_sample_integration_comparison_not_strategy_validation",
                            "policy_revision":policy.revision(),"baseline_max_positions":get_runtime_settings().quant_max_positions,
                            "data_hashes":{str(p.relative_to(args.data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.data.rglob("*.json")},
                            "cases":cases})
    print("Same frozen data and costs; not evidence of future profit. "+str(args.output))


if __name__=="__main__":main()
