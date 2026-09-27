"""Causal daily futures diagnostic on the current liquid-contract universe.

This is not point-in-time universe/fundamental validation. Historical market-cap
data is deliberately absent. Funding uses real historical rates and mark prices;
daily stop ordering uses a documented conservative cost convention.
"""
import bisect
import hashlib
from collections import defaultdict
from pathlib import Path

from app.advisory.engine import DAY, iso
from .backtest import metrics
from .futures_book import FuturesBook
from .service import DATA, ROOT, atomic_json, read
from .universe import contract_features, rank_contracts, target_portfolio, unwrap

START=1767225600000
END=1790208000000


def prepare(directory=DATA,funding_directory=ROOT/"reports/quant_v3/futures_replay/funding/symbols",progress=print):
    specs={r["symbol"]:r for r in unwrap(read(Path(directory)/"exchange_info.json"))["symbols"]}
    requested=read(Path(directory)/"history_request.json")["symbols"]
    histories={s:read(Path(directory)/"klines"/(s+".json"))["rows"] for s in requested}
    fundings={};funding_times={};coverage={};opens={}
    for s,rows in histories.items():
        opens[s]={int(b[0]):b for b in rows}
        p=Path(funding_directory)/(s+".json")
        f=read(p) if p.exists() else {}
        v=f.get("validation",{})
        coverage[s]=bool(v.get("complete") and not v.get("errors"))
        fundings[s]=f.get("rates",[]);funding_times[s]=[int(e["fundingTime"]) for e in fundings[s]]
    if not all(coverage.values()):
        raise ValueError("Full requested funding range required; refusing retrospective complete-symbol filtering")
    days=[]
    for now in range(START,END,DAY):
        universe=[];features={};intervals={};bars={}
        for s,rows in histories.items():
            bar=opens[s].get(now)
            if bar is None:continue
            end=bisect.bisect_left([int(r[0]) for r in rows],now)
            try:f=contract_features(rows[max(0,end-201):end],now)
            except ValueError:continue
            position=bisect.bisect_left(funding_times[s],now)-1
            if position<0 or now-funding_times[s][position]>12*3600000:continue
            rate=float(fundings[s][position]["fundingRate"])
            interval=8 if position<1 else max(1,min(8,round((funding_times[s][position]-funding_times[s][position-1])/3600000)))
            spec=specs[s];price=float(bar[1]);rejections=[]
            if f["volume"]<5_000_000:rejections.append("turnover_below_5m")
            age=(now-int(spec.get("onboardDate",now)))/DAY
            if age<30:rejections.append("listing_under_30_days_research_only")
            universe.append({"symbol":s,"base_asset":spec["baseAsset"],"asset_class":spec.get("underlyingType","UNKNOWN"),
                "contract_type":spec["contractType"],"age_days":age,"volume24_usdt":f["volume"],
                "bid":price,"ask":price,"mark":price,"index":price,"spread_bps":0,"funding_rate":rate,
                "funding_known":True,"rejections":rejections})
            features[s]=f;intervals[s]=interval;bars[s]=bar
        ranked=rank_contracts(universe,{s:[] for s in features},[],now,funding_intervals=intervals,features_override=features)
        # Funding at midnight is settled before orders at 00:01 UTC.
        events=[]
        for s in histories:
            lo=bisect.bisect_left(funding_times[s],now);hi=bisect.bisect_left(funding_times[s],now+DAY)
            events.extend((s,e) for e in fundings[s][lo:hi])
        days.append({"time":now,"ranking":ranked,"bars":{s:b[now] for s,b in opens.items() if now in b},
                     "funding":sorted(events,key=lambda item:int(item[1]["fundingTime"]))})
        if len(days)%50==0:progress(f"Prepared {len(days)} daily cross-sections")
    return days,{"funding_complete_symbols":sum(coverage.values()),"history_symbols":len(histories),
                 "funding_incomplete_symbols":sorted(s for s,v in coverage.items() if not v)}


