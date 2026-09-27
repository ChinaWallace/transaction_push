"""Chronological replay of the same advisory rules; no fit or parameter search."""

from bisect import bisect_left
from dataclasses import asdict
from statistics import mean

from .engine import DAY, Policy, analyze, analyze_daily, closed_candles, iso


def exit_fill(bar, stop, target):
    """Ambiguous OHLC bars hit the stop first; gaps fill at the worse open."""
    if bar.low <= stop:
        return min(bar.open, stop), "stop"
    if target is not None and bar.high >= target:
        return target, "target_half"
    return None


def replay_symbol(symbol, daily_rows, four_rows, btc_rows, as_of, horizon="short_term", policy=Policy()):
    if horizon not in {"short_term", "long_term"}:
        raise ValueError("Unknown horizon")
    daily = closed_candles(daily_rows, "1d", as_of, policy.min_daily_bars)
    four = closed_candles(four_rows, "4h", as_of, 100) if horizon == "short_term" else []
    btc = closed_candles(btc_rows, "1d", as_of, policy.min_daily_bars)
    bars = four if horizon == "short_term" else daily
    d_times, h_times, b_times = ([b.close_time for b in seq] for seq in (daily, four, btc))
    fee, slip = policy.fee_bps / 10_000, policy.slippage_bps / 10_000
    cash, equity, peak, drawdown = 10_000.0, 10_000.0, 10_000.0, 0.0
    position, trades, curve, signals, errors = None, [], [], [], {}
    max_bars = 42 if horizon == "short_term" else 90
    start_index = None

    def sell(raw_price, quantity, when, reason):
        nonlocal cash, position
        price = raw_price * (1 - slip)
        proceeds = quantity * price * (1 - fee)
        cash += proceeds
        position["proceeds"] += proceeds
        position["quantity"] -= quantity
        position["fills"].append({"time": iso(when), "price": price, "quantity": quantity, "reason": reason})
        if position["quantity"] <= 1e-10:
            pnl = position["proceeds"] - position["cost"]
            trades.append({"signal_time": position["signal_time"], "entry_time": position["entry_time"],
                           "entry_price": position["entry_price"], "exit_time": iso(when),
                           "pnl_usdt": pnl, "net_return_pct": pnl / position["cost"] * 100,
                           "fills": position["fills"]})
            position = None

    for i, bar in enumerate(bars):
        # At this open, every signal input must have closed strictly earlier.
        d_end, h_end, b_end = (bisect_left(times, bar.open_time) for times in (d_times, h_times, b_times))
        if d_end < policy.min_daily_bars or b_end < policy.min_daily_bars or horizon == "short_term" and h_end < 100:
            continue
        if start_index is None:
            start_index = i
        try:
            if horizon == "long_term":
                result = analyze_daily(symbol, daily[max(0, d_end-300):d_end],
                                       btc[max(0, b_end-300):b_end], bar.open_time, policy)
            else:
                result = analyze(symbol, daily[max(0, d_end-300):d_end], four[max(0, h_end-300):h_end],
                                 btc[max(0, b_end-300):b_end], bar.open_time, policy)
            p = result[horizon]
        except ValueError as exc:
            errors[str(exc)] = errors.get(str(exc), 0) + 1
            p = None
        if p:
            signals.append({"as_of": iso(bar.open_time), "score": result["selection_score"],
                            "close": result["metrics"]["close"], "action": p["action"]})
        exited_at_open = False
        if position:
            if p and p["action"] == "avoid" or i - position["bar_index"] >= max_bars:
                sell(bar.open, position["quantity"], bar.open_time, "trend_or_time_exit")
                exited_at_open = True
            elif p:
                position["stop"] = max(position["stop"], p["trailing_stop_reference"])
        if position is None and not exited_at_open and p and p["action"] == "buy_candidate":
            fill = bar.open * (1 + slip)
            # Do not assume a later touch fills an unplaced order.
            if p["entry_zone"][0] <= fill <= p["entry_zone"][1] and fill > p["stop_loss"]:
                risk_fraction = (fill - p["stop_loss"]) / fill + 2 * (fee + slip)
                allocation = min(policy.max_position_pct / 100, policy.risk_budget_pct / 100 / risk_fraction)
                cost = cash * allocation
                quantity = cost / (fill * (1 + fee))
                cash -= cost
                position = {"quantity": quantity, "cost": cost, "proceeds": 0.0,
                            "entry_price": fill, "entry_time": iso(bar.open_time),
                            "signal_time": result["four_hour_close_time"] if horizon == "short_term" else result["daily_close_time"],
                            "stop": p["stop_loss"], "target": p["take_profit_reference"],
                            "bar_index": i, "fills": []}
        if position:
            hit = exit_fill(bar, position["stop"], position["target"])
            if hit:
                raw, reason = hit
                quantity = position["quantity"] if reason == "stop" else position["quantity"] / 2
                # With OHLC only, the exact intrabar execution time is unknown.
                sell(raw, quantity, bar.close_time, reason)
                if position and reason == "target_half":
                    position["target"] = None
        equity = cash + (position["quantity"] * bar.close * (1-slip) * (1-fee) if position else 0)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        curve.append({"time": iso(bar.close_time), "equity": round(equity, 4)})
    if position:
        sell(bars[-1].close, position["quantity"], bars[-1].close_time, "end_of_data")
    if start_index is None:
        raise ValueError("No overlapping replay window after warm-up")
    start, end = bars[start_index], bars[-1]
    buy_hold = end.close * (1-slip) * (1-fee) / (start.open * (1+slip) * (1+fee)) - 1
    profit = sum(t["pnl_usdt"] for t in trades if t["pnl_usdt"] > 0)
    loss = -sum(t["pnl_usdt"] for t in trades if t["pnl_usdt"] < 0)
    return {
        "symbol": symbol, "horizon": horizon, "start": iso(start.open_time), "end": iso(end.close_time),
        "policy": asdict(policy), "initial_equity": 10_000, "final_equity": round(cash, 4),
        "net_return_pct": round((cash / 10_000 - 1) * 100, 4),
        "max_close_equity_drawdown_pct": round(drawdown * 100, 4), "trade_count": len(trades),
        "win_rate_pct": round(sum(t["pnl_usdt"] > 0 for t in trades) / len(trades) * 100, 2) if trades else None,
        "profit_factor": round(profit / loss, 3) if loss else None,
        "buy_hold_net_pct": round(buy_hold * 100, 4),
        "matched_exposure_buy_hold_pct": round(buy_hold * policy.max_position_pct, 4),
        "trades": trades, "equity_curve": curve, "signal_history": signals, "skipped_signals": errors,
        "validation": "historical_replay_not_out_of_sample",
        "limitations": ["单币独立资金账户，非组合回测", "标的事后指定，含幸存者和选择偏差",
                        "规则在当前已知行情背景下制定，不能称为样本外验证", "手续费和滑点为假设，止损可能穿价",
                        "收盘权益回撤，非逐笔/盘中最大回撤", "下一根开盘入场，止损优先，目标减半，余仓跟踪退出"],
    }


