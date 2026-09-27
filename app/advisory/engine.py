"""Deterministic, closed-candle spot selection and separate trading horizons.

Scores measure rule agreement, never a probability or a price forecast.
Only the Python standard library is required, including for historical replay.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median
import re

DAY = 86_400_000
INTERVALS = {"1d": DAY, "4h": DAY // 6}
EXCLUDED_BASES = frozenset({
    "USDC", "FDUSD", "USDE", "USDD", "TUSD", "BUSD", "DAI", "USDP",
    "USD1", "U", "EUR", "AEUR", "EURI", "PAXG", "XAUT", "WBTC", "WBETH",
})


@dataclass(frozen=True)
class Policy:
    profile: str = "legacy"
    min_quote_volume: float = 10_000_000
    max_spread_bps: float = 25
    max_candidates: int = 60
    min_daily_bars: int = 220
    risk_budget_pct: float = 0.5
    max_position_pct: float = 10
    fee_bps: float = 10
    slippage_bps: float = 5
    max_positions: int = 4
    max_portfolio_pct: float = 60
    max_portfolio_risk_pct: float = 3
    cooldown_bars: int = 3
    drawdown_pause_pct: float = 15

    def __post_init__(self):
        values = asdict(self)
        if self.profile not in {"legacy", "balanced", "active"}:
            raise ValueError("Unknown strategy profile")
        if any(not isfinite(v) or v < 0 for k, v in values.items() if k != "profile"):
            raise ValueError("Policy values must be finite and nonnegative")
        if (not isinstance(self.max_candidates, int) or not isinstance(self.min_daily_bars, int)
                or not 1 <= self.max_candidates <= 150 or self.min_daily_bars < 220):
            raise ValueError("Candidate count must be 1..150 and history >= 220 days")
        if not 0 < self.max_position_pct <= 100 or not 0 < self.risk_budget_pct <= 2:
            raise ValueError("Invalid position/risk budget")
        if (not isinstance(self.max_positions, int) or not 1 <= self.max_positions <= 10
                or not isinstance(self.cooldown_bars, int) or self.cooldown_bars < 0
                or not 0 < self.max_portfolio_pct <= 100 or not 0 < self.max_portfolio_risk_pct <= 10):
            raise ValueError("Invalid portfolio limits")


def policy_for(profile="active", **overrides):
    values = {
        "legacy": {},
        "balanced": {"risk_budget_pct": 0.5, "max_position_pct": 15, "max_portfolio_pct": 45, "max_portfolio_risk_pct": 2},
        "active": {"risk_budget_pct": 0.75, "max_position_pct": 20, "max_portfolio_pct": 60, "max_portfolio_risk_pct": 3},
    }
    if profile not in values:
        raise ValueError("Unknown strategy profile")
    return Policy(profile=profile, **{**values[profile], **overrides})


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float

    @classmethod
    def from_binance(cls, row):
        return cls(int(row[0]), *(float(v) for v in row[1:6]), int(row[6]), float(row[7]))


def iso(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


def normalize_symbol(value):
    text = value.strip().upper()
    # Futures symbols are deliberately not interpreted as spot quotes.
    if ":" in text or "SWAP" in text:
        raise ValueError("Use a spot symbol such as ZECUSDT or ZEC/USDT")
    text = text.replace("/", "").replace("-", "")
    if not text.endswith("USDT"):
        text += "USDT"
    if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", text):
        raise ValueError("Invalid USDT spot symbol")
    return text


def closed_candles(rows, interval, as_of, minimum):
    """Reject corrupt, gapped and stale data; an open candle is never a signal."""
    step = INTERVALS[interval]
    bars = [r if isinstance(r, Candle) else Candle.from_binance(r) for r in rows]
    bars = [b for b in bars if b.close_time < as_of]
    if len(bars) < minimum:
        raise ValueError(f"{interval}: need {minimum} closed bars, got {len(bars)}")
    previous = None
    for b in bars:
        numbers = (b.open, b.high, b.low, b.close, b.volume, b.quote_volume)
        if (not all(isfinite(v) for v in numbers) or min(numbers[:4]) <= 0
                or b.volume < 0 or b.quote_volume < 0
                or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                or b.open_time % step != 0 or b.close_time != b.open_time + step - 1):
            raise ValueError(f"{interval}: invalid OHLCV or timestamps")
        if previous is not None and b.open_time != previous + step:
            raise ValueError(f"{interval}: missing, duplicate or unsorted bars")
        previous = b.open_time
    if bars[-1].close_time != (as_of // step) * step - 1:
        raise ValueError(f"{interval}: stale candles")
    return bars


def ema(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(result[-1] + alpha * (value - result[-1]))
    return result


def features(bars):
    close = [b.close for b in bars]
    e20, e50, e200 = (ema(close, p) for p in (20, 50, 200))
    tr = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
          for a, b in zip(bars, bars[1:])]
    atr = sum(tr[-14:]) / 14
    if atr <= 0:
        raise ValueError("Zero volatility / unusable candles")
    diffs = [b - a for a, b in zip(close[-15:], close[-14:])]
    gains = sum(max(0, x) for x in diffs)
    losses = sum(max(0, -x) for x in diffs)
    rsi = 100 * gains / (gains + losses) if gains + losses else 50
    volume_base = median(b.volume for b in bars[-21:-1])
    return {
        "close": close[-1], "ema20": e20[-1], "ema50": e50[-1], "ema200": e200[-1],
        "ema50_rising": e50[-1] > e50[-6], "atr": atr, "rsi14": rsi,
        "ema20_rising": e20[-1] > e20[-4], "previous_close": close[-2], "previous_ema20": e20[-2],
        "last_low": bars[-1].low, "last_open": bars[-1].open,
        "close_location": (bars[-1].close-bars[-1].low) / max(bars[-1].high-bars[-1].low, 1e-12),
        "trend_persistence10": sum(c > e for c, e in zip(close[-10:], e50[-10:])) / 10,
        "extension_atr": (close[-1] - e20[-1]) / atr,
        "prior_high20": max(b.high for b in bars[-21:-1]),
        "prior_high60": max(b.high for b in bars[-61:-1]),
        "low10": min(b.low for b in bars[-10:]),
        "low5": min(b.low for b in bars[-5:]),
        "high20": max(b.high for b in bars[-20:]),
        "drawdown90_pct": (close[-1] / max(b.high for b in bars[-90:]) - 1) * 100,
        "volume_ratio": bars[-1].volume / volume_base if volume_base else 0,
        "median_quote_volume20": median(b.quote_volume for b in bars[-20:]),
        "last_quote_volume": bars[-1].quote_volume,
        **{f"return{n}_pct": (close[-1] / close[-n-1] - 1) * 100 for n in (7, 30, 90)},
    }


def select_universe(exchange_info, tickers, as_of, watchlist=(), policy=Policy()):
    """Watchlists retain visibility, but never bypass liquidity/data filters."""
    eligible, rejected = [], {}
    by_symbol = {t.get("symbol"): t for t in tickers}
    for item in exchange_info.get("symbols", []):
        symbol = item.get("symbol", "")
        if item.get("quoteAsset") != "USDT":
            continue
        reason = None
        t = by_symbol.get(symbol, {})
        try:
            price, bid, ask, volume = (float(t.get(k, 0)) for k in
                                      ("lastPrice", "bidPrice", "askPrice", "quoteVolume"))
            age = as_of - int(t.get("closeTime", 0))
            if item.get("status") != "TRADING" or not item.get("isSpotTradingAllowed", False):
                reason = "非活跃现货交易对"
            elif item.get("baseAsset") in EXCLUDED_BASES:
                reason = "稳定币、法币、黄金或重复敞口"
            elif not all(isfinite(v) and v > 0 for v in (price, bid, ask, volume)) or ask < bid:
                reason = "报价缺失或无效"
            elif age < -120_000 or age > 600_000:
                reason = "行情时间过期或异常"
            elif volume < policy.min_quote_volume:
                reason = "24 小时成交额不足"
            elif (ask - bid) / ((ask + bid) / 2) * 10_000 > policy.max_spread_bps:
                reason = "买卖价差过大"
        except (ValueError, TypeError):
            reason = "行情字段无效"
        if reason:
            rejected[symbol] = reason
        else:
            eligible.append((symbol, volume))
    eligible.sort(key=lambda item: (-item[1], item[0]))
    selected = [s for s, _ in eligible[:policy.max_candidates]]
    allowed = {s for s, _ in eligible}
    watched = [normalize_symbol(s) for s in watchlist]
    for s in ["BTCUSDT", "ETHUSDT", *watched]:
        if s in allowed and s not in selected:
            selected.append(s)
    for s in watched:
        if s not in allowed:
            rejected.setdefault(s, "交易所没有该活跃现货交易对")
    return selected, rejected


def plan(horizon, f, daily, strength, market, score, as_of, policy):
    if policy.profile != "legacy":
        return active_plan(horizon, f, daily, strength, market, score, as_of, policy)
    short = horizon == "short_term"
    max_risk = 0.08 if short else 0.20
    step = INTERVALS["4h" if short else "1d"]
    uptrend = f["close"] > f["ema50"] and f["ema20"] > f["ema50"] and f["ema50_rising"]
    extension = f["extension_atr"] > (2 if short else 3)
    daily_up = daily["close"] > daily["ema50"] and daily["ema50_rising"]
    strong = strength > 0 or strength == 0 and score >= 65
    action, reason = "watch", "等待趋势、相对强度与入场条件一致"
    if f["close"] < f["ema50"] and not f["ema50_rising"]:
        action, reason = "avoid", "趋势转弱；已有持仓按失效条件减仓"
    elif uptrend and daily_up and strong and score >= 65:
        if extension:
            action, reason = "wait_pullback", "趋势仍强，但偏离均线过大，等待回踩确认"
        elif market == "risk_off":
            action, reason = "watch", "BTC 趋势偏弱，保留强势币观察，暂停新增仓位"
        elif (f["close"] > f["prior_high20"] and f["volume_ratio"] >= 1.2
              or f["ema20"] - 0.5 * f["atr"] <= f["close"] <= f["ema20"] + f["atr"]):
            action, reason = "buy_candidate", "趋势与相对强度通过，突破放量或回踩均线区间确认"
    anchor = f["ema20"] if extension else f["close"]
    low, high = anchor - 0.25 * f["atr"], anchor + 0.25 * f["atr"]
    stop = min(f["low10"] - 0.5 * f["atr"], low - 1.5 * f["atr"])
    risk = (high - stop) / high if high > 0 else 1
    cost = 2 * (policy.fee_bps + policy.slippage_bps) / 10_000
    resistance = f["prior_high60"]
    target = resistance if resistance > high else high + 3 * (high - stop)
    rr = ((target - high) / high - cost) / (risk + cost)
    if action == "buy_candidate" and (stop <= 0 or risk > max_risk or rr < 2):
        action, reason = "watch", "止损距离过大或扣除交易成本后盈亏比不足 2，等待更好入场"
    actionable = action == "buy_candidate"
    valid_setup = stop > 0 and high > low > stop
    return {
        "horizon": "1–7 天" if short else "1–3 个月",
        "timeframe": "4h + 1d" if short else "1d（至少 220 天历史）",
        "action": action, "reason": reason,
        "entry_zone": [round(low, 8), round(high, 8)] if valid_setup and uptrend else None,
        "stop_loss": round(stop, 8) if valid_setup and uptrend else None,
        "take_profit_reference": round(target, 8) if valid_setup and uptrend else None,
        "target_kind": "历史阻力" if resistance > high else "3R 风险倍数目标，非价格预测",
        "net_reward_risk": round(rr, 3) if valid_setup and uptrend else None,
        "stop_distance_pct": round(risk * 100, 3) if valid_setup and uptrend else None,
        "max_position_pct": round(min(policy.max_position_pct, policy.risk_budget_pct / (risk + cost)), 2) if actionable else 0,
        "account_risk_budget_pct": policy.risk_budget_pct if actionable else 0,
        "valid_until": iso((as_of // step + 1) * step),
        "invalidation": "触及止损，或已收盘价格跌破 EMA50 且均线转弱；跳空可能超出止损预算",
        "holding_plan": "到阻力/目标分批止盈，余仓以 EMA50-ATR 跟踪且止损只能上移；每根收盘重评，禁止仅因超买开空",
        "trailing_stop_reference": max(0, f["ema50"] - f["atr"]),
        "fundamental_review_required": not short,
    }


def active_plan(horizon, f, daily, strength, market, score, as_of, policy):
    """Three independent entries; risk sizing replaces stacked entry vetoes."""
    short = horizon == "short_term"
    step = INTERVALS["4h" if short else "1d"]
    active = policy.profile == "active"
    min_score = 60 if active else 70
    trend = f["close"] > f["ema50"] and f["ema20"] > f["ema50"] and f["ema20_rising"]
    daily_support = daily["close"] > daily["ema50"] or daily["ema20_rising"] and daily["return7_pct"] > 0
    relative = daily.get("rs30_btc_pct", strength)
    leader = relative > 0 or relative == 0 and score >= min_score
    setup, action, reason = None, "watch", "趋势资格不足，暂不开仓"
    risk_scale = 1.0
    extension_limit = (4 if short else 5) if active else 3
    if f["close"] < f["ema50"] and (not f["ema50_rising"] or f["close"] < f["ema50"]-f["atr"]):
        action, reason = "avoid", "收盘跌破趋势支撑，已有仓位退出"
    elif trend and daily_support and leader and score >= min_score:
        if f["extension_atr"] > extension_limit:
            action, reason = "wait_pullback", "趋势仍强但过度延伸，暂不追价；持仓继续跟踪止损"
        elif market == "risk_off" and (score < 80 or relative < 10):
            reason = "BTC 弱势且相对强度不足，暂停新增仓位"
        else:
            breakout = f["close"] > f["prior_high20"] and f["volume_ratio"] >= 1.1 and f["close_location"] >= .55
            pullback = (f["last_low"] <= f["ema20"]+.5*f["atr"] and f["close"] >= f["ema20"]
                        and f["close"] >= f["last_open"] and f["close_location"] >= .5)
            continuation = (f["close"] >= f["ema20"] and f["close"] >= f["previous_close"]*.995
                            and f["volume_ratio"] >= .6 and f["return7_pct"] > 0)
            if breakout:
                setup, reason = "breakout", "已收盘放量突破，下一成交时点在区间内则分批买入"
            elif pullback:
                setup, reason = "pullback", "回踩 EMA20 后收回，分批买入"
            elif continuation:
                setup, reason, risk_scale = "continuation", "趋势中继，小仓试入；浮盈达到 1R 后才允许加仓", .5
            else:
                reason = "趋势保留，但本根仍在回落；等待收回均线或收盘企稳"
            if setup:
                action = "buy_candidate"
                if market == "risk_off":
                    risk_scale *= .5
                    reason += "；大盘弱势，风险预算减半"
    anchor = f["ema20"] if action == "wait_pullback" else f["close"]
    low, high = anchor-.4*f["atr"], anchor+.6*f["atr"]
    # A volatility stop with nearby structure, instead of the widest 10-bar low.
    multiple = 2 if short else 2.5
    stop = max(anchor-multiple*f["atr"], min(f["low5"]-.25*f["atr"], anchor-1.25*f["atr"]))
    risk = (high-stop)/high if high > 0 else 1
    cost = 2*(policy.fee_bps+policy.slippage_bps)/10_000
    first_r = 1.5 if short else 2
    target = high+first_r*(high-stop)
    runner = high+3*(high-stop)
    rr = ((target-high)/high-cost)/(risk+cost)
    if action == "buy_candidate" and (stop <= 0 or risk > (.14 if short else .25) or cost > risk*.25):
        action, reason = "watch", "波动或交易成本超过该周期的风险限额，暂不开仓"
    actionable = action == "buy_candidate"
    budget = policy.risk_budget_pct*risk_scale if actionable else 0
    return {
        "horizon": "1–7 天" if short else "1–3 个月", "timeframe": "4h + 1d" if short else "1d",
        "action": action, "reason": reason, "setup": setup, "strategy_profile": policy.profile,
        "entry_zone": [round(low, 8), round(high, 8)] if stop > 0 and low > stop else None,
        "stop_loss": round(stop, 8) if stop > 0 else None,
        "take_profit_reference": round(target, 8), "runner_target_reference": round(runner, 8),
        "resistance_reference": f["prior_high60"], "target_kind": f"{first_r}R 分批止盈，余仓跟踪；非价格预测",
        "net_reward_risk": round(rr, 3), "stop_distance_pct": round(risk*100, 3),
        "max_position_pct": policy.max_position_pct if actionable else 0,
        "suggested_position_pct": round(min(policy.max_position_pct, budget/(risk+cost)), 2) if actionable else 0,
        "account_risk_budget_pct": budget, "valid_until": iso((as_of//step+1)*step),
        "trailing_stop_reference": max(0, f["high20"]-(2.5 if short else 3)*f["atr"]),
        "invalidation": "硬止损，或收盘跌破 EMA50 且趋势转弱；次根开盘退出，跳空按更差价格处理",
        "holding_plan": "首次目标卖出三分之一；余仓用前一收盘的高点减 ATR 跟踪；止损只能上移",
        "add_condition": "持仓至少浮盈 1R、仍有买入信号且排名在候选池内；最多加仓一次，不摊平亏损",
        "max_holding_bars": 42 if short else 90, "partial_exit_fraction": 1/3,
        "fundamental_review_required": not short,
    }


def analyze_daily(symbol, daily_rows, btc_daily_rows, as_of, policy=Policy()):
    daily = closed_candles(daily_rows, "1d", as_of, policy.min_daily_bars)
    btc = closed_candles(btc_daily_rows, "1d", as_of, policy.min_daily_bars)
    if [b.open_time for b in daily[-91:]] != [b.open_time for b in btc[-91:]]:
        raise ValueError("BTC benchmark timestamps do not align")
    return daily_result(symbol, features(daily[-300:]), features(btc[-300:]), daily[-1].close_time, as_of, policy)


def daily_result(symbol, d, benchmark, close_time, as_of, policy):
    """Pure decision kernel shared by live analysis and prevalidated replay data."""
    if d["median_quote_volume20"] < policy.min_quote_volume:
        raise ValueError("20 日成交额中位数不足，单日放量不构成持续流动性")
    rs = {f"rs{n}_btc_pct": ((1 + d[f"return{n}_pct"] / 100)
                            / (1 + benchmark[f"return{n}_pct"] / 100) - 1) * 100 for n in (30, 90)}
    components = {
        "trend": 10 * sum((d["close"] > d["ema20"], d["ema20"] > d["ema50"],
                            d["ema50"] > d["ema200"], d["ema50_rising"])),
        "relative_strength": sum(max(0, min(15, 7.5 + rs[f"rs{n}_btc_pct"] / 2)) for n in (30, 90)),
        "momentum": sum(5 * (d[f"return{n}_pct"] > 0) for n in (7, 30, 90)),
        "trend_persistence": 10 * d["trend_persistence10"],
        "drawdown": max(0, 5 + d["drawdown90_pct"] / 4),
    }
    score = round(sum(components.values()), 2)
    if policy.profile != "legacy":
        # Keep discrimination among leaders instead of saturating every bull at 95+.
        components = {
            "trend": components["trend"]*.75,
            "relative_strength": sum(max(0, min(15, 7.5+rs[f"rs{n}_btc_pct"]/(4 if n == 30 else 8))) for n in (30, 90)),
            "momentum": sum(max(0, min(10, 5+d[f"return{n}_pct"]/(2 if n == 7 else 6 if n == 30 else 12))) for n in (7,30,90)),
            "trend_persistence": components["trend_persistence"]*.5,
            "drawdown": components["drawdown"],
        }
        score = round(sum(components.values()), 2)
    market = "risk_off" if benchmark["close"] < benchmark["ema200"] and not benchmark["ema50_rising"] else "normal"
    return {
        "symbol": normalize_symbol(symbol), "market": "binance_spot", "as_of": iso(as_of),
        "daily_close_time": iso(close_time),
        "selection_score": score, "score_kind": "规则评分，未经胜率校准", "win_probability": None,
        "score_components": components, "market_regime": market,
        "metrics": {**d, **rs},
        "long_term": plan("long_term", d, {**d, **rs}, rs["rs90_btc_pct"], market, score, as_of, policy),
        "risks": ["规则尚需样本外及前瞻验证", "日线趋势不能替代代币解锁、采用率、监管与项目基本面研究"]
                 + (["日线明显超买：限制追高，但不作为做空证据"] if d["rsi14"] > 70 else []),
    }


def analyze(symbol, daily_rows, four_hour_rows, btc_daily_rows, as_of, policy=Policy()):
    result = analyze_daily(symbol, daily_rows, btc_daily_rows, as_of, policy)
    four = closed_candles(four_hour_rows, "4h", as_of, 100)
    result["four_hour_close_time"] = iso(four[-1].close_time)
    result["execution_quote_volume"] = {"short_term": four[-1].quote_volume,
                                       "long_term": result["metrics"]["last_quote_volume"]}
    d = result["metrics"]
    result["short_term"] = plan("short_term", features(four[-300:]), d, d["rs30_btc_pct"],
                                result["market_regime"], result["selection_score"], as_of, policy)
    return result
