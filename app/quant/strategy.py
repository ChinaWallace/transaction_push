"""Independent implementations of published trend/momentum concepts.

No downloaded strategy code, fitted parameters, future prices, or ML confidence.
"""

from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from statistics import mean, pstdev

from app.advisory.engine import DAY

FAMILIES = ("donchian", "dual_momentum", "trend_ensemble", "liquidity_momentum")


@dataclass(frozen=True)
class RiskPolicy:
    max_gross: float = .95
    max_asset: float = .40
    target_vol: float = .75
    soft_drawdown: float = .30
    hard_drawdown: float = .45
    cooldown_days: int = 28
    min_daily_turnover: float = 5_000_000
    max_positions: int = 4
    fee_bps: float = 10
    slippage_bps: float = 10
    rebalance_band: float = .025
    participation: float = .001

    def __post_init__(self):
        if any(not isfinite(x) or x < 0 for x in asdict(self).values()):
            raise ValueError("Risk settings must be finite and nonnegative")
        if not (0 < self.max_asset <= self.max_gross <= 1 and 0 < self.soft_drawdown < self.hard_drawdown < 1
                and 0 < self.target_vol <= 2 and 1 <= self.max_positions <= 10
                and isinstance(self.max_positions,int) and isinstance(self.cooldown_days,int)
                and 0 < self.participation <= .01 and self.fee_bps < 100 and self.slippage_bps < 100):
            raise ValueError("Invalid spot risk policy")


def momentum(f):
    return (.5*f["mom20"]+.3*f["mom60"]+.2*f["mom120"])/sqrt(f["annual_vol"])


def confidence(f):
    return sum(f["close"] > f[f"sma{n}"] for n in (20,65,150,200))/4


def can_hold(name, f):
    if name == "donchian":
        return f["close"] > f["low20"]
    if name == "dual_momentum":
        return f["close"] > f["sma120"] and f["mom120"] > 0
    if name == "trend_ensemble":
        return confidence(f) >= .5 and f["mom60"] > 0
    return True


def allocation(name, features, held, policy=RiskPolicy()):
    if name not in FAMILIES:
        raise ValueError("Unknown strategy family")
    liquid = {s:f for s,f in features.items() if f["volume20"] >= policy.min_daily_turnover}
    ranking = sorted(liquid, key=lambda s:(-momentum(liquid[s]),s))
    if name == "liquidity_momentum":
        ranked = sorted(liquid,key=lambda s:(-liquid[s]["mom14"],s))
        liquid_rank = sorted(liquid,key=lambda s:(liquid[s]["amihud14"],s))
        intersection = set(ranked[:max(1,int(len(ranked)*.3))]) & set(liquid_rank[:max(1,int(len(liquid_rank)*.5))])
        chosen = [s for s in ranked if s in intersection and liquid[s]["mom14"]>0][:policy.max_positions]
    else:
        eligible = [s for s in ranking if can_hold(name,liquid[s])]
        # Keep a winner while it remains in the leading cohort, reducing churn.
        retained = [s for s in eligible[:policy.max_positions*2] if s in held]
        fresh = [s for s in eligible if s not in retained and
                 (name != "donchian" or liquid[s]["close"] > liquid[s]["prior_high55"])]
        chosen = (retained+fresh)[:policy.max_positions]
    raw = {s:(1 if name == "liquidity_momentum" else 1/liquid[s]["annual_vol"])*
             (confidence(liquid[s]) if name == "trend_ensemble" else 1) for s in chosen}
    total = sum(raw.values())
    weights = {s:v/total for s,v in raw.items()} if total else {}
    if weights:
        # Portfolio covariance comes from synchronized daily return vectors.
        synthetic = [sum(weights[s]*liquid[s]["returns60"][i] for s in weights) for i in range(60)]
        portfolio_vol = max(.10,pstdev(synthetic)*sqrt(365))
        gross = min(policy.max_gross,policy.target_vol/portfolio_vol)
        weights = {s:min(policy.max_asset,w*gross) for s,w in weights.items()}
        # Do not redistribute capped weights into riskier assets.
    return weights, {"ranking": ranking, "selected": chosen, "eligible_count": len(liquid),
                     "expected_annual_vol": portfolio_vol if weights else 0,
                     "scores": {s:momentum(liquid[s]) for s in ranking}}


def is_rebalance_day(now, family):
    return (now//DAY) % (14 if family == "liquidity_momentum" else 7) == 0
