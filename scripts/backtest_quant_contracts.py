#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.quant.futures_replay import research
if __name__=="__main__":
    result=research()
    for name,case in result["cases"].items():
        print(name,{k:case[k] for k in ("return_pct","max_drawdown_pct","intraday_stress_drawdown_pct","round_trips","fees","funding_net_paid")})
