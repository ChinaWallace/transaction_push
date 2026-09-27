"""One cash account and one position state machine for replay and paper trading."""

from dataclasses import asdict
from datetime import datetime
from math import isfinite

from .engine import DAY, INTERVALS, Policy, iso


class Portfolio:
    def __init__(self, policy, horizon="short_term", initial_cash=10000):
        if horizon not in {"short_term", "long_term"} or not isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("Invalid portfolio configuration")
        self.policy, self.horizon = policy, horizon
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions, self.prices, self.cooldown, self.last_entry_signal = {}, {}, {}, {}
        self.ask_prices = {}
        self.events, self.trades, self.equity_curve, self.rejections = [], [], [], []
        self.peak = self.risk_peak = self.initial_cash
        self.max_drawdown = 0.0
        self.pause_until = 0
        self.last_open = self.last_close = None
        self.step = INTERVALS["4h" if horizon == "short_term" else "1d"]

    @property
    def fee(self):
        return self.policy.fee_bps/10000

    @property
    def slip(self):
        return self.policy.slippage_bps/10000

    def net_value(self, raw):
        return raw*(1-self.slip)*(1-self.fee)

    def equity(self):
        return self.cash+sum(p["quantity"]*self.net_value(self.prices[s]) for s,p in self.positions.items())

    def exposure(self):
        return sum(p["quantity"]*self.prices[s] for s,p in self.positions.items())

    def open_risk(self):
        return sum(p["quantity"]*max(0, self.net_value(self.prices[s])-self.net_value(p["stop"]))
                   for s,p in self.positions.items())

    def reject(self, symbol, now, reason):
        self.rejections.append({"symbol": symbol, "time": iso(now), "reason": reason})

    def sell(self, symbol, quantity, raw_price, now, reason):
        p = self.positions[symbol]
        quantity = min(quantity, p["quantity"])
        fill = raw_price*(1-self.slip)
        proceeds, fee = quantity*fill*(1-self.fee), quantity*fill*self.fee
        fraction = quantity/p["quantity"]
        cost = p["remaining_cost"]*fraction
        p["remaining_cost"] -= cost
        p["quantity"] -= quantity
        p["proceeds"] += proceeds
        self.cash += proceeds
        event = {"symbol": symbol, "time": iso(now), "side": "sell", "reason": reason,
                 "price": fill, "quantity": quantity, "fee": fee, "realized_pnl": proceeds-cost}
        self.events.append(event)
        p["fills"].append(event)
        if p["quantity"] < 1e-10:
            self.trades.append({"symbol": symbol, "entry_time": iso(p["opened_at"]), "exit_time": iso(now),
                                "pnl_usdt": p["proceeds"]-p["total_cost"],
                                "net_return_pct": (p["proceeds"]/p["total_cost"]-1)*100,
                                "adds": p["adds"], "fills": p["fills"]})
            del self.positions[symbol]
            self.cooldown[symbol] = (now//self.step+1+self.policy.cooldown_bars)*self.step

    def buy(self, row, now, add=False):
        symbol, p = row["symbol"], row[self.horizon]
        raw = self.prices[symbol]
        fill = self.ask_prices.get(symbol, raw)*(1+self.slip)
        if not p.get("entry_zone") or not p["entry_zone"][0] <= fill <= p["entry_zone"][1]:
            return self.reject(symbol, now, "entry_price_outside_zone")
        old = self.positions.get(symbol)
        proposed_stop = p.get("stop_loss")
        if proposed_stop is None:
            return self.reject(symbol, now, "invalid_stop")
        stop = max(old["stop"], proposed_stop) if old else proposed_stop
        if stop is None or not 0 < stop < raw:
            return self.reject(symbol, now, "invalid_stop")
        eq = self.equity()
        unit_cost, mark = fill*(1+self.fee), self.net_value(raw)
        equity_drag = unit_cost-mark
        risk_unit = unit_cost-self.net_value(stop)
        risk_mark = max(0, mark-self.net_value(stop))
        budget = p["account_risk_budget_pct"]/100
        if add:
            budget = min(budget, self.policy.risk_budget_pct/200)
        single, gross, total_risk = (self.policy.max_position_pct/100, self.policy.max_portfolio_pct/100,
                                      self.policy.max_portfolio_risk_pct/100)
        existing_value = old["quantity"]*raw if old else 0
        # Denominators include the fees' immediate reduction in equity.
        limits = [self.cash/unit_cost, budget*eq/(risk_unit+budget*equity_drag),
                  (single*eq-existing_value)/(raw+single*equity_drag),
                  (gross*eq-self.exposure())/(raw+gross*equity_drag),
                  (total_risk*eq-self.open_risk())/(risk_mark+total_risk*equity_drag)]
        # Bound assumed fills by 0.1% of the previous closed candle's turnover.
        limits.append(row.get("execution_quote_volume", 1e12)*.001/raw)
        quantity = max(0, min(limits))
        if quantity*raw < 10:
            return self.reject(symbol, now, "cash_exposure_or_risk_limit")
        cost = quantity*unit_cost
        self.cash -= cost
        event = {"symbol": symbol, "time": iso(now), "signal_time": row["signal_time"],
                 "side": "buy", "reason": "add_winner" if add else p.get("setup", "legacy_entry"),
                 "price": fill, "quantity": quantity, "fee": quantity*fill*self.fee, "stop": stop}
        self.events.append(event)
        if old:
            old["quantity"] += quantity
            old["remaining_cost"] += cost
            old["total_cost"] += cost
            old["stop"] = stop
            old["adds"] += 1
            old["fills"].append(event)
        else:
            self.positions[symbol] = {
                "quantity": quantity, "remaining_cost": cost, "total_cost": cost, "proceeds": 0.0,
                "entry": fill, "initial_risk": fill-stop, "opened_at": now, "stop": stop,
                "target": p["take_profit_reference"], "partial_taken": False, "adds": 0, "weak_rank_bars": 0,
                "fills": [event],
            }
        self.last_entry_signal[symbol] = row["signal_time"]

    def on_open(self, now, signals, prices, asks=None):
        """All signals are from closed bars; prices are this execution instant."""
        if self.last_open is not None and now <= self.last_open:
            raise ValueError("Portfolio execution times must strictly increase")
        if any(not isfinite(v) or v <= 0 for v in prices.values()):
            raise ValueError("Invalid execution price")
        for row in signals:
            signal_time = datetime.fromisoformat(row["signal_time"]).timestamp()*1000
            if signal_time >= now:
                raise ValueError("Signals must precede execution")
        self.last_open = now
        self.prices.update(prices)
        self.ask_prices = asks or {}
        available = {r["symbol"]: r for r in signals}
        # Only eligible entrants compete for slots, ordered deterministically.
        candidates = sorted((r for r in signals if r[self.horizon]["action"] == "buy_candidate"),
                            key=lambda r: (-r["selection_score"], r["symbol"]))
        leaders = {r["symbol"] for r in sorted(signals, key=lambda r: (-r["selection_score"], r["symbol"]))[:self.policy.max_positions*2]}
        exited = set()
        missing_prices = set(self.positions)-set(prices)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                self.reject(symbol, now, "missing_execution_price_existing_position")
                continue
            row = available.get(symbol)
            p = row[self.horizon] if row else None
            if self.prices[symbol] <= pos["stop"]:
                self.sell(symbol, pos["quantity"], self.prices[symbol], now, "gap_stop")
                exited.add(symbol)
                continue
            if p:
                if pos.get("last_management_signal") != row["signal_time"]:
                    pos["weak_rank_bars"] = 0 if symbol in leaders else pos["weak_rank_bars"]+1
                    pos["last_management_signal"] = row["signal_time"]
                # Trailing data is known before this open, never this bar's high.
                if self.prices[symbol] >= pos["entry"]+pos["initial_risk"] or pos["partial_taken"]:
                    pos["stop"] = max(pos["stop"], p.get("trailing_stop_reference", 0))
                if pos["partial_taken"]:
                    break_even = (pos["remaining_cost"]/pos["quantity"])/((1-self.slip)*(1-self.fee))
                    pos["stop"] = max(pos["stop"], break_even)
            max_age = p.get("max_holding_bars", 42 if self.horizon == "short_term" else 90) if p else (42 if self.horizon == "short_term" else 90)
            reason = None
            if self.prices[symbol] <= pos["stop"]:
                reason = "trailing_stop"
            elif p and p["action"] == "avoid":
                reason = "trend_exit"
            elif now-pos["opened_at"] >= max_age*self.step:
                reason = "time_exit"
            elif pos["weak_rank_bars"] >= 3 and p and p["action"] != "buy_candidate":
                reason = "rank_rotation"
            if reason:
                self.sell(symbol, pos["quantity"], self.prices[symbol], now, reason)
                exited.add(symbol)
        if now < self.pause_until or missing_prices:
            for r in candidates:
                self.reject(r["symbol"], now, "incomplete_valuation" if missing_prices else "portfolio_drawdown_cooldown")
            return
        for row in candidates:
            symbol = row["symbol"]
            if symbol not in prices or symbol in exited or now < self.cooldown.get(symbol, 0):
                self.reject(symbol, now, "missing_price_or_exit_cooldown")
                continue
            if self.last_entry_signal.get(symbol) == row["signal_time"]:
                continue
            pos = self.positions.get(symbol)
            if pos:
                if (self.policy.profile != "legacy" and pos["adds"] == 0 and not pos["partial_taken"]
                        and self.prices[symbol] >= pos["entry"]+pos["initial_risk"]
                        and (not pos["target"] or self.prices[symbol] < pos["target"])):
                    self.buy(row, now, add=True)
            elif len(self.positions) < self.policy.max_positions:
                self.buy(row, now)
            else:
                self.reject(symbol, now, "max_positions")

    def on_close(self, now, bars):
        """Conservative OHLC matching after opening decisions; stop first."""
        if self.last_close is not None and now <= self.last_close:
            raise ValueError("Close times must strictly increase")
        self.last_close = now
        for symbol, pos in list(self.positions.items()):
            bar = bars.get(symbol)
            if bar is None:
                self.reject(symbol, now, "missing_bar_existing_position")
                continue
            if bar.low <= pos["stop"]:
                self.sell(symbol, pos["quantity"], min(bar.open, pos["stop"]), now, "stop")
            elif pos["target"] and bar.high >= pos["target"]:
                fraction = .5 if self.policy.profile == "legacy" else 1/3
                self.sell(symbol, pos["quantity"]*fraction, pos["target"], now, "partial_take_profit")
                self.positions[symbol]["partial_taken"] = True
                self.positions[symbol]["target"] = None
        self.prices.update({s: b.close for s,b in bars.items()})
        self.record_equity(now)

    def on_quote(self, now, prices):
        """Paper fills at observed quotes only; no invented intrapoll OHLC."""
        self.prices.update(prices)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
            raw = prices[symbol]
            if raw <= pos["stop"]:
                self.sell(symbol, pos["quantity"], raw, now, "observed_stop")
            elif pos["target"] and raw >= pos["target"]:
                fraction = .5 if self.policy.profile == "legacy" else 1/3
                self.sell(symbol, pos["quantity"]*fraction, raw, now, "partial_take_profit")
                self.positions[symbol]["partial_taken"] = True
                self.positions[symbol]["target"] = None

    def record_equity(self, now):
        eq = self.equity()
        self.peak = max(self.peak, eq)
        self.risk_peak = max(self.risk_peak, eq)
        self.max_drawdown = max(self.max_drawdown, 1-eq/self.peak)
        if now >= self.pause_until and 1-eq/self.risk_peak >= self.policy.drawdown_pause_pct/100:
            self.pause_until = now+7*DAY
            self.risk_peak = eq
        self.equity_curve.append({"time": iso(now), "equity": eq, "cash": self.cash,
                                  "exposure_pct": self.exposure()/eq*100, "open_risk_pct": self.open_risk()/eq*100,
                                  "positions": len(self.positions)})

    def liquidate(self, now):
        for s,p in list(self.positions.items()):
            self.sell(s, p["quantity"], self.prices[s], now, "end_of_data")
        self.record_equity(now)

    def summary(self):
        eq = self.equity()
        profit = sum(t["pnl_usdt"] for t in self.trades if t["pnl_usdt"] > 0)
        loss = -sum(t["pnl_usdt"] for t in self.trades if t["pnl_usdt"] < 0)
        return {"profile": self.policy.profile, "horizon": self.horizon, "initial_equity": self.initial_cash,
                "equity": eq, "cash": self.cash, "net_return_pct": (eq/self.initial_cash-1)*100,
                "max_drawdown_pct": self.max_drawdown*100, "trade_count": len(self.trades),
                "win_rate_pct": sum(t["pnl_usdt"] > 0 for t in self.trades)/len(self.trades)*100 if self.trades else None,
                "profit_factor": profit/loss if loss else None,
                "fees_paid": sum(e["fee"] for e in self.events), "positions": self.positions,
                "events": self.events, "trades": self.trades, "equity_curve": self.equity_curve,
                "rejections": self.rejections, "policy": asdict(self.policy)}

    def dump(self):
        return {k: v for k,v in self.__dict__.items() if k != "policy"} | {"policy": asdict(self.policy)}

    @classmethod
    def restore(cls, data):
        obj = cls(Policy(**data["policy"]), data["horizon"], data["initial_cash"])
        obj.__dict__.update({k:v for k,v in data.items() if k != "policy"})
        return obj