def run(days,fee_bps=5,slippage_bps=5,leverage_override=None,exclude=(),delay_days=0,allow_funding_credits=True):
    book=FuturesBook(fee_bps=fee_bps,slippage_bps=slippage_bps)
    missing=[];stress_drawdown=0;peak=book.initial_cash;funding_bound=0;gap_liquidations=[]
    for i,day in enumerate(days):
        now=day["time"];bars=day["bars"]
        for s in set(book.positions)-set(bars):
            # No executable observation: conservative full collateral write-off.
            p=book.positions[s]
            book.close(s,p["quantity"],max(0,p["entry"]-p["margin"]/p["quantity"]),now,"missing_bar_collateral_loss")
            missing.append({"symbol":s,"time":iso(now)})
        for s,e in day["funding"]:
            if s in book.positions and int(e["fundingTime"])<=now+60000:
                if not allow_funding_credits and float(e["fundingRate"])<0:
                    funding_bound+=1;continue
                book.funding(s,int(e["fundingTime"]),float(e["fundingRate"]),float(e["markPrice"]))
        quotes={s:{"bid":float(b[1]),"ask":float(b[1]),"mark":float(b[1])} for s,b in bars.items()}
        # A gap can jump through a resting stop. Estimated liquidation uses 1% maintenance,
        # not unavailable historical exchange brackets; never certify real liquidation distance.
        for s,p in list(book.positions.items()):
            liq=max(0,(p["entry"]-p["margin"]/p["quantity"])/.99)
            if quotes[s]["mark"]<=liq:
                gap_liquidations.append({"symbol":s,"time":iso(now),"estimated_liquidation":liq})
        ranking=days[max(0,i-delay_days)]["ranking"] if i>=delay_days else []
        ranking=[r for r in ranking if r["symbol"] not in exclude and r["symbol"] in quotes]
        if leverage_override is not None:
            # Sensitivity only: same unknown-cap selection/weights, changed collateral allocation.
            ranking=[{**r,"leverage":leverage_override if r["asset_class"]=="COIN" and r.get("features",{}).get("bars",0)>=90 else 1} for r in ranking]
        plan=target_portfolio(ranking,book.equity(),book.positions)
        book.apply(plan,quotes,now+60000,str(now))
        peak=max(peak,book.equity())
        # Unknown OHLC order: synchronous highs followed by synchronous lows form
        # a deliberately conservative stress bound, not an observed equity path.
        intraday_upper=book.wallet+sum(p["quantity"]*(float(bars[s][2])-p["entry"]) for s,p in book.positions.items())
        stopped={s for s,p in book.positions.items() if float(bars[s][3])<=p["stop"]}
        intraday_credits=0
        for s,e in day["funding"]:
            if s not in book.positions or int(e["fundingTime"])<=now+60000:continue
            rate=float(e["fundingRate"])
            # Stop time inside a daily bar is unknown: charge all debits, withhold credits
            # on stopped positions. This biases the estimate against the strategy.
            if rate<0 and (s in stopped or not allow_funding_credits):
                funding_bound+=1;continue
            if rate<0:intraday_credits-=book.positions[s]["quantity"]*float(e["markPrice"])*rate
            book.funding(s,int(e["fundingTime"]),rate,float(e["markPrice"]))
        peak=max(peak,intraday_upper+intraday_credits)
        # Worst synchronous daily lows, bounded by already-active individual stops.
        worst=book.wallet-intraday_credits+sum(p["quantity"]*(max(float(bars[s][3]),p["stop"])*(1-book.slip)*(1-book.fee)-p["entry"])
                              for s,p in book.positions.items())
        stress_drawdown=max(stress_drawdown,1-worst/peak)
        for s in stopped:
            p=book.positions[s];book.close(s,p["quantity"],p["stop"],now+DAY-2,"stop")
        closing={s:{"bid":float(b[4]),"ask":float(b[4]),"mark":float(b[4])} for s,b in bars.items()}
        book.observe(now+DAY-1,closing)
        for s,p in book.positions.items():
            # Today's high may tighten tomorrow's stop; never stop today's earlier low
            # using information from a high that might have occurred later.
            book.high_watermarks[s]=max(book.high_watermarks.get(s,0),float(bars[s][2]))
        book.record(now+DAY-1);peak=max(peak,book.equity())
    for s,p in list(book.positions.items()):book.close(s,p["quantity"],book.marks[s],days[-1]["time"]+DAY-1,"end_of_data")
    if book.curve:
        book.curve.pop();book.record(days[-1]["time"]+DAY-1)
    result=metrics(book.curve,book.initial_cash)
    by_symbol=defaultdict(float)
    for t in book.closed:by_symbol[t["symbol"]]+=t["pnl"]
    result.update(start=iso(days[0]["time"]),end=iso(days[-1]["time"]+DAY-1),fee_bps=fee_bps,slippage_bps=slippage_bps,
                  leverage_override=leverage_override,round_trips=len(book.closed),fills=sum(e["side"]!="funding" for e in book.events),
                  fees=sum(e.get("fee",0) for e in book.events),funding_net_paid=sum(e.get("payment",0) for e in book.events),
                  intraday_stress_drawdown_pct=stress_drawdown*100,estimated_gap_liquidations=gap_liquidations,
                  withheld_funding_credit_events=funding_bound,missing_held_bars=missing,
                  pnl_by_symbol=dict(sorted(by_symbol.items(),key=lambda item:-item[1])),
                  curve=book.curve,trades=book.closed,events=book.events)
    return result


