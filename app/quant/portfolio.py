"""Shared target-weight account; supports historical OHLC and observed quotes."""

from dataclasses import asdict
from math import isfinite

from app.advisory.engine import DAY, iso
from .strategy import RiskPolicy, allocation, can_hold, is_rebalance_day


class QuantBook:
    def __init__(self, family, policy=RiskPolicy(), cash=10000):
        if not isfinite(cash) or cash <= 0:
            raise ValueError("Initial cash must be positive")
        self.family, self.policy, self.initial_cash = family,policy,float(cash)
        self.cash = float(cash)
        self.positions, self.prices, self.cooldown = {},{},{}
        self.events, self.curve, self.decisions, self.closed = [],[],[],[]
        self.target_weights = {}
        self.peak = self.risk_peak = cash
        self.pause_until = 0
        self.max_drawdown = 0
        self.last_day = None
        self.last_observed = None
        self.cost_multiplier = 1

    @property
    def fee(self):
        return self.policy.fee_bps/10000

    @property
    def slip(self):
        return self.policy.slippage_bps/10000

    def net(self,price):
        return price*(1-self.slip)*(1-self.fee)

    def equity(self):
        return self.cash+sum(p["quantity"]*self.net(self.prices[s]) for s,p in self.positions.items())

    def gross(self):
        return sum(p["quantity"]*self.prices[s] for s,p in self.positions.items())

    def sell(self,s,quantity,raw,now,reason):
        p=self.positions[s]
        quantity=min(p["quantity"],quantity)
        price=raw*(1-self.slip)
        proceeds=quantity*price*(1-self.fee)
        allocated=p["cost"]*quantity/p["quantity"]
        pnl=proceeds-allocated
        self.cash+=proceeds
        p["quantity"]-=quantity
        p["cost"]-=allocated
        p["pnl"]+=pnl
        self.events.append({"time":iso(now),"symbol":s,"side":"sell","quantity":quantity,"price":price,
                            "fee":quantity*price*self.fee,"pnl":pnl,"reason":reason})
        if p["quantity"] < 1e-10:
            self.closed.append({"symbol":s,"entry_time":iso(p["opened_at"]),"exit_time":iso(now),
                                "pnl":p["pnl"],"reason":reason,"holding_days":(now-p["opened_at"])/DAY})
            del self.positions[s]
            if reason in {"stop","gap_stop","missing_bar_writeoff"}:
                self.cooldown[s]=now+7*DAY
            self.target_weights.pop(s,None)

    def buy(self,s,quantity,raw,ask,feature,now):
        eq=self.equity()
        unit=ask*(1+self.slip)*(1+self.fee)
        drag=unit-self.net(raw)
        existing=self.positions.get(s,{"quantity":0})["quantity"]*raw
        p=self.policy
        cap=min(self.cash/unit,
                (p.max_gross*eq-self.gross())/(raw+p.max_gross*drag),
                (p.max_asset*eq-existing)/(raw+p.max_asset*drag),
                feature["volume"]*p.participation/raw)
        quantity=max(0,min(quantity,cap))
        if quantity*raw < 10:
            return
        fill=ask*(1+self.slip)
        cost=quantity*unit
        self.cash-=cost
        self.events.append({"time":iso(now),"symbol":s,"side":"buy","quantity":quantity,"price":fill,
                            "fee":quantity*fill*self.fee,"reason":"target_rebalance",
                            "signal_time":iso(feature["closed_at"])})
        if s in self.positions:
            self.positions[s]["quantity"]+=quantity
            self.positions[s]["cost"]+=cost
        else:
            self.positions[s]={"quantity":quantity,"cost":cost,"pnl":0,"opened_at":now,
                               "stop":max(raw*.65,raw-4*feature["atr"])}

    def risk_state(self,now):
        eq=self.equity()
        self.peak=max(self.peak,eq)
        self.max_drawdown=max(self.max_drawdown,1-eq/self.peak)
        if self.pause_until and now>=self.pause_until:
            self.risk_peak=eq
            self.pause_until=0
        self.risk_peak=max(self.risk_peak,eq)
        dd=1-eq/self.risk_peak if self.risk_peak else 1
        if dd>=self.policy.hard_drawdown and not self.pause_until:
            self.pause_until=now+self.policy.cooldown_days*DAY
        return 0 if self.pause_until>now else .5 if dd>=self.policy.soft_drawdown else 1

    def observe_stops(self,now,prices):
        self.prices.update(prices)
        for s,p in list(self.positions.items()):
            if s in prices and prices[s]<=p["stop"]:
                self.sell(s,p["quantity"],prices[s],now,"gap_stop")

    def decide(self,now,features,prices,asks=None,force_rebalance=False):
        """Price data must be current; all features must precede this UTC day."""
        if any(not isfinite(x) or x<=0 for x in prices.values()):
            raise ValueError("Invalid execution quote")
        if any(f["closed_at"]>=now//DAY*DAY for f in features.values()):
            raise ValueError("Unclosed data in strategy")
        self.observe_stops(now,prices)
        missing=set(self.positions)-set(prices)
        daily=self.last_day!=now//DAY
        # Repeated polling can execute stops, but cannot generate a new daily rebalance.
        if not daily and not force_rebalance:
            return {"status":"missing_position_quotes" if missing else "same_signal", "target_weights":self.target_weights}
        self.last_day=now//DAY
        for s,p in list(self.positions.items()):
            if s not in prices:
                continue
            f=features.get(s)
            if f:
                p["stop"]=max(p["stop"],f["high55"]-5*f["atr"])
                if prices[s]<=p["stop"]:
                    self.sell(s,p["quantity"],prices[s],now,"gap_stop")
                elif not can_hold(self.family,f):
                    self.sell(s,p["quantity"],prices[s],now,"trend_exit")
        scale=self.risk_state(now)
        if scale==0:
            for s,p in list(self.positions.items()):
                if s in prices:
                    self.sell(s,p["quantity"],prices[s],now,"drawdown_exit")
            self.target_weights={}
        if missing:
            return {"status":"missing_position_quotes","missing":sorted(missing),"target_weights":self.target_weights}
        eligible={s:f for s,f in features.items() if now>=self.cooldown.get(s,0) and s in prices}
        breakout=self.family=="donchian" and any(f["close"]>f["prior_high55"] for s,f in eligible.items() if s not in self.positions)
        rebalance=(force_rebalance or is_rebalance_day(now,self.family) or not self.target_weights or breakout)
        info={"ranking":[],"selected":list(self.target_weights)}
        if scale and rebalance:
            weights,info=allocation(self.family,eligible,set(self.positions),self.policy)
            self.target_weights=weights
        desired={s:w*scale for s,w in self.target_weights.items() if s in eligible}
        eq=self.equity()
        for s,p in list(self.positions.items()):
            target=desired.get(s,0)*eq
            difference=p["quantity"]*prices[s]-target
            if difference>self.policy.rebalance_band*eq or s not in desired:
                self.sell(s,difference/prices[s],prices[s],now,"rebalance_reduce")
        for s,weight in sorted(desired.items(),key=lambda x:(-x[1],x[0])):
            quantity=max(0,weight*self.equity()/prices[s]-self.positions.get(s,{"quantity":0})["quantity"])
            f=eligible[s]
            # Do not fill a signal after an extreme overnight jump.
            if abs(prices[s]-f["close"])>3*f["atr"]:
                continue
            if quantity*prices[s] >= self.policy.rebalance_band*self.equity():
                self.buy(s,quantity,prices[s],(asks or {}).get(s,prices[s]),f,now)
        result={"time":iso(now),"status":"ok","family":self.family,"risk_scale":scale,
                "target_weights":desired,"pause_until":iso(self.pause_until) if self.pause_until else None,**info}
        self.decisions.append(result)
        return result

    def close_bar(self,now,bars):
        for s,p in list(self.positions.items()):
            if s not in bars:
                raise ValueError("Missing bar must be explicitly handled before accounting")
            b=bars[s]
            if b.low<=p["stop"]:
                self.sell(s,p["quantity"],min(b.open,p["stop"]),now,"stop")
        self.prices.update({s:b.close for s,b in bars.items()})
        self.record(now)

    def record(self,now):
        self.risk_state(now)
        eq=self.equity()
        self.curve.append({"time":iso(now),"equity":eq,"cash":self.cash,"gross_pct":self.gross()/eq*100 if eq>0 else 0,
                           "positions":len(self.positions)})

    def dump(self):
        return {k:v for k,v in self.__dict__.items() if k!="policy"}|{"policy":asdict(self.policy)}

    @classmethod
    def restore(cls,data):
        book=cls(data["family"],RiskPolicy(**data["policy"]),data["initial_cash"])
        book.__dict__.update({k:v for k,v in data.items() if k!="policy"})
        return book
