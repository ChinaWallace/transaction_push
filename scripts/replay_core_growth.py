#!/usr/bin/env python3
"""v8 paired counterfactual: no trim, weight trims, cash-backed profit adds.

Run with .venv.freqtrade-quant/bin/python. No exchange or account calls.
Uses the SAME v7 HoldEqual initial fills in every arm. Not a new coin selector.
"""
import fcntl
import json
import math
from pathlib import Path
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.quant.futures_book import FuturesBook
from app.quant.core_growth import growth_notional
from stop_provenance import sha, verify_hashes, verify_seal

OUT = ROOT / 'reports/quant_v8'
STEP = 300_000
CAPITAL = 10000.0
ARMS = {'DriftHold': '不减仓、不加仓（同入场基准）',
        'CapTotal70': '持续压回70%总权重',
        'CapTotal70Single25': '持续压回70%总 / 25%单币',
        'ProfitAdd50': '浮盈额度50%顺势加仓',
        'ProfitAdd100': '浮盈额度100%顺势加仓'}
STEPS = {'BTCUSDT': .001, 'ETHUSDT': .001, 'ZECUSDT': .01}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def breakout_times(rows):
    frame = pd.DataFrame({'timestamp': [int(r[0]) for r in rows],
                          'high': [float(r[2]) for r in rows], 'close': [float(r[4]) for r in rows]})
    high = frame.high.shift(1).rolling(20).max()
    ema = frame.close.ewm(span=50, adjust=False, min_periods=50).mean()
    # Raw kline timestamp denotes OPEN; the signal becomes usable only 4h later.
    return set((frame.loc[(frame.close > high) & (frame.close > ema), 'timestamp'] + 14_400_000).tolist())


def load_data(challenge):
    base = ROOT / ('reports/quant_v6/challenge_data' if challenge else 'reports/quant_v5/data')
    result = {}
    for symbol in STEPS:
        series = {}
        for kind, interval in [('klines', '5m'), ('klines', '4h'), ('markPriceKlines', '5m')]:
            rows = json.loads((base / f'series/{kind}/{interval}/{symbol}.json').read_text())['rows']
            series[kind + interval] = rows
        rates_path = (base / f'funding/{symbol}.json' if challenge else
                      ROOT / f'reports/quant_v3/futures_replay/funding/symbols/{symbol}.json')
        rates = json.loads(rates_path.read_text())['rates']
        result[symbol] = {
            'price': {int(r[0]): float(r[1]) for r in series['klines5m']},
            'marks': {int(r[0]): (float(r[1]), float(r[4])) for r in series['markPriceKlines5m']},
            'signals': breakout_times(series['klines4h']),
            'funding': {int(r['fundingTime']) // 3_600_000 * 3_600_000:
                        (float(r['fundingRate']), float(r['markPrice'])) for r in rates}}
    return result


def buy(book, symbol, amount, price, at, reason):
    fee = amount * price * book.fee
    book.wallet -= fee
    p = book.positions.get(symbol)
    if p:
        p['entry'] = (p['quantity'] * p['entry'] + amount * price) / (p['quantity'] + amount)
        p['quantity'] += amount
        p['margin'] += amount * price
        p['pnl'] -= fee
    else:
        book.positions[symbol] = dict(quantity=amount, entry=price, margin=amount * price,
            leverage=1, stop=0, opened_at=at, pnl=-fee, funding=0, holding_policy='core',
            drawdown_exempt=True, strategy='core-growth-v8')
    book.events.append(dict(time=pd.Timestamp(at, unit='ms', tz='UTC').isoformat(),
        symbol=symbol, side='buy', quantity=amount, price=price, fee=fee, reason=reason))


