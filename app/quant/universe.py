"""Full Binance USD-M discovery, transparent fundamentals and contract ranking."""

from datetime import datetime
from math import isfinite, log, sqrt
from statistics import mean, median, pstdev

from app.advisory.engine import Candle, DAY, ema, iso

PERPETUAL_TYPES = {"PERPETUAL", "TRADIFI_PERPETUAL"}
# Explicit identity mapping. Unknown/ambiguous tickers never inherit another asset's cap.
COINGECKO_IDS = {
    "BTC":"bitcoin","ETH":"ethereum","BNB":"binancecoin","SOL":"solana","XRP":"ripple",
    "DOGE":"dogecoin","ADA":"cardano","AVAX":"avalanche-2","LINK":"chainlink","LTC":"litecoin",
    "UNI":"uniswap","ZEC":"zcash","OP":"optimism","ARB":"arbitrum","APT":"aptos","NEAR":"near",
    "BCH":"bitcoin-cash","ETC":"ethereum-classic","ATOM":"cosmos","DOT":"polkadot","FIL":"filecoin",
    "AAVE":"aave","ALGO":"algorand","XLM":"stellar","TRX":"tron","SUI":"sui","TON":"the-open-network",
    "INJ":"injective-protocol","PEPE":"pepe","SHIB":"shiba-inu","WIF":"dogwifcoin","HBAR":"hedera-hashgraph",
    "TAO":"bittensor","RENDER":"render-token","FET":"fetch-ai","ICP":"internet-computer","SEI":"sei-network",
    "ENA":"ethena","ONDO":"ondo-finance","WLD":"worldcoin-wld","JUP":"jupiter-exchange-solana",
    "POL":"polygon-ecosystem-token","CRV":"curve-dao-token","LDO":"lido-dao",
    "PENDLE":"pendle","RUNE":"thorchain","QNT":"quant-network","DASH":"dash","XMR":"monero",
    "DYDX":"dydx-chain","IMX":"immutable-x","GALA":"gala","SAND":"the-sandbox","MANA":"decentraland",
    "ZRO":"layerzero","PYTH":"pyth-network","STRK":"starknet","TIA":"celestia","1000PEPE":"pepe",
    "1000SHIB":"shiba-inu","1000BONK":"bonk","BONK":"bonk","TRUMP":"official-trump",
    "NIL":"nillion","ONE":"harmony","SAGA":"saga-2","MUBARAK":"mubarak",
    "AKE":"akedo","MET":"meteora","RAYSOL":"raydium",
}


def unwrap(value):
    return value.get("data",value) if isinstance(value,dict) else value


def discover(info,tickers,books,marks,as_of):
    tickers={r["symbol"]:r for r in unwrap(tickers)}
    books={r["symbol"]:r for r in unwrap(books)}
    marks={r["symbol"]:r for r in unwrap(marks)}
    rows=[]
    for spec in unwrap(info)["symbols"]:
        if spec.get("status")!="TRADING" or spec.get("quoteAsset")!="USDT" or spec.get("contractType") not in PERPETUAL_TYPES:
            continue
        s=spec["symbol"]
        t,b,m=tickers.get(s,{}),books.get(s,{}),marks.get(s,{})
        reasons=[]
        try:
            bid,ask,mark,index=map(float,(b["bidPrice"],b["askPrice"],m["markPrice"],m["indexPrice"]))
            volume=float(t["quoteVolume"])
            spread=(ask-bid)/((ask+bid)/2)*10000
            if not all(isfinite(x) and x>0 for x in (bid,ask,mark,index,volume)) or ask<bid:
                raise ValueError("invalid_quote")
            if any(abs(as_of-int(v))>180000 for v in (b["time"],m["time"],t["closeTime"])):
                reasons.append("stale_quote")
            if volume<5_000_000:reasons.append("turnover_below_5m")
            if spread>20:reasons.append("spread_above_20bps")
            if abs(mark/index-1)>.02:reasons.append("mark_index_basis_above_2pct")
        except (KeyError,ValueError,TypeError,ZeroDivisionError):
            bid=ask=mark=index=volume=spread=0
            reasons.append("missing_or_invalid_quote")
        age=(as_of-int(spec.get("onboardDate",as_of)))/DAY
        if age<30:reasons.append("listing_under_30_days_research_only")
        try:
            funding=float(m["lastFundingRate"])
            funding_known=isfinite(funding)
        except (KeyError,TypeError,ValueError):
            funding=0;funding_known=False
        rows.append({"symbol":s,"base_asset":spec["baseAsset"],"contract_type":spec["contractType"],
                     "asset_class":spec.get("underlyingType","UNKNOWN"),"tags":spec.get("underlyingSubType",[]),
                     "age_days":round(age,1),"volume24_usdt":volume,"bid":bid,"ask":ask,"mark":mark,"index":index,
                     "spread_bps":spread,"funding_rate":funding if funding_known else 0,
                     "funding_known":funding_known,"next_funding_time":m.get("nextFundingTime"),
                     "quote_time":m.get("time"),"book_time":b.get("time"),"ticker_time":t.get("closeTime"),
                     "filters":spec.get("filters",[]),"rejections":reasons})
    return rows


