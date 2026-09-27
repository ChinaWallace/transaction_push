"""Fixed-family research, time-separated selection, and robustness reporting."""

from dataclasses import asdict, replace
from math import sqrt
from statistics import mean, pstdev

from app.advisory.backtest import timestamp
from app.advisory.engine import DAY, iso
from .data import DailyHistory
from .portfolio import QuantBook
from .strategy import FAMILIES, RiskPolicy


def metrics(curve, initial):
    values=[initial]+[p["equity"] for p in curve]
    returns=[b/a-1 if a else 0 for a,b in zip(values,values[1:])]
    days=max(1,len(curve))
    peak=initial
    dd=0
    for v in values:
        peak=max(peak,v)
        dd=max(dd,1-v/peak)
    cagr=(values[-1]/initial)**(365/days)-1 if values[-1]>0 else -1
    volatility=pstdev(returns)*sqrt(365)
    return {"return_pct":(values[-1]/initial-1)*100,"cagr_pct":cagr*100,"max_drawdown_pct":dd*100,
            "annual_vol_pct":volatility*100,"sharpe":mean(returns)*365/volatility if volatility else None,
            "calmar":cagr/dd if dd else None,"final_equity":values[-1],
            "mean_gross_pct":mean(p["gross_pct"] for p in curve) if curve else 0}


def run(history, family, start, end=None, policy=RiskPolicy(), universe=None, delay_days=0, details=False):
    start=timestamp(start) if isinstance(start,str) else start
    end=timestamp(end) if isinstance(end,str) else end or history.as_of
    universe=sorted(universe or history.data)
    reference=[b for b in history.data["BTCUSDT"] if start<=b.open_time<end]
    if not reference:
        raise ValueError("Empty backtest range")
    book=QuantBook(family,policy)
    data_losses=[]
    for ref in reference:
        now=ref.open_time
        bars={s:history.opens[s][now] for s in universe if now in history.opens[s]}
        # A held asset disappearing is not magically sold at its last known price.
        for s in set(book.positions)-set(bars):
            data_losses.append({"symbol":s,"time":iso(now),"assumption":"100_percent_writeoff_no_executable_bar"})
            book.sell(s,book.positions[s]["quantity"],0,now,"missing_bar_writeoff")
        features=history.features(now-delay_days*DAY,universe)
        book.decide(now,features,{s:b.open for s,b in bars.items()})
        book.close_bar(ref.close_time,bars)
    # Close at last available observation, paying exit costs already marked in equity.
    for s,p in list(book.positions.items()):
        book.sell(s,p["quantity"],book.prices[s],reference[-1].close_time,"end_of_data")
    result=metrics(book.curve,book.initial_cash)
    profit=sum(t["pnl"] for t in book.closed if t["pnl"]>0)
    loss=-sum(t["pnl"] for t in book.closed if t["pnl"]<0)
    result.update(family=family,start=iso(reference[0].open_time),end=iso(reference[-1].close_time),
                  policy=asdict(policy),initial_equity=book.initial_cash,universe=universe,
                  fills=len(book.events),round_trips=len(book.closed),
                  win_rate_pct=mean(t["pnl"]>0 for t in book.closed)*100 if book.closed else None,
                  profit_factor=profit/loss if loss else None,
                  median_holding_days=__import__('statistics').median(t["holding_days"] for t in book.closed) if book.closed else None,
                  fees=sum(e["fee"] for e in book.events),
                  turnover=sum(e["quantity"]*e["price"] for e in book.events)/book.initial_cash,
                  pnl_by_symbol={s:sum(e.get("pnl",0) for e in book.events if e["symbol"]==s) for s in universe},
                  data_losses=data_losses)
    if details:
        result.update(events=book.events,curve=book.curve,decisions=book.decisions,trades=book.closed)
    return result


def passive(history,start,end,universe,policy=RiskPolicy()):
    start=timestamp(start) if isinstance(start,str) else start
    end=timestamp(end) if isinstance(end,str) else end
    reference=[b for b in history.data["BTCUSDT"] if start<=b.open_time<end]
    if not reference:
        raise ValueError("Empty benchmark")
    now=reference[0].open_time
    eligible=[s for s in universe if now in history.opens[s] and (f:=history.feature(s,now)) and f["volume20"]>=policy.min_daily_turnover]
    if not eligible:
        raise ValueError("No initially eligible benchmark assets")
    cost=(1+policy.fee_bps/10000)*(1+policy.slippage_bps/10000)
    exit_cost=(1-policy.fee_bps/10000)*(1-policy.slippage_bps/10000)
    qty={s:10000/len(eligible)/(history.opens[s][now].open*cost) for s in eligible}
    values={s:10000/len(eligible) for s in eligible}
    gone=set()
    curve=[]
    for b in reference:
        for s in eligible:
            candle=history.opens[s].get(b.open_time)
            if not candle:
                gone.add(s)
            values[s]=0 if s in gone else qty[s]*candle.close*exit_cost
        curve.append({"equity":sum(values.values()),"gross_pct":100})
    return metrics(curve,10000)|{"symbols":eligible,"missing_written_off":sorted(gone)}


