# -*- coding: utf-8 -*-
"""
Paper trading schemas.

These models describe simulated trades only; they are not connected to real
exchange order placement.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PaperTradingMode(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class PaperTradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class PaperOrderStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    REJECTED = "rejected"


class PaperTradePlan(BaseModel):
    symbol: str
    side: PaperTradeSide
    confidence: float = Field(..., ge=0, le=1)
    opportunity_score: float = Field(..., ge=0, le=100)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    risk_reward_ratio: float = Field(..., ge=0)
    position_size_usdt: float = Field(..., ge=0)
    quantity: float = Field(..., ge=0)
    max_loss_usdt: float = Field(..., ge=0)
    leverage: float = Field(default=1.0, ge=1)
    invalidation_reason: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    source_signal: Dict[str, Any] = Field(default_factory=dict)


class PaperTradeRecord(BaseModel):
    id: str
    plan: PaperTradePlan
    status: PaperOrderStatus = PaperOrderStatus.OPEN
    opened_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    realized_pnl_usdt: float = 0.0
    realized_pnl_percent: float = 0.0
    close_reason: Optional[str] = None


class PaperTradeView(PaperTradeRecord):
    mark_price: Optional[float] = None
    unrealized_pnl_usdt: float = 0.0
    unrealized_pnl_percent: float = 0.0


class PaperRejectedSignal(BaseModel):
    symbol: str
    reason: str
    action: Optional[str] = None
    confidence: Optional[float] = None
    opportunity_score: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class PaperScanRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=20)
    mode: PaperTradingMode = PaperTradingMode.BALANCED
    dry_run: bool = True
    force_update: bool = False
    analysis_type: str = Field(
        default="technical_only",
        description="technical_only, integrated, kronos_only, ml_only",
    )


class PaperScanResponse(BaseModel):
    mode: PaperTradingMode
    dry_run: bool
    scanned_symbols: int
    opened_count: int
    candidate_plans: List[PaperTradePlan] = Field(default_factory=list)
    opened_trades: List[PaperTradeRecord] = Field(default_factory=list)
    rejected: List[PaperRejectedSignal] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class PaperStatusResponse(BaseModel):
    enabled: bool
    mode: PaperTradingMode
    initial_balance_usdt: float
    balance_usdt: float
    equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    open_positions: List[PaperTradeView] = Field(default_factory=list)
    closed_trades: List[PaperTradeRecord] = Field(default_factory=list)
    total_trades: int
    win_rate: float
    max_open_positions: int
    timestamp: datetime = Field(default_factory=datetime.now)


class PaperCloseRequest(BaseModel):
    reason: str = "manual"


class PaperResetRequest(BaseModel):
    initial_balance_usdt: Optional[float] = Field(default=None, gt=0)
