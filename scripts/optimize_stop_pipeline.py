#!/usr/bin/env python3
"""Resume the frozen stop study and its independent historical challenges."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
from stop_provenance import verify_seal

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports/quant_v6"
RESEARCH_PYTHON=ROOT/".venv.freqtrade-quant/bin/python"


def run(*args):
    subprocess.run(list(map(str,args)),cwd=ROOT,check=True)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/"pipeline.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("Stop research pipeline is already running") from None
        verify_seal()
        if not RESEARCH_PYTHON.exists():raise SystemExit("Freqtrade research environment is missing")
        run(sys.executable,"scripts/run_stop_comparison.py","--windows","development","validation")
        run(sys.executable,"scripts/run_stop_comparison.py","--windows","validation","--double-cost")
        run(RESEARCH_PYTHON,"scripts/analyze_stop_comparison.py","--select")
        selected=json.loads((OUT/"selection.json").read_text())["retained"]
        # Keep all four unchanged controls. Do not pick challengers using the
        # performance of these later challenge windows.
        strategies=sorted({s["strategy"] for s in selected}|{"D55Legacy","E4Legacy","A1Legacy","M4Legacy"})
        if not (OUT/"challenge_data/freqtrade_data/manifest.json").exists():
            run(sys.executable,"scripts/prepare_stop_challenge_data.py")
        for double_cost in (False,True):
            command=[sys.executable,"scripts/run_stop_comparison.py","--windows","reused_holdout","challenge2025",
                     "--strategies",*strategies]
            if double_cost:command.append("--double-cost")
            run(*command)
        run(RESEARCH_PYTHON,"scripts/analyze_stop_comparison.py")
        run(sys.executable,"scripts/stop_provenance.py")
        print("Stop screening and challenge gates updated: reports/quant_v6/REPORT.md; live remains disabled",flush=True)


if __name__=="__main__":main()
