#!/usr/bin/env python3
"""Paired first-lot-only 2x holding controls; never hide liquidation/re-entry."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time

import leverage_accounting as accounting
from analyze_holding_comparison import load_2025
from stop_provenance import sha, verify_hashes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/quant_v9'


def main():
    protocol=json.loads((OUT/'protocol.json').read_text())
    verify_hashes(protocol['sources']);verify_hashes(protocol['data'])
    original=json.loads((OUT/'comparison.json').read_text())
    rows=[r for r in original['rows'] if not r.get('derived_first_lot_only')]
    inputs={str((OUT/'runs'/r['window']/r['strategy']/'trades.json').relative_to(ROOT)):
            sha(OUT/'runs'/r['window']/r['strategy']/'trades.json') for r in rows}
    derivation=dict(source_sha256=sha(Path(__file__)),inputs=inputs,
        method='Keep each pair first original 2x holding lot, then permanently stop that pair after exit. Require all three initial lots to enter together before any liquidation. No later entry/stake decisions copied. This is a counterfactual subset with full cashflow/MTM reconstruction, not a separately run Freqtrade strategy.',
        limitations='Engine liquidation exits exclude liquidation penalties and use static tiers. Forced settlement remains approximate.')
    path=OUT/'survival_protocol.json'
    if path.exists():
        prior=json.loads(path.read_text())
        if {k:v for k,v in prior.items() if k!='frozen_ms'}!=derivation:raise ValueError('Survival controls changed')
    else:accounting.write(path,dict(frozen_ms=int(time.time()*1000),**derivation))
    accounting.WINDOWS={k:tuple(datetime.strptime(s,'%Y%m%d').strftime('%Y-%m-%d') for s in v.split('-')) for k,v in protocol['windows'].items()}
    data26=accounting.load_data();data25=load_2025()
    derived=[]
    for row in rows:
        if row['strategy'] not in ('HoldMargin2x','HoldNotional2x'):continue
        source=OUT/'runs'/row['window']/row['strategy']
        meta=json.loads((source/'summary.json').read_text());verify_hashes(meta['artifacts'])
        trades=sorted(json.loads((source/'trades.json').read_text()),key=lambda t:t['open_timestamp'])
        first={}
        for t in trades:first.setdefault(t['pair'],t)
        trades=list(first.values())
        if len(trades)!=3 or len({t['open_timestamp'] for t in trades})!=1 or any(len(t['orders'])!=2 for t in trades):
            raise ValueError('Not an identical simultaneous seed basket')
        name=row['strategy']+'NoReentry';run=OUT/'runs'/row['window']/name;run.mkdir(parents=True,exist_ok=True)
        summary=dict(strategy=name,window=row['window'],fee=row['fee'],total_trades=3,
            profit_total_abs=sum(t['profit_abs'] for t in trades),profit_total=sum(t['profit_abs'] for t in trades)/10000,
            derived_first_lot_only=True,source_run=str(source.relative_to(ROOT)),source_trades_sha256=sha(source/'trades.json'))
        accounting.write(run/'trades.json',trades);accounting.write(run/'summary.json',summary)
        result=accounting.analyze(run,data25 if row['window'].startswith('challenge2025') else data26)
        if not result['mark_metrics']['reconciled']:raise ValueError('Survival cashflow reconciliation failed')
        result['study']='v9';derived.append(result)
    baselines={r['window']:r['mark_metrics'] for r in json.loads((ROOT/'reports/quant_v7/comparison.json').read_text())['rows'] if r['strategy']=='HoldEqual'}
    all_rows=rows+derived
    for row in all_rows:
        m=row['mark_metrics'];b=baselines[row['window']]
        row['versus_equal_hold']=dict(return_gap_pp=m['return_pct']-b['return_pct'],allocation_differs=True,
            within_50pct_historical_drawdown=m['sampled_mark_drawdown_pct']<=50)
        row['liquidation_count']=m['exit_counts'].get('liquidation',0)
        row['allows_reentry_after_liquidation']=not row.get('derived_first_lot_only',False)
        if row['liquidation_count']:
            print(row['window'],row['strategy'],'liq',row['liquidation_count'],round(m['return_pct'],2),'DD',round(m['sampled_mark_drawdown_pct'],2),flush=True)
    accounting.write(OUT/'comparison.json',{**original,'rows':all_rows,'engine_runs':len(rows),'survival_controls':len(derived),'survival':derivation})
    lines=['# 2x持有：强平与重入必须分开','',
        'Margin2x用70%初始保证金（约140%敞口）；Notional2x用35%保证金（约70%敞口）。所有方案含费用及真实资金费。',
        '', '**原始策略强平后可以再次入场。NoReentry仅保留各币最初一笔仓位，该币强平后永久停止买入。后者是相同初始成交的现金流反事实重建，不能称为独立引擎回测。**',
        '', '静态维持保证金档位、5m撮合与采样回撤；引擎不计强平罚金，真实损失可能更高。', '',
        '|区间|方案|净收益|5m含浮亏回撤|强平次数|强平后重入|','|---|---|---:|---:|---:|---|']
    for row in all_rows:
        m=row['mark_metrics'];lines.append(f"|{row['window']}|{row['strategy']}|{m['return_pct']:.2f}%|{m['sampled_mark_drawdown_pct']:.2f}%|{row['liquidation_count']}|{'允许' if row['allows_reentry_after_liquidation'] else '禁止'}|")
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
