"""Closed-bar 4h selection, 1h confirmation, 15m trigger; shared by replay and paper."""
from math import isfinite, log, sqrt
from statistics import mean, median, pstdev
from app.advisory.engine import Candle, DAY, ema
from .universe import rank_contracts

PERIODS = {'4h': 14_400_000, '1h': 3_600_000, '15m': 900_000}
VERSION = 'contracts-v4.0-mtf'


def features(rows, timeframe, as_of):
    period = PERIODS[timeframe]
    bars = [Candle.from_binance(r) for r in rows if int(r[6]) < as_of][-201:]
    if len(bars) < 61:
        raise ValueError(f'insufficient_closed_{timeframe}_bars')
    if bars[-1].close_time != as_of // period * period - 1:
        raise ValueError(f'stale_{timeframe}_bars')
    for i, b in enumerate(bars):
        if (not all(isfinite(x) for x in (b.open, b.high, b.low, b.close, b.volume, b.quote_volume))
                or not 0 < b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                or b.volume < 0 or b.quote_volume < 0 or b.open_time % period
                or b.close_time != b.open_time + period - 1
                or i and b.open_time - bars[i-1].open_time != period):
            raise ValueError(f'invalid_or_gapped_{timeframe}_bars')
    close = [b.close for b in bars]
    e20, e50 = ema(close, 20), ema(close, 50)
    atr = mean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a,b in zip(bars[-15:-1], bars[-14:]))
    if atr <= 0: raise ValueError('zero_volatility')
    returns = [log(b/a) for a,b in zip(close[-61:-1], close[-60:])]
    annual = max(.1, pstdev(returns)*sqrt(365*DAY/period))
    # 4h windows: 1 / 3 / 10 days. No daily-bar assumptions.
    windows = (6, 18, 60)
    momentum = mean(log(close[-1]/close[-n-1])*sqrt(18/n) for n in windows)
    recent = bars[-1]
    return {'closed_at': recent.close_time, 'bars': len(bars), 'close': close[-1], 'atr': atr,
            'ema20': e20[-1], 'ema50': e50[-1], 'ema20_rising': e20[-1] > e20[-4],
            'trend': sum((close[-1]>e20[-1], close[-1]>e50[-1], e20[-1]>e20[-4], close[-1]>close[-19]))/4,
            'annual_vol': annual, 'annualization_periods': 365*DAY/period,
            'momentum_score': momentum/sqrt(annual), 'returns30': returns,
            'return20': close[-1]/close[-19]-1, 'momentum_windows': [f'{n} bars/{timeframe}' for n in windows],
            'median_volume20': median(b.quote_volume for b in bars[-20:])*DAY/period,
            'prior_high20': max(b.high for b in bars[-21:-1]),
            'prior_low10': min(b.low for b in bars[-11:-1]), 'low10': min(b.low for b in bars[-10:]),
            'last_low': recent.low, 'last_high': recent.high, 'previous_close': close[-2],
            'previous_ema20': e20[-2], 'volume_ratio': recent.quote_volume/max(1,median(b.quote_volume for b in bars[-21:-1])),
            'timeframe': timeframe}


def rank_multiframe(universe, histories, markets, as_of, max_leverage=3, funding_intervals=None):
    computed = {}; errors = {}; four = {}
    for row in universe:
        symbol = row['symbol']; source = histories.get(symbol, {})
        try:
            frames = {tf: features(source.get(tf, []), tf, as_of) for tf in PERIODS}
            computed[symbol] = frames; four[symbol] = frames['4h']
        except ValueError as exc: errors[symbol] = str(exc)
    ranked = rank_contracts(universe, {s: [] for s in four}, markets, as_of, max_leverage,
                            funding_intervals, features_override=four)
    for row in ranked:
        s = row['symbol']
        if s not in computed:
            if not row['rejections']: row['rejections'].append(errors.get(s, 'missing_multiframe_bars'))
            continue
        f4, f1, f15 = (computed[s][tf] for tf in PERIODS)
        row['timeframes'] = computed[s]
        # These outputs use 4h ranking weights, then explicit faster confirmation.
        row['history_class'] = 'seasoned' if row['age_days'] >= 120 else 'young'
        if row['age_days'] < 90: row['leverage'] = 1
        confirmed = f1['close'] > f1['ema20'] > f1['ema50'] and f1['ema20_rising']
        breakout = f15['close'] > f15['prior_high20'] and f15['volume_ratio'] >= 1.2
        pullback = (f15['last_low'] <= f15['ema20'] and f15['close'] > f15['ema20']
                    and f15['close'] > f15['previous_close'] and f15['volume_ratio'] >= .8)
        trigger = 'breakout_15m' if breakout else 'pullback_reclaim_15m' if pullback else None
        stop = max(f15['close']-2.5*f1['atr'], f15['close']*.90)
        row['entry_zone'] = [max(stop*1.001, f15['close']-.3*f15['atr']), f15['close']+.5*f15['atr']]
        row['stop_price'] = stop
        row['features'] = {**f4, 'atr': f1['atr'], 'close': f15['close']}
        # Use aligned 4h returns and the correct volatility scale in portfolio sizing.
        row['signal'] = {'selection_closed_at': f4['closed_at'], 'confirmation_closed_at': f1['closed_at'],
                         'execution_closed_at': f15['closed_at'], 'confirmed_1h': confirmed,
                         'trigger_15m': trigger, 'volume_ratio_15m': f15['volume_ratio'],
                         'exit_1h': f1['close'] < f1['ema50'],
                         'exit_15m': f15['close'] < f15['prior_low10']}
        row['exit_rule'] = '1h EMA50 loss / 15m prior 10-bar low loss / 3x 1h ATR trail / 72h time exit'
        row['hold_eligible'] = (not row['rejections'] and f4['trend']>=.5 and f4['close']>f4['ema50']
                                and row['selection_score']>=50 and not row['signal']['exit_1h'] and not row['signal']['exit_15m'])
        if row['rejections'] or row['action']=='underlying_leverage_requires_review': continue
        if row['ask'] <= stop:
            row['action']='current_price_below_stop'; row['hold_eligible']=False
        elif f4['trend']<.75 or f4['return20']<=0: row['action']='wait_trend'
        elif row['selection_score']<65: row['action']='below_rank_threshold'
        elif not confirmed: row['action']='wait_1h_confirmation'
        elif not trigger: row['action']='wait_15m_trigger'
        elif not row['entry_zone'][0] <= row['ask'] <= row['entry_zone'][1]: row['action']='wait_pullback'
        else: row['action']='candidate'
    return ranked
