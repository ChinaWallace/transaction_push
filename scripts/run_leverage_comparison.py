#!/usr/bin/env python3
"""Freeze 2x holding experiments with both 70% budget interpretations."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_strategy_comparison import config, load_result, write
from stop_provenance import verify_seal, verify_hashes, sha, economic_config, engine_version

OUT=ROOT/'reports/quant_v9'
STRATEGIES=['HoldMargin2x','HoldNotional2x','D55Margin2x','D55Notional2x']
WINDOWS={'full':'20260101-20260924','challenge2025':'20250101-20260101','reused_holdout':'20260701-20260924'}
TIERS=ROOT/'.venv.freqtrade-quant/lib/python3.11/site-packages/freqtrade/exchange/binance_leverage_tiers.json'


def freeze():
    verify_seal(required=True)
    v7=json.loads((ROOT/'reports/quant_v7/protocol.json').read_text())
    verify_hashes(v7['data']);verify_hashes(v7['sources'])
    sources={p:sha(ROOT/p) for p in ['scripts/run_leverage_comparison.py','research/strategies/LeverageComparisonStrategies.py',
        'research/strategies/HoldingComparisonStrategies.py','research/strategies/ComparisonStrategies.py',
        'scripts/analyze_leverage_comparison.py','scripts/leverage_accounting.py']}
    protocol=dict(strategies=STRATEGIES,windows=WINDOWS,sources=sources,data=v7['data'],engine_version=engine_version(),
        tier_source=str(TIERS.relative_to(ROOT)),tier_sha256=sha(TIERS),capital=10000,direction='long_only',leverage=2,
        budgets={'Margin2x':'70% initial margin; up to approximately 140% initial notional',
                 'Notional2x':'35% initial margin; up to approximately 70% initial notional'},
        liquidation='Freqtrade isolated Binance liquidation model with bundled STATIC maintenance tiers; 10% liquidation-price buffer and 99% emergency stop in margin terms. Stops may end a holding early. These are not historical exchange tiers or actual liquidation fills.',
        limitations=['Post-hoc same three coins; not fresh OOS or full-universe validation',
                     '2x is not guaranteed to survive until rebound; judge full floating drawdown and forced exits',
                     'Budget choice does not change an existing paper account; no real orders, credentials or funding transfers'])
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'protocol.json').exists():
        old=json.loads((OUT/'protocol.json').read_text())
        if {k:v for k,v in old.items() if k!='frozen_ms'}!=protocol:raise ValueError('Frozen leverage protocol changed')
    else:
        shutil.copy2(TIERS,OUT/'binance_leverage_tiers.json')
        write(OUT/'protocol.json',dict(frozen_ms=int(time.time()*1000),**protocol))
    return protocol


def run(strategy,window,fee,protocol):
    name=window+('_double_cost' if fee>.001 else '')
    directory=OUT/'runs'/name/strategy;directory.mkdir(parents=True,exist_ok=True)
    cfg=config(strategy,directory,fee)
    cfg['tradable_balance_ratio']=.35 if 'Notional' in strategy else .7
    for key in ('ccxt_config','ccxt_async_config'):
        proxy=cfg['exchange'][key].pop('httpProxy',None)
        if proxy:cfg['exchange'][key]['httpsProxy']=proxy
    data=ROOT/('reports/quant_v6/challenge_data/freqtrade_data' if window=='challenge2025' else 'reports/quant_v5/freqtrade_data')
    identity=dict(sources=protocol['sources'],data=sha(data/'manifest.json'),engine_version=protocol['engine_version'],
        tiers=protocol['tier_sha256'],timerange=WINDOWS[window],config=economic_config(cfg))
    summary=directory/'summary.json'
    if summary.exists():
        saved=json.loads(summary.read_text())
        if saved['identity']!=identity:raise ValueError('Cached leverage identity changed')
        verify_hashes(saved['artifacts']);return
    write(directory/'config.json',cfg);(directory/'result').mkdir(exist_ok=True)
    command=[str(ROOT/'.venv.freqtrade-quant/bin/freqtrade'),'backtesting','-c',str(directory/'config.json'),
        '--strategy-path',str(ROOT/'research/strategies'),'-s',strategy,'--datadir',str(data),
        '--timerange',WINDOWS[window],'--cache','none','--export','trades','--backtest-directory',str(directory/'result')]
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('FREQTRADE__') and k.lower() not in {'http_proxy','https_proxy','all_proxy'}}
    env.update(PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    print('RUN',name,strategy,flush=True)
    with (directory/'run.log').open('w') as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    log=(directory/'run.log').read_text()
    if result.returncode or ' - ERROR - ' in log or 'Traceback (most recent call last)' in log:raise RuntimeError(str(directory/'run.log'))
    if sha(TIERS)!=protocol['tier_sha256']:raise ValueError('Liquidation tiers changed during run')
    result,archive=load_result(directory/'result',strategy)
    with zipfile.ZipFile(ROOT/archive) as z:
        source=z.read(next(n for n in z.namelist() if n.endswith('_'+strategy+'.py')))
        if source!=(ROOT/'research/strategies/LeverageComparisonStrategies.py').read_bytes():raise ValueError('Archived strategy mismatch')
    if result['timerange']!=WINDOWS[window] or any(t['leverage']!=2 or t['is_short'] for t in result['trades']):raise ValueError('Unexpected leverage execution')
    write(directory/'trades.json',result['trades'])
    selected={k:result.get(k) for k in ['total_trades','profit_total','profit_total_abs','max_drawdown_account',
        'exit_reason_summary','results_per_pair']}
    artifacts={str(p.relative_to(ROOT)):sha(p) for p in [directory/'config.json',directory/'trades.json',directory/'run.log',ROOT/archive]}
    write(summary,dict(**selected,strategy=strategy,window=name,fee=fee,archive=archive,identity=identity,artifacts=artifacts))
    print('DONE',name,strategy,round(result['profit_total']*100,2),result['total_trades'],flush=True)


def main():
    protocol=freeze()
    with (OUT/'runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for window in WINDOWS:
            for strategy in STRATEGIES:run(strategy,window,.001,protocol)
        for window in ['full','challenge2025']:
            for strategy in STRATEGIES:run(strategy,window,.002,protocol)
    subprocess.run([str(ROOT/'.venv.freqtrade-quant/bin/python'),'scripts/analyze_leverage_comparison.py'],cwd=ROOT,check=True)


if __name__=='__main__':main()
