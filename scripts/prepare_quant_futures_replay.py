#!/usr/bin/env python3
"""Validate the 354-symbol USD-M daily history and assemble real funding pages.

The market snapshot is a current-symbol universe, so historical inclusion is
subject to survivorship bias. Each Binance connector funding page is saved as
``reports/quant_v3/futures_replay/funding/pages/SYMBOL_000.json`` (and then
001, ...). This script is read-only for the connector and does not invent rates.

Usage:
    python3 scripts/prepare_quant_futures_replay.py index
    python3 scripts/prepare_quant_futures_replay.py assemble
    python3 scripts/prepare_quant_futures_replay.py archive-sample
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "reports" / "quant_v3" / "futures_universe"
OUT = ROOT / "reports" / "quant_v3" / "futures_replay"
AS_OF = int(json.loads((DATA / "history_request.json").read_text())["endTime"])
START_2026 = 1767225600000
DAY = 86_400_000
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
SAMPLE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "AAVEUSDT",
                  "DELLUSDT", "OPENAIUSDT", "1000PEPEUSDT", "PONSUSDT", "哈基米USDT")


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(encode(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def utc(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms is not None else None


def sources() -> list[str]:
    request = json.loads((DATA / "history_request.json").read_text())
    return request["symbols"]


def indexed_symbols() -> dict:
    symbols = {}
    for symbol in sources():
        path = DATA / "klines" / f"{symbol}.json"
        value = json.loads(path.read_text())
        if value["symbol"] != symbol:
            raise ValueError(f"Symbol mismatch in {path}")
        rows = value["rows"]
        if not rows:
            raise ValueError(f"No rows for {symbol}")
        complete = sorted((row for row in rows if int(row[6]) < AS_OF), key=lambda row: int(row[0]))
        if not complete:
            raise ValueError(f"No closed candle for {symbol}")
        opens = [int(row[0]) for row in complete]
        if opens != sorted(set(opens)):
            raise ValueError(f"Duplicate or unordered bars for {symbol}")
        gaps = [
            {"after_utc": utc(left), "before_utc": utc(right), "missing_days": (right-left)//DAY-1}
            for left,right in zip(opens, opens[1:]) if right-left != DAY
        ]
        first = opens[0]
        last = opens[-1]
        first_2026 = next((t for t in opens if t >= START_2026), None)
        symbols[symbol] = {
            "source_file": str(path.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "raw_rows": len(rows), "closed_rows": len(complete),
            "capped_1000": len(rows) >= 1000,
            "first_observed_daily_utc": utc(first),
            "last_closed_daily_utc": utc(last),
            "observed_age_days": (last-first)//DAY+1,
            "listing_time_known": False,
            "listing_note": ("First bar is the REST 1000-row limit, so actual listing is earlier"
                             if len(rows) >= 1000 else
                             "First returned bar may be listing day; exact listing time not verified"),
            "first_2026_daily_utc": utc(first_2026),
            "daily_gaps": gaps,
            "missing_closed_2026_days": [gap for gap in gaps if gap["before_utc"] >= utc(START_2026)],
            "closed_as_of_ms": AS_OF,
        }
    return symbols


def do_index() -> None:
    data = indexed_symbols()
    result = {
        "as_of": AS_OF, "as_of_utc": utc(AS_OF),
        "source": "Binance connector /fapi/v1/klines, 1d, limit 1000, current 354-symbol universe",
        "bias_note": "A snapshot of currently listed symbols excludes historical delistings. First observed candle is not verified listing time.",
        "recommended_window": {
            "start_utc": utc(START_2026), "end_exclusive_utc": utc(1790208000000),
            "explanation": "2026-01-01 through 2026-09-23 closed UTC days; per-symbol eligibility begins only after observed data and funding become available. Use Jan-Aug for archive-only verification; September requires connector funding history.",
        },
        "symbols": data,
        "counts": {
            "symbols": len(data),
            "capped_1000": sum(x["capped_1000"] for x in data.values()),
            "daily_gap_symbols": sum(bool(x["daily_gaps"]) for x in data.values()),
            "observed_by_2026_start": sum(x["first_2026_daily_utc"] is not None and x["first_observed_daily_utc"] <= utc(START_2026) for x in data.values()),
        },
    }
    save(OUT / "daily_index.json", result)
    print(json.dumps(result["counts"], ensure_ascii=False))


def validate_pages(symbol: str, pages: list[tuple[Path,dict]]) -> tuple[list[dict],dict]:
    events: list[dict] = []
    status = {"symbol": symbol, "pages": [], "complete": False, "errors": []}
    expected_start = START_2026
    for number,(path,payload) in enumerate(pages):
        request = payload.get("request", {})
        if payload.get("symbol") != symbol or int(request.get("startTime", -1)) != expected_start:
            status["errors"].append(f"Page {number} request start is not the cursor: {path.name}")
            break
        if int(request.get("endTime", -1)) != AS_OF-1:
            status["errors"].append(f"Page {number} end differs from frozen as_of: {path.name}")
            break
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            status["errors"].append(f"Page {number} rows malformed: {path.name}")
            break
        for event in rows:
            timestamp = int(event["fundingTime"])
            if event.get("symbol", symbol) != symbol or not START_2026 <= timestamp < AS_OF:
                status["errors"].append(f"Out-of-range funding row in {path.name}")
                break
            if events and timestamp <= int(events[-1]["fundingTime"]):
                status["errors"].append(f"Non-increasing funding time in {path.name}")
                break
            rate = float(event["fundingRate"])
            if not -1 <= rate <= 1:
                status["errors"].append(f"Invalid funding rate in {path.name}")
                break
            events.append(event)
        if status["errors"]:
            break
        status["pages"].append({
            "file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "request": request, "rows": len(rows),
        })
        if len(rows) < int(request.get("limit", 1000)):
            status["complete"] = True
            break
        expected_start = int(rows[-1]["fundingTime"]) + 1
    if status["complete"] and len(status["pages"]) != len(pages):
        status["errors"].append("Additional page exists after terminal short page")
    times = [int(event["fundingTime"]) for event in events]
    intervals = [(right-left)/3_600_000 for left,right in zip(times,times[1:])]
    typical = statistics.median(intervals) if intervals else None
    status.update({
        "count": len(events),
        "first_utc": utc(times[0]) if times else None,
        "last_utc": utc(times[-1]) if times else None,
        "median_interval_hours": typical,
        "interval_changes_or_gaps": [{"after_utc": utc(left), "before_utc": utc(right), "hours": round((right-left)/3_600_000,4)}
                 for left,right in zip(times,times[1:]) if typical and right-left > typical*1.5*3_600_000],
        "rates_sha256": hashlib.sha256(encode(events)).hexdigest(),
    })
    return events,status


def do_assemble() -> None:
    if not (OUT / "daily_index.json").exists():
        do_index()
    index = json.loads((OUT / "daily_index.json").read_text())
    results = {}
    complete = 0
    samples_path = OUT / "funding" / "archive_sample_2026_08.json"
    samples = json.loads(samples_path.read_text()) if samples_path.exists() else {}
    archive_checks = {}
    for symbol in sources():
        pages = [(p,json.loads(p.read_text())) for p in sorted((OUT/"funding"/"pages").glob(f"{symbol}_*.json"))]
        if not pages:
            results[symbol] = {"symbol": symbol, "complete": False, "count": 0, "errors": ["No funding pages"]}
            continue
        events,status = validate_pages(symbol,pages)
        first_observed = int(datetime.fromisoformat(index["symbols"][symbol]["first_observed_daily_utc"]).timestamp()*1000)
        expected_start = max(START_2026,first_observed)
        first_time = int(events[0]["fundingTime"]) if events else None
        last_time = int(events[-1]["fundingTime"]) if events else None
        status["first_event_delay_hours"] = round((first_time-expected_start)/3_600_000,3) if first_time is not None else None
        status["last_event_staleness_hours"] = round((AS_OF-last_time)/3_600_000,3) if last_time is not None else None
        status["usable_for_full_observed_2026_window"] = bool(
            status["complete"] and not status["errors"] and events
            and first_time-expected_start <= 24*3_600_000
            and AS_OF-last_time <= 24*3_600_000
        )
        status["no_long_interval_detected"] = not status["interval_changes_or_gaps"]
        if samples.get(symbol,{}).get("status")=="ok":
            rates={int(event["fundingTime"])//1000:Decimal(event["fundingRate"]) for event in events}
            sample_rows=samples[symbol]["rates"]
            matches=sum(rates.get(int(item["fundingTime"])//1000)==Decimal(item["fundingRate"])
                        for item in sample_rows)
            archive_checks[symbol]={"sample_rows":len(sample_rows),"matches":matches,
                                    "all_match":matches==len(sample_rows)}
        if status["complete"] and not status["errors"]:
            complete += 1
        save(OUT / "funding" / "symbols" / f"{symbol}.json", {
            "symbol": symbol, "as_of": AS_OF, "source": "Binance connector /fapi/v1/fundingRate",
            "rates": events, "validation": status,
        })
        results[symbol] = status
    manifest = {
        "as_of": AS_OF, "symbols": results,
        "complete": complete, "total_symbols": len(results),
        "archive_sample_numeric_checks": archive_checks,
        "no_imputation": "Missing pages or funding intervals are UNKNOWN; never zero.",
        "universe_bias": index["bias_note"],
    }
    save(OUT / "funding" / "manifest.json", manifest)
    print(f"complete funding symbols: {complete}/{len(results)}")


def do_queue() -> None:
    """Emit resumable connector request cursors as one machine-readable line."""
    pending = []
    for symbol in sources():
        pages = sorted((OUT / "funding" / "pages").glob(f"{symbol}_*.json"))
        if pages:
            last = json.loads(pages[-1].read_text())
            rows = last["rows"]
            if len(rows) < int(last["request"]["limit"]):
                continue
            if not rows:
                raise ValueError(f"Full empty page for {symbol}")
            start = int(rows[-1]["fundingTime"]) + 1
            sequence = len(pages)
        else:
            start = START_2026
            sequence = 0
        pending.append({"symbol": symbol, "startTime": start, "endTime": AS_OF-1,
                        "limit": 1000, "page": sequence})
    print(json.dumps(pending,ensure_ascii=False,separators=(",",":")))


def do_archive_sample() -> None:
    samples = {}
    for symbol in SAMPLE_SYMBOLS:
        encoded = urllib.parse.quote(symbol, safe="")
        url = f"{ARCHIVE}/{encoded}/{encoded}-fundingRate-2026-08.zip"
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"transaction-push-research/1.0"}),timeout=25) as response:
                raw=response.read()
            with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
                if zipped.testzip() is not None:
                    raise ValueError("ZIP checksum failed")
                members=[name for name in zipped.namelist() if name.endswith(".csv")]
                if len(members)!=1:
                    raise ValueError(f"Expected one CSV: {members}")
                rows=list(csv.reader(io.TextIOWrapper(zipped.open(members[0]),encoding="utf-8-sig")))
            if rows and not rows[0][0].isdigit():
                rows=rows[1:]
            samples[symbol]={"url":url,"status":"ok","zip_sha256":hashlib.sha256(raw).hexdigest(),
                             "rows":len(rows),"first_funding_utc":utc(int(rows[0][0])) if rows else None,
                             "last_funding_utc":utc(int(rows[-1][0])) if rows else None,
                             "rates": [{"fundingTime":int(row[0]),"fundingIntervalHours":int(row[1]),"fundingRate":row[2]} for row in rows]}
        except urllib.error.HTTPError as exc:
            if exc.code in (418,429):
                raise RuntimeError(f"Rate limited on {url}: HTTP {exc.code}") from exc
            if exc.code!=404:
                raise
            samples[symbol]={"url":url,"status":"not_published_or_not_listed","http_status":404}
    save(OUT / "funding" / "archive_sample_2026_08.json", samples)
    print({symbol:(value["status"],value.get("rows")) for symbol,value in samples.items()})


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("index","assemble","archive-sample","queue"))
    args=parser.parse_args()
    {"index":do_index,"assemble":do_assemble,"archive-sample":do_archive_sample,"queue":do_queue}[args.mode]()


if __name__=="__main__":
    main()
