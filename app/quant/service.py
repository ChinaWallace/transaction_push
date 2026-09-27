"""Snapshot-based contract research, plans, and transactionally persisted paper execution."""

import hashlib
import json
import sqlite3
import time
import tempfile
from math import isfinite
from collections import Counter
from contextlib import closing
from pathlib import Path

from app.advisory.engine import DAY, iso
from .futures_book import FuturesBook
from .universe import discover, rank_contracts, target_portfolio, unwrap

from app.core.runtime_config import PROJECT_ROOT, get_runtime_settings
ROOT=PROJECT_ROOT
DATA=get_runtime_settings().quant_data_dir
OUTPUT=get_runtime_settings().quant_output_dir
VERSION="contracts-v3.2"


def read(path):
    return json.loads(Path(path).read_text())


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,prefix=path.name+".",suffix=".tmp",delete=False) as handle:
        handle.write(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
        temporary=Path(handle.name)
    temporary.replace(path)


def funding_coverage_valid(coverage,start,end):
    if not coverage.get("complete") or coverage.get("start",end+1)>start or coverage.get("end",0)<end:return False
    try:
        events=[e for e in coverage.get("events",[]) if start<int(e["fundingTime"])<=end]
        times=[int(e["fundingTime"]) for e in events]
        return len(times)==len(set(times)) and all(isfinite(float(e["fundingRate"])) and
                isfinite(float(e["markPrice"])) and float(e["markPrice"])>0 for e in events)
    except (KeyError,ValueError,TypeError):return False


def load_snapshot(directory=DATA, multiframe=False):
    from .snapshot_store import snapshot_lock
    with snapshot_lock(directory,shared=True):
        return _load_snapshot(directory,multiframe)


def _load_snapshot(directory=DATA, multiframe=False):
    directory=Path(directory)
    names=("exchange_info","tickers","book_tickers","premium_index","funding_info")
    result={name:read(directory/(name+".json")) for name in names}
    result["as_of"]=max(int(r["time"]) for r in unwrap(result["premium_index"]))
    result["histories"]={} if multiframe else {p.stem:read(p)["rows"] for p in (directory/"klines").glob("*.json")}
    if multiframe:
        result["multiframe_histories"]={}
        for tf in ("4h","1h","15m"):
            for p in (directory/"mtf"/tf).glob("*.json"):
                result["multiframe_histories"].setdefault(p.stem,{})[tf]=read(p)["rows"]
    cap_path=directory/"coingecko_markets.json"
    caps=read(cap_path) if cap_path.exists() else {}
    result["market_caps"]=[r for page in caps.get("pages",[]) for r in page.get("data",[])]
    result["source_hashes"]={name:hashlib.sha256((directory/(name+".json")).read_bytes()).hexdigest() for name in names}
    return result


def build_report(snapshot,capital=10000,held_symbols=(),max_leverage=3,active_plan=None,policy=None,rules=None,ranking_override=None):
    now=snapshot["as_of"]
    universe=discover(snapshot["exchange_info"],snapshot["tickers"],snapshot["book_tickers"],snapshot["premium_index"],now)
    intervals={r["symbol"]:r["fundingIntervalHours"] for r in unwrap(snapshot["funding_info"])}
    mtf="multiframe_histories" in snapshot
    version=VERSION
    if ranking_override is not None:
        from .multiframe import VERSION as version
        ranking=ranking_override
    elif mtf:
        from .multiframe import rank_multiframe, VERSION as version
        ranking=rank_multiframe(universe,snapshot["multiframe_histories"],snapshot["market_caps"],now,max_leverage,intervals)
    else:
        ranking=rank_contracts(universe,snapshot["histories"],snapshot["market_caps"],now,max_leverage,intervals)
    config=get_runtime_settings()
    if rules and mtf:
        from .strategy_rules import apply_rules
        ranking=apply_rules(ranking,rules,policy.preferred_symbols if policy else ())
    if policy and mtf:
        from .policy import candidate_pool, apply_allocations, summarize_allocations
        pool={r["symbol"] for r in candidate_pool(ranking,policy)}
    else:pool={r["symbol"] for r in ranking}
    selection=[dict(r,action="wait_pullback") if r["action"] in {"wait_1h_confirmation","wait_15m_trigger"} else r for r in ranking]
    selection=[r for r in selection if r["symbol"] in pool and (not policy or r["symbol"] not in policy.preferred_symbols)]
    plan=target_portfolio(selection,capital,held_symbols,max_positions=policy.max_positions if policy else config.quant_max_positions,
                          position_risk=config.quant_position_risk,allow_waiting=True)
    # One rebalance per UTC day; quote-only steps still execute stops/funding.
    period=14_400_000 if mtf else DAY
    signal_id=f"{version}:{now//period}:{max_leverage}"
    if rules and mtf:signal_id+=":"+rules.revision()
    if policy and mtf:
        signal_id+=":"+policy.revision()
        apply_allocations(plan,ranking,policy,capital)
    if active_plan and active_plan.get("signal_id")==signal_id:
        plan={**active_plan}
    plan["execution_policy"]="multiframe_rotation" if mtf else "daily_rebalance_intraday_entry"
    plan["entry_allowed_symbols"]=[r["symbol"] for r in ranking if r["action"]=="candidate"]
    plan["invalidated_symbols"]=[r["symbol"] for r in ranking if r["action"] in
                                  {"wait_trend","below_rank_threshold","current_price_below_stop","underlying_leverage_requires_review"}]
    plan["signal_expires_at"]=(now//period+1)*period
    plan.update(version=version,signal_id=signal_id,created_at=now,valid_until=now+30*60*1000,
                closed_daily_signal_at=now//DAY*DAY-1,capital_reference=capital)
    if mtf:
        plan.pop("closed_daily_signal_at",None)
        plan.update(timeframes={"selection":"4h","confirmation":"1h","execution":"15m"},
                    closed_selection_at=now//period*period-1, cooldown_ms=3_600_000, max_hold_ms=72*3_600_000,
                    trailing_atr_multiplier=3, strategy_schema=4,
                    signal_evidence={r["symbol"]:r["signal"] for r in ranking if "signal" in r},
                    protective_updates={r["symbol"]:{"atr":r["features"]["atr"],"stop_price":r["stop_price"],"closed_at":r["signal"]["execution_closed_at"]}
                                        for r in ranking if "signal" in r},
                    exit_signals={r["symbol"]:("hourly_trend_exit" if r["signal"]["exit_1h"] else "15m_structure_exit")
                                  for r in ranking if "signal" in r and (r["signal"]["exit_1h"] or r["signal"]["exit_15m"])})
        if rules:
            from dataclasses import asdict
            plan.update(strategy_rules=asdict(rules),max_hold_ms=rules.max_hold_hours*3_600_000,
                        retain_until_exit=rules.retain_until_exit)
            if rules.exit_timeframe=="4h":
                plan["exit_signals"]={s:("four_hour_trend_exit" if reason=="hourly_trend_exit" else reason) for s,reason in plan["exit_signals"].items()}
        # Preserve the 4h membership/weight but update 15m entry bounds and 1h ATR.
        lookup={r["symbol"]:r for r in ranking if "signal" in r}
        plan["targets"]=[{**t,**({"entry_zone":lookup[t["symbol"]]["entry_zone"],"stop_price":t["stop_price"] if t.get("holding_policy")=="core" else lookup[t["symbol"]]["stop_price"],
                               "atr":lookup[t["symbol"]]["features"]["atr"]} if t["symbol"] in lookup else {})} for t in plan["targets"]]
        plan["planned_stop_risk"]=sum(t["weight"]*max(0,1-t["stop_price"]/lookup[t["symbol"]]["ask"])
                                       for t in plan["targets"] if t["symbol"] in lookup and lookup[t["symbol"]]["ask"]>0)
        if policy:summarize_allocations(plan,ranking)
    eligible={r["symbol"] for r in universe if not r["rejections"]}
    histories=snapshot["multiframe_histories"] if mtf else snapshot["histories"]
    missing=sorted(eligible-set(histories))
    plan["complete"]=not missing and all(r.get("action")!="data_unavailable" for r in ranking if r["symbol"] in eligible)
    plan["research_status"]="experimental_unvalidated_current_universe"
    current=int(time.time()*1000)
    return {"version":version,"as_of":iso(now),"snapshot_time":now,"generated_at":iso(current),
            "quote_age_seconds":max(0,(current-now)/1000),"snapshot_fresh":0<=current-now<=180000,
            "scope":"All TRADING Binance USD-M USDT PERPETUAL and TRADIFI_PERPETUAL contracts",
            "coverage":{"contracts":len(universe),"by_contract_type":dict(Counter(r["contract_type"] for r in universe)),
                        "by_asset_class":dict(Counter(r["asset_class"] for r in universe)),"histories":len(histories),"timeframes":["4h","1h","15m"] if mtf else ["1d"],
                        "market_caps_verified":sum(r["market_cap"]["value_usd"] is not None for r in ranking),
                        "actions":dict(Counter(r["action"] for r in ranking)),"missing_eligible_histories":missing},
            "plan":plan,"ranking":ranking,"source_hashes":snapshot.get("source_hashes",{}),
            "limitations":["USDT settlement only; USDC and COIN-M contracts are not pooled into this USDT account",
                "Market caps use explicit identities and timestamps; missing valuations remain null, not zero",
                "TradFi includes stock/ADR/index/commodity exposures, not ownership of the underlying assets",
                "Current liquid universe has survivor and selection bias in retrospective research",
                "30-day history minimum; younger listings are tracked but not bought",
                "45% drawdown exit trigger is not a guarantee against gaps exceeding 50%",
                "Long-only trend rotation; no validated short-selling strategy yet; live execution disabled"]}


def report_markdown(report):
    coverage=report["coverage"];plan=report["plan"]
    lines=["# 币安合约全池研究与模拟组合",f"策略 {report['version']}；快照 {report['as_of']}；模式：模拟",
           f"覆盖 {coverage['contracts']} 个 USDT 永续，{coverage['histories']} 个有历史缓存，{coverage['market_caps_verified']} 个市值身份匹配。",
           "周期：4h选币 / 1h确认 / 15m入场退出；每4h冻结组合，每分钟检查保护止损。" if plan.get("strategy_schema")==4 else "旧日线策略快照。",
           "评分：相对动量40 + 趋势25 + 成交额15 + 市值10 + 资金费10；评分不是上涨概率。",
           "", "| 模拟目标 | 评分 | 杠杆 | 名义仓位/权益 | 入场区间 | 初始止损 |", "|---|---:|---:|---:|---:|---:|"]
    for t in plan["targets"]:
        lines.append(f"| {t['symbol']} | {t['score']:.2f} | {t['leverage']}x | {t['weight']:.1%} | {t['entry_zone'][0]:.6g}–{t['entry_zone'][1]:.6g} | {t['stop_price']:.6g} |")
    lines += ["",f"总敞口 {plan['gross_exposure']:.1%}；保证金 {plan['margin_fraction']:.1%}；计划止损风险 {plan['planned_stop_risk']:.1%}。",
              "未知市值、年轻合约降低仓位；股票标的估值未接入；合约池存在幸存偏差。",
              "v4：1h EMA20>EMA50且上行，15m放量突破20根前高或回踩EMA20收复；2.5倍1h ATR初始止损（至多10%价格距离），3倍1h ATR追踪。",
              "1h失守EMA50或15m跌破前10根低点退出；72h时间退出；止损/信号退出冷却1h。",
              "最多3倍杠杆，45%回撤退出暂停28天；跳空可能超过50%容忍线。旧日线收益不代表多周期策略业绩。"]
    return "\n".join(lines)+"\n"


class FuturesLedger:
    def __init__(self,path=OUTPUT/"paper.sqlite3",capital=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.capital=capital or get_runtime_settings().quant_initial_capital

    def _connect(self):
        conn=sqlite3.connect(self.path,timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS cycles (id INTEGER PRIMARY KEY, at INTEGER, status TEXT, payload TEXT)")
        return conn

    def status(self):
        with closing(self._connect()) as conn, conn:
            row=conn.execute("SELECT state FROM account WHERE id=1").fetchone()
            book=FuturesBook.restore(json.loads(row[0])) if row else FuturesBook(self.capital)
            cycles=conn.execute("SELECT at,payload FROM cycles ORDER BY id DESC LIMIT 2").fetchall()
            last=json.loads(cycles[0][1]) if cycles else None
            if last is not None and len(cycles)>1:
                gap=max(0,(cycles[0][0]-cycles[1][0])/1000)
                last.setdefault("observation_gap_seconds",gap)
                last.setdefault("unobserved_stop_interval",gap>300)
        positions={s:{**p,"mark":book.marks[s],"unrealized_pnl":p["quantity"]*(book.marks[s]-p["entry"]),
                      "notional":p["quantity"]*book.marks[s]} for s,p in book.positions.items()}
        return {"equity":book.equity(),"wallet":book.wallet,"margin":book.margin(),"positions":positions,
                "initial_capital":book.initial_cash,"gross":book.gross(),"active_plan":book.active_plan,
                "last_decisions":book.last_decisions,"started_at":book.events[0]["time"] if book.events else None,
                "net_return_pct":(book.equity()/book.initial_cash-1)*100,
                "funding_cursor":book.funding_cursor,"pending_funding_debts":book.funding_debts,
                "last_plan":book.last_plan,"last_cycle":last,"mode":"paper","live":False}

    def history(self,limit=100,before=None):
        limit=max(1,min(int(limit),500))
        with closing(self._connect()) as conn, conn:
            row=conn.execute("SELECT state FROM account WHERE id=1").fetchone()
            book=FuturesBook.restore(json.loads(row[0])) if row else FuturesBook(self.capital)
            cycles=conn.execute("SELECT at,status,payload FROM cycles ORDER BY id DESC LIMIT 20").fetchall()
            gap_count=conn.execute("SELECT COUNT(*) FROM (SELECT at-LAG(at) OVER (ORDER BY id) gap FROM cycles) WHERE gap>300000").fetchone()[0]
        end=min(len(book.events),max(0,before-1)) if before is not None else len(book.events)
        start=max(0,end-limit)
        events=[dict(book.events[i],id=i+1) for i in range(end-1,start-1,-1)]
        from datetime import datetime
        segmented=[];segment=0;previous=None
        for point in book.curve:
            at=datetime.fromisoformat(point["time"]).timestamp()
            if previous is not None and (at-previous>300 or point.get("valuation_complete") is False):segment+=1
            segmented.append(dict(point,segment=segment));previous=at
        stride=max(1,len(segmented)//600)
        curve=segmented[::stride]
        if segmented and (not curve or curve[-1]!=segmented[-1]):curve.append(segmented[-1])
        return {"events":events,"total_events":len(book.events),"next_before":start+1 if start else None,
                "closed_trades":list(reversed(book.closed[-100:])),"curve":curve,"curve_points_total":len(book.curve),
                "recorded_observation_gaps":gap_count,"cycles":[{"at":iso(at),"status":status,
                    "fills_total":json.loads(payload).get("fills_total"),"valuation_complete":json.loads(payload).get("valuation_complete")} for at,status,payload in cycles]}

    def step(self,report,now=None,funding=None):
        wall_now=int(time.time()*1000)
        if now is None and funding:
            # Imported funding and quotes can share a captured decision cutoff.
            # Only accept a recent cutoff after every supplied quote, never invent
            # coverage for the milliseconds that elapsed during asynchronous I/O.
            cutoff=min(int(v.get("end",0)) for v in funding.values())
            newest_quote=max((int(r.get(k) or 0) for r in report["ranking"] for k in ("quote_time","book_time")),default=0)
            if 0<=wall_now-cutoff<=180000 and cutoff>=newest_quote:now=cutoff
        now=now or wall_now;plan=report["plan"]
        # Never execute imported historical quotes as if they were current.
        quotes={r["symbol"]:{"bid":r["bid"],"ask":r["ask"],"mark":r["mark"]} for r in report["ranking"]
                if r["mark"]>0 and r["bid"]>0 and r["ask"]>=r["bid"]
                and all(0<=now-int(r.get(k) or 0)<=180000 for k in ("quote_time","book_time"))
                and "stale_quote" not in r["rejections"]}
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT state FROM account WHERE id=1").fetchone()
            book=FuturesBook.restore(json.loads(row[0])) if row else FuturesBook(self.capital)
            previous_observation=book.last_time
            missing_funding=[]
            # Coverage envelopes are mandatory, including empty intervals. Persist a cursor
            # at each quantity change; a later event is never charged against a newer quantity.
            remaining_debts=[]
            for debt in book.funding_debts:
                coverage=(funding or {}).get(debt["symbol"],{})
                if not funding_coverage_valid(coverage,debt["start"],debt["end"]):
                    remaining_debts.append(debt);continue
                for event in coverage.get("events",[]):
                    at=int(event["fundingTime"]);key=f"{debt['symbol']}:{at}"
                    if not debt["start"]<at<=debt["end"] or key in book.processed_funding:continue
                    payment=debt["quantity"]*float(event["markPrice"])*float(event["fundingRate"])
                    book.wallet-=payment;book.processed_funding.add(key)
                    book.events.append({"time":iso(at),"symbol":debt["symbol"],"side":"funding","payment":payment,"reason":"late_settlement_after_exit"})
                    for trade in book.closed:
                        if trade["symbol"]==debt["symbol"] and trade["entry_time"]==iso(debt["opened_at"]):trade["pnl"]-=payment
            book.funding_debts=remaining_debts
            unsettled={}
            for s,p in list(book.positions.items()):
                coverage=(funding or {}).get(s,{})
                start=coverage.get("start",now+1);end=coverage.get("end",0)
                cursor=max(book.funding_cursor.get(s,0),p["opened_at"])
                if not funding_coverage_valid(coverage,cursor,now):
                    unsettled[s]={"symbol":s,"start":cursor,"end":now,"quantity":p["quantity"],"opened_at":p["opened_at"]}
                    missing_funding.append(s);continue
                for event in sorted(coverage.get("events",[]),key=lambda e:e["fundingTime"]):
                    at=int(event["fundingTime"])
                    if cursor<at<=now:
                        book.funding(s,at,float(event["fundingRate"]),float(event["markPrice"]))
                book.funding_cursor[s]=now
            fresh=0<=now-plan["created_at"]<=30*60*1000 and now<=plan["valid_until"]
            if plan.get("strategy_schema")==4:
                evidence_times=[v.get("execution_closed_at",0) for v in plan.get("signal_evidence",{}).values()]
                signal_fresh=fresh and all(t==now//900_000*900_000-1 for t in evidence_times)
                if not signal_fresh:
                    plan={**plan,"exit_signals":{},"protective_updates":{},"entry_allowed_symbols":[]}
                fresh=fresh and signal_fresh
            complete=bool(plan.get("complete") and fresh and not missing_funding and not remaining_debts)
            status=book.apply(plan,quotes,now,plan["signal_id"],complete=complete)
            book.funding_debts.extend(debt for s,debt in unsettled.items() if s not in book.positions)
            book.record(now)
            result={"at":iso(now),"status":status,"fresh_plan":fresh,"missing_funding":missing_funding,
                    "observation_gap_seconds":max(0,(now-previous_observation)/1000) if previous_observation else 0,
                    "unobserved_stop_interval":bool(previous_observation and now-previous_observation>300000),
                    "missing_position_quotes":sorted(set(book.positions)-set(quotes)),
                    "pending_funding_debts":book.funding_debts,
                    "equity":book.equity(),"wallet":book.wallet,"margin":book.margin(),"positions":book.positions,
                    "fills_total":len([e for e in book.events if e["side"] in {"buy","sell"}]),
                    "decisions":book.last_decisions,"strategy":plan.get("version"),
                    "mode":"paper","live":False}
            result["valuation_complete"]=not (result["missing_position_quotes"] or missing_funding or book.funding_debts)
            book.curve[-1]["valuation_complete"]=result["valuation_complete"]
            book.curve[-1]["unobserved_stop_interval"]=result["unobserved_stop_interval"]
            conn.execute("INSERT OR REPLACE INTO account VALUES (1,?)",(json.dumps(book.dump(),allow_nan=False),))
            conn.execute("INSERT INTO cycles(at,status,payload) VALUES (?,?,?)",(now,status,json.dumps(result,allow_nan=False)))
        return result


def scan(directory=DATA,output=OUTPUT,capital=10000):
    from .policy import load_policy
    state=FuturesLedger(Path(output)/"paper.sqlite3",capital).status()
    report=build_report(load_snapshot(directory,multiframe=True),capital,state["positions"],
                        max_leverage=get_runtime_settings().quant_max_leverage,active_plan=state["active_plan"],
                        policy=load_policy(get_runtime_settings(),output))
    atomic_json(Path(output)/"latest.json",report)
    atomic_json(Path(output)/"plan.json",report["plan"])
    (Path(output)/"latest.md").write_text(report_markdown(report))
    return report
