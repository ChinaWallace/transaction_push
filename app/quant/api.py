"""Read contracts and explicitly step the local paper ledger; no exchange credentials."""
import asyncio
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict
from fastapi.responses import PlainTextResponse, HTMLResponse
from app.core.runtime_config import get_runtime_settings
from .service import FuturesLedger, ROOT, read, report_markdown, scan
from .policy import PortfolioPolicy, load_policy

router=APIRouter(prefix="/api/quant",tags=["全池合约策略与模拟盘"])


def _settings(request:Request):
    return getattr(request.app.state,"settings",None) or get_runtime_settings()


def _ledger(request:Request):
    settings=_settings(request)
    return FuturesLedger(settings.quant_output_dir/"paper.sqlite3",settings.quant_initial_capital)


@router.get("/dashboard",response_class=HTMLResponse)
async def dashboard():return (ROOT/"docs/quant_dashboard.html").read_text()


@router.get("/contracts")
async def contracts(request:Request):
    try:
        result=await asyncio.to_thread(read,_settings(request).quant_output_dir/"latest.json")
    except (OSError,ValueError) as exc:
        raise HTTPException(503,"No valid contracts snapshot; run scripts/quant_portfolio.py scan") from exc
    age=(time.time()*1000-result["snapshot_time"])/1000
    result["quote_age_seconds"]=max(0,age);result["snapshot_fresh"]=0<=age<=180
    result["executable_now"]=bool(result["snapshot_fresh"] and result["plan"]["complete"])
    return result


@router.get("/report",response_class=PlainTextResponse)
async def report(request:Request):return report_markdown(await contracts(request))


@router.get("/replay")
async def replay(request:Request):
    try:result=await asyncio.to_thread(read,_settings(request).quant_output_dir/"replay.json")
    except (OSError,ValueError) as exc:raise HTTPException(503,"Contract replay unavailable") from exc
    result["cases"]={name:{k:v for k,v in case.items() if k not in {"events","trades","pnl_by_symbol"}} for name,case in result["cases"].items()}
    return result


@router.get("/replay/mtf")
async def replay_mtf():
    try:result=await asyncio.to_thread(read,ROOT/"reports/quant_v4/sample_replay.json")
    except (OSError,ValueError) as exc:raise HTTPException(503,"MTF replay sample unavailable") from exc
    return {name:{k:v for k,v in case.items() if k not in {"events","decisions","curve"}} for name,case in result.items()}


@router.get("/replay/policy")
async def replay_policy():
    try:result=await asyncio.to_thread(read,ROOT/"reports/quant_v4/policy_comparison.json")
    except (OSError,ValueError) as exc:raise HTTPException(503,"Policy comparison unavailable") from exc
    result["cases"]={name:{k:v for k,v in case.items() if k not in {"events","decisions","curve"}} for name,case in result["cases"].items()}
    result.pop("data_hashes",None)
    return result


@router.get("/research.js",response_class=PlainTextResponse)
async def research_script():
    return PlainTextResponse((ROOT/"docs/quant_research.js").read_text(),media_type="application/javascript")


@router.get("/research")
async def research_results():
    def load():
        directory=ROOT/"reports/quant_v5"
        result=read(directory/"comparison.json")
        result["protocol"]=read(directory/"strategy_protocol.json")
        result["selection"]=read(directory/"selection_freeze.json")
        # Keep per-run fills and equity curves behind the detail endpoint.
        for row in result["rows"]:
            row.pop("results_per_pair",None);row.pop("exit_reason_summary",None)
        return result
    try:return await asyncio.to_thread(load)
    except (OSError,ValueError) as exc:raise HTTPException(503,"Strategy comparison not ready") from exc


@router.get("/research/detail")
async def research_detail(window:str,strategy:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500),study:str=Query("v5",pattern="^v(?:[5-9]|10|11|12)$")):
    def load():
        directory=ROOT/("reports/quant_"+study)
        rows=read(directory/"comparison.json")["rows"]
        matched=next((r for r in rows if r["window"]==window and r["strategy"]==strategy),None)
        if matched is None:
            raise HTTPException(404,"Unknown comparison run")
        base=directory/("reference_runs" if study=="v7" and matched.get("origin")=="v6_frozen_reference" else "runs")
        run=(base/window/strategy).resolve()
        if not run.is_relative_to(base.resolve()):raise HTTPException(404,"Unknown run")
        orders=read(run/"orders.json")
        result={"orders":orders[offset:offset+limit],"total_orders":len(orders),"offset":offset,
                "curve":read(run/"equity_preview.json"),"metrics":read(run/"mark_metrics.json")}
        if study in {"v10","v11","v12"}:
            snapshots=read(run/"risk_snapshots.json")
            result["risk_reductions"]=[s for s in snapshots if s["reason"] in {"before_reduce","after_reduce"}]
        if study in {"v11","v12"}:result["monthly_returns"]=read(run/"monthly_returns.json")
        if study=="v12":result["seed_eligibility"]=read(run/"seed_eligibility.json")
        return result
    try:return await asyncio.to_thread(load)
    except (OSError,ValueError) as exc:raise HTTPException(503,"Comparison detail not ready") from exc


