#!/usr/bin/env python3
"""Verified public Binance data for the frozen v12 expanded research universe.

Run with .venv.freqtrade-quant/bin/python. Uses only allowlisted proxy settings,
public archive/API endpoints, six workers and a global five-request/s ceiling.
No old research file, simulator, account or order endpoint is modified.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
import re
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_v12/data"
UNIVERSE = ROOT / "reports/quant_v12/universe_freeze.json"
BASE = "https://data.binance.vision/data/futures/um"
FAPI = "https://fapi.binance.com"
START = 1727740800000  # 2024-10-01 UTC
YEAR_2025 = 1735689600000
YEAR_2026 = 1767225600000
END = 1790208000000  # 2026-09-24 exclusive
STEP = 300_000
ANCHORS = ("BTCUSDT", "ETHUSDT", "ZECUSDT")
EXPECTED = ["BTCUSDT", "ETHUSDT", "ZECUSDT", "UNIUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "LINKUSDT", "AAVEUSDT", "AVAXUSDT", "SUIUSDT", "NEARUSDT", "DOTUSDT", "ADAUSDT", "LTCUSDT", "BCHUSDT"]
STOP = threading.Event()
RATE_LOCK = threading.Lock()
THREAD = threading.local()
NEXT_REQUEST = 0.0


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save(path: Path, value: object) -> None:
    write(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def proxy_config() -> str:
    values = {}
    for line in (ROOT / ".env").open():
        match = re.match(r"^\s*(PROXY_ENABLED|PROXY_URL)\s*=\s*(.*)$", line)
        if match:
            values[match[1]] = match[2].strip().strip('"').strip("'")
    for key in ("PROXY_ENABLED", "PROXY_URL"):
        if os.environ.get(key) is not None:
            values[key] = os.environ[key]
    if values.get("PROXY_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
        raise ValueError("The frozen public-data workflow requires the configured proxy")
    proxy = values.get("PROXY_URL", "")
    parsed = urlsplit(proxy)
    if parsed.scheme not in ("http", "https") or parsed.port != 7897:
        raise ValueError("Expected configured public HTTP proxy on port 7897")
    return proxy


def client() -> httpx.Client:
    if not hasattr(THREAD, "client"):
        THREAD.client = httpx.Client(proxy=proxy_config(), trust_env=False, timeout=40,
                                     follow_redirects=True,
                                     headers={"User-Agent": "transaction-push-v12-public-research/1.0"})
    return THREAD.client


def get(url: str, params: dict | None = None) -> bytes:
    global NEXT_REQUEST
    for attempt in range(4):
        if STOP.is_set():
            raise RuntimeError("Global stop after public endpoint rate limit")
        with RATE_LOCK:
            now = time.monotonic()
            due = max(now, NEXT_REQUEST)
            NEXT_REQUEST = due + .205
        if due > now:
            time.sleep(due - now)
        if STOP.is_set():
            raise RuntimeError("Global stop after public endpoint rate limit")
        try:
            response = client().get(url, params=params)
            if response.status_code in (418, 429):
                STOP.set()
                raise RuntimeError(f"HTTP {response.status_code}; global stop: {response.request.url.path}")
            if response.status_code == 404:
                raise FileNotFoundError(f"HTTP 404: {response.request.url.path}")
            if response.status_code >= 500:
                if attempt == 3:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.request.url.path}")
                time.sleep(2**attempt)
                continue
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.request.url.path}")
            return response.content
        except httpx.TransportError as error:
            if attempt == 3:
                raise RuntimeError(f"Public transport failed: {type(error).__name__}, path={urlsplit(url).path}") from None
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def archive_jobs(symbols: list[str]) -> list[dict]:
    result = []
    for symbol in symbols:
        if symbol in ANCHORS:
            continue
        for kind in ("klines", "markPriceKlines"):
            month = datetime(2024, 10, 1, tzinfo=timezone.utc)
            while month < datetime(2026, 9, 1, tzinfo=timezone.utc):
                label = month.strftime("%Y-%m")
                result.append({"symbol": symbol, "kind": kind,
                    "path": f"monthly/{kind}/{symbol}/5m/{symbol}-5m-{label}.zip"})
                month = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1, tzinfo=timezone.utc)
            day = datetime(2026, 9, 1, tzinfo=timezone.utc)
            while int(day.timestamp() * 1000) < END:
                label = day.strftime("%Y-%m-%d")
                result.append({"symbol": symbol, "kind": kind,
                    "path": f"daily/{kind}/{symbol}/5m/{symbol}-5m-{label}.zip"})
                day += timedelta(days=1)
        for month in range(1, 13):
            result.append({"symbol": symbol, "kind": "fundingRate",
                "path": f"monthly/fundingRate/{symbol}/{symbol}-fundingRate-2025-{month:02d}.zip"})
    return result


def freeze() -> dict:
    raw = UNIVERSE.read_bytes()
    symbols = json.loads(raw)["symbols"]
    if symbols != EXPECTED:
        raise ValueError("Universe differs from the specified frozen 16-symbol list")
    value = {"version": 1, "universe_path": str(UNIVERSE.relative_to(ROOT)),
        "universe_sha256": digest(raw), "symbols": symbols,
        "start_utc": iso(START), "end_exclusive_utc": iso(END), "timeframe": "5m",
        "archive_root": BASE, "jobs": archive_jobs(symbols),
        "proxy_policy": "Only PROXY_ENABLED/PROXY_URL, environment before .env, HTTP proxy port 7897, trust_env=False",
        "reuse_policy": "Anchor price sources v6+v5, 2026 true funding v3, 2024-2025 anchor funding v6; preserve all source hashes",
        "funding_validation": "2025 official funding ZIP/CHECKSUM event/rate cross-check against true public REST funding events with settlement markPrice"}
    path = OUT / "freeze_manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Data freeze changed; no silent scope update allowed")
    else:
        save(path, value)
    return value


def check_zip(path: Path, checksum_path: Path) -> dict:
    raw = path.read_bytes()
    text = checksum_path.read_bytes()
    match = re.fullmatch(rb"\s*([a-fA-F0-9]{64})\s+\*?([^\s]+)\s*", text)
    if not match or match[2].decode() != path.name or digest(raw) != match[1].decode().lower():
        raise ValueError(f"ZIP/checksum mismatch: {path.relative_to(ROOT)}")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.namelist()) != 1 or archive.testzip() is not None:
            raise ValueError(f"Bad ZIP: {path.relative_to(ROOT)}")
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(raw),
            "checksum_path": str(checksum_path.relative_to(ROOT)), "zip_bytes": len(raw)}


def download(job: dict) -> dict:
    path = OUT / "raw" / job["path"]
    checksum_path = OUT / "raw" / (job["path"] + ".CHECKSUM")
    if not checksum_path.exists():
        write(checksum_path, get(f"{BASE}/{job['path']}.CHECKSUM"))
    if not path.exists():
        write(path, get(f"{BASE}/{job['path']}"))
    return {**job, **check_zip(path, checksum_path)}


def csv_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            rows = list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8-sig")))
    if rows and rows[0][0] in ("open_time", "calc_time"):
        rows = rows[1:]
    return [row for row in rows if row]


def numeric_same(a: list, b: list) -> bool:
    return len(a) == len(b) and all(Decimal(str(x)) == Decimal(str(y)) for x, y in zip(a, b))


def add_rows(target: dict[int, list], rows: list[list], label: str) -> None:
    for raw in rows:
        row = [int(raw[0]), *raw[1:6], int(raw[6]), *raw[7:]]
        if len(row) != 12 or row[0] % STEP or row[6] != row[0] + STEP - 1:
            raise ValueError(f"Malformed 5m candle: {label} {row[0]}")
        if not START <= row[0] < END:
            continue
        if row[0] in target and not numeric_same(target[row[0]], row):
            raise ValueError(f"Conflicting duplicate 5m candle: {label} {row[0]}")
        target[row[0]] = row


def repair_missing(symbol: str, kind: str, rows: dict[int, list]) -> list[dict]:
    missing = [at for at in range(START, END, STEP) if at not in rows]
    if not missing:
        return []
    ranges = []
    first = previous = missing[0]
    for at in missing[1:]:
        if at != previous + STEP or (at - first) // STEP >= 1000:
            ranges.append((first, previous))
            first = at
        previous = at
    ranges.append((first, previous))
    if len(ranges) > 16:
        raise ValueError(f"Too many archive gaps for bounded REST repair: {symbol} {kind}, {len(ranges)} pages")
    sources = []
    for first, last in ranges:
        request = {"symbol": symbol, "interval": "5m", "startTime": first,
                   "endTime": last + STEP - 1, "limit": 1000}
        path = OUT / "raw_rest" / kind / f"{symbol}_{first}_{last}.json"
        if path.exists():
            value = json.loads(path.read_text())
            if value["request"] != request:
                raise ValueError("Cached gap request conflict")
        else:
            value = {"source": f"Binance public /fapi/v1/{kind}", "request": request,
                     "rows": json.loads(get(f"{FAPI}/fapi/v1/{kind}", request))}
            save(path, value)
        expected = list(range(first, last + STEP, STEP))
        if [int(row[0]) for row in value["rows"]] != expected:
            raise ValueError(f"REST did not return the full real archive gap: {symbol} {kind} {iso(first)}")
        add_rows(rows, value["rows"], str(path.relative_to(ROOT)))
        sources.append({"path": str(path.relative_to(ROOT)), "sha256": digest(path.read_bytes()),
                        "request": request, "bars": len(expected), "kind": kind})
    return sources


def funding_rest(symbol: str) -> tuple[list[dict], list[dict]]:
    rates, sources = [], []
    cursor = START
    page = 0
    while cursor < YEAR_2026:
        request = {"symbol": symbol, "startTime": cursor, "endTime": YEAR_2026 - 1, "limit": 1000}
        path = OUT / "raw_rest/fundingRate" / f"{symbol}_{page:03d}.json"
        if path.exists():
            value = json.loads(path.read_text())
            if value["request"] != request:
                raise ValueError("Cached funding request conflict")
        else:
            value = {"source": "Binance public /fapi/v1/fundingRate", "request": request,
                     "rows": json.loads(get(f"{FAPI}/fapi/v1/fundingRate", request))}
            save(path, value)
        rows = value["rows"]
        sources.append({"path": str(path.relative_to(ROOT)), "sha256": digest(path.read_bytes()),
                        "request": request, "events": len(rows)})
        if not rows:
            break
        times = [int(row["fundingTime"]) for row in rows]
        if times != sorted(set(times)) or times[0] < cursor or times[-1] >= YEAR_2026:
            raise ValueError(f"Invalid funding pagination: {symbol} {page}")
        rates.extend(rows)
        if len(rows) < 1000:
            break
        cursor = times[-1] + 1
        page += 1
    return rates, sources


def source_json(path: Path) -> tuple[dict, dict]:
    raw = path.read_bytes()
    return json.loads(raw), {"path": str(path.relative_to(ROOT)), "sha256": digest(raw)}


def validate_funding(symbol: str, rates: list[dict], archive: list[list]) -> dict:
    times = [int(row["fundingTime"]) for row in rates]
    seconds = [round(at / 1000) for at in times]
    if seconds != sorted(set(seconds)):
        raise ValueError(f"Funding duplicate/time conflict: {symbol}")
    if abs(times[0] - START) > 1000 or END - times[-1] > 8 * 3_600_000 + 1000:
        raise ValueError(f"Incomplete funding boundaries: {symbol}")
    gaps = [(a, b) for a, b in zip(seconds, seconds[1:]) if b - a > 8 * 3600]
    if gaps:
        raise ValueError(f"Funding gap above eight hours: {symbol} {gaps[:3]}")
    for row in rates:
        if row.get("symbol") != symbol or not math.isfinite(float(row["fundingRate"])) or not math.isfinite(float(row["markPrice"])) or float(row["markPrice"]) <= 0:
            raise ValueError(f"Invalid true funding/settlement mark: {symbol}")
    history = {round(int(row[0]) / 1000): row[2] for row in archive if YEAR_2025 <= int(row[0]) < YEAR_2026}
    actual = {round(int(row["fundingTime"]) / 1000): row["fundingRate"] for row in rates if YEAR_2025 <= int(row["fundingTime"]) < YEAR_2026}
    if len(history) != len(archive) or history.keys() != actual.keys():
        raise ValueError(f"2025 funding archive/REST event set differs: {symbol}")
    if any(Decimal(history[at]) != Decimal(actual[at]) for at in history):
        raise ValueError(f"2025 funding archive/REST rate differs: {symbol}")
    intervals = sorted(set((b - a) / 3600 for a, b in zip(seconds, seconds[1:])))
    return {"events": len(rates), "first_utc": iso(times[0]), "last_utc": iso(times[-1]),
            "actual_interval_hours": intervals, "gaps_over_8h": [], "archive_2025_rate_event_matches": len(actual)}


def build_symbol(symbol: str, archives: list[dict]) -> dict:
    sources, repairs = [], []
    prices = {"klines": {}, "markPriceKlines": {}}
    archive_funding = []
    if symbol in ANCHORS:
        for base in (ROOT / "reports/quant_v6/challenge_data", ROOT / "reports/quant_v5/data"):
            _, manifest_source = source_json(base / "manifest.json")
            sources.append(manifest_source)
            for kind in prices:
                path = base / "series" / kind / "5m" / f"{symbol}.json"
                value, source = source_json(path)
                sources.append(source)
                add_rows(prices[kind], value["rows"], source["path"])
        value, source = source_json(ROOT / "reports/quant_v6/challenge_data/funding" / f"{symbol}.json")
        sources.append(source)
        early_rates = value["rates"]
        old_manifest = json.loads((ROOT / "reports/quant_v6/challenge_data/manifest.json").read_text())
        for job in old_manifest["archives"]:
            if job["symbol"] == symbol and job["kind"] == "fundingRate" and job["month"].startswith("2025-"):
                path = ROOT / "reports/quant_v6/challenge_data/raw" / job["path"]
                sources.append(check_zip(path, Path(str(path) + ".CHECKSUM")))
                archive_funding.extend(csv_rows(path))
    else:
        for job in archives:
            if job["symbol"] != symbol:
                continue
            path = ROOT / job["path"]
            sources.append({key: value for key, value in job.items() if key not in ("symbol", "kind")})
            if job["kind"] == "fundingRate":
                archive_funding.extend(csv_rows(path))
            else:
                add_rows(prices[job["kind"]], csv_rows(path), job["path"])
        early_rates, rest_sources = funding_rest(symbol)
        sources.extend(rest_sources)
    later, source = source_json(ROOT / "reports/quant_v3/futures_replay/funding/symbols" / f"{symbol}.json")
    if not later["validation"]["complete"] or later["validation"]["errors"]:
        raise ValueError(f"Reused 2026 funding not complete: {symbol}")
    sources.append(source)
    rates = [row for row in early_rates + later["rates"] if START <= int(row["fundingTime"]) < END]
    funding_validation = validate_funding(symbol, rates, archive_funding)
    funding_path = OUT / "funding" / f"{symbol}.json"
    save(funding_path, {"symbol": symbol, "rates": rates, "source": "True Binance public fundingRate events with actual settlement markPrice", "validation": funding_validation})
    for kind in prices:
        repairs.extend(repair_missing(symbol, kind, prices[kind]))
        if sorted(prices[kind]) != list(range(START, END, STEP)):
            raise ValueError(f"Non-contiguous final {kind}: {symbol}")
    columns = {"timestamp": list(range(START, END, STEP))}
    for kind, prefix in (("klines", ""), ("markPriceKlines", "mark_")):
        data = [prices[kind][at] for at in columns["timestamp"]]
        for index, name in ((1, "open"), (2, "high"), (3, "low"), (4, "close")):
            values = [float(row[index]) for row in data]
            if any(not math.isfinite(value) or value <= 0 for value in values):
                raise ValueError(f"Non-finite/non-positive {kind}/{name}: {symbol}")
            columns[prefix + name] = values
        for row in data:
            op, high, low, close = map(float, row[1:5])
            if high < max(op, close, low) or low > min(op, close, high):
                raise ValueError(f"Invalid OHLC envelope: {symbol} {kind} {row[0]}")
        if not prefix:
            quote = [float(row[7]) for row in data]
            if any(not math.isfinite(value) or value < 0 for value in quote):
                raise ValueError(f"Invalid quote volume: {symbol}")
            columns["quote_volume"] = quote
    ordered = ["timestamp", "open", "high", "low", "close", "quote_volume", "mark_open", "mark_high", "mark_low", "mark_close"]
    frame = pd.DataFrame(columns)[ordered]
    path = OUT / "series" / f"{symbol}.feather"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".feather.tmp")
    frame.to_feather(temporary)
    os.replace(temporary, path)
    return {"status": "complete", "bars": len(frame), "first_utc": iso(START),
        "last_open_utc": iso(END - STEP), "internal_gaps": 0,
        "series_path": str(path.relative_to(ROOT)), "series_sha256": digest(path.read_bytes()),
        "funding_path": str(funding_path.relative_to(ROOT)), "funding_sha256": digest(funding_path.read_bytes()),
        "funding": funding_validation, "sources": sources, "public_rest_archive_gap_repairs": repairs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    frozen = freeze()
    print(f"Frozen {len(frozen['symbols'])} symbols, {len(frozen['jobs'])} ZIP/CHECKSUM pairs", flush=True)
    if args.freeze_only:
        return
    proxy_config()
    coverage = {"freeze_sha256": digest((OUT / "freeze_manifest.json").read_bytes()),
                "start_utc": iso(START), "end_exclusive_utc": iso(END), "symbols": {}}
    failures, archives, failed_symbols = [], [], set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(download, job): job for job in frozen["jobs"]}
        for symbol in ANCHORS:
            try:
                coverage["symbols"][symbol] = build_symbol(symbol, [])
                print(f"Validated local anchor {symbol}: 208224 bars", flush=True)
            except Exception as error:
                failures.append({"symbol": symbol, "stage": "local_anchor", "error_type": type(error).__name__, "error": str(error)})
                failed_symbols.add(symbol)
            save(OUT / "coverage_manifest.json", coverage)
        completed = 0
        for future in concurrent.futures.as_completed(pending):
            job = pending[future]
            completed += 1
            try:
                archives.append(future.result())
            except Exception as error:
                failed_symbols.add(job["symbol"])
                failures.append({"symbol": job["symbol"], "stage": "archive", "path": job["path"], "error_type": type(error).__name__, "error": str(error)})
                if STOP.is_set():
                    for item in pending:
                        item.cancel()
                    break
            if completed % 120 == 0 or completed == len(pending):
                save(OUT / "progress.json", {"phase": "archives", "completed": completed, "total": len(pending), "successful": len(archives), "failed_symbols": sorted(failed_symbols)})
                save(OUT / "failures.json", failures)
                print(f"Archives {completed}/{len(pending)}, successful {len(archives)}, failed symbols {len(failed_symbols)}", flush=True)
    order = {job["path"]: index for index, job in enumerate(frozen["jobs"])}
    archives.sort(key=lambda job: order[job["path"].split("reports/quant_v12/data/raw/", 1)[-1]])
    save(OUT / "archive_manifest.json", archives)
    for symbol in frozen["symbols"]:
        if symbol in ANCHORS or symbol in failed_symbols:
            continue
        try:
            coverage["symbols"][symbol] = build_symbol(symbol, archives)
            print(f"Validated {symbol}: 208224 bars", flush=True)
        except Exception as error:
            failed_symbols.add(symbol)
            failures.append({"symbol": symbol, "stage": "assemble", "error_type": type(error).__name__, "error": str(error)})
        save(OUT / "coverage_manifest.json", coverage)
        save(OUT / "failures.json", failures)
    coverage["complete_symbols"] = len(coverage["symbols"])
    coverage["target_symbols"] = len(frozen["symbols"])
    coverage["failed_symbols"] = sorted(failed_symbols)
    coverage["status"] = "complete" if not failed_symbols and len(coverage["symbols"]) == 16 else "incomplete"
    save(OUT / "coverage_manifest.json", coverage)
    save(OUT / "failures.json", failures)
    print(f"Complete symbols {len(coverage['symbols'])}/16; failures {len(failures)}", flush=True)
    if coverage["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
