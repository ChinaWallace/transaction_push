#!/usr/bin/env python3
"""Freeze and download verified public Binance USD-M data for strategy research.

Run with ``.venv.quant/bin/python scripts/prepare_quant_strategy_data.py --freeze-only``
before the first download, then run without the flag. Resumes verified ZIPs and
never fabricates absent candles. This script only reads public archive data.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "quant_v5" / "data"
BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "ZECUSDT")
START = datetime(2025, 12, 1, tzinfo=timezone.utc)
TEST_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 24, tzinfo=timezone.utc)
FIVE_MIN_MS = 300_000
STOP = threading.Event()
RATE_LOCK = threading.Lock()
NEXT_REQUEST = 0.0
THREAD_LOCAL = threading.local()


def stamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def encode(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json(path: Path, value: object) -> None:
    write_bytes(path, encode(value))


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def jobs() -> list[dict]:
    result = []
    for symbol in SYMBOLS:
        for kind in ("klines", "markPriceKlines"):
            month = START
            while month < datetime(2026, 9, 1, tzinfo=timezone.utc):
                ymonth = month.strftime("%Y-%m")
                result.append({"symbol": symbol, "kind": kind,
                               "path": f"monthly/{kind}/{symbol}/5m/{symbol}-5m-{ymonth}.zip"})
                month = datetime(month.year + (month.month == 12), month.month % 12 + 1,
                                 1, tzinfo=timezone.utc)
            day = datetime(2026, 9, 1, tzinfo=timezone.utc)
            while day < END:
                yday = day.strftime("%Y-%m-%d")
                result.append({"symbol": symbol, "kind": kind,
                               "path": f"daily/{kind}/{symbol}/5m/{symbol}-5m-{yday}.zip"})
                day += timedelta(days=1)
    return result


def freeze() -> dict:
    path = OUT / "freeze_manifest.json"
    expected = {
        "protocol_version": 1,
        "selection": "User nominated BTC, ETH, ZEC before this strategy comparison; do not use 2026 returns to change the set.",
        "symbols": list(SYMBOLS),
        "warmup_start_utc": START.isoformat(),
        "test_start_utc": TEST_START.isoformat(),
        "end_exclusive_utc": END.isoformat(),
        "market": "Binance USD-M perpetual USDT",
        "timeframe": "5m",
        "data_types": ["klines", "markPriceKlines"],
        "archive_root": BASE,
        "funding_reference": "reports/quant_v3/futures_replay/funding/symbols/{symbol}.json",
        "jobs": jobs(),
    }
    if path.exists():
        existing = json.loads(path.read_text())
        if existing != expected:
            raise ValueError("Frozen manifest differs from this script; never silently change scope")
    else:
        write_json(path, expected)
    return expected


def proxy_setting() -> str | None:
    config = {}
    for line in (ROOT / ".env").read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    if config.get("PROXY_ENABLED", "").lower() in ("true", "1", "yes", "on"):
        if not config.get("PROXY_URL"):
            raise ValueError("PROXY_ENABLED but PROXY_URL is missing")
        return config["PROXY_URL"]
    return None


def client() -> httpx.Client:
    if not hasattr(THREAD_LOCAL, "client"):
        THREAD_LOCAL.client = httpx.Client(proxy=proxy_setting(), trust_env=False,
                                           timeout=35, follow_redirects=True,
                                           headers={"User-Agent": "transaction-push-public-research/1.0"})
    return THREAD_LOCAL.client


def throttle() -> None:
    global NEXT_REQUEST
    with RATE_LOCK:
        now = time.monotonic()
        due = max(now, NEXT_REQUEST)
        NEXT_REQUEST = due + 0.18  # globally <= ~5.5 public archive requests/s
    if due > now:
        time.sleep(due - now)


def get(path: str) -> bytes:
    if STOP.is_set():
        raise RuntimeError("Stopped after public archive rate limit")
    for attempt in range(4):
        throttle()
        try:
            response = client().get(f"{BASE}/{path}")
            if response.status_code in (418, 429):
                STOP.set()
                raise RuntimeError(f"Archive rate limited with HTTP {response.status_code}: {path}")
            if response.status_code == 404:
                raise FileNotFoundError(f"Archive missing HTTP 404: {path}")
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request,
                                            response=response)
            response.raise_for_status()
            return response.content
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            time.sleep(0.5 * 2**attempt)
    raise AssertionError("unreachable")


def fetch_job(job: dict) -> dict:
    relative = job["path"]
    zpath = OUT / "raw" / relative
    cpath = OUT / "raw" / (relative + ".CHECKSUM")
    checksum = cpath.read_bytes() if cpath.exists() else get(relative + ".CHECKSUM")
    match = re.fullmatch(rb"\s*([a-fA-F0-9]{64})\s+\*?([^\s]+)\s*", checksum)
    if match is None or match.group(2).decode() != zpath.name:
        raise ValueError(f"Bad official CHECKSUM file: {relative}")
    digest = match.group(1).decode().lower()
    raw = zpath.read_bytes() if zpath.exists() else get(relative)
    if sha(raw) != digest:
        raise ValueError(f"SHA-256 mismatch: {relative}")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != 1:
            raise ValueError(f"Bad ZIP structure: {relative}")
    if not cpath.exists():
        write_bytes(cpath, checksum)
    if not zpath.exists():
        write_bytes(zpath, raw)
    return {**job, "sha256": digest, "zip_bytes": len(raw),
            "checksum_file": relative + ".CHECKSUM"}


def read_rows(job: dict) -> list[list]:
    raw = (OUT / "raw" / job["path"]).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            rows = list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8-sig")))
    if rows and rows[0][0] == "open_time":
        rows = rows[1:]
    normalized = []
    for row in rows:
        if not row:
            continue
        if len(row) != 12:
            raise ValueError(f"Expected 12 fields: {job['path']} {row[:2]}")
        opened, closed = int(row[0]), int(row[6])
        if opened % FIVE_MIN_MS or closed != opened + FIVE_MIN_MS - 1:
            raise ValueError(f"Invalid 5m timestamp: {job['path']} {opened}")
        normalized.append([opened, *row[1:6], closed, *row[7:]])
    return normalized


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def validate_series(rows: list[list], symbol: str, kind: str) -> None:
    expected = stamp(START)
    stop = stamp(END)
    for row in rows:
        opened = row[0]
        if opened != expected:
            raise ValueError(f"Missing/duplicate {kind} {symbol} 5m bar: expected {iso(expected)}, got {iso(opened)}")
        expected += FIVE_MIN_MS
    if expected != stop:
        raise ValueError(f"Missing tail of {kind} {symbol}: expected through {iso(stop)}; got {iso(expected)}")


def number(value: Decimal) -> str:
    return format(value, "f")


def aggregate(rows: list[list], duration_ms: int) -> list[list]:
    n = duration_ms // FIVE_MIN_MS
    if len(rows) % n:
        raise ValueError(f"Incomplete aggregate group: {duration_ms}")
    result = []
    for index in range(0, len(rows), n):
        group = rows[index:index + n]
        start = group[0][0]
        if start % duration_ms or group[-1][0] != start + duration_ms - FIVE_MIN_MS:
            raise ValueError(f"Misaligned aggregate group: {iso(start)} {duration_ms}")
        result.append([
            start, group[0][1], number(max(Decimal(r[2]) for r in group)),
            number(min(Decimal(r[3]) for r in group)), group[-1][4],
            number(sum((Decimal(r[5]) for r in group), Decimal(0))),
            start + duration_ms - 1,
            number(sum((Decimal(r[7]) for r in group), Decimal(0))),
            sum(int(r[8]) for r in group),
            number(sum((Decimal(r[9]) for r in group), Decimal(0))),
            number(sum((Decimal(r[10]) for r in group), Decimal(0))), "0",
        ])
    return result


def funding_meta(symbol: str) -> dict:
    path = ROOT / "reports" / "quant_v3" / "futures_replay" / "funding" / "symbols" / f"{symbol}.json"
    raw = path.read_bytes()
    value = json.loads(raw)
    rates = value["rates"]
    first, last = int(rates[0]["fundingTime"]), int(rates[-1]["fundingTime"])
    if first > stamp(TEST_START) + 60_000 or last < stamp(END) - 8 * 3_600_000:
        raise ValueError(f"Funding does not cover test range: {symbol}")
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(raw), "events": len(rates),
            "first_utc": iso(first), "last_utc": iso(last),
            "note": "True funding event times only; no missing event is set to zero."}


def fetch_mark_gap(symbol: str) -> tuple[list[list], dict]:
    """Retrieve the verified 2026-06-29 hole in all three monthly mark archives."""
    start = stamp(datetime(2026, 6, 29, tzinfo=timezone.utc))
    end = start + 86_400_000 - 1
    request = {"symbol": symbol, "interval": "5m", "startTime": start,
               "endTime": end, "limit": 1000}
    path = OUT / "raw_rest" / "markPriceKlines" / f"{symbol}_2026-06-29.json"
    if path.exists():
        value = json.loads(path.read_text())
        if value.get("request") != request:
            raise ValueError(f"Cached mark gap request mismatch: {path}")
        rows = value["rows"]
    else:
        throttle()
        response = client().get("https://fapi.binance.com/fapi/v1/markPriceKlines", params=request)
        if response.status_code in (418, 429):
            STOP.set()
            raise RuntimeError(f"Public REST rate limited on mark gap: {symbol}")
        response.raise_for_status()
        rows = response.json()
        write_json(path, {"source": "Binance public USD-M /fapi/v1/markPriceKlines",
                          "request": request, "rows": rows})
    if len(rows) != 288 or [int(row[0]) for row in rows] != list(range(start, end + 1, FIVE_MIN_MS)):
        raise ValueError(f"REST mark gap not complete: {symbol}")
    normalized = [[int(row[0]), *[str(v) for v in row[1:6]], int(row[6]),
                   *[str(v) for v in row[7:]]] for row in rows]
    return normalized, {"path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes()),
                        "source": "Binance public USD-M /fapi/v1/markPriceKlines",
                        "request": request, "bars": len(rows),
                        "first_open_utc": iso(start),
                        "last_open_utc": iso(start + 287 * FIVE_MIN_MS)}


def assemble(done: list[dict]) -> dict:
    summary = {"freeze_manifest": "reports/quant_v5/data/freeze_manifest.json",
               "archive_base": BASE, "archives": done, "symbols": {}}
    repair_freeze = OUT / "mark_gap_freeze_manifest.json"
    repair_request = {"reason": "Official June 2026 monthly markPriceKlines ZIPs for all three frozen symbols omit 2026-06-29 UTC; use real public REST rows only for that gap.",
                      "source": "Binance public USD-M /fapi/v1/markPriceKlines",
                      "symbols": list(SYMBOLS), "interval": "5m",
                      "startTime": stamp(datetime(2026, 6, 29, tzinfo=timezone.utc)),
                      "endTime": stamp(datetime(2026, 6, 30, tzinfo=timezone.utc)) - 1,
                      "limit": 1000}
    if repair_freeze.exists():
        if json.loads(repair_freeze.read_text()) != repair_request:
            raise ValueError("Mark gap repair freeze changed")
    else:
        write_json(repair_freeze, repair_request)
    for symbol in SYMBOLS:
        entry = {"funding": funding_meta(symbol), "series": {}}
        for kind in ("klines", "markPriceKlines"):
            relevant = [job for job in done if job["symbol"] == symbol and job["kind"] == kind]
            rows = []
            for job in relevant:
                rows.extend(read_rows(job))
            if kind == "markPriceKlines":
                gap_rows, gap_source = fetch_mark_gap(symbol)
                existing = {row[0] for row in rows}
                if any(row[0] in existing for row in gap_rows):
                    raise ValueError(f"Frozen mark gap overlaps archive: {symbol}")
                rows.extend(gap_rows)
                rows.sort(key=lambda row: row[0])
                entry["mark_gap_supplement"] = gap_source
            validate_series(rows, symbol, kind)
            durations = {"5m": FIVE_MIN_MS}
            if kind == "klines":
                durations.update({"15m": 900_000, "1h": 3_600_000,
                                  "4h": 14_400_000, "1d": 86_400_000})
            else:
                durations.update({"1h": 3_600_000})
            for tf, duration in durations.items():
                data = rows if tf == "5m" else aggregate(rows, duration)
                payload = {"symbol": symbol, "timeframe": tf, "kind": kind,
                           "source": "Binance public USD-M archive CHECKSUM verified",
                           "start_utc": START.isoformat(), "end_exclusive_utc": END.isoformat(),
                           "rows": data}
                path = OUT / "series" / kind / tf / f"{symbol}.json"
                write_json(path, payload)
                entry["series"][f"{kind}/{tf}"] = {
                    "path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes()),
                    "bars": len(data), "first_open_utc": iso(data[0][0]),
                    "last_open_utc": iso(data[-1][0]), "internal_gaps": 0,
                }
        summary["symbols"][symbol] = entry
        write_json(OUT / "progress.json", {"phase": "assembled", "symbols_complete": list(summary["symbols"])})
    write_json(OUT / "manifest.json", summary)
    return summary


def warmup_jobs() -> list[dict]:
    return [{"symbol": symbol, "interval": interval,
             "endTime": stamp(TEST_START) - 1, "limit": 1000}
            for symbol in SYMBOLS for interval in ("1h", "4h", "1d")]


def freeze_warmup() -> dict:
    path = OUT / "warmup_freeze_manifest.json"
    value = {"protocol_version": 1,
             "reason": "NostalgiaForInfinity X7/X8 requires 800 startup candles on each informative timeframe before 2026-01-01.",
             "source": "Binance public USD-M /fapi/v1/klines",
             "requests": warmup_jobs(),
             "merge_policy": "Use native REST bars before 2025-12-01; use CHECKSUM-verified 5m archive aggregates from 2025-12-01 onward. Never use an unfinished candle or fill a gap."}
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Warmup freeze manifest changed")
    else:
        write_json(path, value)
    return value


def fetch_warmup(request: dict) -> dict:
    symbol, interval = request["symbol"], request["interval"]
    path = OUT / "raw_rest" / "klines" / f"{symbol}_{interval}.json"
    if path.exists():
        value = json.loads(path.read_text())
        if value.get("request") != request:
            raise ValueError(f"Cached REST request mismatch: {path}")
        rows = value["rows"]
    else:
        if STOP.is_set():
            raise RuntimeError("Stopped after public REST rate limit")
        throttle()
        response = client().get("https://fapi.binance.com/fapi/v1/klines", params={
            "symbol": symbol, "interval": interval,
            "endTime": request["endTime"], "limit": request["limit"]})
        if response.status_code in (418, 429):
            STOP.set()
            raise RuntimeError(f"Public REST rate limited: {symbol} {interval} HTTP {response.status_code}")
        response.raise_for_status()
        rows = response.json()
        write_json(path, {"source": "Binance USD-M public REST /fapi/v1/klines",
                          "request": request, "rows": rows})
    interval_ms = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[interval]
    if len(rows) != 1000:
        raise ValueError(f"Expected 1000 native {interval} bars for {symbol}, got {len(rows)}")
    for before, after in zip(rows, rows[1:]):
        if int(after[0]) - int(before[0]) != interval_ms:
            raise ValueError(f"Native REST gap: {symbol} {interval}")
    if int(rows[-1][0]) + interval_ms != stamp(TEST_START):
        raise ValueError(f"REST tail is not the final closed bar of 2025: {symbol} {interval}")
    return {"symbol": symbol, "interval": interval,
            "request": request, "raw_path": str(path.relative_to(ROOT)),
            "raw_sha256": sha(path.read_bytes()), "rows": len(rows),
            "first_open_utc": iso(int(rows[0][0])),
            "last_open_utc": iso(int(rows[-1][0]))}


def assemble_warmup(results: list[dict]) -> dict:
    output = {"freeze_manifest": "reports/quant_v5/data/warmup_freeze_manifest.json",
              "timeframe_startup_candles": 800, "test_start_utc": TEST_START.isoformat(),
              "series": {}}
    for item in results:
        symbol, tf = item["symbol"], item["interval"]
        interval_ms = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[tf]
        native = json.loads((ROOT / item["raw_path"]).read_text())["rows"]
        archive_path = OUT / "series" / "klines" / tf / f"{symbol}.json"
        archive = json.loads(archive_path.read_text())
        if archive["start_utc"] != START.isoformat():
            raise ValueError(f"Unexpected archive start: {archive_path}")
        early = [row for row in native if int(row[0]) < stamp(START)]
        merged = early + archive["rows"]
        if not early or int(early[-1][0]) + interval_ms != stamp(START):
            raise ValueError(f"No exact native/archive join: {symbol} {tf}")
        expected = int(merged[0][0])
        for row in merged:
            if int(row[0]) != expected:
                raise ValueError(f"Warmup merged gap: {symbol} {tf} expected {iso(expected)}")
            expected += interval_ms
        if expected != stamp(END):
            raise ValueError(f"Warmup merged tail missing: {symbol} {tf}")
        before_test = sum(int(row[0]) < stamp(TEST_START) for row in merged)
        if before_test < 800:
            raise ValueError(f"Insufficient NFI warmup: {symbol} {tf}: {before_test}")
        path = OUT / "series" / "klines_warmup" / tf / f"{symbol}.json"
        payload = {"symbol": symbol, "timeframe": tf,
                   "source": "native Binance REST before Dec 2025 + CHECKSUM-verified 5m aggregates thereafter",
                   "native_rest_source": item["raw_path"],
                   "archive_source": str(archive_path.relative_to(ROOT)),
                   "native_through_exclusive_utc": START.isoformat(),
                   "test_start_utc": TEST_START.isoformat(),
                   "end_exclusive_utc": END.isoformat(), "rows": merged}
        write_json(path, payload)
        output["series"][f"{symbol}/{tf}"] = {
            "path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes()),
            "bars": len(merged), "warmup_bars_before_test": before_test,
            "first_open_utc": iso(int(merged[0][0])),
            "last_open_utc": iso(int(merged[-1][0])),
            "native_rest": item, "archive_sha256": sha(archive_path.read_bytes()),
            "internal_gaps": 0}
    write_json(OUT / "warmup_manifest.json", output)
    return output


def run_warmup() -> None:
    fixed = freeze_warmup()
    if not (OUT / "manifest.json").exists():
        raise FileNotFoundError("Download/assemble the verified archive before native warmup")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch_warmup, fixed["requests"]))
    merged = assemble_warmup(results)
    print(f"Native warmup complete: {len(merged['series'])} aligned symbol/timeframe series", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--warmup-only", action="store_true")
    args = parser.parse_args()
    if args.warmup_only:
        run_warmup()
        return
    fixed = freeze()
    print(f"Frozen {len(fixed['symbols'])} symbols, {len(fixed['jobs'])} ZIPs and CHECKSUMs", flush=True)
    if args.freeze_only:
        return
    done = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_job, job): job for job in fixed["jobs"]}
        try:
            for future in concurrent.futures.as_completed(futures):
                done.append(future.result())
                if len(done) % 12 == 0 or len(done) == len(futures):
                    write_json(OUT / "progress.json", {"phase": "download", "complete": len(done),
                                                           "total": len(futures), "checked": done})
                    print(f"Verified {len(done)}/{len(futures)} archives", flush=True)
        except Exception:
            STOP.set()
            for future in futures:
                future.cancel()
            raise
    order = {job["path"]: i for i, job in enumerate(fixed["jobs"])}
    done.sort(key=lambda job: order[job["path"]])
    result = assemble(done)
    print(f"Complete: {len(result['archives'])} verified archives, {len(result['symbols'])} symbols", flush=True)


if __name__ == "__main__":
    main()
