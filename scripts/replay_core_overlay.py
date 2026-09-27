#!/usr/bin/env python3
"""v11: persistent 70% core plus separately attributed trend overlay, cross margin."""
import fcntl
import json
import math
from pathlib import Path
import sys
import time

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.quant.core_overlay import CoreOverlayAccount, overlay_quantity
from replay_cross_margin import load_data, STEP, CAPITAL, STEPS
from stop_provenance import sha, verify_hashes

OUT=ROOT/'reports/quant_v11'
ARMS={
    'CoreHold70': dict(name='70%底仓持续持有', weight=0, exit_ema=50),
    'Enhance20': dict(name='底仓＋20%趋势增强', weight=.2, exit_ema=50),
    'Enhance40': dict(name='底仓＋40%趋势增强', weight=.4, exit_ema=50),
    'Enhance70': dict(name='底仓＋70%趋势增强', weight=.7, exit_ema=50),
    'Enhance40Slow': dict(name='底仓＋40%慢退出增强', weight=.4, exit_ema=200),
}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    tmp.replace(path)


def features(rows):
    """Feature keys are availability times, 4h AFTER source candle opens."""
    f=pd.DataFrame({'time':[int(r[0]) for r in rows], 'close':[float(r[4]) for r in rows],
                    'high':[float(r[2]) for r in rows]})
    if len(f)<2 or (f.time%14_400_000!=0).any() or not (f.time.diff().iloc[1:]==14_400_000).all():
        raise ValueError('Expected unique consecutive 4h candles')
    if not all(math.isfinite(v) and v>0 for v in [*f.close,*f.high]):
        raise ValueError('Invalid closed candle values')
    ema50=f.close.ewm(span=50,adjust=False,min_periods=50).mean()
    ema200=f.close.ewm(span=200,adjust=False,min_periods=200).mean()
    high=f.high.shift(1).rolling(20).max()
    out={}
    for i in range(1,len(f)):
        out[int(f.time.iloc[i])+14_400_000]=dict(
            enter=bool(f.close.iloc[i]>high.iloc[i] and f.close.iloc[i]>ema50.iloc[i]
                       and ema50.iloc[i]>ema200.iloc[i]),
            exit50=bool(f.close.iloc[i]<ema50.iloc[i] and f.close.iloc[i-1]<ema50.iloc[i-1]),
            exit200=bool(f.close.iloc[i]<ema200.iloc[i] and f.close.iloc[i-1]<ema200.iloc[i-1]),
            momentum=float(f.close.iloc[i]/f.close.iloc[max(0,i-20)]-1))
    return out


def prepare(challenge):
    data=load_data(challenge)
    base=ROOT/('reports/quant_v6/challenge_data' if challenge else 'reports/quant_v5/data')
    for s in data:
        data[s]['features']=features(json.loads((base/f'series/klines/4h/{s}.json').read_text())['rows'])
    return data


