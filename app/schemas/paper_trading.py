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


class PaperBacktestStrategy(str, Enum):
    EMA_RSI = "ema_rsi"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    LONG_ONLY_PORTFOLIO = "long_only_portfolio"


class PaperPortfolioBucket(str, Enum):
    CORE = "core"
    SATELLITE = "satellite"
    CASH = "cash"


class PaperExecutionMode(str, Enum):
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE_DISABLED = "live_disabled"


class PaperForwardRunnerState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    STOPPING = "stopping"


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
    long_only: bool = True
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


class PaperBacktestRequest(BaseModel):
    symbol: str = Field(..., description="Example: BTC-USDT-SWAP")
    strategy: PaperBacktestStrategy = PaperBacktestStrategy.EMA_RSI
    timeframe: str = "1h"
    candles: int = Field(default=1000, ge=100, le=1500)
    mode: PaperTradingMode = PaperTradingMode.BALANCED
    initial_balance_usdt: float = Field(default=10000.0, gt=0)
    fee_rate: float = Field(default=0.0004, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.0002, ge=0, le=0.01)
    allow_short: bool = False
    parameters: Dict[str, Any] = Field(default_factory=dict)


class PaperBacktestTrade(BaseModel):
    symbol: str
    side: PaperTradeSide
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    position_size_usdt: float
    pnl_usdt: float
    pnl_percent: float
    close_reason: str


class PaperBacktestResponse(BaseModel):
    symbol: str
    strategy: PaperBacktestStrategy
    timeframe: str
    candles: int
    mode: PaperTradingMode
    initial_balance_usdt: float
    final_balance_usdt: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    fees_paid_usdt: float
    trades: List[PaperBacktestTrade] = Field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class PaperUniverseAsset(BaseModel):
    symbol: str
    bucket: PaperPortfolioBucket
    base_asset: str
    price: float
    volume_24h_usdt: float
    change_percent_24h: float
    score: float
    reason: str
    market_cap_rank: Optional[int] = None
    max_leverage: float
    risk_pct: float


class PaperUniverseResponse(BaseModel):
    core: List[PaperUniverseAsset] = Field(default_factory=list)
    satellite: List[PaperUniverseAsset] = Field(default_factory=list)
    cash_allocation: float
    allocation: Dict[str, float]
    source: str
    execution_mode: PaperExecutionMode
    timestamp: datetime = Field(default_factory=datetime.now)
    warnings: List[str] = Field(default_factory=list)


class PaperPortfolioBacktestRequest(BaseModel):
    core_symbols: Optional[List[str]] = None
    satellite_symbols: Optional[List[str]] = None
    timeframe: str = "1h"
    candles: int = Field(default=1000, ge=100, le=1500)
    mode: PaperTradingMode = PaperTradingMode.BALANCED
    initial_balance_usdt: float = Field(default=10000.0, gt=0)
    fee_rate: float = Field(default=0.0004, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.0002, ge=0, le=0.01)
    sample_split: float = Field(default=0.7, gt=0.5, lt=0.95)
    max_core_symbols: int = Field(default=10, ge=1, le=15)
    max_satellite_symbols: int = Field(default=8, ge=0, le=20)
    strategies: List[PaperBacktestStrategy] = Field(
        default_factory=lambda: [PaperBacktestStrategy.EMA_RSI, PaperBacktestStrategy.BREAKOUT]
    )


class PaperSymbolContribution(BaseModel):
    symbol: str
    bucket: PaperPortfolioBucket
    strategy: PaperBacktestStrategy
    allocation_usdt: float
    final_balance_usdt: float
    total_return_pct: float
    max_drawdown_pct: float
    total_trades: int
    pnl_usdt: float


