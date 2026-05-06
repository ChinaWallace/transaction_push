# -*- coding: utf-8 -*-
"""
Paper trading orchestration service.

The service turns analysis signals into simulated trades behind explicit risk
gates. It never calls exchange order APIs.
"""

import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.schemas.paper_trading import (
    PaperOrderStatus,
    PaperRejectedSignal,
    PaperScanResponse,
    PaperTradePlan,
    PaperTradeRecord,
    PaperTradeSide,
    PaperTradeView,
    PaperTradingMode,
    PaperStatusResponse,
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

    async def scan_and_trade(
        self,
        symbols: List[str],
        mode: PaperTradingMode = PaperTradingMode.BALANCED,
        dry_run: bool = True,
        force_update: bool = False,
        analysis_type: str = "technical_only",
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

                plan, reject = await self._build_plan(signal, mode)
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

    async def _build_plan(
        self, signal: TradingSignal, mode: PaperTradingMode
    ) -> Tuple[Optional[PaperTradePlan], Optional[PaperRejectedSignal]]:
        cfg = self.MODE_CONFIG[mode]
        side = self._action_to_side(signal.final_action)
        if not side:
            return None, self._reject(signal, "not_actionable")

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
        quantity = position_size_usdt / entry_price
        max_loss_usdt = position_size_usdt * stop_distance_pct
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
            leverage=1.0,
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
        return f"{text} {repaired}"

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


_paper_trading_service: Optional[PaperTradingService] = None


def get_paper_trading_service() -> PaperTradingService:
    global _paper_trading_service
    if _paper_trading_service is None:
        _paper_trading_service = PaperTradingService()
    return _paper_trading_service