def contract_features(rows,as_of):
    bars=[Candle.from_binance(r) for r in rows if int(r[6])<as_of]
    if len(bars)<30:
        raise ValueError("fewer_than_30_closed_days")
    bars=bars[-201:]
    if bars[-1].close_time!=as_of//DAY*DAY-1:
        raise ValueError("stale_daily_bars")
    for i,b in enumerate(bars):
        if (not all(isfinite(x) for x in (b.open,b.high,b.low,b.close,b.volume,b.quote_volume))
                or not 0<b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high
                or b.quote_volume<0 or b.volume<0 or b.open_time%DAY or b.close_time!=b.open_time+DAY-1
                or i and b.open_time-bars[i-1].open_time!=DAY):
            raise ValueError("invalid_or_gapped_daily_bars")
    close=[b.close for b in bars]
    atr=mean(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(bars[-15:-1],bars[-14:]))
    if atr<=0:raise ValueError("zero_volatility")
    returns=[log(b/a) for a,b in zip(close[-31:-1],close[-30:])]
    e20=ema(close,20)
    e50=ema(close,min(50,len(close)))
    lookbacks=(7,20,60,120)
    available=[n for n in lookbacks if n<len(close)]
    momenta={f"return{n}":close[-1]/close[-n-1]-1 if n in available else None for n in lookbacks}
    score=mean(log(1+momenta[f"return{n}"])*sqrt(30/n) for n in available)
    vol=max(.1,pstdev(returns)*sqrt(365))
    return {"closed_at":bars[-1].close_time,"bars":len(bars),"close":close[-1],"atr":atr,
            "ema20":e20[-1],"ema50":e50[-1],"ema20_rising":e20[-1]>e20[-4],
            "annual_vol":vol,"momentum_score":score/sqrt(vol),"returns30":returns,"momentum_windows":available,
            "trend":sum((close[-1]>e20[-1],close[-1]>e50[-1],e20[-1]>e20[-4],momenta["return20"]>0))/4,
            "median_volume20":median(b.quote_volume for b in bars[-20:]),"volume":bars[-1].quote_volume,
            "high20":max(b.high for b in bars[-20:]),"prior_high20":max(b.high for b in bars[-21:-1]),
            "low10":min(b.low for b in bars[-10:]),**momenta}


def market_cap(row,markets,as_of=None):
    identifier=COINGECKO_IDS.get(row["base_asset"])
    match=next((r for r in markets if r.get("id")==identifier),None) if identifier else None
    if row["asset_class"]!="COIN":
        return {"value_usd":None,"status":"underlying_equity_or_asset_valuation_not_available"}
    if not match or not match.get("market_cap"):
        return {"value_usd":None,"status":"identity_or_market_cap_unavailable"}
    if as_of is not None:
        try:
            observed=datetime.fromisoformat(match["last_updated"].replace("Z","+00:00")).timestamp()*1000
            if not 0<=as_of-observed<=DAY:
                return {"value_usd":None,"status":"market_cap_not_point_in_time_or_stale"}
        except (KeyError,ValueError,TypeError):
            return {"value_usd":None,"status":"market_cap_timestamp_missing"}
    return {"value_usd":match["market_cap"],"id":identifier,"source":"CoinGecko /coins/markets",
            "observed_at":match.get("last_updated"),"status":"explicit_id_mapping",
            "fdv_usd":match.get("fully_diluted_valuation")}


