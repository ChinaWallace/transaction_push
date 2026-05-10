#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run long-range Freqtrade backtests for the transaction_push signal projection.

The script is intentionally thin: Freqtrade owns historical data handling and
trade simulation, while this helper supplies project-style pair selection,
strategy threshold variants, and a losing-logic filter report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
USERDIR = PROJECT_ROOT / "freqtrade" / "user_data"
DEFAULT_CONFIG = USERDIR / "config.dryrun.example.json"
RESULTS_DIR = PROJECT_ROOT / "backtest_results"
STRATEGY_NAME = "TransactionPushSignalStrategy"


DEFAULT_SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "OP-USDT-SWAP",
    "ARB-USDT-SWAP",
    "LINK-USDT-SWAP",
    "AAVE-USDT-SWAP",
    "CRV-USDT-SWAP",
    "MKR-USDT-SWAP",
    "AVAX-USDT-SWAP",
]


@dataclass(frozen=True)
class Variant:
    name: str
    env: Dict[str, str]


VARIANTS = [
    Variant(
        "baseline",
        {
            "TP_SIGNAL_BUY_THRESHOLD": "68",
            "TP_SIGNAL_EXIT_THRESHOLD": "48",
            "TP_SIGNAL_MIN_VOLUME_FACTOR": "0.95",
            "TP_SIGNAL_MAX_ATR_RATIO": "0.065",
            "TP_SIGNAL_MAX_RSI": "72",
        },
    ),
    Variant(
        "strict_quality",
        {
            "TP_SIGNAL_BUY_THRESHOLD": "74",
            "TP_SIGNAL_EXIT_THRESHOLD": "52",
            "TP_SIGNAL_MIN_VOLUME_FACTOR": "1.10",
            "TP_SIGNAL_MAX_ATR_RATIO": "0.055",
            "TP_SIGNAL_MAX_RSI": "68",
        },
    ),
    Variant(
        "trend_follow",
        {
            "TP_SIGNAL_BUY_THRESHOLD": "64",
            "TP_SIGNAL_EXIT_THRESHOLD": "45",
            "TP_SIGNAL_MIN_VOLUME_FACTOR": "0.90",
            "TP_SIGNAL_MAX_ATR_RATIO": "0.070",
            "TP_SIGNAL_MAX_RSI": "74",
        },
    ),
]


