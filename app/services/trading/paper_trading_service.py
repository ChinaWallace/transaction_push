# -*- coding: utf-8 -*-
"""
Paper trading orchestration service.

The service turns analysis signals into simulated trades behind explicit risk
gates. It never calls exchange order APIs.
"""

import asyncio
import aiohttp
import os
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc

from app.core.database import get_db_session, get_engine
from app.core.logging import get_logger
from app.core.trading_universe import (
    ALLOWED_PROJECT_SYMBOLS,
    normalize_project_symbol,
    normalize_project_symbols,
)
from app.models.paper_trading import PaperBacktestRun, PaperForwardSession, PaperForwardSnapshot
from app.schemas.paper_trading import (
    PaperExecutionMode,
    PaperBacktestHistoryItem,
    PaperBacktestHistoryResponse,
    PaperBacktestRequest,
    PaperBacktestResponse,
    PaperBacktestRunDetail,
    PaperBacktestStrategy,
    PaperBacktestTrade,
    PaperForwardRunnerStartRequest,
    PaperForwardRunnerState,
    PaperForwardRunnerStatus,
    PaperForwardSessionDetail,
    PaperForwardSessionItem,
    PaperForwardSessionResponse,
    PaperForwardSnapshotItem,
    PaperForwardSnapshotResponse,
    PaperLeaderboardRequest,
    PaperLeaderboardResponse,
    PaperLeaderboardRow,
    PaperOrderStatus,
    PaperPortfolioBacktestRequest,
    PaperPortfolioBacktestResponse,
    PaperPortfolioBucket,
    PaperRejectedSignal,
    PaperRiskStatusResponse,
    PaperScanResponse,
    PaperSymbolContribution,
    PaperTradePlan,
    PaperTradeRecord,
    PaperTradeSide,
    PaperTradeView,
    PaperTradingMode,
    PaperStatusResponse,
    PaperUniverseAsset,
    PaperUniverseResponse,
)
from app.schemas.trading import AnalysisType, TradingSignal
from app.services.exchanges.service_manager import (
    get_current_exchange_service,
    start_exchange_services,
)
from app.services.trading.core_trading_service import get_core_trading_service


logger = get_logger(__name__)


