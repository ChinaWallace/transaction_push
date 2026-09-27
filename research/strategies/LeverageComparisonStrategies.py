"""Offline-only 2x counterparts; the engine's liquidation protection stays on."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from HoldingComparisonStrategies import HoldEqual, D55HoldEntry


class TwoTimes:
    def leverage(self, **kwargs):
        return 2.0


class HoldMargin2x(TwoTimes, HoldEqual): pass
class HoldNotional2x(TwoTimes, HoldEqual): pass
class D55Margin2x(TwoTimes, D55HoldEntry): pass
class D55Notional2x(TwoTimes, D55HoldEntry): pass
