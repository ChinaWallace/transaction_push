#!/usr/bin/env python3
"""Reproducible BTC/ETH USD-M futures daily prices and actual funding history.

Uses Binance's official public monthly archive (available even if fapi REST is
region-blocked), plus daily price archives for the unfinished current month.
Optional ``rest_<symbol>_funding.json`` / ``rest_<symbol>_klines.json`` files in
the output directory may supplement archival lag. They must contain Binance
REST result rows and source metadata; missing funding is NEVER imputed as zero.
The spot research manifest freezes the end timestamp across all datasets.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "quant_v3" / "futures"
ARCHIVE = "https://data.binance.vision/data/futures/um"
START = datetime(2020, 1, 1, tzinfo=timezone.utc)
DAY_MS = 86_400_000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
_STOP = threading.Event()


class RateLimited(RuntimeError):
    pass


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(path, encode(value))


def fetch_zip(relative_path: str, *, optional: bool = False) -> tuple[bytes | None, str]:
    local = OUT / "raw" / relative_path
    if local.exists():
        data = local.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupted cached ZIP: {local}")
        return data, "cache"
    if _STOP.is_set():
        raise RateLimited("Another request received HTTP 429/418; stopped")
    url = f"{ARCHIVE}/{relative_path}"
    last: Exception | None = None
    for attempt in range(4):
        if _STOP.is_set():
            raise RateLimited("Another request received HTTP 429/418; stopped")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "transaction-push-research/1.0"})
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"Corrupted ZIP from {url}")
            atomic_bytes(local, data)
            return data, "download"
        except urllib.error.HTTPError as exc:
            if exc.code in (418, 429):
                _STOP.set()
                raise RateLimited(f"HTTP {exc.code} on {url}; resume later") from exc
            if exc.code == 404 and optional:
                return None, "not_published"
            if exc.code not in (500, 502, 503, 504):
                raise
            last = exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            last = exc
        if attempt < 3:
            time.sleep(min(2**attempt, 4))
    raise RuntimeError(f"Fetch failed after 4 attempts: {url}: {last}")


def csv_rows(zipped: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        members = [member for member in archive.namelist() if member.endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in ZIP, found {members}")
        with archive.open(members[0]) as raw:
            rows = list(csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig")))
    if rows and not rows[0][0].isdigit():
        rows = rows[1:]
    return [row for row in rows if row]


def monthly_paths(symbol: str, last_full_month: datetime) -> list[tuple[str, str, bool]]:
    jobs = []
    cursor = START
    while cursor < last_full_month:
        year_month = cursor.strftime("%Y-%m")
        jobs.extend([
            (symbol, f"monthly/klines/{symbol}/1d/{symbol}-1d-{year_month}.zip", False),
            (symbol, f"monthly/fundingRate/{symbol}/{symbol}-fundingRate-{year_month}.zip", False),
        ])
        cursor = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1, tzinfo=timezone.utc)
    return jobs


def daily_paths(symbol: str, last_full_month: datetime, as_of: int) -> list[tuple[str, str, bool]]:
    jobs = []
    cursor = last_full_month
    while int((cursor + timedelta(days=1)).timestamp() * 1000) <= as_of:
        day = cursor.strftime("%Y-%m-%d")
        jobs.append((symbol, f"daily/klines/{symbol}/1d/{symbol}-1d-{day}.zip", True))
        cursor += timedelta(days=1)
    return jobs


def archive_job(job: tuple[str, str, bool]) -> dict:
    symbol, path, optional = job
    raw, state = fetch_zip(path, optional=optional)
    if raw is None:
        return {"symbol": symbol, "path": path, "status": state, "rows": []}
    return {
        "symbol": symbol, "path": path, "status": state,
        "zip_sha256": hashlib.sha256(raw).hexdigest(), "rows": csv_rows(raw),
    }


def supplement(symbol: str, kind: str, as_of: int) -> tuple[list, dict | None]:
    path = OUT / f"rest_{symbol}_{kind}.json"
    if not path.exists():
        return [], None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("symbol") != symbol or value.get("as_of") != as_of:
        raise ValueError(f"Supplement symbol/as_of mismatch: {path}")
    rows = value["rows"]
    if not isinstance(rows, list):
        raise ValueError(f"Malformed supplement rows: {path}")
    return rows, {"file": path.name, "source": value.get("source"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def iso(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms is not None else None


def assemble(symbol: str, archive_results: list[dict], as_of: int) -> tuple[dict, dict]:
    klines: dict[int, list] = {}
    funding: dict[int, dict] = {}
    provenance = []
    not_published = []
    for item in archive_results:
        if item["symbol"] != symbol:
            continue
        if item["status"] == "not_published":
            not_published.append(item["path"])
            continue
        provenance.append({"path": item["path"], "zip_sha256": item["zip_sha256"]})
        if "/fundingRate/" in item["path"]:
            for row in item["rows"]:
                if len(row) < 3:
                    raise ValueError(f"Malformed funding row in {item['path']}: {row}")
                timestamp = int(row[0])
                if timestamp < int(START.timestamp() * 1000) or timestamp >= as_of:
                    continue
                entry = {"fundingTime": timestamp, "fundingIntervalHours": int(row[1]), "fundingRate": row[2]}
                key = timestamp // 1000  # Archive timestamps sometimes differ by 1-9 ms.
                if key in funding and funding[key]["fundingRate"] != entry["fundingRate"]:
                    raise ValueError(f"Conflicting funding at {timestamp} for {symbol}")
                funding[key] = entry
        else:
            for row in item["rows"]:
                if len(row) < 12:
                    raise ValueError(f"Malformed kline row in {item['path']}: {row}")
                opened, closed = int(row[0]), int(row[6])
                if opened < int(START.timestamp() * 1000) or closed >= as_of:
                    continue
                if opened in klines and klines[opened] != row:
                    raise ValueError(f"Conflicting kline at {opened} for {symbol}")
                klines[opened] = [opened, *row[1:6], closed, *row[7:]]

    extra_funding, funding_source = supplement(symbol, "funding", as_of)
    extra_klines, kline_source = supplement(symbol, "klines", as_of)
    for row in extra_funding:
        timestamp = int(row["fundingTime"])
        if not int(START.timestamp() * 1000) <= timestamp < as_of:
            continue
        key = timestamp // 1000
        old = funding.get(key)
        if old and old["fundingRate"] != row["fundingRate"]:
            raise ValueError(f"REST/archive funding disagreement at {timestamp} for {symbol}")
        funding[key] = {"fundingTime": timestamp, "fundingRate": row["fundingRate"],
                        "fundingIntervalHours": old["fundingIntervalHours"] if old else None,
                        **({"markPrice": row["markPrice"]} if row.get("markPrice") else {})}
    for row in extra_klines:
        opened, closed = int(row[0]), int(row[6])
        if closed >= as_of:
            continue
        old = klines.get(opened)
        if old and str(old[4]) != str(row[4]):
            raise ValueError(f"REST/archive close disagreement at {opened} for {symbol}")
        klines[opened] = row

    daily = [klines[timestamp] for timestamp in sorted(klines)]
    rates = [funding[timestamp] for timestamp in sorted(funding)]
    gap_days = [iso(int(right[0])) for left, right in zip(daily, daily[1:])
                if int(right[0]) - int(left[0]) != DAY_MS]
    # Funding intervals can change by symbol and date. Flag >12h gaps rather
    # than assuming exactly three 8h settlements per day.
    funding_gaps = [
        {"after": iso(int(left["fundingTime"])), "before": iso(int(right["fundingTime"])),
         "hours": round((int(right["fundingTime"]) - int(left["fundingTime"])) / 3_600_000, 4)}
        for left, right in zip(rates, rates[1:])
        if int(right["fundingTime"]) - int(left["fundingTime"]) > 12 * 3_600_000
    ]
    payload = {"1d": daily, "funding": rates}
    meta = {
        "symbol": symbol, "daily_bars": len(daily), "funding_events": len(rates),
        "first_daily_utc": iso(int(daily[0][0])) if daily else None,
        "last_daily_utc": iso(int(daily[-1][0])) if daily else None,
        "first_funding_utc": iso(int(rates[0]["fundingTime"])) if rates else None,
        "last_funding_utc": iso(int(rates[-1]["fundingTime"])) if rates else None,
        "daily_gap_starts": gap_days, "funding_gaps_over_12h": funding_gaps,
        "unpublished_daily_archives": not_published,
        "supplements": [x for x in (funding_source, kline_source) if x],
        "source_archive_zips": provenance,
        "daily_sha256": hashlib.sha256(encode(daily)).hexdigest(),
        "funding_sha256": hashlib.sha256(encode(rates)).hexdigest(),
    }
    return payload, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    spot_manifest = ROOT / "reports" / "quant_v3" / "data" / "manifest.json"
    if not spot_manifest.exists():
        parser.error(f"Spot manifest not found: {spot_manifest}")
    as_of = int(json.loads(spot_manifest.read_text(encoding="utf-8"))["as_of"])
    end = datetime.fromtimestamp(as_of / 1000, timezone.utc)
    this_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    jobs = [job for symbol in SYMBOLS
            for job in monthly_paths(symbol, this_month) + daily_paths(symbol, this_month, as_of)]
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Frozen end: {iso(as_of)}; {len(jobs)} Binance archive ZIP requests or cached files", flush=True)
    completed: list[dict] = []
    errors: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(archive_job, job): job for job in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            job = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                errors.append({"path": job[1], "error": f"{type(exc).__name__}: {exc}"})
                print(f"ERROR {job[1]}: {exc}", file=sys.stderr, flush=True)
            if count % 40 == 0 or count == len(jobs):
                print(f"Archive files processed: {count}/{len(jobs)}, errors: {len(errors)}", flush=True)
    if errors:
        atomic_json(OUT / "download_errors.json", errors)
        print("Archive incomplete; rerun to resume.", file=sys.stderr)
        return 1
    all_data = {}
    all_meta = {}
    for symbol in SYMBOLS:
        all_data[symbol], all_meta[symbol] = assemble(symbol, completed, as_of)
    snapshot = {"as_of": as_of, "source": ARCHIVE, "symbols": all_data}
    snapshot_path = OUT / "snapshot.json"
    atomic_json(snapshot_path, snapshot)
    metadata = {
        "as_of": as_of, "as_of_utc": iso(as_of), "start_utc": iso(int(START.timestamp() * 1000)),
        "archive": ARCHIVE, "rest_region_status": "fapi.binance.com returned HTTP 451 from this host",
        "funding_semantics": "Actual recorded funding rates; positive rate costs a long. Missing periods are unknown, never zero.",
        "symbols": all_meta, "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
    }
    atomic_json(OUT / "download_meta.json", metadata)
    for symbol in SYMBOLS:
        m = all_meta[symbol]
        print(f"{symbol}: {m['daily_bars']} daily, {m['funding_events']} funding, last funding {m['last_funding_utc']}")
    print(f"Snapshot SHA-256 {metadata['snapshot_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
