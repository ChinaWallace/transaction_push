"""Offline contract tests for the independently downloaded public warmup."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import forward_bootstrap as bootstrap
from scripts import forward_expanded_core as runner
from scripts import forward_runtime as runtime


# The frozen clock gives exactly 92 whole days of closed five-minute candles.
NOW_MS = 100 * bootstrap.DAY + 15_000
END_MS = 100 * bootstrap.DAY
START_MS = END_MS - 92 * bootstrap.DAY
EXPECTED_ROWS = 92 * bootstrap.DAY // bootstrap.STEP
EXPECTED_PAGES = 2 * len(bootstrap.SYMBOLS) * ((EXPECTED_ROWS + 999) // 1000)


class FakePublicAPI:
    """Generates Binance-shaped trade/mark pages without a network call."""

    def __init__(self, fail_page=None, error=None):
        self.calls = []
        self.page_count = 0
        self.fail_page = fail_page
        self.error = error

    def fetch(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if endpoint == '/fapi/v1/time':
            return {'serverTime': NOW_MS}
        if endpoint not in bootstrap.ENDPOINTS:
            raise AssertionError(f'unexpected public endpoint: {endpoint}')
        self.page_count += 1
        if self.page_count == self.fail_page:
            raise self.error or RuntimeError('simulated transport failure')
        start = params['startTime']
        end = params['endTime'] + 1
        assert params['limit'] == 1000 and params['interval'] == '5m'
        assert 0 < end - start <= 1000 * bootstrap.STEP
        return [[at, '100', '102', '99', '101', '1',
                 at + bootstrap.STEP - 1, '101', 1, '1', '101', '0']
                for at in range(start, end, bootstrap.STEP)]


class PublicBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / 'batch'
        self.clock = patch.object(bootstrap.time, 'time', return_value=NOW_MS / 1000)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_public_bundle_omits_historical_feathers_and_seals_full_warmup(self):
        root = Path(self.temporary.name) / 'repo'
        source = root / 'scripts/forward_bootstrap.py'
        source.parent.mkdir(parents=True)
        source.write_text('frozen bootstrap source\n')
        tiers = root / 'reports/quant_v9/binance_leverage_tiers.json'
        tiers.parent.mkdir(parents=True)
        tiers.write_text('{}\n')
        (root / '.env').write_text('API_SECRET=must-not-copy\n')
        code = runtime.build_bundle(root, self.out, ('scripts/forward_bootstrap.py',), 'public')
        self.assertEqual(runtime.verify_bundle(code)['bootstrap_mode'], 'public')
        self.assertFalse((code / '.env').exists())
        self.assertFalse((code / 'reports/quant_v12/protocol.json').exists())
        self.assertFalse((code / 'reports/quant_v12/data/series').exists())
        with self.assertRaisesRegex(ValueError, 'mode is frozen'):
            runtime.build_bundle(root, self.out, (), 'historical')

        api = FakePublicAPI()
        manifest = bootstrap.prepare_public(self.out, api)
        self.assertEqual((manifest['start_ms'], manifest['end_ms']), (START_MS, END_MS))
        self.assertEqual(len(manifest['pages']), EXPECTED_PAGES)
        self.assertEqual(api.page_count, EXPECTED_PAGES)
        self.assertEqual(set(manifest['files']), set(bootstrap.SYMBOLS))
        self.assertFalse((self.out / 'protocol.json').exists())
        self.assertEqual(bootstrap.load_public(self.out), manifest)
        for symbol, item in manifest['files'].items():
            self.assertEqual(item['rows'], EXPECTED_ROWS, symbol)
            self.assertEqual(runtime.digest(self.out / item['path']), item['sha256'])
            frame = __import__('pandas').read_feather(self.out / item['path'])
            bootstrap.validate_frame(frame, START_MS, END_MS, symbol)
        for item in manifest['pages']:
            self.assertEqual(runtime.digest(self.out / item['path']), item['sha256'])
        self.assertEqual(runtime.digest(self.out / 'bootstrap/plan.json'), manifest['plan_sha256'])
        stored_plan = bootstrap.read(self.out / 'bootstrap/plan.json')
        self.assertEqual(stored_plan['sha256'], bootstrap.rows_digest(stored_plan['plan']))
        self.assertEqual(stored_plan['plan']['start_ms'], START_MS)
        self.assertFalse((self.out / 'bootstrap/plan.sha256').exists())
        self.assertEqual(runtime.digest(self.out / 'bootstrap/ready/manifest.json'),
                         (self.out / 'bootstrap/ready/manifest.sha256').read_text().strip())
        before = len(api.calls)
        self.assertEqual(bootstrap.prepare_public(self.out, api), manifest)
        self.assertEqual(len(api.calls), before, 'sealed warmup must never redownload')

    def test_interrupted_download_resumes_only_missing_pages_without_protocol(self):
        first = FakePublicAPI(fail_page=4)
        with patch.object(runner, 'ROOT', self.out / 'code'):
            (runner.ROOT).mkdir(parents=True)
            (runner.ROOT / 'bundle.json').write_text(json.dumps({'bootstrap_mode': 'public'}))
            with self.assertRaisesRegex(RuntimeError, 'simulated transport failure'):
                runner.initialize(self.out, runner.iso(END_MS + 2 * bootstrap.DAY), first)
        self.assertEqual(first.page_count, 4)
        self.assertEqual(len(list((self.out / 'bootstrap/pages').rglob('*.json'))), 3)
        self.assertFalse((self.out / 'bootstrap/ready').exists())
        self.assertFalse((self.out / 'protocol.json').exists())
        self.assertFalse((self.out / 'protocol.sha256').exists())
        self.assertEqual(bootstrap.read(self.out / 'bootstrap/status.json')['state'], 'download_error')

        resumed = FakePublicAPI()
        manifest = bootstrap.prepare_public(self.out, resumed)
        self.assertEqual(len(manifest['pages']), EXPECTED_PAGES)
        self.assertEqual(resumed.page_count, EXPECTED_PAGES - 3)
        self.assertEqual((manifest['start_ms'], manifest['end_ms']), (START_MS, END_MS))
        self.assertFalse((self.out / 'protocol.json').exists())

    def test_missing_or_corrupt_sealed_cache_is_rejected_without_network(self):
        api = FakePublicAPI()
        bootstrap.prepare_public(self.out, api)
        first_page = self.out / bootstrap.load_public(self.out)['pages'][0]['path']
        first_page.write_text('{}')
        # A ready warmup loads only sealed feathers, but the manifest records
        # page hashes for an independent provenance audit.
        self.assertNotEqual(runtime.digest(first_page), bootstrap.load_public(self.out)['pages'][0]['sha256'])
        sealed = self.out / 'bootstrap/ready/BTCUSDT.feather'
        sealed.write_bytes(b'corrupt')
        before = len(api.calls)
        with self.assertRaisesRegex(ValueError, 'file changed'):
            bootstrap.prepare_public(self.out, api)
        self.assertEqual(len(api.calls), before)
        sealed.unlink()
        with self.assertRaises(FileNotFoundError):
            bootstrap.load_public(self.out)

    def test_corrupt_resumable_page_is_rejected_instead_of_silently_refetched(self):
        first = FakePublicAPI(fail_page=2)
        with self.assertRaises(RuntimeError):
            bootstrap.prepare_public(self.out, first)
        page = next((self.out / 'bootstrap/pages').rglob('*.json'))
        record = bootstrap.read(page)
        record['rows'][0][4] = '999'
        page.write_text(json.dumps(record))
        resumed = FakePublicAPI()
        with self.assertRaisesRegex(ValueError, 'Cached public warmup page changed'):
            bootstrap.prepare_public(self.out, resumed)
        self.assertEqual([endpoint for endpoint, _ in resumed.calls], ['/fapi/v1/time'])
        self.assertFalse((self.out / 'bootstrap/ready').exists())
        self.assertFalse((self.out / 'protocol.json').exists())

    def test_missing_duplicate_or_reversed_public_candles_never_seal(self):
        for defect in ('missing', 'duplicate', 'reversed'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)

                class BadPage(FakePublicAPI):
                    def fetch(self, endpoint, params=None):
                        rows = super().fetch(endpoint, params)
                        if endpoint == bootstrap.ENDPOINTS[0] and self.page_count == 1:
                            if defect == 'missing':
                                rows.pop(0)
                            elif defect == 'duplicate':
                                rows[1][0] = rows[0][0]
                            else:
                                rows.reverse()
                        return rows

                api = BadPage()
                with self.assertRaisesRegex(ValueError, 'missing candles|not consecutive'):
                    bootstrap.prepare_public(out, api)
                self.assertEqual(api.page_count, 1)
                self.assertFalse((out / 'bootstrap/ready').exists())
                self.assertFalse((out / 'protocol.json').exists())

    def test_invalid_ohlc_nan_or_negative_volume_never_seal(self):
        for defect, message in (('ohlc', 'inconsistent OHLC'),
                                ('nan', 'invalid price'),
                                ('volume', 'invalid quote volume')):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)

                class BadMarketValue(FakePublicAPI):
                    def fetch(self, endpoint, params=None):
                        rows = super().fetch(endpoint, params)
                        if endpoint == bootstrap.ENDPOINTS[0] and self.page_count == 1:
                            if defect == 'ohlc':
                                rows[0][2] = '90'  # high below open and close
                            elif defect == 'nan':
                                rows[0][4] = 'nan'
                            else:
                                rows[0][7] = '-1'
                        return rows

                api = BadMarketValue()
                with self.assertRaisesRegex(ValueError, message):
                    bootstrap.prepare_public(out, api)
                pages_per_symbol = 2 * ((EXPECTED_ROWS + 999) // 1000)
                self.assertEqual(api.page_count, pages_per_symbol)
                self.assertFalse((out / 'bootstrap/ready').exists())
                self.assertFalse((out / 'protocol.json').exists())

    def test_rate_limit_and_access_denial_suspend_further_requests(self):
        for error, state in ((bootstrap.RateLimited(NOW_MS + 60_000), 'rate_limited'),
                             (bootstrap.AccessDenied('denied'), 'access_denied')):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                first = FakePublicAPI(fail_page=1, error=error)
                with self.assertRaises(type(error)):
                    bootstrap.prepare_public(out, first)
                self.assertEqual(first.page_count, 1)
                self.assertEqual(bootstrap.read(out / 'bootstrap/status.json')['state'], state)
                later = FakePublicAPI()
                with self.assertRaises(type(error)):
                    bootstrap.prepare_public(out, later)
                self.assertEqual(later.calls, [], 'blocked state must prevent even a time request')
                self.assertFalse((out / 'protocol.json').exists())

    def test_stop_during_download_cancels_before_next_page_and_never_seals(self):
        out = self.out

        class StopAfterFirstPage(FakePublicAPI):
            def fetch(self, endpoint, params=None):
                result = super().fetch(endpoint, params)
                if endpoint in bootstrap.ENDPOINTS:
                    (out / 'stop_requested.json').write_text('{"requested_ms": 1}')
                return result

        api = StopAfterFirstPage()
        with self.assertRaises(bootstrap.PreparationCancelled):
            bootstrap.prepare_public(out, api)
        self.assertEqual(api.page_count, 1)
        self.assertEqual(bootstrap.read(out / 'bootstrap/status.json')['state'], 'cancelled')
        self.assertEqual(len(list((out / 'bootstrap/pages').rglob('*.json'))), 1)
        self.assertFalse((out / 'bootstrap/ready').exists())
        self.assertFalse((out / 'protocol.json').exists())
        subsequent = FakePublicAPI()
        with self.assertRaises(bootstrap.PreparationCancelled):
            bootstrap.prepare_public(out, subsequent)
        self.assertEqual(subsequent.calls, [])


if __name__ == '__main__':
    unittest.main()
