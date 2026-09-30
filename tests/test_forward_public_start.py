"""Future seed commitment and cancellation during cold public initialization."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_expanded_forward import runner


class PublicInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        self.clock = [runner.ms('2026-09-30T12:04:59+08:00')]
        runner.save(self.out / 'bundle.json', {'bootstrap_mode': 'public'})
        runner.save(self.out / 'reports/quant_v9/binance_leverage_tiers.json', {})
        runner.save(self.out / 'bootstrap/ready/manifest.json', {})
        self.warmup = {'files': {}, 'start_ms': self.clock[0] // runner.DAY * runner.DAY - 92 * runner.DAY}
        def fetch(endpoint):
            if endpoint == '/fapi/v1/time':
                return {'serverTime': self.clock[0]}
            if endpoint == '/fapi/v1/fundingInfo':
                return []
            return {'symbols': [dict(symbol=s, status='TRADING', contractType='PERPETUAL', quoteAsset='USDT',
                filters=[dict(filterType='LOT_SIZE', stepSize='.001'), dict(filterType='MIN_NOTIONAL', notional='5')])
                for s in runner.SYMBOLS]}
        self.api = Mock(fetch=Mock(side_effect=fetch))
        for context in (patch.object(runner, 'ROOT', self.out), patch.object(runner, 'SOURCES', ()),
                        patch.object(runner, 'verify_protocol'), patch.object(runner, 'refresh_frame'),
                        patch.object(runner.time, 'time', side_effect=lambda: self.clock[0] / 1000)):
            context.start()
            self.addCleanup(context.stop)

    def test_download_finishes_before_seed_chosen_and_restart_retains_it(self):
        before = self.clock[0]
        def download(*_args):
            self.clock[0] += 8 * 60_000
            return self.warmup
        with patch.object(runner, 'prepare_public', side_effect=download):
            protocol = runner.initialize(self.out, '2026-10-31T00:00:00+08:00', self.api)
        self.assertGreater(protocol['seed_ms'], before + 8 * 60_000 + 30_000)
        self.assertEqual(protocol['bootstrap_mode'], 'public')
        self.assertIsNone(protocol['historical_protocol_sha256'])
        self.assertFalse((self.out / 'latest.json').exists())
        frozen_sha = runner.sha(self.out / 'protocol.json')
        self.clock[0] += runner.DAY
        with patch.object(runner, 'prepare_public') as download:
            restarted = runner.initialize(self.out, None, self.api)
        download.assert_not_called()
        self.assertEqual(restarted['seed_ms'], protocol['seed_ms'])
        self.assertEqual(frozen_sha, runner.sha(self.out / 'protocol.json'))

    def test_near_boundary_reserves_time_to_seal_and_start(self):
        with patch.object(runner, 'prepare_public', return_value=self.warmup):
            protocol = runner.initialize(self.out, '2026-10-31T00:00:00+08:00', self.api)
        self.assertEqual(protocol['seed_ms'], runner.ms('2026-09-30T12:10:00+08:00'))
        self.assertLess(runner.read(self.out / 'initialization.json')['persisted_ms'], protocol['seed_ms'])

    def test_slow_seal_misses_boundary_and_cannot_silently_restart_or_reseed(self):
        original_write = runner.write
        def slow_write(path, data):
            original_write(path, data)
            if path.name == 'protocol.sha256':
                self.clock[0] = runner.read(self.out / 'protocol.json')['seed_ms'] + 1
        with patch.object(runner, 'prepare_public', return_value=self.warmup), patch.object(runner, 'write', side_effect=slow_write):
            with self.assertRaisesRegex(ValueError, 'crossed seed'):
                runner.initialize(self.out, '2026-10-31T00:00:00+08:00', self.api)
        frozen_sha = runner.sha(self.out / 'protocol.json')
        with self.assertRaisesRegex(ValueError, 'not sealed before seed'):
            runner.initialize(self.out, None, self.api)
        self.assertEqual(frozen_sha, runner.sha(self.out / 'protocol.json'))
        self.assertFalse((self.out / 'process.json').exists())

    def test_stop_during_metadata_blocks_protocol_commit(self):
        def download(*_args):
            runner.save(self.out / 'stop_requested.json', {'requested_ms': self.clock[0]})
            return self.warmup
        with patch.object(runner, 'prepare_public', side_effect=download):
            with self.assertRaisesRegex(RuntimeError, 'stopped by user'):
                runner.initialize(self.out, '2026-10-31T00:00:00+08:00', self.api)
        self.assertFalse((self.out / 'protocol.json').exists())


class PublicAccessGateTests(unittest.TestCase):
    def test_metadata_rate_limit_and_denial_survive_new_client_and_process(self):
        for error in (runner.RateLimited(2_000_000), runner.AccessDenied('denied')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                transport = Mock()
                transport.get.side_effect = error
                with patch.object(runner, 'PublicTransport', return_value=transport), \
                        patch.object(runner.time, 'time', return_value=1000):
                    with self.assertRaises(type(error)):
                        runner.PublicData(out).fetch('/fapi/v1/exchangeInfo')
                    later = runner.PublicData(out)
                    with self.assertRaises(type(error)):
                        later.fetch('/fapi/v1/time')
                self.assertEqual(transport.get.call_count, 1)
                self.assertTrue((out / 'public_access.json').exists())


class WorkerStartupTests(unittest.TestCase):
    def test_pid_without_successful_initialization_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            child = Mock(pid=123, poll=Mock(return_value=None))
            def spawn(*_args, **_kwargs):
                runner.save(out / 'process.json', dict(pid=123, started_ms=1_000_000))
                runner.save(out / 'runtime.json', dict(pid=123, state='startup_error', updated_ms=1_000_001))
                return child
            with patch.object(runner, 'owned_pid', side_effect=[None, 123]), \
                    patch.object(runner, 'verify_bundle'), patch.object(runner, 'PublicData'), \
                    patch.object(runner, 'initialize', return_value={'stop_ms': 2_000_000}), \
                    patch.object(runner.time, 'time', return_value=1000), \
                    patch.object(runner.subprocess, 'Popen', side_effect=spawn), \
                    patch('builtins.print') as output:
                with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
                    runner.start_background(out, None)
            output.assert_not_called()


if __name__ == '__main__':
    unittest.main()