class PaperPortfolioBacktestResponse(BaseModel):
    strategy: str = "long_only_portfolio"
    timeframe: str
    candles: int
    mode: PaperTradingMode
    initial_balance_usdt: float
    final_balance_usdt: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    in_sample: Dict[str, Any]
    out_of_sample: Dict[str, Any]
    symbol_contributions: List[PaperSymbolContribution] = Field(default_factory=list)
    exit_reason_stats: Dict[str, int] = Field(default_factory=dict)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class PaperLeaderboardRequest(BaseModel):
    symbols: Optional[List[str]] = None
    strategies: List[PaperBacktestStrategy] = Field(
        default_factory=lambda: [
            PaperBacktestStrategy.EMA_RSI,
            PaperBacktestStrategy.BREAKOUT,
            PaperBacktestStrategy.MEAN_REVERSION,
        ]
    )
    timeframe: str = "1h"
    candles: int = Field(default=600, ge=100, le=1500)
    mode: PaperTradingMode = PaperTradingMode.BALANCED
    initial_balance_usdt: float = Field(default=10000.0, gt=0)
    max_symbols: int = Field(default=12, ge=1, le=30)


class PaperLeaderboardRow(BaseModel):
    rank: int
    symbol: str
    strategy: PaperBacktestStrategy
    score: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int


class PaperLeaderboardResponse(BaseModel):
    rows: List[PaperLeaderboardRow]
    timestamp: datetime = Field(default_factory=datetime.now)
    warnings: List[str] = Field(default_factory=list)


class PaperRiskStatusResponse(BaseModel):
    execution_mode: PaperExecutionMode
    long_only: bool
    allocation: Dict[str, float]
    leverage_limits: Dict[str, float]
    risk_limits: Dict[str, float]
    current_open_positions: int
    max_open_positions: int
    gross_exposure_usdt: float
    equity_usdt: float
    exposure_ratio: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    trading_paused: bool
    pause_reasons: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class PaperBacktestHistoryItem(BaseModel):
    run_id: str
    run_type: str
    title: str
    symbol: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    strategy: Optional[str] = None
    timeframe: Optional[str] = None
    candles: int = 0
    mode: Optional[str] = None
    initial_balance_usdt: float = 0.0
    final_balance_usdt: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    completed_at: datetime
    warnings: List[str] = Field(default_factory=list)


class PaperBacktestHistoryResponse(BaseModel):
    items: List[PaperBacktestHistoryItem] = Field(default_factory=list)
    total: int


class PaperBacktestRunDetail(PaperBacktestHistoryItem):
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)
    trades: List[Dict[str, Any]] = Field(default_factory=list)
    symbol_contributions: List[Dict[str, Any]] = Field(default_factory=list)
    exit_reason_stats: Dict[str, int] = Field(default_factory=dict)
    leaderboard_rows: List[Dict[str, Any]] = Field(default_factory=list)


class PaperForwardRunnerStartRequest(BaseModel):
    mode: PaperTradingMode = PaperTradingMode.BALANCED
    analysis_type: str = "technical_only"
    scan_interval_seconds: int = Field(default=900, ge=60, le=86400)
    tick_interval_seconds: int = Field(default=60, ge=15, le=3600)
    max_core_symbols: int = Field(default=5, ge=1, le=15)
    max_satellite_symbols: int = Field(default=5, ge=0, le=20)
    force_update: bool = False


class PaperForwardRunnerStatus(BaseModel):
    state: PaperForwardRunnerState
    running: bool
    mode: PaperTradingMode
    analysis_type: str
    scan_interval_seconds: int
    tick_interval_seconds: int
    max_core_symbols: int
    max_satellite_symbols: int
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    last_tick_at: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None
    next_scan_at: Optional[datetime] = None
    loop_count: int = 0
    scan_count: int = 0
    opened_count: int = 0
    rejected_count: int = 0
    last_error: Optional[str] = None
    last_symbols: List[str] = Field(default_factory=list)
    last_scan_summary: Dict[str, Any] = Field(default_factory=dict)


class PaperForwardSnapshotItem(BaseModel):
    snapshot_id: str
    created_at: datetime
    equity_usdt: float
    balance_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    open_positions: int
    closed_trades: int
    win_rate: float
    state: PaperForwardRunnerState
    scan_count: int


class PaperForwardSnapshotResponse(BaseModel):
    items: List[PaperForwardSnapshotItem] = Field(default_factory=list)
    total: int
