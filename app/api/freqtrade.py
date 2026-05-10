# -*- coding: utf-8 -*-
"""
Freqtrade integration API.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.freqtrade import (
    FreqtradeBacktestRequest,
    FreqtradeBotStartRequest,
    FreqtradeCommandResult,
    FreqtradeDownloadDataRequest,
    FreqtradeStatusResponse,
)
from app.services.trading.freqtrade_service import FreqtradeService, get_freqtrade_service


router = APIRouter(prefix="/api/freqtrade", tags=["Freqtrade"])


def get_service() -> FreqtradeService:
    return get_freqtrade_service()


@router.get("/status", response_model=FreqtradeStatusResponse)
async def get_status(service: FreqtradeService = Depends(get_service)) -> FreqtradeStatusResponse:
    return await service.status()


@router.post("/download-data", response_model=FreqtradeCommandResult)
async def download_data(
    request: FreqtradeDownloadDataRequest,
    service: FreqtradeService = Depends(get_service),
) -> FreqtradeCommandResult:
    try:
        return await service.download_data(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest", response_model=FreqtradeCommandResult)
async def backtest(
    request: FreqtradeBacktestRequest,
    service: FreqtradeService = Depends(get_service),
) -> FreqtradeCommandResult:
    try:
        return await service.backtest(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bot/start", response_model=FreqtradeCommandResult)
async def start_bot(
    request: FreqtradeBotStartRequest,
    service: FreqtradeService = Depends(get_service),
) -> FreqtradeCommandResult:
    try:
        return await service.start_bot(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bot/stop", response_model=FreqtradeCommandResult)
async def stop_bot(service: FreqtradeService = Depends(get_service)) -> FreqtradeCommandResult:
    return await service.stop_bot()

