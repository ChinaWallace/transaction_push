"""Shared bounded scan cache for API and existing scheduled summaries."""

from copy import deepcopy
import threading
import time

from .engine import policy_for, normalize_symbol
from .market import MarketDataError, refresh_quotes, scan_market


class AdvisoryService:
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._report = None
        self._expires = 0

    def report(self, watchlist=("ZECUSDT",), max_candidates=60, profile="active"):
        if len(watchlist) > 10:
            raise ValueError("At most 10 watchlist symbols")
        watchlist = tuple(sorted({normalize_symbol(s) for s in watchlist}))
        policy = policy_for(profile, max_candidates=max_candidates)
        key = (watchlist, max_candidates, profile)
        if not self._lock.acquire(blocking=False):
            raise MarketDataError("Market scan in progress; retry shortly")
        try:
            now = time.time()
            if self._key == key and self._report and now < self._expires:
                return refresh_quotes(deepcopy(self._report))
            report = scan_market(watchlist, policy)
            self._key, self._report = key, report
            # Never carry a cached plan over its next 4h candle boundary.
            self._expires = min(now + 300, (int(now) // 14400 + 1) * 14400)
            return deepcopy(report)
        finally:
            self._lock.release()


advisory_service = AdvisoryService()
