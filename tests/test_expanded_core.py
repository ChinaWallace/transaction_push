"""Offline multi-asset replay accounting, chronology and frozen-v11 parity."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.quant.expanded_core import STEP, run_portfolio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import replay_core_overlay as v11
from tests.test_core_overlay import fixture as three_coin_fixture
from tests.test_cross_margin_replay import START, END, DATES, TIERS

SYMBOLS = ('BTC', 'ETH', 'ZEC', 'UNI', 'SOL', 'BNB', 'XRP', 'DOGE',
           'ADA', 'AVAX', 'LINK', 'LTC', 'AAVE', 'NEAR', 'BCH', 'DOT')
HOUR = 3_600_000
RULE = dict(weight=.2, exit_ema=50)


def expanded_fixture():
    trades, data, tiers, steps = [], {}, {}, {}
    for i, base in enumerate(SYMBOLS):
        symbol = base+'USDT'
        trades.append(dict(pair=base+'/USDT:USDT', amount=4,
                           open_timestamp=START+4*HOUR,
                           close_timestamp=END-STEP,
                           open_rate=100, close_rate=200))
        prices = {at: (100 if at < START+8*HOUR else 200)
                  for at in range(START, END, STEP)}
        data[symbol] = dict(price=prices,
            marks={at: (p, p, p) for at, p in prices.items()},
            funding={START+9*HOUR: (.001 if i % 2 == 0 else -.0005, 200)},
            features={START+8*HOUR: dict(enter=True, exit50=False,
                exit200=False, momentum=100 if base=='UNI' else 16-i),
                START+12*HOUR: dict(enter=False, exit50=True,
                                   exit200=True, momentum=-.1)})
        tiers[symbol] = [dict(minNotional=0, maxNotional=1_000_000,
                             maintenanceMarginRate=.01, info={'cum': 0})]
        steps[symbol] = 1 if base=='UNI' else .01
    return trades, data, tiers, steps


class ExpandedCoreTests(unittest.TestCase):
    def run_expanded(self, *, rule=None, fee=.001, delay=0, fraction=1,
                     data=None, trades=None):
        original, market, tiers, steps = expanded_fixture()
        return run_portfolio(rule or RULE, original if trades is None else trades,
            market if data is None else data, tiers, steps, fee, DATES,
            delay_bars=delay, exit_fraction=fraction)

    def test_sixteen_seeds_and_integer_uni_overlay_use_one_account(self):
        result = self.run_expanded()
        m = result['metrics']
        self.assertEqual(len(m['initial_core_symbols']), 16)
        self.assertEqual(m['initial_core_notional_usdt'], 6400)
        adds = [o for o in result['orders'] if o['side']=='buy' and o['sleeve']=='overlay']
        uni = [o for o in adds if o['symbol']=='UNIUSDT']
        self.assertTrue(uni)
        self.assertTrue(all(float(o['amount']).is_integer() for o in uni))
        # Independent 10k wallets would each allow an 800 notional addition.
        # The shared 20% account budget must instead constrain the whole batch.
        self.assertLess(sum(o['amount']*o['price'] for o in adds), 16*800)
        at = START+8*HOUR
        marked = next(r for r in result['curve'] if r['timestamp']==at+STEP)
        self.assertLessEqual(sum(o['amount']*200 for o in adds), .2*marked['equity']+1e-8)
        self.assertLessEqual(marked['effective_leverage'], 1.4+1e-8)

    def test_expanded_cashflows_fees_funding_and_sleeves_reconcile(self):
        result = self.run_expanded(fee=.002)
        m = result['metrics']
        cash = 0.0
        for e in result['events']:
            if e['side']=='funding':
                cash -= e['payment']
            else:
                cash += (1 if e['side']=='sell' else -1)*e['amount']*e['price']-e['fee']
        self.assertAlmostEqual(m['final_equity'], 10000+cash)
        self.assertAlmostEqual(m['core_pnl_usdt']+m['overlay_pnl_usdt'], cash)
        self.assertAlmostEqual(sum(m['pnl_by_pair'].values()), cash)
        self.assertAlmostEqual(sum(m['sleeve_funding_net'].values()), m['funding_net_income_usdt'])
        self.assertNotEqual(m['sleeve_funding_net']['overlay'], 0)
        self.assertAlmostEqual(m['fee_cost_usdt'], sum(o['fee'] for o in result['orders']))
        for row in result['curve']:
            self.assertAlmostEqual(10000+row['core_pnl']+row['overlay_pnl'], row['equity'])
        self.assertAlmostEqual(math.prod(1+r['return_pct']/100 for r in result['monthly_returns']), m['final_equity']/10000)

    def test_hold_baseline_has_exact_expanded_seed_profit_after_real_funding(self):
        result = self.run_expanded(rule=dict(weight=0, exit_ema=50))
        expected = 16*4*(200-100)-16*4*(100+200)*.001
        expected -= 8*4*200*.001 + 8*4*200*(-.0005)
        self.assertAlmostEqual(result['metrics']['final_equity'], 10000+expected)
        self.assertEqual(result['metrics']['add_fills'], 0)

    def test_future_prices_and_lows_cannot_change_past_orders(self):
        rule = dict(weight=.7, exit_ema=50)
        clean = self.run_expanded(rule=rule)
        _, changed, _, _ = expanded_fixture()
        cutoff = START+10*HOUR
        for market in changed.values():
            for at in market['price']:
                if at >= cutoff:
                    market['price'][at] = 250
                    market['marks'][at] = (250, 270, 0)
        revised = self.run_expanded(rule=rule, data=changed)
        self.assertEqual([o for o in clean['orders'] if o['timestamp']<cutoff],
                         [o for o in revised['orders'] if o['timestamp']<cutoff])
        self.assertFalse(revised['metrics']['risk_model_passed'])

    def test_delayed_half_exits_only_consume_overlay_until_terminal(self):
        result = self.run_expanded(delay=1, fraction=.5, fee=.003)
        adds = [o for o in result['orders'] if o['side']=='buy' and o['sleeve']=='overlay']
        exits = [o for o in result['orders'] if o['reason']=='overlay_trend_exit']
        self.assertTrue(adds)
        self.assertGreater(len(exits), len(adds))
        self.assertEqual(min(o['timestamp'] for o in adds), START+8*HOUR+STEP)
        self.assertEqual(min(o['timestamp'] for o in exits), START+12*HOUR+STEP)
        for symbol in {o['symbol'] for o in adds}:
            self.assertAlmostEqual(sum(o['amount'] for o in adds if o['symbol']==symbol),
                                   sum(o['amount'] for o in exits if o['symbol']==symbol))
        core = [o for o in result['orders'] if o['sleeve']=='core' and o['side']=='sell']
        self.assertEqual(len(core), 16)
        self.assertEqual({o['reason'] for o in core}, {'sample_end'})
        self.assertEqual({o['timestamp'] for o in core}, {END})
        self.assertTrue(all(o['amount']==4 for o in core))

    def test_shared_account_risk_reduces_overlay_and_preserves_all_core(self):
        _, data, _, _ = expanded_fixture()
        for market in data.values():
            for at in market['price']:
                if at >= START+10*HOUR:
                    market['price'][at] = 100
                    market['marks'][at] = (100, 100, 100)
        result = self.run_expanded(rule=dict(weight=.7, exit_ema=50), data=data)
        reductions = [o for o in result['orders'] if o['reason']=='overlay_account_risk']
        self.assertTrue(reductions)
        self.assertEqual({o['sleeve'] for o in reductions}, {'overlay'})
        self.assertTrue(result['metrics']['core_preserved_until_terminal'])
        before = next(r for r in result['risk_snapshots'] if r['reason']=='before_reduce')
        after = next(r for r in result['risk_snapshots'] if r['reason']=='after_reduce')
        self.assertEqual(before['core_quantities'], after['core_quantities'])
        self.assertFalse(after['overlay_quantities'])

    def test_seed_duplicates_unsynchronized_and_outside_window_rejected(self):
        original, _, _, _ = expanded_fixture()
        cases = []
        duplicated = copy.deepcopy(original); duplicated[1] = copy.deepcopy(duplicated[0]); cases.append(duplicated)
        unsynchronized = copy.deepcopy(original); unsynchronized[0]['open_timestamp'] += STEP; cases.append(unsynchronized)
        outside = copy.deepcopy(original)
        for t in outside: t['open_timestamp'] = START-STEP
        cases.append(outside)
        reversed_times = copy.deepcopy(original); reversed_times[0]['close_timestamp'] = START; cases.append(reversed_times)
        for seeds in cases:
            with self.subTest(seeds=seeds[0]['open_timestamp']):
                with self.assertRaises(ValueError): self.run_expanded(trades=seeds)

    def test_non_grid_seed_timestamps_rejected_rather_than_silently_skipped(self):
        seeds, _, _, _ = expanded_fixture()
        for t in seeds:
            t['open_timestamp'] += 1
            t['close_timestamp'] += 1
        with self.assertRaises(ValueError): self.run_expanded(trades=seeds)

    def test_last_candle_low_is_evaluated_before_terminal_settlement(self):
        trades, data, tiers, steps = expanded_fixture()
        trade = dict(trades[0], amount=70, close_rate=200)
        symbol = 'BTCUSDT'
        market = data[symbol]
        market['price'] = dict.fromkeys(market['price'], 100)
        market['marks'] = dict.fromkeys(market['marks'], (100, 100, 100))
        market['marks'][END-STEP] = (100, 200, 1)
        market['funding'] = {}
        result = run_portfolio(dict(weight=0, exit_ema=200), [trade],
            {symbol:market}, tiers, steps, 0, DATES)
        self.assertAlmostEqual(result['metrics']['joint_low_stress_drawdown_pct'], 69.3)
        self.assertAlmostEqual(result['metrics']['max_marked_exposure_pct'], 14000/17000*100)
        self.assertAlmostEqual(result['metrics']['max_single_marked_weight_pct'], 14000/17000*100)
        self.assertEqual(result['orders'][-1]['timestamp'], END)
        self.assertEqual(result['curve'][-1]['timestamp'], END)
        self.assertEqual(len({r['timestamp'] for r in result['curve']}), len(result['curve']))

    def test_three_coin_cashflows_preserved_with_corrected_close_timestamps(self):
        trades, data = three_coin_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(v11, 'ROOT', root), patch.object(v11, 'OUT', root/'reports/quant_v11'):
                for arm, fee, delay, fraction in [('CoreHold70', .001, 0, 1),
                        ('Enhance20', .001, 0, 1), ('Enhance40Slow', .003, 1, .5)]:
                    with self.subTest(arm=arm):
                        old = v11.run_arm(arm, 'fixture', trades, data, TIERS, fee, DATES,
                                          delay_bars=delay, exit_fraction=fraction)
                        new = run_portfolio(v11.ARMS[arm], trades, data, TIERS,
                                            v11.STEPS, fee, DATES,
                                            delay_bars=delay, exit_fraction=fraction)
                        path = v11.OUT/'runs'/old['window']/arm
                        for key in ['orders', 'events', 'risk_snapshots', 'risk_breaches', 'monthly_returns']:
                            prior = json.loads((path/(key+'.json')).read_text())
                            for event in prior:
                                if event.get('reason')=='sample_end': event['timestamp'] += STEP
                            self.assertEqual(new[key], prior)
                        # v11 timing/risk observations are intentionally not an oracle.
                        for key in ['return_pct','final_equity','fee_cost_usdt',
                                'funding_net_income_usdt','core_pnl_usdt','overlay_pnl_usdt',
                                'pnl_by_pair','add_fills','cashflow_error_usdt']:
                            self.assertEqual(new['metrics'][key], old['mark_metrics'][key], key)


if __name__ == '__main__':
    unittest.main()