def normalize_pairs(pairs: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for pair in pairs:
        value = (pair or "").strip().upper()
        if not value:
            continue
        value = value.replace("_", "-")
        if value.endswith("-USDT-SWAP"):
            value = f"{value[:-len('-USDT-SWAP')]}/USDT:USDT"
        elif value.endswith("USDT") and "/" not in value:
            value = f"{value[:-4].rstrip('-')}/USDT:USDT"
        elif "-" in value and "/" not in value:
            base, quote, *_ = value.split("-")
            value = f"{base}/{quote}:USDT" if quote == "USDT" else f"{base}/{quote}"
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def parse_symbols(raw: Optional[str]) -> List[str]:
    if not raw:
        env_symbols = os.getenv("FREQTRADE_BACKTEST_SYMBOLS")
        raw = env_symbols if env_symbols else ",".join(DEFAULT_SYMBOLS)
    return normalize_pairs(item for item in raw.replace(";", ",").split(","))


def run_command(cmd: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def freqtrade_cmd(args: List[str]) -> List[str]:
    return [sys.executable, "-m", "freqtrade", *args]


def download_data(args: argparse.Namespace, pairs: List[str]) -> subprocess.CompletedProcess[str]:
    cmd = freqtrade_cmd(
        [
            "download-data",
            "--config",
            str(args.config),
            "--userdir",
            str(USERDIR),
            "--timerange",
            args.timerange,
            "--trading-mode",
            "futures",
        ]
    )
    for timeframe in args.download_timeframes:
        cmd.extend(["--timeframes", timeframe])
    cmd.append("--pairs")
    cmd.extend(pairs)
    return run_command(cmd)


def run_backtest(args: argparse.Namespace, pairs: List[str], variant: Variant) -> subprocess.CompletedProcess[str]:
    env = {
        **variant.env,
        "TP_SIGNAL_TIMEFRAME": args.timeframe,
    }
    cmd = freqtrade_cmd(
        [
            "backtesting",
            "--config",
            str(args.config),
            "--userdir",
            str(USERDIR),
            "--strategy",
            args.strategy,
            "--timeframe",
            args.timeframe,
            "--timerange",
            args.timerange,
            "--cache",
            "none",
            "--export",
            "trades",
        ]
    )
    if args.enable_protections:
        cmd.append("--enable-protections")
    cmd.append("--pairs")
    cmd.extend(pairs)
    return run_command(cmd, env=env)


def latest_backtest_zip() -> Path:
    marker = USERDIR / "backtest_results" / ".last_result.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    return USERDIR / "backtest_results" / data["latest_backtest"]


def load_backtest_result(zip_path: Path, strategy: str) -> Dict[str, Any]:
    with zipfile.ZipFile(zip_path) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and "_config" not in name and "_meta" not in name
        ]
        if not candidates:
            raise RuntimeError(f"No backtest json found in {zip_path}")
        payload = json.loads(archive.read(candidates[0]))
    return payload["strategy"][strategy]


def summarize_variant(name: str, result: Dict[str, Any], zip_path: Path, env: Dict[str, str]) -> Dict[str, Any]:
    per_pair = [row for row in result.get("results_per_pair", []) if row.get("key") != "TOTAL"]
    losing_pairs = [
        {
            "pair": row.get("key"),
            "trades": row.get("trades", 0),
            "profit_total_pct": row.get("profit_total_pct", 0),
            "profit_total_abs": row.get("profit_total_abs", 0),
            "winrate": row.get("winrate", 0),
            "profit_factor": row.get("profit_factor", 0),
        }
        for row in per_pair
        if row.get("trades", 0) > 0 and row.get("profit_total", 0) < 0
    ]
    inactive_pairs = [row.get("key") for row in per_pair if row.get("trades", 0) == 0]

    return {
        "variant": name,
        "parameters": env,
        "result_zip": str(zip_path),
        "period": {
            "start": result.get("backtest_start"),
            "end": result.get("backtest_end"),
            "days": result.get("backtest_days"),
        },
        "total": {
            "trades": result.get("total_trades", 0),
            "profit_total_pct": result.get("profit_total", 0) * 100,
            "profit_total_abs": result.get("profit_total_abs", 0),
            "profit_factor": result.get("profit_factor", 0),
            "winrate": result.get("winrate", 0),
            "max_drawdown_abs": result.get("max_drawdown_abs", 0),
            "max_drawdown_account_pct": result.get("max_drawdown_account", 0) * 100,
        },
        "losing_pairs": losing_pairs,
        "inactive_pairs": inactive_pairs,
        "surviving_pairs": [
            row.get("key")
            for row in per_pair
            if row.get("trades", 0) > 0 and row.get("profit_total", 0) >= 0
        ],
    }


def write_report(summaries: List[Dict[str, Any]], args: argparse.Namespace) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = RESULTS_DIR / f"freqtrade_signal_filter_{stamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "summary.json"
    json_path.write_text(
        json.dumps(
            {
                "strategy": args.strategy,
                "timeframe": args.timeframe,
                "timerange": args.timerange,
                "generated_at": datetime.now().isoformat(),
                "variants": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        f"# Freqtrade Signal Filter Report",
        "",
        f"- Strategy: `{args.strategy}`",
        f"- Timeframe: `{args.timeframe}`",
        f"- Timerange: `{args.timerange}`",
        "",
        "| Variant | Trades | Profit % | Profit factor | Winrate | Losing pairs | Surviving pairs |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summaries:
        total = item["total"]
        lines.append(
            "| {variant} | {trades} | {profit:.2f} | {pf:.2f} | {winrate:.2%} | {losers} | {survivors} |".format(
                variant=item["variant"],
                trades=total["trades"],
                profit=total["profit_total_pct"],
                pf=total["profit_factor"] or 0,
                winrate=total["winrate"] or 0,
                losers=len(item["losing_pairs"]),
                survivors=len(item["surviving_pairs"]),
            )
        )

    lines.extend(["", "## Losing Pair Detail", ""])
    for item in summaries:
        lines.append(f"### {item['variant']}")
        if not item["losing_pairs"]:
            lines.append("")
            lines.append("No losing pairs with trades.")
            lines.append("")
            continue
        for row in item["losing_pairs"]:
            lines.append(
                "- `{pair}`: trades={trades}, profit={profit:.2f}%, winrate={winrate:.2%}, pf={pf:.2f}".format(
                    pair=row["pair"],
                    trades=row["trades"],
                    profit=row["profit_total_pct"],
                    winrate=row["winrate"] or 0,
                    pf=row["profit_factor"] or 0,
                )
            )
        lines.append("")

    md_path = report_dir / "summary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return report_dir


def selected_variants(raw: str) -> List[Variant]:
    requested = {item.strip() for item in raw.split(",") if item.strip()}
    if not requested or "all" in requested:
        return VARIANTS
    variants_by_name = {variant.name: variant for variant in VARIANTS}
    missing = requested - set(variants_by_name)
    if missing:
        raise ValueError(f"Unknown variants: {', '.join(sorted(missing))}")
    return [variants_by_name[name] for name in requested]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", help="Comma-separated pairs. Defaults to core liquid USDT futures.")
    parser.add_argument("--timerange", default="20230101-20260501")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--download-timeframes", nargs="+", default=["1h"])
    parser.add_argument("--strategy", default=STRATEGY_NAME)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--variants", default="all", help="Comma-separated: baseline,strict_quality,trend_follow,all")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--enable-protections", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.config = args.config.resolve()

    pairs = parse_symbols(args.pairs)
    variants = selected_variants(args.variants)
    print(f"Pairs: {', '.join(pairs)}")
    print(f"Variants: {', '.join(variant.name for variant in variants)}")

    if not args.skip_download:
        print("Downloading Freqtrade data...")
        proc = download_data(args, pairs)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            return proc.returncode

    summaries: List[Dict[str, Any]] = []
    for variant in variants:
        print(f"Running backtest variant: {variant.name}")
        before = latest_backtest_zip() if (USERDIR / "backtest_results" / ".last_result.json").exists() else None
        proc = run_backtest(args, pairs, variant)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            return proc.returncode

        zip_path = latest_backtest_zip()
        if before == zip_path:
            time.sleep(0.2)
            zip_path = latest_backtest_zip()
        result = load_backtest_result(zip_path, args.strategy)
        summary = summarize_variant(variant.name, result, zip_path, variant.env)
        summaries.append(summary)
        total = summary["total"]
        print(
            f"{variant.name}: trades={total['trades']} "
            f"profit={total['profit_total_pct']:.2f}% "
            f"pf={(total['profit_factor'] or 0):.2f} "
            f"losers={len(summary['losing_pairs'])}"
        )

    report_dir = write_report(summaries, args)
    print(f"Report written to: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
