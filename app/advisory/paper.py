"""Transactional local paper ledger. No exchange order API or API keys."""

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
import sqlite3
import time

from .backtest import timestamp
from .engine import Policy
from .portfolio import Portfolio

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data/advisory_paper.sqlite3"
VERSION = "portfolio-v2"


def update_paper(report, horizon="short_term", ledger=None, initial_cash=10000):
    """Keep exit quotes available even when holdings leave the selection universe."""
    from .market import BinancePublicClient, MarketDataError
    ledger = ledger or PaperLedger()
    held = ledger.status(report["policy"]["profile"], horizon).get("positions", {})
    covered = {r["symbol"] for r in report["ranking"] if r.get("quote_valid")}
    extra = {}
    for symbol in set(held)-covered:
        try:
            ticker = BinancePublicClient().get("ticker/24hr", symbol=symbol)
            from .engine import iso
            extra[symbol] = {"price": float(ticker["lastPrice"]), "bid": float(ticker["bidPrice"]),
                             "ask": float(ticker["askPrice"]), "time": iso(int(ticker["closeTime"])), "valid": True}
        except (MarketDataError, KeyError, ValueError, TypeError):
            continue
    return ledger.step(report, horizon, initial_cash, extra_quotes=extra)


def paper_cycle(watchlist=("ZECUSDT",), max_candidates=60, profile="active", horizon="short_term", ledger=None, initial_cash=10000):
    from .engine import iso, policy_for
    from .market import MarketDataError
    from .service import advisory_service
    try:
        report = advisory_service.report(watchlist, max_candidates, profile)
        if report["status"] == "unavailable":
            raise MarketDataError("Research unavailable")
    except MarketDataError as exc:
        now = iso(int(time.time()*1000))
        report = {"status": "degraded", "as_of": now, "published_at": now,
                  "policy": asdict(policy_for(profile, max_candidates=max_candidates)),
                  "ranking": [], "data_errors": {"scan": str(exc)}, "watchlist": {},
                  "scan_count": 0, "analyzed_count": 0,
                  "limitations": ["研究扫描失败，本次只管理持仓退出，不生成入场信号"]}
    return report, update_paper(report, horizon, ledger, initial_cash)


class PaperLedger:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, book TEXT, time INTEGER, payload TEXT)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, profile="active", horizon="short_term"):
        with self.connect() as db:
            row = db.execute("SELECT state FROM books WHERE id=?", (profile+":"+horizon,)).fetchone()
        if not row:
            return {"status": "not_started", "profile": profile, "horizon": horizon, "simulation": True}
        data = json.loads(row[0])
        book = Portfolio.restore(data["portfolio"])
        return self.result(book, data, [])

    @staticmethod
    def result(book, data, events):
        result = book.summary()
        result.pop("equity_curve")
        result.pop("rejections")
        result.update(simulation=True, strategy_version=data["version"], observed_at=data["observed_at"],
                      research_status=data.get("research_status", "ok"),
                      missing_prices=data["missing_prices"], valuation_complete=not data["missing_prices"],
                      new_events=events,
                      limitations=["本地模拟资金，不提交真实订单", "按轮询时可见报价成交，无法重建轮询间的止损触发",
                                   "持仓缺价时冻结新增交易，权益沿用旧价且标记不完整"])
        return result

    def step(self, report, horizon="short_term", initial_cash=10000, now=None, extra_quotes=None):
        now = int(time.time()*1000) if now is None else now
        policy = Policy(**report["policy"])
        if report["status"] == "unavailable":
            raise ValueError("Unavailable research cannot update paper account")
        if not 0 <= now-timestamp(report["published_at"]) <= 120_000:
            raise ValueError("Research delivery is stale or in the future")
        key = policy.profile+":"+horizon
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM books WHERE id=?", (key,)).fetchone()
            data = json.loads(row[0]) if row else None
            if data and (data["version"] != VERSION or data["portfolio"]["policy"] != asdict(policy)):
                raise ValueError("Existing account has different rules; use a new ledger path")
            book = Portfolio.restore(data["portfolio"]) if data else Portfolio(policy, horizon, initial_cash)
            if book.last_open is not None and now <= book.last_open:
                return self.result(book, data, [])
            rows = deepcopy(report["ranking"])
            quotes = {r["symbol"]: {"price": r["last_price"], "time": r["quote_time"],
                                   "bid": r.get("bid_price"), "ask": r.get("ask_price"),
                                   "valid": r.get("quote_valid", False)} for r in rows}
            quotes.update(extra_quotes or {})
            prices, asks = {}, {}
            for symbol, quote in quotes.items():
                age = now-timestamp(quote["time"])
                bid, ask = quote.get("bid"), quote.get("ask")
                if (quote["valid"] and 0 <= age <= 120_000 and bid is not None and ask is not None
                        and isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
                    prices[symbol], asks[symbol] = bid, ask
            signals = []
            for r in rows:
                r["signal_time"] = r["four_hour_close_time" if horizon == "short_term" else "daily_close_time"]
                r["execution_quote_volume"] = r.get("execution_quote_volume", {}).get(horizon, 0)
                if timestamp(r[horizon]["valid_until"]) <= now:
                    continue
                signals.append(r)
            missing = sorted(set(book.positions)-set(prices))
            count = len(book.events)
            book.on_quote(now, prices)
            book.on_open(now, signals, prices, asks)
            book.record_equity(now)
            data = {"version": VERSION, "observed_at": report["published_at"], "missing_prices": missing,
                    "research_status": report["status"],
                    "portfolio": book.dump()}
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False)
            db.execute("INSERT INTO books VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (key, payload))
            # Preserve the exact inputs for forward audit, including no-trade decisions.
            db.execute("INSERT INTO observations(book,time,payload) VALUES (?,?,?)",
                       (key, now, json.dumps({"report": report, "extra_quotes": extra_quotes}, ensure_ascii=False, allow_nan=False)))
        return self.result(book, data, book.events[count:])
