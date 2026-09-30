#!/usr/bin/env python3
"""Measure forward process, storage and candle progress across separate sessions.

This produces bounded evidence on the host where it runs, never a hosting/SLA
guarantee. Run checkpoint before leaving that environment and check after return.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

import pandas as pd

from forward_bootstrap import load_public
from forward_expanded_core import owned_pid
from forward_runtime import digest, verify_bundle
from prepare_expanded_core_data import save, write
from replay_expanded_core import validate_frame

STEP = 300_000
MAX_OBSERVATION_LAG_MS = 120_000


def read(path):
    return json.loads(Path(path).read_text())


def value_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sealed_frame(out, symbol):
    path = out / 'series' / (symbol + '.feather')
    # An active writer can replace the feather just before replacing its seal.
    for attempt in range(3):
        try:
            before = digest(path)
            frame = pd.read_feather(path)
            if before == path.with_suffix('.sha256').read_text().strip() == digest(path):
                return frame
        except (FileNotFoundError, OSError):
            pass
        if attempt < 2:
            time.sleep(.1)
    raise ValueError(symbol + ': candle file/seal changed or is unreadable')


def inspect(out, now=None):
    out = Path(out).resolve()
    now = int(time.time() * 1000) if now is None else now
    verify_bundle(out / 'code')
    protocol = read(out / 'protocol.json')
    protocol_sha = digest(out / 'protocol.json')
    require(protocol_sha == (out / 'protocol.sha256').read_text().strip(), 'Protocol seal mismatch')
    for path, expected in protocol['sources'].items():
        require(digest(out / 'code' / path) == expected, 'Protocol source mismatch: ' + path)
    require(digest(out / 'code' / protocol['tiers_path']) == protocol['tiers_sha256'], 'Tier hash mismatch')
    if protocol.get('bootstrap_mode') == 'public':
        public = load_public(out, protocol['bootstrap_manifest_sha256'])
        require(public['files'] == protocol['bootstrap'] and public['start_ms'] == protocol['warmup_ms'],
                'Bootstrap inputs mismatch')
        commit = read(out / 'initialization.json')
        require(commit['state'] == 'frozen' and commit['persisted_ms'] < protocol['seed_ms'],
                'Public protocol was not sealed before seed')
    else:
        require(digest(out / 'code/reports/quant_v12/protocol.json') == protocol['historical_protocol_sha256'],
                'Historical protocol hash mismatch')
    pid = owned_pid(out)
    runtime, latest = read(out / 'runtime.json'), read(out / 'latest.json')
    require(pid is not None and runtime.get('pid') == pid, 'No matching live worker PID/command')
    require(runtime['state'] == 'observing' and not runtime.get('consecutive_failures'), 'Worker is not observing successfully')
    require(-120_000 <= now - runtime['updated_ms'] <= 180_000, 'Worker heartbeat is stale')
    require(-120_000 <= now - latest['observed_ms'] <= 600_000, 'Successful observation is stale')
    end = latest['data_end_ms']
    require(0 <= now - end <= 600_000 and end <= protocol['stop_ms'], 'Candle data is stale or beyond deadline')
    require(latest['protocol_sha256'] == protocol_sha, 'Snapshot protocol mismatch')
    require(set(latest['arms']) == set(protocol['arms']), 'Missing simulation accounts')
    marks = {}
    for symbol in protocol['symbols']:
        frame = sealed_frame(out, symbol)
        validate_frame(frame, protocol['warmup_ms'], int(frame.timestamp.iloc[-1]) + STEP, symbol)
        closed = frame[frame.timestamp == end - STEP]
        require(len(closed) == 1, symbol + ': missing snapshot candle')
        marks[symbol] = float(closed.iloc[0].mark_close)
    evidence = {}
    core = latest['arms']['TriHold']['core']
    for name, arm in latest['arms'].items():
        require(arm['core'] == core, name + ': control core differs')
        cash = protocol['capital']
        quantities = dict.fromkeys(protocol['symbols'], 0.)
        for event in arm['events']:
            require(event['timestamp'] >= protocol['seed_ms'] and
                    event['timestamp'] < end and
                    event['timestamp'] + STEP <= event['first_observed_ms'] <= latest['observed_ms'],
                    name + ': invalid model/first-observed timestamp')
            if event['side'] == 'funding':
                cash -= event['payment']
            else:
                require(event['side'] in ('buy', 'sell'), 'Unknown event side')
                sign = 1 if event['side'] == 'buy' else -1
                quantities[event['symbol']] += sign * event['amount']
                cash -= sign * event['amount'] * event['price'] + event['fee']
        initial = [e for e in arm['events'] if e['side'] == 'buy' and e['sleeve'] == 'core']
        require(len(initial) == 3 and {e['symbol'] for e in initial} == set(protocol['symbols']),
                name + ': expected three initial model buys')
        require(all(e['timestamp'] == protocol['seed_ms'] and e['first_observed_ms'] >= e['timestamp'] + STEP
                    for e in initial), name + ': seed or initial observation changed')
        for symbol, quantity in quantities.items():
            require(math.isclose(quantity, arm['positions'].get(symbol, {}).get('quantity', 0.), abs_tol=1e-8),
                    name + ': event/position quantity mismatch')
        equity = cash + sum(quantities[s] * marks[s] for s in quantities)
        errors = [equity - arm['account']['equity'], equity - arm['metrics']['final_equity']]
        require(all(math.isfinite(e) and abs(e) < .01 for e in errors), name + ': independent cashflow reconciliation failed')
        evidence[name] = dict(events=len(arm['events']), events_sha256=value_sha(arm['events']),
                             initial_model_buys=len(initial), equity=equity,
                             reconciliation_error=max(abs(e) for e in errors))
    return dict(checked_ms=now, pid=pid, protocol_sha256=protocol_sha,
                bundle_sha256=digest(out / 'code/bundle.json'),
                data_end_ms=end, observed_ms=latest['observed_ms'],
                late_collection=latest['late_collection'], arms=evidence), latest


def checkpoint(out):
    evidence, _ = inspect(out)
    identifier = uuid.uuid4().hex
    nonce = Path('checks') / (identifier + '.nonce')
    write(out / nonce, uuid.uuid4().bytes)
    record = dict(evidence, nonce_path=str(nonce), nonce_sha256=digest(out / nonce))
    path = out / 'checks' / (identifier + '.checkpoint.json')
    save(path, dict(record=record, sha256=value_sha(record)))
    return dict(state='checkpoint_saved', checkpoint=str(path), **evidence)


def check(out, checkpoint_path):
    stored = read(checkpoint_path)
    before = stored['record']
    require(value_sha(before) == stored['sha256'], 'Checkpoint seal mismatch')
    nonce = Path(before['nonce_path'])
    require(len(nonce.parts) == 2 and nonce.parts[0] == 'checks' and nonce.suffix == '.nonce', 'Invalid persistence nonce path')
    require(digest(out / nonce) == before['nonce_sha256'], 'Persistent storage nonce is missing/changed')
    evidence, latest = inspect(out)
    for field in ('protocol_sha256', 'bundle_sha256'):
        require(evidence[field] == before[field], 'Frozen batch identity changed: ' + field)
    require(evidence['checked_ms'] > before['checked_ms'], 'Check must run after checkpoint')
    for name, previous in before['arms'].items():
        require(value_sha(latest['arms'][name]['events'][:previous['events']]) == previous['events_sha256'],
                name + ': prior events or first-observed times changed')
    ends = list(range(before['data_end_ms'] + STEP, evidence['data_end_ms'] + STEP, STEP))
    require(len(ends) >= 2, 'Need at least two new completed 5m observations after checkpoint')
    last_observed = before['observed_ms']
    for end in ends:
        path = out / 'snapshots' / (str(end) + '.json.gz')
        require(path.exists(), 'Missing intermediate observation snapshot; catch-up is not continuity')
        snapshot = json.loads(gzip.decompress(path.read_bytes()))
        require(snapshot['data_end_ms'] == end and snapshot['protocol_sha256'] == before['protocol_sha256'],
                'Intermediate snapshot identity mismatch')
        observed = snapshot['observed_ms']
        require(last_observed < observed <= evidence['checked_ms']
                and 0 <= observed - end <= MAX_OBSERVATION_LAG_MS,
                'Observation timestamp is nonmonotonic or exceeds the 120-second latency limit')
        require(not snapshot['late_collection']
                and snapshot['new_completed_5m'] == 1, 'Late/catch-up observation inside measured window')
        last_observed = observed
    require(last_observed == evidence['observed_ms'], 'Latest observation differs from its saved snapshot')
    return dict(state='measured_window_passed', new_completed_5m=len(ends),
                maximum_allowed_observation_lag_ms=MAX_OBSERVATION_LAG_MS,
                process_restarted=evidence['pid'] != before['pid'], **evidence,
                limitation='Only this measured host/window. Run check in a later target cloud session; not a 24/7 hosting guarantee.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('checkpoint', 'check'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--checkpoint', type=Path)
    args = parser.parse_args()
    if args.command == 'check' and args.checkpoint is None:
        parser.error('check requires --checkpoint from an earlier session')
    out = args.output.resolve()
    try:
        result = checkpoint(out) if args.command == 'checkpoint' else check(out, args.checkpoint)
        code = 0
    except Exception as error:
        result = dict(state='not_verified', checked_ms=int(time.time() * 1000),
                      error_type=type(error).__name__, error=str(error))
        code = 1
    save(out / 'checks' / ('probe-' + str(result['checked_ms']) + '-' + uuid.uuid4().hex[:8] + '.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