def correlation(a,b):
    n=min(len(a),len(b));a=a[-n:];b=b[-n:]
    sa,sb=pstdev(a),pstdev(b)
    ma,mb=mean(a),mean(b)
    return mean((x-ma)*(y-mb) for x,y in zip(a,b))/(sa*sb) if sa*sb else 1


def rank_contracts(universe,histories,markets,as_of,max_leverage=3,funding_intervals=None,features_override=None):
    if not 1<=max_leverage<=3:raise ValueError("Leverage must be between 1 and 3")
    rows=[]
    for original in universe:
        row={**original,"market_cap":market_cap(original,markets,as_of)}
        row["rejections"]=list(original["rejections"])
        if row["symbol"] not in histories:
            row["action"]="excluded" if row["rejections"] else "data_unavailable"
            rows.append(row);continue
        try:
            row["features"]=(features_override[row["symbol"]] if features_override is not None
                             else contract_features(histories[row["symbol"]],as_of))
        except ValueError as exc:
            row["rejections"].append(str(exc));row["action"]="data_unavailable";rows.append(row);continue
        f=row["features"]
        if f["median_volume20"]<3_000_000:row["rejections"].append("persistent_turnover_below_3m")
        # Funding interval is contract-specific; missing information is explicit.
        interval=(funding_intervals or {}).get(row["symbol"],8)
        if not isinstance(interval,(int,float)) or interval<=0 or interval>24:
            row["rejections"].append("invalid_funding_interval");interval=8
        row["funding_interval_hours"]=interval
        row["estimated_daily_funding_pct"]=row["funding_rate"]*24/interval*100
        if not row["funding_known"]:row["rejections"].append("funding_unavailable")
        if row["estimated_daily_funding_pct"]>.15:row["rejections"].append("long_carry_above_0_15pct_daily")
        row["action"]="excluded" if row["rejections"] else "candidate"
        rows.append(row)
    technical=[r for r in rows if "features" in r]
    for row in technical:
        f=row["features"]
        cohort=[r for r in technical if (r["asset_class"]=="COIN")== (row["asset_class"]=="COIN")]
        pct=lambda key:sum(r[key]<=row[key] for r in cohort)/max(1,len(cohort))
        momentum_pct=sum(r["features"]["momentum_score"]<=f["momentum_score"] for r in cohort)/max(1,len(cohort))
        cap=row["market_cap"]["value_usd"]
        cap_score=min(1,max(0,(log(cap)/log(10)-7)/3)) if cap else .25
        carry=max(0,min(1,1-max(0,row["estimated_daily_funding_pct"])/.15))
        row["score_components"]={"relative_momentum":40*momentum_pct,"trend":25*f["trend"],
                                 "liquidity":15*pct("volume24_usdt"),"market_cap_quality":10*cap_score,"carry":10*carry}
        row["selection_score"]=round(sum(row["score_components"].values()),2)
        row["history_class"]="seasoned" if f["bars"]>=120 else "young"
        if row["action"]=="candidate":
            if f["trend"]<.75 or f["return20"]<=0:row["action"]="wait_trend"
            elif row["selection_score"]<65:row["action"]="below_rank_threshold"
            elif row["ask"]>f["close"]+1.5*f["atr"]:row["action"]="wait_pullback"
        stop=max(f["close"]-4*f["atr"],f["close"]*.78)
        row["entry_zone"]=[f["close"]-f["atr"],f["close"]+1.5*f["atr"]]
        row["stop_price"]=stop
        row["exit_rule"]="4 ATR initial risk capped at 22%; rising 5 ATR chandelier; trend/rank exit; no fixed profit cap"
        row["hold_eligible"]=not row["rejections"] and f["trend"]>=.5 and f["close"]>f["ema50"] and row["selection_score"]>=50
        # Unknown fundamental identity, young contracts, and TradFi start at 1x.
        row["leverage"]=min(max_leverage,3 if f["annual_vol"]<1 else 2 if f["annual_vol"]<2 else 1)
        if f["atr"]/f["close"]>.12:row["leverage"]=1
        if f["bars"]<90 or not cap or row["asset_class"]!="COIN":row["leverage"]=1
        # Leave distance to liquidation; not a replacement for exchange brackets.
        if not row["rejections"] and row["ask"]>0:
            if row["ask"]<=stop:
                row["action"]="current_price_below_stop";row["hold_eligible"]=False
            elif (row["ask"]-stop)/row["ask"]>.8/row["leverage"]:
                row["action"]="stop_too_close_to_liquidation";row["hold_eligible"]=False
        if any(x in row["symbol"] for x in ("2LUSDT","3LUSDT","2SUSDT","3SUSDT")):
            row["action"]="underlying_leverage_requires_review"
            row["hold_eligible"]=False
    rows.sort(key=lambda r:(-r.get("selection_score",-1),r["symbol"]))
    return rows


