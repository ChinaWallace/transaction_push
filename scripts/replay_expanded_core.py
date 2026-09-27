#!/usr/bin/env python3
"""v12 fixed-universe core/overlay comparison using public, verified 5m data."""
import argparse
import concurrent.futures
import multiprocessing
import fcntl
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.quant.expanded_core import run_portfolio
from replay_core_overlay import features
from stop_provenance import sha, verify_hashes

OUT = ROOT / 'reports/quant_v12'
STEP = 300_000
CAPITAL = 10000.0
WINDOWS = {
    'challenge2025': ['2025-01-01', '2026-01-01'],
    'full': ['2026-01-01', '2026-09-24'],
    'reused_holdout': ['2026-07-01', '2026-09-24'],
}
ARMS = {
    'TriHold': {'name': '三币底仓持有（新版控制）', 'allocation': 'three', 'weight': 0, 'exit_ema': 200},
    'TriEnhance': {'name': '三币底仓＋慢退出增强', 'allocation': 'three', 'weight': .4, 'exit_ema': 200},
    'BroadHold': {'name': '16币等权底仓持有', 'allocation': 'equal', 'weight': 0, 'exit_ema': 200},
    'BroadEnhance': {'name': '16币等权底仓＋增强', 'allocation': 'equal', 'weight': .4, 'exit_ema': 200},
    'AnchorHold': {'name': '三币50%＋扩展币20%持有', 'allocation': 'anchor', 'weight': 0, 'exit_ema': 200},
    'AnchorEnhance': {'name': '三币50%＋扩展币20%增强', 'allocation': 'anchor', 'weight': .4, 'exit_ema': 200},
}
REQUIRED = ['timestamp', 'open', 'high', 'low', 'close', 'quote_volume',
            'mark_open', 'mark_high', 'mark_low', 'mark_close']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def timestamp(value):
    return int(pd.Timestamp(value, tz='UTC').timestamp() * 1000)


