"""Public Binance data ingestion. HTTP 451 is reported, never bypassed or hidden."""
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.advisory.engine import DAY, iso
from .service import DATA, atomic_json, read
from .universe import COINGECKO_IDS, discover
from .transport import PublicMarketClient
from .snapshot_store import snapshot_lock
from app.core.runtime_config import get_runtime_settings


def fetch(path,params=None):
    with PublicMarketClient() as client:
        return client.get(path,params)


def collect_quotes(directory=DATA):
    endpoints={"tickers":"/fapi/v1/ticker/24hr","book_tickers":"/fapi/v1/ticker/bookTicker",
               "premium_index":"/fapi/v1/premiumIndex"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={name:pool.submit(fetch,path) for name,path in endpoints.items()}
        values={name:future.result() for name,future in pending.items()}
    with snapshot_lock(directory):
        for name,value in values.items():
            atomic_json(Path(directory)/(name+".json"),{"source":"Binance public REST","endpoint":endpoints[name],
                        "retrieved_at":iso(int(time.time()*1000)),"data":value})
    return {"quotes_refreshed":True}


def collect(directory=DATA,output=None,stop_event=None):
    directory=Path(directory)
    endpoints={"exchange_info":"/fapi/v1/exchangeInfo","tickers":"/fapi/v1/ticker/24hr",
               "book_tickers":"/fapi/v1/ticker/bookTicker","premium_index":"/fapi/v1/premiumIndex",
               "funding_info":"/fapi/v1/fundingInfo"}
    metadata={}
    for name,path in endpoints.items():metadata[name]=fetch(path)
    now=max(int(r["time"]) for r in metadata["premium_index"])
    universe=discover(metadata["exchange_info"],metadata["tickers"],metadata["book_tickers"],metadata["premium_index"],now)
    required={r["symbol"] for r in universe if r["volume24_usdt"]>=5_000_000}|{"UNIUSDT","ZECUSDT","SKHYUSDT","SKHYNIXUSDT"}
    config=get_runtime_settings()
    from .policy import load_policy
    required |= set(load_policy(config,output).preferred_symbols)
    periods={"4h":14_400_000,"1h":3_600_000,"15m":900_000}
    missing=[];errors={}
    available={r["symbol"] for r in universe}
    required &= available
    # Always refresh existing positions even if their volume falls below selection floor.
    from .service import FuturesLedger
    required |= set((FuturesLedger(Path(output)/"paper.sqlite3") if output else FuturesLedger()).status()["positions"]) & available
    for symbol in sorted(required):
        for tf,period in periods.items():
            path=directory/"mtf"/tf/(symbol+".json")
            value=read(path) if path.exists() else {}
            closed=[r for r in value.get("rows",[]) if int(r[6])<now]
            if not closed or int(closed[-1][6])!=now//period*period-1: missing.append((symbol,tf))
    staged={};cancelled=threading.Event()
    def fetch_history(client,symbol,tf):
        if cancelled.is_set() or stop_event and stop_event.is_set():
            raise RuntimeError("History collection cancelled")
        try:return client.get("/fapi/v1/klines",{"symbol":symbol,"interval":tf,"limit":config.quant_history_bars,"endTime":now})
        except Exception:
            cancelled.set()
            raise
    with PublicMarketClient() as client, ThreadPoolExecutor(max_workers=config.quant_http_workers) as pool:
        pending={pool.submit(fetch_history,client,symbol,tf):(symbol,tf) for symbol,tf in missing}
        for future in as_completed(pending):
            symbol,tf=pending[future]
            try:
                rows=future.result()
                staged[(symbol,tf)]={"symbol":symbol,"timeframe":tf,"as_of":now,
                    "source":"Binance public REST /fapi/v1/klines","retrieved_at":iso(int(time.time()*1000)),"rows":rows}
            except Exception as exc: errors[symbol+":"+tf]=str(exc)
    if stop_event and stop_event.is_set():return {"cancelled":True}
    # Publish one coherent history generation. Quote observer owns its own snapshot.
    with snapshot_lock(directory):
        for (symbol,tf),value in staged.items():atomic_json(directory/"mtf"/tf/(symbol+".json"),value)
        for name in ("exchange_info","funding_info"):
            atomic_json(directory/(name+".json"),{"source":"Binance public REST","endpoint":endpoints[name],
                        "retrieved_at":iso(int(time.time()*1000)),"data":metadata[name]})
    # The once command also needs fresh quotes; background collector avoids duplicate writes.
    if output is None:collect_quotes(directory)
    cap_error=None
    try:
        url="https://api.coingecko.com/api/v3/coins/markets?"+urlencode({"vs_currency":"usd","ids":",".join(sorted(set(COINGECKO_IDS.values()))),"per_page":250,"page":1,"sparkline":"false"})
        with PublicMarketClient() as client: markets=client.get(url)
        with snapshot_lock(directory):atomic_json(directory/"coingecko_markets.json",{"source":"CoinGecko public /coins/markets","pages":[{"retrieved_at":iso(int(time.time()*1000)),"endpoint":url,"data":markets}]})
    except Exception as exc:cap_error=str(exc)
    result={"required_histories":len(required),"refreshed_histories":len(missing)-len(errors),"history_errors":errors,"market_cap_error":cap_error}
    atomic_json(directory/"collection_status.json",result)
    return result


def collect_funding(status,now):
    ranges={}
    for s,p in status["positions"].items():ranges[s]=max(status.get("funding_cursor",{}).get(s,0),p["opened_at"])
    for debt in status.get("pending_funding_debts",[]):ranges[debt["symbol"]]=min(ranges.get(debt["symbol"],now),debt["start"])
    result={}
    for s,start in ranges.items():
        rows=[];cursor=start+1
        while cursor<=now:
            page=fetch("/fapi/v1/fundingRate",{"symbol":s,"startTime":cursor,"endTime":now,"limit":1000})
            if not isinstance(page,list):raise ValueError("Invalid funding response")
            rows.extend(page)
            if len(page)<1000:break
            next_cursor=int(page[-1]["fundingTime"])+1
            if next_cursor<=cursor:raise ValueError("Funding cursor did not advance")
            cursor=next_cursor
        result[s]={"start":start,"end":now,"complete":True,"events":rows,"source":"Binance public REST"}
    return result
