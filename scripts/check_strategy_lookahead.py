#!/usr/bin/env python3
"""Use Freqtrade's truncation checker in explicitly offline BACKTEST mode."""
import argparse
import json
import os
from pathlib import Path

from freqtrade.commands.arguments import Arguments
from freqtrade.configuration import setup_utils_configuration
from freqtrade.enums import RunMode
from freqtrade.optimize.analysis.lookahead_helpers import LookaheadAnalysisSubFunctions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_v5"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategies", nargs="+")
    parser.add_argument("--study", choices=["v5","v6","v7"], default="v5")
    args = parser.parse_args()
    output=ROOT/("reports/quant_"+args.study)
    allowed=(["Donchian55","EMA4h","NFI8Long1x"] if args.study=="v5" else
             json.loads((output/"protocol.json").read_text())["strategies"])
    if not set(args.strategies)<=set(allowed):parser.error("Strategy is not part of the frozen experiment")
    for key in list(os.environ):
        if key.upper().startswith("FREQTRADE__") or key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            del os.environ[key]
    for strategy in args.strategies:
        run = output / "lookahead" / strategy
        run.mkdir(parents=True, exist_ok=True)
        cfg = json.loads((output / "runs/validation" / strategy / "config.json").read_text())
        cfg["user_data_dir"] = str(run / "user_data")
        (run / "user_data").mkdir(exist_ok=True)
        (run / "config.json").write_text(json.dumps(cfg, indent=2))
        cli = ["lookahead-analysis", "-c", str(run / "config.json"), "-s", strategy,
               "--strategy-path", str(ROOT / "research/strategies"),
               "--datadir", str(OUT / "freqtrade_data"), "--timerange", "20260501-20260701",
               "--minimum-trade-amount", "3", "--targeted-trade-amount", "12",
               "--lookahead-analysis-exportfilename", str(run / "result.csv")]
        parsed = Arguments(cli).get_parsed_arg()
        # Native command uses UTIL_NO_EXCHANGE; NFI custom exits explicitly branch
        # on BACKTEST. Keep the same offline mode as the compared production code.
        config = setup_utils_configuration(parsed, RunMode.BACKTEST)
        LookaheadAnalysisSubFunctions.start(config)


if __name__ == "__main__":
    main()
