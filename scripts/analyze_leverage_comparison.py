#!/usr/bin/env python3
"""Reconstruct leveraged PnL from actual notional fills, fees and funding."""
import json
from datetime import datetime
from pathlib import Path
import leverage_accounting as accounting
from analyze_holding_comparison import load_2025
from stop_provenance import verify_hashes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/quant_v9'


def main():
    protocol=json.loads((OUT/'protocol.json').read_text())
    verify_hashes(protocol['sources']);verify_hashes(protocol['data'])
    accounting.WINDOWS={k:tuple(datetime.strptime(s,'%Y%m%d').strftime('%Y-%m-%d') for s in v.split('-')) for k,v in protocol['windows'].items()}
    data26=accounting.load_data();data25=load_2025();rows=[]
    for path in sorted((OUT/'runs').glob('*/*/summary.json')):
        value=json.loads(path.read_text());verify_hashes(value['artifacts'])
        row=accounting.analyze(path.parent,data25 if path.parent.parent.name.startswith('challenge2025') else data26)
        if not row['mark_metrics']['reconciled']:raise ValueError('2x cashflows do not reconcile')
        row={k:v for k,v in row.items() if k not in {'identity','artifacts'}}
        row['study']='v9';rows.append(row)
        print(row['window'],row['strategy'],row['mark_metrics']['return_pct'],row['mark_metrics']['sampled_mark_drawdown_pct'],flush=True)
    baselines={r['window']:r for r in json.loads((ROOT/'reports/quant_v7/comparison.json').read_text())['rows'] if r['strategy']=='HoldEqual'}
    for row in rows:
        b=baselines[row['window']]['mark_metrics'];m=row['mark_metrics']
        row['versus_equal_hold']=dict(return_gap_pp=m['return_pct']-b['return_pct'],allocation_differs=True,
            within_50pct_historical_drawdown=m['sampled_mark_drawdown_pct']<=50)
    accounting.write(OUT/'comparison.json',dict(rows=rows,protocol={k:v for k,v in protocol.items() if k!='data'},live_enabled=False))
    lines=['# 2x优选持有研究 v9','',protocol['liquidation'],'',
        'Margin2x：70%初始保证金，约140%名义敞口。Notional2x：35%初始保证金，约70%名义敞口。费用及实际资金费已计入。', '',
        '|区间|策略|收益|5m盯市回撤|退出原因|','|---|---|---:|---:|---|']
    for row in rows:
        m=row['mark_metrics'];lines.append(f"|{row['window']}|{row['strategy']}|{m['return_pct']:.2f}%|{m['sampled_mark_drawdown_pct']:.2f}%|{m['exit_counts']}|")
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
