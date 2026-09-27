"""Public REST transport using the same project settings as the legacy app."""
import threading
import time
import httpx
from app.core.runtime_config import get_runtime_settings

_rate_lock = threading.Lock()
_last_request = 0.0


class MarketDataError(RuntimeError):
    pass


class PublicMarketClient:
    def __init__(self, settings=None):
        self.settings = settings or get_runtime_settings()
        self.client = httpx.Client(
            base_url=self.settings.binance_base_url.rstrip("/"),
            proxy=self.settings.proxy_url if self.settings.proxy_enabled else None,
            trust_env=False, timeout=self.settings.quant_http_timeout_seconds,
            headers={"User-Agent": "transaction-push-quant/4.0"})

    def get(self, path, params=None):
        global _last_request
        # Bounded public request rate shared by collector and funding readers.
        with _rate_lock:
            time.sleep(max(0, .15 - (time.monotonic() - _last_request)))
            _last_request = time.monotonic()
        try:
            response = self.client.get(path, params=params)
            if response.status_code == 451:
                raise MarketDataError("Binance HTTP 451: regional access restricted; collection stopped")
            if response.status_code in {418, 429}:
                raise MarketDataError(f"Binance HTTP {response.status_code}: rate limited; wait for next collection")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # HTTP/proxy errors may contain URLs and credentials; do not persist them.
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
            raise MarketDataError(f"Public market request failed ({code})") from None

    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
