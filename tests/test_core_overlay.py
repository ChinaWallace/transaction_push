"""Offline net-account/sleeve reconciliation and v11 replay chronology."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import replay_core_overlay as replay
from app.quant.core_overlay import CoreOverlayAccount, overlay_quantity
from tests.test_cross_margin_replay import START, END, FOUR_HOURS, DATES, SYMBOLS, TIERS, synthetic_seed


def fixture():
    trades, data = synthetic_seed()
    for symbol in SYMBOLS:
        data[symbol]['features'] = {}
    data['BTCUSDT']['features'] = {
        START + 8*3_600_000: dict(enter=True, exit50=False, exit200=False, momentum=.2),
        START + 12*3_600_000: dict(enter=False, exit50=True, exit200=True, momentum=-.1),
    }
    return trades, data


class CoreOverlayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for key, value in [('ROOT', self.root), ('OUT', self.root/'reports/quant_v11')]:
            p = patch.object(replay, key, value)
            p.start(); self.addCleanup(p.stop)

    def account(self):
        book = CoreOverlayAccount(10_000, TIERS, fee=.001)
        book.marks = dict.fromkeys(SYMBOLS, 200)
        return book

    def read(self, arm, window, name):
        return json.loads((replay.OUT/'runs'/window/arm/(name+'.json')).read_text())

    def test_partial_overlay_sale_realizes_aggregate_average_and_keeps_attribution(self):
        book = self.account()
        book.purchase('core', 'BTCUSDT', 10, 100, 1, 'core')
        book.purchase('overlay', 'BTCUSDT', 10, 200, 2, 'overlay')
        self.assertAlmostEqual(book.positions['BTCUSDT']['entry'], 150)
        book.verify_sleeves()
        self.assertAlmostEqual(10_000 + sum(book.sleeve_pnl().values()), book.state()['equity'])
        before = book.wallet
        book.sell_sleeve('overlay', 'BTCUSDT', 10, 200, 3, 'exit')
        self.assertAlmostEqual(book.wallet-before, 500-2)
        self.assertAlmostEqual(book.wallet, 10495)
        self.assertAlmostEqual(book.positions['BTCUSDT']['entry'], 150)
        self.assertEqual(book.core['BTCUSDT']['quantity'], 10)
        self.assertNotIn('BTCUSDT', book.overlay)
        book.verify_sleeves()
        self.assertAlmostEqual(book.sleeve_pnl()['overlay'], -4)
        self.assertAlmostEqual(10_000 + sum(book.sleeve_pnl().values()), book.state()['equity'])

    def test_funding_split_follows_current_quantity_and_is_idempotent(self):
        book = self.account()
        book.purchase('core', 'BTCUSDT', 10, 100, 1, 'core')
        book.purchase('overlay', 'BTCUSDT', 5, 200, 2, 'overlay')
        old = book.wallet
        book.funding('BTCUSDT', 10, .01, 200)
        self.assertAlmostEqual(book.wallet, old-30)
        self.assertAlmostEqual(book.funding_flow['core'], -20)
        self.assertAlmostEqual(book.funding_flow['overlay'], -10)
        unchanged = (book.wallet, copy.deepcopy(book.flow), copy.deepcopy(book.events))
        book.funding('BTCUSDT', 10, .01, 200)
        self.assertEqual((book.wallet, book.flow, book.events), unchanged)
        book.sell_sleeve('overlay', 'BTCUSDT', 5, 200, 11, 'exit')
        book.funding('BTCUSDT', 20, -.005, 200)
        self.assertAlmostEqual(book.funding_flow['core'], -10)
        self.assertAlmostEqual(book.funding_flow['overlay'], -10)
        book.verify_sleeves()

    def test_overselling_overlay_is_atomic_and_cannot_consume_core(self):
        book = self.account()
        book.purchase('core', 'BTCUSDT', 10, 100, 1, 'core')
        book.purchase('overlay', 'BTCUSDT', 5, 200, 2, 'overlay')
        old = copy.deepcopy((book.wallet, book.positions, book.core, book.overlay, book.flow, book.events))
        with self.assertRaisesRegex(ValueError, 'other sleeve'):
            book.sell_sleeve('overlay', 'BTCUSDT', 6, 200, 3, 'bad')
        self.assertEqual((book.wallet, book.positions, book.core, book.overlay, book.flow, book.events), old)

    def test_rejected_overlay_purchase_cannot_mutate_wallet_or_attribution(self):
        book = self.account()
        book.purchase('core', 'BTCUSDT', 10, 100, 1, 'core')
        old = copy.deepcopy((book.wallet, book.positions, book.core, book.overlay, book.flow, book.events))
        with self.assertRaisesRegex(ValueError, 'Insufficient'):
            book.purchase('overlay', 'BTCUSDT', 1000, 200, 2, 'unfunded')
        self.assertEqual((book.wallet, book.positions, book.core, book.overlay, book.flow, book.events), old)

    def test_repeated_profit_adds_near_cap_include_execution_spread_and_fees(self):
        book = self.account()
        book.marks = dict.fromkeys(SYMBOLS, 100)
        for s in SYMBOLS:
            book.purchase('core', s, 20, 100, 1, 'core')
        book.marks = dict.fromkeys(SYMBOLS, 200)
        initial_wallet = book.wallet
        additions = 0
        for at in range(2, 12):
            for s in SYMBOLS:
                q = overlay_quantity(book, s, 205, .7, replay.STEPS[s])
                if q:
                    book.purchase('overlay', s, q, 205, at, 'overlay')
                    additions += 1
                    self.assertLessEqual(book.state()['effective_leverage'], 1.4+1e-8)
                    book.verify_sleeves()
        self.assertGreater(additions, 3)
        self.assertGreater(book.state()['effective_leverage'], 1.35)
        add_fees = sum(e['fee'] for e in book.events if e['sleeve']=='overlay')
        self.assertAlmostEqual(book.wallet, initial_wallet-add_fees)

    def test_features_use_completed_distinct_four_hour_confirmations(self):
        bars = [[START+i*FOUR_HOURS, 100, 100, 100, 100] for i in range(200)]
        first_low = [START+200*FOUR_HOURS, 90, 100, 90, 90]
        duplicated = bars + [first_low, first_low.copy()]
        try:
            values = replay.features(duplicated)
        except ValueError:
            pass  # Explicit rejection is also a valid causal data contract.
        else:
            self.assertFalse(values[START+201*FOUR_HOURS]['exit50'],
                             'One duplicated candle must not count as two confirmations')
        distinct = bars + [first_low, [START+201*FOUR_HOURS, 80, 90, 80, 80]]
        values = replay.features(distinct)
        self.assertFalse(values[START+201*FOUR_HOURS]['exit50'])
        self.assertTrue(values[START+202*FOUR_HOURS]['exit50'])
        extended = replay.features(distinct + [[START+202*FOUR_HOURS, 1000, 1000, 1000, 1000]])
        self.assertEqual(values, {k:v for k,v in extended.items() if k<=START+202*FOUR_HOURS})

    def test_core_hold_baseline_matches_seed_profit_and_real_funding(self):
        trades, data = fixture()
        m = replay.run_arm('CoreHold70', 'fixture', trades, data, TIERS, .001, DATES)['mark_metrics']
        self.assertAlmostEqual(m['final_equity'], 11184.4)
        self.assertAlmostEqual(m['funding_net_income_usdt'], -2.4)
        self.assertAlmostEqual(m['freqtrade_baseline_difference_usdt'], 0)
        self.assertAlmostEqual(m['cashflow_error_usdt'], 0)
        self.assertAlmostEqual(m['core_pnl_usdt']+m['overlay_pnl_usdt'], m['final_equity']-10_000)
        self.assertTrue(m['core_preserved_until_terminal'])
        months = self.read('CoreHold70', 'fixture', 'monthly_returns')
        self.assertAlmostEqual(math.prod(1+r['return_pct']/100 for r in months),
                               m['final_equity']/10_000)

    def test_monthly_compounding_includes_terminal_funding_in_ending_month(self):
        trades, data = fixture()
        shift = 30*24*3_600_000
        start, end = START+shift, END+shift+24*3_600_000
        for t in trades:
            t['open_timestamp'] += shift
            t['close_timestamp'] = end
            if t['pair'].startswith('BTC/'):
                t['profit_abs'] -= 2.4
        for s in SYMBOLS:
            data[s]['price'] = {at: (100 if at<start+8*3_600_000 else 120)
                                for at in range(start, end, replay.STEP)}
            data[s]['marks'] = {at: (p,p,p) for at,p in data[s]['price'].items()}
            data[s]['features'] = {}
            data[s]['funding'] = ({start+8*3_600_000:(.001,120), end:(.001,120)}
                                  if s=='BTCUSDT' else {})
        m = replay.run_arm('CoreHold70', 'monthly', trades, data, TIERS, .001,
                           ('2026-01-31','2026-02-02'))['mark_metrics']
        months = self.read('CoreHold70', 'monthly', 'monthly_returns')
        self.assertEqual([r['month'] for r in months], ['2026-01','2026-02'])
        self.assertAlmostEqual(m['funding_net_income_usdt'], -4.8)
        self.assertAlmostEqual(m['freqtrade_baseline_difference_usdt'], 0)
        self.assertAlmostEqual(math.prod(1+r['return_pct']/100 for r in months),
                               m['final_equity']/10_000)
        self.assertAlmostEqual(months[-1]['final_equity'], m['final_equity'])

    def test_future_low_cannot_sell_overlay_before_closed_trend_signal(self):
        trades, data = fixture()
        replay.run_arm('Enhance20', 'clean', trades, data, TIERS, .001, DATES)
        altered = copy.deepcopy(data)
        for s in SYMBOLS:
            at = START+10*3_600_000
            opened, closed, _ = altered[s]['marks'][at]
            altered[s]['marks'][at] = (opened, closed, 0)
        replay.run_arm('Enhance20', 'low', trades, altered, TIERS, .001, DATES)
        clean = self.read('Enhance20', 'clean', 'orders')
        self.assertEqual(clean, self.read('Enhance20', 'low', 'orders'))
        exits = [o for o in clean if o['reason']=='overlay_trend_exit']
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]['timestamp'], START+12*3_600_000)

    def test_delayed_half_fills_keep_core_and_fully_settle_overlay(self):
        trades, data = fixture()
        row = replay.run_arm('Enhance20', 'fixture', trades, data, TIERS, .003, DATES,
                             delay_bars=1, exit_fraction=.5)
        m = row['mark_metrics']
        orders = self.read('Enhance20', 'fixture_execution_stress', 'orders')
        adds = [o for o in orders if o['sleeve']=='overlay' and o['side']=='buy']
        exits = [o for o in orders if o['reason']=='overlay_trend_exit']
        self.assertEqual(len(adds), 1)
        self.assertGreater(len(exits), 1)
        self.assertEqual(adds[0]['timestamp'], START+8*3_600_000+replay.STEP)
        self.assertEqual(exits[0]['timestamp'], START+12*3_600_000+replay.STEP)
        self.assertLess(exits[0]['amount'], adds[0]['amount'])
        self.assertAlmostEqual(sum(o['amount'] for o in exits), adds[0]['amount'])
        core_sells = [o for o in orders if o['sleeve']=='core' and o['side']=='sell']
        self.assertEqual(len(core_sells), 3)
        self.assertEqual({o['reason'] for o in core_sells}, {'sample_end'})
        self.assertEqual({o['timestamp'] for o in core_sells}, {END-replay.STEP})
        self.assertTrue(m['core_preserved_until_terminal'])
        self.assertAlmostEqual(m['cashflow_error_usdt'], 0)


if __name__ == '__main__':
    unittest.main()
