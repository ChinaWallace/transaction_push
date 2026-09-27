"""Cash-backed profit pyramiding arithmetic, shared by offline research only."""
from math import isfinite


def growth_notional(*, initial_quantity, initial_price, current_price, added_cost,
                    last_add_price, profit_fraction, free_collateral, equity,
                    reserve_cash, breakout):
    """Use a profitable seed as permission to deploy cash, never mint profit cash.

    A new 4h breakout and a further 20% rise since the previous buy are required.
    Additional cost is bounded by 50%/100% of the original seed's current gain.
    Cash is supplied by genuinely unused collateral; one fill is <=5% equity.
    """
    values = (initial_quantity, initial_price, current_price, added_cost,
              last_add_price, profit_fraction, free_collateral, equity, reserve_cash)
    if not all(isfinite(v) for v in values):
        raise ValueError("Non-finite growth input")
    if (min(initial_quantity, initial_price, current_price, last_add_price, equity) <= 0
            or added_cost < 0 or reserve_cash < 0 or not 0 <= profit_fraction <= 1):
        raise ValueError("Invalid growth input")
    if not breakout or current_price < last_add_price * 1.2:
        return 0.0
    seed_gain = initial_quantity * max(0, current_price - initial_price)
    return max(0.0, min(profit_fraction * seed_gain - added_cost,
                        free_collateral - reserve_cash, .05 * equity))
