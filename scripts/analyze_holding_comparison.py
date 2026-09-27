#!/usr/bin/env python3
"""Compare trend capture against honest same-window holding alternatives."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil

import analyze_strategy_comparison as accounting
from stop_provenance import verify_seal, verify_hashes, sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports/quant_v7"
ACTIVE={"M4Structure","A1Fixed","D55ClosedTrail"}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    accounting.write(path,value)


def load_2025():
    result={}
    for pair in accounting.PAIRS:
        symbol=pair.split('/')[0]+'USDT'
        base=ROOT/"reports/quant_v6/challenge_data"
        rows=json.loads((base/f"series/markPriceKlines/5m/{symbol}.json").read_text())["rows"]
        rates=json.loads((base/f"funding/{symbol}.json").read_text())["rates"]
        result[pair]=({int(r[0]):float(r[4]) for r in rows},
            [(int(r['fundingTime'])//3_600_000*3_600_000,float(r['fundingRate'])*float(r['markPrice'])) for r in rates])
    return result


def compare(rows):
    baselines={r['window']:r for r in rows if r['strategy']=='HoldEqual'}
    for row in rows:
        baseline=baselines.get(row['window'])
        if baseline is None:continue
        m=row['mark_metrics'];b=baseline['mark_metrics']
        row['versus_equal_hold']={
            'return_gap_pp':m['return_pct']-b['return_pct'],
            'drawdown_gap_pp':m['sampled_mark_drawdown_pct']-b['sampled_mark_drawdown_pct'],
            'upside_capture_pct':100*m['return_pct']/b['return_pct'] if b['return_pct']>0 else None,
            'concentration_differs':row['strategy']=='HoldZec70',
            'allocation_differs':row['strategy'] in {'HoldZec70','HoldZecSlice'},
            'within_50pct_historical_drawdown':m['sampled_mark_drawdown_pct']<=50,
            'holding_dominates_return_and_drawdown':b['return_pct']>=m['return_pct'] and
                b['sampled_mark_drawdown_pct']<=m['sampled_mark_drawdown_pct'] and
                (b['return_pct']>m['return_pct'] or b['sampled_mark_drawdown_pct']<m['sampled_mark_drawdown_pct'])}
    return rows


def render(rows,protocol):
    lines=['# 持有与趋势保留对照 v7','',
        '针对“ZEC长期持有赚数倍，主动策略只赚几十个百分点”的复核。期初10,000 USDT，仅多1x；同一数据、费用和真实资金费。所有日期为UTC，结束日期不含。',
        '', '三币等权持有是正式基准。ZEC70为集中持仓的诊断，风险及单币配置不同，未修改实际优选仓上限。HoldEntry保留原入场然后持有到样本结束；SlowHold仅在连续两根已收盘4h跌破EMA200后退出；无ATR追踪和72h期限。三种主动v6版本由原始已验证结果复制到本批后重新对账，没有修改旧报告。',
        '', '这些行情已看过，本轮是针对漏掉趋势的事后研究，不能再称新样本外。50%历史回撤阈值是研究容忍度，不保证未来回撤上限。持有收益高不证明事先能选对币或买在起点。', '']
    for window in [*protocol['windows'],'full_double_cost','challenge2025_double_cost']:
        selected=[r for r in rows if r['window']==window]
        if not selected:continue
        lines += [f'## {window}', '', '| 方案 | 净收益 | 含浮亏回撤 | 相对三币持有 | 平均敞口 | 交易数 |', '|---|---:|---:|---:|---:|---:|']
        for row in sorted(selected,key=lambda r:-r['mark_metrics']['return_pct']):
            m=row['mark_metrics'];v=row.get('versus_equal_hold',{})
            gap=f"{v['return_gap_pp']:+.2f}pp" if 'return_gap_pp' in v else '待基准'
            if v.get('allocation_differs'):gap+='（仓位不同）'
            lines.append(f"| {row['strategy']} | {m['return_pct']:.2f}% | {m['sampled_mark_drawdown_pct']:.2f}% | {gap} | {m['average_marked_exposure_pct']:.2f}% | {row['total_trades']} |")
        lines += ['']
    lines += ['## 使用方式','',
        '不再把有正收益或交易频繁视为优秀。先检查同风险预算下能否胜过简单持有，以及降低的回撤是否值得放弃的收益；集中押中ZEC与三币分散组合分开呈现。新研究结果不自动覆盖模拟策略，原三币核心长期仓的免止损规则保留。',
        '', '逐笔、曲线、资金费位于 runs/ 与 reference_runs/；空仓与币种贡献归因见 diagnostics/zec_hold_attribution.md。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


def main():
    protocol=json.loads((OUT/'protocol.json').read_text())
    verify_seal(required=True);verify_hashes(protocol['sources']);verify_hashes(protocol['data'])
    data26=accounting.load_data();data25=None
    accounting.WINDOWS={name:tuple(datetime.strptime(s,'%Y%m%d').strftime('%Y-%m-%d') for s in dates.split('-')) for name,dates in protocol['windows'].items()}
    runs=[]
    for summary in sorted((OUT/'runs').glob('*/*/summary.json')):
        meta=json.loads(summary.read_text());verify_hashes(meta['artifacts']);runs.append((summary.parent,'v7'))
    for summary in sorted((ROOT/'reports/quant_v6/runs').glob('*/*/summary.json')):
        if summary.parent.name not in ACTIVE:continue
        target=OUT/'reference_runs'/summary.parent.parent.name/summary.parent.name
        target.mkdir(parents=True,exist_ok=True)
        for name in ('summary.json','trades.json'):shutil.copy2(summary.parent/name,target/name)
        runs.append((target,'v6_frozen_reference'))
    rows=[]
    for run,origin in runs:
        if run.parent.name.startswith('challenge2025'):
            if data25 is None:data25=load_2025()
            data=data25
        else:data=data26
        result=accounting.analyze(run,data);result['origin']=origin
        result['details_dir']=str(run.relative_to(ROOT))
        result['summary_sha256']=sha(run/'summary.json')
        rows.append(result)
        m=result['mark_metrics'];print(result['window'],result['strategy'],round(m['return_pct'],2),'DD',round(m['sampled_mark_drawdown_pct'],2),m['reconciled'],flush=True)
        if not m['reconciled']:raise ValueError('Failed reconciliation: '+str(run))
    compare(rows)
    # Keep the reader lightweight; the original identities remain in each run.
    brief=[{k:v for k,v in r.items() if k not in {'identity','artifacts'}} for r in rows]
    write(OUT/'comparison.json',{'rows':brief,'protocol':{k:v for k,v in protocol.items() if k!='data'},
        'analysis_source':sha(Path(__file__)), 'live_enabled':False,'paper_strategy_replaced':False})
    render(rows,protocol)


if __name__=='__main__':main()
