"""USDT single-collateral, long-only cross-margin accounting and risk.

Pure arithmetic: no credentials, network, exchange orders, or implicit transfers.
The caller supplies the maintenance tiers and synchronized mark prices.
"""
from math import isfinite


def maintenance(notional, tiers):
    if not isfinite(notional) or notional < 0:
        raise ValueError('Invalid notional')
    if not tiers:raise ValueError('Maintenance tiers required')
    for tier in tiers:
        if tier['minNotional'] <= notional <= tier['maxNotional']:
            return max(0.0, notional*tier['maintenanceMarginRate'] - float(tier['info']['cum']))
    raise ValueError('Notional outside supported maintenance tiers')


class CrossMarginAccount:
    def __init__(self, capital, tiers, fee=.001):
        if not isfinite(capital) or capital <= 0 or not 0 <= fee < .01:
            raise ValueError('Invalid capital or fee')
        self.initial_cash = self.wallet = float(capital)
        self.tiers = tiers
        self.fee = fee
        self.positions = {}
        self.marks = {}
        self.events = []
        self.funding_keys = set()

    def state(self, marks=None):
        marks = self.marks if marks is None else marks
        gross = cost = required = 0.0
        for symbol,p in self.positions.items():
            mark=marks[symbol]
            if not isfinite(mark) or mark < 0:raise ValueError('Invalid mark')
            value=p['quantity']*mark
            gross+=value;cost+=p['quantity']*p['entry']
            required+=maintenance(value,self.tiers[symbol])
        equity=self.wallet+gross-cost
        return dict(wallet=self.wallet,equity=equity,gross=gross,maintenance=required,
            maintenance_buffer=equity-required,all_zero_cash_floor=self.wallet-cost,
            effective_leverage=gross/equity if equity>0 else None,
            estimated_initial_margin=sum(p['quantity']*marks[s]/p['leverage'] for s,p in self.positions.items()),
            at_liquidation=equity<=required)

    def conditional_liquidation_price(self,symbol):
        """Other marks held constant, no future fees; None means no positive root."""
        p=self.positions[symbol];q=p['quantity']
        other_upnl=sum(v['quantity']*(self.marks[s]-v['entry']) for s,v in self.positions.items() if s!=symbol)
        other_mm=sum(maintenance(v['quantity']*self.marks[s],self.tiers[s]) for s,v in self.positions.items() if s!=symbol)
        numerator=q*p['entry']-self.wallet-other_upnl+other_mm
        roots=[]
        for t in self.tiers[symbol]:
            rate=t['maintenanceMarginRate']
            if not 0<=rate<1:raise ValueError('Unsupported maintenance rate')
            x=(numerator-float(t['info']['cum']))/(q*(1-rate))
            if x>0 and t['minNotional']-1e-7<=q*x<=t['maxNotional']+1e-7:roots.append(x)
        return max(roots) if roots else None

    def buy(self,symbol,quantity,price,at,reason,leverage=2):
        if leverage not in (1,2) or not all(isfinite(v) and v>0 for v in (quantity,price)):
            raise ValueError('Unsupported core order')
        if symbol not in self.tiers or symbol not in self.marks:raise ValueError('Missing risk inputs')
        p=self.positions.get(symbol)
        if p and p['leverage']!=leverage:raise ValueError('Explicit migration required')
        maintenance(((p['quantity'] if p else 0)+quantity)*self.marks[symbol],self.tiers[symbol])
        before=self.state();cost=quantity*price;fee=cost*self.fee
        new_margin=before['estimated_initial_margin']+quantity*self.marks[symbol]/leverage
        new_equity=before['equity']-fee+quantity*(self.marks[symbol]-price)
        if new_margin>new_equity:raise ValueError('Insufficient cross initial margin')
        self.wallet-=fee
        if p:
            p['entry']=(p['entry']*p['quantity']+cost)/(p['quantity']+quantity)
            p['quantity']+=quantity
        else:self.positions[symbol]=dict(quantity=quantity,entry=price,leverage=leverage)
        self.events.append(dict(timestamp=at,symbol=symbol,side='buy',amount=quantity,price=price,fee=fee,reason=reason))

    def sell(self,symbol,quantity,price,at,reason):
        if not all(isfinite(v) and v>0 for v in (quantity,price)):raise ValueError('Invalid sell')
        p=self.positions[symbol];quantity=min(quantity,p['quantity']);fee=quantity*price*self.fee
        self.wallet+=quantity*(price-p['entry'])-fee
        p['quantity']-=quantity
        if p['quantity']<1e-10:del self.positions[symbol]
        self.events.append(dict(timestamp=at,symbol=symbol,side='sell',amount=quantity,price=price,fee=fee,reason=reason))

    def fund(self,symbol,at,rate,mark):
        if not all(isfinite(v) for v in (rate,mark)) or mark<=0:raise ValueError('Invalid funding')
        key=(symbol,at)
        if key in self.funding_keys:return
        self.funding_keys.add(key)
        if symbol not in self.positions:return
        payment=self.positions[symbol]['quantity']*mark*rate
        self.wallet-=payment
        self.events.append(dict(timestamp=at,symbol=symbol,side='funding',payment=payment,rate=rate,mark=mark))

    def reduce_to(self,target_leverage,prices,at):
        """Proportional known-quote sale, including cost/spread drag in the target.

        A target below 1 creates a positive all-assets-zero cash floor, provided
        every fill succeeds. This is an observable risk reduction, not a stop
        filled retroactively at an unseen intrabar price.
        """
        if not 0<=target_leverage<1:raise ValueError('Reduction target must remove positive basket liquidation risk')
        state=self.state()
        if state['equity']<=0:raise ValueError('Already insolvent')
        if state['gross']<=target_leverage*state['equity']+1e-8:return False
        if any(s not in prices or not isfinite(prices[s]) or prices[s]<=0 for s in self.positions):
            raise ValueError('Missing or invalid execution price')
        total_drag=sum(p['quantity']*(self.marks[s]-prices[s]+prices[s]*self.fee) for s,p in self.positions.items())
        denominator=state['gross']-target_leverage*total_drag
        if denominator<=0:raise ValueError('Unfillable reduction')
        fraction=min(1.0,(state['gross']-target_leverage*state['equity'])/denominator)
        for s,p in list(self.positions.items()):
            self.sell(s,p['quantity']*fraction,prices[s],at,'cross_reduce_to_cash_floor')
        after=self.state()
        if after['gross']>target_leverage*after['equity']+1e-6 or after['all_zero_cash_floor']<=0:
            raise ValueError('Reduction failed risk target')
        return True
