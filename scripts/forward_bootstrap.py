"""Resumable, independently sourced public warmup for new forward batches."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import pandas as pd

from forward_runtime import AccessDenied, RateLimited, digest
from prepare_expanded_core_data import save, write
from replay_expanded_core import validate_frame

STEP = 300_000
DAY = 86_400_000
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'ZECUSDT')
ENDPOINTS = ('/fapi/v1/klines', '/fapi/v1/markPriceKlines')


class PreparationCancelled(RuntimeError):
    pass


def check_cancelled(out):
    if (Path(out) / 'stop_requested.json').exists():
        raise PreparationCancelled('Public preparation stopped by user; no new seed may be frozen')


def read(path):
    return json.loads(Path(path).read_text())


def rows_digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def check_rows(rows, start, end):
    if not isinstance(rows, list) or len(rows) != (end - start) // STEP:
        raise ValueError('Public warmup page has missing candles')
    for row, at in zip(rows, range(start, end, STEP), strict=True):
        if len(row) != 12 or int(row[0]) != at or int(row[6]) != at + STEP - 1:
            raise ValueError('Public warmup candles are malformed or not consecutive')


def load_public(out, expected_manifest_sha=None):
    ready = Path(out) / 'bootstrap/ready'
    path = ready / 'manifest.json'
    seal = (ready / 'manifest.sha256').read_text().strip()
    if digest(path) != seal or (expected_manifest_sha is not None and seal != expected_manifest_sha):
        raise ValueError('Public warmup manifest changed')
    manifest = read(path)
    if manifest['kind'] != 'public_rest_warmup' or set(manifest['files']) != set(SYMBOLS):
        raise ValueError('Public warmup universe changed')
    for symbol, item in manifest['files'].items():
        # Fixed filenames prevent a manifest from redirecting input outside the batch.
        if item['path'] != f'bootstrap/ready/{symbol}.feather':
            raise ValueError('Invalid public warmup path')
        if digest(Path(out) / item['path']) != item['sha256']:
            raise ValueError(symbol + ': public warmup file changed')
    return manifest


def prepare_public(out, api):
    """Called under runner.lock, before any seed/protocol or trading event exists."""
    out = Path(out)
    check_cancelled(out)
    base = out / 'bootstrap'
    ready = base / 'ready'
    if ready.exists():
        return load_public(out)
    base.mkdir(parents=True, exist_ok=True)
    status_path = base / 'status.json'
    status = read(status_path) if status_path.exists() else {}
    now = int(time.time() * 1000)
    if status.get('state') == 'access_denied':
        raise AccessDenied('Public warmup access denied; manual review required')
    if status.get('retry_at_ms', 0) > now:
        raise RateLimited(status['retry_at_ms'])
    try:
        server = int(api.fetch('/fapi/v1/time')['serverTime'])
        now = int(time.time() * 1000)
        if abs(server - now) > 120_000:
            raise ValueError('Public warmup server clock differs by more than 120 seconds')
        end = (min(server, now) - 15_000) // STEP * STEP
        plan_path = base / 'plan.json'
        if plan_path.exists():
            stored = read(plan_path)
            plan = stored['plan']
            if rows_digest(plan) != stored['sha256']:
                raise ValueError('Public warmup download plan changed')
            if plan['symbols'] != list(SYMBOLS) or plan['start_ms'] % DAY:
                raise ValueError('Invalid public warmup plan')
        else:
            plan = dict(symbols=list(SYMBOLS), start_ms=(end // DAY) * DAY - 92 * DAY,
                        created_ms=now, first_end_ms=end)
            save(plan_path, dict(plan=plan, sha256=rows_digest(plan)))
        start = plan['start_ms']
        if end < plan['first_end_ms'] or end - start < 92 * DAY:
            raise ValueError('Public warmup clock moved backwards')
        frames, pages = {}, []
        total = len(SYMBOLS) * len(ENDPOINTS) * ((end - start + 1000 * STEP - 1) // (1000 * STEP))
        for symbol in SYMBOLS:
            series = []
            for endpoint in ENDPOINTS:
                rows = []
                for first in range(start, end, 1000 * STEP):
                    check_cancelled(out)
                    last = min(first + 1000 * STEP, end)
                    params = dict(symbol=symbol, interval='5m', startTime=first,
                                  endTime=last - 1, limit=1000)
                    path = base / 'pages' / symbol / endpoint.rsplit('/', 1)[-1] / f'{first}-{last}.json'
                    if path.exists():
                        page = read(path)
                        if page['endpoint'] != endpoint or page['params'] != params or rows_digest(page['rows']) != page['rows_sha256']:
                            raise ValueError('Cached public warmup page changed')
                    else:
                        value = api.fetch(endpoint, params)
                        check_rows(value, first, last)
                        page = dict(endpoint=endpoint, params=params, rows=value,
                                    rows_sha256=rows_digest(value), observed_ms=int(time.time() * 1000))
                        save(path, page)  # One atomic record: page and checksum commit together.
                    check_rows(page['rows'], first, last)
                    rows.extend(page['rows'])
                    pages.append(dict(path=str(path.relative_to(out)), sha256=digest(path)))
                    save(status_path, dict(state='downloading', updated_ms=int(time.time() * 1000),
                         completed_pages=len(pages), total_pages=total, symbol=symbol, end_ms=end))
                series.append(rows)
            trade, marks = series
            frame = pd.DataFrame([dict(timestamp=int(t[0]), open=float(t[1]), high=float(t[2]),
                low=float(t[3]), close=float(t[4]), quote_volume=float(t[7]),
                mark_open=float(m[1]), mark_high=float(m[2]), mark_low=float(m[3]), mark_close=float(m[4]))
                for t, m in zip(trade, marks, strict=True)])
            validate_frame(frame, start, end, symbol)
            frames[symbol] = frame
        check_cancelled(out)
        temporary = Path(tempfile.mkdtemp(prefix='.ready-', dir=base))
        try:
            files = {}
            for symbol, frame in frames.items():
                path = temporary / f'{symbol}.feather'
                frame.to_feather(path)
                with path.open('rb') as handle:
                    os.fsync(handle.fileno())
                files[symbol] = dict(path=f'bootstrap/ready/{symbol}.feather', sha256=digest(path),
                                     storage='batch', rows=len(frame))
            manifest = dict(kind='public_rest_warmup', start_ms=start, end_ms=end,
                            completed_ms=int(time.time() * 1000), files=files, pages=pages,
                            source='Binance public USD-M trade and mark 5m klines',
                            plan_sha256=digest(plan_path))
            save(temporary / 'manifest.json', manifest)
            write(temporary / 'manifest.sha256', (digest(temporary / 'manifest.json') + '\n').encode())
            temporary.rename(ready)  # All symbols become visible together, never a partial seal.
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        save(status_path, dict(state='ready', updated_ms=int(time.time() * 1000),
                              completed_pages=total, total_pages=total, end_ms=end))
        return load_public(out)
    except Exception as error:
        state = ('cancelled' if isinstance(error, PreparationCancelled) else
                 'access_denied' if isinstance(error, AccessDenied) else
                 'rate_limited' if isinstance(error, RateLimited) else 'download_error')
        save(status_path, dict(state=state, updated_ms=int(time.time() * 1000),
                              error_type=type(error).__name__, error=str(error),
                              retry_at_ms=getattr(error, 'retry_at_ms', 0)))
        raise
