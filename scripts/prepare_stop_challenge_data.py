#!/usr/bin/env python3
"""Download frozen 2025 BTC/ETH/ZEC USD-M stress data and Freqtrade feathers.

Run with ``.venv.freqtrade-quant/bin/python scripts/prepare_stop_challenge_data.py``.
Only public Binance archives and public USD-M funding-rate REST are queried.
Verified downloads are cached so an interrupted run can be resumed.
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
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "quant_v6" / "challenge_data"
BASE = "https://data.binance.vision/data/futures/um"
FAPI = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "ZECUSDT")
START = datetime(2024, 10, 1, tzinfo=timezone.utc)
TEST_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
MS = 300_000
THREAD = threading.local()
RATE_LOCK = threading.Lock()
NEXT = 0.0
STOP = threading.Event()


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def save(path: Path, value: object) -> None:
    write(path, encode(value))


def settings_proxy() -> str | None:
    config = {}
    for line in (ROOT / ".env").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key, value = s.split("=", 1)
            if key in ("PROXY_ENABLED", "PROXY_URL"):
                config[key] = value.strip().strip('"').strip("'")
    if config.get("PROXY_ENABLED", "").lower() in ("1", "true", "yes", "on"):
        if not config.get("PROXY_URL"):
            raise ValueError("Proxy enabled without URL")
        return config["PROXY_URL"]
    return None


def client() -> httpx.Client:
    if not hasattr(THREAD, "client"):
        THREAD.client = httpx.Client(proxy=settings_proxy(), trust_env=False, timeout=45,
                                     follow_redirects=True,
                                     headers={"User-Agent": "transaction-push-public-research/1.0"})
    return THREAD.client


def get(url: str, params: dict | None = None) -> bytes:
    global NEXT
    for attempt in range(4):
        if STOP.is_set():
            raise RuntimeError("Stopped after Binance public rate limit")
        with RATE_LOCK:
            now = time.monotonic()
            due = max(now, NEXT)
            NEXT = due + 0.2  # globally <= five requests per second
        if due > now:
            time.sleep(due - now)
        try:
            response = client().get(url, params=params)
            if response.status_code in (418, 429):
                STOP.set()
                raise RuntimeError(f"Rate limited HTTP {response.status_code}: {response.request.url.path}")
            if response.status_code == 404:
                raise FileNotFoundError(f"Public archive missing: {response.request.url.path}")
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request,
                                            response=response)
            response.raise_for_status()
            return response.content
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            time.sleep(2**attempt / 2)
    raise AssertionError("unreachable")


def jobs() -> list[dict]:
    result = []
    for symbol in SYMBOLS:
        for kind in ("klines", "markPriceKlines", "fundingRate"):
            for year in (2024, 2025):
                months = range(10, 13) if year == 2024 else range(1, 13)
                for month in months:
                    date = f"{year}-{month:02d}"
                    if kind == "fundingRate":
                        relative = f"monthly/fundingRate/{symbol}/{symbol}-fundingRate-{date}.zip"
                    else:
                        relative = f"monthly/{kind}/{symbol}/5m/{symbol}-5m-{date}.zip"
                    result.append({"symbol": symbol, "kind": kind, "month": date,
                                   "path": relative})
    return result


def freeze() -> dict:
    value = {"version": 1, "selection": "BTC/ETH/ZEC frozen before 2025 stop challenge analysis",
             "warmup_start_utc": START.isoformat(), "test_start_utc": TEST_START.isoformat(),
             "end_exclusive_utc": END.isoformat(), "market": "Binance USD-M perpetual USDT",
             "timeframe": "5m", "source_archive": BASE,
             "funding_rest": "/fapi/v1/fundingRate, true event markPrice",
             "jobs": jobs()}
    path = OUT / "freeze_manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Freeze manifest changed")
    else:
        save(path, value)
    return value


def archive_job(job: dict) -> dict:
    relative = job["path"]
    zpath = OUT / "raw" / relative
    cpath = OUT / "raw" / f"{relative}.CHECKSUM"
    checksum = cpath.read_bytes() if cpath.exists() else get(f"{BASE}/{relative}.CHECKSUM")
    match = re.fullmatch(rb"\s*([a-fA-F0-9]{64})\s+\*?([^\s]+)\s*", checksum)
    if match is None or match.group(2).decode() != zpath.name:
        raise ValueError(f"Malformed CHECKSUM: {relative}")
    digest = match.group(1).decode().lower()
    raw = zpath.read_bytes() if zpath.exists() else get(f"{BASE}/{relative}")
    if sha(raw) != digest:
        raise ValueError(f"ZIP SHA-256 mismatch: {relative}")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.namelist()) != 1 or archive.testzip() is not None:
            raise ValueError(f"Malformed ZIP: {relative}")
    if not cpath.exists():
        write(cpath, checksum)
    if not zpath.exists():
        write(zpath, raw)
    return {**job, "sha256": digest, "zip_bytes": len(raw),
            "checksum_path": f"{relative}.CHECKSUM"}


def csv_rows(job: dict) -> list[list[str]]:
    path = OUT / "raw" / job["path"]
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            rows = list(csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig")))
    if rows and rows[0][0] in ("open_time", "calc_time"):
        rows = rows[1:]
    return [row for row in rows if row]


def continuity(rows: list[list], step: int, symbol: str, kind: str) -> None:
    expect = ms(START)
    for row in rows:
        if int(row[0]) != expect:
            raise ValueError(f"{symbol} {kind} missing or duplicate bar: expected {iso(expect)}, got {iso(int(row[0]))}")
        expect += step
    if expect != ms(END):
        raise ValueError(f"{symbol} {kind} missing tail after {iso(expect)}")


def clean_decimal(value: Decimal) -> str:
    return format(value, "f")


def aggregate(rows: list[list], step: int) -> list[list]:
    group_size = step // MS
    if len(rows) % group_size:
        raise ValueError("Incomplete aggregation group")
    result = []
    for index in range(0, len(rows), group_size):
        group = rows[index:index + group_size]
        at = group[0][0]
        if at % step or group[-1][0] != at + step - MS:
            raise ValueError(f"Misaligned aggregation at {iso(at)}")
        result.append([at, group[0][1],
                       clean_decimal(max(Decimal(row[2]) for row in group)),
                       clean_decimal(min(Decimal(row[3]) for row in group)),
                       group[-1][4],
                       clean_decimal(sum((Decimal(row[5]) for row in group), Decimal(0))),
                       at + step - 1,
                       clean_decimal(sum((Decimal(row[7]) for row in group), Decimal(0))),
                       sum(int(row[8]) for row in group),
                       clean_decimal(sum((Decimal(row[9]) for row in group), Decimal(0))),
                       clean_decimal(sum((Decimal(row[10]) for row in group), Decimal(0))), "0"])
    return result


def funding_rest(symbol: str) -> tuple[list[dict], list[dict]]:
    cursor = ms(START)
    end = ms(END) - 1
    pages = []
    rates = []
    index = 0
    while cursor <= end:
        request = {"symbol": symbol, "startTime": cursor, "endTime": end, "limit": 1000}
        path = OUT / "raw_rest" / "fundingRate" / f"{symbol}_{index:03d}.json"
        if path.exists():
            value = json.loads(path.read_text())
            if value.get("request") != request:
                raise ValueError(f"Cached REST funding request mismatch: {path}")
            rows = value["rows"]
        else:
            rows = json.loads(get(f"{FAPI}/fapi/v1/fundingRate", request))
            save(path, {"source": "Binance public USD-M /fapi/v1/fundingRate",
                        "request": request, "rows": rows})
        pages.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes()),
                      "request": request, "rows": len(rows)})
        if not rows:
            break
        if any(row.get("symbol") != symbol or not row.get("markPrice") for row in rows):
            raise ValueError(f"Missing funding symbol/settlement mark: {symbol}")
        at = [int(row["fundingTime"]) for row in rows]
        if at != sorted(set(at)) or at[0] < cursor or at[-1] > end:
            raise ValueError(f"Malformed REST funding page: {symbol} {index}")
        rates.extend(rows)
        if len(rows) < 1000:
            break
        cursor = at[-1] + 1
        index += 1
    return rates, pages


def funding_archive(symbol: str, archives: list[dict]) -> list[dict]:
    result = []
    for job in archives:
        if job["symbol"] != symbol or job["kind"] != "fundingRate":
            continue
        for row in csv_rows(job):
            if len(row) != 3:
                raise ValueError(f"Malformed archive funding row: {job['path']}")
            at = int(row[0])
            if ms(START) <= at < ms(END):
                result.append({"fundingTime": at, "fundingIntervalHours": int(row[1]),
                               "fundingRate": row[2]})
    return result


def validate_funding(symbol: str, archived: list[dict], rest: list[dict]) -> dict:
    # Binance archive and REST settlement stamps can differ by a few ms.
    archive_map = {round(int(row["fundingTime"]) / 1000): row for row in archived}
    rest_map = {round(int(row["fundingTime"]) / 1000): row for row in rest}
    if len(archive_map) != len(archived) or len(rest_map) != len(rest) or archive_map.keys() != rest_map.keys():
        raise ValueError(f"Archive/REST funding events disagree: {symbol}, archive={len(archived)}, rest={len(rest)}")
    for at, row in archive_map.items():
        if Decimal(row["fundingRate"]) != Decimal(rest_map[at]["fundingRate"]):
            raise ValueError(f"Archive/REST funding rate differs: {symbol} {at}")
    event_times = sorted(rest_map)
    gaps = []
    for before, after in zip(event_times, event_times[1:]):
        hours = (after - before) / 3600
        if hours > 8:
            gaps.append({"after": iso(before * 1000), "before": iso(after * 1000),
                         "hours": hours})
    if gaps:
        raise ValueError(f"Funding interval above eight hours for {symbol}: {gaps[:3]}")
    first_slot = ms(START) // 1000
    end_exclusive = ms(END) // 1000
    if event_times[0] > first_slot or event_times[-1] < end_exclusive - 8 * 3600:
        raise ValueError(f"Funding boundary incomplete: {symbol}")
    if all(b - a == 8 * 3600 for a, b in zip(event_times, event_times[1:])):
        expected_slots = list(range(first_slot, end_exclusive, 8 * 3600))
        if event_times != expected_slots:
            raise ValueError(f"Funding missing an eight-hour slot: {symbol}")
    return {"events": len(rest), "first_utc": iso(int(rest[0]["fundingTime"])),
            "last_utc": iso(int(rest[-1]["fundingTime"])),
            "archive_rest_rate_matches": len(rest), "gaps_over_8h": gaps,
            "actual_interval_hours": sorted(set((b - a) / 3600 for a, b in zip(event_times, event_times[1:]))) }


def build_series(archives: list[dict]) -> dict:
    summary = {}
    for symbol in SYMBOLS:
        output = {"series": {}, "funding": {}}
        for kind in ("klines", "markPriceKlines"):
            rows = []
            for job in archives:
                if job["symbol"] == symbol and job["kind"] == kind:
                    for row in csv_rows(job):
                        if len(row) != 12:
                            raise ValueError(f"Malformed {kind} CSV row: {job['path']}")
                        opened, closed = int(row[0]), int(row[6])
                        if closed != opened + MS - 1:
                            raise ValueError(f"Malformed {kind} close timestamp: {job['path']}")
                        rows.append([opened, *row[1:6], closed, *row[7:]])
            continuity(rows, MS, symbol, kind)
            durations = {"5m": MS, "1h": 3_600_000} if kind == "markPriceKlines" else {
                "5m": MS, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
            for tf, duration in durations.items():
                data = rows if tf == "5m" else aggregate(rows, duration)
                path = OUT / "series" / kind / tf / f"{symbol}.json"
                save(path, {"symbol": symbol, "kind": kind, "timeframe": tf,
                            "source": "Binance public archive CHECKSUM verified",
                            "start_utc": START.isoformat(), "end_exclusive_utc": END.isoformat(),
                            "rows": data})
                output["series"][f"{kind}/{tf}"] = {"path": str(path.relative_to(ROOT)),
                    "sha256": sha(path.read_bytes()), "bars": len(data),
                    "first_open_utc": iso(data[0][0]), "last_open_utc": iso(data[-1][0]),
                    "internal_gaps": 0}
        archive_rates = funding_archive(symbol, archives)
        rest_rates, pages = funding_rest(symbol)
        check = validate_funding(symbol, archive_rates, rest_rates)
        path = OUT / "funding" / f"{symbol}.json"
        save(path, {"symbol": symbol, "source": "Binance public REST cross-checked with official monthly archive",
                    "rates": rest_rates, "archive_rates": archive_rates, "rest_pages": pages,
                    "validation": check})
        output["funding"] = {"path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes()),
                             **check}
        prior_4h = (ms(TEST_START) - ms(START)) // 14_400_000
        if prior_4h < 240:
            raise ValueError(f"4h warmup too short: {symbol}")
        output["pretest_4h_bars"] = prior_4h
        summary[symbol] = output
        save(OUT / "progress.json", {"phase": "series", "symbols_complete": list(summary)})
        print(f"Series complete {symbol}", flush=True)
    return summary


def write_feathers(summary: dict) -> dict:
    import pandas as pd
    from freqtrade.data.history import get_datahandler
    from freqtrade.enums import CandleType
    from freqtrade.exchange.exchange import Exchange

    dest = OUT / "freqtrade_data"
    dest.mkdir(parents=True, exist_ok=True)
    handler = get_datahandler(dest, "feather")

    def candles(path: Path):
        rows = json.loads(path.read_text())["rows"]
        frame = pd.DataFrame([[row[0], *map(float, row[1:6])] for row in rows],
                             columns=["date", "open", "high", "low", "close", "volume"])
        frame["date"] = pd.to_datetime(frame.date, unit="ms", utc=True)
        return frame

    output = {"source": "reports/quant_v6/challenge_data/manifest.json",
              "funding_convention": "Actual funding event and markPrice; sub-second event jitter normalized to scheduled hour; missing events never filled with zero.",
              "symbols": {}, "output_hashes": {}}
    for symbol in SYMBOLS:
        pair = symbol.removesuffix("USDT") + "/USDT:USDT"
        source = summary[symbol]
        for tf in ("5m", "15m", "1h", "4h"):
            path = ROOT / source["series"][f"klines/{tf}"]["path"]
            handler.ohlcv_store(pair, tf, candles(path), CandleType.FUTURES)
        mark_path = ROOT / source["series"]["markPriceKlines/1h"]["path"]
        mark = candles(mark_path).set_index("date")
        funding = json.loads((ROOT / source["funding"]["path"]).read_text())["rates"]
        items = []
        for event in funding:
            at = int(event["fundingTime"])
            hour = at // 3_600_000 * 3_600_000
            if at - hour >= 60_000:
                raise ValueError(f"Funding event not near scheduled hour: {symbol} {at}")
            dt = pd.to_datetime(hour, unit="ms", utc=True)
            if dt not in mark.index:
                raise ValueError(f"Missing mark hour for funding event: {symbol} {dt}")
            price = float(event["markPrice"])
            mark.loc[dt, "open"] = price
            mark.loc[dt, "high"] = max(mark.loc[dt, "high"], price)
            mark.loc[dt, "low"] = min(mark.loc[dt, "low"], price)
            items.append([dt, float(event["fundingRate"])])
        funding_frame = pd.DataFrame(items, columns=["date", "funding_rate"])
        if funding_frame.date.duplicated().any():
            raise ValueError(f"Two funding events in one hour: {symbol}")
        combined = Exchange.combine_funding_and_mark(funding_frame, mark.reset_index())
        if len(combined) != len(items):
            raise ValueError(f"Freqtrade silently lost funding rows: {symbol}")
        handler.ohlcv_store(pair, "1h", funding_frame, CandleType.FUNDING_RATE)
        handler.ohlcv_store(pair, "1h", mark.reset_index(), CandleType.MARK)
        output["symbols"][symbol] = {"funding_events": len(items),
                                     "funding_events_joined": len(combined),
                                     "pretest_4h_bars": source["pretest_4h_bars"]}
    output["output_hashes"] = {str(path.relative_to(dest)): sha(path.read_bytes())
                               for path in dest.rglob("*.feather")}
    save(dest / "manifest.json", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    fixed = freeze()
    print(f"Frozen {len(SYMBOLS)} symbols, {len(fixed['jobs'])} archive ZIPs", flush=True)
    if args.freeze_only:
        return
    done = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(archive_job, job): job for job in fixed["jobs"]}
        try:
            for future in concurrent.futures.as_completed(futures):
                done.append(future.result())
                if len(done) % 15 == 0 or len(done) == len(futures):
                    save(OUT / "progress.json", {"phase": "download", "complete": len(done),
                                                  "total": len(futures), "archives": done})
                    print(f"Verified {len(done)}/{len(futures)}", flush=True)
        except Exception:
            STOP.set()
            for future in futures:
                future.cancel()
            raise
    order = {job["path"]: index for index, job in enumerate(fixed["jobs"])}
    done.sort(key=lambda job: order[job["path"]])
    symbols = build_series(done)
    manifest = {"freeze_manifest": "reports/quant_v6/challenge_data/freeze_manifest.json",
                "archives": done, "symbols": symbols}
    save(OUT / "manifest.json", manifest)
    feather = write_feathers(symbols)
    save(OUT / "validation_summary.json", {
        "status": "pass", "archive_zip_checksum_pairs": len(done),
        "symbols": {symbol: {"trade_5m_bars": symbols[symbol]["series"]["klines/5m"]["bars"],
                            "mark_5m_bars": symbols[symbol]["series"]["markPriceKlines/5m"]["bars"],
                            "pretest_4h_bars": symbols[symbol]["pretest_4h_bars"],
                            "funding": symbols[symbol]["funding"]} for symbol in SYMBOLS},
        "feather_files": len(feather["output_hashes"]),
        "no_price_or_funding_imputation": True})
    print(f"Complete: {len(done)} archives, {len(feather['output_hashes'])} feathers", flush=True)


if __name__ == "__main__":
    main()