def run_arm(arm,window,trades,data,tiers,fee,dates,delay_bars=0,exit_fraction=1.0):
    start,end=[int(pd.Timestamp(s,tz='UTC').timestamp()*1000) for s in dates]
    rule=ARMS[arm]
    seeds={t['pair'].split('/')[0]+'USDT':t for t in trades}
    if len(seeds)!=3 or len({t['open_timestamp'] for t in trades})!=1:raise ValueError('Invalid core seeds')
    book=CoreOverlayAccount(CAPITAL,tiers,fee)
    last_buy={s:0.0 for s in seeds};cooldown=dict.fromkeys(seeds,0)
    pending={};risk_pending=False;previous_leverage=0.0
    curve=[];snapshots=[];breaches=[];residual=[]
    peak=CAPITAL;worst_low_dd=0.0;min_buffer=CAPITAL;max_concentration=0.0
    risk_rounds=0;overlay_exits=0;cost_basis_bridge_max=0.0
    def snap(at,reason):
        return dict(timestamp=at,reason=reason,**book.state(),
            conditional_liquidation_prices={s:book.conditional_liquidation_price(s) for s in book.positions},
            core_quantities={s:p['quantity'] for s,p in book.core.items()},
            overlay_quantities={s:p['quantity'] for s,p in book.overlay.items()})
    for at in range(start,end+STEP,STEP):
        idx=min(at,end-STEP)
        book.marks={s:data[s]['marks'][idx][0] for s in seeds}
        prices={s:data[s]['price'][idx] for s in seeds}
        for s,t in seeds.items():
            if at==t['open_timestamp']:
                book.purchase('core',s,t['amount'],t['open_rate'],at,'same_hold_seed')
        for s in seeds:
            if at in data[s]['funding']:
                rate,mark=data[s]['funding'][at];book.funding(s,at,rate,mark)
        st=book.state()
        if st['at_liquidation']:breaches.append(dict(timestamp=at,stage='known_open',**st))
        risk_signal=previous_leverage if delay_bars else (st['effective_leverage'] or 0)
        previous_leverage=st['effective_leverage'] or 0
        if not breaches and risk_signal>1.5 and book.overlay and not risk_pending:
            risk_pending=True;risk_rounds+=1;snapshots.append(snap(at,'before_reduce'))
            pending.update({s:'overlay_account_risk' for s in book.overlay})
        signals={s:data[s]['features'].get(at-delay_bars*STEP) for s in seeds}
        if not breaches:
            for s,p in list(book.overlay.items()):
                f=signals[s]
                if f and f['exit'+str(rule['exit_ema'])] and s not in pending:
                    pending[s]='overlay_trend_exit';overlay_exits+=1
            # Stress fills at most half the remaining overlay on each 5m quote.
            for s,reason in list(pending.items()):
                if s not in book.overlay:pending.pop(s);continue
                q=book.overlay[s]['quantity']
                quantity=min(q,max(STEPS[s],math.floor(q*exit_fraction/STEPS[s])*STEPS[s]))
                if exit_fraction==1.0:quantity=q
                book.sell_sleeve('overlay',s,quantity,prices[s],at,reason)
                cooldown[s]=at+14_400_000
                if s not in book.overlay:pending.pop(s);last_buy[s]=0
            if risk_pending and not pending:
                snapshots.append(snap(at,'after_reduce'));risk_pending=False
                if book.state()['all_zero_cash_floor']<=0:
                    residual.append(dict(timestamp=at,reason='Overlay closed but core still has negative zero-price floor'))
        for s,t in seeds.items():
            if at==t['close_timestamp']:
                for sleeve,positions in (('overlay',book.overlay),('core',book.core)):
                    if s in positions:book.sell_sleeve(sleeve,s,positions[s]['quantity'],t['close_rate'],at,'sample_end')
                pending.pop(s,None)
        if not breaches and not residual and not risk_pending and rule['weight']:
            # Same closed-bar ranking for all candidates; prefer strongest positive trend.
            ranked=sorted((s for s in seeds if signals[s] and signals[s]['enter']),
                          key=lambda s:(-signals[s]['momentum'],s))
            for s in ranked:
                if s not in book.core or s in pending or at<cooldown[s]:continue
                if last_buy[s] and prices[s]<last_buy[s]*1.1:continue
                q=overlay_quantity(book,s,prices[s],rule['weight'],STEPS[s])
                if q:
                    book.purchase('overlay',s,q,prices[s],at,'overlay_profit_breakout')
                    last_buy[s]=prices[s]
                    if (book.state()['effective_leverage'] or 0)>1.4+1e-8:
                        raise ValueError('Post-fill account exposure exceeded 1.4')
        book.verify_sleeves()
        for s,t in seeds.items():
            if t['open_timestamp']<=at<t['close_timestamp'] and abs(book.core[s]['quantity']-t['amount'])>1e-8:
                raise ValueError('Core quantity changed before terminal settlement')
        low=book.state({s:data[s]['marks'][idx][2] for s in seeds})
        min_buffer=min(min_buffer,low['maintenance_buffer'])
        worst_low_dd=max(worst_low_dd,(peak-low['equity'])/peak)
        if low['at_liquidation']:breaches.append(dict(timestamp=at,stage='joint_intrabar_lows_bound',**low))
        book.marks={s:data[s]['marks'][idx][1] for s in seeds}
        st=book.state();book.verify_sleeves()
        if st['at_liquidation']:breaches.append(dict(timestamp=at,stage='mark_close',**st))
        attributed=book.sleeve_pnl()
        # Bridge is attribution UPNL minus net-position UPNL, not extra wallet cash.
        original_cost=sum(p['quantity']*p['entry'] for positions in (book.core,book.overlay) for p in positions.values())
        net_cost=sum(p['quantity']*p['entry'] for p in book.positions.values())
        cost_basis_bridge_max=max(cost_basis_bridge_max,abs(original_cost-net_cost))
        if st['equity']>0:
            max_concentration=max(max_concentration,max((p['quantity']*book.marks[s]/st['equity'] for s,p in book.positions.items()),default=0))
        peak=max(peak,st['equity'])
        curve.append(dict(timestamp=at,equity=st['equity'],drawdown=(peak-st['equity'])/peak,
            exposure=st['gross'],effective_leverage=st['effective_leverage'],
            core_pnl=attributed['core'],overlay_pnl=attributed['overlay']))
    if book.positions or book.core or book.overlay:raise ValueError('Non-flat terminal account')
    orders=[dict(**e,pair=e['symbol'].removesuffix('USDT')+'/USDT:USDT') for e in book.events if e['side']!='funding']
    pnl=dict.fromkeys(seeds,0.0);fees=fund=0.0
    for e in book.events:
        if e['side']=='funding':pnl[e['symbol']]-=e['payment'];fund-=e['payment']
        else:
            pnl[e['symbol']]+=(-1 if e['side']=='buy' else 1)*e['amount']*e['price']-e['fee'];fees+=e['fee']
    error=book.wallet-CAPITAL-sum(pnl.values())
    baseline_error=book.wallet-CAPITAL-sum(t['profit_abs'] for t in trades) if arm=='CoreHold70' and fee==.001 else None
    if abs(error)>.01 or baseline_error is not None and abs(baseline_error)>.01:raise ValueError('Cashflow parity failed')
    metrics=dict(return_pct=(book.wallet/CAPITAL-1)*100,final_equity=book.wallet,
        sampled_mark_drawdown_pct=max(r['drawdown'] for r in curve)*100,joint_low_stress_drawdown_pct=worst_low_dd*100,
        average_marked_exposure_pct=sum((r['effective_leverage'] or 0) for r in curve)/len(curve)*100,
        max_marked_exposure_pct=max((r['effective_leverage'] or 0) for r in curve)*100,max_single_marked_weight_pct=max_concentration*100,
        fee_cost_usdt=fees,funding_net_income_usdt=fund,pnl_by_pair={s.removesuffix('USDT')+'/USDT:USDT':v for s,v in pnl.items()},
        core_pnl_usdt=book.flow['core'],overlay_pnl_usdt=book.flow['overlay'],sleeve_funding_net=book.funding_flow,
        add_fills=sum(o['sleeve']=='overlay' and o['side']=='buy' for o in orders),
        overlay_exit_rounds=overlay_exits,risk_reduction_rounds=risk_rounds,core_preserved_until_terminal=True,
        minimum_joint_low_maintenance_buffer_usdt=min_buffer,risk_model_passed=not breaches,
        return_is_hypothetical_after_breach=bool(breaches),risk_breach_observations=len(breaches),
        unresolved_core_risk=residual,first_risk_breach=breaches[0] if breaches else None,
        cashflow_error_usdt=error,freqtrade_baseline_difference_usdt=baseline_error,reconciled=True,
        max_cost_basis_bridge_usdt=cost_basis_bridge_max,
        definition='One aggregate cross wallet; sleeves attribute cashflows and funding but never replace exchange-average realized PnL. Core seed quantity invariant until terminal. Mark lows assess risk only, never fill historical orders.')
    months=[];previous_equity=CAPITAL;previous_core=previous_overlay=0.0
    frame=pd.DataFrame(curve)
    # Inclusive terminal funding/settlement belongs to the ending study month.
    frame['month']=pd.to_datetime(frame.timestamp.clip(upper=end-1),unit='ms',utc=True).dt.strftime('%Y-%m')
    for month,part in frame.groupby('month',sort=True):
        last=part.iloc[-1]
        months.append(dict(month=str(month),return_pct=float((last.equity/previous_equity-1)*100),
            core_contribution_pp=float((last.core_pnl-previous_core)/previous_equity*100),
            overlay_contribution_pp=float((last.overlay_pnl-previous_overlay)/previous_equity*100),
            final_equity=float(last.equity)))
        previous_equity=float(last.equity);previous_core=float(last.core_pnl);previous_overlay=float(last.overlay_pnl)
    metrics['positive_months']=sum(r['return_pct']>0 for r in months)
    metrics['observed_months']=len(months)
    metrics['worst_month_pct']=min(r['return_pct'] for r in months)
    name=window+('_execution_stress' if delay_bars else '_double_cost' if fee>.001 else '')
    run=OUT/'runs'/name/arm
    for fn,obj in [('orders',orders),('events',book.events),('mark_metrics',metrics),('risk_snapshots',snapshots),('risk_breaches',breaches),('monthly_returns',months),
                   ('equity_preview',curve[::max(1,len(curve)//700)]+[curve[-1]])]:write(run/(fn+'.json'),obj)
    frame.drop(columns=['month']).to_feather(run/'equity_5m.feather')
    row=dict(study='v11',strategy=arm,name=rule['name'],window=name,fee=fee,total_trades=sum(o['side']=='buy' for o in orders),
        margin_mode='cross',mark_metrics=metrics,execution=dict(delay_bars=delay_bars,overlay_exit_fraction=exit_fraction),
        artifacts={str(p.relative_to(ROOT)):sha(p) for p in run.iterdir() if p.is_file() and p.name!='summary.json'})
    write(run/'summary.json',row)
    print(name,arm,round(metrics['return_pct'],2),'DD',round(metrics['sampled_mark_drawdown_pct'],2),
          'overlay',round(book.flow['overlay'],2),'adds',metrics['add_fills'],'valid',metrics['risk_model_passed'],flush=True)
    return row


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior=json.loads((ROOT/'reports/quant_v10/protocol.json').read_text())
        for key in ('sources','data','seeds'):verify_hashes(prior[key])
        source_files=[Path(__file__),ROOT/'app/quant/core_overlay.py',ROOT/'app/quant/cross_margin.py',ROOT/'scripts/replay_cross_margin.py',ROOT/'scripts/stop_provenance.py']
        protocol=dict(sources={str(p.relative_to(ROOT)):sha(p) for p in source_files},data=prior['data'],seeds=prior['seeds'],
            windows=prior['windows'],arms=ARMS,capital=CAPITAL,leverage_setting=2,margin_mode='USDT cross, one net account; no other holdings',
            core='Same v7 HoldEqual seed quantities (~70% initial NOTIONAL). Never sell core for expiry, weak trend, coin weight or account drawdown; sample-end settlement only.',
            entry='Completed 4h close exceeds previous 20 highs and EMA50, EMA50>EMA200. Priority by past 20-bar return. Price above original core average; each later buy within an overlay episode requires +10% vs last buy. New overlay notional <=2x current positive core unrealized profit less existing overlay notional, <=10% equity per fill. Combined overlay adds within declared 20/40/70% equity; appreciation drift is not trimmed. Postfill gross/equity<=1.4.',
            exit='Two distinct completed 4h closes below EMA50 (EMA200 slow ablation) close only overlay at current 5m open. Four-hour cooldown after any overlay sale. Total gross/equity>1.5 closes overlay first; if its removal still leaves negative all-assets-zero cash floor, flag unresolved core risk and block further adds. No fictional core safety guarantee.',
            accounting='Aggregate average-price wallet; sleeve cashflow+remaining marked value attributes PnL. Funding allocated by actual sleeve quantity at each settlement. No double-counted collateral. Same inclusive endpoint convention as frozen baseline.',
            fees=[.001,.002],stress='Full2026 and 2025: .003 each side plus 1-bar (5m) delay for overlay signals/risk, sell only half remaining overlay per 5m quote until done. Seed/terminal fills fixed for paired comparison. Does not fully model unbounded outage, queue priority or gap liquidity.',
            quantity_steps=STEPS,seed_rounding='Seed quantities preserved exactly from v7 even if not a multiple of the disclosed overlay steps. Overlay fills follow steps; these are research assumptions, not verified current exchange filters.',
            selection='Retrospective shortlist only: all five windows at both normal costs must have <=50% close and joint-low stress DD, no margin/residual breaches. Full2026/2025 at normal, double and execution stress must have positive return AND outperform matching core hold. Rank survivors by worst full-window excess vs hold; tie by lower worst DD. No live promotion.',
            limitations=['All source periods and coins already observed; neither 60 comparisons nor monthly return summaries constitute independent samples or genuine new OOS.',
                'Only BTC/ETH/ZEC; no historical contract selection or ordinary-position portfolio tested.',
                'Static maintenance tiers; conditional liquidation depends on other coins. Mark OHLC and stress are approximations.',
                'Core may retain large losses; enhanced trading losses can consume shared collateral. Core-preservation failure is reported, never silently liquidated or rescued.'])
        path=OUT/'protocol.json'
        if path.exists():
            saved=json.loads(path.read_text())
            if {k:v for k,v in saved.items() if k!='frozen_ms'}!=protocol:raise ValueError('Frozen v11 protocol changed')
        else:write(path,dict(frozen_ms=int(time.time()*1000),**protocol))
        raw=json.loads((ROOT/'reports/quant_v9/binance_leverage_tiers.json').read_text())
        tiers={s:raw[s.removesuffix('USDT')+'/USDT:USDT'] for s in STEPS}
        datasets={};rows=[]
        for window,dates in prior['windows'].items():
            challenge=window=='challenge2025'
            if challenge not in datasets:datasets[challenge]=prepare(challenge)
            trades=json.loads((ROOT/'reports/quant_v7/runs'/window/'HoldEqual/trades.json').read_text())
            dates=[pd.Timestamp(s).strftime('%Y-%m-%d') for s in dates.split('-')]
            cases=[(.001,0,1.0),(.002,0,1.0)]+([(.003,1,.5)] if window in ('full','challenge2025') else [])
            for fee,delay,fraction in cases:
                for arm in ARMS:rows.append(run_arm(arm,window,trades,datasets[challenge],tiers,fee,dates,delay,fraction))
        bases={r['window']:r['mark_metrics'] for r in rows if r['strategy']=='CoreHold70'}
        for r in rows:
            m=r['mark_metrics'];r['versus_equal_hold']=dict(return_gap_pp=m['return_pct']-bases[r['window']]['return_pct'],
                allocation_differs=r['strategy']!='CoreHold70',within_50pct_historical_drawdown=m['sampled_mark_drawdown_pct']<=50)
        details={}
        for arm in ARMS:
            if arm=='CoreHold70':continue
            arm_rows=[r for r in rows if r['strategy']==arm]
            failed=[]
            for r in arm_rows:
                m=r['mark_metrics']
                if max(m['sampled_mark_drawdown_pct'],m['joint_low_stress_drawdown_pct'])>50:failed.append(r['window']+': drawdown>50')
                if not m['risk_model_passed'] or m['unresolved_core_risk']:failed.append(r['window']+': risk model failure')
                if r['window'].startswith(('full','challenge2025')) and (m['return_pct']<=0 or r['versus_equal_hold']['return_gap_pp']<=0):
                    failed.append(r['window']+': did not beat holding')
            details[arm]=dict(passed=not failed,failed=failed,
                worst_full_window_excess_pp=min(r['versus_equal_hold']['return_gap_pp'] for r in arm_rows if r['window'].startswith(('full','challenge2025'))),
                worst_drawdown_pct=max(r['mark_metrics']['sampled_mark_drawdown_pct'] for r in arm_rows))
        candidates=sorted((s for s,d in details.items() if d['passed']),
                          key=lambda s:(-details[s]['worst_full_window_excess_pp'],details[s]['worst_drawdown_pct']))
        selection=dict(kind='retrospective_frozen_rule_screen_not_new_oos',candidates=candidates,details=details,
            execution_changed=False,requires_new_forward_comparison=True,selected=candidates[0] if candidates else None)
        write(OUT/'selection.json',selection)
        write(OUT/'comparison.json',dict(rows=rows,protocol=protocol,selection=selection,live_enabled=False))
        lines=['# 底仓保留与趋势增强 v11','',protocol['core'],'',protocol['entry'],'',protocol['exit'],'',
            '全部为事后研究。增强归因不改变整仓均价的钱包记账；底仓数量验证与现金流对账逐5m检查。', '',
            '|区间|方案|净收益|5m回撤|共同低点压力回撤|增强净贡献USDT|加仓数|',
            '|---|---|---:|---:|---:|---:|---:|']
        for r in rows:
            m=r['mark_metrics'];lines.append(f"|{r['window']}|{r['name']}|{m['return_pct']:.2f}%|{m['sampled_mark_drawdown_pct']:.2f}%|{m['joint_low_stress_drawdown_pct']:.2f}%|{m['overlay_pnl_usdt']:.2f}|{m['add_fills']}|")
        lines+=['','## 冻结筛选','',json.dumps(selection,ensure_ascii=False,indent=2),'','## 限制','']+protocol['limitations']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
