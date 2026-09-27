"""Can run standalone: uvicorn app.advisory.api:app --port 8890."""

import asyncio
from typing import List, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .market import MarketDataError, markdown_report
from .service import advisory_service
from .paper import PaperLedger, paper_cycle

router = APIRouter(prefix="/api/market-advisory", tags=["选币与长短线建议"])


@router.get("/scan")
async def scan(watch: List[str] = Query(default=["ZECUSDT"]), top: int = Query(default=60, ge=1, le=150),
               profile: Literal["active", "balanced", "legacy"] = "active"):
    """Public spot data; quality failures are visible; never places an order."""
    try:
        result = await asyncio.to_thread(advisory_service.report, watch, top, profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result["status"] == "unavailable":
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/report", response_class=PlainTextResponse)
async def report(watch: List[str] = Query(default=["ZECUSDT"]), top: int = Query(default=60, ge=1, le=150),
                 profile: Literal["active", "balanced", "legacy"] = "active"):
    return markdown_report(await scan(watch, top, profile))


@router.get("/paper")
async def paper_status(profile: Literal["active", "balanced", "legacy"] = "active",
                       horizon: Literal["short_term", "long_term"] = "short_term"):
    return await asyncio.to_thread(lambda: PaperLedger().status(profile, horizon))


@router.post("/paper/step")
async def paper_step(request: Request, watch: List[str] = Query(default=["ZECUSDT"]), top: int = Query(default=60, ge=1, le=150),
                     profile: Literal["active", "balanced", "legacy"] = "active",
                     horizon: Literal["short_term", "long_term"] = "short_term"):
    if not request.client or request.client.host not in {"127.0.0.1", "::1"} or request.headers.get("origin"):
        raise HTTPException(status_code=403, detail="Paper writes require a local non-browser client; use CLI or localhost curl")
    try:
        _, result = await asyncio.to_thread(paper_cycle, watch, top, profile, horizon)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


app = FastAPI(title="选币、长短线策略与本地模拟盘")
app.include_router(router)
