"""v12 generic multi-asset research replay; no network, credentials or live orders.

Preserves v11 aggregate cross-wallet accounting and overlay rules, but injects
universe, seed amounts and quantity steps explicitly. Frozen v11 stays intact.
"""
import math
import pandas as pd
from .core_overlay import CoreOverlayAccount, overlay_quantity

STEP = 300_000

def run_portfolio(rule,trades,data,tiers,steps,fee,dates,capital=10000.0,delay_bars=0,exit_fraction=1.0):
    start,end=[int(pd.Timestamp(s,tz='UTC').timestamp()*1000) for s in dates]
    if start>=end or start%STEP or end%STEP:
        raise ValueError('Research dates must use a valid 5m grid')
    seeds={t['pair'].split('/')[0]+'USDT':t for t in trades}
    if not seeds or len(seeds)!=len(trades) or len({t['open_timestamp'] for t in trades})!=1:
        raise ValueError('Expected unique simultaneous portfolio seeds')
    if delay_bars not in (0,1) or not 0<exit_fraction<=1:raise ValueError('Invalid execution model')
    if set(seeds)-set(data) or set(seeds)-set(steps):raise ValueError('Missing symbol inputs')
    if any(t['open_timestamp']%STEP or t['close_timestamp']%STEP for t in trades):
        raise ValueError('Seed timestamps must align to the 5m grid')
    if any(not math.isfinite(steps[s]) or steps[s]<=0 for s in seeds):
        raise ValueError('Invalid quantity step')
    if rule.get('exit_ema') not in (50,200) or not 0<=rule.get('weight',-1)<=.7:
        raise ValueError('Invalid overlay rule')
    if any(not start<=t['open_timestamp']<t['close_timestamp']<end for t in trades):
        raise ValueError('Seeds outside research window')
    book=CoreOverlayAccount(capital,tiers,fee)
    last_buy={s:0.0 for s in seeds};cooldown=dict.fromkeys(seeds,0)
    pending={};risk_pending=False;previous_leverage=0.0
    curve=[dict(timestamp=start,equity=capital,drawdown=0.0,exposure=0.0,
                effective_leverage=0.0,core_pnl=0.0,overlay_pnl=0.0)]
    snapshots=[];breaches=[];residual=[]
    peak=capital;worst_low_dd=0.0;min_buffer=capital;max_concentration=0.0
    sampled_exposures=[]
    risk_rounds=0;overlay_exits=0;cost_basis_bridge_max=0.0
    def snap(at,reason):
        return dict(timestamp=at,reason=reason,**book.state(),
            conditional_liquidation_prices={s:book.conditional_liquidation_price(s) for s in book.positions},
            core_quantities={s:p['quantity'] for s,p in book.core.items()},
            overlay_quantities={s:p['quantity'] for s,p in book.overlay.items()})
    for at in range(start,end,STEP):
        idx=at
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
                quantity=min(q,max(steps[s],math.floor(q*exit_fraction/steps[s])*steps[s]))
                if exit_fraction==1.0:quantity=q
                book.sell_sleeve('overlay',s,quantity,prices[s],at,reason)
                cooldown[s]=at+14_400_000
                if s not in book.overlay:pending.pop(s);last_buy[s]=0
            if risk_pending and not pending:
                snapshots.append(snap(at,'after_reduce'));risk_pending=False
                if book.state()['all_zero_cash_floor']<=0:
                    residual.append(dict(timestamp=at,reason='Overlay closed but core still has negative zero-price floor'))
        if not breaches and not residual and not risk_pending and rule['weight']:
            # Same closed-bar ranking for all candidates; prefer strongest positive trend.
            ranked=sorted((s for s in seeds if signals[s] and signals[s]['enter']),
                          key=lambda s:(-signals[s]['momentum'],s))
            for s in ranked:
                if s not in book.core or s in pending or at<cooldown[s] or at>=seeds[s]['close_timestamp']:continue
                if last_buy[s] and prices[s]<last_buy[s]*1.1:continue
                q=overlay_quantity(book,s,prices[s],rule['weight'],steps[s])
                if q:
                    book.purchase('overlay',s,q,prices[s],at,'overlay_profit_breakout')
                    last_buy[s]=prices[s]
                    if (book.state()['effective_leverage'] or 0)>1.4+1e-8:
                        raise ValueError('Post-fill account exposure exceeded 1.4')
        book.verify_sleeves()
        for s,t in seeds.items():
            if t['open_timestamp']<=at<=t['close_timestamp'] and abs(book.core[s]['quantity']-t['amount'])>1e-8:
                raise ValueError('Core quantity changed before terminal settlement')
        low=book.state({s:data[s]['marks'][idx][2] for s in seeds})
        min_buffer=min(min_buffer,low['maintenance_buffer'])
        worst_low_dd=max(worst_low_dd,(peak-low['equity'])/peak)
        if low['at_liquidation']:breaches.append(dict(timestamp=at,stage='joint_intrabar_lows_bound',**low))
        book.marks={s:data[s]['marks'][idx][1] for s in seeds}
        st=book.state();book.verify_sleeves()
        if st['at_liquidation']:breaches.append(dict(timestamp=at,stage='mark_close',**st))
        sampled_exposures.append(st['effective_leverage'] or 0)
        if st['equity']>0:
            max_concentration=max(max_concentration,max((p['quantity']*book.marks[s]/st['equity'] for s,p in book.positions.items()),default=0))
        # Terminal close is known only after this candle. Preserve its full
        # holding-period risk before settling; never fill at a future close
        # under the candle-open timestamp.
        peak=max(peak,st['equity'])
        for s,t in seeds.items():
            if at==t['close_timestamp']:
                for sleeve,positions in (('overlay',book.overlay),('core',book.core)):
                    if s in positions:book.sell_sleeve(sleeve,s,positions[s]['quantity'],t['close_rate'],at+STEP,'sample_end')
                pending.pop(s,None)
        st=book.state();book.verify_sleeves()
        attributed=book.sleeve_pnl()
        # Bridge is attribution UPNL minus net-position UPNL, not extra wallet cash.
        original_cost=sum(p['quantity']*p['entry'] for positions in (book.core,book.overlay) for p in positions.values())
        net_cost=sum(p['quantity']*p['entry'] for p in book.positions.values())
        cost_basis_bridge_max=max(cost_basis_bridge_max,abs(original_cost-net_cost))
        peak=max(peak,st['equity'])
        curve.append(dict(timestamp=at+STEP,equity=st['equity'],drawdown=(peak-st['equity'])/peak,
            exposure=st['gross'],effective_leverage=st['effective_leverage'],
            core_pnl=attributed['core'],overlay_pnl=attributed['overlay']))
    if book.positions or book.core or book.overlay:raise ValueError('Non-flat terminal account')
    orders=[dict(**e,pair=e['symbol'].removesuffix('USDT')+'/USDT:USDT') for e in book.events if e['side']!='funding']
    pnl=dict.fromkeys(seeds,0.0);fees=fund=0.0
    for e in book.events:
        if e['side']=='funding':pnl[e['symbol']]-=e['payment'];fund-=e['payment']
        else:
            pnl[e['symbol']]+=(-1 if e['side']=='buy' else 1)*e['amount']*e['price']-e['fee'];fees+=e['fee']
    error=book.wallet-capital-sum(pnl.values())
    if abs(error)>.01:raise ValueError('Cashflow parity failed')
    metrics=dict(return_pct=(book.wallet/capital-1)*100,final_equity=book.wallet,
        sampled_mark_drawdown_pct=max(r['drawdown'] for r in curve)*100,joint_low_stress_drawdown_pct=worst_low_dd*100,
        average_marked_exposure_pct=sum(sampled_exposures)/len(sampled_exposures)*100,
        max_marked_exposure_pct=max(sampled_exposures)*100,max_single_marked_weight_pct=max_concentration*100,
        fee_cost_usdt=fees,funding_net_income_usdt=fund,pnl_by_pair={s.removesuffix('USDT')+'/USDT:USDT':v for s,v in pnl.items()},
        core_pnl_usdt=book.flow['core'],overlay_pnl_usdt=book.flow['overlay'],sleeve_funding_net=book.funding_flow,
        add_fills=sum(o['sleeve']=='overlay' and o['side']=='buy' for o in orders),
        overlay_exit_rounds=overlay_exits,risk_reduction_rounds=risk_rounds,core_preserved_until_terminal=True,
        minimum_joint_low_maintenance_buffer_usdt=min_buffer,risk_model_passed=not breaches,
        return_is_hypothetical_after_breach=bool(breaches),risk_breach_observations=len(breaches),
        unresolved_core_risk=residual,first_risk_breach=breaches[0] if breaches else None,
        cashflow_error_usdt=error,reconciled=True,
        max_cost_basis_bridge_usdt=cost_basis_bridge_max,
        definition='One aggregate cross wallet; sleeves attribute cashflows and funding but never replace exchange-average realized PnL. Core seed quantity invariant until terminal. Mark lows assess risk only, never fill historical orders.')
    months=[];previous_equity=capital;previous_core=previous_overlay=0.0
    frame=pd.DataFrame(curve)
    # Close observations on a month boundary belong to the candle just ended.
    frame['month']=pd.to_datetime((frame.timestamp-1).clip(lower=start),unit='ms',utc=True).dt.strftime('%Y-%m')
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
    metrics['initial_core_notional_usdt']=sum(t['amount']*t['open_rate'] for t in trades)
    metrics['initial_core_symbols']=list(seeds)
    return dict(metrics=metrics,orders=orders,events=book.events,risk_snapshots=snapshots,
                risk_breaches=breaches,monthly_returns=months,curve=curve,frame=frame.drop(columns=['month']))
