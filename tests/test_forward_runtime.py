"""Connection recovery, immutable bundles, and truthful forward observations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from scripts import forward_runtime as runtime
from tests.test_expanded_forward import runner


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'PROXY_ENABLED': 'false', 'PROXY_URL': ''})
        self.environment.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.temporary.cleanup)

    def test_tls_or_pool_error_discards_failed_client_and_uses_new_connection(self):
        for error in (httpx.ConnectError('private-proxy-url'), httpx.PoolTimeout('pool exhausted')):
            broken = Mock()
            broken.get.side_effect = error
            healthy = Mock()
            healthy.get.return_value = httpx.Response(200, content=b'{"serverTime": 123}')
            factory = Mock(side_effect=[broken, healthy])
            transport = runtime.PublicTransport(self.temporary.name, factory)
            with patch.object(runtime.time, 'sleep'):
                value = transport.get('https://fapi.binance.com/fapi/v1/time')
            self.assertEqual(value, b'{"serverTime": 123}')
            broken.close.assert_called_once()
            self.assertEqual(factory.call_count, 2)
            transport.close()
            healthy.close.assert_called_once()

    def test_bounded_transport_retries_do_not_leak_sensitive_exception_text(self):
        clients = [Mock() for _ in range(4)]
        for client in clients:
            client.get.side_effect = httpx.ConnectError('secret-proxy-password')
        transport = runtime.PublicTransport(self.temporary.name, Mock(side_effect=clients))
        with patch.object(runtime.time, 'sleep'), self.assertRaises(RuntimeError) as caught:
            transport.get('https://fapi.binance.com/fapi/v1/time')
        self.assertNotIn('secret', str(caught.exception))
        for client in clients:
            client.close.assert_called_once()
        self.assertIsNone(transport.client)

    def test_429_honors_backoff_and_does_not_retry_immediately(self):
        client = Mock()
        client.get.return_value = httpx.Response(429, headers={'Retry-After': '120'})
        transport = runtime.PublicTransport(self.temporary.name, Mock(return_value=client))
        with patch.object(runtime.time, 'time', return_value=1000), self.assertRaises(runtime.RateLimited) as caught:
            transport.get('https://fapi.binance.com/fapi/v1/time')
        self.assertEqual(caught.exception.retry_at_ms, 1120000)
        client.get.assert_called_once()

    def test_access_denial_is_not_retried_or_redirected(self):
        for status in (403, 451):
            client = Mock()
            client.get.return_value = httpx.Response(status)
            transport = runtime.PublicTransport(self.temporary.name, Mock(return_value=client))
            with self.assertRaises(runtime.AccessDenied):
                transport.get('https://fapi.binance.com/fapi/v1/time')
            client.get.assert_called_once()

    def test_direct_network_works_without_dotenv_and_private_host_rejected(self):
        transport = runtime.PublicTransport(self.temporary.name)
        self.assertEqual(transport.settings['PROXY_ENABLED'], 'false')
        with self.assertRaisesRegex(ValueError, 'host'):
            transport.get('https://example.com/private')
        self.assertIsNone(transport.client)


class EvidenceTests(unittest.TestCase):
    def test_explicit_stop_prevents_service_restart_from_opening_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            runner.save(out / 'stop_requested.json', {'requested_ms': 100})
            with patch.object(runner, 'PublicData') as api:
                runner.run(out, None)
            api.assert_not_called()
            self.assertFalse((out / 'process.json').exists())

    def test_no_new_candle_after_restart_reports_active_without_changing_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            end = 20 * runner.STEP
            protocol = dict(stop_ms=end + runner.DAY)
            runner.save(out / 'protocol.json', protocol)
            (out / 'protocol.sha256').write_text(runner.sha(out / 'protocol.json'))
            snapshot = dict(state='stopped_by_signal', data_end_ms=end, observed_ms=end + 1000,
                            arms={'TriHold': {}})
            runner.save(out / 'latest.json', snapshot)
            api = Mock()
            api.fetch.return_value = {'serverTime': end + 20_000}
            with patch.object(runner, 'verify_protocol'), patch.object(runner.time, 'time', return_value=(end + 20_000) / 1000):
                result = runner.cycle(out, protocol, api)
            self.assertEqual(result['state'], 'observing')
            self.assertEqual(result['observed_ms'], snapshot['observed_ms'])

    def test_failed_worker_initialization_removes_stale_pid_and_records_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            api = Mock()
            with patch.object(runner, 'ROOT', out), patch.object(runner, 'PublicData', return_value=api), \
                    patch.object(runner.signal, 'signal'), patch.object(runner, 'initialize', side_effect=ValueError('protocol changed')):
                with self.assertRaisesRegex(ValueError, 'protocol changed'):
                    runner.run(out, None)
            self.assertFalse((out / 'process.json').exists())
            self.assertEqual(runner.read(out / 'runtime.json')['state'], 'startup_error')
            api.close.assert_called_once()

    def test_shutdown_preserves_last_successful_observation_for_late_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            seed = 1_000_000_000
            protocol = dict(seed_ms=seed, stop_ms=seed + 100 * runner.STEP)
            before = dict(state='observing', data_end_ms=seed + runner.STEP,
                          observed_ms=seed + runner.STEP + 1000, arms={})
            runner.save(out / 'latest.json', before)
            with patch.object(runner.time, 'time', return_value=(seed + 12 * runner.STEP) / 1000):
                runner.finish(out, protocol, stopped=True, stop_signal=15)
            after = runner.read(out / 'latest.json')
            self.assertEqual(after['observed_ms'], before['observed_ms'])
            self.assertGreater(after['stopped_ms'], after['observed_ms'])
            timing = runner.observation_timing(after, seed + 13 * runner.STEP,
                                                seed + 12 * runner.STEP, seed)
            self.assertTrue(timing['late_collection'])
            self.assertEqual(timing['new_completed_5m'], 11)

    def test_partial_sales_do_not_count_as_closed_positions(self):
        def event(side, amount):
            return dict(symbol='BTCUSDT', sleeve='overlay', side=side, amount=amount)
        events = [event('buy', 1), event('sell', .5)]
        self.assertEqual(runner.closed_overlay_positions(events), 0)
        self.assertEqual(runner.closed_overlay_positions(events + [event('sell', .5)]), 1)

    def test_execution_bundle_keeps_original_code_and_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, out = Path(temporary) / 'repo', Path(temporary) / 'run'
            sources = ('scripts/runner.py', 'app/quant/expanded_core.py')
            paths = sources + ('reports/quant_v12/protocol.json', 'reports/quant_v9/binance_leverage_tiers.json')
            paths += tuple('reports/quant_v12/data/series/' + s + '.feather'
                           for s in ('BTCUSDT', 'ETHUSDT', 'ZECUSDT'))
            for path in paths:
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text('frozen-content')
            (root / '.env').write_text('API_SECRET=never-copy\n')
            bundle = runtime.build_bundle(root, out, sources)
            (root / sources[0]).write_text('new-research-version')
            runtime.verify_bundle(bundle)
            self.assertEqual((bundle / sources[0]).read_text(), 'frozen-content')
            self.assertFalse((bundle / '.env').exists())
            self.assertEqual(runtime.build_bundle(root, out, sources), bundle)
            (bundle / sources[1]).write_text('changed')
            with self.assertRaisesRegex(ValueError, 'file changed'):
                runtime.verify_bundle(bundle)


if __name__ == '__main__':
    unittest.main()
