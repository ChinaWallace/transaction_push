"""Forward-only cutoffs, frozen-v12 parity and public-data integrity."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from app.quant.expanded_core import run_portfolio
from app.quant.expanded_forward import run_forward
from scripts import forward_expanded_core as runner
from tests.test_expanded_core import expanded_fixture, RULE
from tests.test_cross_margin_replay import START, END, DATES
from tests.test_expanded_core_runner import frame


class ForwardEngineTests(unittest.TestCase):
    def test_seed_at_observation_start_opens_once_without_waiting_for_four_utc(self):
        trades, data, tiers, steps = expanded_fixture()
        seed = START + 5 * 3_600_000
        for trade in trades:
            trade['open_timestamp'] = seed
            trade['close_timestamp'] = END
        result = run_forward(RULE, trades, data, tiers, steps, .001,
                             [runner.iso(seed), runner.iso(seed + runner.STEP)])
        self.assertEqual(len(result['core']), len(trades))
        self.assertEqual(len(result['events']), len(trades))
        self.assertEqual({e['timestamp'] for e in result['events']}, {seed})
        self.assertEqual({e['side'] for e in result['events']}, {'buy'})

    def test_unchanged_orders_and_equity_before_historical_terminal(self):
        trades, data, tiers, steps = expanded_fixture()
        reference = run_portfolio(RULE, trades, data, tiers, steps, .001, DATES)
        future = copy.deepcopy(trades)
        for trade in future:
            trade['close_timestamp'] = END
        result = run_forward(RULE, future, data, tiers, steps, .001, DATES)
        self.assertEqual(reference['curve'][:-1], result['curve'][:-1])
        self.assertEqual([e for e in reference['events'] if e.get('reason') != 'sample_end'], result['events'])
        self.assertTrue(result['core'])
        self.assertFalse(any(e.get('reason') == 'sample_end' for e in result['events']))
        self.assertAlmostEqual(result['metrics']['final_equity'], result['account']['equity'])
        self.assertAlmostEqual(sum(result['metrics']['pnl_by_pair'].values()), result['account']['equity'] - 10000)
        self.assertAlmostEqual(result['metrics']['cashflow_error_usdt'], 0)

    def test_repeated_growing_windows_preserve_events_and_do_not_sell_cutoff(self):
        trades, data, tiers, steps = expanded_fixture()
        for trade in trades:
            trade['close_timestamp'] = END
        cutoff = START + 10 * 3_600_000
        first = run_forward(RULE, trades, data, tiers, steps, .001,
                            [runner.iso(START), runner.iso(cutoff)])
        second = run_forward(RULE, trades, data, tiers, steps, .001, DATES)
        self.assertEqual(first['events'], [e for e in second['events'] if e['timestamp'] < cutoff])
        self.assertEqual(first['curve'], [r for r in second['curve'] if r['timestamp'] <= cutoff])
        self.assertTrue(first['overlay'])
        self.assertTrue(first['core'])
        self.assertTrue(second['core'])

    def test_terminal_beyond_observation_is_required_and_missing_mark_fails(self):
        trades, data, tiers, steps = expanded_fixture()
        with self.assertRaisesRegex(ValueError, 'close no earlier'):
            run_forward(RULE, trades, data, tiers, steps, .001, DATES)
        for trade in trades:
            trade['close_timestamp'] = END
        del data['BTCUSDT']['marks'][START + runner.STEP]
        with self.assertRaises(KeyError):
            run_forward(RULE, trades, data, tiers, steps, .001, DATES)

    def test_final_low_risk_is_not_erased_by_observation_cutoff(self):
        trades, data, tiers, steps = expanded_fixture()
        for trade in trades:
            trade['close_timestamp'] = END
        for market in data.values():
            op, close, _low = market['marks'][END - runner.STEP]
            market['marks'][END - runner.STEP] = (op, close, .01)
        result = run_forward(RULE, trades, data, tiers, steps, .001, DATES)
        self.assertGreater(result['metrics']['joint_low_stress_drawdown_pct'], 50)
        self.assertTrue(result['core'])


class ForwardInputTests(unittest.TestCase):
    def test_cycle_waits_for_seed_then_persists_matched_nonduplicated_accounts(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            seed = START + 4 * 3_600_000
            warmup = START - 92 * runner.DAY
            filters = {s: dict(lot=dict(stepSize='.001', minQty='.001', maxQty='1000000'),
                               minimum=dict(notional='5'), funding_hours=8) for s in runner.SYMBOLS}
            protocol = dict(start_ms=START, seed_ms=seed, stop_ms=END, warmup_ms=warmup,
                            capital=10000., fee=.001, filters=filters, tiers_path='tiers.json')
            runner.save(out / 'protocol.json', protocol)
            (out / 'protocol.sha256').write_text(runner.sha(out / 'protocol.json'))
            _trades, _data, tiers, _steps = expanded_fixture()
            runner.save(out / 'tiers.json', {s.removesuffix('USDT') + '/USDT:USDT': tiers[s] for s in runner.SYMBOLS})
            clock = [seed - 3_600_000 + 20_000]
            class API:
                def fetch(self, *_args):
                    return dict(serverTime=clock[0])
            def refresh(_out, _protocol, _symbol, end, _api):
                return frame(start=warmup, end=end)
            with patch.object(runner, 'ROOT', out), patch.object(runner, 'verify_protocol'), \
                    patch.object(runner, 'refresh_frame', side_effect=refresh), \
                    patch.object(runner, 'funding_events', return_value={}), \
                    patch.object(runner.time, 'time', side_effect=lambda: clock[0] / 1000):
                before = runner.cycle(out, protocol, API())
                self.assertEqual(before['state'], 'waiting_for_seed')
                self.assertFalse(before['arms'])
                clock[0] = seed + runner.STEP + 20_000
                seeded = runner.cycle(out, protocol, API())
                self.assertEqual(seeded['state'], 'observing')
                self.assertEqual(seeded['arms']['TriHold']['core'], seeded['arms']['TriEnhance']['core'])
                self.assertEqual(len(seeded['arms']['TriHold']['events']), 3)
                for event in seeded['arms']['TriHold']['events']:
                    self.assertEqual(event['timestamp'], seed)
                    self.assertGreater(event['first_observed_ms'], seed + runner.STEP)
                clock[0] += runner.STEP
                later = runner.cycle(out, protocol, API())
                self.assertEqual(later['arms']['TriHold']['events'], seeded['arms']['TriHold']['events'])
                self.assertEqual(later['arms']['TriHold']['account']['equity'], seeded['arms']['TriHold']['account']['equity'])

    def test_immediate_seed_is_next_future_five_minute_boundary(self):
        now = runner.ms('2026-09-28T06:30:00+08:00')
        self.assertEqual(runner.next_seed(now), runner.ms('2026-09-28T06:35:00+08:00'))
        self.assertEqual(runner.next_seed(now + runner.STEP - 1), runner.ms('2026-09-28T06:35:00+08:00'))
        self.assertEqual(runner.next_seed(runner.next_seed(now)), runner.ms('2026-09-28T06:40:00+08:00'))
        midnight = runner.ms('2026-09-28T23:59:59+08:00')
        self.assertEqual(runner.next_seed(midnight), runner.ms('2026-09-29T00:00:00+08:00'))
        with self.assertRaisesRegex(ValueError, 'timezone'):
            runner.ms('2026-09-28T06:30:00')

    def test_first_observed_time_survives_restart_and_revisions_are_rejected(self):
        events = [dict(timestamp=100, side='buy', price=10.)]
        first = runner.preserve_events([], events, 500)
        second = runner.preserve_events(first, events + [dict(timestamp=600, side='sell', price=11.)], 900)
        self.assertEqual(second[0]['first_observed_ms'], 500)
        self.assertEqual(second[1]['first_observed_ms'], 900)
        self.assertEqual(second[0]['observation_lag_ms'], 400)
        with self.assertRaisesRegex(ValueError, 'changed'):
            runner.preserve_events(first, [dict(timestamp=100, side='buy', price=12.)], 900)
        with self.assertRaisesRegex(ValueError, 'shortened'):
            runner.preserve_events(first, [], 900)

    def test_missing_funding_is_not_assumed_zero(self):
        class API:
            def fetch(self, *_args):
                return []
        protocol = dict(start_ms=START, filters={'BTCUSDT': dict(funding_hours=8)})
        with self.assertRaisesRegex(ValueError, 'missing funding'):
            runner.funding_events(API(), 'BTCUSDT', protocol, START + runner.STEP)

    def test_private_endpoint_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'Non-public'):
                runner.PublicData(Path(temporary)).fetch('/fapi/v1/order')

    def test_public_candle_gap_is_rejected(self):
        class API:
            def fetch(self, *_args):
                return [[START + runner.STEP, '1', '1', '1', '1', '1', START + 2 * runner.STEP - 1, '1', 1, '1', '1', '0']]
        with self.assertRaisesRegex(ValueError, 'non-consecutive'):
            runner.fetch_bars(API(), 'BTCUSDT', '/fapi/v1/klines', START, START + runner.STEP)


if __name__ == '__main__':
    unittest.main()