def replay_ranking(snapshot, symbols, policy=Policy(), forward_days=30, top_k=3):
    """Selection diagnostic with next-open forward outcomes, NOT strategy PnL.

    Universe is explicitly caller-supplied, not reconstructed from today's
    liquidity leaders. Weekly observations overlap and are not independent.
    """
    if forward_days < 1 or top_k < 1:
        raise ValueError("Positive horizon and top_k required")
    universe = list(dict.fromkeys(symbols))
    data = {s: closed_candles(snapshot["symbols"][s]["1d"], "1d", snapshot["as_of"], policy.min_daily_bars)
            for s in dict.fromkeys([*universe, "BTCUSDT"])}
    indices = {s: {b.open_time: i for i, b in enumerate(bars)} for s, bars in data.items()}
    times = {s: [b.close_time for b in bars] for s, bars in data.items()}
    observations = []
    cost_factor = (1-policy.slippage_bps/10000)*(1-policy.fee_bps/10000) / ((1+policy.slippage_bps/10000)*(1+policy.fee_bps/10000))
    # Dates come solely from the reference calendar, without outcome filtering.
    for ref in data["BTCUSDT"][policy.min_daily_bars::7]:
        now = ref.open_time
        b_end = bisect_left(times["BTCUSDT"], now)
        btc = data["BTCUSDT"][max(0, b_end-300):b_end]
        ranked = []
        for s in universe:
            end = bisect_left(times[s], now)
            if end < policy.min_daily_bars:
                continue
            try:
                row = analyze_daily(s, data[s][max(0, end-300):end], btc, now, policy)
            except ValueError:
                continue
            ranked.append({"symbol": s, "score": row["selection_score"],
                           "signal_close": row["metrics"]["close"], "long_action": row["long_term"]["action"]})
        ranked.sort(key=lambda r: (-r["score"], r["symbol"]))
        # Outcomes are joined AFTER selection; missing future data stays missing.
        for rank, r in enumerate(ranked, 1):
            s = r["symbol"]
            start = indices[s].get(now)
            end = indices[s].get(now + (forward_days-1)*DAY)
            r["rank"] = rank
            r["forward_net_return_pct"] = ((data[s][end].close / data[s][start].open * cost_factor - 1) * 100
                                            if start is not None and end is not None else None)
        b_start = indices["BTCUSDT"].get(now)
        b_finish = indices["BTCUSDT"].get(now+(forward_days-1)*DAY)
        benchmark = ((data["BTCUSDT"][b_finish].close / data["BTCUSDT"][b_start].open * cost_factor-1)*100
                     if b_finish is not None and b_start is not None else None)
        matured = bool(ranked) and benchmark is not None and all(r["forward_net_return_pct"] is not None for r in ranked)
        chosen = ranked[:top_k]
        best = max(ranked, key=lambda r: r["forward_net_return_pct"]) if matured else None
        observations.append({"as_of": iso(now), "ranking": ranked, "matured": matured,
                             "top_k_mean_forward_net_pct": mean(r["forward_net_return_pct"] for r in chosen) if matured else None,
                             "universe_equal_weight_forward_net_pct": mean(r["forward_net_return_pct"] for r in ranked) if matured else None,
                             "btc_forward_net_pct": benchmark,
                             "forward_winner_in_top_k": best in chosen if matured else None})
    mature = [o for o in observations if o["matured"]]
    return {"universe": universe, "forward_days": forward_days, "top_k": top_k,
            "observation_count": len(observations), "matured_count": len(mature),
            "mean_top_k_excess_vs_btc_pct": mean(o["top_k_mean_forward_net_pct"]-o["btc_forward_net_pct"] for o in mature) if mature else None,
            "missed_forward_winner_rate_pct": mean(not o["forward_winner_in_top_k"] for o in mature)*100 if mature else None,
            "observations": observations,
            "limitations": ["事后指定标的，存在幸存者/选择偏差", "每周窗口有重叠，不能视为独立样本",
                            "前瞻收益用于评价排序，不是可实现的组合策略收益", "规则未经独立样本外或前瞻校准"]}
