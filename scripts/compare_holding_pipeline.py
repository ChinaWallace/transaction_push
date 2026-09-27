#!/usr/bin/env python3
"""Reproduce frozen holding comparisons and cost sensitivity, offline only."""
import fcntl
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/quant_v7'
PYTHON=ROOT/'.venv.freqtrade-quant/bin/python'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'pipeline.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Holding pipeline already running') from None
        commands=[
            [sys.executable,'scripts/run_holding_comparison.py'],
            [sys.executable,'scripts/run_holding_comparison.py','--windows','full','challenge2025','--double-cost'],
            [str(PYTHON),'scripts/analyze_holding_comparison.py'],
            [str(PYTHON),'scripts/check_strategy_lookahead.py','--study','v7','M4HoldEntry','A1HoldEntry','D55HoldEntry','M4SlowHold','A1SlowHold','D55SlowHold'],
        ]
        for command in commands:subprocess.run(command,cwd=ROOT,check=True)
        print('Holding comparisons complete: reports/quant_v7/REPORT.md. No execution strategy replaced.')


if __name__=='__main__':main()
