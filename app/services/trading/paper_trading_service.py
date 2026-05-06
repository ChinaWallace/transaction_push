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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.schemas.paper_trading import (
    PaperExecutionMode,
    PaperBacktestRequest,
    PaperBacktestResponse,
    PaperBacktestStrategy,
    PaperBacktestTrade,
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

    ALLOCATION = {"core": 0.60, "satellite": 0.30, "cash": 0.10}
    LEVERAGE_LIMITS = {"core": 3.0, "satellite": 1.5, "high_volatility_core": 2.0}
    RISK_LIMITS = {
        "core_trade_risk_pct": 0.006,
        "satellite_trade_risk_pct": 0.0025,
        "daily_loss_pause_pct": 0.02,
        "portfolio_drawdown_pause_pct": 0.08,
    }
    STABLE_OR_WRAPPED_ASSETS = {
        "USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDP", "USDE", "WBTC", "WETH",
        "BUSD", "FRAX", "LUSD", "PYUSD",
    }
    DEFAULT_PINNED_CORE = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "ZEC-USDT-SWAP"]

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
        self.max_open_positions = self._env_int("PAPER_TRADING_MAX_OPEN_POSITIONS", 5)
        self.execution_mode = self._parse_execution_mode(
            os.getenv("PAPER_TRADING_EXECUTION_MODE", PaperExecutionMode.PAPER.value)
        )
        self.pinned_core_symbols = self._parse_symbol_env(
            "PAPER_TRADING_PINNED_CORE_SYMBOLS",
            self.DEFAULT_PINNED_CORE,
        )
        self.trades: Dict[str, PaperTradeRecord] = {}
        self._lock = asyncio.Lock()

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
            return default
        symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
        return symbols or default

    async def scan_and_trade(
        self,
        symbols: List[str],
        mode: PaperTradingMode = PaperTradingMode.BALANCED,
        dry_run: bool = True,
        force_update: bool = False,
        analysis_type: str = "technical_only",
        long_only: bool = True,
    ) -> PaperScanResponse:
        candidate_plans: List[PaperTradePlan] = []
        opened_trades: List[PaperTradeRecord] = []
        rejected: List[PaperRejectedSignal] = []

        if not self.enabled:
            return PaperScanResponse(
                mode=mode,
                dry_run=dry_run,
                scanned_symbols=len(symbols),
                opened_count=0,
                rejected=[
                    PaperRejectedSignal(symbol=symbol, reason="paper_trading_disabled")
                    for symbol in symbols
                ],
            )

        await self._mark_to_market_open_positions()

        trading_service = await get_core_trading_service()
        analysis_enum = self._parse_analysis_type(analysis_type)

        for symbol in self._normalize_symbols(symbols):
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
                    reject_reason = self._portfolio_reject_reason(symbol)
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
            scanned_symbols=len(symbols),
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
        return {
            "status": "reset",
            "initial_balance_usdt": self.initial_balance_usdt,
            "timestamp": datetime.now(),
        }

    async def tick(self) -> PaperStatusResponse:
        await self._mark_to_market_open_positions()
        return await self.get_status()

    async def get_universe(
        self,
        max_core_symbols: int = 10,
        max_satellite_symbols: int = 8,
    ) -> PaperUniverseResponse:
        exchange = await self._ensure_exchange()
        tickers = await exchange.get_tickers("SWAP")
        ticker_map = self._ticker_map(tickers)
        warnings: List[str] = []

        ranked_assets, source = await self._get_market_cap_ranked_assets()
        core = self._build_core_universe(
            ticker_map=ticker_map,
            ranked_assets=ranked_assets,
            max_symbols=max_core_symbols,
        )
        if not core:
            source = "binance_volume_fallback"
            warnings.append("CoinGecko ranking unavailable; core universe fell back to Binance volume.")
            core = self._build_volume_core_universe(ticker_map, max_core_symbols)

        core_symbols = {asset.symbol for asset in core}
        satellite = self._build_satellite_universe(
            ticker_map=ticker_map,
            excluded_symbols=core_symbols,
            max_symbols=max_satellite_symbols,
        )

        return PaperUniverseResponse(
            core=core,
            satellite=satellite,
            cash_allocation=self.ALLOCATION["cash"],
            allocation=dict(self.ALLOCATION),
            source=source,
            execution_mode=self.execution_mode,
            warnings=warnings,
        )

    async def get_risk_status(self) -> PaperRiskStatusResponse:
        status = await self.get_status()
        gross_exposure = sum(
            trade.plan.position_size_usdt * trade.plan.leverage
            for trade in status.open_positions
            if trade.status == PaperOrderStatus.OPEN
        )
        exposure_ratio = gross_exposure / status.equity_usdt if status.equity_usdt else 0.0
        pause_reasons = []
        if len(status.open_positions) >= self.max_open_positions:
            pause_reasons.append("max_open_positions_reached")
        if exposure_ratio > 1.0:
            pause_reasons.append("gross_exposure_above_equity")
        if status.realized_pnl_usdt <= -self.initial_balance_usdt * self.RISK_LIMITS["daily_loss_pause_pct"]:
            pause_reasons.append("daily_loss_limit_reached")

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
        core_symbols = self._normalize_symbols(request.core_symbols or [asset.symbol for asset in universe.core])
        satellite_symbols = self._normalize_symbols(
            request.satellite_symbols or [asset.symbol for asset in universe.satellite]
        )

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
                max_core_symbols=min(10, request.max_symbols),
                max_satellite_symbols=max(0, request.max_symbols - 10),
            )
            symbols = [asset.symbol for asset in universe.core + universe.satellite]
            warnings.extend(universe.warnings)
        symbols = self._normalize_symbols(symbols)[:request.max_symbols]

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

    async def run_backtest(self, request: PaperBacktestRequest) -> PaperBacktestResponse:
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
        use_atr_exits = bool(request.parameters.get("use_atr_exits", False))
        partial_take_profit = bool(request.parameters.get("partial_take_profit", False))
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

        position_size_usdt = self._position_size_usdt(stop_distance_pct, cfg)
        bucket = self._bucket_for_symbol(signal.symbol)
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

    def _portfolio_reject_reason(self, symbol: str) -> Optional[str]:
        open_trades = [
            trade
            for trade in self.trades.values()
            if trade.status == PaperOrderStatus.OPEN
        ]
        if len(open_trades) >= self.max_open_positions:
            return "max_open_positions_reached"
        if any(trade.plan.symbol == symbol for trade in open_trades):
            return "duplicate_open_symbol"
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
        return PaperRejectedSignal(
            symbol=signal.symbol,
            reason=reason,
            action=signal.final_action,
            confidence=signal.final_confidence,
            details=details or {},
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

    @staticmethod
    def _ticker_map(tickers: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        result = {}
        for ticker in tickers:
            symbol = str(ticker.get("symbol") or ticker.get("instId") or "").upper()
            if symbol.endswith("-USDT-SWAP"):
                result[symbol] = ticker
        return result

    async def _get_market_cap_ranked_assets(self) -> Tuple[List[Dict[str, Any]], str]:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": "25",
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
        for symbol, ticker in ticker_map.items():
            base = self._base_asset(symbol)
            if symbol in excluded_symbols or base in self.STABLE_OR_WRAPPED_ASSETS:
                continue
            volume_usdt = self._ticker_volume_usdt(ticker)
            change_pct = self._ticker_change_percent(ticker)
            price = self._ticker_price(ticker)
            if volume_usdt < 10_000_000 or price <= 0:
                continue
            range_pct = self._ticker_range_percent(ticker)
            momentum = max(0.0, change_pct)
            score = momentum * 3 + min(volume_usdt / 10_000_000, 50) + range_pct
            if change_pct < 2.0 and range_pct < 5.0:
                continue
            candidates.append((score, symbol, ticker))

        candidates.sort(reverse=True, key=lambda item: item[0])
        return [
            self._universe_asset(
                symbol,
                PaperPortfolioBucket.SATELLITE,
                ticker,
                score,
                "high liquidity plus positive momentum/range expansion",
            )
            for score, symbol, ticker in candidates[:max_symbols]
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
