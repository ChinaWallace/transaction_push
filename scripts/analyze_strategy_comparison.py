#!/usr/bin/env python3
"""Rebuild long 1x research equity from fills and actual settlement events.

Run with .venv.freqtrade-quant/bin/python. Never reads credentials or trades.
The curve samples 5m mark closes, so it does not claim tick-level drawdown.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_v5"
STEP = 300_000
CAPITAL = 10_000.0
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "ZEC/USDT:USDT"]
WINDOWS = {"full": ("2026-01-01", "2026-09-24"), "validation": ("2026-05-01", "2026-07-01"),
           "holdout": ("2026-07-01", "2026-09-24")}


def write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def timestamp(value):
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def load_data():
    result = {}
    for pair in PAIRS:
        symbol = pair.split("/")[0] + "USDT"
        rows = json.loads((OUT / f"data/series/markPriceKlines/5m/{symbol}.json").read_text())["rows"]
        marks = {int(r[0]): float(r[4]) for r in rows}
        raw = json.loads((ROOT / f"reports/quant_v3/futures_replay/funding/symbols/{symbol}.json").read_text())["rates"]
        # Same documented <60s settlement jitter normalization as the converter.
        funding = [(int(r["fundingTime"]) // 3_600_000 * 3_600_000,
                    float(r["fundingRate"]) * float(r["markPrice"])) for r in raw]
        result[pair] = marks, funding
    return result


def funding_flows(orders, events, *, parity=False):
    """Long cash flows; parity reproduces the engine's inclusive fill segments.

    A fill exactly at settlement can occur in both adjacent engine segments.
    Preserve order-list order for fills with identical timestamps.
    """
    flows = {}
    if parity:
        quantity = 0.0
        for order, following in zip(orders, orders[1:]):
            quantity += float(order["amount"]) * (1 if order["ft_is_entry"] else -1)
            for at, unit_cost in events:
                if order["order_filled_timestamp"] <= at <= following["order_filled_timestamp"]:
                    flows[at] = flows.get(at, 0.0) - quantity * unit_cost
    else:
        for at, unit_cost in events:
            if not orders[0]["order_filled_timestamp"] <= at <= orders[-1]["order_filled_timestamp"]:
                continue
            held = sum(float(o["amount"]) * (1 if o["ft_is_entry"] else -1) for o in orders
                       if o["order_filled_timestamp"] <= at and
                       (o["ft_is_entry"] or o["order_filled_timestamp"] < at))
            flows[at] = -held * unit_cost
    return flows


def analyze(run, data):
    summary = json.loads((run / "summary.json").read_text())
    trades = json.loads((run / "trades.json").read_text())
    start, end = map(timestamp, WINDOWS[summary["window"].removesuffix("_double_cost")])
    times = np.arange(start, end + STEP, STEP, dtype=np.int64)
    n = len(times)
    cash_delta = np.zeros(n)
    economic_funding_delta = np.zeros(n)
    quantity_delta = {p: np.zeros(n) for p in PAIRS}
    pnl_by_pair = dict.fromkeys(PAIRS, 0.0)
    fees_by_pair = dict.fromkeys(PAIRS, 0.0)
    funding_by_pair = dict.fromkeys(PAIRS, 0.0)
    fund_errors = []
    orders_export = []
    for trade_id, trade in enumerate(trades):
        if trade["is_short"] or trade["leverage"] != 1:
            raise ValueError("Only long 1x research is supported")
        pair = trade["pair"]
        orders = trade["orders"]
        cash = fee_total = 0.0
        for order in orders:
            at = int(order["order_filled_timestamp"])
            if not start <= at <= end or (at - start) % STEP:
                raise ValueError("Fill outside the expected candle clock")
            slot = (at - start) // STEP
            amount = float(order["amount"])
            price = float(order["safe_price"])
            entry = bool(order["ft_is_entry"])
            fee = amount * price * trade["fee_open" if entry else "fee_close"]
            qty = amount if entry else -amount
            change = -qty * price - fee
            cash += change
            fee_total += fee
            cash_delta[slot] += change
            quantity_delta[pair][slot] += qty
            orders_export.append({"trade_id": trade_id, "pair": pair, "timestamp": at,
                                  "side": "buy" if entry else "sell", "amount": amount,
                                  "price": price, "fee": fee, "reason": order.get("ft_order_tag"),
                                  "trade_exit_reason": trade["exit_reason"]})
        events = [(at, cost) for at, cost in data[pair][1]
                  if start <= at <= end and at < timestamp(WINDOWS["full"][1])]
        engine_flows = funding_flows(orders, events, parity=True)
        single_flows = funding_flows(orders, events, parity=False)
        fund_total = sum(engine_flows.values())
        for at in engine_flows.keys() | single_flows.keys():
            cash_delta[(at - start) // STEP] += engine_flows.get(at, 0)
            economic_funding_delta[(at - start) // STEP] += single_flows.get(at, 0) - engine_flows.get(at, 0)
        fund_errors.append(fund_total - float(trade.get("funding_fees", 0)))
        pnl_by_pair[pair] += cash + fund_total
        fees_by_pair[pair] += fee_total
        funding_by_pair[pair] += fund_total

    cash = CAPITAL + np.cumsum(cash_delta)
    equity = cash.copy()
    exposure = np.zeros(n)
    for pair in PAIRS:
        qty = np.cumsum(quantity_delta[pair])
        if abs(qty[-1]) > 1e-7:
            raise ValueError("Unclosed final position")
        marks = data[pair][0]
        # Last sample is flat after terminal liquidation; use preceding close.
        prices = np.array([marks[int(t)] if int(t) in marks else marks[int(t - STEP)]
                           if int(t) == end else float("nan") for t in times])
        if not np.all(np.isfinite(prices)):
            raise ValueError("Missing mark price; no forward-filling research gaps")
        marked_value = qty * prices
        equity += marked_value
        exposure += marked_value
    peaks = np.maximum.accumulate(np.concatenate(([CAPITAL], equity)))[1:]
    dd = (peaks - equity) / peaks
    account_error = float(equity[-1] - CAPITAL - summary["profit_total_abs"])
    economic_equity = equity + np.cumsum(economic_funding_delta)
    economic_peaks = np.maximum.accumulate(np.concatenate(([CAPITAL], economic_equity)))[1:]
    max_fund_error = max(map(abs, fund_errors), default=0)
    # 1 cent account tolerance allows Freqtrade's 8-decimal per-trade rounding.
    reconciled = abs(account_error) <= .01 and max_fund_error <= .01
    monthly = []
    last = CAPITAL
    frame = pd.DataFrame({"timestamp": times, "equity": equity, "drawdown": dd, "exposure": exposure})
    dates = pd.to_datetime(times, unit="ms", utc=True)
    for month in sorted(set(dates[:-1].strftime("%Y-%m"))):
        selected = np.flatnonzero(dates.strftime("%Y-%m") == month)
        final = float(equity[selected[-1]])
        monthly.append({"month": month, "return_pct": (final / last - 1) * 100, "end_equity": final})
        last = final
    duration = [float(t["trade_duration"]) / 60 for t in trades]
    metrics = {"return_pct": (float(equity[-1]) / CAPITAL - 1) * 100,
               "sampled_mark_drawdown_pct": float(dd.max()) * 100,
               "final_equity": float(equity[-1]), "reconciled": reconciled,
               "engine_profit_difference_usdt": account_error, "max_trade_funding_difference_usdt": max_fund_error,
               "fee_cost_usdt": sum(fees_by_pair.values()), "funding_net_income_usdt": sum(funding_by_pair.values()),
               "max_marked_exposure_pct": float((exposure / equity).max()) * 100,
               "economic_single_settlement_return_pct": (float(economic_equity[-1]) / CAPITAL - 1) * 100,
               "economic_single_settlement_drawdown_pct": float(((economic_peaks-economic_equity)/economic_peaks).max())*100,
               "engine_funding_vs_single_event_difference_usdt": float(economic_equity[-1]-equity[-1]),
               "average_marked_exposure_pct": float((exposure / equity).mean()) * 100,
               "holding_median_hours": float(np.median(duration)) if duration else 0,
               "holding_max_hours": max(duration, default=0),
               "exit_counts": dict(Counter(t["exit_reason"] for t in trades)),
               "pnl_by_pair": pnl_by_pair, "monthly": monthly,
               "definition": "5m mark-close equity reconstructed from all fills, each-side fees and real funding events; not tick drawdown",
               "funding_tie_convention": "Engine parity: inclusive intervals between adjacent fills; also report single-event settlement sensitivity",
               "engine_accounting_warning": None if reconciled else "Engine and fill/settlement cash flows differ; not eligible for selection until resolved"}
    frame.to_feather(run / "equity_5m.feather")
    write(run / "equity_preview.json", frame.iloc[::max(1, len(frame)//700)].to_dict(orient="records") + [frame.iloc[-1].to_dict()])
    write(run / "orders.json", sorted(orders_export, key=lambda x: (x["timestamp"], x["trade_id"])))
    write(run / "mark_metrics.json", metrics)
    return {**summary, "mark_metrics": metrics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="all")
    args = parser.parse_args()
    data = load_data()
    rows = []
    for p in sorted((OUT / "runs").glob("*/*/summary.json")):
        if args.window != "all" and p.parent.parent.name != args.window:
            continue
        result = analyze(p.parent, data)
        m = result["mark_metrics"]
        rows.append(result)
        print(result["window"], result["strategy"], f'{m["return_pct"]:.2f}%',
              f'DD {m["sampled_mark_drawdown_pct"]:.2f}%', "OK" if m["reconciled"] else f'DIFF {m["engine_profit_difference_usdt"]:.6f}', flush=True)
    write(OUT / ("comparison.json" if args.window == "all" else f"comparison_{args.window}.json"),
          {"capital": CAPITAL, "curve_method": "5m mark close", "rows": rows})


if __name__ == "__main__":
    main()
