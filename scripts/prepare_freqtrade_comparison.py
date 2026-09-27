#!/usr/bin/env python3
"""Convert verified public research data to isolated Freqtrade files (no network)."""
import hashlib
import json
from pathlib import Path

import pandas as pd
from freqtrade.data.history import get_datahandler
from freqtrade.enums import CandleType
from freqtrade.exchange.exchange import Exchange

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"reports/quant_v5/data"
DEST=ROOT/"reports/quant_v5/freqtrade_data"
START=1767225600000
END=1790208000000


def candles(path):
    rows=json.loads(path.read_text())["rows"]
    frame=pd.DataFrame([[r[0],*map(float,r[1:6])] for r in rows],columns=["date","open","high","low","close","volume"])
    frame["date"]=pd.to_datetime(frame.date,unit="ms",utc=True)
    return frame


def main():
    if not (SOURCE/"warmup_manifest.json").exists():raise SystemExit("Native informative warmup is not ready")
    DEST.mkdir(parents=True,exist_ok=True)
    handler=get_datahandler(DEST,"feather")
    result={"sources":{},"symbols":{},"funding_convention":"Actual event rates and event mark prices; exchange settlement jitter below 60s normalized to scheduled hour; no missing events filled with zero."}
    for symbol in ("BTCUSDT","ETHUSDT","ZECUSDT"):
        pair=symbol.removesuffix("USDT")+"/USDT:USDT"
        for tf in ("5m","15m","1h","4h","1d"):
            kind="klines_warmup" if tf in {"1h","4h","1d"} else "klines"
            path=SOURCE/"series"/kind/tf/(symbol+".json")
            frame=candles(path)
            result["sources"][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
            handler.ohlcv_store(pair,tf,frame,CandleType.FUTURES)
        path=SOURCE/"series/markPriceKlines/1h"/(symbol+".json")
        mark=candles(path).set_index("date")
        raw=ROOT/"reports/quant_v3/futures_replay/funding/symbols"/(symbol+".json")
        value=json.loads(raw.read_text())
        if not value["validation"]["complete"] or value["validation"]["errors"]:raise ValueError("Incomplete funding")
        events=[e for e in value["rates"] if START<=int(e["fundingTime"])<END]
        items=[];jitters=[]
        for e in events:
            at=int(e["fundingTime"]);hour=at//3_600_000*3_600_000
            if at-hour>=60_000:raise ValueError("Funding not near its scheduled hour")
            dt=pd.to_datetime(hour,unit="ms",utc=True)
            if dt not in mark.index:raise ValueError("Missing mark at funding event")
            # Use the true settlement mark, not a later or approximate hourly price.
            price=float(e["markPrice"])
            mark.loc[dt,"open"]=price
            mark.loc[dt,"high"]=max(mark.loc[dt,"high"],price)
            mark.loc[dt,"low"]=min(mark.loc[dt,"low"],price)
            items.append([dt,float(e["fundingRate"])])
            jitters.append(at-hour)
        funding=pd.DataFrame(items,columns=["date","funding_rate"])
        if funding.date.duplicated().any():raise ValueError("Ambiguous funding schedule")
        combined=Exchange.combine_funding_and_mark(funding,mark.reset_index())
        if len(combined)!=len(events):raise ValueError("Funding silently dropped by Freqtrade join")
        handler.ohlcv_store(pair,"1h",funding,CandleType.FUNDING_RATE)
        handler.ohlcv_store(pair,"1h",mark.reset_index(),CandleType.MARK)
        result["sources"][str(raw.relative_to(ROOT))]=hashlib.sha256(raw.read_bytes()).hexdigest()
        result["sources"][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        result["symbols"][symbol]={"funding_events":len(events),"funding_events_joined":len(combined),"max_settlement_jitter_ms":max(jitters)}
        print(symbol,result["symbols"][symbol],flush=True)
    result["output_hashes"]={str(p.relative_to(DEST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in DEST.rglob("*.feather")}
    (DEST/"manifest.json").write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":main()