def benchmark(days):
    """65% initial BTC/ETH perpetual exposure, 1x, actual funding, identical costs."""
    qty={};entry={};wallet=10000;curve=[];cost=.0005;funding=0;fees=0
    for s in ("BTCUSDT","ETHUSDT"):
        entry[s]=float(days[0]["bars"][s][1])*(1+cost)
        qty[s]=3250/entry[s];fees+=3250*cost
    wallet-=fees
    for day in days:
        for s,e in day["funding"]:
            if s in qty and int(e["fundingTime"])>days[0]["time"]+60000:
                paid=qty[s]*float(e["markPrice"])*float(e["fundingRate"]);wallet-=paid;funding+=paid
        equity=wallet+sum(qty[s]*(float(day["bars"][s][4])-entry[s]) for s in qty)
        curve.append({"time":iso(day["time"]+DAY-1),"equity":equity,"gross_pct":sum(qty[s]*float(day["bars"][s][4]) for s in qty)/equity*100})
    exit_drag=sum(qty[s]*float(days[-1]["bars"][s][4])*(1-(1-cost)*(1-cost)) for s in qty)
    curve[-1]["equity"]-=exit_drag
    return metrics(curve,10000)|{"curve":curve,"funding_net_paid":funding,"definition":"BTC 32.5% + ETH 32.5% initial notional; 1x hold; 35% idle collateral"}


def research(output=ROOT/"reports/quant_v3/contracts"):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"app/quant").glob("*.py")}
    plan={"created_before_first_contract_replay":True,"source_hashes":sources,"start":iso(START),"end":iso(END),
          "cases":["base_1x_missing_historical_caps","double_cost","without_zec","one_day_delay","2x_collateral_sensitivity","3x_collateral_sensitivity"],
          "selection_policy":"No parameter search or choosing the best retrospective case for deployment",
          "limitations":["Current liquid universe: survivor and current-volume selection bias", "Historical market caps unavailable: neutral missing-cap score and reduced position limits", "2x/3x collateral cases override the missing-cap leverage guard solely for stress research", "Daily fill and approximate liquidation model, not exchange replay", "Stop-day funding uses a conservative daily cost bound, not exact intraday trade ordering"]}
    # Preserve original protocol on reruns; result hashes describe actual current source.
    if not (output/"replay_protocol.json").exists():atomic_json(output/"replay_protocol.json",plan)
    days,coverage=prepare()
    cases={}
    for name,kwargs in (("base_1x_missing_historical_caps",{}),("double_cost",{"fee_bps":10,"slippage_bps":10}),
                        ("without_zec",{"exclude":["ZECUSDT"]}),("one_day_delay",{"delay_days":1}),
                        ("2x_collateral_sensitivity",{"leverage_override":2}),("3x_collateral_sensitivity",{"leverage_override":3}),
                        ("no_funding_credits",{"allow_funding_credits":False})):
        print("Replay: "+name,flush=True);cases[name]=run(days,**kwargs)
    result={"version":"contracts-v3.1","source_hashes":sources,"coverage":coverage,"cases":cases,"benchmark":benchmark(days),
            "additional_stress_reason":"No-funding-credit diagnostic added after observing material funding contribution; no parameters retuned",
            "protocol":plan,"live_eligible":False,"validated_profitability":False,
            "reason":"Requires historical universe/cap data, exact exchange liquidation modelling and prospective paper evidence"}
    atomic_json(output/"replay.json",result)
    return result
