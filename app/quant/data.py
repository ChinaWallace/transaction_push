"""Point-in-time daily features. Inactive assets and missing bars remain visible."""

from bisect import bisect_left
from math import isfinite, log, sqrt
from statistics import mean, median, pstdev

from app.advisory.engine import Candle, DAY, iso


class DailyHistory:
    def __init__(self, snapshot):
        self.as_of = int(snapshot["as_of"])
        self.issues = []
        self.data, self.times, self.opens, self.cache = {}, {}, {}, {}
        for symbol, intervals in snapshot["symbols"].items():
            bars = [r if isinstance(r, Candle) else Candle.from_binance(r) for r in intervals["1d"]]
            bars = [b for b in bars if b.close_time < self.as_of]
            valid = []
            previous = -1
            for b in bars:
                numbers = (b.open, b.high, b.low, b.close, b.volume, b.quote_volume)
                if (not all(isfinite(x) for x in numbers) or min(numbers[:4]) <= 0
                        or min(numbers[4:]) < 0 or not b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high
                        or b.open_time % DAY or not b.open_time <= b.close_time < b.open_time+DAY or b.open_time <= previous):
                    raise ValueError(f"Invalid {symbol} OHLCV at {iso(b.open_time)}")
                previous = b.open_time
                if b.close_time != b.open_time+DAY-1:
                    self.issues.append({"symbol":symbol,"time":iso(b.open_time),"reason":"partial_day_bar_excluded"})
                    continue
                valid.append(b)
            bars = valid
            self.data[symbol] = bars
            self.times[symbol] = [b.close_time for b in bars]
            self.opens[symbol] = {b.open_time:b for b in bars}
        if "BTCUSDT" not in self.data:
            raise ValueError("BTC history required")

    def feature(self, symbol, now):
        end = bisect_left(self.times[symbol], now)
        key = symbol,end
        if key in self.cache:
            result = self.cache[key]
            return result if result["closed_at"] == now//DAY*DAY-1 else None
        bars = self.data[symbol][max(0,end-201):end]
        if len(bars) < 201 or bars[-1].close_time != now//DAY*DAY-1:
            return None
        if any(b.open_time-a.open_time != DAY for a,b in zip(bars,bars[1:])):
            return None
        close = [b.close for b in bars]
        returns = [log(b/a) for a,b in zip(close[-61:-1],close[-60:])]
        atr = mean(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(bars[-21:-1],bars[-20:]))
        if atr <= 0:
            return None
        feature = {"closed_at": bars[-1].close_time, "close": close[-1], "atr": atr,
                   "volume20": median(b.quote_volume for b in bars[-20:]), "volume": bars[-1].quote_volume,
                   "annual_vol": max(.15,pstdev(returns)*sqrt(365)), "returns60": returns,
                   "amihud14": mean(abs(b.close/a.close-1)/max(b.quote_volume,1) for a,b in zip(bars[-15:-1],bars[-14:])),
                   "high55": max(b.high for b in bars[-55:]),
                   "prior_high55": max(b.high for b in bars[-56:-1]),
                   "low20": min(b.low for b in bars[-21:-1])}
        feature.update({f"sma{n}":mean(close[-n:]) for n in (20,65,120,150,200)})
        feature.update({f"mom{n}":log(close[-1]/close[-n-1]) for n in (14,20,60,120)})
        self.cache[key] = feature
        return feature

    def features(self, now, symbols=None):
        return {s:f for s in (symbols or self.data) if (f:=self.feature(s,now)) is not None}
