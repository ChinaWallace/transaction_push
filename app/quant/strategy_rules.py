"""Explicit, versioned exit rules shared by paper execution and research."""
from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class StrategyRules:
    name: str = "mtf_72h"
    max_hold_hours: int = 72
    exit_timeframe: str = "15m_1h"
    entry_mode: str = "mtf"
    atr_timeframe: str = "1h"
    retain_until_exit: bool = False

    def __post_init__(self):
        if not 0 <= self.max_hold_hours <= 720: raise ValueError("Invalid holding-time limit")
        if self.exit_timeframe not in {"15m_1h", "1h", "4h"}: raise ValueError("Invalid exit timeframe")
        if self.entry_mode not in {"mtf", "4h_breakout"}: raise ValueError("Invalid entry mode")
        if self.atr_timeframe not in {"1h", "4h"}: raise ValueError("Invalid ATR timeframe")

    def revision(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()[:12]


CASES = {
    "mtf_72h": StrategyRules(),
    "mtf_no_time": StrategyRules("mtf_no_time",0),
    "hourly_swing": StrategyRules("hourly_swing",0,"1h",retain_until_exit=True),
    "four_hour_breakout": StrategyRules("four_hour_breakout",0,"4h","4h_breakout","4h",True),
}


def apply_rules(ranking, rules, preferred_symbols=()):
    """Return variant rows; identical preferred/core entry signals in every case."""
    result=[]
    for original in ranking:
        row={**original}
        if "signal" not in row or row["symbol"] in preferred_symbols:
            result.append(row);continue
        row["signal"]={**row["signal"]}
        f4=row["timeframes"]["4h"]
        if rules.exit_timeframe != "15m_1h":row["signal"]["exit_15m"]=False
        if rules.exit_timeframe == "4h":row["signal"]["exit_1h"]=f4["close"]<f4["ema50"]
        if rules.atr_timeframe == "4h":
            row["features"]={**row["features"],"atr":f4["atr"]}
            row["stop_price"]=max(row["features"]["close"]-2.5*f4["atr"],row["features"]["close"]*.75)
        if rules.entry_mode == "4h_breakout" and not row["rejections"] and row["action"]!="underlying_leverage_requires_review":
            valid=f4["close"]>f4["prior_high20"] and f4["close"]>f4["ema50"]
            row["action"]="candidate" if valid else "wait_4h_breakout"
            row["entry_zone"]=[row["stop_price"]*1.001,f4["close"]+.5*row["timeframes"]["15m"]["atr"]]
            row["signal"]["trigger_15m"]="closed_4h_breakout" if valid else None
        if rules.retain_until_exit:
            row["hold_eligible"]=not row["rejections"] and not row["signal"]["exit_1h"] and not row["signal"]["exit_15m"]
        result.append(row)
    return result