def target_portfolio(ranking,capital=10000,held_symbols=(),max_positions=6,position_risk=.045,allow_waiting=False):
    if not 1<=max_positions<=50 or not 0<position_risk<=.045:raise ValueError("Invalid portfolio policy")
    chosen=[];weights={};margin=0;risks=0
    issuers=set();decisions={}
    ordered=sorted(ranking,key=lambda r:(r["symbol"] not in held_symbols,-r.get("selection_score",-1)))
    for row in ordered:
        retained=row["symbol"] in held_symbols and row.get("hold_eligible",False)
        if row["action"] not in ({"candidate","wait_pullback"} if allow_waiting else {"candidate"}) and not retained:
            decisions[row["symbol"]]=row["action"];continue
        if len(chosen)>=max_positions:decisions[row["symbol"]]="position_limit";continue
        issuer="SK_HYNIX" if "SKHY" in row["symbol"] else row["base_asset"]
        if issuer in issuers:decisions[row["symbol"]]="same_issuer";continue
        if any(correlation(row["features"]["returns30"],r["features"]["returns30"])>.90 for r in chosen):
            decisions[row["symbol"]]="high_correlation";continue
        f=row["features"]
        stop_distance=(row["ask"]-row["stop_price"])/row["ask"]
        if stop_distance<=0:continue
        weight=min(.35,position_risk/stop_distance,.35/max(f.get("annual_vol",1),.1))
        if row["history_class"]=="young":weight=min(weight,.12)
        if row["market_cap"]["value_usd"] is None:weight=min(weight,.15)
        weight=min(weight,max(0,1.8-sum(weights.values())),max(0,(.65-margin)*row["leverage"]),max(0,(.25-risks)/stop_distance))
        if weight<.025:decisions[row["symbol"]]="risk_budget";continue
        chosen.append(row);issuers.add(issuer);weights[row["symbol"]]=weight
        decisions[row["symbol"]]="retained" if retained else "selected"
        margin+=weight/row["leverage"];risks+=weight*stop_distance
    if weights:
        n=min(len(r["features"]["returns30"]) for r in chosen)
        synthetic=[sum(weights[r["symbol"]]*r["features"]["returns30"][-n+i] for r in chosen) for i in range(n)]
        vol=pstdev(synthetic)*sqrt(chosen[0]["features"].get("annualization_periods",365))
        scale=min(1,.8/max(vol,.01))
        weights={s:w*scale for s,w in weights.items()};margin*=scale;risks*=scale
    return {"targets":[{"symbol":r["symbol"],"pair":r["base_asset"]+"/USDT:USDT","weight":weights[r["symbol"]],
                         "notional_usdt":capital*weights[r["symbol"]],"margin_usdt":capital*weights[r["symbol"]]/r["leverage"],
                         "leverage":r["leverage"],"stop_price":r["stop_price"],"entry_zone":r["entry_zone"],
                         "atr":r["features"]["atr"],"closed_price":r["features"]["close"],
                         "asset_class":r["asset_class"],"score":r["selection_score"]} for r in chosen],
            "gross_exposure":sum(weights.values()),"margin_fraction":margin,"planned_stop_risk":risks,
            "max_positions":max_positions,"position_risk_budget":position_risk,"selection_decisions":decisions,
            "max_allowed_drawdown":.5,"hard_drawdown_trigger":.45,"max_allowed_leverage":3,
            "live_eligible":False,"mode":"research_paper"}