@router.get("/research/stops")
async def stop_research_results():
    def load():
        directory=ROOT/"reports/quant_v6"
        result=read(directory/"comparison.json")
        result["registry"]=read(directory/"registry.json") if (directory/"registry.json").exists() else None
        result["selection"]=read(directory/"selection.json") if (directory/"selection.json").exists() else None
        result["completed_backtests"]=len(list((directory/"runs").glob("*/*/summary.json")))
        for row in result["rows"]:
            row.pop("results_per_pair",None);row.pop("exit_reason_summary",None)
        return result
    try:return await asyncio.to_thread(load)
    except (OSError,ValueError) as exc:raise HTTPException(503,"Stop comparison not ready") from exc


@router.get("/research/holding")
async def holding_research_results():
    def load():
        directory=ROOT/"reports/quant_v7"
        result=read(directory/"comparison.json")
        result["completed_backtests"]=len(list((directory/"runs").glob("*/*/summary.json")))
        for row in result["rows"]:row["study"]="v7"
        for study in ("v8","v9","v10","v11","v12"):
            path=ROOT/("reports/quant_"+study)/"comparison.json"
            if not path.exists():continue
            extra=read(path)
            for row in extra["rows"]:
                row.pop("artifacts",None)
                result["rows"].append(row)
            result[study+"_runs"]=len(extra["rows"])
            if study=="v11":result["overlay_selection"]=extra.get("selection")
            if study=="v12":result["expansion_selection"]=extra.get("selection")
        expanded=ROOT/"reports/quant_v12"
        for name in ("universe_freeze","fundamental_sources","status"):
            if (expanded/(name+".json")).exists():result["expansion_"+name]=read(expanded/(name+".json"))
        for row in result["rows"]:
            row.pop("results_per_pair",None);row.pop("exit_reason_summary",None)
        return result
    try:return await asyncio.to_thread(load)
    except (OSError,ValueError) as exc:raise HTTPException(503,"Holding comparison not ready") from exc


@router.get("/research/forward")
async def forward_research_results():
    def load():
        directory=ROOT/"reports/quant_v6/forward"
        if not (directory/"status.json").exists():return {"state":"not_started","accounts":[],"live_enabled":False}
        result=read(directory/"status.json")
        result["status_stale"]=time.time()*1000-result["updated_ms"]>90_000
        result["assessment"]=read(directory/"protocol.json")["assessment"]
        return result
    try:return await asyncio.to_thread(load)
    except (OSError,ValueError) as exc:raise HTTPException(503,"Forward observation unavailable") from exc


@router.get("/paper")
async def paper(request:Request):return await asyncio.to_thread(_ledger(request).status)


@router.get("/history")
async def history(request:Request,limit:int=Query(100,ge=1,le=500),before:int|None=Query(None,ge=1)):
    return await asyncio.to_thread(_ledger(request).history,limit,before)


@router.get("/runtime")
async def runtime(request:Request):
    from .runtime import runtime_status
    result=runtime_status(_settings(request).quant_output_dir)
    if getattr(request.app.state,"research_only",False):
        result.update(state="research_only",automatic=False,research_only=True)
        result["configuration"]["worker_enabled"]=False
    return result