def choose(training):
    valid=[r for r in training if r["cagr_pct"]>0 and r["max_drawdown_pct"]<=50 and r["fills"]>=20]
    return max(valid,key=lambda r:(r["calmar"] or -999,-r["turnover"]))["family"] if valid else None


def research(snapshot,progress=print):
    history=DailyHistory(snapshot)
    policy=RiskPolicy()
    training=[]
    for family in FAMILIES:
        progress("Selection window 2020–2023: "+family)
        training.append(run(history,family,"2020-01-01T00:00:00+00:00","2024-01-01T00:00:00+00:00",policy))
    selected=choose(training)
    progress("Frozen family from selection window: "+str(selected))
    evaluation=[]
    for family in FAMILIES:
        progress("Evaluation 2024 onward: "+family)
        evaluation.append(run(history,family,"2024-01-01T00:00:00+00:00",policy=policy,details=family==selected))
    stress=[]
    if selected:
        for label,p,symbols,delay in (
            ("double_cost",replace(policy,fee_bps=20,slippage_bps=20),list(history.data),0),
            ("without_zec",policy,[s for s in history.data if s!="ZECUSDT"],0),
            ("one_day_delay",policy,list(history.data),1),
            ("lower_risk",replace(policy,target_vol=.60,max_gross=.80),list(history.data),0),
        ):
            progress("Stress: "+label)
            stress.append(run(history,selected,"2024-01-01T00:00:00+00:00",policy=p,universe=symbols,delay_days=delay)|{"case":label})
    years=[]
    for year in range(2020,2027):
        for family in ([selected] if selected else FAMILIES):
            years.append(run(history,family,f"{year}-01-01T00:00:00+00:00",min(history.as_of,timestamp(f"{year+1}-01-01T00:00:00+00:00")),policy)|{"year":year})
    # A separate rolling family-selection diagnostic: each year only sees prior two years.
    rolling=[]
    for year in range(2022,2027):
        train=[run(history,f,f"{year-2}-01-01T00:00:00+00:00",f"{year}-01-01T00:00:00+00:00",policy) for f in FAMILIES]
        winner=choose(train)
        if winner:
            test=run(history,winner,f"{year}-01-01T00:00:00+00:00",min(history.as_of,timestamp(f"{year+1}-01-01T00:00:00+00:00")),policy)
            rolling.append({"year":year,"selected_using_prior_two_years":winner,"result":test})
        else:
            rolling.append({"year":year,"selected_using_prior_two_years":None,"result":{"return_pct":0,"max_drawdown_pct":0}})
    benchmarks={"btc_buy_hold":passive(history,"2024-01-01T00:00:00+00:00",history.as_of,["BTCUSDT"]),
                "initial_eligible_equal_weight":passive(history,"2024-01-01T00:00:00+00:00",history.as_of,list(history.data))}
    chosen=next((r for r in evaluation if r["family"]==selected),None)
    gates={"positive_evaluation_return":bool(chosen and chosen["return_pct"]>0),
           "drawdown_within_user_tolerance":bool(chosen and chosen["max_drawdown_pct"]<=50),
           "double_cost_profitable":any(r["case"]=="double_cost" and r["return_pct"]>0 for r in stress),
           "without_zec_profitable":any(r["case"]=="without_zec" and r["return_pct"]>0 for r in stress)}
    return {"version":"quant-v3.0","as_of":iso(history.as_of),"selected":selected,"selection_window":"2020–2023 only",
            "training":training,"evaluation":evaluation,"stress":stress,"annual":years,"walk_forward":rolling,
            "benchmarks":benchmarks,"data_issues":history.issues,"research_gates":gates,
            "paper_eligible":all(gates.values()),"live_eligible":False,
            "limitations":["Not prospective unseen data: recent prices were known to the researcher",
                           "Fixed universe includes inactive assets but not every historical listing",
                           "Missing held asset is conservatively written down to zero; token migrations not valued",
                           "Daily OHLC costs and close-equity drawdown; not tick-level exchange simulation"]}