class EpochValues:
    """Checked timestamp access to dense data, without millions of dict entries."""
    def __init__(self, start, values):
        self.start = int(start)
        self.values = np.asarray(values)

    def __getitem__(self, at):
        offset = int(at) - self.start
        if offset < 0 or offset % STEP or offset // STEP >= len(self.values):
            raise KeyError(f'Missing aligned 5m observation: {at}')
        value = self.values[offset // STEP]
        return float(value) if np.ndim(value) == 0 else tuple(float(x) for x in value)


def validate_frame(frame, start, end, symbol):
    if set(REQUIRED) - set(frame):
        raise ValueError(f'{symbol}: missing columns')
    expected = np.arange(start, end, STEP, dtype=np.int64)
    if not np.array_equal(frame.timestamp.to_numpy(), expected):
        raise ValueError(f'{symbol}: non-consecutive 5m history')
    price_columns = [c for c in REQUIRED if c not in ('timestamp', 'quote_volume')]
    numbers = frame[price_columns].to_numpy()
    if not np.isfinite(numbers).all() or (numbers <= 0).any():
        raise ValueError(f'{symbol}: invalid price')
    if not np.isfinite(frame.quote_volume).all() or (frame.quote_volume < 0).any():
        raise ValueError(f'{symbol}: invalid quote volume')
    for prefix in ('', 'mark_'):
        o, h, l, c = [frame[prefix + key] for key in ('open', 'high', 'low', 'close')]
        if ((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l)).any():
            raise ValueError(f'{symbol}: inconsistent OHLC')


def features_from_frame(frame):
    indexed = frame.set_index(pd.to_datetime(frame.timestamp, unit='ms', utc=True))
    bars = indexed.resample('4h', closed='left', label='left').agg(
        timestamp=('timestamp', 'first'), open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last'), count=('timestamp', 'count'))
    if (bars['count'] != 48).any():
        raise ValueError('Partial 4h candle')
    rows = [[int(r.timestamp), float(r.open), float(r.high), float(r.low), float(r.close)]
            for r in bars.itertuples()]
    return features(rows)


def eligibility(frame, seed_at):
    """Only complete UTC days before the window, never future volume/returns."""
    day = 86_400_000
    cutoff = seed_at // day * day
    prior = frame[(frame.timestamp >= cutoff - 30 * day) & (frame.timestamp < cutoff)]
    if len(prior) != 30 * 288:
        raise ValueError('Insufficient past-only liquidity lookback')
    grouped = prior.groupby(prior.timestamp // day)
    volume = grouped.quote_volume.sum()
    closes = grouped.close.last()
    return {'median_daily_quote_volume': float(volume.median()),
            'eligible': bool(volume.median() >= 10_000_000),
            'daily_return_volatility': float(closes.pct_change().dropna().std()),
            'lookback_start': cutoff - 30 * day, 'lookback_end_exclusive': cutoff}


def make_seeds(allocation, symbols, anchors, filters, frames, dates):
    start, end = map(timestamp, dates)
    opened, closed = start + 14_400_000, end - STEP
    if allocation not in ('three', 'equal', 'anchor'):
        raise ValueError('Unknown allocation')
    extras = [s for s in symbols if s not in anchors]
    weights = ({s: .7 / len(anchors) for s in anchors} if allocation == 'three' else
               {s: .7 / len(symbols) for s in symbols} if allocation == 'equal' else
               {**{s: .5 / len(anchors) for s in anchors}, **{s: .2 / len(extras) for s in extras}})
    trades, checks = [], {}
    for s, weight in weights.items():
        frame = frames[s]
        check = eligibility(frame, opened)
        checks[s] = {**check, 'target_weight': weight}
        # User nominated anchors remain the matched control. Excluded new slots stay cash.
        if s not in anchors and not check['eligible']:
            checks[s]['decision'] = 'past_volume_below_10m_keep_slot_cash'
            continue
        first = frame.iloc[(opened - int(frame.timestamp.iloc[0])) // STEP]
        last = frame.iloc[(closed - int(frame.timestamp.iloc[0])) // STEP]
        if first.timestamp != opened or last.timestamp != closed:
            raise ValueError('Seed quote unavailable')
        price = float(first.open)
        step = float(filters[s]['lot_size']['stepSize'])
        amount = math.floor((CAPITAL * weight / price) / step + 1e-10) * step
        minimum = float(filters[s]['min_notional']['notional'])
        if amount < float(filters[s]['lot_size']['minQty']) or amount * price < minimum:
            checks[s]['decision'] = 'below_current_research_filters_keep_slot_cash'
            continue
        trades.append(dict(pair=s.removesuffix('USDT') + '/USDT:USDT', amount=amount,
                           open_timestamp=opened, open_rate=price,
                           close_timestamp=closed, close_rate=float(last.close)))
        checks[s]['decision'] = 'core_seed'
        checks[s]['initial_notional'] = amount * price
    if not trades or sum(t['amount'] * t['open_rate'] for t in trades) > .7 * CAPITAL + 1e-6:
        raise ValueError('Invalid portfolio seed budget')
    return trades, checks


def load_window(symbols, dates):
    start, end = map(timestamp, dates)
    # Identical >=200 completed 4h warmup for all new-version controls and treatments.
    warmup = start - 92 * 86_400_000
    data, frames = {}, {}
    for s in symbols:
        frame = pd.read_feather(OUT / 'data/series' / f'{s}.feather')
        frame = frame[(frame.timestamp >= warmup) & (frame.timestamp < end)].reset_index(drop=True)
        validate_frame(frame, warmup, end, s)
        fund = json.loads((OUT / 'data/funding' / f'{s}.json').read_text())['rates']
        events = {}
        for event in fund:
            original = int(event['fundingTime'])
            at = original // STEP * STEP
            if not start <= at <= end:
                continue
            if original - at > 999:
                raise ValueError(f'{s}: off-boundary funding event')
            value = float(event['fundingRate']), float(event['markPrice'])
            if not all(math.isfinite(x) for x in value) or value[1] <= 0 or at in events:
                raise ValueError(f'{s}: missing/duplicate/invalid real funding')
            events[at] = value
        if not events:
            raise ValueError(f'{s}: no verified funding history')
        data[s] = dict(price=EpochValues(warmup, frame.open.to_numpy()),
                       marks=EpochValues(warmup, frame[['mark_open', 'mark_close', 'mark_low']].to_numpy()),
                       features=features_from_frame(frame), funding=events)
        frames[s] = frame
    return data, frames


def cases():
    for window, dates in WINDOWS.items():
        yield window, dates, .001, 0, 1.0
        if window in ('full', 'challenge2025'):
            yield window + '_double_cost', dates, .002, 0, 1.0
            yield window + '_execution_stress', dates, .003, 1, .5


def protocol(universe):
    coverage = json.loads((OUT / 'data/coverage_manifest.json').read_text())
    freeze_path = OUT / 'data/freeze_manifest.json'
    frozen_data = json.loads(freeze_path.read_text())
    symbols = set(universe['symbols'])
    if (coverage.get('status') != 'complete' or coverage.get('failed_symbols') or
            set(coverage.get('symbols', {})) != symbols or
            coverage.get('complete_symbols') != len(symbols) or
            coverage.get('target_symbols') != len(symbols) or
            set(frozen_data.get('symbols', [])) != symbols or
            frozen_data.get('universe_sha256') != sha(OUT / 'universe_freeze.json') or
            coverage.get('freeze_sha256') != sha(freeze_path)):
        raise ValueError('Download coverage is incomplete or differs from frozen universe')
    for s, entry in coverage['symbols'].items():
        if entry.get('status') != 'complete' or entry.get('internal_gaps') != 0:
            raise ValueError(f'{s}: incomplete data coverage')
        for kind, expected_path in [('series', OUT / 'data/series' / f'{s}.feather'),
                                    ('funding', OUT / 'data/funding' / f'{s}.json')]:
            if (entry.get(kind + '_path') != str(expected_path.relative_to(ROOT)) or
                    entry.get(kind + '_sha256') != sha(expected_path)):
                raise ValueError(f'{s}: prepared data differs from verified download manifest')
    data_paths = sorted((OUT / 'data/series').glob('*.feather')) + sorted((OUT / 'data/funding').glob('*.json'))
    expected = {str(OUT / 'data/series' / f'{s}.feather') for s in universe['symbols']}
    expected |= {str(OUT / 'data/funding' / f'{s}.json') for s in universe['symbols']}
    if {str(p) for p in data_paths} != expected:
        raise ValueError('Incomplete or unexpected frozen universe data')
    sources = ['app/quant/expanded_core.py', 'app/quant/core_overlay.py', 'app/quant/cross_margin.py',
               'scripts/replay_expanded_core.py', 'scripts/replay_core_overlay.py',
               'scripts/replay_cross_margin.py', 'scripts/stop_provenance.py', 'scripts/prepare_expanded_core_data.py']
    inputs = [OUT / 'universe_freeze.json', OUT / 'fundamental_sources.json',
              ROOT / 'reports/quant_v9/binance_leverage_tiers.json', OUT / 'data/coverage_manifest.json', freeze_path]
    return dict(study='v12', capital=CAPITAL, sources={p: sha(ROOT / p) for p in sources},
        data={str(p.relative_to(ROOT)): sha(p) for p in [*data_paths, *inputs]},
        symbols=universe['symbols'], windows=WINDOWS, arms=ARMS,
        cases=[{'window': w, 'fee': f, 'delay_bars': d, 'exit_fraction': x} for w, _, f, d, x in cases()],
        market='USDT perpetual, long only, shared cross wallet, 2x setting',
        budget='70% initial NOTIONAL (not 70% margin); new allocations do not change saved account policy',
        warmup='92 days before each window, same for all arms; v12 three-coin control is rerun, not identical v11 warmup/filters',
        selection='Current 16-coin research list, hindsight/survivorship bias. Extra coins need prior 30 full UTC days median daily quote volume >=10m; failed slots remain cash. Anchors remain matched user control. No future returns used for historical eligibility.',
        accounting='Frozen aggregate cross account and sleeve attribution; funding events within first 999ms normalize to same 5m boundary, retain source original time. True event markPrice required. Final candle holding risk is evaluated before terminal close settlement; close observations and terminal fills use candle end timestamps. No funding at exclusive window end.',
        rules='v11 40% slow overlay unchanged: profitable core + completed 4h breakout/EMA trend, +10% add spacing, 10% equity max order, profit budget, postfill gross<=1.4 equity; two 4h closes below EMA200 exit overlay; >1.5 total exposure exit overlay first. Preserve core.',
        filters='Current public step/minNotional are research approximations, not historical filters. Minimum overlay order 100 USDT. No extra single-coin weight trim.',
        promotion='No auto execution change. All candidates must be profitable and beat matched allocation hold at full2025 and full2026 in all 3 costs, and stay <=50% close/joint-low DD in every tested case, without margin/residual failures. Rank eligible allocations by worst full-window absolute account return after costs, then lower worst joint/close drawdown. Matched-hold excess establishes overlay efficacy, not portfolio preference. Disclose versus TriEnhance in every case.',
        limitations=['All selected coins survive to current date; current fundamentals are not historical point-in-time facts.',
                    'No ordinary-position mixture, short hedges, staking rewards, liquidation penalties or actual orderbook queues.',
                    'Static maintenance tiers and current lot filters; mark OHLC joint lows are a conservative bound, not real synchronized ticks.',
                    'More coins may remain highly correlated and dilute winners. No future return/50% maximum loss guarantee.'])


def finish(rows):
    by_key = {(r['window'], r['strategy']): r for r in rows}
    for row in rows:
        name = row['strategy']
        base_name = name.replace('Enhance', 'Hold')
        base = by_key[(row['window'], base_name)]['mark_metrics']
        tri = by_key[(row['window'], 'TriEnhance')]['mark_metrics']
        metric = row['mark_metrics']
        row['versus_equal_hold'] = dict(return_gap_pp=metric['return_pct'] - base['return_pct'],
            allocation_differs=name.endswith('Enhance'), reference_strategy=base_name)
        row['versus_three_coin_enhance_pp'] = metric['return_pct'] - tri['return_pct']
    details = {}
    for name in ('TriEnhance', 'BroadEnhance', 'AnchorEnhance'):
        selected = [r for r in rows if r['strategy'] == name]
        failures = []
        for row in selected:
            m = row['mark_metrics']
            if max(m['sampled_mark_drawdown_pct'], m['joint_low_stress_drawdown_pct']) > 50:
                failures.append(row['window'] + ': drawdown>50')
            if not m['risk_model_passed'] or m['unresolved_core_risk']:
                failures.append(row['window'] + ': risk model failure')
            if row['window'].startswith(('full', 'challenge2025')) and row['versus_equal_hold']['return_gap_pp'] <= 0:
                failures.append(row['window'] + ': did not beat matched holding')
            if row['window'].startswith(('full', 'challenge2025')) and m['return_pct'] <= 0:
                failures.append(row['window'] + ': non-positive return')
        details[name] = dict(passed=not failures, failed=failures,
            worst_drawdown_pct=max(r['mark_metrics']['sampled_mark_drawdown_pct'] for r in selected),
            worst_stress_drawdown_pct=max(max(r['mark_metrics']['sampled_mark_drawdown_pct'],r['mark_metrics']['joint_low_stress_drawdown_pct']) for r in selected),
            worst_full_return_pct=min(r['mark_metrics']['return_pct'] for r in selected if r['window'].startswith(('full', 'challenge2025'))),
            worst_full_excess_pp=min(r['versus_equal_hold']['return_gap_pp'] for r in selected if r['window'].startswith(('full', 'challenge2025'))),
            full_window_beats_three_coin_enhance=all(r['versus_three_coin_enhance_pp'] >= 0 for r in selected if r['window'].startswith(('full', 'challenge2025'))))
    candidates = sorted((s for s, d in details.items() if d['passed']),
        key=lambda s: (-details[s]['worst_full_return_pct'], details[s]['worst_stress_drawdown_pct'], s))
    selection = dict(kind='retrospective_expansion_comparison_not_new_oos', candidates=candidates,
        selected=candidates[0] if candidates else None, details=details, execution_changed=False,
        ranking='Highest worst full-window absolute account return among risk-qualified candidates; lower worst stress drawdown breaks ties.',
        note='Passing matched holding does not prove adding coins beats the three-coin control.')
    write(OUT / 'selection.json', selection)
    write(OUT / 'comparison.json', dict(study='v12', rows=rows, selection=selection))
    lines = ['# 多币底仓与趋势增强 v12', '', '42组固定规则比较；同一账户、同窗口、费用及真实资金费。当前名单有事后选择/幸存偏差，未改变旧模拟。', '',
             '| 区间 | 配置 | 收益 | 5m回撤 | 共同低点回撤 | 相对同配置持有 | 相对三币增强 |',
             '|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        m = r['mark_metrics']
        lines.append(f"| {r['window']} | {r['name']} | {m['return_pct']:.2f}% | {m['sampled_mark_drawdown_pct']:.2f}% | {m['joint_low_stress_drawdown_pct']:.2f}% | {r['versus_equal_hold']['return_gap_pp']:.2f}pp | {r['versus_three_coin_enhance_pp']:.2f}pp |")
    lines += ['', '## 研究筛选', '', '```json', json.dumps(selection, ensure_ascii=False, indent=2), '```']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


def read_cached_run(target, arm, window, fee, delay, fraction):
    row = json.loads((target / 'summary.json').read_text())
    expected = dict(study='v12', strategy=arm, name=ARMS[arm]['name'], window=window,
                    fee=fee, margin_mode='cross',
                    execution=dict(delay_bars=delay, overlay_exit_fraction=fraction))
    if any(row.get(k) != value for k, value in expected.items()):
        raise ValueError('Cached run identity changed')
    filenames = ['orders.json', 'events.json', 'mark_metrics.json', 'risk_snapshots.json',
                 'risk_breaches.json', 'monthly_returns.json', 'equity_preview.json',
                 'seed_eligibility.json', 'equity_5m.feather']
    paths = {str((target / name).relative_to(ROOT)) for name in filenames}
    if set(row.get('artifacts', {})) != paths:
        raise ValueError('Cached run artifact set changed')
    verify_hashes(row['artifacts'])
    metrics = json.loads((target / 'mark_metrics.json').read_text())
    orders = json.loads((target / 'orders.json').read_text())
    if row['mark_metrics'] != metrics or row['total_trades'] != sum(o['side'] == 'buy' for o in orders):
        raise ValueError('Cached summary differs from verified results')
    return row


def execute_window(selected_dates, universe):
    filters = {r['symbol']: r for r in universe['rows']}
    steps = {s: float(filters[s]['lot_size']['stepSize']) for s in universe['symbols']}
    raw = json.loads((ROOT / 'reports/quant_v9/binance_leverage_tiers.json').read_text())
    tiers = {s: raw[s.removesuffix('USDT') + '/USDT:USDT'] for s in universe['symbols']}
    rows = []
    data, frames = load_window(universe['symbols'], selected_dates)
    for window, dates, fee, delay, fraction in cases():
        if dates != selected_dates:
            continue
        for arm, rule in ARMS.items():
            target = OUT / 'runs' / window / arm
            if (target / 'summary.json').exists():
                row = read_cached_run(target, arm, window, fee, delay, fraction)
            else:
                seeds, checks = make_seeds(rule['allocation'], universe['symbols'], universe['anchor_symbols'], filters, frames, dates)
                result = run_portfolio(rule, seeds, data, tiers, steps, fee, dates, delay_bars=delay, exit_fraction=fraction)
                artifacts = dict(orders=result['orders'], events=result['events'], mark_metrics=result['metrics'],
                    risk_snapshots=result['risk_snapshots'], risk_breaches=result['risk_breaches'], monthly_returns=result['monthly_returns'],
                    equity_preview=result['curve'][::max(1, len(result['curve']) // 700)] + [result['curve'][-1]],
                    seed_eligibility=checks)
                for name, value in artifacts.items():
                    write(target / (name + '.json'), value)
                result['frame'].to_feather(target / 'equity_5m.feather')
                row = dict(study='v12', strategy=arm, name=rule['name'], window=window, fee=fee,
                    total_trades=sum(o['side'] == 'buy' for o in result['orders']), margin_mode='cross',
                    mark_metrics=result['metrics'], execution=dict(delay_bars=delay, overlay_exit_fraction=fraction),
                    artifacts={str(p.relative_to(ROOT)): sha(p) for p in target.iterdir() if p.is_file() and p.name != 'summary.json'})
                write(target / 'summary.json', row)
            rows.append(row)
            m = row['mark_metrics']
            print(window, arm, f"return={m['return_pct']:.2f}% DD={m['sampled_mark_drawdown_pct']:.2f}%", flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        universe = json.loads((OUT / 'universe_freeze.json').read_text())
        manifest = protocol(universe)
        path = OUT / 'protocol.json'
        if path.exists():
            saved = json.loads(path.read_text())
            if {k: v for k, v in saved.items() if k != 'frozen_ms'} != manifest:
                raise ValueError('Frozen v12 protocol changed; use a new research batch')
        else:
            write(path, dict(frozen_ms=int(time.time() * 1000), **manifest))
        if args.freeze_only:
            print('Frozen v12 research protocol; no backtest run')
            return
        # Reject damaged caches before any independent window starts computing.
        for window, _dates, fee, delay, fraction in cases():
            for arm in ARMS:
                target = OUT / 'runs' / window / arm
                if (target / 'summary.json').exists():
                    read_cached_run(target, arm, window, fee, delay, fraction)
        rows = []
        write(OUT / 'status.json', dict(state='running', completed=0, expected=42, updated_ms=int(time.time()*1000)))
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn')) as pool:
                pending = {pool.submit(execute_window, dates, universe) for dates in WINDOWS.values()}
                while pending:
                    finished, pending = concurrent.futures.wait(pending, timeout=15, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in finished:
                        rows.extend(future.result())
                    write(OUT / 'status.json', dict(state='running',
                        completed=len(list((OUT / 'runs').glob('*/*/summary.json'))), expected=42,
                        updated_ms=int(time.time()*1000)))
            order = {w: i for i, (w, *_rest) in enumerate(cases())}
            rows.sort(key=lambda r: (order[r['window']], list(ARMS).index(r['strategy'])))
            finish(rows)
            write(OUT / 'status.json', dict(state='completed', completed=len(rows), expected=42, updated_ms=int(time.time() * 1000)))
        except Exception as error:
            write(OUT / 'status.json', dict(state='failed', error_type=type(error).__name__, error=str(error),
                completed=len(list((OUT / 'runs').glob('*/*/summary.json'))), expected=42,
                updated_ms=int(time.time()*1000)))
            raise


if __name__ == '__main__':
    main()
