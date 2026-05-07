# -*- coding: utf-8 -*-
"""Paper trading persistence models."""

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String
from sqlalchemy.sql import func

from app.models.base import BaseModel


class PaperBacktestRun(BaseModel):
    """Stored paper backtest result for dashboard comparison."""

    __tablename__ = "paper_backtest_runs"

    run_id = Column(String(36), unique=True, index=True, nullable=False)
    run_type = Column(String(20), index=True, nullable=False)
    title = Column(String(200), nullable=False)

    symbol = Column(String(40), index=True)
    symbols = Column(JSON)
    strategy = Column(String(50), index=True)
    timeframe = Column(String(20), index=True)
    candles = Column(Integer, default=0)
    mode = Column(String(20))

    initial_balance_usdt = Column(Float, default=0.0)
    final_balance_usdt = Column(Float, default=0.0)
    total_return_pct = Column(Float, default=0.0, index=True)
    max_drawdown_pct = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)

    request_payload = Column(JSON)
    summary = Column(JSON)
    equity_curve = Column(JSON)
    trades = Column(JSON)
    symbol_contributions = Column(JSON)
    exit_reason_stats = Column(JSON)
    leaderboard_rows = Column(JSON)
    warnings = Column(JSON)

    completed_at = Column(DateTime, default=func.now(), index=True, nullable=False)

