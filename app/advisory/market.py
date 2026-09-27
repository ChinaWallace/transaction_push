"""Binance public spot data only: no credentials, orders, or notifications."""

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import asdict
import json
from math import isfinite
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime

from .engine import Policy, analyze, iso, normalize_symbol, select_universe, policy_for


class MarketDataError(RuntimeError):
    pass


class BinancePublicClient:
    base_url = "https://data-api.binance.vision"

    def __init__(self, deadline=None):
        self.deadline = deadline

    def get(self, endpoint, **params):
        url = self.base_url + "/api/v3/" + endpoint
        if params:
            url += "?" + urlencode(params)
        for attempt in range(2):
            remaining = self.deadline - time.monotonic() if self.deadline else 15
            if remaining <= 0:
                raise MarketDataError("Market scan deadline exceeded")
            try:
                request = Request(url, headers={"User-Agent": "transaction-push-research/1.0"})
                with urlopen(request, timeout=min(15, remaining)) as response:
                    data = json.load(response)
                if isinstance(data, dict) and "code" in data and data["code"] < 0:
                    raise MarketDataError(f"Binance rejected {endpoint}: {data['code']}")
                return data
            except HTTPError as exc:
                # Do not amplify bans, throttling or bad requests with retries.
                if exc.code < 500 or attempt:
                    raise MarketDataError(f"Binance {endpoint}: HTTP {exc.code}") from exc
            except (URLError, TimeoutError, ValueError) as exc:
                if attempt:
                    raise MarketDataError(f"Binance {endpoint}: {type(exc).__name__}") from exc
            time.sleep(0.5)

    def candles(self, symbol, interval, limit=301, end_time=None):
        params = {"symbol": normalize_symbol(symbol), "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        return self.get("klines", **params)


def scan_market(watchlist=("ZECUSDT",), policy=None, client=None):
    policy = policy or policy_for("active")
    deadline = time.monotonic() + 90
    client = client or BinancePublicClient(deadline=deadline)
    as_of = int(client.get("time")["serverTime"])
    if abs(as_of - int(time.time() * 1000)) > 300_000:
        raise MarketDataError("Local clock and Binance server differ by more than 5 minutes")
    info = client.get("exchangeInfo", permissions="SPOT", showPermissionSets="false")
    tickers = client.get("ticker/24hr")
    selected, rejected = select_universe(info, tickers, as_of, watchlist, policy)
    # Historical BTC is needed even if it cannot pass the *current* spread filter.
    btc = client.candles("BTCUSDT", "1d", end_time=as_of)
    analyzed, errors = [], {}
    ticker_map = {t["symbol"]: t for t in tickers}

    def research(symbol):
        daily = btc if symbol == "BTCUSDT" else client.candles(symbol, "1d", end_time=as_of)
        four = client.candles(symbol, "4h", end_time=as_of)
        result = analyze(symbol, daily, four, btc, as_of, policy)
        ticker = ticker_map[symbol]
        result["last_price"] = float(ticker["lastPrice"])
        result["quote_time"] = iso(int(ticker["closeTime"]))
        result["trade_url"] = "https://www.binance.com/en/trade/" + symbol[:-4] + "_USDT"
        # A closed-bar setup is not executable after the quote has moved away.
        for horizon in ("short_term", "long_term"):
            p = result[horizon]
            if p["action"] == "buy_candidate" and not p["entry_zone"][0] <= result["last_price"] <= p["entry_zone"][1]:
                p.update(action="watch", reason="实时价格已离开收盘信号入场区，等待下一根确认",
                         max_position_pct=0, account_risk_budget_pct=0)
        return result

    pool = ThreadPoolExecutor(max_workers=4)
    tasks = {pool.submit(research, symbol): symbol for symbol in selected}
    try:
        for task in as_completed(tasks, timeout=max(0, deadline-time.monotonic())):
            symbol = tasks[task]
            try:
                analyzed.append(task.result())
            except (ValueError, MarketDataError, KeyError, TypeError) as exc:
                errors[symbol] = str(exc)
    except FuturesTimeout:
        completed = {r["symbol"] for r in analyzed} | set(errors)
        for task, symbol in tasks.items():
            if symbol not in completed:
                task.cancel()
                errors[symbol] = "扫描超过 90 秒截止时间，未生成建议"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    analyzed.sort(key=lambda r: (-r["selection_score"], r["symbol"]))
    for index, row in enumerate(analyzed, 1):
        row["rank"] = index
    report = {
        "status": "ok" if analyzed and not errors else "partial" if analyzed else "unavailable",
        "source": client.base_url, "market": "binance_spot", "as_of": iso(as_of),
        "policy": asdict(policy), "scan_count": len(selected), "analyzed_count": len(analyzed),
        "ranking": analyzed, "rejected": rejected, "data_errors": errors,
        "watchlist": {normalize_symbol(s): next((r for r in analyzed if r["symbol"] == normalize_symbol(s)),
                       {"status": "unavailable", "reason": errors.get(normalize_symbol(s), rejected.get(normalize_symbol(s), "未覆盖"))}) for s in watchlist},
        "limitations": ["流动性前 N 名加自选池，不是全市场穷举", "排名不是买入指令或上涨概率",
                        "现货研究；不包含合约资金费率、杠杆或做空建议", "长期基本面仍需人工复核"],
    }

    return refresh_quotes(report, client)


def refresh_quotes(report, client=None):
    """Revalidate every delivery, including cache hits; never upgrades a plan."""
    client = client or BinancePublicClient(deadline=time.monotonic()+15)
    analyzed, errors = report["ranking"], report["data_errors"]
    # Refresh after the slow kline scan. A stale quote must not permit entry.
    try:
        latest = {t["symbol"]: t for t in client.get("ticker/24hr")}
    except MarketDataError:
        latest = {}
    published_at = int(time.time() * 1000)
    for row in analyzed:
        ticker = latest.get(row["symbol"], {})
        try:
            quote_time = int(ticker["closeTime"])
            price = float(ticker["lastPrice"])
            bid, ask = float(ticker["bidPrice"]), float(ticker["askPrice"])
            valid_quote = (all(isfinite(v) and v > 0 for v in (price, bid, ask))
                           and ask >= bid and (ask-bid)/((ask+bid)/2)*10_000 <= report["policy"]["max_spread_bps"]
                           and -120_000 <= published_at - quote_time <= 120_000)
        except (KeyError, ValueError, TypeError):
            valid_quote = False
        if valid_quote:
            row.update(last_price=price, bid_price=bid, ask_price=ask, quote_time=iso(quote_time))
        else:
            errors[row["symbol"]] = "发布前报价缺失或过期，暂停入场建议"
        row["quote_valid"] = valid_quote
        for horizon in ("short_term", "long_term"):
            p = row[horizon]
            expired = datetime.fromisoformat(p["valid_until"]).timestamp() * 1000 <= published_at
            if p["action"] == "buy_candidate" and (not valid_quote or expired or not p["entry_zone"][0] <= price <= p["entry_zone"][1]):
                p.update(action="watch", reason="报价/价差不合格、信号已过有效期或现价离开入场区，等待重新确认",
                         max_position_pct=0, account_risk_budget_pct=0)
            if "suggested_position_pct" in p:
                p["suggested_position_pct"] = 0
                if p["action"] == "buy_candidate":
                    fee, slip = report["policy"]["fee_bps"]/10000, report["policy"]["slippage_bps"]/10000
                    risk_unit = ask*(1+slip)*(1+fee)-p["stop_loss"]*(1-slip)*(1-fee)
                    p["suggested_position_pct"] = round(min(p["max_position_pct"], p["account_risk_budget_pct"]*bid/risk_unit), 2)
    report["published_at"] = iso(published_at)
    report["status"] = "ok" if analyzed and not errors else "partial" if analyzed else "unavailable"
    return report


ACTION_LABELS = {"buy_candidate": "可分批买入", "wait_pullback": "等回踩", "watch": "待触发", "avoid": "退出/回避"}
SETUP_LABELS = {"breakout": "突破买入", "pullback": "回踩买入", "continuation": "中继试仓"}


def prioritized_rows(report):
    ready = [r for r in report["ranking"] if any(r[h]["action"] == "buy_candidate" for h in ("short_term", "long_term"))]
    return list({r["symbol"]: r for r in [*ready, *report["ranking"]]}.values())


def notification_summary(report):
    """Compact enough for the existing WeChat/Feishu text transports."""
    rows = {r["symbol"]: r for r in prioritized_rows(report)[:3]}
    rows.update({s: r for s, r in report["watchlist"].items() if "selection_score" in r})
    lines = ["选币与长短线研究｜Binance 现货", report["as_of"],
             f"有效 {report['analyzed_count']}/{report['scan_count']}；评分不是胜率。"]
    for s, r in list(rows.items())[:4]:
        lines.append(f"{s} {r['selection_score']:.1f}分；30日相对BTC {r['metrics']['rs30_btc_pct']:+.1f}%")
        for key, label in (("short_term", "短1–7天"), ("long_term", "长1–3月")):
            p = r[key]
            line = f"{label}：{ACTION_LABELS[p['action']]}，{p['reason']}"
            if p["action"] == "buy_candidate":
                size = p.get("suggested_position_pct", p["max_position_pct"])
                line += f"；区间{p['entry_zone']}，止损{p['stop_loss']:.6g}，目标{p['take_profit_reference']:.6g}，独立预算仓位约{size}%（组合额度另限）"
            lines.append(line)
    lines.append("先按止损预算配仓；首次目标卖1/3，余仓跟踪；浮盈1R后最多加一次。详情 /api/market-advisory/report")
    # WeChat markdown payload is limited to 4096 bytes; don't split UTF-8.
    return "\n".join(lines).encode("utf-8")[:3900].decode("utf-8", errors="ignore")


def markdown_report(report):
    lines = ["# 选币与长短线研究", "", f"数据时间：{report['as_of']}（UTC）；来源：Binance 现货。",
             f"候选 {report['scan_count']}，有效 {report['analyzed_count']}；状态：{report['status']}。",
             "", "评分衡量趋势和相对强度，不是胜率。短线 1–7 天，长线 1–3 个月。",
             "", "| 排名 | 币种 | 评分 | 30 日涨幅 | 30 日相对 BTC | 短线 | 长线 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in report["ranking"][:20]:
        lines.append(f"| {r['rank']} | {r['symbol']} | {r['selection_score']:.1f} | {r['metrics']['return30_pct']:+.1f}% | {r['metrics']['rs30_btc_pct']:+.1f}% | {ACTION_LABELS[r['short_term']['action']]} | {ACTION_LABELS[r['long_term']['action']]} |")
    policy = report["policy"]
    lines.extend(["", "## 当前可执行候选", "",
                  f"策略档位 `{policy['profile']}`；每笔最大账户风险 {policy['risk_budget_pct']}%，单币上限 {policy['max_position_pct']}%，组合买入时总仓位上限 {policy['max_portfolio_pct']}%，最多 {policy['max_positions']} 个币。长短线为独立研究账户，不可直接叠加仓位。"])
    for horizon, label in (("short_term", "短线"), ("long_term", "长线")):
        ready = [r for r in report["ranking"] if r[horizon]["action"] == "buy_candidate"]
        lines.append(f"- {label}：" + ("、".join(f"{r['symbol']}（{SETUP_LABELS.get(r[horizon].get('setup'), '条件通过')}）" for r in ready) if ready else "当前无入场触发；下方列出候选与原因。"))
    focus = {r["symbol"]: r for r in prioritized_rows(report)[:8]}
    focus.update({s: r for s, r in report["watchlist"].items() if "selection_score" in r})
    for symbol, r in focus.items():
        lines.extend(["", f"## {symbol}", "", f"最新报价 {r['last_price']:.8g} USDT（{r['quote_time']}）。"])
        for horizon, label in (("short_term", "短线"), ("long_term", "长线")):
            p = r[horizon]
            lines.append(f"- {label}：**{ACTION_LABELS[p['action']]}**。{p['reason']}。")
            if p["entry_zone"]:
                lines.append(f"  条件参考区 {p['entry_zone'][0]:.8g}–{p['entry_zone'][1]:.8g}；失效止损 {p['stop_loss']:.8g}；目标参考 {p['take_profit_reference']:.8g}（{p['target_kind']}）；净盈亏比 {p['net_reward_risk']:.2f}；新增仓位上限 {p['max_position_pct']}%。有效至 {p['valid_until']}。")
            if p["action"] == "buy_candidate" and "suggested_position_pct" in p:
                lines.append(f"  按当前报价和单笔风险预算估算首仓约 {p['suggested_position_pct']}%；实际仍受共享现金、单币和组合风险额度限制。")
            if p.get("add_condition"):
                lines.append(f"  加仓：{p['add_condition']}。退出：{p['holding_plan']}；最长 {p['max_holding_bars']} 根本周期 K 线，趋势转弱或退出候选队列时提前退出。")
        lines.append("仓位按实际成交价到止损的距离、现金和组合剩余额度计算；尚未触发的参考区不构成入场信号。")
    lines.extend(["", "## 数据限制", ""] + [f"- {x}" for x in report["limitations"]])
    for s, reason in report["data_errors"].items():
        lines.append(f"- {s} 未生成建议：{reason}")
    for s, r in report["watchlist"].items():
        if "selection_score" not in r:
            lines.append(f"- 自选 {s} 未生成建议：{r['reason']}")
    return "\n".join(lines) + "\n"
