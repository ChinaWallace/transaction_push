#!/usr/bin/env python3
"""Download a reproducible Binance spot daily-candle research snapshot.

Only Binance public market-data endpoints are used. The first run freezes Binance
server time in ``manifest.json``; subsequent runs resume that exact snapshot.
Cached symbol files are updated atomically after every page, so a network failure
does not discard earlier pages or historical data for delisted pairs.

Usage: python3 scripts/download_quant_history.py
       python3 scripts/download_quant_history.py --workers 2
       python3 scripts/download_quant_history.py --as-of 1790228737388
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "quant_v3" / "data"
BASE = "https://data-api.binance.vision"
START_MS = 1514764800000  # 2018-01-01 00:00:00 UTC
DAY_MS = 86_400_000
SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "UNIUSDT", "ZECUSDT",
    "OPUSDT", "ARBUSDT", "APTUSDT", "NEARUSDT", "BCHUSDT", "ETCUSDT",
    "ATOMUSDT", "DOTUSDT", "FILUSDT", "AAVEUSDT", "ALGOUSDT",
    "XLMUSDT", "TRXUSDT", "EOSUSDT", "FTMUSDT", "MATICUSDT",
)
HEADERS = {"User-Agent": "transaction-push-research-history/1.0"}
_STOP = threading.Event()


class RateLimited(RuntimeError):
    pass


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(compact_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def get_json(path: str, parameters: dict[str, object] | None = None) -> object:
    if _STOP.is_set():
        raise RateLimited("A parallel request received HTTP 429/418; download stopped")
    url = BASE + path
    if parameters:
        url += "?" + urllib.parse.urlencode(parameters)
    last: Exception | None = None
    for attempt in range(4):
        if _STOP.is_set():
            raise RateLimited("A parallel request received HTTP 429/418; download stopped")
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=35) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (418, 429):
                _STOP.set()
                raise RateLimited(f"HTTP {exc.code} on {path}; stop and resume later") from exc
            if exc.code not in (500, 502, 503, 504):
                raise
            last = exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            last = exc
        if attempt < 3:
            time.sleep(min(2**attempt, 4))
    raise RuntimeError(f"Fetch failed after 4 attempts: {path}: {last}")


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def validate_rows(rows: list, as_of: int) -> tuple[list, list[dict]]:
    """Check for duplicate or missing daily bars; never synthesize gap candles."""
    clean: list = []
    gaps: list[dict] = []
    previous: int | None = None
    for row in sorted(rows, key=lambda item: int(item[0])):
        if not isinstance(row, list) or len(row) < 11:
            raise ValueError("Malformed Binance kline row")
        opened = int(row[0])
        closed = int(row[6])
        if opened < START_MS or closed >= as_of:
            continue
        # Binance has a few genuine historical shortened candles (for example
        # BTCUSDT on 2018-02-08). Preserve source rows and disclose them below.
        if closed < opened or closed >= opened + DAY_MS:
            raise ValueError(f"Invalid daily close timestamp at {opened}: {closed}")
        if previous == opened:
            continue
        if previous is not None:
            if opened < previous:
                raise ValueError("Kline order is not increasing")
            if opened - previous != DAY_MS:
                gaps.append({
                    "after": iso(previous), "before": iso(opened),
                    "missing_days": (opened - previous) // DAY_MS - 1,
                })
        clean.append(row)
        previous = opened
    return clean, gaps


def cache_path(symbol: str) -> Path:
    return OUT / "symbols" / f"{symbol}_1d.json"


def download_symbol(symbol: str, as_of: int) -> dict:
    path = cache_path(symbol)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("as_of") != as_of or cached.get("symbol") != symbol:
            raise ValueError(f"Cache timestamp/symbol mismatch: {path}; use a new output directory")
        rows, _ = validate_rows(cached["rows"], as_of)
        complete = bool(cached.get("complete"))
    else:
        rows, complete = [], False
    if complete:
        return summarize(symbol, rows, as_of, from_cache=True)

    cursor = int(rows[-1][0]) + DAY_MS if rows else START_MS
    pages = 0
    while cursor < as_of and not _STOP.is_set():
        chunk = get_json("/api/v3/klines", {
            "symbol": symbol, "interval": "1d", "startTime": cursor,
            "endTime": as_of - 1, "limit": 1000,
        })
        if not isinstance(chunk, list):
            raise ValueError(f"Unexpected kline response for {symbol}: {chunk!r}")
        if not chunk:
            complete = True
            break
        fresh = [row for row in chunk if int(row[0]) >= cursor and int(row[6]) < as_of]
        if fresh:
            rows.extend(fresh)
            rows, _ = validate_rows(rows, as_of)
            next_cursor = int(rows[-1][0]) + DAY_MS
            if next_cursor <= cursor:
                raise ValueError(f"Non-progressing kline page for {symbol} at {cursor}")
            cursor = next_cursor
        elif len(chunk) < 1000:
            complete = True
            break
        else:
            raise ValueError(f"No completed rows in full kline page for {symbol}")
        pages += 1
        atomic_json(path, {"symbol": symbol, "as_of": as_of, "complete": False, "rows": rows})
        # A partial final page means no more bars exist at this frozen time.
        if len(chunk) < 1000:
            complete = True
            break
    if _STOP.is_set() and not complete:
        raise RateLimited(f"Stopped while downloading {symbol}; {len(rows)} bars cached")
    atomic_json(path, {"symbol": symbol, "as_of": as_of, "complete": complete, "rows": rows})
    summary = summarize(symbol, rows, as_of, from_cache=False)
    summary["pages_fetched"] = pages
    return summary


def summarize(symbol: str, rows: list, as_of: int, *, from_cache: bool) -> dict:
    rows, gaps = validate_rows(rows, as_of)
    shortened = [
        {"open_utc": iso(int(row[0])), "actual_close_utc": iso(int(row[6]))}
        for row in rows if int(row[6]) != int(row[0]) + DAY_MS - 1
    ]
    return {
        "symbol": symbol,
        "bars": len(rows),
        "first_open_utc": iso(int(rows[0][0])) if rows else None,
        "last_open_utc": iso(int(rows[-1][0])) if rows else None,
        "gaps": gaps,
        "shortened_candles": shortened,
        "last_bar_before_snapshot_days": (as_of - 1 - int(rows[-1][6])) // DAY_MS if rows else None,
        "sha256": hashlib.sha256(compact_json(rows)).hexdigest(),
        "cached": from_cache,
        "complete": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3, choices=(2, 3, 4))
    parser.add_argument("--as-of", type=int, help="Binance server timestamp in milliseconds, for reproducibility")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        as_of = int(manifest["as_of"])
        if args.as_of is not None and args.as_of != as_of:
            parser.error(f"Existing manifest freezes as_of={as_of}; cannot change it")
    else:
        try:
            as_of = args.as_of or int(get_json("/api/v3/time")["serverTime"])
        except Exception as exc:
            parser.error(f"Cannot establish Binance server time: {exc}")
        manifest = {
            "as_of": as_of, "as_of_utc": iso(as_of), "start_ms": START_MS,
            "source": BASE + "/api/v3/klines", "symbols": list(SYMBOLS),
            "notes": "Spot USDT daily candles; includes historically delisted symbols when available",
        }
        atomic_json(manifest_path, manifest)
    print(f"Frozen Binance server time: {iso(as_of)} ({as_of}); {len(SYMBOLS)} symbols", flush=True)

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_symbol, symbol, as_of): symbol for symbol in SYMBOLS}
        for future in concurrent.futures.as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
                results[symbol] = result
                print(f"{symbol}: {result['bars']} bars, {len(result['gaps'])} internal gaps", flush=True)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
                print(f"{symbol}: ERROR {errors[symbol]}", file=sys.stderr, flush=True)
    metadata = {
        **manifest, "completed_symbols": len(results), "total_bars": sum(r["bars"] for r in results.values()),
        "results": {symbol: results[symbol] for symbol in SYMBOLS if symbol in results},
        "errors": errors,
    }
    atomic_json(OUT / "download_meta.json", metadata)
    if errors:
        print("Incomplete snapshot; run the same command again to resume.", file=sys.stderr)
        return 1
    snapshot = {
        "as_of": as_of, "source": manifest["source"],
        "symbols": {
            symbol: {"1d": json.loads(cache_path(symbol).read_text(encoding="utf-8"))["rows"]}
            for symbol in SYMBOLS
        },
    }
    atomic_json(OUT / "snapshot.json", snapshot)
    metadata["snapshot_sha256"] = hashlib.sha256((OUT / "snapshot.json").read_bytes()).hexdigest()
    atomic_json(OUT / "download_meta.json", metadata)
    print(f"Complete: {metadata['total_bars']} bars; snapshot SHA-256 {metadata['snapshot_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
