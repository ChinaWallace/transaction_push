"""Strategy-specific absolute stop proposals from already closed candles.

Pure calculations shared with offline research; proposal does not place orders.
The execution engine must never move an existing stop farther from the market.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class StopProfile:
    name: str
    initial_atr: float
    trailing_atr: float | None
    activate_profit_atr: float = 0.0
    structure_buffer_atr: float | None = None


PROFILES = {
    "fixed": StopProfile("fixed", 3.5, None),
    "closed_trail": StopProfile("closed_trail", 3.5, 4.0, 2.0),
    "structure": StopProfile("structure", 3.5, None, structure_buffer_atr=.5),
}


def initial_stop(profile: StopProfile, entry: float, atr: float, max_loss: float,
                 structure_low: float | None = None) -> float:
    if not all(isfinite(v) and v > 0 for v in (entry, atr, max_loss)) or max_loss >= 1:
        raise ValueError("Invalid stop inputs")
    proposed = entry - profile.initial_atr * atr
    if profile.structure_buffer_atr is not None:
        if structure_low is None or not isfinite(structure_low) or not 0 < structure_low < entry:
            raise ValueError("Structure must be a finite closed-bar low below entry")
        proposed = structure_low - profile.structure_buffer_atr * atr
    return max(entry * (1 - max_loss), proposed)


def closed_stop(profile: StopProfile, *, entry: float, entry_atr: float, initial: float,
                previous_stop: float, closed_high: float, current_atr: float,
                structure_low: float | None = None) -> float:
    values = (entry, entry_atr, initial, previous_stop, closed_high, current_atr)
    if not all(isfinite(v) and v > 0 for v in values):
        raise ValueError("Invalid closed-bar stop inputs")
    proposed = initial
    if profile.trailing_atr is not None and closed_high >= entry + profile.activate_profit_atr * entry_atr:
        proposed = max(proposed, closed_high - profile.trailing_atr * current_atr)
    if profile.structure_buffer_atr is not None:
        if structure_low is None or not isfinite(structure_low) or structure_low <= 0:
            raise ValueError("Missing closed structure low")
        proposed = max(proposed, structure_low - profile.structure_buffer_atr * current_atr)
    return max(previous_stop, proposed)
