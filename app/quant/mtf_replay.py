"""Deterministic short-sample integration replay, never presented as validated returns."""
from bisect import bisect_left
from pathlib import Path
from app.advisory.engine import DAY, iso
from .futures_book import FuturesBook
from .multiframe import PERIODS
from .service import read, build_report


def replay(directory, fee_bps=5, slippage_bps=5, policy=None, rules=None):
    directory=Path(directory)
    histories={}
    for tf in PERIODS:
        for path in (directory/tf).glob('*.json'):
            histories.setdefault(path.stem,{})[tf]=read(path)['rows']
    histories={s:frames for s,frames in histories.items() if all(tf in frames and len(frames[tf])>=100 for tf in PERIODS)}
    if not histories: raise ValueError('No complete 4h/1h/15m sample. Collect history first; replay will not invent data.')
    funding={s:read(directory/'funding'/(s+'.json')) for s in histories}
    funding={s:({'start':c['coverage']['startTime'],'end':c['coverage']['endTime'],
                 'complete':c['coverage']['complete'],'events':c['rows']} if 'coverage' in c else c) for s,c in funding.items()}
    start=max(max(int(frames[tf][60][6])+1 for tf in PERIODS) for frames in histories.values())
    start=max(start,max(int(frames['15m'][96][0]) for frames in histories.values()))
    end=min(int(frames['15m'][-1][6])+1 for frames in histories.values())
    if start>=end:raise ValueError('No common out-of-warmup replay range')
    for s,c in funding.items():
        if not c.get('complete') or c['start']>start or c['end']<end-1:
            raise ValueError('Incomplete funding coverage: '+s)
    opens={s:{int(r[0]):r for r in f['15m']} for s,f in histories.items()}
    closes={s:{tf:[int(r[6]) for r in f[tf]] for tf in PERIODS} for s,f in histories.items()}
    book=FuturesBook(10000,fee_bps,slippage_bps);decisions=[];previous=start-1;steps=0
    def settle_until(cutoff):
        nonlocal previous
        for s,c in funding.items():
            for event in sorted(c['events'],key=lambda e:int(e['fundingTime'])):
                at=int(event['fundingTime'])
                if previous<at<=cutoff:book.funding(s,at,float(event['fundingRate']),float(event['markPrice']))
        previous=cutoff
    for now in range(start,end,900_000):
        if not all(now in opens[s] for s in histories):raise ValueError('15m history gap in common replay range')
        sliced={s:{tf:rows[max(0,bisect_left(closes[s][tf],now)-201):bisect_left(closes[s][tf],now)]
                   for tf,rows in frames.items()} for s,frames in histories.items()}
        quotes={s:{'bid':float(opens[s][now][1]),'ask':float(opens[s][now][1]),'mark':float(opens[s][now][1])} for s in histories}
        settle_until(now)
        info={'symbols':[{'symbol':s,'baseAsset':s.removesuffix('USDT'),'quoteAsset':'USDT','contractType':'PERPETUAL',
                          'status':'TRADING','underlyingType':'COIN','onboardDate':0} for s in histories]}
        tickers=[{'symbol':s,'quoteVolume':sum(float(r[7]) for r in sliced[s]['15m'][-96:]),'closeTime':now} for s in histories]
        books=[{'symbol':s,'bidPrice':q['bid'],'askPrice':q['ask'],'time':now} for s,q in quotes.items()]
        marks=[]
        for s,q in quotes.items():
            past=[e for e in funding[s]['events'] if int(e['fundingTime'])<=now]
            marks.append({'symbol':s,'markPrice':q['mark'],'indexPrice':q['mark'],'time':now,
                          'lastFundingRate':float(past[-1]['fundingRate']) if past else 0})
        snapshot={'as_of':now,'exchange_info':info,'tickers':tickers,'book_tickers':books,'premium_index':marks,
                  'funding_info':[],'histories':{},'multiframe_histories':sliced,'market_caps':[]}
        report=build_report(snapshot,book.equity(),book.positions,active_plan=book.active_plan,policy=policy,rules=rules)
        before=len(book.events)
        book.apply(report['plan'],quotes,now,report['plan']['signal_id'],complete=report['plan']['complete'])
        if len(book.events)>before:decisions.append({'at':iso(now),'evidence':report['plan']['signal_evidence'],
                                                  'decisions':book.last_decisions})
        # Intrabar OHLC approximation: high then low for long trailing stops.
        high={s:{k:float(opens[s][now][2]) for k in ('bid','ask','mark')} for s in histories}
        settle_until(now+450_000)
        book.observe(now+450_000,high)
        low={}
        for s in histories:
            bar=opens[s][now];minimum=float(bar[3]);stop=book.positions.get(s,{}).get('stop',0)
            execution=stop if minimum<=stop else minimum
            low[s]={'bid':execution,'ask':execution,'mark':minimum}
        settle_until(now+899_998)
        book.observe(now+899_998,low)
        close={s:{k:float(opens[s][now][4]) for k in ('bid','ask','mark')} for s in histories}
        settle_until(now+899_999)
        book.observe(now+899_999,close);book.record(now+899_999)
        steps+=1
    peak=10000;dd=0
    for point in book.curve:peak=max(peak,point['equity']);dd=max(dd,1-point['equity']/peak)
    return {'strategy':'contracts-v4.0-mtf','purpose':'real_data_integration_sample_not_validation',
            'portfolio_policy':policy.model_dump() if policy else None,
            'missing_preferred_symbols':sorted(set(policy.preferred_symbols)-set(histories)) if policy else [],
            'from':iso(start),'through':iso(end-1),'symbols':sorted(histories),'steps':steps,
            'net_return_pct':(book.equity()/10000-1)*100,'sampled_close_drawdown_pct':dd*100,
            'trades_closed':len(book.closed),'fills':sum(e['side'] in {'buy','sell'} for e in book.events),
            'fee_bps':fee_bps,'slippage_bps':slippage_bps,'equity':book.equity(),
            'events':book.events,'decisions':decisions,'curve':book.curve,
            'limitations':['Preselected liquid assets, short sample; not full-universe or out-of-sample validation',
                'OHLC high-then-low stop approximation; no tick order, spread, depth or liquidation model',
                'Historical market caps absent: unknown cap reduces position size and leverage to 1x',
                'Funding interval filter assumes 8h where metadata is absent; actual funding events settle cash',
                'Past sample returns are not an expected return or evidence of a profitable deployable strategy'],
            'live_eligible':False}
