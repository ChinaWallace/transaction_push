"""Research sleeves on ONE cross-margin net position, never separate wallets."""
from math import floor

from .cross_margin import CrossMarginAccount


class CoreOverlayAccount(CrossMarginAccount):
    def __init__(self, capital, tiers, fee=.001):
        super().__init__(capital, tiers, fee)
        self.core = {}
        self.overlay = {}
        self.flow = {'core': 0.0, 'overlay': 0.0}
        self.funding_flow = {'core': 0.0, 'overlay': 0.0}

    def purchase(self, sleeve, symbol, quantity, price, at, reason):
        if sleeve not in self.flow:raise ValueError('Unknown sleeve')
        self.buy(symbol, quantity, price, at, reason, leverage=2)
        self.events[-1]['sleeve'] = sleeve
        self.flow[sleeve] -= quantity*price*(1+self.fee)
        target = self.core if sleeve == 'core' else self.overlay
        if symbol not in target:target[symbol] = dict(quantity=0.0, entry=price)
        p = target[symbol]
        p['entry'] = (p['entry']*p['quantity']+quantity*price)/(p['quantity']+quantity)
        p['quantity'] += quantity

    def sell_sleeve(self, sleeve, symbol, quantity, price, at, reason):
        if sleeve not in self.flow:raise ValueError('Unknown sleeve')
        target = self.core if sleeve == 'core' else self.overlay
        p = target[symbol]
        if quantity > p['quantity']+1e-9:raise ValueError('Sale would consume other sleeve')
        quantity = min(quantity, p['quantity'])
        # The real wallet realizes against the aggregate net-position average.
        self.sell(symbol, quantity, price, at, reason)
        self.events[-1]['sleeve'] = sleeve
        self.flow[sleeve] += quantity*price*(1-self.fee)
        p['quantity'] -= quantity
        if p['quantity'] < 1e-9:del target[symbol]

    def funding(self, symbol, at, rate, mark):
        old = len(self.events)
        self.fund(symbol, at, rate, mark)
        if len(self.events) == old:return
        payment = self.events[-1]['payment']
        total = self.positions[symbol]['quantity']
        for sleeve, positions in (('core', self.core), ('overlay', self.overlay)):
            part = -payment*positions.get(symbol, {}).get('quantity', 0)/total
            self.flow[sleeve] += part
            self.funding_flow[sleeve] += part

    def sleeve_pnl(self):
        return {sleeve: self.flow[sleeve]+sum(p['quantity']*self.marks[s] for s,p in positions.items())
                for sleeve, positions in (('core', self.core), ('overlay', self.overlay))}

    def verify_sleeves(self):
        for s in self.positions.keys() | self.core.keys() | self.overlay.keys():
            q = self.core.get(s, {}).get('quantity', 0)+self.overlay.get(s, {}).get('quantity', 0)
            if abs(q-self.positions.get(s, {}).get('quantity', 0)) > 1e-7:
                raise ValueError('Sleeves do not sum to net position')
        if abs(self.initial_cash+sum(self.sleeve_pnl().values())-self.state()['equity']) > 1e-5:
            raise ValueError('Sleeve attribution differs from account equity')


def overlay_quantity(book, symbol, price, max_weight, step):
    """Profit permits collateral use; no synthetic wallet credit or loss averaging."""
    core = book.core.get(symbol)
    if not core or price <= core['entry']:return 0.0
    st = book.state()
    if st['equity'] <= 0:return 0.0
    mark = book.marks[symbol]
    existing = sum(p['quantity']*book.marks[s] for s,p in book.overlay.items())
    this_overlay = book.overlay.get(symbol, {}).get('quantity', 0)*mark
    profit = max(0.0, core['quantity']*(mark-core['entry']))
    notional = min(.1*st['equity'], max(0.0, max_weight*st['equity']-existing),
                   max(0.0, 2*profit-this_overlay))
    # Total marked exposure must remain <=1.4 equity including fees/spread.
    drag = price*(1+book.fee)-mark
    denominator = mark+1.4*drag
    if denominator <= 0:return 0.0
    headroom = max(0.0, (1.4*st['equity']-st['gross'])/denominator)
    q = floor(min(notional/price, headroom)/step)*step
    return q if q*price >= 100 else 0.0
