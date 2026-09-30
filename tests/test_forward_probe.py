"""Offline evidence checks for the cross-session forward runtime probe."""
from __future__ import annotations

import gzip
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import check_forward_runtime as probe


STEP = probe.STEP
SEED = 2 * STEP
FIRST_END = SEED + STEP


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)
        self.names = ('TriHold', 'TriEnhance', 'TriEnhance20')
        self.original = dict(timestamp=SEED, first_observed_ms=FIRST_END + 10_000,
                             symbol='BTCUSDT', side='buy', amount=1., price=100., fee=.1)
        before_arms = {name: dict(events=1, events_sha256=probe.value_sha([self.original]))
                       for name in self.names}
        self.before = dict(checked_ms=FIRST_END + 20_000, pid=111,
                           protocol_sha256='protocol', bundle_sha256='bundle',
                           data_end_ms=FIRST_END, observed_ms=FIRST_END + 10_000,
                           arms=before_arms)
        self.after = dict(checked_ms=FIRST_END + 3 * STEP + 20_000, pid=111,
                          protocol_sha256='protocol', bundle_sha256='bundle',
                          data_end_ms=FIRST_END + 2 * STEP,
                          observed_ms=FIRST_END + 2 * STEP + 10_000,
                          arms=before_arms)
        self.latest = dict(arms={name: dict(events=[dict(self.original)]) for name in self.names})
        with patch.object(probe, 'inspect', return_value=(self.before, {})):
            created = probe.checkpoint(self.out)
        self.checkpoint_path = Path(created['checkpoint'])
        for end in (FIRST_END + STEP, FIRST_END + 2 * STEP):
            self.write_snapshot(end)

    def write_snapshot(self, end, *, late=False, new_bars=1, observed_ms=None):
        snapshot = dict(data_end_ms=end, protocol_sha256='protocol',
                        observed_ms=end + 10_000 if observed_ms is None else observed_ms,
                        late_collection=late,
                        new_completed_5m=new_bars)
        path = self.out / 'snapshots' / (str(end) + '.json.gz')
        probe.write(path, gzip.compress(probe.json.dumps(snapshot).encode(), mtime=0))

    def check(self):
        with patch.object(probe, 'inspect', return_value=(self.after, self.latest)):
            return probe.check(self.out, self.checkpoint_path)

    def test_two_separately_completed_candles_pass(self):
        result = self.check()
        self.assertEqual(result['state'], 'measured_window_passed')
        self.assertEqual(result['new_completed_5m'], 2)
        self.assertFalse(result['process_restarted'])

    def test_missing_storage_nonce_fails(self):
        record = probe.read(self.checkpoint_path)['record']
        (self.out / record['nonce_path']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_rewriting_old_first_observed_time_fails(self):
        for arm in self.latest['arms'].values():
            arm['events'][0]['first_observed_ms'] += STEP
        with self.assertRaisesRegex(ValueError, 'prior events or first-observed times changed'):
            self.check()

    def test_missing_middle_snapshot_fails(self):
        (self.out / 'snapshots' / (str(FIRST_END + STEP) + '.json.gz')).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing intermediate observation snapshot'):
            self.check()

    def test_late_or_catchup_snapshot_fails(self):
        for options in (dict(late=True), dict(new_bars=2)):
            with self.subTest(options=options):
                self.write_snapshot(FIRST_END + STEP, **options)
                with self.assertRaisesRegex(ValueError, 'Late/catch-up observation'):
                    self.check()

    def test_four_minute_late_snapshot_fails_even_when_flag_says_on_time(self):
        self.write_snapshot(FIRST_END + STEP, observed_ms=FIRST_END + STEP + 240_000)
        with self.assertRaisesRegex(ValueError, '120-second latency limit'):
            self.check()

    def test_nonmonotonic_or_future_observation_fails(self):
        first = FIRST_END + STEP
        for observed in (self.before['observed_ms'] - 1, self.after['checked_ms'] + 1):
            with self.subTest(observed_ms=observed):
                self.write_snapshot(first, observed_ms=observed)
                with self.assertRaisesRegex(ValueError, 'nonmonotonic or exceeds'):
                    self.check()

    def test_worker_restart_passes_when_event_prefix_and_candles_remain_continuous(self):
        self.after['pid'] = 222
        result = self.check()
        self.assertTrue(result['process_restarted'])
        self.assertEqual(result['new_completed_5m'], 2)


class LiveInspectionTests(unittest.TestCase):
    def test_inspect_reconciles_sealed_candles_and_rejects_stale_heartbeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            code = out / 'code'
            source = code / 'scripts' / 'dummy.py'
            tier = code / 'reports' / 'quant_v9' / 'binance_leverage_tiers.json'
            historical = code / 'reports' / 'quant_v12' / 'protocol.json'
            probe.write(source, b'# frozen source\n')
            probe.write(tier, b'{}\n')
            probe.write(historical, b'{}\n')
            probe.write(code / 'bundle.json', b'{}\n')
            symbols = ('BTCUSDT', 'ETHUSDT', 'ZECUSDT')
            protocol = dict(symbols=symbols, arms={name: {} for name in
                            ('TriHold', 'TriEnhance', 'TriEnhance20')},
                            seed_ms=SEED, stop_ms=FIRST_END + 10 * STEP,
                            warmup_ms=SEED, capital=10_000.,
                            sources={'scripts/dummy.py': probe.digest(source)},
                            tiers_path='reports/quant_v9/binance_leverage_tiers.json',
                            tiers_sha256=probe.digest(tier),
                            historical_protocol_sha256=probe.digest(historical),
                            bootstrap_mode='historical')
            probe.save(out / 'protocol.json', protocol)
            protocol_sha = probe.digest(out / 'protocol.json')
            probe.write(out / 'protocol.sha256', (protocol_sha + '\n').encode())
            for symbol in symbols:
                frame = pd.DataFrame([dict(timestamp=SEED, open=100., high=101.,
                    low=99., close=100., quote_volume=1000., mark_open=100.,
                    mark_high=101., mark_low=99., mark_close=100.)])
                path = out / 'series' / (symbol + '.feather')
                path.parent.mkdir(parents=True, exist_ok=True)
                frame.to_feather(path)
                probe.write(path.with_suffix('.sha256'), (probe.digest(path) + '\n').encode())
            events = [dict(timestamp=SEED, first_observed_ms=FIRST_END + 10_000,
                           symbol=symbol, side='buy', sleeve='core', amount=1.,
                           price=100., fee=.1) for symbol in symbols]
            positions = {symbol: dict(quantity=1.) for symbol in symbols}
            core = {symbol: dict(quantity=1.) for symbol in symbols}
            arms = {name: dict(core=core, events=events, positions=positions,
                               account=dict(equity=9999.7),
                               metrics=dict(final_equity=9999.7))
                    for name in protocol['arms']}
            probe.save(out / 'latest.json', dict(data_end_ms=FIRST_END,
                observed_ms=FIRST_END + 10_000, protocol_sha256=protocol_sha,
                late_collection=False, arms=arms))
            runtime = dict(pid=123, state='observing', consecutive_failures=0,
                           updated_ms=FIRST_END + 20_000)
            probe.save(out / 'runtime.json', runtime)
            with patch.object(probe, 'verify_bundle', return_value={}), \
                 patch.object(probe, 'owned_pid', return_value=123):
                result, _ = probe.inspect(out, now=FIRST_END + 30_000)
                self.assertEqual(set(result['arms']), set(protocol['arms']))
                self.assertLess(result['arms']['TriHold']['reconciliation_error'], 1e-8)
                runtime['updated_ms'] = FIRST_END - 200_000
                probe.save(out / 'runtime.json', runtime)
                with self.assertRaisesRegex(ValueError, 'heartbeat is stale'):
                    probe.inspect(out, now=FIRST_END + 30_000)


if __name__ == '__main__':
    unittest.main()
