# -*- coding: utf-8 -*-
"""
Paper trading API.

All endpoints here operate on simulated positions only.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.paper_trading import (
    PaperBacktestRequest,
    PaperBacktestResponse,
    PaperCloseRequest,
    PaperResetRequest,
    PaperScanRequest,
    PaperScanResponse,
    PaperStatusResponse,
    PaperTradeRecord,
)
from app.services.trading.paper_trading_service import (
    PaperTradingService,
    get_paper_trading_service,
)


router = APIRouter(prefix="/api/paper-trading", tags=["Paper Trading"])


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
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backtest", response_model=PaperBacktestResponse)
async def run_backtest(
    request: PaperBacktestRequest,
    service: PaperTradingService = Depends(get_service),
) -> PaperBacktestResponse:
    try:
        return await service.run_backtest(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