class PaperTradingService:
    """A conservative paper trading layer for opportunity discovery."""

    ALLOCATION = {"core": 0.90, "satellite": 0.0, "cash": 0.10}
    LEVERAGE_LIMITS = {"core": 1.0, "satellite": 1.0, "high_volatility_core": 1.0}
    RISK_LIMITS = {
        "core_trade_risk_pct": 0.006,
        "satellite_trade_risk_pct": 0.0,
        "daily_loss_pause_pct": 0.02,
        "portfolio_drawdown_pause_pct": 0.08,
        "max_gross_exposure_pct": 0.25,
    }
    STABLE_OR_WRAPPED_ASSETS = {
        "USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDP", "USDE", "WBTC", "WETH",
        "BUSD", "FRAX", "LUSD", "PYUSD",
    }
    DEFAULT_PINNED_CORE = list(ALLOWED_PROJECT_SYMBOLS)
    MIN_CORE_VOLUME_USDT = 300_000_000
    MIN_SATELLITE_VOLUME_USDT = 50_000_000
    MIN_UNRANKED_SATELLITE_VOLUME_USDT = 150_000_000
    MAX_CORE_MARKET_CAP_RANK = 80
    MAX_SATELLITE_MARKET_CAP_RANK = 300
    MARKET_CAP_CACHE_TTL = timedelta(hours=6)

    MODE_CONFIG: Dict[PaperTradingMode, Dict[str, float]] = {
        PaperTradingMode.CONSERVATIVE: {
            "min_confidence": 0.72,
            "min_rr": 1.8,
            "min_score": 72.0,
            "risk_pct": 0.005,
            "max_position_usdt": 300.0,
            "max_stop_pct": 0.06,
            "default_stop_pct": 0.018,
            "default_take_pct": 0.04,
        },
        PaperTradingMode.BALANCED: {
            "min_confidence": 0.65,
            "min_rr": 1.5,
            "min_score": 64.0,
            "risk_pct": 0.01,
            "max_position_usdt": 500.0,
            "max_stop_pct": 0.08,
            "default_stop_pct": 0.025,
            "default_take_pct": 0.05,
        },
        PaperTradingMode.AGGRESSIVE: {
            "min_confidence": 0.58,
            "min_rr": 1.2,
            "min_score": 56.0,
            "risk_pct": 0.015,
            "max_position_usdt": 800.0,
            "max_stop_pct": 0.10,
            "default_stop_pct": 0.035,
            "default_take_pct": 0.07,
        },
    }

    def __init__(self) -> None:
        self.enabled = os.getenv("PAPER_TRADING_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            self.default_mode = PaperTradingMode(
                os.getenv("PAPER_TRADING_DEFAULT_MODE", PaperTradingMode.BALANCED.value).lower()
            )
        except ValueError:
            self.default_mode = PaperTradingMode.BALANCED
        self.initial_balance_usdt = self._env_float("PAPER_TRADING_INITIAL_BALANCE", 10000.0)
        self.balance_usdt = self.initial_balance_usdt
        self.max_open_positions = min(
            2,
            max(1, self._env_int("PAPER_TRADING_MAX_OPEN_POSITIONS", 2)),
        )
        self.execution_mode = self._parse_execution_mode(
            os.getenv("PAPER_TRADING_EXECUTION_MODE", PaperExecutionMode.PAPER.value)
        )
        self.pinned_core_symbols = self._parse_symbol_env(
            "PAPER_TRADING_PINNED_CORE_SYMBOLS",
            self.DEFAULT_PINNED_CORE,
        )
        self.peak_equity_usdt = self.initial_balance_usdt
        self._risk_day = datetime.now().date()
        self._day_start_equity_usdt = self.initial_balance_usdt
        self._last_equity_usdt = self.initial_balance_usdt
        self.trades: Dict[str, PaperTradeRecord] = {}
        self._lock = asyncio.Lock()
        self._history_table_ready = False
        self._forward_table_ready = False
        self._forward_session_table_ready = False
        self._runner_task: Optional[asyncio.Task] = None
        self._runner_stop_event: Optional[asyncio.Event] = None
        self._runner_state = PaperForwardRunnerState.STOPPED
        self._runner_config = PaperForwardRunnerStartRequest(mode=self.default_mode)
        self._runner_started_at: Optional[datetime] = None
        self._runner_stopped_at: Optional[datetime] = None
        self._runner_last_tick_at: Optional[datetime] = None
        self._runner_last_scan_at: Optional[datetime] = None
        self._runner_next_scan_at: Optional[datetime] = None
        self._runner_loop_count = 0
        self._runner_scan_count = 0
        self._runner_opened_count = 0
        self._runner_rejected_count = 0
        self._runner_last_error: Optional[str] = None
        self._runner_last_symbols: List[str] = []
        self._runner_last_scan_summary: Dict[str, Any] = {}
        self._market_cap_cache: Tuple[List[Dict[str, Any]], datetime] = ([], datetime.min)

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_execution_mode(value: str) -> PaperExecutionMode:
        try:
            return PaperExecutionMode((value or PaperExecutionMode.PAPER.value).lower())
        except ValueError:
            return PaperExecutionMode.PAPER

    @staticmethod
    def _parse_symbol_env(name: str, default: List[str]) -> List[str]:
        raw = os.getenv(name)
        if not raw:
            return list(default)
        return normalize_project_symbols(raw.split(","))

    async def scan_and_trade(
        self,
        symbols: List[str],
        mode: PaperTradingMode = PaperTradingMode.BALANCED,
        dry_run: bool = True,
        force_update: bool = False,
        analysis_type: str = "technical_only",
        long_only: bool = True,
    ) -> PaperScanResponse:
        normalized_symbols = normalize_project_symbols(symbols)
        if not long_only:
            raise ValueError("The BTC/ETH paper baseline is long-only.")
        if (analysis_type or "").lower() not in {"technical", "technical_only"}:
            raise ValueError("The BTC/ETH paper baseline only allows technical_only analysis.")

        candidate_plans: List[PaperTradePlan] = []
        opened_trades: List[PaperTradeRecord] = []
        rejected: List[PaperRejectedSignal] = []

        if not self.enabled:
            return PaperScanResponse(
                mode=mode,
                dry_run=dry_run,
                scanned_symbols=len(normalized_symbols),
                opened_count=0,
                rejected=[
                    PaperRejectedSignal(symbol=symbol, reason="paper_trading_disabled")
                    for symbol in normalized_symbols
                ],
            )

        await self._mark_to_market_open_positions()

        if not dry_run:
            risk = await self.get_risk_status()
            if risk.trading_paused:
                return PaperScanResponse(
                    mode=mode,
                    dry_run=dry_run,
                    scanned_symbols=len(normalized_symbols),
                    opened_count=0,
                    rejected=[
                        PaperRejectedSignal(
                            symbol=symbol,
                            reason="risk_gate_paused",
                            details={"pause_reasons": risk.pause_reasons},
                        )
                        for symbol in normalized_symbols
                    ],
                )

        trading_service = await get_core_trading_service()
        analysis_enum = self._parse_analysis_type(analysis_type)

        for symbol in normalized_symbols:
            try:
                signal = await trading_service.analyze_symbol(
                    symbol=symbol,
                    analysis_type=analysis_enum,
                    force_update=force_update,
                )
                if not signal:
                    rejected.append(PaperRejectedSignal(symbol=symbol, reason="no_signal"))
                    continue

                plan, reject = await self._build_plan(signal, mode, long_only=long_only)
                if reject:
                    rejected.append(reject)
                    continue

                candidate_plans.append(plan)

                if dry_run:
                    continue

                async with self._lock:
                    reject_reason = self._portfolio_reject_reason(
                        symbol,
                        plan.position_size_usdt * plan.leverage,
                    )
                    if reject_reason:
                        rejected.append(
                            PaperRejectedSignal(
                                symbol=symbol,
                                reason=reject_reason,
                                action=signal.final_action,
                                confidence=signal.final_confidence,
                                opportunity_score=plan.opportunity_score,
                            )
                        )
                        continue

                    trade = PaperTradeRecord(id=str(uuid.uuid4()), plan=plan)
                    self.trades[trade.id] = trade
                    opened_trades.append(trade)

            except Exception as exc:
                logger.warning("Paper scan failed for %s: %s", symbol, exc)
                rejected.append(
                    PaperRejectedSignal(
                        symbol=symbol,
                        reason="analysis_failed",
                        details={"error": str(exc)},
                    )
                )

        return PaperScanResponse(
            mode=mode,
            dry_run=dry_run,
            scanned_symbols=len(normalized_symbols),
            opened_count=len(opened_trades),
            candidate_plans=candidate_plans,
            opened_trades=opened_trades,
            rejected=rejected,
        )

    async def get_status(
        self, mode: Optional[PaperTradingMode] = None
    ) -> PaperStatusResponse:
        open_views, unrealized = await self._mark_to_market_open_positions()
        closed_trades = [
            trade
            for trade in self.trades.values()
            if trade.status == PaperOrderStatus.CLOSED
        ]
        wins = sum(1 for trade in closed_trades if trade.realized_pnl_usdt > 0)
        win_rate = wins / len(closed_trades) if closed_trades else 0.0
        realized = self.balance_usdt - self.initial_balance_usdt

        return PaperStatusResponse(
            enabled=self.enabled,
            mode=mode or self.default_mode,
            initial_balance_usdt=round(self.initial_balance_usdt, 4),
            balance_usdt=round(self.balance_usdt, 4),
            equity_usdt=round(self.balance_usdt + unrealized, 4),
            realized_pnl_usdt=round(realized, 4),
            unrealized_pnl_usdt=round(unrealized, 4),
            open_positions=open_views,
            closed_trades=closed_trades[-50:],
            total_trades=len(closed_trades),
            win_rate=round(win_rate, 4),
            max_open_positions=self.max_open_positions,
        )

    async def close_trade(self, trade_id: str, reason: str = "manual") -> PaperTradeRecord:
        trade = self.trades.get(trade_id)
        if not trade:
            raise ValueError(f"paper trade not found: {trade_id}")
        if trade.status == PaperOrderStatus.CLOSED:
            return trade

        price = await self._get_current_price(trade.plan.symbol)
        if not price:
            price = trade.plan.entry_price
        return self._close_trade(trade, price, reason)

    def reset(self, initial_balance_usdt: Optional[float] = None) -> Dict[str, Any]:
        if initial_balance_usdt:
            self.initial_balance_usdt = initial_balance_usdt
        self.balance_usdt = self.initial_balance_usdt
        self.trades.clear()
        self.peak_equity_usdt = self.initial_balance_usdt
        self._risk_day = datetime.now().date()
        self._day_start_equity_usdt = self.initial_balance_usdt
        self._last_equity_usdt = self.initial_balance_usdt
        return {
            "status": "reset",
            "initial_balance_usdt": self.initial_balance_usdt,
            "timestamp": datetime.now(),
        }

    async def tick(self) -> PaperStatusResponse:
        await self._mark_to_market_open_positions()
        return await self.get_status()

    async def start_forward_runner(
        self, request: PaperForwardRunnerStartRequest
    ) -> PaperForwardRunnerStatus:
        if self._runner_task and not self._runner_task.done():
            return self.get_forward_runner_status()
        if self.execution_mode != PaperExecutionMode.PAPER:
            raise ValueError("forward runner only starts in PAPER execution mode")
        if (request.analysis_type or "").lower() not in {"technical", "technical_only"}:
            raise ValueError("forward runner only supports technical_only analysis")
        if request.max_core_symbols > 2 or request.max_satellite_symbols != 0:
            raise ValueError("forward runner is restricted to BTC and ETH with no satellites")
        if request.momentum_probe_enabled:
            raise ValueError("momentum probes are disabled in the BTC/ETH baseline")

        self._runner_config = request
        self._runner_stop_event = asyncio.Event()
        self._runner_state = PaperForwardRunnerState.RUNNING
        self._runner_started_at = datetime.now()
        self._runner_stopped_at = None
        self._runner_last_error = None
        self._runner_last_scan_summary = {}
        self._runner_last_symbols = []
        self._runner_next_scan_at = datetime.now()
        self._runner_task = asyncio.create_task(self._forward_runner_loop())
        return self.get_forward_runner_status()

    async def stop_forward_runner(self) -> PaperForwardRunnerStatus:
        status_before_clear: Optional[PaperStatusResponse] = None
        if not self._runner_task or self._runner_task.done():
            self._runner_state = PaperForwardRunnerState.STOPPED
            self._runner_stopped_at = datetime.now()
            status_before_clear = await self.get_status()
            self._record_forward_session(status_before_clear)
            self._clear_forward_runtime()
            return self.get_forward_runner_status()
        self._runner_state = PaperForwardRunnerState.STOPPING
        if self._runner_stop_event:
            self._runner_stop_event.set()
        try:
            await asyncio.wait_for(self._runner_task, timeout=10)
        except asyncio.TimeoutError:
            self._runner_task.cancel()
        self._runner_state = PaperForwardRunnerState.STOPPED
        self._runner_stopped_at = datetime.now()
        status_before_clear = await self.get_status()
        self._record_forward_session(status_before_clear)
        self._clear_forward_runtime()
        return self.get_forward_runner_status()

    def get_forward_runner_status(self) -> PaperForwardRunnerStatus:
        cfg = self._runner_config
        return PaperForwardRunnerStatus(
            state=self._runner_state,
            running=bool(self._runner_task and not self._runner_task.done()),
            mode=cfg.mode,
            analysis_type=cfg.analysis_type,
            scan_interval_seconds=cfg.scan_interval_seconds,
            tick_interval_seconds=cfg.tick_interval_seconds,
            max_core_symbols=cfg.max_core_symbols,
            max_satellite_symbols=cfg.max_satellite_symbols,
            started_at=self._runner_started_at,
            stopped_at=self._runner_stopped_at,
            last_tick_at=self._runner_last_tick_at,
            last_scan_at=self._runner_last_scan_at,
            next_scan_at=self._runner_next_scan_at,
            loop_count=self._runner_loop_count,
            scan_count=self._runner_scan_count,
            opened_count=self._runner_opened_count,
            rejected_count=self._runner_rejected_count,
            last_error=self._runner_last_error,
            last_symbols=self._runner_last_symbols,
            last_scan_summary=self._runner_last_scan_summary,
        )

    def list_forward_snapshots(
        self, limit: int = 200, offset: int = 0
    ) -> PaperForwardSnapshotResponse:
        self._ensure_forward_table()
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        with get_db_session() as db:
            query = db.query(PaperForwardSnapshot)
            total = query.count()
            rows = (
                query.order_by(desc(PaperForwardSnapshot.created_at), desc(PaperForwardSnapshot.id))
                .offset(offset)
                .limit(limit)
                .all()
            )
            return PaperForwardSnapshotResponse(
                total=total,
                items=[
                    PaperForwardSnapshotItem(
                        snapshot_id=row.snapshot_id,
                        created_at=row.created_at,
                        equity_usdt=row.equity_usdt or 0.0,
                        balance_usdt=row.balance_usdt or 0.0,
                        realized_pnl_usdt=row.realized_pnl_usdt or 0.0,
                        unrealized_pnl_usdt=row.unrealized_pnl_usdt or 0.0,
                        open_positions=row.open_positions or 0,
                        closed_trades=row.closed_trades or 0,
                        win_rate=row.win_rate or 0.0,
                        state=PaperForwardRunnerState(row.state),
                        scan_count=row.scan_count or 0,
                    )
                    for row in rows
                ],
            )

    def list_forward_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> PaperForwardSessionResponse:
        self._ensure_forward_session_table()
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with get_db_session() as db:
            query = db.query(PaperForwardSession)
            total = query.count()
            rows = (
                query.order_by(desc(PaperForwardSession.stopped_at), desc(PaperForwardSession.id))
                .offset(offset)
                .limit(limit)
                .all()
            )
            return PaperForwardSessionResponse(
                total=total,
                items=[self._forward_session_item(row) for row in rows],
            )

    def get_forward_session(self, session_id: str) -> PaperForwardSessionDetail:
        self._ensure_forward_session_table()
        with get_db_session() as db:
            row = db.query(PaperForwardSession).filter(PaperForwardSession.session_id == session_id).first()
            if not row:
                raise ValueError("forward session not found")
            item = self._forward_session_item(row)
            return PaperForwardSessionDetail(
                **self._model_payload(item),
                open_positions_payload=row.open_positions_payload or [],
                closed_trades_payload=row.closed_trades_payload or [],
                runner_payload=row.runner_payload or {},
            )

    async def get_universe(
        self,
        max_core_symbols: int = 2,
        max_satellite_symbols: int = 0,
    ) -> PaperUniverseResponse:
        exchange = await self._ensure_exchange()
        tickers = await exchange.get_tickers("SWAP")
        ticker_map = self._ticker_map(tickers)
        warnings: List[str] = ["Trading universe is locked to BTC and ETH."]
        requested_core = max(1, min(max_core_symbols, len(ALLOWED_PROJECT_SYMBOLS)))
        core = [
            self._universe_asset(
                symbol,
                PaperPortfolioBucket.CORE,
                ticker_map[symbol],
                100.0,
                "fixed BTC/ETH execution allowlist",
            )
            for symbol in ALLOWED_PROJECT_SYMBOLS[:requested_core]
            if symbol in ticker_map
        ]
        missing = [symbol for symbol in ALLOWED_PROJECT_SYMBOLS[:requested_core] if symbol not in ticker_map]
        if missing:
            warnings.append(f"Missing exchange tickers: {', '.join(missing)}")
        if max_satellite_symbols:
            warnings.append("Satellite symbols are disabled and were ignored.")

        return PaperUniverseResponse(
            core=core,
            satellite=[],
            cash_allocation=self.ALLOCATION["cash"],
            allocation=dict(self.ALLOCATION),
            source="btc_eth_fixed",
            execution_mode=self.execution_mode,
            warnings=warnings,
        )

    async def get_risk_status(self) -> PaperRiskStatusResponse:
        status = await self.get_status()
        today = datetime.now().date()
        if today != self._risk_day:
            self._risk_day = today
            self._day_start_equity_usdt = status.equity_usdt
        self._last_equity_usdt = status.equity_usdt
        self.peak_equity_usdt = max(self.peak_equity_usdt, status.equity_usdt)
        gross_exposure = sum(
            trade.plan.position_size_usdt * trade.plan.leverage
            for trade in status.open_positions
            if trade.status == PaperOrderStatus.OPEN
        )
        exposure_ratio = gross_exposure / status.equity_usdt if status.equity_usdt else 0.0
        daily_loss_ratio = (
            max(0.0, (self._day_start_equity_usdt - status.equity_usdt) / self._day_start_equity_usdt)
            if self._day_start_equity_usdt
            else 0.0
        )
        drawdown_ratio = (
            max(0.0, (self.peak_equity_usdt - status.equity_usdt) / self.peak_equity_usdt)
            if self.peak_equity_usdt
            else 0.0
        )
        pause_reasons = []
        if len(status.open_positions) >= self.max_open_positions:
            pause_reasons.append("max_open_positions_reached")
        if exposure_ratio >= self.RISK_LIMITS["max_gross_exposure_pct"]:
            pause_reasons.append("gross_exposure_limit_reached")
        if daily_loss_ratio >= self.RISK_LIMITS["daily_loss_pause_pct"]:
            pause_reasons.append("daily_loss_limit_reached")
        if drawdown_ratio >= self.RISK_LIMITS["portfolio_drawdown_pause_pct"]:
            pause_reasons.append("portfolio_drawdown_limit_reached")

        return PaperRiskStatusResponse(
            execution_mode=self.execution_mode,
            long_only=True,
            allocation=dict(self.ALLOCATION),
            leverage_limits=dict(self.LEVERAGE_LIMITS),
            risk_limits=dict(self.RISK_LIMITS),
            current_open_positions=len(status.open_positions),
            max_open_positions=self.max_open_positions,
            gross_exposure_usdt=round(gross_exposure, 4),
            equity_usdt=status.equity_usdt,
            exposure_ratio=round(exposure_ratio, 4),
            realized_pnl_usdt=status.realized_pnl_usdt,
            unrealized_pnl_usdt=status.unrealized_pnl_usdt,
            trading_paused=bool(pause_reasons),
            pause_reasons=pause_reasons,
        )

    async def run_portfolio_backtest(
        self, request: PaperPortfolioBacktestRequest
    ) -> PaperPortfolioBacktestResponse:
        universe = await self.get_universe(
            max_core_symbols=request.max_core_symbols,
            max_satellite_symbols=request.max_satellite_symbols,
        )
        core_symbols = normalize_project_symbols(
            request.core_symbols or [asset.symbol for asset in universe.core]
        )
        if request.satellite_symbols:
            raise ValueError("Satellite symbols are disabled; only BTC and ETH are allowed.")
        satellite_symbols: List[str] = []

        contributions: List[PaperSymbolContribution] = []
        all_trades: List[PaperBacktestTrade] = []
        equity_curves: List[Tuple[float, List[Dict[str, Any]]]] = []
        warnings = list(universe.warnings)

        async def run_bucket_symbol(symbol: str, bucket: PaperPortfolioBucket, allocation_usdt: float):
            strategy = self._strategy_for_bucket(bucket, request.strategies)
            leverage = self._max_leverage_for_symbol(symbol, bucket)
            risk_pct = (
                self.RISK_LIMITS["core_trade_risk_pct"]
                if bucket == PaperPortfolioBucket.CORE
                else self.RISK_LIMITS["satellite_trade_risk_pct"]
            )
            backtest_request = PaperBacktestRequest(
                symbol=symbol,
                strategy=strategy,
                timeframe=request.timeframe,
                candles=request.candles,
                mode=request.mode,
                initial_balance_usdt=allocation_usdt,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                allow_short=False,
                parameters={
                    "bucket": bucket.value,
                    "max_leverage": leverage,
                    "risk_pct": risk_pct,
                    "max_position_usdt": allocation_usdt * leverage,
                    "use_atr_exits": True,
                    "atr_stop_mult": 3.0 if bucket == PaperPortfolioBucket.CORE else 2.5,
                    "atr_trail_mult": 2.5 if bucket == PaperPortfolioBucket.CORE else 2.0,
                    "partial_take_profit": True,
                },
            )
            result = await self.run_backtest(backtest_request)
            contributions.append(
                PaperSymbolContribution(
                    symbol=symbol,
                    bucket=bucket,
                    strategy=strategy,
                    allocation_usdt=round(allocation_usdt, 4),
                    final_balance_usdt=result.final_balance_usdt,
                    total_return_pct=result.total_return_pct,
                    max_drawdown_pct=result.max_drawdown_pct,
                    total_trades=result.total_trades,
                    pnl_usdt=round(result.final_balance_usdt - allocation_usdt, 4),
                )
            )
            all_trades.extend(result.trades)
            equity_curves.append((allocation_usdt, result.equity_curve))

        core_allocation = request.initial_balance_usdt * self.ALLOCATION["core"]
        satellite_allocation = request.initial_balance_usdt * self.ALLOCATION["satellite"]
        per_core = core_allocation / len(core_symbols) if core_symbols else 0.0
        per_satellite = satellite_allocation / len(satellite_symbols) if satellite_symbols else 0.0

        for symbol in core_symbols:
            await run_bucket_symbol(symbol, PaperPortfolioBucket.CORE, per_core)
        for symbol in satellite_symbols:
            await run_bucket_symbol(symbol, PaperPortfolioBucket.SATELLITE, per_satellite)

        active_allocation = per_core * len(core_symbols) + per_satellite * len(satellite_symbols)
        cash_balance = max(0.0, request.initial_balance_usdt - active_allocation)
        final_balance = cash_balance + sum(item.final_balance_usdt for item in contributions)
        equity_curve = self._merge_equity_curves(equity_curves, cash_balance)
        portfolio_metrics = self._portfolio_metrics(
            request.initial_balance_usdt,
            final_balance,
            all_trades,
            equity_curve,
        )
        in_sample, out_of_sample = self._split_equity_metrics(
            request.initial_balance_usdt,
            equity_curve,
            request.sample_split,
        )
        exit_reason_stats: Dict[str, int] = {}
        for trade in all_trades:
            exit_reason_stats[trade.close_reason] = exit_reason_stats.get(trade.close_reason, 0) + 1
        warnings.extend(self._portfolio_warnings(portfolio_metrics, contributions))

        return PaperPortfolioBacktestResponse(
            timeframe=request.timeframe,
            candles=request.candles,
            mode=request.mode,
            initial_balance_usdt=round(request.initial_balance_usdt, 4),
            final_balance_usdt=round(final_balance, 4),
            total_return_pct=portfolio_metrics["total_return_pct"],
            max_drawdown_pct=portfolio_metrics["max_drawdown_pct"],
            sharpe_ratio=portfolio_metrics["sharpe_ratio"],
            win_rate=portfolio_metrics["win_rate"],
            profit_factor=portfolio_metrics["profit_factor"],
            total_trades=portfolio_metrics["total_trades"],
            in_sample=in_sample,
            out_of_sample=out_of_sample,
            symbol_contributions=sorted(contributions, key=lambda item: item.pnl_usdt, reverse=True),
            exit_reason_stats=exit_reason_stats,
            equity_curve=equity_curve,
            warnings=warnings,
        )

    async def run_leaderboard(
        self, request: PaperLeaderboardRequest
    ) -> PaperLeaderboardResponse:
        symbols = request.symbols
        warnings: List[str] = []
        if not symbols:
            universe = await self.get_universe(
                max_core_symbols=min(2, request.max_symbols),
                max_satellite_symbols=0,
            )
            symbols = [asset.symbol for asset in universe.core + universe.satellite]
            warnings.extend(universe.warnings)
        symbols = normalize_project_symbols(symbols)[:request.max_symbols]

        rows: List[PaperLeaderboardRow] = []
        for symbol in symbols:
            for strategy in request.strategies:
                if strategy == PaperBacktestStrategy.LONG_ONLY_PORTFOLIO:
                    continue
                result = await self.run_backtest(
                    PaperBacktestRequest(
                        symbol=symbol,
                        strategy=strategy,
                        timeframe=request.timeframe,
                        candles=request.candles,
                        mode=request.mode,
                        initial_balance_usdt=request.initial_balance_usdt,
                        allow_short=False,
                        parameters={"use_atr_exits": True, "partial_take_profit": True},
                    )
                )
                score = self._leaderboard_score(result)
                rows.append(
                    PaperLeaderboardRow(
                        rank=0,
                        symbol=symbol,
                        strategy=strategy,
                        score=score,
                        total_return_pct=result.total_return_pct,
                        max_drawdown_pct=result.max_drawdown_pct,
                        sharpe_ratio=result.sharpe_ratio,
                        win_rate=result.win_rate,
                        profit_factor=result.profit_factor,
                        total_trades=result.total_trades,
                    )
                )

        rows = sorted(rows, key=lambda row: row.score, reverse=True)
        for idx, row in enumerate(rows, 1):
            row.rank = idx
        return PaperLeaderboardResponse(rows=rows, warnings=warnings)

    def record_single_backtest(
        self, request: PaperBacktestRequest, result: PaperBacktestResponse
    ) -> PaperBacktestHistoryItem:
        payload = self._model_payload(result)
        run = self._save_backtest_run(
            run_type="single",
            title=f"{result.symbol} {result.strategy.value} {result.timeframe}",
            symbol=result.symbol,
            symbols=[result.symbol],
            strategy=result.strategy.value,
            timeframe=result.timeframe,
            candles=result.candles,
            mode=result.mode.value,
            initial_balance_usdt=result.initial_balance_usdt,
            final_balance_usdt=result.final_balance_usdt,
            total_return_pct=result.total_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            win_rate=result.win_rate,
            profit_factor=result.profit_factor,
            total_trades=result.total_trades,
            request_payload=self._model_payload(request),
            summary={
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "fees_paid_usdt": result.fees_paid_usdt,
            },
            equity_curve=payload.get("equity_curve", []),
            trades=payload.get("trades", []),
            warnings=payload.get("warnings", []),
        )
        return self._history_item_from_model(run)

    def record_portfolio_backtest(
        self,
        request: PaperPortfolioBacktestRequest,
        result: PaperPortfolioBacktestResponse,
    ) -> PaperBacktestHistoryItem:
        payload = self._model_payload(result)
        symbols = [item.get("symbol") for item in payload.get("symbol_contributions", []) if item.get("symbol")]
        run = self._save_backtest_run(
            run_type="portfolio",
            title=f"Long-only portfolio {result.timeframe} {result.candles}",
            symbol=None,
            symbols=symbols,
            strategy=result.strategy,
            timeframe=result.timeframe,
            candles=result.candles,
            mode=result.mode.value,
            initial_balance_usdt=result.initial_balance_usdt,
            final_balance_usdt=result.final_balance_usdt,
            total_return_pct=result.total_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            win_rate=result.win_rate,
            profit_factor=result.profit_factor,
            total_trades=result.total_trades,
            request_payload=self._model_payload(request),
            summary={
                "in_sample": result.in_sample,
                "out_of_sample": result.out_of_sample,
            },
            equity_curve=payload.get("equity_curve", []),
            symbol_contributions=payload.get("symbol_contributions", []),
            exit_reason_stats=payload.get("exit_reason_stats", {}),
            warnings=payload.get("warnings", []),
        )
        return self._history_item_from_model(run)

    def record_leaderboard(
        self, request: PaperLeaderboardRequest, result: PaperLeaderboardResponse
    ) -> PaperBacktestHistoryItem:
        payload = self._model_payload(result)
        rows = payload.get("rows", [])
        best = rows[0] if rows else {}
        return_pct = float(best.get("total_return_pct", 0.0) or 0.0)
        max_drawdown = float(best.get("max_drawdown_pct", 0.0) or 0.0)
        final_balance = request.initial_balance_usdt * (1 + return_pct / 100)
        run = self._save_backtest_run(
            run_type="leaderboard",
            title=f"Strategy leaderboard {request.timeframe} {request.candles}",
            symbol=best.get("symbol"),
            symbols=request.symbols or [],
            strategy=best.get("strategy"),
            timeframe=request.timeframe,
            candles=request.candles,
            mode=request.mode.value,
            initial_balance_usdt=request.initial_balance_usdt,
            final_balance_usdt=round(final_balance, 4),
            total_return_pct=return_pct,
            max_drawdown_pct=max_drawdown,
            sharpe_ratio=float(best.get("sharpe_ratio", 0.0) or 0.0),
            win_rate=float(best.get("win_rate", 0.0) or 0.0),
            profit_factor=float(best.get("profit_factor", 0.0) or 0.0),
            total_trades=int(best.get("total_trades", 0) or 0),
            request_payload=self._model_payload(request),
            summary={"best": best, "rows_count": len(rows)},
            leaderboard_rows=rows,
            warnings=payload.get("warnings", []),
        )
        return self._history_item_from_model(run)

    def list_backtest_history(
        self,
        limit: int = 30,
        offset: int = 0,
        run_type: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> PaperBacktestHistoryResponse:
        self._ensure_history_table()
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with get_db_session() as db:
            query = db.query(PaperBacktestRun)
            if run_type:
                query = query.filter(PaperBacktestRun.run_type == run_type)
            if symbol:
                normalized = self._normalize_symbol(symbol)
                query = query.filter(PaperBacktestRun.symbol == normalized)
            if strategy:
                query = query.filter(PaperBacktestRun.strategy == strategy)
            total = query.count()
            runs = (
                query.order_by(desc(PaperBacktestRun.completed_at), desc(PaperBacktestRun.id))
                .offset(offset)
                .limit(limit)
                .all()
            )
            return PaperBacktestHistoryResponse(
                items=[self._history_item_from_model(run) for run in runs],
                total=total,
            )

    def get_backtest_run(self, run_id: str) -> PaperBacktestRunDetail:
        self._ensure_history_table()
        with get_db_session() as db:
            run = db.query(PaperBacktestRun).filter(PaperBacktestRun.run_id == run_id).first()
            if not run:
                raise ValueError("backtest run not found")
            item = self._history_item_from_model(run)
            return PaperBacktestRunDetail(
                **self._model_payload(item),
                request_payload=run.request_payload or {},
                summary=run.summary or {},
                equity_curve=run.equity_curve or [],
                trades=run.trades or [],
                symbol_contributions=run.symbol_contributions or [],
                exit_reason_stats=run.exit_reason_stats or {},
                leaderboard_rows=run.leaderboard_rows or [],
            )

    async def run_backtest(self, request: PaperBacktestRequest) -> PaperBacktestResponse:
        request.symbol = normalize_project_symbol(request.symbol)
        if request.timeframe != "4h":
            raise ValueError("The BTC/ETH paper baseline only supports the 4h timeframe.")
        if request.allow_short:
            raise ValueError("The BTC/ETH paper baseline is long-only.")
        exchange = await get_current_exchange_service()
        if exchange is None:
            await start_exchange_services()
            exchange = await get_current_exchange_service()
        if exchange is None:
            raise ValueError("exchange service is not available")

        klines = await exchange.get_kline_data(
            request.symbol.upper(),
            request.timeframe,
            request.candles,
        )
        candles = self._normalize_klines(klines)
        if len(candles) < 100:
            raise ValueError(f"not enough kline data: {len(candles)} candles")

        cfg = dict(self.MODE_CONFIG[request.mode])
        for key in (
            "risk_pct",
            "max_position_usdt",
            "default_stop_pct",
            "default_take_pct",
            "max_stop_pct",
        ):
            if key in request.parameters:
                cfg[key] = float(request.parameters[key])
        max_leverage = float(request.parameters.get("max_leverage", 1.0))
        if max_leverage != 1.0:
            raise ValueError("The BTC/ETH paper baseline requires exactly 1x leverage.")
        use_atr_exits = bool(request.parameters.get("use_atr_exits", False))
        partial_take_profit = bool(request.parameters.get("partial_take_profit", False))
        proactive_exit = bool(request.parameters.get("proactive_exit", True))
        balance = request.initial_balance_usdt
        position: Optional[Dict[str, Any]] = None
        trades: List[PaperBacktestTrade] = []
        equity_curve: List[Dict[str, Any]] = []
        fees_paid = 0.0
        peak_equity = balance
        max_drawdown = 0.0

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        ema_fast = self._ema(closes, int(request.parameters.get("ema_fast", 12)))
        ema_slow = self._ema(closes, int(request.parameters.get("ema_slow", 26)))
        rsi = self._rsi(closes, int(request.parameters.get("rsi_period", 14)))
        atr = self._atr(candles, int(request.parameters.get("atr_period", 14)))

        warmup = max(30, int(request.parameters.get("warmup", 60)))
        for idx in range(warmup, len(candles)):
            candle = candles[idx]
            mark_price = candle["close"]

            if position:
                if use_atr_exits:
                    self._update_trailing_stop(position, candle, atr[idx], request.parameters)
                    if partial_take_profit and not position.get("partial_taken"):
                        partial_price = self._partial_take_profit_price(position, candle)
                        if partial_price:
                            closed_qty = position["quantity"] * 0.30
                            fee = closed_qty * partial_price * request.fee_rate
                            fees_paid += fee
                            pnl = self._backtest_pnl(
                                {**position, "quantity": closed_qty},
                                partial_price,
                            ) - fee
                            balance += pnl
                            position["quantity"] -= closed_qty
                            position["position_size_usdt"] *= 0.70
                            position["partial_taken"] = True
                            position["stop_loss"] = max(position["stop_loss"], position["entry_price"])

                exit_price, close_reason = self._backtest_exit_price(position, candle)
                if proactive_exit and not close_reason:
                    exit_price, close_reason = self._backtest_proactive_exit_price(
                        position,
                        idx,
                        candle,
                        closes,
                        ema_fast,
                        ema_slow,
                        rsi,
                    )
                if close_reason:
                    fee = position["position_size_usdt"] * request.fee_rate
                    fees_paid += fee
                    pnl = self._backtest_pnl(position, exit_price) - fee
                    balance += pnl
                    trades.append(
                        PaperBacktestTrade(
                            symbol=request.symbol.upper(),
                            side=position["side"],
                            entry_time=position["entry_time"],
                            exit_time=candle["time"],
                            entry_price=round(position["entry_price"], 8),
                            exit_price=round(exit_price, 8),
                            position_size_usdt=round(position["position_size_usdt"], 4),
                            pnl_usdt=round(pnl, 4),
                            pnl_percent=round(
                                (pnl / position["position_size_usdt"]) * 100
                                if position["position_size_usdt"]
                                else 0.0,
                                4,
                            ),
                            close_reason=close_reason,
                        )
                    )
                    position = None

            if position is None:
                side = self._strategy_signal(
                    request.strategy,
                    idx,
                    closes,
                    highs,
                    lows,
                    ema_fast,
                    ema_slow,
                    rsi,
                    request.parameters,
                )
                if side and (side == PaperTradeSide.LONG or request.allow_short):
                    raw_entry = mark_price
                    entry_price = self._apply_slippage(raw_entry, side, request.slippage_rate, entry=True)
                    stop_loss, take_profit = self._backtest_levels(
                        entry_price,
                        side,
                        cfg,
                        atr_value=atr[idx] if use_atr_exits else None,
                        params=request.parameters,
                    )
                    stop_distance_pct = abs(entry_price - stop_loss) / entry_price
                    position_size_usdt = min(
                        cfg["max_position_usdt"],
                        ((balance * cfg["risk_pct"]) / stop_distance_pct) * max(1.0, max_leverage),
                    )
                    if not self._liquidation_distance_ok(entry_price, stop_loss, max_leverage):
                        position_size_usdt = 0.0
                    if position_size_usdt > 0 and balance > 0:
                        fee = position_size_usdt * request.fee_rate
                        balance -= fee
                        fees_paid += fee
                        position = {
                            "side": side,
                            "entry_time": candle["time"],
                            "entry_price": entry_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "quantity": position_size_usdt / entry_price,
                            "position_size_usdt": position_size_usdt,
                            "initial_quantity": position_size_usdt / entry_price,
                            "risk_per_unit": abs(entry_price - stop_loss),
                            "partial_taken": False,
                            "max_leverage": max_leverage,
                        }

            unrealized = self._backtest_pnl(position, mark_price) if position else 0.0
            equity = balance + unrealized
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity if peak_equity else 0.0
            max_drawdown = max(max_drawdown, drawdown)
            equity_curve.append(
                {
                    "timestamp": candle["time"],
                    "equity": round(equity, 4),
                    "balance": round(balance, 4),
                    "drawdown_pct": round(drawdown * 100, 4),
                }
            )

        if position:
            last = candles[-1]
            exit_price = self._apply_slippage(
                last["close"], position["side"], request.slippage_rate, entry=False
            )
            fee = position["position_size_usdt"] * request.fee_rate
            fees_paid += fee
            pnl = self._backtest_pnl(position, exit_price) - fee
            balance += pnl
            trades.append(
                PaperBacktestTrade(
                    symbol=request.symbol.upper(),
                    side=position["side"],
                    entry_time=position["entry_time"],
                    exit_time=last["time"],
                    entry_price=round(position["entry_price"], 8),
                    exit_price=round(exit_price, 8),
                    position_size_usdt=round(position["position_size_usdt"], 4),
                    pnl_usdt=round(pnl, 4),
                    pnl_percent=round((pnl / position["position_size_usdt"]) * 100, 4),
                    close_reason="end_of_backtest",
                )
            )

        metrics = self._backtest_metrics(
            request.initial_balance_usdt,
            balance,
            max_drawdown,
            trades,
            equity_curve,
        )
        warnings = self._backtest_warnings(metrics, len(candles))

        return PaperBacktestResponse(
            symbol=request.symbol.upper(),
            strategy=request.strategy,
            timeframe=request.timeframe,
            candles=len(candles),
            mode=request.mode,
            initial_balance_usdt=round(request.initial_balance_usdt, 4),
            final_balance_usdt=round(balance, 4),
            total_return_pct=metrics["total_return_pct"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sharpe_ratio=metrics["sharpe_ratio"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            total_trades=metrics["total_trades"],
            winning_trades=metrics["winning_trades"],
            losing_trades=metrics["losing_trades"],
            fees_paid_usdt=round(fees_paid, 4),
            trades=trades[-200:],
            equity_curve=equity_curve,
            warnings=warnings,
        )

    async def _build_plan(
        self, signal: TradingSignal, mode: PaperTradingMode, long_only: bool = True
    ) -> Tuple[Optional[PaperTradePlan], Optional[PaperRejectedSignal]]:
        cfg = self.MODE_CONFIG[mode]
        side = self._action_to_side(signal.final_action)
        if not side:
            return None, self._reject(signal, "not_actionable")
        if long_only and side == PaperTradeSide.SHORT:
            return None, self._reject(signal, "short_not_allowed")

        entry_price = await self._resolve_entry_price(signal)
        if not entry_price or entry_price <= 0:
            return None, self._reject(signal, "missing_entry_price")

        stop_loss, take_profit = self._resolve_levels(signal, side, entry_price, cfg)
        if not self._levels_are_valid(side, entry_price, stop_loss, take_profit):
            return None, self._reject(
                signal,
                "invalid_stop_or_take_profit",
                {"entry_price": entry_price, "stop_loss": stop_loss, "take_profit": take_profit},
            )

        stop_distance_pct = abs(entry_price - stop_loss) / entry_price
        reward_distance_pct = abs(take_profit - entry_price) / entry_price
        risk_reward_ratio = reward_distance_pct / stop_distance_pct if stop_distance_pct else 0.0
        bucket = self._bucket_for_symbol(signal.symbol)

        liquidity_reject = await self._liquidity_reject_reason(signal.symbol, bucket)
        if liquidity_reject:
            return None, self._reject(signal, liquidity_reject["reason"], liquidity_reject)

        if stop_distance_pct <= 0 or stop_distance_pct > cfg["max_stop_pct"]:
            return None, self._reject(
                signal,
                "stop_distance_out_of_bounds",
                {"stop_distance_pct": stop_distance_pct, "max_stop_pct": cfg["max_stop_pct"]},
            )

        if signal.final_confidence < cfg["min_confidence"]:
            return None, self._reject(
                signal,
                "confidence_below_mode_threshold",
                {"min_confidence": cfg["min_confidence"]},
            )

        if risk_reward_ratio < cfg["min_rr"]:
            return None, self._reject(
                signal,
                "risk_reward_below_mode_threshold",
                {"risk_reward_ratio": risk_reward_ratio, "min_rr": cfg["min_rr"]},
            )

        sizing_cfg = self._sizing_config_for_bucket(cfg, bucket)
        position_size_usdt = self._position_size_usdt(stop_distance_pct, sizing_cfg)
        leverage = self._max_leverage_for_symbol(signal.symbol, bucket)
        quantity = position_size_usdt * leverage / entry_price
        max_loss_usdt = position_size_usdt * leverage * stop_distance_pct
        opportunity_score = self._opportunity_score(
            signal=signal,
            risk_reward_ratio=risk_reward_ratio,
            min_rr=cfg["min_rr"],
            stop_distance_pct=stop_distance_pct,
            max_stop_pct=cfg["max_stop_pct"],
        )

        if opportunity_score < cfg["min_score"]:
            return None, self._reject(
                signal,
                "opportunity_score_below_mode_threshold",
                {"opportunity_score": opportunity_score, "min_score": cfg["min_score"]},
            )

        plan = PaperTradePlan(
            symbol=signal.symbol,
            side=side,
            confidence=round(signal.final_confidence, 4),
            opportunity_score=round(opportunity_score, 2),
            entry_price=round(entry_price, 8),
            stop_loss=round(stop_loss, 8),
            take_profit=round(take_profit, 8),
            risk_reward_ratio=round(risk_reward_ratio, 4),
            position_size_usdt=round(position_size_usdt, 4),
            quantity=round(quantity, 10),
            max_loss_usdt=round(max_loss_usdt, 4),
            leverage=leverage,
            invalidation_reason=self._invalidation_reason(side, stop_loss),
            reasons=self._plan_reasons(signal, risk_reward_ratio, opportunity_score),
            source_signal=self._source_signal(signal),
        )
        return plan, None

    def _position_size_usdt(self, stop_distance_pct: float, cfg: Dict[str, float]) -> float:
        risk_budget = self._current_equity_snapshot() * cfg["risk_pct"]
        risk_based_size = risk_budget / stop_distance_pct if stop_distance_pct else 0.0
        return max(0.0, min(cfg["max_position_usdt"], risk_based_size))

    def _sizing_config_for_bucket(
        self, cfg: Dict[str, float], bucket: PaperPortfolioBucket
    ) -> Dict[str, float]:
        result = dict(cfg)
        equity = self._current_equity_snapshot()
        if bucket == PaperPortfolioBucket.CORE:
            result["risk_pct"] = self.RISK_LIMITS["core_trade_risk_pct"]
            bucket_cap = equity * self.ALLOCATION["core"] / max(1, self.max_open_positions)
        else:
            result["risk_pct"] = self.RISK_LIMITS["satellite_trade_risk_pct"]
            bucket_cap = equity * self.ALLOCATION["satellite"] / max(1, self.max_open_positions)
        result["max_position_usdt"] = min(result["max_position_usdt"], bucket_cap)
        return result

    def _opportunity_score(
        self,
        signal: TradingSignal,
        risk_reward_ratio: float,
        min_rr: float,
        stop_distance_pct: float,
        max_stop_pct: float,
    ) -> float:
        confidence_score = signal.final_confidence * 55.0
        rr_score = min(25.0, (risk_reward_ratio / min_rr) * 18.0)
        action_score = 8.0 if self._is_strong_action(signal.final_action) else 4.0
        stop_score = max(0.0, 8.0 * (1.0 - stop_distance_pct / max_stop_pct))
        agreement_score = self._signal_agreement(signal) * 4.0
        return min(100.0, confidence_score + rr_score + action_score + stop_score + agreement_score)

    @staticmethod
    def _action_to_side(action: str) -> Optional[PaperTradeSide]:
        text = PaperTradingService._normalized_action_text(action)
        if any(token in text for token in ("sell", "short", "bear", "卖", "空")):
            return PaperTradeSide.SHORT
        if any(token in text for token in ("buy", "long", "bull", "买", "多")):
            return PaperTradeSide.LONG
        return None

    @staticmethod
    def _is_strong_action(action: str) -> bool:
        text = PaperTradingService._normalized_action_text(action)
        return any(token in text for token in ("strong", "强烈", "very"))

    @staticmethod
    def _normalized_action_text(action: str) -> str:
        text = (action or "").lower()
        try:
            repaired = text.encode("latin1").decode("utf-8").lower()
        except (UnicodeEncodeError, UnicodeDecodeError):
            repaired = ""
        combined = f"{text} {repaired}"
        if any(token in combined for token in ("\u5356", "\u7a7a")):
            combined += " sell short"
        if any(token in combined for token in ("\u4e70", "\u591a")):
            combined += " buy long"
        if "\u5f3a\u70c8" in combined:
            combined += " strong"
        return combined

    async def _resolve_entry_price(self, signal: TradingSignal) -> Optional[float]:
        for value in (signal.entry_price, signal.current_price):
            if value and value > 0:
                return float(value)
        return await self._get_current_price(signal.symbol)

    @staticmethod
    def _resolve_levels(
        signal: TradingSignal,
        side: PaperTradeSide,
        entry_price: float,
        cfg: Dict[str, float],
    ) -> Tuple[float, float]:
        stop_loss = float(signal.stop_loss) if signal.stop_loss else 0.0
        take_profit = float(signal.take_profit) if signal.take_profit else 0.0

        if side == PaperTradeSide.LONG:
            if not stop_loss or stop_loss >= entry_price:
                stop_loss = entry_price * (1 - cfg["default_stop_pct"])
            if not take_profit or take_profit <= entry_price:
                take_profit = entry_price * (1 + cfg["default_take_pct"])
        else:
            if not stop_loss or stop_loss <= entry_price:
                stop_loss = entry_price * (1 + cfg["default_stop_pct"])
            if not take_profit or take_profit >= entry_price:
                take_profit = entry_price * (1 - cfg["default_take_pct"])

        return stop_loss, take_profit

    @staticmethod
    def _levels_are_valid(
        side: PaperTradeSide, entry_price: float, stop_loss: float, take_profit: float
    ) -> bool:
        if side == PaperTradeSide.LONG:
            return stop_loss < entry_price < take_profit
        return take_profit < entry_price < stop_loss

    @staticmethod
    def _parse_analysis_type(value: str) -> AnalysisType:
        normalized = (value or "technical_only").lower()
        mapping = {
            "technical": AnalysisType.TECHNICAL_ONLY,
            "technical_only": AnalysisType.TECHNICAL_ONLY,
            "integrated": AnalysisType.INTEGRATED,
            "kronos_only": AnalysisType.KRONOS_ONLY,
            "ml_only": AnalysisType.ML_ONLY,
        }
        return mapping.get(normalized, AnalysisType.TECHNICAL_ONLY)

    def _portfolio_reject_reason(
        self,
        symbol: str,
        proposed_exposure_usdt: float = 0.0,
    ) -> Optional[str]:
        try:
            symbol = normalize_project_symbol(symbol)
        except ValueError:
            return "symbol_not_allowed"
        open_trades = [
            trade
            for trade in self.trades.values()
            if trade.status == PaperOrderStatus.OPEN
        ]
        if len(open_trades) >= self.max_open_positions:
            return "max_open_positions_reached"
        if any(trade.plan.symbol == symbol for trade in open_trades):
            return "duplicate_open_symbol"
        current_exposure = sum(
            trade.plan.position_size_usdt * trade.plan.leverage
            for trade in open_trades
        )
        max_exposure = self._last_equity_usdt * self.RISK_LIMITS["max_gross_exposure_pct"]
        if current_exposure + proposed_exposure_usdt > max_exposure:
            return "gross_exposure_limit_reached"
        if self._day_start_equity_usdt:
            daily_loss_ratio = max(
                0.0,
                (self._day_start_equity_usdt - self._last_equity_usdt)
                / self._day_start_equity_usdt,
            )
            if daily_loss_ratio >= self.RISK_LIMITS["daily_loss_pause_pct"]:
                return "daily_loss_limit_reached"
        if self.peak_equity_usdt:
            drawdown_ratio = max(
                0.0,
                (self.peak_equity_usdt - self._last_equity_usdt) / self.peak_equity_usdt,
            )
            if drawdown_ratio >= self.RISK_LIMITS["portfolio_drawdown_pause_pct"]:
                return "portfolio_drawdown_limit_reached"
        return None

    async def _mark_to_market_open_positions(self) -> Tuple[List[PaperTradeView], float]:
        open_views: List[PaperTradeView] = []
        unrealized_total = 0.0

        for trade in list(self.trades.values()):
            if trade.status != PaperOrderStatus.OPEN:
                continue

            price = await self._get_current_price(trade.plan.symbol)
            if not price:
                price = trade.plan.entry_price

            pnl_usdt, pnl_percent = self._pnl(trade, price)
            close_reason = self._exit_reason(trade, price)
            if not close_reason:
                close_reason = await self._dynamic_exit_reason(trade, price)
            if close_reason:
                self._close_trade(trade, price, close_reason)
                continue

            unrealized_total += pnl_usdt
            open_views.append(
                PaperTradeView(
                    **trade.model_dump(),
                    mark_price=round(price, 8),
                    unrealized_pnl_usdt=round(pnl_usdt, 4),
                    unrealized_pnl_percent=round(pnl_percent, 4),
                )
            )

        return open_views, unrealized_total

    def _close_trade(self, trade: PaperTradeRecord, price: float, reason: str) -> PaperTradeRecord:
        pnl_usdt, pnl_percent = self._pnl(trade, price)
        trade.status = PaperOrderStatus.CLOSED
        trade.exit_price = round(price, 8)
        trade.realized_pnl_usdt = round(pnl_usdt, 4)
        trade.realized_pnl_percent = round(pnl_percent, 4)
        trade.close_reason = reason
        trade.closed_at = datetime.now()
        trade.updated_at = datetime.now()
        self.balance_usdt += pnl_usdt
        return trade

    @staticmethod
    def _pnl(trade: PaperTradeRecord, price: float) -> Tuple[float, float]:
        plan = trade.plan
        if plan.side == PaperTradeSide.LONG:
            pnl = (price - plan.entry_price) * plan.quantity
        else:
            pnl = (plan.entry_price - price) * plan.quantity
        pnl_percent = (pnl / plan.position_size_usdt) * 100 if plan.position_size_usdt else 0.0
        return pnl, pnl_percent

    @staticmethod
    def _exit_reason(trade: PaperTradeRecord, price: float) -> Optional[str]:
        plan = trade.plan
        if plan.side == PaperTradeSide.LONG:
            if price <= plan.stop_loss:
                return "stop_loss"
            if price >= plan.take_profit:
                return "take_profit"
        else:
            if price >= plan.stop_loss:
                return "stop_loss"
            if price <= plan.take_profit:
                return "take_profit"
        return None

    async def _dynamic_exit_reason(self, trade: PaperTradeRecord, price: float) -> Optional[str]:
        if os.getenv("PAPER_TRADING_DYNAMIC_EXIT_ENABLED", "true").lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return None
        plan = trade.plan
        try:
            trading_service = await get_core_trading_service()
            signal = await trading_service.analyze_symbol(
                symbol=plan.symbol,
                analysis_type=AnalysisType.TECHNICAL_ONLY,
                force_update=True,
            )
        except Exception as exc:
            logger.debug("Dynamic exit analysis failed for %s: %s", plan.symbol, exc)
            return None
        if not signal:
            return None

        signal_side = self._action_to_side(signal.final_action)
        confidence = float(signal.final_confidence or 0.0)
        pnl_usdt, _ = self._pnl(trade, price)
        risk_usdt = max(plan.max_loss_usdt, 1e-9)

        if signal_side and signal_side != plan.side and confidence >= 0.55:
            return "signal_reversal"
        if plan.side == PaperTradeSide.LONG and signal_side != PaperTradeSide.LONG and pnl_usdt > risk_usdt * 0.35:
            return "signal_fade_take_profit"
        if plan.side == PaperTradeSide.SHORT and signal_side != PaperTradeSide.SHORT and pnl_usdt > risk_usdt * 0.35:
            return "signal_fade_take_profit"
        return None

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        exchange = await get_current_exchange_service()
        if exchange is None:
            await start_exchange_services()
            exchange = await get_current_exchange_service()
        if exchange is None:
            return None
        return await exchange.get_current_price(symbol)

    def _current_equity_snapshot(self) -> float:
        return max(0.0, self.balance_usdt)

    @staticmethod
    def _normalize_symbols(symbols: List[str]) -> List[str]:
        seen = set()
        normalized = []
        for symbol in symbols:
            value = symbol.strip().upper()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @staticmethod
    def _invalidation_reason(side: PaperTradeSide, stop_loss: float) -> str:
        direction = "below" if side == PaperTradeSide.LONG else "above"
        return f"Close the paper trade if price moves {direction} {stop_loss:.8f}."

    @staticmethod
    def _plan_reasons(
        signal: TradingSignal, risk_reward_ratio: float, opportunity_score: float
    ) -> List[str]:
        reasons = [
            f"confidence={signal.final_confidence:.2%}",
            f"risk_reward={risk_reward_ratio:.2f}",
            f"opportunity_score={opportunity_score:.1f}",
        ]
        if signal.key_factors:
            reasons.extend(signal.key_factors[:3])
        return reasons

    @staticmethod
    def _source_signal(signal: TradingSignal) -> Dict[str, Any]:
        return {
            "symbol": signal.symbol,
            "final_action": signal.final_action,
            "final_confidence": signal.final_confidence,
            "signal_strength": getattr(signal.signal_strength, "value", str(signal.signal_strength)),
            "reasoning": signal.reasoning,
            "key_factors": signal.key_factors,
            "confidence_breakdown": signal.confidence_breakdown,
            "timestamp": signal.timestamp,
        }

    @staticmethod
    def _signal_agreement(signal: TradingSignal) -> float:
        breakdown = signal.confidence_breakdown or {}
        matrix = breakdown.get("decision_matrix")
        if not isinstance(matrix, dict):
            return 0.5

        side = PaperTradingService._action_to_side(signal.final_action)
        if not side:
            return 0.0

        votes = 0
        matches = 0
        for item in matrix.values():
            if not isinstance(item, dict):
                continue
            item_side = PaperTradingService._action_to_side(str(item.get("action")))
            if item_side:
                votes += 1
                if item_side == side:
                    matches += 1
        return matches / votes if votes else 0.5

    @staticmethod
    def _reject(
        signal: TradingSignal, reason: str, details: Optional[Dict[str, Any]] = None
    ) -> PaperRejectedSignal:
        merged_details = {
            "normalized_action": PaperTradingService._normalized_action_text(signal.final_action),
            "reasoning": signal.reasoning,
            "key_factors": signal.key_factors[:5] if signal.key_factors else [],
        }
        if details:
            merged_details.update(details)
        return PaperRejectedSignal(
            symbol=signal.symbol,
            reason=reason,
            action=signal.final_action,
            confidence=signal.final_confidence,
            details=merged_details,
        )

    @staticmethod
    def _normalize_klines(klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candles = []
        for item in klines:
            try:
                ts = int(item["timestamp"])
                if ts > 10_000_000_000:
                    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
                else:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                candles.append(
                    {
                        "time": dt,
                        "open": float(item["open"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "close": float(item["close"]),
                        "volume": float(item.get("volume", 0.0)),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(candles, key=lambda row: row["time"])

    @staticmethod
    def _ema(values: List[float], period: int) -> List[Optional[float]]:
        result: List[Optional[float]] = [None] * len(values)
        if period <= 1 or len(values) < period:
            return result
        alpha = 2 / (period + 1)
        ema_value = sum(values[:period]) / period
        result[period - 1] = ema_value
        for idx in range(period, len(values)):
            ema_value = values[idx] * alpha + ema_value * (1 - alpha)
            result[idx] = ema_value
        return result

    @staticmethod
    def _rsi(values: List[float], period: int) -> List[Optional[float]]:
        result: List[Optional[float]] = [None] * len(values)
        if period <= 1 or len(values) <= period:
            return result
        gains = []
        losses = []
        for idx in range(1, period + 1):
            change = values[idx] - values[idx - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        result[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
        for idx in range(period + 1, len(values)):
            change = values[idx] - values[idx - 1]
            gain = max(change, 0)
            loss = abs(min(change, 0))
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            result[idx] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
        return result

    def _strategy_signal(
        self,
        strategy: PaperBacktestStrategy,
        idx: int,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        ema_fast: List[Optional[float]],
        ema_slow: List[Optional[float]],
        rsi: List[Optional[float]],
        params: Dict[str, Any],
    ) -> Optional[PaperTradeSide]:
        if strategy == PaperBacktestStrategy.EMA_RSI:
            if not ema_fast[idx] or not ema_slow[idx] or rsi[idx] is None:
                return None
            long_rsi = float(params.get("long_rsi_max", 68))
            short_rsi = float(params.get("short_rsi_min", 32))
            if ema_fast[idx] > ema_slow[idx] and rsi[idx] < long_rsi:
                return PaperTradeSide.LONG
            if ema_fast[idx] < ema_slow[idx] and rsi[idx] > short_rsi:
                return PaperTradeSide.SHORT
            return None

        lookback = int(params.get("lookback", 20))
        if idx <= lookback:
            return None

        if strategy == PaperBacktestStrategy.BREAKOUT:
            previous_high = max(highs[idx - lookback:idx])
            previous_low = min(lows[idx - lookback:idx])
            if closes[idx] > previous_high:
                return PaperTradeSide.LONG
            if closes[idx] < previous_low:
                return PaperTradeSide.SHORT
            return None

        if strategy == PaperBacktestStrategy.MEAN_REVERSION:
            window = closes[idx - lookback:idx]
            average = sum(window) / lookback
            variance = sum((price - average) ** 2 for price in window) / lookback
            std = math.sqrt(variance)
            zscore = (closes[idx] - average) / std if std else 0.0
            threshold = float(params.get("zscore", 2.0))
            if zscore <= -threshold:
                return PaperTradeSide.LONG
            if zscore >= threshold:
                return PaperTradeSide.SHORT
        return None

    @staticmethod
    def _backtest_levels(
        entry_price: float,
        side: PaperTradeSide,
        cfg: Dict[str, float],
        atr_value: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float]:
        params = params or {}
        if atr_value and atr_value > 0:
            stop_mult = float(params.get("atr_stop_mult", 3.0))
            reward_mult = float(params.get("reward_r", 2.0))
            risk = atr_value * stop_mult
            if side == PaperTradeSide.LONG:
                return entry_price - risk, entry_price + risk * reward_mult
            return entry_price + risk, entry_price - risk * reward_mult
        if side == PaperTradeSide.LONG:
            return (
                entry_price * (1 - cfg["default_stop_pct"]),
                entry_price * (1 + cfg["default_take_pct"]),
            )
        return (
            entry_price * (1 + cfg["default_stop_pct"]),
            entry_price * (1 - cfg["default_take_pct"]),
        )

    @staticmethod
    def _apply_slippage(
        price: float, side: PaperTradeSide, slippage_rate: float, entry: bool
    ) -> float:
        if (side == PaperTradeSide.LONG and entry) or (side == PaperTradeSide.SHORT and not entry):
            return price * (1 + slippage_rate)
        return price * (1 - slippage_rate)

    def _backtest_exit_price(
        self, position: Dict[str, Any], candle: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[str]]:
        side = position["side"]
        if side == PaperTradeSide.LONG:
            if candle["low"] <= position["stop_loss"]:
                return position["stop_loss"], "stop_loss"
            if candle["high"] >= position["take_profit"]:
                return position["take_profit"], "take_profit"
        else:
            if candle["high"] >= position["stop_loss"]:
                return position["stop_loss"], "stop_loss"
            if candle["low"] <= position["take_profit"]:
                return position["take_profit"], "take_profit"
        return None, None

    def _backtest_proactive_exit_price(
        self,
        position: Dict[str, Any],
        idx: int,
        candle: Dict[str, Any],
        closes: List[float],
        ema_fast: List[Optional[float]],
        ema_slow: List[Optional[float]],
        rsi: List[Optional[float]],
    ) -> Tuple[Optional[float], Optional[str]]:
        side = position["side"]
        if side != PaperTradeSide.LONG:
            return None, None

        fast = ema_fast[idx]
        slow = ema_slow[idx]
        prev_fast = ema_fast[idx - 1] if idx > 0 else None
        prev_slow = ema_slow[idx - 1] if idx > 0 else None
        cur_rsi = rsi[idx]
        prev_rsi = rsi[idx - 1] if idx > 0 else None
        close = candle["close"]
        pnl = self._backtest_pnl(position, close)
        risk_usdt = max(position["risk_per_unit"] * position["quantity"], 1e-9)

        if fast is not None and slow is not None:
            if prev_fast is not None and prev_slow is not None and prev_fast >= prev_slow and fast < slow:
                return close, "trend_reversal"
            if close < slow and cur_rsi is not None and cur_rsi < 48:
                return close, "trend_breakdown"

        if pnl > risk_usdt * 0.35 and fast is not None and close < fast:
            if prev_rsi is not None and cur_rsi is not None and prev_rsi >= 55 and cur_rsi < 55:
                return close, "momentum_fade_take_profit"

        if len(closes) > 1 and pnl > 0 and close < closes[idx - 1] and fast is not None and close < fast:
            return close, "profit_protection"
        return None, None

    @staticmethod
    def _backtest_pnl(position: Optional[Dict[str, Any]], price: float) -> float:
        if not position:
            return 0.0
        if position["side"] == PaperTradeSide.LONG:
            return (price - position["entry_price"]) * position["quantity"]
        return (position["entry_price"] - price) * position["quantity"]

    @staticmethod
    def _backtest_metrics(
        initial_balance: float,
        final_balance: float,
        max_drawdown: float,
        trades: List[PaperBacktestTrade],
        equity_curve: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        wins = [trade for trade in trades if trade.pnl_usdt > 0]
        losses = [trade for trade in trades if trade.pnl_usdt < 0]
        gross_profit = sum(trade.pnl_usdt for trade in wins)
        gross_loss = abs(sum(trade.pnl_usdt for trade in losses))
        returns = []
        for prev, cur in zip(equity_curve, equity_curve[1:]):
            prev_equity = prev["equity"]
            returns.append((cur["equity"] - prev_equity) / prev_equity if prev_equity else 0.0)
        mean_return = sum(returns) / len(returns) if returns else 0.0
        variance = sum((item - mean_return) ** 2 for item in returns) / len(returns) if returns else 0.0
        sharpe = (mean_return / math.sqrt(variance) * math.sqrt(365 * 24)) if variance else 0.0
        return {
            "total_return_pct": round((final_balance / initial_balance - 1) * 100, 4),
            "max_drawdown_pct": round(max_drawdown * 100, 4),
            "sharpe_ratio": round(sharpe, 4),
            "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
        }

    @staticmethod
    def _backtest_warnings(metrics: Dict[str, Any], candles: int) -> List[str]:
        warnings = []
        if candles < 500:
            warnings.append("Sample is small; use a longer history before trusting the result.")
        if metrics["total_trades"] < 20:
            warnings.append("Trade count is low; performance may not be statistically meaningful.")
        if metrics["max_drawdown_pct"] > 20:
            warnings.append("Drawdown is high; reduce risk or add a market-regime filter.")
        return warnings

    async def _ensure_exchange(self):
        exchange = await get_current_exchange_service()
        if exchange is None:
            await start_exchange_services()
            exchange = await get_current_exchange_service()
        if exchange is None:
            raise ValueError("exchange service is not available")
        return exchange

    async def _liquidity_reject_reason(
        self, symbol: str, bucket: PaperPortfolioBucket
    ) -> Optional[Dict[str, Any]]:
        try:
            exchange = await self._ensure_exchange()
            tickers = await exchange.get_tickers("SWAP")
            ticker = self._ticker_map(tickers).get(symbol.upper())
        except Exception as exc:
            logger.debug("Liquidity gate skipped for %s: %s", symbol, exc)
            return None
        if not ticker:
            return {"reason": "symbol_not_tradeable", "symbol": symbol}

        volume_usdt = self._ticker_volume_usdt(ticker)
        ranked_assets, source = await self._get_market_cap_ranked_assets()
        rank_by_base = {
            str(item.get("symbol", "")).upper(): int(item.get("market_cap_rank") or 9999)
            for item in ranked_assets
            if item.get("symbol")
        }
        rank = rank_by_base.get(self._base_asset(symbol))

        if bucket == PaperPortfolioBucket.CORE:
            if volume_usdt < self.MIN_CORE_VOLUME_USDT:
                return {
                    "reason": "core_volume_too_low",
                    "volume_24h_usdt": volume_usdt,
                    "min_volume_24h_usdt": self.MIN_CORE_VOLUME_USDT,
                    "market_cap_rank": rank,
                    "market_cap_source": source,
                }
            if rank and rank > self.MAX_CORE_MARKET_CAP_RANK:
                return {
                    "reason": "core_market_cap_rank_too_low",
                    "volume_24h_usdt": volume_usdt,
                    "market_cap_rank": rank,
                    "max_market_cap_rank": self.MAX_CORE_MARKET_CAP_RANK,
                    "market_cap_source": source,
                }
            return None

        min_volume = (
            self.MIN_SATELLITE_VOLUME_USDT
            if rank and rank <= self.MAX_SATELLITE_MARKET_CAP_RANK
            else self.MIN_UNRANKED_SATELLITE_VOLUME_USDT
        )
        if volume_usdt < min_volume:
            return {
                "reason": "satellite_volume_too_low",
                "volume_24h_usdt": volume_usdt,
                "min_volume_24h_usdt": min_volume,
                "market_cap_rank": rank,
                "market_cap_source": source,
            }
        if rank and rank > self.MAX_SATELLITE_MARKET_CAP_RANK:
            return {
                "reason": "satellite_market_cap_rank_too_low",
                "volume_24h_usdt": volume_usdt,
                "market_cap_rank": rank,
                "max_market_cap_rank": self.MAX_SATELLITE_MARKET_CAP_RANK,
                "market_cap_source": source,
            }
        return None

    @staticmethod
    def _ticker_map(tickers: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        result = {}
        for ticker in tickers:
            symbol = str(ticker.get("symbol") or ticker.get("instId") or "").upper()
            if symbol.endswith("-USDT-SWAP"):
                result[symbol] = ticker
        return result

    async def _get_market_cap_ranked_assets(self) -> Tuple[List[Dict[str, Any]], str]:
        cached_assets, cached_at = self._market_cap_cache
        if cached_assets and datetime.now() - cached_at < self.MARKET_CAP_CACHE_TTL:
            return cached_assets, "coingecko_market_cap_cache"

        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": "250",
            "page": "1",
            "sparkline": "false",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        return [], "coingecko_error"
                    data = await response.json()
                    if isinstance(data, list):
                        self._market_cap_cache = (data, datetime.now())
                        return data, "coingecko_market_cap"
        except Exception as exc:
            logger.warning("CoinGecko market cap fetch failed: %s", exc)
        return [], "coingecko_unavailable"

    def _build_core_universe(
        self,
        ticker_map: Dict[str, Dict[str, Any]],
        ranked_assets: List[Dict[str, Any]],
        max_symbols: int,
    ) -> List[PaperUniverseAsset]:
        assets: List[PaperUniverseAsset] = []
        seen = set()

        for symbol in self.pinned_core_symbols:
            if symbol in ticker_map and symbol not in seen:
                assets.append(self._universe_asset(symbol, PaperPortfolioBucket.CORE, ticker_map[symbol], 100, "pinned core symbol"))
                seen.add(symbol)

        for item in ranked_assets:
            base = str(item.get("symbol", "")).upper()
            if base in self.STABLE_OR_WRAPPED_ASSETS:
                continue
            symbol = f"{base}-USDT-SWAP"
            if symbol not in ticker_map or symbol in seen:
                continue
            rank = int(item.get("market_cap_rank") or 999)
            if rank > self.MAX_CORE_MARKET_CAP_RANK:
                continue
            assets.append(
                self._universe_asset(
                    symbol,
                    PaperPortfolioBucket.CORE,
                    ticker_map[symbol],
                    max(0.0, 100 - rank),
                    f"market cap rank #{rank}",
                    market_cap_rank=rank,
                )
            )
            seen.add(symbol)
            if len(assets) >= max_symbols:
                break
        return assets[:max_symbols]

    def _build_volume_core_universe(
        self,
        ticker_map: Dict[str, Dict[str, Any]],
        max_symbols: int,
    ) -> List[PaperUniverseAsset]:
        ranked = sorted(
            ticker_map.items(),
            key=lambda item: self._ticker_volume_usdt(item[1]),
            reverse=True,
        )
        assets = []
        for symbol, ticker in ranked:
            base = self._base_asset(symbol)
            if base in self.STABLE_OR_WRAPPED_ASSETS:
                continue
            assets.append(
                self._universe_asset(
                    symbol,
                    PaperPortfolioBucket.CORE,
                    ticker,
                    self._ticker_volume_usdt(ticker) / 1_000_000,
                    "fallback top quote volume",
                )
            )
            if len(assets) >= max_symbols:
                break
        return assets

    def _build_satellite_universe(
        self,
        ticker_map: Dict[str, Dict[str, Any]],
        excluded_symbols: set,
        max_symbols: int,
    ) -> List[PaperUniverseAsset]:
        candidates = []
        rank_by_base = {
            str(item.get("symbol", "")).upper(): int(item.get("market_cap_rank") or 9999)
            for item in self._market_cap_cache[0]
            if item.get("symbol")
        }
        for symbol, ticker in ticker_map.items():
            base = self._base_asset(symbol)
            if symbol in excluded_symbols or base in self.STABLE_OR_WRAPPED_ASSETS:
                continue
            volume_usdt = self._ticker_volume_usdt(ticker)
            change_pct = self._ticker_change_percent(ticker)
            price = self._ticker_price(ticker)
            market_cap_rank = rank_by_base.get(base)
            min_volume = (
                self.MIN_SATELLITE_VOLUME_USDT
                if market_cap_rank and market_cap_rank <= self.MAX_SATELLITE_MARKET_CAP_RANK
                else self.MIN_UNRANKED_SATELLITE_VOLUME_USDT
            )
            if volume_usdt < min_volume or price <= 0:
                continue
            if market_cap_rank and market_cap_rank > self.MAX_SATELLITE_MARKET_CAP_RANK:
                continue
            range_pct = self._ticker_range_percent(ticker)
            momentum = max(0.0, change_pct)
            score = momentum * 3 + min(volume_usdt / 10_000_000, 50) + range_pct
            if change_pct < 2.0 and range_pct < 5.0:
                continue
            candidates.append((score, symbol, ticker, market_cap_rank))

        candidates.sort(reverse=True, key=lambda item: item[0])
        return [
            self._universe_asset(
                symbol,
                PaperPortfolioBucket.SATELLITE,
                ticker,
                score,
                "high liquidity plus positive momentum/range expansion",
                market_cap_rank=market_cap_rank,
            )
            for score, symbol, ticker, market_cap_rank in candidates[:max_symbols]
        ]

    def _universe_asset(
        self,
        symbol: str,
        bucket: PaperPortfolioBucket,
        ticker: Dict[str, Any],
        score: float,
        reason: str,
        market_cap_rank: Optional[int] = None,
    ) -> PaperUniverseAsset:
        return PaperUniverseAsset(
            symbol=symbol,
            bucket=bucket,
            base_asset=self._base_asset(symbol),
            price=round(self._ticker_price(ticker), 8),
            volume_24h_usdt=round(self._ticker_volume_usdt(ticker), 4),
            change_percent_24h=round(self._ticker_change_percent(ticker), 4),
            score=round(score, 4),
            reason=reason,
            market_cap_rank=market_cap_rank,
            max_leverage=self._max_leverage_for_symbol(symbol, bucket),
            risk_pct=(
                self.RISK_LIMITS["core_trade_risk_pct"]
                if bucket == PaperPortfolioBucket.CORE
                else self.RISK_LIMITS["satellite_trade_risk_pct"]
            ),
        )

    @staticmethod
    def _base_asset(symbol: str) -> str:
        return symbol.split("-")[0].upper()

    @staticmethod
    def _ticker_price(ticker: Dict[str, Any]) -> float:
        for key in ("price", "last", "lastPrice"):
            try:
                value = float(ticker.get(key, 0) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue
        return 0.0

    def _ticker_volume_usdt(self, ticker: Dict[str, Any]) -> float:
        for key in ("quote_volume_24h", "quoteVolume", "volCcy24h"):
            try:
                value = float(ticker.get(key, 0) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue
        try:
            return float(ticker.get("volume_24h", 0) or ticker.get("volume", 0) or 0) * self._ticker_price(ticker)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _ticker_change_percent(ticker: Dict[str, Any]) -> float:
        for key in ("change_percent_24h", "priceChangePercent"):
            try:
                return float(ticker.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
        return 0.0

    def _ticker_range_percent(self, ticker: Dict[str, Any]) -> float:
        price = self._ticker_price(ticker)
        if price <= 0:
            return 0.0
        try:
            high = float(ticker.get("high_24h", 0) or ticker.get("highPrice", 0) or 0)
            low = float(ticker.get("low_24h", 0) or ticker.get("lowPrice", 0) or 0)
            return max(0.0, (high - low) / price * 100)
        except (TypeError, ValueError):
            return 0.0

    def _bucket_for_symbol(self, symbol: str) -> PaperPortfolioBucket:
        if symbol.upper() in self.pinned_core_symbols:
            return PaperPortfolioBucket.CORE
        return PaperPortfolioBucket.SATELLITE

    def _max_leverage_for_symbol(self, symbol: str, bucket: PaperPortfolioBucket) -> float:
        if bucket == PaperPortfolioBucket.SATELLITE:
            return self.LEVERAGE_LIMITS["satellite"]
        if self._base_asset(symbol) in {"ZEC", "DOGE", "SOL"}:
            return self.LEVERAGE_LIMITS["high_volatility_core"]
        return self.LEVERAGE_LIMITS["core"]

    @staticmethod
    def _liquidation_distance_ok(entry_price: float, stop_loss: float, leverage: float) -> bool:
        if leverage <= 1:
            return True
        stop_distance = abs(entry_price - stop_loss) / entry_price
        rough_liquidation_distance = 1 / leverage
        return stop_distance < rough_liquidation_distance * 0.70

    @staticmethod
    def _strategy_for_bucket(
        bucket: PaperPortfolioBucket, strategies: List[PaperBacktestStrategy]
    ) -> PaperBacktestStrategy:
        preferred = PaperBacktestStrategy.EMA_RSI if bucket == PaperPortfolioBucket.CORE else PaperBacktestStrategy.BREAKOUT
        return preferred if preferred in strategies else strategies[0]

    @staticmethod
    def _atr(candles: List[Dict[str, Any]], period: int) -> List[Optional[float]]:
        result: List[Optional[float]] = [None] * len(candles)
        if len(candles) <= period:
            return result
        true_ranges = []
        for idx, candle in enumerate(candles):
            if idx == 0:
                true_ranges.append(candle["high"] - candle["low"])
            else:
                prev_close = candles[idx - 1]["close"]
                true_ranges.append(
                    max(
                        candle["high"] - candle["low"],
                        abs(candle["high"] - prev_close),
                        abs(candle["low"] - prev_close),
                    )
                )
        atr_value = sum(true_ranges[1:period + 1]) / period
        result[period] = atr_value
        for idx in range(period + 1, len(candles)):
            atr_value = (atr_value * (period - 1) + true_ranges[idx]) / period
            result[idx] = atr_value
        return result

    def _update_trailing_stop(
        self,
        position: Dict[str, Any],
        candle: Dict[str, Any],
        atr_value: Optional[float],
        params: Dict[str, Any],
    ) -> None:
        if not atr_value or position["side"] != PaperTradeSide.LONG:
            return
        trail_mult = float(params.get("atr_trail_mult", 2.5))
        new_stop = candle["high"] - atr_value * trail_mult
        position["stop_loss"] = max(position["stop_loss"], new_stop)

    @staticmethod
    def _partial_take_profit_price(
        position: Dict[str, Any], candle: Dict[str, Any]
    ) -> Optional[float]:
        if position["side"] != PaperTradeSide.LONG:
            return None
        target = position["entry_price"] + position["risk_per_unit"]
        if candle["high"] >= target:
            return target
        return None

    @staticmethod
    def _merge_equity_curves(
        curves: List[Tuple[float, List[Dict[str, Any]]]], cash_balance: float
    ) -> List[Dict[str, Any]]:
        if not curves:
            return []
        min_len = min(len(curve) for _, curve in curves if curve)
        merged = []
        for idx in range(min_len):
            ts = curves[0][1][idx]["timestamp"]
            equity = cash_balance + sum(curve[idx]["equity"] for _, curve in curves if curve)
            merged.append({"timestamp": ts, "equity": round(equity, 4)})
        peak = 0.0
        for item in merged:
            peak = max(peak, item["equity"])
            item["drawdown_pct"] = round((peak - item["equity"]) / peak * 100, 4) if peak else 0.0
        return merged

    def _portfolio_metrics(
        self,
        initial_balance: float,
        final_balance: float,
        trades: List[PaperBacktestTrade],
        equity_curve: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        max_drawdown = max((row.get("drawdown_pct", 0) for row in equity_curve), default=0) / 100
        return self._backtest_metrics(initial_balance, final_balance, max_drawdown, trades, equity_curve)

    def _split_equity_metrics(
        self,
        initial_balance: float,
        equity_curve: List[Dict[str, Any]],
        sample_split: float,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if len(equity_curve) < 2:
            empty = {"return_pct": 0.0, "max_drawdown_pct": 0.0, "points": len(equity_curve)}
            return empty, empty
        split_idx = max(1, min(len(equity_curve) - 1, int(len(equity_curve) * sample_split)))
        first = equity_curve[:split_idx]
        second = equity_curve[split_idx:]
        return (
            self._curve_summary(initial_balance, first),
            self._curve_summary(first[-1]["equity"], second),
        )

    @staticmethod
    def _curve_summary(start_equity: float, curve: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not curve or start_equity <= 0:
            return {"return_pct": 0.0, "max_drawdown_pct": 0.0, "points": 0}
        end_equity = curve[-1]["equity"]
        return {
            "return_pct": round((end_equity / start_equity - 1) * 100, 4),
            "max_drawdown_pct": round(max(row.get("drawdown_pct", 0) for row in curve), 4),
            "points": len(curve),
        }

    @staticmethod
    def _portfolio_warnings(
        metrics: Dict[str, Any], contributions: List[PaperSymbolContribution]
    ) -> List[str]:
        warnings = []
        if metrics["total_trades"] < 20:
            warnings.append("Portfolio trade count is low; keep this in paper mode.")
        if metrics["max_drawdown_pct"] > 8:
            warnings.append("Portfolio drawdown breached the planned 8% pause threshold.")
        if not contributions:
            warnings.append("No tradable symbols were backtested.")
        return warnings

    def _ensure_history_table(self) -> None:
        if self._history_table_ready:
            return
        engine = get_engine()
        if engine is None:
            raise RuntimeError("database is not available for backtest history")
        PaperBacktestRun.__table__.create(bind=engine, checkfirst=True)
        self._history_table_ready = True

    def _ensure_forward_table(self) -> None:
        if self._forward_table_ready:
            return
        engine = get_engine()
        if engine is None:
            raise RuntimeError("database is not available for forward paper snapshots")
        PaperForwardSnapshot.__table__.create(bind=engine, checkfirst=True)
        self._forward_table_ready = True

    def _ensure_forward_session_table(self) -> None:
        if self._forward_session_table_ready:
            return
        engine = get_engine()
        if engine is None:
            raise RuntimeError("database is not available for forward paper sessions")
        PaperForwardSession.__table__.create(bind=engine, checkfirst=True)
        self._forward_session_table_ready = True

    async def _forward_runner_loop(self) -> None:
        cfg = self._runner_config
        next_scan_ts = 0.0
        try:
            while self._runner_stop_event and not self._runner_stop_event.is_set():
                now_ts = datetime.now().timestamp()
                status = await self.tick()
                self._runner_last_tick_at = datetime.now()
                self._runner_loop_count += 1
                self._record_forward_snapshot(status)

                if now_ts >= next_scan_ts:
                    risk = await self.get_risk_status()
                    if risk.trading_paused:
                        self._runner_last_scan_summary = {
                            "skipped": True,
                            "pause_reasons": risk.pause_reasons,
                        }
                    else:
                        universe = await self.get_universe(
                            max_core_symbols=cfg.max_core_symbols,
                            max_satellite_symbols=cfg.max_satellite_symbols,
                        )
                        symbols = [asset.symbol for asset in universe.core + universe.satellite]
                        self._runner_last_symbols = symbols
                        scan = await self.scan_and_trade(
                            symbols=symbols,
                            mode=cfg.mode,
                            dry_run=False,
                            force_update=cfg.force_update,
                            analysis_type=cfg.analysis_type,
                            long_only=True,
                        )
                        probe_opened: List[PaperTradeRecord] = []
                        probe_rejected: List[PaperRejectedSignal] = []
                        if (
                            cfg.momentum_probe_enabled
                            and scan.opened_count == 0
                            and all(item.reason == "not_actionable" for item in scan.rejected)
                        ):
                            probe_opened, probe_rejected = await self._open_probe_trades(universe, scan.rejected)
                        self._runner_scan_count += 1
                        opened_count = scan.opened_count + len(probe_opened)
                        rejected_count = len(scan.rejected) + len(probe_rejected)
                        self._runner_opened_count += opened_count
                        self._runner_rejected_count += rejected_count
                        self._runner_last_scan_at = datetime.now()
                        self._runner_last_scan_summary = {
                            "scanned_symbols": scan.scanned_symbols,
                            "opened_count": opened_count,
                            "candidate_count": len(scan.candidate_plans),
                            "probe_opened_count": len(probe_opened),
                            "probe_rejected_count": len(probe_rejected),
                            "rejected_count": rejected_count,
                            "rejected_reasons": self._rejection_reason_counts(scan.rejected + probe_rejected),
                            "rejected_samples": self._rejection_samples(scan.rejected + probe_rejected),
                            "opened_symbols": [trade.plan.symbol for trade in probe_opened + scan.opened_trades],
                        }
                    next_scan_ts = datetime.now().timestamp() + cfg.scan_interval_seconds
                    self._runner_next_scan_at = datetime.fromtimestamp(next_scan_ts)

                sleep_seconds = max(1, min(cfg.tick_interval_seconds, max(1, next_scan_ts - datetime.now().timestamp())))
                try:
                    await asyncio.wait_for(self._runner_stop_event.wait(), timeout=sleep_seconds)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._runner_last_error = str(exc)
            logger.exception("Paper forward runner failed: %s", exc)
        finally:
            self._runner_state = PaperForwardRunnerState.STOPPED
            self._runner_stopped_at = datetime.now()

    def _record_forward_snapshot(self, status: PaperStatusResponse) -> None:
        try:
            self._ensure_forward_table()
            with get_db_session() as db:
                db.add(
                    PaperForwardSnapshot(
                        snapshot_id=str(uuid.uuid4()),
                        state=self._runner_state.value,
                        mode=status.mode.value,
                        analysis_type=self._runner_config.analysis_type,
                        equity_usdt=status.equity_usdt,
                        balance_usdt=status.balance_usdt,
                        realized_pnl_usdt=status.realized_pnl_usdt,
                        unrealized_pnl_usdt=status.unrealized_pnl_usdt,
                        open_positions=len(status.open_positions),
                        closed_trades=status.total_trades,
                        win_rate=status.win_rate,
                        scan_count=self._runner_scan_count,
                        open_positions_payload=self._model_payload(status.open_positions),
                        closed_trades_payload=self._model_payload(status.closed_trades),
                        runner_payload=self._model_payload(self.get_forward_runner_status()),
                    )
                )
        except Exception as exc:
            logger.warning("Failed to record paper forward snapshot: %s", exc)

    def _record_forward_session(self, status: PaperStatusResponse) -> None:
        if (
            self._runner_started_at is None
            and self._runner_scan_count <= 0
            and self._runner_opened_count <= 0
            and self._runner_rejected_count <= 0
            and not self.trades
        ):
            return
        try:
            self._ensure_forward_session_table()
            started = self._runner_started_at
            stopped = self._runner_stopped_at or datetime.now()
            duration = int((stopped - started).total_seconds()) if started else 0
            with get_db_session() as db:
                db.add(
                    PaperForwardSession(
                        session_id=str(uuid.uuid4()),
                        state=PaperForwardRunnerState.STOPPED.value,
                        mode=status.mode.value,
                        analysis_type=self._runner_config.analysis_type,
                        started_at=started,
                        stopped_at=stopped,
                        duration_seconds=duration,
                        scan_count=self._runner_scan_count,
                        opened_count=self._runner_opened_count,
                        rejected_count=self._runner_rejected_count,
                        final_equity_usdt=status.equity_usdt,
                        final_balance_usdt=status.balance_usdt,
                        realized_pnl_usdt=status.realized_pnl_usdt,
                        unrealized_pnl_usdt=status.unrealized_pnl_usdt,
                        open_positions=len(status.open_positions),
                        closed_trades=status.total_trades,
                        win_rate=status.win_rate,
                        open_positions_payload=self._model_payload(status.open_positions),
                        closed_trades_payload=self._model_payload(status.closed_trades),
                        runner_payload=self._model_payload(self.get_forward_runner_status()),
                        last_scan_summary=self._runner_last_scan_summary,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to record paper forward session: %s", exc)

    def _clear_forward_runtime(self) -> None:
        self.balance_usdt = self.initial_balance_usdt
        self.trades.clear()
        self.peak_equity_usdt = self.initial_balance_usdt
        self._risk_day = datetime.now().date()
        self._day_start_equity_usdt = self.initial_balance_usdt
        self._last_equity_usdt = self.initial_balance_usdt
        self._runner_task = None
        self._runner_stop_event = None
        self._runner_state = PaperForwardRunnerState.STOPPED
        self._runner_started_at = None
        self._runner_stopped_at = datetime.now()
        self._runner_last_tick_at = None
        self._runner_last_scan_at = None
        self._runner_next_scan_at = None
        self._runner_loop_count = 0
        self._runner_scan_count = 0
        self._runner_opened_count = 0
        self._runner_rejected_count = 0
        self._runner_last_error = None
        self._runner_last_symbols = []
        self._runner_last_scan_summary = {}

    async def _open_probe_trades(
        self, universe: PaperUniverseResponse, rejected_signals: List[PaperRejectedSignal]
    ) -> Tuple[List[PaperTradeRecord], List[PaperRejectedSignal]]:
        opened: List[PaperTradeRecord] = []
        rejected: List[PaperRejectedSignal] = []
        rejected_by_symbol = {item.symbol: item for item in rejected_signals}
        core_candidates = [
            asset
            for asset in universe.core
            if asset.symbol in self.pinned_core_symbols and asset.symbol in rejected_by_symbol
        ]
        core_candidates = sorted(
            core_candidates,
            key=lambda item: (
                self._hold_signal_score(rejected_by_symbol.get(item.symbol)),
                item.change_percent_24h,
                item.volume_24h_usdt,
            ),
            reverse=True,
        )
        for asset in core_candidates:
            if len(opened) >= 2:
                break
            signal_reject = rejected_by_symbol.get(asset.symbol)
            plan, reject = self._build_core_hold_probe_plan(asset, signal_reject)
            trade, trade_reject = self._try_open_probe_plan(plan, reject, "core_hold_probe")
            if trade:
                opened.append(trade)
            elif trade_reject:
                rejected.append(trade_reject)

        candidates = sorted(
            list(universe.satellite),
            key=lambda item: item.score,
            reverse=True,
        )
        for asset in candidates:
            if len(opened) >= 3:
                break
            plan, reject = self._build_momentum_probe_plan(asset)
            trade, trade_reject = self._try_open_probe_plan(plan, reject, "momentum_probe")
            if trade:
                opened.append(trade)
            elif trade_reject:
                rejected.append(trade_reject)
        return opened, rejected

    def _try_open_probe_plan(
        self,
        plan: Optional[PaperTradePlan],
        reject: Optional[PaperRejectedSignal],
        source: str,
    ) -> Tuple[Optional[PaperTradeRecord], Optional[PaperRejectedSignal]]:
        if reject:
            return None, reject
        if not plan:
            return None, PaperRejectedSignal(symbol="UNKNOWN", reason=f"{source}_no_plan")
        reject_reason = self._portfolio_reject_reason(
            plan.symbol,
            plan.position_size_usdt * plan.leverage,
        )
        if reject_reason:
            return None, PaperRejectedSignal(
                symbol=plan.symbol,
                reason=reject_reason,
                action=source,
                confidence=plan.confidence,
                opportunity_score=plan.opportunity_score,
                details={"source": source},
            )
        trade = PaperTradeRecord(id=str(uuid.uuid4()), plan=plan)
        self.trades[trade.id] = trade
        return trade, None

    def _build_core_hold_probe_plan(
        self, asset: PaperUniverseAsset, signal_reject: Optional[PaperRejectedSignal]
    ) -> Tuple[Optional[PaperTradePlan], Optional[PaperRejectedSignal]]:
        if asset.price <= 0:
            return None, PaperRejectedSignal(symbol=asset.symbol, reason="core_probe_missing_price")
        score = self._hold_signal_score(signal_reject)
        min_score = 60.0
        min_volume = 300_000_000
        if score < min_score:
            return None, PaperRejectedSignal(
                symbol=asset.symbol,
                reason="core_hold_score_too_low",
                action="core_hold_probe",
                confidence=signal_reject.confidence if signal_reject else 0.0,
                details={"hold_signal_score": score, "min_score": min_score},
            )
        if asset.volume_24h_usdt < min_volume:
            return None, PaperRejectedSignal(
                symbol=asset.symbol,
                reason="core_probe_volume_too_low",
                action="core_hold_probe",
                confidence=signal_reject.confidence if signal_reject else 0.0,
                details={"volume_24h_usdt": asset.volume_24h_usdt, "min_volume": min_volume},
            )
        stop_pct = 0.06
        take_pct = 0.12
        leverage = self._max_leverage_for_symbol(asset.symbol, asset.bucket)
        cfg = self._sizing_config_for_bucket(self.MODE_CONFIG[self._runner_config.mode], asset.bucket)
        cfg["max_position_usdt"] = min(cfg["max_position_usdt"], self._current_equity_snapshot() * 0.08)
        position_size_usdt = self._position_size_usdt(stop_pct, cfg)
        quantity = position_size_usdt * leverage / asset.price
        confidence = max(0.58, min(0.7, (signal_reject.confidence if signal_reject else 0.5) + score / 500))
        opportunity_score = min(100.0, 58 + score * 0.35 + max(0, asset.change_percent_24h) * 1.2)
        plan = PaperTradePlan(
            symbol=asset.symbol,
            side=PaperTradeSide.LONG,
            confidence=round(confidence, 4),
            opportunity_score=round(opportunity_score, 2),
            entry_price=round(asset.price, 8),
            stop_loss=round(asset.price * (1 - stop_pct), 8),
            take_profit=round(asset.price * (1 + take_pct), 8),
            risk_reward_ratio=round(take_pct / stop_pct, 4),
            position_size_usdt=round(position_size_usdt, 4),
            quantity=round(quantity, 10),
            max_loss_usdt=round(position_size_usdt * leverage * stop_pct, 4),
            leverage=leverage,
            invalidation_reason=f"Core hold probe exits if price loses {stop_pct:.1%}.",
            reasons=[
                "core_hold_probe",
                "empty core position converted from hold to starter long",
                f"hold_signal_score={score:.1f}",
                f"24h_change={asset.change_percent_24h:.2f}%",
                f"volume_24h_usdt={asset.volume_24h_usdt:.0f}",
            ],
            source_signal={
                "source": "core_hold_probe",
                "original_action": signal_reject.action if signal_reject else None,
                "original_confidence": signal_reject.confidence if signal_reject else None,
                "hold_signal_score": score,
                "reasoning": (signal_reject.details or {}).get("reasoning") if signal_reject else None,
            },
        )
        return plan, None

    @staticmethod
    def _hold_signal_score(reject: Optional[PaperRejectedSignal]) -> float:
        if not reject:
            return 0.0
        text = f"{reject.action or ''} {(reject.details or {}).get('reasoning', '')} {(reject.details or {}).get('normalized_action', '')}".lower()
        score = 0.0
        for token, value in (
            ("trend100", 35),
            ("趋势100", 35),
            ("trend90", 25),
            ("趋势90", 25),
            ("trend86", 20),
            ("趋势86", 20),
            ("momentum100", 30),
            ("动量100", 30),
            ("bollinger(buy)", 15),
            ("布林带(buy)", 15),
            ("buy", 10),
        ):
            if token in text:
                score += value
        if (reject.confidence or 0) >= 0.5:
            score += 10
        return min(100.0, score)

    def _build_momentum_probe_plan(
        self, asset: PaperUniverseAsset
    ) -> Tuple[Optional[PaperTradePlan], Optional[PaperRejectedSignal]]:
        if asset.price <= 0:
            return None, PaperRejectedSignal(symbol=asset.symbol, reason="probe_missing_price")
        min_change = 8.0 if asset.bucket == PaperPortfolioBucket.SATELLITE else 3.0
        min_score = 90.0 if asset.bucket == PaperPortfolioBucket.SATELLITE else 100.0
        min_volume = 30_000_000 if asset.bucket == PaperPortfolioBucket.SATELLITE else 300_000_000
        if asset.change_percent_24h < min_change:
            return None, PaperRejectedSignal(
                symbol=asset.symbol,
                reason="probe_momentum_too_weak",
                action="momentum_probe",
                confidence=0.0,
                details={"change_percent_24h": asset.change_percent_24h, "min_change": min_change},
            )
        if asset.score < min_score:
            return None, PaperRejectedSignal(
                symbol=asset.symbol,
                reason="probe_score_too_low",
                action="momentum_probe",
                confidence=0.0,
                details={"score": asset.score, "min_score": min_score},
            )
        if asset.volume_24h_usdt < min_volume:
            return None, PaperRejectedSignal(
                symbol=asset.symbol,
                reason="probe_volume_too_low",
                action="momentum_probe",
                confidence=0.0,
                details={"volume_24h_usdt": asset.volume_24h_usdt, "min_volume": min_volume},
            )

        stop_pct = 0.055 if asset.bucket == PaperPortfolioBucket.SATELLITE else 0.045
        take_pct = 0.11 if asset.bucket == PaperPortfolioBucket.SATELLITE else 0.09
        leverage = self._max_leverage_for_symbol(asset.symbol, asset.bucket)
        cfg = self._sizing_config_for_bucket(self.MODE_CONFIG[self._runner_config.mode], asset.bucket)
        position_size_usdt = self._position_size_usdt(stop_pct, cfg)
        quantity = position_size_usdt * leverage / asset.price
        confidence = min(0.72, 0.52 + min(asset.change_percent_24h, 50) / 250 + min(asset.score, 200) / 1000)
        opportunity_score = min(100.0, asset.score * 0.45 + asset.change_percent_24h * 0.8)
        plan = PaperTradePlan(
            symbol=asset.symbol,
            side=PaperTradeSide.LONG,
            confidence=round(confidence, 4),
            opportunity_score=round(opportunity_score, 2),
            entry_price=round(asset.price, 8),
            stop_loss=round(asset.price * (1 - stop_pct), 8),
            take_profit=round(asset.price * (1 + take_pct), 8),
            risk_reward_ratio=round(take_pct / stop_pct, 4),
            position_size_usdt=round(position_size_usdt, 4),
            quantity=round(quantity, 10),
            max_loss_usdt=round(position_size_usdt * leverage * stop_pct, 4),
            leverage=leverage,
            invalidation_reason=f"Momentum probe exits if price loses {stop_pct:.1%}.",
            reasons=[
                "momentum_probe",
                f"24h_change={asset.change_percent_24h:.2f}%",
                f"volume_24h_usdt={asset.volume_24h_usdt:.0f}",
                f"universe_score={asset.score:.1f}",
                asset.reason,
            ],
            source_signal={
                "source": "universe_momentum_probe",
                "bucket": asset.bucket.value,
                "base_asset": asset.base_asset,
                "change_percent_24h": asset.change_percent_24h,
                "volume_24h_usdt": asset.volume_24h_usdt,
                "score": asset.score,
            },
        )
        return plan, None

    @staticmethod
    def _rejection_reason_counts(rejected: List[PaperRejectedSignal]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in rejected:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts

    @staticmethod
    def _rejection_samples(rejected: List[PaperRejectedSignal], limit: int = 8) -> List[Dict[str, Any]]:
        samples = []
        for item in rejected[:limit]:
            samples.append(
                {
                    "symbol": item.symbol,
                    "reason": item.reason,
                    "action": item.action,
                    "confidence": item.confidence,
                    "details": item.details,
                }
            )
        return samples

    @staticmethod
    def _forward_session_item(row: PaperForwardSession) -> PaperForwardSessionItem:
        return PaperForwardSessionItem(
            session_id=row.session_id,
            state=PaperForwardRunnerState(row.state),
            mode=row.mode,
            analysis_type=row.analysis_type,
            started_at=row.started_at,
            stopped_at=row.stopped_at,
            duration_seconds=row.duration_seconds or 0,
            scan_count=row.scan_count or 0,
            opened_count=row.opened_count or 0,
            rejected_count=row.rejected_count or 0,
            final_equity_usdt=row.final_equity_usdt or 0.0,
            final_balance_usdt=row.final_balance_usdt or 0.0,
            realized_pnl_usdt=row.realized_pnl_usdt or 0.0,
            unrealized_pnl_usdt=row.unrealized_pnl_usdt or 0.0,
            open_positions=row.open_positions or 0,
            closed_trades=row.closed_trades or 0,
            win_rate=row.win_rate or 0.0,
            last_scan_summary=row.last_scan_summary or {},
        )

    def _save_backtest_run(self, **values: Any) -> PaperBacktestRun:
        self._ensure_history_table()
        clean_values = {
            key: value
            for key, value in values.items()
            if hasattr(PaperBacktestRun, key)
        }
        with get_db_session() as db:
            run = PaperBacktestRun(
                run_id=str(uuid.uuid4()),
                completed_at=datetime.now(),
                **clean_values,
            )
            db.add(run)
            db.flush()
            db.refresh(run)
            return run

    @staticmethod
    def _model_payload(model: Any) -> Any:
        if model is None:
            return None
        if isinstance(model, list):
            return [PaperTradingService._model_payload(item) for item in model]
        if isinstance(model, dict):
            return {key: PaperTradingService._model_payload(value) for key, value in model.items()}
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        if hasattr(model, "dict"):
            return model.dict()
        return model

    @staticmethod
    def _history_item_from_model(run: PaperBacktestRun) -> PaperBacktestHistoryItem:
        return PaperBacktestHistoryItem(
            run_id=run.run_id,
            run_type=run.run_type,
            title=run.title,
            symbol=run.symbol,
            symbols=run.symbols or ([] if not run.symbol else [run.symbol]),
            strategy=run.strategy,
            timeframe=run.timeframe,
            candles=run.candles or 0,
            mode=run.mode,
            initial_balance_usdt=run.initial_balance_usdt or 0.0,
            final_balance_usdt=run.final_balance_usdt or 0.0,
            total_return_pct=run.total_return_pct or 0.0,
            max_drawdown_pct=run.max_drawdown_pct or 0.0,
            sharpe_ratio=run.sharpe_ratio or 0.0,
            win_rate=run.win_rate or 0.0,
            profit_factor=run.profit_factor or 0.0,
            total_trades=run.total_trades or 0,
            completed_at=run.completed_at,
            warnings=run.warnings or [],
        )

    @staticmethod
    def _leaderboard_score(result: PaperBacktestResponse) -> float:
        trade_penalty = 10 if result.total_trades < 5 else 0
        return round(
            result.total_return_pct * 2
            + result.sharpe_ratio * 5
            + result.win_rate * 20
            - result.max_drawdown_pct * 1.5
            - trade_penalty,
            4,
        )


_paper_trading_service: Optional[PaperTradingService] = None


def get_paper_trading_service() -> PaperTradingService:
    global _paper_trading_service
    if _paper_trading_service is None:
        _paper_trading_service = PaperTradingService()
    return _paper_trading_service

