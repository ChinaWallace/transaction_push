#!/usr/bin/env python3
"""v10: synchronized USDT cross-margin core portfolio, offline research only."""
import fcntl
import json
import math
from pathlib import Path
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.quant.cross_margin import CrossMarginAccount
from stop_provenance import sha, verify_hashes

OUT = ROOT / 'reports/quant_v10'
STEP, CAPITAL = 300_000, 10000.0
STEPS = {'BTCUSDT': .001, 'ETHUSDT': .001, 'ZECUSDT': .01}
ARMS = {
    'CrossNotional70': '全仓2x · 70%初始名义仓位持有',
    'CrossMargin70': '全仓2x · 70%初始保证金持有',
    'CrossFlex': '全仓2x · 风险上升减仓',
    'CrossFlexAdd': '全仓2x · 浮盈加仓＋风险减仓',
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    tmp.replace(path)


def breakout_times(rows):
    frame = pd.DataFrame({'time': [int(r[0]) for r in rows],
                          'high': [float(r[2]) for r in rows], 'close': [float(r[4]) for r in rows]})
    high = frame.high.shift(1).rolling(20).max()
    ema = frame.close.ewm(span=50, adjust=False, min_periods=50).mean()
    return set((frame.loc[(frame.close > high) & (frame.close > ema), 'time'] + 14_400_000).tolist())


def load_data(challenge):
    base = ROOT / ('reports/quant_v6/challenge_data' if challenge else 'reports/quant_v5/data')
    result = {}
    for s in STEPS:
        def bars(kind, interval):
            return json.loads((base/f'series/{kind}/{interval}/{s}.json').read_text())['rows']
        funding_path = (base/f'funding/{s}.json' if challenge else
                        ROOT/f'reports/quant_v3/futures_replay/funding/symbols/{s}.json')
        result[s] = dict(price={int(r[0]): float(r[1]) for r in bars('klines', '5m')},
            marks={int(r[0]): (float(r[1]), float(r[4]), float(r[3])) for r in bars('markPriceKlines', '5m')},
            signals=breakout_times(bars('klines', '4h')),
            funding={int(r['fundingTime'])//3_600_000*3_600_000: (float(r['fundingRate']), float(r['markPrice']))
                     for r in json.loads(funding_path.read_text())['rates']})
    return result


def add_quantity(book, symbol, price, last_price, added_margin, breakout):
    """Size from current profit and cross collateral; never credit profit to wallet."""
    p = book.positions[symbol]
    st = book.state()
    if not breakout or price < last_price*1.2 or price <= p['entry'] or st['equity'] <= 0:
        return 0.0
    gain = max(0.0, p['quantity']*(book.marks[symbol]-p['entry']))
    margin_budget = min(max(0.0, .5*gain-added_margin), .05*st['equity'])
    # Enforce <=1.4x account exposure AFTER the fill and its execution costs.
    mark = book.marks[symbol]
    per_unit_drag = price*(1+book.fee)-mark
    denominator = mark+1.4*per_unit_drag
    exposure_qty = max(0.0, (1.4*st['equity']-st['gross'])/denominator) if denominator > 0 else 0
    amount = min(margin_budget*2/price, exposure_qty)
    amount = math.floor(amount/STEPS[symbol])*STEPS[symbol]
    return amount if amount*price >= 100 else 0.0


def run_arm(arm, window, trades, data, tiers, fee, dates):
    start, end = [int(pd.Timestamp(s, tz='UTC').timestamp()*1000) for s in dates]
    seeds = {t['pair'].split('/')[0]+'USDT': t for t in trades}
    if len(seeds) != 3 or len({t['open_timestamp'] for t in trades}) != 1 or any(len(t['orders']) != 2 for t in trades):
        raise ValueError('Expected simultaneous three-coin seeds')
    book = CrossMarginAccount(CAPITAL, tiers, fee)
    multiplier = 1 if arm == 'CrossNotional70' else 2
    last_buy = {s: t['open_rate'] for s, t in seeds.items()}
    added_margin = dict.fromkeys(seeds, 0.0)
    curve, snapshots, breaches = [], [], []
    peak, min_floor, min_buffer, min_low_buffer = CAPITAL, CAPITAL, CAPITAL, CAPITAL
    worst_low_dd = 0.0
    reductions = 0
    def snapshot(at, why):
        return dict(timestamp=at, reason=why, **book.state(),
                    conditional_liquidation_prices={s: book.conditional_liquidation_price(s) for s in book.positions})
    for at in range(start, end+STEP, STEP):
        mark_at = min(at, end-STEP)
        prices = {s: data[s]['price'][mark_at] for s in seeds}
        book.marks = {s: data[s]['marks'][mark_at][0] for s in seeds}
        previous_events = len(book.events)
        for s, t in seeds.items():
            if at == t['open_timestamp']:
                book.buy(s, multiplier*t['amount'], t['open_rate'], at, 'same_hold_seed', leverage=2)
        for s in seeds:
            if at in data[s]['funding']:
                rate, mark = data[s]['funding'][at]
                book.fund(s, at, rate, mark)
        st = book.state()
        if st['at_liquidation']:
            breaches.append(dict(timestamp=at, stage='known_open', **st))
        # An already breached model may not be rescued by a fictional order.
        if not breaches and arm.startswith('CrossFlex') and (st['effective_leverage'] or 0) > 1.6:
            before = snapshot(at, 'before_reduce')
            book.reduce_to(.9, prices, at)
            reductions += 1
            snapshots.extend([before, snapshot(at, 'after_reduce')])
        for s, t in seeds.items():
            if at == t['close_timestamp'] and s in book.positions:
                book.sell(s, book.positions[s]['quantity'], t['close_rate'], at, 'sample_end')
        if not breaches and arm == 'CrossFlexAdd':
            for s in list(book.positions):
                amount = add_quantity(book, s, prices[s], last_buy[s], added_margin[s], at in data[s]['signals'])
                if amount:
                    book.buy(s, amount, prices[s], at, 'cross_profit_breakout_add', leverage=2)
                    added_margin[s] += amount*prices[s]/2
                    last_buy[s] = prices[s]
                    if book.state()['effective_leverage'] > 1.4+1e-9:
                        raise ValueError('Addition exceeded account exposure cap')
        st = book.state()
        min_floor = min(min_floor, st['all_zero_cash_floor'])
        min_buffer = min(min_buffer, st['maintenance_buffer'])
        # Current 5m lows are used ONLY to assess risk, NEVER to trigger an earlier fill.
        low = book.state({s: data[s]['marks'][mark_at][2] for s in seeds})
        min_low_buffer = min(min_low_buffer, low['maintenance_buffer'])
        worst_low_dd = max(worst_low_dd, (peak-low['equity'])/peak)
        if low['at_liquidation']:
            breaches.append(dict(timestamp=at, stage='joint_intrabar_lows_bound', **low))
        if len(book.events) > previous_events or at % 14_400_000 == 0:
            snapshots.append(snapshot(at, 'known_open_after_actions'))
        book.marks = {s: data[s]['marks'][mark_at][1] for s in seeds}
        st = book.state()
        min_floor = min(min_floor, st['all_zero_cash_floor'])
        min_buffer = min(min_buffer, st['maintenance_buffer'])
        if st['at_liquidation']:
            breaches.append(dict(timestamp=at, stage='mark_close', **st))
        peak = max(peak, st['equity'])
        curve.append(dict(timestamp=at, equity=st['equity'], drawdown=(peak-st['equity'])/peak,
                          exposure=st['gross'], effective_leverage=st['effective_leverage']))
    if book.positions:raise ValueError('Expected flat sample end')
    orders, pnl = [], dict.fromkeys(seeds, 0.0)
    fee_total = funding_net = 0.0
    for e in book.events:
        s = e['symbol']
        if e['side'] == 'funding':
            pnl[s] -= e['payment']; funding_net -= e['payment']
        else:
            pnl[s] += (-1 if e['side'] == 'buy' else 1)*e['amount']*e['price']-e['fee']
            fee_total += e['fee']
            orders.append({**e, 'pair': s.removesuffix('USDT')+'/USDT:USDT'})
    error = book.wallet-CAPITAL-sum(pnl.values())
    baseline_error = (book.wallet-CAPITAL-sum(t['profit_abs'] for t in trades)
                      if arm == 'CrossNotional70' and fee == .001 else None)
    if abs(error) > .01 or baseline_error is not None and abs(baseline_error) > .01:
        raise ValueError(f'Cashflow/1x hold parity failed: {error}, {baseline_error}')
    eligible = not breaches
    metrics = dict(return_pct=(book.wallet/CAPITAL-1)*100, final_equity=book.wallet,
        sampled_mark_drawdown_pct=max(r['drawdown'] for r in curve)*100,
        joint_low_stress_drawdown_pct=worst_low_dd*100,
        average_marked_exposure_pct=sum((r['effective_leverage'] or 0) for r in curve)/len(curve)*100,
        max_marked_exposure_pct=max((r['effective_leverage'] or 0) for r in curve)*100,
        fee_cost_usdt=fee_total, funding_net_income_usdt=funding_net,
        pnl_by_pair={s.removesuffix('USDT')+'/USDT:USDT': v for s, v in pnl.items()},
        add_fills=sum(o['reason'] == 'cross_profit_breakout_add' for o in orders),
        risk_reduction_rounds=reductions, risk_reduction_fills=sum(o['reason']=='cross_reduce_to_cash_floor' for o in orders),
        minimum_all_zero_cash_floor_usdt=min_floor, minimum_maintenance_buffer_usdt=min_buffer,
        minimum_joint_low_maintenance_buffer_usdt=min_low_buffer,
        risk_breach_observations=len(breaches), first_risk_breach=breaches[0] if breaches else None,
        risk_model_passed=eligible, return_is_hypothetical_after_breach=not eligible,
        historical_drawdown_within_50pct=max(r['drawdown'] for r in curve)<=.5,
        reconciled=True, cashflow_error_usdt=error, freqtrade_baseline_difference_usdt=baseline_error,
        definition='USDT cross account, synchronized 5m marks; static notional tiers; actual funding; known-open fills. Intrabar joint-low bound is assessed after actions, never used for fills. Breached rows are unrankable hypothetical PnL, no liquidation fill invented.')
    name = window+('_double_cost' if fee > .001 else '')
    run = OUT/'runs'/name/arm
    for filename, obj in [('orders', orders), ('events', book.events), ('mark_metrics', metrics),
                          ('risk_snapshots', snapshots), ('risk_breaches', breaches),
                          ('equity_preview', curve[::max(1, len(curve)//700)]+[curve[-1]])]:
        write(run/(filename+'.json'), obj)
    pd.DataFrame(curve).to_feather(run/'equity_5m.feather')
    row = dict(strategy=arm, name=ARMS[arm], window=name, study='v10', fee=fee,
        total_trades=sum(o['side']=='buy' for o in orders), margin_mode='cross', mark_metrics=metrics,
        artifacts={str(p.relative_to(ROOT)): sha(p) for p in run.iterdir() if p.is_file() and p.name!='summary.json'})
    write(run/'summary.json', row)
    print(name, arm, round(metrics['return_pct'], 2), 'DD', round(metrics['sampled_mark_drawdown_pct'], 2),
          'adds', metrics['add_fills'], 'reductions', reductions, 'risk_valid', eligible, flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        v7 = json.loads((ROOT/'reports/quant_v7/protocol.json').read_text())
        verify_hashes(v7['data']); verify_hashes(v7['sources'])
        seeds = {}
        for window in v7['windows']:
            run = ROOT/'reports/quant_v7/runs'/window/'HoldEqual'
            meta = json.loads((run/'summary.json').read_text()); verify_hashes(meta['artifacts'])
            seeds[str((run/'trades.json').relative_to(ROOT))] = sha(run/'trades.json')
        tier_path = ROOT/'reports/quant_v9/binance_leverage_tiers.json'
        all_tiers = json.loads(tier_path.read_text())
        tiers = {s: all_tiers[s.removesuffix('USDT')+'/USDT:USDT'] for s in STEPS}
        protocol = dict(sources={str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT/'app/quant/cross_margin.py', ROOT/'scripts/stop_provenance.py']},
            data={**v7['data'], str(tier_path.relative_to(ROOT)): sha(tier_path)}, seeds=seeds,
            windows=v7['windows'], arms=ARMS, initial_cash=CAPITAL, fees=[.001,.002], leverage_setting=2,
            margin_mode='USDT single-collateral cross, long-only, three assets, no satellite positions',
            rules='Identical v7 seed fills: Notional70 keeps quantities; other arms double quantities (70% initial margin / 140% notional). Flex reduces proportionally at the next known 5m open when current gross/equity >1.6 to 0.9 AFTER execution drag. This creates a positive all-assets-zero cash floor, before future costs. Add variant requires a completed 4h breakout above previous 20 highs and EMA50, price >=1.2x last purchase and above current average entry. Added margin <=50% current positive marked position PnL minus prior added margin, <=5% equity per fill, postfill account exposure <=1.4. No coin weight trims, ordinary stops, expiry, or drawdown breaker.',
            quantity_steps=STEPS, reduction_rounding='Proportional fractional fills; ignores exchange lot rounding/minimum remainder. Research target 0.9 leaves margin for execution rounding; not an order router.',
            liquidation='Equity vs sum(current marked notional tier MM). Check synchronized opens/closes and joint 5m mark lows as conservative bound. If any breach, block further adds/reductions and mark final mark-to-market return unrankable/hypothetical; never manufacture forced fills or resurrect a liquidated account.',
            funding='One actual historical event per symbol/hour; initial fills at ties included, additions after settlement; sample end same as frozen v7 baseline.',
            limitations=['Chosen coins and reused windows are retrospective, not new out-of-sample validation',
                'Static bundled maintenance tiers, not historical/account-specific tiers; no real account keys/orders',
                '5m OHLC does not prove exchange execution; gap, latency, order failure and liquidation penalty stress are not modeled',
                'Conditional no-positive liquidation price holds other coin marks fixed; future funding/fees/shared losses change it',
                '2x label is not effective leverage; 70% margin and 70% notional are both shown, no live/paper allocation silently changed'])
        path = OUT/'protocol.json'
        if path.exists():
            prior = json.loads(path.read_text())
            if {k:v for k,v in prior.items() if k!='frozen_ms'} != protocol:raise ValueError('v10 frozen protocol changed')
        else:write(path, dict(frozen_ms=int(time.time()*1000), **protocol))
        datasets, rows = {}, []
        for window, dates in v7['windows'].items():
            challenge = window == 'challenge2025'
            if challenge not in datasets:datasets[challenge] = load_data(challenge)
            trades = json.loads((ROOT/'reports/quant_v7/runs'/window/'HoldEqual/trades.json').read_text())
            dates = [pd.Timestamp(s).strftime('%Y-%m-%d') for s in dates.split('-')]
            for fee in (.001, .002):
                for arm in ARMS:rows.append(run_arm(arm, window, trades, datasets[challenge], tiers, fee, dates))
        baselines = {r['window']: r['mark_metrics'] for r in rows if r['strategy']=='CrossNotional70'}
        for r in rows:
            m = r['mark_metrics']; b = baselines[r['window']]
            r['versus_equal_hold'] = dict(return_gap_pp=m['return_pct']-b['return_pct'],
                allocation_differs=r['strategy']!='CrossNotional70',
                within_50pct_historical_drawdown=m['sampled_mark_drawdown_pct']<=50)
        write(OUT/'comparison.json', dict(rows=rows, protocol=protocol, live_enabled=False))
        lines = ['# 全仓2x灵活加减仓研究 v10', '', protocol['rules'], '',
                 '全部结果含实际资金费、每边0.1%费用/滑点预留，另有双倍成本。任何保证金风险越界的收益只能看作未执行强平的假设值，不参与策略评比。未接入实盘。', '',
                 '|区间|方案|净收益|5m收盘回撤|5m共同低点压力回撤|加仓/减仓轮数|保证金模型|',
                 '|---|---|---:|---:|---:|---:|---|']
        for r in rows:
            m=r['mark_metrics']
            lines.append(f"|{r['window']}|{r['name']}|{m['return_pct']:.2f}%|{m['sampled_mark_drawdown_pct']:.2f}%|{m['joint_low_stress_drawdown_pct']:.2f}%|{m['add_fills']}/{m['risk_reduction_rounds']}|{'未触发边界' if m['risk_model_passed'] else '越界，收益无效'}|")
        lines += ['', '## 适用边界', *['- '+s for s in protocol['limitations']], '',
                  '减仓明细附前后账户权益、有效杠杆、全币归零余额下界与条件强平价。参数在本轮首次运行前冻结，后续调整必须新版本，不能覆盖原结果。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':main()
