"""Isolated, public-only transport and immutable execution bundles for forward runs."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import urlsplit

import httpx

PACKAGES = ('httpx', 'httpcore', 'pandas', 'numpy', 'pyarrow')


class RateLimited(RuntimeError):
    def __init__(self, retry_at_ms):
        super().__init__('Public API rate limit; requests suspended until retry deadline')
        self.retry_at_ms = retry_at_ms


class AccessDenied(RuntimeError):
    pass


def network_settings(root):
    """Read only network keys, never load trading credentials or print proxy URLs."""
    values = {}
    path = Path(root) / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r'^\s*(PROXY_ENABLED|PROXY_URL)\s*=\s*(.*)$', line)
            if match:
                values[match[1]] = match[2].strip().strip('\"').strip("'")
    for key in ('PROXY_ENABLED', 'PROXY_URL'):
        if key in os.environ:
            values[key] = os.environ[key]
    enabled = values.get('PROXY_ENABLED', '').lower() in ('1', 'true', 'yes', 'on')
    if enabled:
        parsed = urlsplit(values.get('PROXY_URL', ''))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Enabled public proxy must have a valid HTTP(S) URL')
    return {'PROXY_ENABLED': 'true' if enabled else 'false',
            'PROXY_URL': values.get('PROXY_URL', '') if enabled else ''}


class PublicTransport:
    def __init__(self, root, factory=None):
        self.settings = network_settings(root)
        self.factory = factory or httpx.Client
        self.client = None
        self.next_request = 0.

    def close(self):
        if self.client is not None:
            client, self.client = self.client, None
            client.close()

    def get(self, url, params=None):
        if urlsplit(url).netloc != 'fapi.binance.com':
            raise ValueError('Only the frozen public futures data host is allowed')
        for attempt in range(4):
            wait = self.next_request - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.next_request = time.monotonic() + .21
            if self.client is None:
                self.client = self.factory(
                    proxy=self.settings['PROXY_URL'] or None, trust_env=False,
                    timeout=httpx.Timeout(20, connect=10, pool=5),
                    limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
                    follow_redirects=False,
                    headers={'User-Agent': 'transaction-push-forward-public-research/2'})
            try:
                response = self.client.get(url, params=params)
            except httpx.TransportError as error:
                self.close()  # A failed CONNECT/TLS must not retain an allocated pool slot.
                if attempt == 3:
                    raise RuntimeError('Public transport failed: ' + type(error).__name__) from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code in (418, 429):
                try:
                    delay = max(60., float(response.headers.get('Retry-After', '900')))
                except ValueError:
                    delay = 900.
                if response.status_code == 418:
                    delay = max(delay, 3 * 86400.)
                self.close()
                raise RateLimited(int((time.time() + delay) * 1000))
            if response.status_code in (403, 451):
                self.close()
                raise AccessDenied('Public API access denied; manual review required')
            if response.status_code >= 500 and attempt < 3:
                self.close()
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise RuntimeError('Public HTTP status ' + str(response.status_code))
            return response.content
        raise AssertionError('unreachable')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment_versions():
    return {'python': sys.version.split()[0],
            'packages': {name: importlib.metadata.version(name) for name in PACKAGES}}


def verify_bundle(root):
    root = Path(root)
    manifest = root / 'bundle.json'
    if digest(manifest) != (root / 'bundle.sha256').read_text().strip():
        raise ValueError('Execution bundle manifest changed')
    data = json.loads(manifest.read_text())
    for relative, expected in data['files'].items():
        if digest(root / relative) != expected:
            raise ValueError('Execution bundle file changed: ' + relative)
    if environment_versions() != data['environment']:
        raise ValueError('Frozen Python dependency versions changed')
    return data


def build_bundle(root, out, sources, bootstrap_mode=None):
    """Copy code and hashed bootstrap inputs; never copy .env, credentials, or ledgers."""
    root, out = Path(root), Path(out)
    target = out / 'code'
    if target.exists():
        existing = verify_bundle(target)
        if bootstrap_mode is not None and existing.get('bootstrap_mode', 'historical') != bootstrap_mode:
            raise ValueError('Existing batch bootstrap mode is frozen')
        return target
    if (out / 'protocol.json').exists():
        raise ValueError('Legacy batch is frozen; use its saved runner, not new source')
    bootstrap_mode = bootstrap_mode or 'historical'
    if bootstrap_mode not in ('historical', 'public'):
        raise ValueError('Unsupported bootstrap mode')
    inputs = ('reports/quant_v9/binance_leverage_tiers.json',)
    if bootstrap_mode == 'historical':
        inputs += ('reports/quant_v12/protocol.json',)
        inputs += tuple('reports/quant_v12/data/series/' + s + '.feather'
                        for s in ('BTCUSDT', 'ETHUSDT', 'ZECUSDT'))
    files = tuple(dict.fromkeys(tuple(sources) + inputs))
    temporary = out / ('.code-' + str(os.getpid()))
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        hashes = {}
        for relative in files:
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            expected = digest(root / relative)
            shutil.copyfile(root / relative, destination)
            if digest(destination) != expected:
                raise ValueError('Source changed while freezing execution bundle: ' + relative)
            hashes[relative] = expected
        manifest = {'created_ms': int(time.time() * 1000), 'source_root': str(root),
                    'bootstrap_mode': bootstrap_mode,
                    'files': hashes, 'environment': environment_versions()}
        (temporary / 'bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (temporary / 'bundle.sha256').write_text(digest(temporary / 'bundle.json') + '\n')
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    verify_bundle(target)
    return target
