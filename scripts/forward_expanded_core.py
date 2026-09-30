#!/usr/bin/env python3
"""Frozen v12 TriEnhance/TriHold observation on newly arriving public candles.

This is a prospective candle simulation, not an exchange order executor. Every
fill has a model timestamp and a separate first-observed timestamp. Old account
files and the v12 historical protocol remain untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.quant.expanded_forward import run_forward
from prepare_expanded_core_data import FAPI, iso, save, write
from forward_runtime import (AccessDenied, PublicTransport, RateLimited,
                             build_bundle, network_settings, verify_bundle)
from forward_bootstrap import check_cancelled, load_public, prepare_public
from replay_expanded_core import EpochValues, features_from_frame, validate_frame

STEP = 300_000
DAY = 86_400_000
H4 = 14_400_000
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'ZECUSDT')
ARMS = {'TriHold': dict(weight=0, exit_ema=200),
        'TriEnhance': dict(weight=.4, exit_ema=200),
        'TriEnhance20': dict(weight=.2, exit_ema=200)}
SOURCES = ('app/quant/expanded_forward.py', 'app/quant/core_overlay.py',
           'app/quant/cross_margin.py', 'scripts/forward_expanded_core.py',
           'scripts/replay_expanded_core.py', 'scripts/replay_core_overlay.py',
           'scripts/replay_cross_margin.py', 'scripts/stop_provenance.py',
           'scripts/prepare_expanded_core_data.py', 'scripts/forward_runtime.py',
           'app/quant/expanded_core.py', 'app/__init__.py', 'app/quant/__init__.py',
           'scripts/forward_bootstrap.py', 'scripts/check_forward_runtime.py')
STOP = False


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def ms(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Explicit timezone required')
    return int(parsed.timestamp() * 1000)


def next_seed(now):
    """Start at the next future 5m boundary; never buy at an already known open."""
    return (int(now) // STEP + 1) * STEP


class PublicData:
    def __init__(self, out):
        self.out = out
        self.transport = PublicTransport(ROOT)

    def close(self):
        self.transport.close()

    def fetch(self, path, params=None):
        check_cancelled(self.out)
        if path not in ('/fapi/v1/time', '/fapi/v1/exchangeInfo',
                        '/fapi/v1/fundingInfo', '/fapi/v1/klines',
                        '/fapi/v1/markPriceKlines', '/fapi/v1/fundingRate'):
            raise ValueError('Non-public endpoint rejected')
        gate_path = self.out / 'public_access.json'
        gate = read(gate_path) if gate_path.exists() else {}
        if gate.get('state') == 'access_denied':
            raise AccessDenied('Public API access denied; manual review required')
        if gate.get('retry_at_ms', 0) > int(time.time() * 1000):
            raise RateLimited(gate['retry_at_ms'])
        try:
            raw = self.transport.get(FAPI + path, params)
        except (RateLimited, AccessDenied) as error:
            save(gate_path, dict(state='rate_limited' if isinstance(error, RateLimited) else 'access_denied',
                                updated_ms=int(time.time() * 1000), retry_at_ms=getattr(error, 'retry_at_ms', 0)))
            raise
        if gate.get('state') == 'rate_limited':
            save(gate_path, dict(state='available', updated_ms=int(time.time() * 1000), retry_at_ms=0))
        check_cancelled(self.out)
        observed = int(time.time() * 1000)
        digest = hashlib.sha256(raw).hexdigest()
        target = self.out / 'raw' / (digest + '.json')
        if not target.exists():
            write(target, raw)
        append(self.out / 'requests.jsonl', dict(observed_ms=observed,
               endpoint=path, params=params, sha256=digest))
        return json.loads(raw)


def initialize(out, until, api):
    path = out / 'protocol.json'
    if path.exists():
        protocol = read(path)
        seal = out / 'protocol.sha256'
        if not seal.exists() or seal.read_text().strip() != sha(path):
            raise ValueError('Forward protocol seal mismatch')
        if until is not None and ms(until) != protocol['stop_ms']:
            raise ValueError('Existing session deadline is frozen')
        if protocol.get('bootstrap_mode') == 'public':
            commit = read(out / 'initialization.json')
            if commit['state'] != 'frozen' or commit['persisted_ms'] >= protocol['seed_ms']:
                raise ValueError('Protocol was not sealed before seed; preserve this batch and use a new output')
        verify_protocol(protocol, out)
        return protocol
    if until is None:
        raise ValueError('New session requires --until with explicit timezone')
    now = int(time.time() * 1000)
    end = ms(until)
    if end % STEP or end <= now:
        raise ValueError('Deadline must be a future 5m boundary')
    bundle_path = ROOT / 'bundle.json'
    mode = read(bundle_path).get('bootstrap_mode', 'historical') if bundle_path.exists() else 'historical'
    public = prepare_public(out, api) if mode == 'public' else None
    info = api.fetch('/fapi/v1/exchangeInfo')
    funding_info = api.fetch('/fapi/v1/fundingInfo')
    intervals = {r['symbol']: int(r['fundingIntervalHours']) for r in funding_info}
    filters = {}
    for symbol in SYMBOLS:
        row = next(r for r in info['symbols'] if r['symbol'] == symbol)
        if row['status'] != 'TRADING' or row['contractType'] != 'PERPETUAL' or row['quoteAsset'] != 'USDT':
            raise ValueError(symbol + ': not an eligible public USDT perpetual')
        lookup = {f['filterType']: f for f in row['filters']}
        filters[symbol] = dict(lot=lookup['LOT_SIZE'], minimum=lookup['MIN_NOTIONAL'],
                               funding_hours=intervals.get(symbol, 8))
        if filters[symbol]['funding_hours'] not in (1, 2, 4, 8):
            raise ValueError('Unsupported funding schedule')
    tier_path = ROOT / 'reports/quant_v9/binance_leverage_tiers.json'
    if public:
        bootstrap = public['files']
        # Catch up a resumed prefix before freezing the future seed. No model
        # order or event is created while preparing these public inputs.
        server = int(api.fetch('/fapi/v1/time')['serverTime'])
        now = int(time.time() * 1000)
        if abs(server - now) > 120_000:
            raise ValueError('Public server clock differs by more than 120 seconds')
        tail_end = (min(server, now) - 15_000) // STEP * STEP
        for symbol in SYMBOLS:
            refresh_frame(out, dict(bootstrap=bootstrap, warmup_ms=public['start_ms']), symbol, tail_end, api)
        historical_sha = None
    else:
        historical = read(ROOT / 'reports/quant_v12/protocol.json')
        bootstrap = {s: dict(path=f'reports/quant_v12/data/series/{s}.feather',
                            sha256=historical['data'][f'reports/quant_v12/data/series/{s}.feather'])
                     for s in SYMBOLS}
        historical_sha = sha(ROOT / 'reports/quant_v12/protocol.json')
    now = int(time.time() * 1000)
    # Cold preparation must leave time to seal files and start the worker.
    start = seed = next_seed(now + 30_000 if public else now)
    if seed + STEP > end:
        raise ValueError('No complete future 5m seed candle before requested deadline')
    protocol = dict(study='v12_forward_' + out.name, frozen_ms=now,
        start_ms=start, seed_ms=seed, stop_ms=end,
        seed_policy='Next future 5m boundary after initialization; public mode reserves at least 30 seconds for sealing/startup. Frozen before its opening price is known.',
        warmup_ms=public['start_ms'] if public else (start // DAY) * DAY - 92 * DAY,
        symbols=list(SYMBOLS), capital=10000., nominal_core_budget=.7,
        arms=ARMS, fee=.001, filters=filters, bootstrap=bootstrap,
        tiers_path=str(tier_path.relative_to(ROOT)), tiers_sha256=sha(tier_path),
        bootstrap_mode=mode,
        bootstrap_manifest_sha256=sha(out / 'bootstrap/ready/manifest.json') if public else None,
        historical_protocol_sha256=historical_sha,
        sources={p: sha(ROOT / p) for p in SOURCES},
        execution='Frozen prospective 5m candle-open simulation, recorded only after candle close. No live bid/ask fills. First observation time retained. Late catch-up is labeled, never real-time execution.',
        cutoff='Keep core and overlay positions marked at cutoff; no fabricated terminal sale.',
        evaluation='At least 30 natural days and 10 fully closed overlay positions before assessment. This sampling threshold never authorizes live trading or proves effectiveness.',
        live_trading_enabled=False,
        snapshot_format='gzip JSON, lossless full snapshots with first-observed event times',
        limitations=['Static v9 maintenance tiers; current public quantity filters.',
                     'No order-book depth, actual liquidation, ordinary-position mixture or live orders.',
                     'Joint mark lows are a stress bound, not synchronous traded ticks.',
                     'TriEnhance40 baseline, identical-seed TriHold control, and pre-registered TriEnhance20 candidate. Other expanded allocations remain historical research.'])
    verify_protocol(protocol, out)
    check_cancelled(out)
    save(path, protocol)
    write(out / 'protocol.sha256', (sha(path) + '\n').encode())
    if public:
        persisted = int(time.time() * 1000)
        state = 'frozen' if persisted < seed else 'missed_seed_boundary'
        save(out / 'initialization.json', dict(state=state, persisted_ms=persisted))
        if state != 'frozen':
            raise ValueError('Sealing crossed seed boundary; preserve this batch and use a new output')
    return protocol


def verify_protocol(protocol, out=None):
    if protocol['symbols'] != list(SYMBOLS) or protocol['arms'] != ARMS:
        raise ValueError('Frozen forward universe/rules changed')
    for path, expected in protocol['sources'].items():
        if sha(ROOT / path) != expected:
            raise ValueError('Frozen forward source changed: ' + path)
    if sha(ROOT / protocol['tiers_path']) != protocol['tiers_sha256']:
        raise ValueError('Frozen maintenance tiers changed')
    if protocol.get('bootstrap_mode') == 'public':
        public = load_public(out, protocol['bootstrap_manifest_sha256'])
        if public['files'] != protocol['bootstrap'] or public['start_ms'] != protocol['warmup_ms']:
            raise ValueError('Frozen public warmup inputs changed')
    elif sha(ROOT / 'reports/quant_v12/protocol.json') != protocol['historical_protocol_sha256']:
        raise ValueError('Frozen v12 historical protocol changed')


def fetch_bars(api, symbol, endpoint, start, end):
    result = []
    while start < end:
        rows = api.fetch(endpoint, dict(symbol=symbol, interval='5m',
                         startTime=start, endTime=min(end, start + 1000 * STEP) - 1, limit=1000))
        if not rows:
            raise ValueError(symbol + ': missing closed public candles')
        for row in rows:
            if len(row) != 12 or int(row[0]) != start or int(row[6]) != start + STEP - 1:
                raise ValueError(symbol + ': non-consecutive or malformed public candles')
            if start >= end:
                raise ValueError('Endpoint included future/unclosed candle')
            result.append(row)
            start += STEP
    return result


def refresh_frame(out, protocol, symbol, end, api):
    path = out / 'series' / (symbol + '.feather')
    seal = path.with_suffix('.sha256')
    if path.exists():
        if not seal.exists() or sha(path) != seal.read_text().strip():
            raise ValueError(symbol + ': forward cache hash mismatch')
        frame = pd.read_feather(path)
    else:
        bootstrap = protocol['bootstrap'][symbol]
        source = (out if bootstrap.get('storage') == 'batch' else ROOT) / bootstrap['path']
        if sha(source) != bootstrap['sha256']:
            raise ValueError(symbol + ': historical warmup hash mismatch')
        frame = pd.read_feather(source)
        frame = frame[(frame.timestamp >= protocol['warmup_ms']) & (frame.timestamp < end)].reset_index(drop=True)
    start = int(frame.timestamp.iloc[-1]) + STEP
    if start < end:
        trade = fetch_bars(api, symbol, '/fapi/v1/klines', start, end)
        marks = fetch_bars(api, symbol, '/fapi/v1/markPriceKlines', start, end)
        extra = pd.DataFrame([dict(timestamp=int(t[0]), open=float(t[1]),
            high=float(t[2]), low=float(t[3]), close=float(t[4]), quote_volume=float(t[7]),
            mark_open=float(m[1]), mark_high=float(m[2]), mark_low=float(m[3]),
            mark_close=float(m[4])) for t, m in zip(trade, marks, strict=True)])
        frame = pd.concat([frame, extra], ignore_index=True)
    validate_frame(frame, protocol['warmup_ms'], end, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    frame.to_feather(temporary)
    temporary.replace(path)
    write(seal, (sha(path) + '\n').encode())
    return frame


def funding_events(api, symbol, protocol, end):
    start = protocol['start_ms']
    hours = protocol['filters'][symbol]['funding_hours']
    period = hours * 3_600_000
    expected = set(range(((start + period - 1) // period) * period, end, period))
    if not expected:
        return {}
    events = {}
    cursor = start
    while cursor < end:
        rows = api.fetch('/fapi/v1/fundingRate', dict(symbol=symbol,
                         startTime=cursor, endTime=end - 1, limit=1000))
        if not rows:
            break
        for r in rows:
            original = int(r['fundingTime'])
            at = original // STEP * STEP
            rate, mark = float(r['fundingRate']), float(r['markPrice'])
            if (r['symbol'] != symbol or not start <= at < end or original - at > 999
                    or at in events or not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0):
                raise ValueError(symbol + ': invalid actual funding event')
            events[at] = (rate, mark)
        cursor = int(rows[-1]['fundingTime']) + 1
        if len(rows) < 1000:
            break
    if set(events) != expected:
        raise ValueError(symbol + ': missing funding or changed settlement schedule')
    return events


def seed_trades(protocol, frames):
    at = protocol['seed_ms']
    trades = []
    for symbol in SYMBOLS:
        frame = frames[symbol]
        # Before the seed bar is complete no position and no guessed seed price.
        if at > int(frame.timestamp.iloc[-1]):
            return None
        row = frame.loc[frame.timestamp == at].iloc[0]
        price = float(row.open)
        filters = protocol['filters'][symbol]
        step = float(filters['lot']['stepSize'])
        quantity = math.floor((protocol['capital'] * .7 / 3 / price) / step + 1e-10) * step
        if (quantity < float(filters['lot']['minQty']) or quantity > float(filters['lot']['maxQty'])
                or quantity * price < float(filters['minimum']['notional'])):
            raise ValueError(symbol + ': initial core cannot satisfy frozen filters')
        trades.append(dict(pair=symbol.removesuffix('USDT') + '/USDT:USDT', amount=quantity,
            open_timestamp=at, open_rate=price, close_timestamp=protocol['stop_ms'], close_rate=price))
    return trades


def preserve_events(old, new, observed):
    if len(new) < len(old):
        raise ValueError('Forward event history shortened')
    for i, event in enumerate(old):
        original = {k: v for k, v in event.items() if k not in ('first_observed_ms', 'observation_lag_ms')}
        if original != new[i]:
            raise ValueError('Previously observed forward event changed')
    return old + [dict(e, first_observed_ms=observed,
                       observation_lag_ms=max(0, observed - e['timestamp'])) for e in new[len(old):]]


def report(out, protocol, snapshot):
    lines = ['# v12 冻结规则前向模拟', '',
        f"状态：{snapshot['state']}；更新 UTC：{iso(snapshot['observed_ms'])}。",
        f"初始建仓 UTC：{iso(protocol['seed_ms'])}；截止 UTC：{iso(protocol['stop_ms'])}。", '',
        f'{len(protocol.get("arms", ARMS))} 个独立账户各 10,000 USDT 模拟资金，三币底仓合计约 70% 初始名义金额；增强上限分别冻结在协议中。只在已完成 K 线后记录模拟成交。', '',
        '| 方案 | 盯市权益 | 收益 | 回撤 | 增强买入 | 增强退出轮次 |',
        '|---|---:|---:|---:|---:|---:|']
    for arm, result in snapshot.get('arms', {}).items():
        m = result['metrics']
        lines.append(f"| {arm} | {m['final_equity']:.2f} | {m['return_pct']:.3f}% | {m['sampled_mark_drawdown_pct']:.3f}% | {m['add_fills']} | {m['overlay_exit_rounds'] + m['risk_reduction_rounds']} |")
    if not snapshot.get('arms'):
        lines += ['', '正在采集和核验预热数据，等待预先冻结的下一根 5m 建仓 K 线完成后记账；尚无已确认模拟持仓。']
    lines += ['', '截止时只盯市、保留模拟持仓，不伪造成交。断线后的补采明确属于延迟观察；不代表实时可成交。',
        '至少 30 自然日及主动策略 10 笔真正闭合交易后才开始评价；达到样本门槛不代表策略有效，更不授权真实交易。',
        '每次公开响应、哈希、首次观察时间、费用、真实资金费、风险与错误均保存在本目录；旧 v6 及全池账户没有恢复。']
    write(out / 'REPORT.md', ('\n'.join(lines) + '\n').encode())


def closed_overlay_positions(events):
    quantities, closed = {}, 0
    for event in events:
        if event.get('sleeve') != 'overlay' or event['side'] not in ('buy', 'sell'):
            continue
        symbol = event['symbol']
        before = quantities.get(symbol, 0.)
        after = before + event['amount'] * (1 if event['side'] == 'buy' else -1)
        if after < -1e-8:
            raise ValueError('Overlay sells exceed observed purchases')
        if event['side'] == 'sell' and before > 1e-8 and after <= 1e-8:
            closed += 1
        quantities[symbol] = max(0., after)
    return closed


def observation_timing(previous, observed, end, seed):
    previous_end = previous.get('data_end_ms', seed)
    previous_observed = previous.get('observed_ms', seed)
    new_bars = max(0, (end - max(seed, previous_end)) // STEP)
    gap = max(0, observed - previous_observed)
    return dict(late_collection=bool(new_bars > 1 or gap > 2 * STEP),
                observation_gap_ms=gap, new_completed_5m=new_bars,
                data_lag_ms=max(0, observed - end))


def cycle(out, protocol, api):
    verify_protocol(protocol, out)
    if sha(out / 'protocol.json') != (out / 'protocol.sha256').read_text().strip():
        raise ValueError('Forward protocol seal mismatch')
    observed = int(time.time() * 1000)
    server = int(api.fetch('/fapi/v1/time')['serverTime'])
    if abs(server - observed) > 120_000:
        raise ValueError('Public server clock is stale or differs by more than 120 seconds')
    end = min((min(server, observed) - 15_000) // STEP * STEP, protocol['stop_ms'])
    previous = read(out / 'latest.json') if (out / 'latest.json').exists() else {}
    if end <= previous.get('data_end_ms', 0):
        return dict(previous, state='observing' if previous.get('arms') else 'waiting_for_first_bar')
    frames = {s: refresh_frame(out, protocol, s, end, api) for s in SYMBOLS}
    funding = {s: funding_events(api, s, protocol, end) for s in SYMBOLS}
    data = {}
    full4h = end // H4 * H4
    for s, frame in frames.items():
        data[s] = dict(price=EpochValues(protocol['warmup_ms'], frame.open.to_numpy()),
            marks=EpochValues(protocol['warmup_ms'], frame[['mark_open', 'mark_close', 'mark_low']].to_numpy()),
            features=features_from_frame(frame[frame.timestamp < full4h]), funding=funding[s])
    trades = seed_trades(protocol, frames)
    results = {}
    if trades:
        tier_data = read(ROOT / protocol['tiers_path'])
        tiers = {s: tier_data[s.removesuffix('USDT') + '/USDT:USDT'] for s in SYMBOLS}
        steps = {s: float(protocol['filters'][s]['lot']['stepSize']) for s in SYMBOLS}
        for arm, rule in ARMS.items():
            value = run_forward(rule, trades, data, tiers, steps, protocol['fee'],
                [iso(protocol['start_ms']), iso(end)], capital=protocol['capital'])
            value.pop('frame')
            old = previous.get('arms', {}).get(arm, {}).get('events', [])
            value['events'] = preserve_events(old, value['events'], int(time.time() * 1000))
            value['orders'] = [e for e in value['events'] if e['side'] != 'funding']
            value['metrics']['evaluation_ready'] = False
            value['metrics']['observation_days'] = (end - protocol['seed_ms']) / DAY
            value['metrics']['fully_closed_overlay_positions'] = closed_overlay_positions(value['events'])
            value['metrics']['minimum_sample_reached'] = (
                value['metrics']['observation_days'] >= 30 and
                (not rule['weight'] or value['metrics']['fully_closed_overlay_positions'] >= 10))
            results[arm] = value
        if any(value['core'] != results['TriHold']['core'] for value in results.values()):
            raise ValueError('Control and enhancement core differ')
    observed = int(time.time() * 1000)
    state = 'observing' if trades else 'waiting_for_first_bar' if end <= protocol['start_ms'] else 'waiting_for_seed'
    result = dict(state=state, observed_ms=observed,
        data_end_ms=end, seed_ms=protocol['seed_ms'], protocol_sha256=sha(out / 'protocol.json'),
        **observation_timing(previous, observed, end, protocol['seed_ms']),
        completed_5m_since_start=max(0, (end - protocol['start_ms']) // STEP), arms=results)
    raw = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    write(out / 'snapshots' / (str(end) + '.json.gz'), gzip.compress(raw, mtime=0))
    save(out / 'latest.json', result)
    report(out, protocol, result)
    return result


def owned_pid(out):
    path = out / 'process.json'
    if not path.exists():
        return None
    pid = read(path).get('pid')
    if not isinstance(pid, int) or pid < 2:
        return None
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
    scripts = (Path(__file__).resolve(), out / 'code/scripts/forward_expanded_core.py')
    return pid if any(str(script) + ' run --output ' + str(out) in command for script in scripts) else None


def finish(out, protocol, stopped=False, stop_signal=None):
    latest = read(out / 'latest.json') if (out / 'latest.json').exists() else {}
    complete = latest.get('data_end_ms') == protocol['stop_ms']
    state = 'stopped_by_signal' if stopped else 'day_complete' if complete else 'day_finished_incomplete'
    ended = int(time.time() * 1000)
    save(out / 'runtime.json', dict(state=state, updated_ms=ended, pid=os.getpid(),
        stop_ms=protocol['stop_ms'], data_end_ms=latest.get('data_end_ms'),
        last_successful_observed_ms=latest.get('observed_ms'), stop_signal=stop_signal,
        complete_through_deadline=complete))
    if latest:
        latest.update(state=state, stopped_ms=ended, complete_through_deadline=complete)
        # observed_ms remains the successful data observation, never the shutdown time.
        save(out / 'latest.json', latest)
        report(out, protocol, latest)


def run(out, until):
    global STOP
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'stop_requested.json').exists():
        return  # A user stop remains effective across login/service restarts.
    with (out / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (ROOT / 'bundle.json').exists():
            verify_bundle(ROOT)
        STOP = False
        stop_signal = None
        save(out / 'process.json', dict(pid=os.getpid(), started_ms=int(time.time() * 1000)))
        def stop(_signum, _frame):
            global STOP
            nonlocal stop_signal
            STOP = True
            stop_signal = _signum
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        api = None
        try:
            api = PublicData(out)
            protocol = initialize(out, until, api)
        except Exception as error:
            save(out / 'runtime.json', dict(state='startup_error', pid=os.getpid(),
                updated_ms=int(time.time() * 1000), error_type=type(error).__name__, error=str(error)))
            if api is not None:
                api.close()
            if read(out / 'process.json').get('pid') == os.getpid():
                (out / 'process.json').unlink()
            raise
        failures = 0
        last_runtime = read(out / 'runtime.json') if (out / 'runtime.json').exists() else {}
        retry_at = last_runtime.get('retry_at_ms', 0)
        access_denied = last_runtime.get('state') == 'access_denied'
        save(out / 'runtime.json', dict(state='starting', pid=os.getpid(), updated_ms=int(time.time() * 1000)))
        while not STOP:
            now = int(time.time() * 1000)
            if now > protocol['stop_ms'] + 120_000:
                break
            try:
                if access_denied or now < retry_at:
                    save(out / 'runtime.json', dict(state='access_denied' if access_denied else 'rate_limited',
                        pid=os.getpid(), updated_ms=now, retry_at_ms=retry_at,
                        stop_ms=protocol['stop_ms'], consecutive_failures=failures))
                    for _ in range(60):
                        if STOP:
                            break
                        time.sleep(1)
                    continue
                result = cycle(out, protocol, api)
                failures = 0
                state = result.get('state', 'waiting')
                save(out / 'runtime.json', dict(state=state, pid=os.getpid(), updated_ms=int(time.time() * 1000),
                    data_end_ms=result.get('data_end_ms'),
                    last_successful_observed_ms=result.get('observed_ms'),
                    stop_ms=protocol['stop_ms'], consecutive_failures=0))
                if result.get('data_end_ms', 0) >= protocol['stop_ms']:
                    break
            except Exception as error:
                failures += 1
                if isinstance(error, RateLimited):
                    retry_at = error.retry_at_ms
                if isinstance(error, AccessDenied):
                    access_denied = True
                state = 'access_denied' if access_denied else 'rate_limited' if retry_at > int(time.time() * 1000) else 'data_error'
                event = dict(state=state, updated_ms=int(time.time() * 1000), retry_at_ms=retry_at,
                             error_type=type(error).__name__, error=str(error), consecutive_failures=failures)
                append(out / 'errors.jsonl', event)
                save(out / 'runtime.json', dict(event, pid=os.getpid(), stop_ms=protocol['stop_ms']))
                print(json.dumps(event, ensure_ascii=False), flush=True)
            for _ in range(60):
                if STOP:
                    break
                time.sleep(1)
        api.close()
        finish(out, protocol, STOP, stop_signal)
        if (out / 'process.json').exists() and read(out / 'process.json').get('pid') == os.getpid():
            (out / 'process.json').unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'start', 'run', 'once', 'status', 'stop'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--until')
    parser.add_argument('--bootstrap', choices=['historical', 'public'],
                        help='New batch input mode; public downloads its own warmup without local market files')
    args = parser.parse_args()
    out = args.output.resolve()
    if args.bootstrap is not None and args.command not in ('prepare', 'start'):
        parser.error('--bootstrap is only supported with prepare/start')
    if args.command in ('prepare', 'start') and ROOT != out / 'code':
        out.mkdir(parents=True, exist_ok=True)
        with (out / 'bundle.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            bundle = build_bundle(ROOT, out, SOURCES, args.bootstrap)
        command = [sys.executable, str(bundle / 'scripts/forward_expanded_core.py'),
                   args.command, '--output', str(out)]
        if args.until:
            command += ['--until', args.until]
        environment = dict(os.environ, **network_settings(ROOT))
        raise SystemExit(subprocess.call(command, cwd=bundle, env=environment))
    if args.command == 'status':
        print(json.dumps(dict(process_running=owned_pid(out) is not None,
            runtime=read(out / 'runtime.json') if (out / 'runtime.json').exists() else {},
            bootstrap=read(out / 'bootstrap/status.json') if (out / 'bootstrap/status.json').exists() else {},
            public_access=read(out / 'public_access.json') if (out / 'public_access.json').exists() else {},
            stop_requested=(out / 'stop_requested.json').exists(),
            report=str(out / 'REPORT.md')), ensure_ascii=False, indent=2))
    elif args.command == 'stop':
        save(out / 'stop_requested.json', dict(requested_ms=int(time.time() * 1000)))
        pid = owned_pid(out)
        if pid:
            os.kill(pid, signal.SIGTERM)
        print('Stop requested' if pid else 'No owned forward process')
    elif args.command == 'prepare':
        with (out / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            verify_bundle(ROOT)
            api = PublicData(out)
            try:
                protocol = initialize(out, args.until, api)
            finally:
                api.close()
            print(json.dumps(dict(seed_ms=protocol['seed_ms'], stop_ms=protocol['stop_ms'],
                                  code_root=str(ROOT))))
    elif args.command == 'start':
        start_background(out, args.until)
    elif args.command == 'once':
        out.mkdir(parents=True, exist_ok=True)
        with (out / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            protocol = initialize(out, args.until, PublicData(out))
            if int(time.time() * 1000) > protocol['stop_ms'] + 120_000:
                raise ValueError('Session deadline passed; do not retroactively create forward observations')
            result = cycle(out, protocol, PublicData(out))
            print(json.dumps({k: v for k, v in result.items() if k != 'arms'}, ensure_ascii=False))
    else:
        run(out, args.until)


def start_background(out, until):
    out.mkdir(parents=True, exist_ok=True)
    # Serialize launchers until the child owns runner.lock/process.json.
    with (out / 'start.lock').open('a') as launch_lock:
        fcntl.flock(launch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if owned_pid(out):
            print('Forward observation already running')
            return
        with (out / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            verify_bundle(ROOT)
            (out / 'stop_requested.json').unlink(missing_ok=True)
            api = PublicData(out)
            try:
                protocol = initialize(out, until, api)
            finally:
                api.close()
        check_cancelled(out)
        if int(time.time() * 1000) >= protocol['stop_ms']:
            raise ValueError('Session deadline passed; new authorization/batch required')
        with (out / 'worker.log').open('a') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run', '--output', str(out)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('Worker exited during startup; inspect worker.log and runtime.json')
            if owned_pid(out) == process.pid:
                runtime = read(out / 'runtime.json') if (out / 'runtime.json').exists() else {}
                started = read(out / 'process.json')['started_ms']
                if runtime.get('updated_ms', 0) < started:
                    time.sleep(.1)
                    continue
                if runtime.get('pid') == process.pid and runtime.get('state') == 'startup_error':
                    raise RuntimeError('Worker initialization failed; inspect worker.log and runtime.json')
                if runtime.get('pid') == process.pid and runtime.get('state') in (
                        'starting', 'waiting_for_first_bar', 'waiting_for_seed', 'observing'):
                    print(json.dumps(dict(state='initialized', pid=process.pid,
                        runtime_state=runtime['state'], report=str(out / 'REPORT.md')), ensure_ascii=False))
                    return
            time.sleep(.1)
        raise RuntimeError('Worker initialization not confirmed in 10 seconds; inspect status before restarting')


if __name__ == '__main__':
    main()
