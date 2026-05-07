# -*- coding: utf-8 -*-
"""
Paper trading API.

All endpoints here operate on simulated positions only.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.schemas.paper_trading import (
    PaperBacktestRequest,
    PaperBacktestResponse,
    PaperBacktestHistoryResponse,
    PaperBacktestRunDetail,
    PaperCloseRequest,
    PaperForwardRunnerStartRequest,
    PaperForwardRunnerStatus,
    PaperForwardSessionDetail,
    PaperForwardSessionResponse,
    PaperForwardSnapshotResponse,
    PaperLeaderboardRequest,
    PaperLeaderboardResponse,
    PaperPortfolioBacktestRequest,
    PaperPortfolioBacktestResponse,
    PaperRiskStatusResponse,
    PaperResetRequest,
    PaperScanRequest,
    PaperScanResponse,
    PaperStatusResponse,
    PaperTradeRecord,
    PaperUniverseResponse,
)
from app.services.trading.paper_trading_service import (
    PaperTradingService,
    get_paper_trading_service,
)


router = APIRouter(prefix="/api/paper-trading", tags=["Paper Trading"])
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "static" / "paper_trading_dashboard.html"


async def get_service() -> PaperTradingService:
    return get_paper_trading_service()


@router.post("/scan", response_model=PaperScanResponse)
async def scan_opportunities(
    request: PaperScanRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperScanResponse:
    try:
        return await service.scan_and_trade(
            symbols=request.symbols,
            mode=request.mode,
            dry_run=request.dry_run,
            force_update=request.force_update,
            analysis_type=request.analysis_type,
            long_only=request.long_only,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backtest", response_model=PaperBacktestResponse)
async def run_backtest(
    request: PaperBacktestRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperBacktestResponse:
    try:
        result = await service.run_backtest(request)
        service.record_single_backtest(request, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backtest/portfolio", response_model=PaperPortfolioBacktestResponse)
async def run_portfolio_backtest(
    request: PaperPortfolioBacktestRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperPortfolioBacktestResponse:
    try:
        result = await service.run_portfolio_backtest(request)
        service.record_portfolio_backtest(request, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backtest/leaderboard", response_model=PaperLeaderboardResponse)
async def run_leaderboard(
    request: PaperLeaderboardRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperLeaderboardResponse:
    try:
        result = await service.run_leaderboard(request)
        service.record_leaderboard(request, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/backtest/history", response_model=PaperBacktestHistoryResponse)
async def list_backtest_history(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    run_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    service: PaperTradingService = Depends(get_service),
) -> PaperBacktestHistoryResponse:
    try:
        return service.list_backtest_history(
            limit=limit,
            offset=offset,
            run_type=run_type,
            symbol=symbol,
            strategy=strategy,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/backtest/history/{run_id}", response_model=PaperBacktestRunDetail)
async def get_backtest_history_detail(
    run_id: str,
    service: PaperTradingService = Depends(get_service),
) -> PaperBacktestRunDetail:
    try:
        return service.get_backtest_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard", response_class=HTMLResponse)
async def paper_trading_dashboard() -> HTMLResponse:
    if not DASHBOARD_PATH.exists():
        raise HTTPException(status_code=404, detail="dashboard file not found")
    return HTMLResponse(DASHBOARD_PATH.read_text(encoding="utf-8"))


@router.get("/universe", response_model=PaperUniverseResponse)
async def get_universe(
    max_core_symbols: int = 10,
    max_satellite_symbols: int = 8,
    service: PaperTradingService = Depends(get_service),
) -> PaperUniverseResponse:
    try:
        return await service.get_universe(max_core_symbols, max_satellite_symbols)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/risk-status", response_model=PaperRiskStatusResponse)
async def get_risk_status(
    service: PaperTradingService = Depends(get_service),
) -> PaperRiskStatusResponse:
    try:
        return await service.get_risk_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/forward/start", response_model=PaperForwardRunnerStatus)
async def start_forward_runner(
    request: PaperForwardRunnerStartRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardRunnerStatus:
    try:
        return await service.start_forward_runner(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/forward/stop", response_model=PaperForwardRunnerStatus)
async def stop_forward_runner(
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardRunnerStatus:
    try:
        return await service.stop_forward_runner()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/forward/status", response_model=PaperForwardRunnerStatus)
async def get_forward_runner_status(
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardRunnerStatus:
    try:
        return service.get_forward_runner_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/forward/snapshots", response_model=PaperForwardSnapshotResponse)
async def list_forward_snapshots(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardSnapshotResponse:
    try:
        return service.list_forward_snapshots(limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/forward/sessions", response_model=PaperForwardSessionResponse)
async def list_forward_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardSessionResponse:
    try:
        return service.list_forward_sessions(limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/forward/sessions/{session_id}", response_model=PaperForwardSessionDetail)
async def get_forward_session(
    session_id: str,
    service: PaperTradingService = Depends(get_service),
) -> PaperForwardSessionDetail:
    try:
        return service.get_forward_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tick", response_model=PaperStatusResponse)
async def tick_positions(
    service: PaperTradingService = Depends(get_service),
) -> PaperStatusResponse:
    try:
        return await service.tick()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status", response_model=PaperStatusResponse)
async def get_status(
    service: PaperTradingService = Depends(get_service),
) -> PaperStatusResponse:
    try:
        return await service.get_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/close/{trade_id}", response_model=PaperTradeRecord)
async def close_trade(
    trade_id: str,
    request: PaperCloseRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperTradeRecord:
    try:
        return await service.close_trade(trade_id, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/reset")
@router.delete("/reset")
async def reset_paper_account(
    request: PaperResetRequest = PaperResetRequest(),
    service: PaperTradingService = Depends(get_service),
):
    return service.reset(request.initial_balance_usdt)
