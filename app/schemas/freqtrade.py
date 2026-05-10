# -*- coding: utf-8 -*-
"""
Schemas for the Freqtrade integration layer.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FreqtradeRunMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class FreqtradeCommandResult(BaseModel):
    command: List[str]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    started_at: datetime
    finished_at: datetime
    elapsed_seconds: float
    success: bool


class FreqtradeStatusResponse(BaseModel):
    docker_available: bool
    compose_available: bool
    native_available: bool
    selected_backend: str
    bot_running: bool = False
    bot_pid: Optional[int] = None
    compose_file_exists: bool
    user_data_exists: bool
    default_config: str
    default_strategy: str
    last_check: datetime = Field(default_factory=datetime.now)
    details: List[str] = Field(default_factory=list)


class FreqtradeDownloadDataRequest(BaseModel):
    pairs: List[str] = Field(default_factory=lambda: ["SOL-USDT-SWAP", "LINK-USDT-SWAP"])
    timeframes: List[str] = Field(default_factory=lambda: ["1h"])
    timerange: Optional[str] = Field(
        default=None,
        description="Freqtrade timerange, for example 20240101-20240501",
    )
    config_file: Optional[str] = None


class FreqtradeBacktestRequest(BaseModel):
    strategy: str = "OpenSourceTrendStrategy"
    timeframe: str = "1h"
    pairs: Optional[List[str]] = None
    timerange: Optional[str] = None
    export_trades: bool = True
    config_file: Optional[str] = None
    enable_protections: bool = False
    cache: Optional[str] = None


class FreqtradeBotStartRequest(BaseModel):
    mode: FreqtradeRunMode = FreqtradeRunMode.DRY_RUN
    strategy: str = "OpenSourceTrendStrategy"
    config_file: Optional[str] = None
    confirm_live: bool = False