def run_arm(arm, window, trades, data, fee, timerange):
    start, end = [int(pd.Timestamp(s, tz='UTC').timestamp() * 1000) for s in timerange]
    book = FuturesBook(CAPITAL, fee_bps=fee * 10000, slippage_bps=0)
    seeds = {t['pair'].split('/')[0] + 'USDT': t for t in trades}
    if len(seeds) != 3 or any(len(t['orders']) != 2 for t in trades):
        raise ValueError('Expected three simple holding seeds')
    added = dict.fromkeys(seeds, 0.0)
    last_buy = {s: t['open_rate'] for s, t in seeds.items()}
    peak = CAPITAL
    curve = []
    min_free = CAPITAL
    previous_funding = dict.fromkeys(seeds, 0.0)
    for at in range(start, end + STEP, STEP):
        mark_at = min(at, end - STEP)
        quotes = {}
        for s in seeds:
            # Never fill at the current candle close; open marks are already known.
            mark = data[s]['marks'][mark_at][0]
            price = data[s]['price'][mark_at]
            book.marks[s] = mark
            quotes[s] = dict(bid=price, ask=price, mark=mark)
        for s, t in seeds.items():
            if at == t['open_timestamp']:
                buy(book, s, t['amount'], t['open_rate'], at, 'same_hold_seed')
        for s in seeds:
            if at in data[s]['funding']:
                rate, mark = data[s]['funding'][at]
                book.funding(s, at, rate, mark)
        for s, t in seeds.items():
            if at == t['close_timestamp'] and s in book.positions:
                book.close(s, book.positions[s]['quantity'], t['close_rate'], at, 'sample_end')
        if arm.startswith('Cap'):
            book._enforce_policy_caps({'policy': {'core_total_weight': .7,
                'core_single_weight': .25 if arm == 'CapTotal70Single25' else 1.0,
                'satellite_single_weight': .1, 'core_allow_weight_drift': False}}, quotes, at)
        elif arm.startswith('ProfitAdd'):
            for s, p in list(book.positions.items()):
                t = seeds[s]
                # Remaining seed allocations are reserved until all initial fills occur.
                reserved_seed = sum(v['stake_amount'] * (1 + fee) for v in seeds.values() if at < v['open_timestamp'])
                price = data[s]['price'][mark_at]
                notional = growth_notional(initial_quantity=t['amount'], initial_price=t['open_rate'],
                    current_price=price, added_cost=added[s], last_add_price=last_buy[s],
                    profit_fraction=.5 if arm == 'ProfitAdd50' else 1.0,
                    free_collateral=book.wallet - book.margin() - reserved_seed, equity=book.equity(),
                    reserve_cash=CAPITAL * .1, breakout=at in data[s]['signals'])
                # Fees also consume collateral; round DOWN to a disclosed lot assumption.
                amount = math.floor(notional / (price * (1 + fee)) / STEPS[s]) * STEPS[s]
                if amount * price >= 100:
                    buy(book, s, amount, price, at, 'profit_breakout_add')
                    added[s] += amount * price * (1 + fee)
                    last_buy[s] = price
                    if book.wallet - book.margin() < CAPITAL * .1 - 1e-6:
                        raise ValueError('Addition spent protected cash')
        min_free = min(min_free, book.wallet - book.margin())
        for s in seeds:
            book.marks[s] = data[s]['marks'][mark_at][1]
        eq = book.equity()
        if eq <= 0 or book.wallet - book.margin() < 0:
            raise ValueError('Insolvent replay requires a liquidation model; reject run')
        peak = max(peak, eq)
        curve.append(dict(timestamp=at, equity=eq, drawdown=(peak-eq)/peak, exposure=book.gross()))
    if book.positions:
        raise ValueError('Non-flat terminal portfolio')
    orders, pnl = [], dict.fromkeys(seeds, 0.0)
    fee_total = funding_total = 0.0
    for event in book.events:
        s = event['symbol']
        if event['side'] == 'funding':
            pnl[s] -= event['payment']; funding_total -= event['payment']
            continue
        qty, price, cost = event['quantity'], event['price'], event['fee']
        pnl[s] += (-1 if event['side'] == 'buy' else 1) * qty * price - cost
        fee_total += cost
        orders.append(dict(timestamp=int(pd.Timestamp(event['time']).timestamp()*1000),
            pair=s.removesuffix('USDT')+'/USDT:USDT', side=event['side'], amount=qty,
            price=price, fee=cost, reason=event['reason']))
    error = book.equity() - CAPITAL - sum(pnl.values())
    baseline_error = book.equity() - CAPITAL - sum(t['profit_abs'] for t in trades) if arm == 'DriftHold' and fee == .001 else None
    if abs(error) > .01 or baseline_error is not None and abs(baseline_error) > .01:
        raise ValueError(f'Cash flow or Freqtrade baseline reconciliation failed: {error}, {baseline_error}')
    metrics = dict(return_pct=(book.equity()/CAPITAL-1)*100, final_equity=book.equity(),
        sampled_mark_drawdown_pct=max(r['drawdown'] for r in curve)*100,
        average_marked_exposure_pct=sum(r['exposure']/r['equity'] for r in curve)/len(curve)*100,
        max_marked_exposure_pct=max(r['exposure']/r['equity'] for r in curve)*100,
        fee_cost_usdt=fee_total, funding_net_income_usdt=funding_total,
        pnl_by_pair={s.removesuffix('USDT')+'/USDT:USDT':v for s,v in pnl.items()},
        added_notional_including_fees_usdt=sum(added.values()), min_free_collateral_usdt=min_free,
        add_fills=sum(o['reason']=='profit_breakout_add' for o in orders),
        cap_reductions=sum(o['reason']=='policy_weight_cap' for o in orders),
        reconciled=True, cashflow_error_usdt=error, freqtrade_baseline_difference_usdt=baseline_error,
        definition='5m mark-close MTM; known open execution; real single-event funding; no invented profit cash')
    name = window + ('_double_cost' if fee > .001 else '')
    run = OUT / 'runs' / name / arm
    write(run/'orders.json', orders); write(run/'events.json', book.events)
    write(run/'mark_metrics.json', metrics)
    write(run/'equity_preview.json', curve[::max(1,len(curve)//700)] + [curve[-1]])
    pd.DataFrame(curve).to_feather(run/'equity_5m.feather')
    row = dict(strategy=arm, name=ARMS[arm], window=name, study='v8', origin='core_growth_counterfactual',
        fee=fee, total_trades=3, mark_metrics=metrics,
        artifacts={str(p.relative_to(ROOT)):sha(p) for p in run.iterdir() if p.is_file()})
    write(run/'summary.json', row)
    print(name, arm, round(metrics['return_pct'],2), 'DD', round(metrics['sampled_mark_drawdown_pct'],2),
          'adds', metrics['add_fills'], 'trims', metrics['cap_reductions'], flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_seal(required=True)
        v7 = json.loads((ROOT/'reports/quant_v7/protocol.json').read_text())
        verify_hashes(v7['data']); verify_hashes(v7['sources'])
        sources = {str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),
            ROOT/'app/quant/core_growth.py', ROOT/'app/quant/futures_book.py']}
        seed_files = {}
        for window in v7['windows']:
            run = ROOT/'reports/quant_v7/runs'/window/'HoldEqual'
            for name in ('summary.json','trades.json'):
                seed_files[str((run/name).relative_to(ROOT))] = sha(run/name)
        protocol = dict(sources=sources, data=v7['data'], seeds=seed_files, arms=ARMS,
            windows=v7['windows'], capital=CAPITAL, fees=[.001,.002], leverage=1,
            rules='Same v7 initial fills around 04:00 UTC. Hold until window end. Adds: completed 4h close exceeds previous 20 highs and EMA50, then next 5m open at least 20% above last buy. Spend <=50%/100% original-seed current gain minus past adds, <=5% account equity per fill, and available CASH collateral less 1000 USDT reserve. Never spend unrealized PnL as cash. No DCA into a losing seed. No per-coin weight trim in drift/add arms. Minimum add 100 USDT; fixed disclosed quantity steps.',
            quantity_steps=STEPS, execution='5m opens; caps checked every 5m, runtime checks can differ. Fee proxy .1%/.2% per side includes execution allowance. Initial fills at funding ties included, additions at ties occur after funding. No strategy substitution or exchange orders.',
            limitations=['Post-hoc three chosen coins, not new OOS or coin-selection evidence',
                'Pyramiding spends reserved cash and increases invested capital, so it is not equal exposure to 70% buy-and-hold',
                'No ordinary exit; very large bear-market drawdowns remain possible',
                'All cost sensitivities keep the identical initial quantities; not separate rescaled Freqtrade runs'])
        frozen = OUT/'protocol.json'
        if frozen.exists():
            old = json.loads(frozen.read_text())
            if {k:v for k,v in old.items() if k!='frozen_ms'} != protocol:
                raise ValueError('v8 protocol changed after freeze')
        else:write(frozen, dict(frozen_ms=int(time.time()*1000), **protocol))
        datasets, rows = {}, []
        for window, dates in v7['windows'].items():
            challenge = window == 'challenge2025'
            if challenge not in datasets:datasets[challenge] = load_data(challenge)
            trades = json.loads((ROOT/'reports/quant_v7/runs'/window/'HoldEqual/trades.json').read_text())
            timerange = [pd.Timestamp(s).strftime('%Y-%m-%d') for s in dates.split('-')]
            for fee in (.001,.002):
                for arm in ARMS:rows.append(run_arm(arm,window,trades,datasets[challenge],fee,timerange))
        baselines = {r['window']:r['mark_metrics'] for r in rows if r['strategy']=='DriftHold'}
        for row in rows:
            b = baselines[row['window']]; m = row['mark_metrics']
            row['versus_equal_hold'] = dict(return_gap_pp=m['return_pct']-b['return_pct'],
                drawdown_gap_pp=m['sampled_mark_drawdown_pct']-b['sampled_mark_drawdown_pct'],
                allocation_differs=row['strategy']!='DriftHold',
                within_50pct_historical_drawdown=m['sampled_mark_drawdown_pct']<=50)
        write(OUT/'comparison.json', dict(rows=rows, protocol={k:v for k,v in protocol.items() if k!='data'}, live_enabled=False))
        lines = ['# 浮盈加仓与机械减仓对照 v8', '', protocol['rules'], '',
                 '加仓资金来自剩余现金，不把浮盈记作现金。加仓组投入增加，不声称同敞口。5m收盘盯市；资金费逐事件结算；无实盘调用。', '']
        for window in baselines:
            lines += [f'## {window}', '', '|方案|净收益|回撤|相对持有|加仓次数|机械减仓次数|', '|---|---:|---:|---:|---:|---:|']
            for row in [r for r in rows if r['window']==window]:
                m=row['mark_metrics'];gap=row['versus_equal_hold']['return_gap_pp']
                lines.append(f"|{row['name']}|{m['return_pct']:.2f}%|{m['sampled_mark_drawdown_pct']:.2f}%|{gap:+.2f}pp|{m['add_fills']}|{m['cap_reductions']}|")
            lines += ['']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':main()