@router.get("/strategy")
async def strategy(request:Request):
    settings=_settings(request)
    policy=load_policy(settings)
    return {"version":"contracts-v4.0-mtf","name":"4h趋势轮动 / 1h确认 / 15m突破与回踩",
            "signal_timeframe":"4h / 1h / 15m", "rebalance":f"每根4h收盘后冻结最多{policy.max_positions}个目标；北京时间00/04/08/12/16/20点",
            "entry":"1h收盘高于EMA20且EMA20>EMA50并上行；15m放量突破前20根最高价，或回踩EMA20后收复；每4h每币最多一次加仓",
            "selection":"4h的1/3/10日动量和趋势，成交额、市值及资金费；同发行人/高相关去重",
            "exit":"最新报价触发止损；1h跌破EMA50或15m跌破此前10根低点退出；72h到期退出；止损或信号退出冷却1h",
            "holding_period":"15m触发，预期数小时至3天；仅做多，当前仍属实验策略",
            "costs":{"fee_bps":5,"slippage_bps":5,"funding":"按实际结算事件记账"},
            "risk":{"max_positions":policy.max_positions,"max_leverage":settings.quant_max_leverage,
                    "position_stop_risk":settings.quant_position_risk,"satellite_stop_risk":.25,"gross":1.8,
                    "margin":min(.85,.65+max(0,policy.core_total_weight-.5)),"core_drawdown_exempt":True,"total_drawdown_limit":None},
            "portfolio_policy":policy.model_dump(),
            "core_exit":"优选长期仓不按短线/72h/排名退出，不受45%熔断；"+("允许上涨后权重漂移，不机械减仓；" if policy.core_allow_weight_drift else "权重超限减仓；")+"保留可选宽止损，移出优选后恢复普通规则；浮盈加仓正在独立研究对照，尚未替换本账户",
            "configuration":settings.public_status(),
            "historical_replay":{"version":"contracts-v3.1","from":"2026-01-01","through":"2026-09-23","positions":6,
                "applies_to_current_strategy":False,"note":"旧日线回放不代表v4多周期收益"},"live":False}


class PolicyUpdate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision:str
    policy:PortfolioPolicy


@router.get("/policy")
async def portfolio_policy(request:Request):
    settings=_settings(request)
    policy=await asyncio.to_thread(load_policy,settings)
    return {"policy":policy.model_dump(),"revision":policy.revision(),"live":False,
            "source":".env defaults + persisted user portfolio preferences",
            "effective":"next complete fresh paper cycle","core_leverage":1,"core_drawdown_exempt":True}


@router.put("/policy")
async def save_portfolio_policy(request:Request,update:PolicyUpdate):
    host=urlsplit(str(request.url)).hostname
    origin=request.headers.get("origin")
    expected=f"{request.url.scheme}://{request.url.netloc}"
    if (not request.client or request.client.host not in {"127.0.0.1","::1"}
        or host not in {"127.0.0.1","::1","localhost"}
        or origin and origin!=expected or request.headers.get("x-quant-paper")!="1"
        or request.headers.get("content-type","").split(";")[0]!="application/json"):
        raise HTTPException(403,"Paper preferences require a same-origin local JSON client")
    def save():
        from .runtime import writer_lock
        from .service import atomic_json
        settings=_settings(request)
        with writer_lock(settings.quant_output_dir):
            current=load_policy(settings)
            if update.revision!=current.revision():raise HTTPException(409,"Preferences changed; reload before saving")
            try:ranking=read(settings.quant_output_dir/"latest.json")["ranking"]
            except (OSError,ValueError,KeyError):raise HTTPException(409,"Contract catalog unavailable") from None
            available={r["symbol"] for r in ranking}
            unknown=set(update.policy.preferred_symbols)-available
            if unknown:raise HTTPException(422,"Unknown active USDT contracts: "+", ".join(sorted(unknown)))
            atomic_json(settings.quant_output_dir/"portfolio_policy.json",
                        {"overrides":update.policy.model_dump(),"saved_at":int(time.time()*1000),"previous_revision":current.revision()})
    try:await asyncio.to_thread(save)
    except RuntimeError as exc:raise HTTPException(409,"Paper cycle busy; retry shortly") from exc
    return await portfolio_policy(request)


@router.get("/permissions")
async def permission_status(request:Request):
    try:result=await asyncio.to_thread(read,_settings(request).quant_output_dir/"permissions.json")
    except (OSError,ValueError):result={"verified":False,"error":"not_checked"}
    return {**result,"execution_mode":"paper","live_orders_enabled":False}



@router.post("/paper/step")
async def paper_step(request:Request):
    if not request.client or request.client.host not in {"127.0.0.1","::1"} or request.headers.get("origin"):
        raise HTTPException(403,"Paper writes require a local non-browser client")
    try:
        payload=await request.json() if request.headers.get("content-length","0")!="0" else {}
        def run_step():
            from .runtime import writer_lock
            settings=_settings(request)
            output=settings.quant_output_dir
            with writer_lock(output):
                ledger=FuturesLedger(output/"paper.sqlite3",settings.quant_initial_capital)
                report=scan(settings.quant_data_dir,output,settings.quant_initial_capital)
                return ledger.step(report,funding=payload.get("funding"))
        return await asyncio.to_thread(run_step)
    except (OSError,ValueError,RuntimeError) as exc:
        raise HTTPException(409,str(exc)) from exc


# Compatibility ASGI entry delegates to the same composition root/lifecycle.
def __getattr__(name):
    if name=="app":
        from app.application import create_app
        app=create_app();globals()["app"]=app
        return app
    raise AttributeError(name)
