"""Offline v12 input chronology, cash-slot budgeting and cache provenance."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import replay_expanded_core as runner
import stop_provenance
from tests.test_expanded_core import SYMBOLS

DAY = 86_400_000
START = runner.timestamp('2026-01-01')
DATES = ('2026-01-01', '2026-01-02')
ANCHORS = ['BTCUSDT', 'ETHUSDT', 'ZECUSDT']
POOL = [s+'USDT' for s in SYMBOLS]


def frame(start=START-30*DAY, end=START+DAY, volume=20_000_000):
    times = np.arange(start, end, runner.STEP, dtype=np.int64)
    return pd.DataFrame(dict(timestamp=times, open=100., high=101., low=99.,
        close=100., quote_volume=volume/288, mark_open=100., mark_high=101.,
        mark_low=99., mark_close=100.))


def seed_inputs():
    shared = frame()
    frames = dict.fromkeys(POOL, shared)
    filters = {s: dict(lot_size=dict(stepSize='1' if s=='UNIUSDT' else '.01',
                                    minQty='1' if s=='UNIUSDT' else '.01'),
                       min_notional=dict(notional='5')) for s in POOL}
    return filters, frames


class ExpandedCoreRunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for field, value in [('ROOT', self.root), ('OUT', self.root/'reports/quant_v12')]:
            mocked = patch.object(runner, field, value)
            mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(stop_provenance, 'ROOT', self.root)
        mocked.start(); self.addCleanup(mocked.stop)

    def test_liquidity_uses_thirty_complete_utc_days_and_ignores_seed_day_future(self):
        market = frame(volume=1_000_000)
        at = START+4*3_600_000
        old = runner.eligibility(market, at)
        future = market.timestamp >= START
        market.loc[future, 'quote_volume'] = 1e12
        market.loc[future, 'close'] = 1e9
        self.assertEqual(old, runner.eligibility(market, at))
        self.assertFalse(old['eligible'])
        self.assertEqual(old['lookback_end_exclusive'], START)
        self.assertEqual(old['lookback_start'], START-30*DAY)
        with self.assertRaises(ValueError): runner.eligibility(market.iloc[1:], at)

    def test_equal_and_anchor_budgets_are_seventy_percent_without_hidden_reallocation(self):
        filters, markets = seed_inputs()
        for allocation in ['equal', 'anchor', 'three']:
            with self.subTest(allocation=allocation):
                seeds, checks = runner.make_seeds(allocation, POOL, ANCHORS, filters, markets, DATES)
                total = sum(t['amount']*t['open_rate'] for t in seeds)
                self.assertLessEqual(total, 7000+1e-6)
                self.assertEqual(len(seeds), 3 if allocation=='three' else 16)
                if allocation=='anchor':
                    anchor_notional = sum(t['amount']*t['open_rate'] for t in seeds if t['pair'].split('/')[0]+'USDT' in ANCHORS)
                    self.assertLessEqual(anchor_notional, 5000)
                    self.assertLessEqual(total-anchor_notional, 2000)
                if allocation=='equal':
                    uni = next(t for t in seeds if t['pair'].startswith('UNI/'))
                    self.assertEqual(uni['amount'], 4)
                    self.assertAlmostEqual(checks['UNIUSDT']['target_weight'], .7/16)
        markets['UNIUSDT'] = frame(volume=1_000_000)
        dropped, checks = runner.make_seeds('equal', POOL, ANCHORS, filters, markets, DATES)
        self.assertEqual(len(dropped), 15)
        self.assertLess(sum(t['amount']*t['open_rate'] for t in dropped), 6600)
        self.assertEqual(checks['UNIUSDT']['decision'], 'past_volume_below_10m_keep_slot_cash')
        self.assertTrue(all(t['amount']==4.37 for t in dropped))

    def test_current_uni_minimum_and_integer_step_fail_slot_to_cash(self):
        filters, markets = seed_inputs()
        filters['UNIUSDT']['min_notional']['notional'] = '1000'
        seeds, checks = runner.make_seeds('equal', POOL, ANCHORS, filters, markets, DATES)
        self.assertFalse(any(t['pair'].startswith('UNI/') for t in seeds))
        self.assertEqual(checks['UNIUSDT']['decision'], 'below_current_research_filters_keep_slot_cash')
        self.assertLess(sum(t['amount']*t['open_rate'] for t in seeds), 6600)

    def test_epoch_values_reject_negative_indices_wrong_time_and_outside_tail(self):
        dense = runner.EpochValues(START, [10, 20])
        self.assertEqual(dense[START], 10)
        self.assertEqual(dense[START+runner.STEP], 20)
        for at in [START-runner.STEP, START-1, START+1, START+2*runner.STEP]:
            with self.subTest(at=at):
                with self.assertRaises(KeyError): dense[at]
        marks = runner.EpochValues(START, [[10, 11, 9]])
        self.assertEqual(marks[START], (10., 11., 9.))

    def test_four_hour_features_require_all_forty_eight_rows_and_closed_availability(self):
        market = frame(start=START, end=START+202*4*3_600_000)
        breakout_open = START+200*4*3_600_000
        market.loc[market.timestamp >= breakout_open, ['open', 'high', 'low', 'close']] = [120., 121., 119., 120.]
        original = runner.features_from_frame(market.iloc[:-48])
        available = breakout_open+4*3_600_000
        self.assertFalse(original[breakout_open]['enter'])
        self.assertTrue(original[available]['enter'])
        changed = market.copy()
        changed.loc[changed.timestamp >= available, ['open','high','low','close']] = [1., 10000., 1., 1.]
        extended = runner.features_from_frame(changed)
        self.assertEqual(original, {at:f for at,f in extended.items() if at<=available})
        with self.assertRaisesRegex(ValueError, 'Partial 4h'):
            runner.features_from_frame(market.iloc[:-1])

    def test_frame_validation_rejects_gap_duplicate_and_impossible_mark_ohlc(self):
        good = frame(start=START, end=START+DAY)
        runner.validate_frame(good, START, START+DAY, 'UNIUSDT')
        broken = [good.drop(index=10), pd.concat([good.iloc[:10],good.iloc[9:]], ignore_index=True)]
        impossible = good.copy(); impossible.loc[5, 'mark_low'] = 110; broken.append(impossible)
        for bad in broken:
            with self.assertRaises(ValueError): runner.validate_frame(bad, START, START+DAY, 'UNIUSDT')

    def mocked_main(self, manifest):
        return [patch.object(sys, 'argv', ['replay_expanded_core']),
                patch.object(runner, 'protocol', return_value=manifest),
                patch.object(runner, 'cases', return_value=[('full', DATES, .001, 0, 1.)]),
                patch.object(runner, 'ARMS', {'TriHold':runner.ARMS['TriHold']}),
                patch.object(runner, 'load_window', return_value=({}, {})),
                patch.object(runner, 'finish')]

    def setup_cache(self):
        out = runner.OUT
        (out/'runs/full/TriHold').mkdir(parents=True)
        runner.write(out/'universe_freeze.json', dict(symbols=['BTCUSDT'], anchor_symbols=['BTCUSDT'],
            rows=[dict(symbol='BTCUSDT', lot_size=dict(stepSize='.001'))]))
        runner.write(self.root/'reports/quant_v9/binance_leverage_tiers.json', {'BTC/USDT:USDT':[]})
        manifest = dict(study='v12', data={'fixture':'hash'})
        runner.write(out/'protocol.json', manifest)
        target = out/'runs/full/TriHold'
        metrics = dict(return_pct=1., sampled_mark_drawdown_pct=2.)
        for name, value in [('orders',[dict(side='buy')]), ('events', []),
                ('mark_metrics',metrics), ('risk_snapshots', []), ('risk_breaches', []),
                ('monthly_returns', []), ('equity_preview', []), ('seed_eligibility', {})]:
            runner.write(target/(name+'.json'), value)
        pd.DataFrame(dict(timestamp=[START], equity=[10000.])).to_feather(target/'equity_5m.feather')
        summary = dict(study='v12', name=runner.ARMS['TriHold']['name'],
                       strategy='TriHold', window='full', fee=.001, mark_metrics=metrics,
                       margin_mode='cross', total_trades=1,
                       execution=dict(delay_bars=0, overlay_exit_fraction=1.),
                       artifacts={str(p.relative_to(self.root)):runner.sha(p) for p in target.iterdir()})
        runner.write(target/'summary.json', summary)
        return manifest, target, summary

    def test_cache_artifact_hash_tamper_rejected_before_any_replay(self):
        manifest, target, summary = self.setup_cache()
        runner.write(target/'mark_metrics.json', dict(return_pct=999))
        mocks = self.mocked_main(manifest)
        for mocked in mocks: mocked.start(); self.addCleanup(mocked.stop)
        with patch.object(runner, 'run_portfolio') as replay:
            with self.assertRaises(ValueError): runner.main()
            replay.assert_not_called()

    def test_valid_cache_is_accepted_and_summary_metrics_cannot_be_forged(self):
        manifest, target, summary = self.setup_cache()
        self.assertEqual(runner.read_cached_run(target, 'TriHold', 'full', .001, 0, 1.), summary)
        summary['mark_metrics'] = dict(return_pct=999., sampled_mark_drawdown_pct=2.)
        runner.write(target/'summary.json', summary)
        with self.assertRaisesRegex(ValueError, 'differs from verified'):
            runner.read_cached_run(target, 'TriHold', 'full', .001, 0, 1.)

    def test_cache_identity_trade_count_and_artifact_set_cannot_be_forged(self):
        _, target, original = self.setup_cache()
        for key, value in [('strategy','BroadEnhance'), ('fee', .002),
                ('total_trades', 999), ('artifacts', {})]:
            summary = copy.deepcopy(original); summary[key] = value
            runner.write(target/'summary.json', summary)
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    runner.read_cached_run(target, 'TriHold', 'full', .001, 0, 1.)

    def test_changed_frozen_protocol_rejected_before_loading_data(self):
        manifest, _, _ = self.setup_cache()
        changed = copy.deepcopy(manifest); changed['data']['fixture'] = 'changed'
        mocks = self.mocked_main(changed)
        for mocked in mocks: mocked.start(); self.addCleanup(mocked.stop)
        with self.assertRaisesRegex(ValueError, 'Frozen v12 protocol changed'): runner.main()
        runner.load_window.assert_not_called()

    def test_worker_failure_marks_batch_failed(self):
        manifest, _, _ = self.setup_cache()
        mocks = self.mocked_main(manifest)
        for mocked in mocks: mocked.start(); self.addCleanup(mocked.stop)
        future = runner.concurrent.futures.Future()
        future.set_exception(ValueError('invalid public data fixture'))
        with patch.object(runner.concurrent.futures, 'ProcessPoolExecutor') as pool:
            pool.return_value.__enter__.return_value.submit.return_value = future
            with self.assertRaisesRegex(ValueError, 'invalid public data'): runner.main()
        status = json.loads((runner.OUT/'status.json').read_text())
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['completed'], 1)

    def test_allocation_preference_uses_account_return_not_weaker_baseline_excess(self):
        rows = []
        returns = dict(TriHold=50,TriEnhance=100,BroadHold=-20,BroadEnhance=40,
                       AnchorHold=0,AnchorEnhance=30)
        for window in ['full','challenge2025','reused_holdout']:
            for name, value in returns.items():
                rows.append(dict(strategy=name,name=name,window=window,mark_metrics=dict(
                    return_pct=value,sampled_mark_drawdown_pct=20,
                    joint_low_stress_drawdown_pct=21,risk_model_passed=True,
                    unresolved_core_risk=[])))
        runner.finish(rows)
        chosen = json.loads((runner.OUT/'selection.json').read_text())
        self.assertEqual(chosen['selected'], 'TriEnhance')
        self.assertEqual(chosen['details']['BroadEnhance']['worst_full_excess_pp'], 60)
        self.assertEqual(chosen['details']['TriEnhance']['worst_full_return_pct'], 100)

    def test_first_freeze_rejects_data_that_disagrees_with_completed_download_manifest(self):
        sources = ['app/quant/expanded_core.py', 'app/quant/core_overlay.py',
            'app/quant/cross_margin.py', 'scripts/replay_expanded_core.py',
            'scripts/replay_core_overlay.py', 'scripts/replay_cross_margin.py',
            'scripts/stop_provenance.py', 'scripts/prepare_expanded_core_data.py']
        for name in sources:
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# synthetic source fixture\n')
        universe = dict(symbols=['UNIUSDT'])
        runner.write(runner.OUT/'universe_freeze.json', universe)
        runner.write(runner.OUT/'fundamental_sources.json', {})
        runner.write(self.root/'reports/quant_v9/binance_leverage_tiers.json', {})
        series = runner.OUT/'data/series/UNIUSDT.feather'
        series.parent.mkdir(parents=True)
        frame(start=START, end=START+DAY).to_feather(series)
        funding = runner.OUT/'data/funding/UNIUSDT.json'
        runner.write(funding, dict(rates=[]))
        freeze = runner.OUT/'data/freeze_manifest.json'
        runner.write(freeze, dict(symbols=['UNIUSDT'], universe_sha256=runner.sha(runner.OUT/'universe_freeze.json')))
        coverage = dict(status='complete', complete_symbols=1, target_symbols=1,
            failed_symbols=[], freeze_sha256=runner.sha(freeze), symbols={'UNIUSDT':dict(
                status='complete', bars=288, internal_gaps=0,
                series_path=str(series.relative_to(self.root)), series_sha256=runner.sha(series),
                funding_path=str(funding.relative_to(self.root)), funding_sha256=runner.sha(funding))})
        runner.write(runner.OUT/'data/coverage_manifest.json', coverage)
        # Validate the fixture first, so an unrelated missing file cannot hide
        # the provenance failure we are actually exercising.
        runner.protocol(universe)
        runner.write(funding, dict(rates=[dict(fundingTime=START, fundingRate='.99', markPrice='100')]))
        with self.assertRaises(ValueError): runner.protocol(universe)


if __name__ == '__main__':
    unittest.main()
