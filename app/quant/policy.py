"""Validated paper portfolio preferences; deployment defaults remain in .env."""
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PortfolioPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    preferred_symbols: list[str] = Field(default_factory=lambda: ["ZECUSDT", "BTCUSDT", "ETHUSDT"], max_length=50)
    candidate_limit: int = Field(default=50, ge=1, le=50)
    max_positions: int = Field(default=50, ge=1, le=50)
    core_stop_mode: Literal["none", "wide"] = "none"
    core_stop_distance: float = Field(default=.35, ge=.1, le=.5)
    core_total_weight: float = Field(default=.7, gt=0, le=.7)
    core_single_weight: float = Field(default=.7, gt=0, le=.7)
    core_allow_weight_drift: bool = False
    satellite_single_weight: float = Field(default=.1, gt=0, le=.1)

    @field_validator("preferred_symbols", mode="before")
    @classmethod
    def symbols(cls, value):
        if isinstance(value, str): value = re.split(r"[,，\s;；]+", value.strip()) if value.strip() else []
        if not isinstance(value, list): raise ValueError("Symbols must be a list")
        result = []
        for item in value:
            if not isinstance(item, str): raise ValueError("Invalid contract symbol")
            symbol = item.strip().upper()
            if not symbol.endswith("USDT"): symbol += "USDT"
            if not re.fullmatch(r"[A-Z0-9]{1,24}USDT", symbol): raise ValueError("Invalid contract symbol")
            if symbol not in result: result.append(symbol)
        return result

    @model_validator(mode="after")
    def capacity(self):
        if len(self.preferred_symbols) > min(self.candidate_limit, self.max_positions):
            raise ValueError("Preferred symbols exceed candidate or position capacity")
        return self

    def revision(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def load_policy(settings, output=None):
    defaults = {name: getattr(settings, "quant_" + name) for name in PortfolioPolicy.model_fields}
    path = Path(output or settings.quant_output_dir) / "portfolio_policy.json"
    if path.exists(): defaults.update(json.loads(path.read_text())["overrides"])
    return PortfolioPolicy(**defaults)


def candidate_pool(ranking, policy):
    lookup = {r["symbol"]: r for r in ranking}
    preferred = [lookup[s] for s in policy.preferred_symbols if s in lookup]
    other = [r for r in ranking if r["symbol"] not in policy.preferred_symbols and not r["rejections"] and "signal" in r]
    return (preferred + other)[:policy.candidate_limit]


def apply_allocations(plan, ranking, policy, capital):
    """Reserve core capital first; preference never overrides quote/data/entry checks."""
    lookup = {r["symbol"]: r for r in ranking}
    core = []
    weight = min(policy.core_single_weight, policy.core_total_weight / max(1, len(policy.preferred_symbols)))
    for symbol in policy.preferred_symbols:
        r = lookup.get(symbol)
        if not r or r["rejections"] or "signal" not in r: continue
        if r["action"] == "underlying_leverage_requires_review": continue
        w = min(weight, .15) if r["market_cap"]["value_usd"] is None else weight
        core.append({"symbol": symbol, "pair": r["base_asset"] + "/USDT:USDT", "weight": w,
                     "leverage": 1, "stop_price": r["ask"] * (1-policy.core_stop_distance) if policy.core_stop_mode == "wide" else 0,
                     "entry_zone": r["entry_zone"], "atr": r["features"]["atr"], "closed_price": r["features"]["close"],
                     "asset_class": r["asset_class"], "score": r["selection_score"], "holding_policy": "core",
                     "stop_mode": policy.core_stop_mode})
    satellite = [{**t, "weight": min(t["weight"], policy.satellite_single_weight), "holding_policy": "satellite", "stop_mode": "atr"}
                 for t in plan["targets"] if t["symbol"] not in policy.preferred_symbols][:policy.max_positions-len(core)]
    margin = sum(t["weight"] for t in core)
    requested = sum(t["weight"]/t["leverage"] for t in satellite)
    margin_limit=min(.85,.65+max(0,policy.core_total_weight-.5))
    scale = min(1, max(0, margin_limit-margin)/requested) if requested else 1
    for t in satellite: t["weight"] *= scale
    plan["targets"] = core + satellite
    for t in plan["targets"]:
        t.update(notional_usdt=capital*t["weight"], margin_usdt=capital*t["weight"]/t["leverage"])
    plan["policy"] = policy.model_dump()
    plan["portfolio_variant"] = "core_satellite_v1"
    plan["policy_revision"] = policy.revision()
    plan["candidate_symbols"] = [r["symbol"] for r in candidate_pool(ranking, policy)]
    plan["max_positions"] = policy.max_positions
    plan["margin_limit"] = margin_limit
    plan["core_drawdown_exempt"] = True
    plan["max_allowed_drawdown"] = None
    plan["hard_drawdown_scope"] = "satellite_only"


def summarize_allocations(plan, ranking):
    lookup = {r["symbol"]: r for r in ranking}
    plan["gross_exposure"] = sum(t["weight"] for t in plan["targets"])
    plan["margin_fraction"] = sum(t["weight"]/t["leverage"] for t in plan["targets"])
    # A zero stop is an explicit absence of a per-coin stop, never zero risk.
    plan["core_exposure"] = sum(t["weight"] for t in plan["targets"] if t.get("holding_policy") == "core")
    plan["unstopped_exposure"] = sum(t["weight"] for t in plan["targets"] if t.get("stop_mode") == "none")
    plan["planned_stop_risk"] = sum(t["weight"]*max(0, 1-t["stop_price"]/lookup[t["symbol"]]["ask"])
                                    for t in plan["targets"] if t.get("holding_policy") != "core" and t["symbol"] in lookup and lookup[t["symbol"]]["ask"] > 0)
    plan["stop_risk_scope"] = "satellite_only; core is exempt from the 45% drawdown exit; total drawdown may exceed 50%"
