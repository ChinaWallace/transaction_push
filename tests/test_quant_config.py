"""Shared quant configuration and public transport boundaries."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.core.runtime_config import PROJECT_ROOT, RuntimeSettings
from app.quant.transport import MarketDataError, PublicMarketClient


class RuntimeSettingsTests(unittest.TestCase):
    def test_absolute_project_env_path_and_explicit_env_file_ignore_cwd(self):
        configured = Path(RuntimeSettings.model_config["env_file"])
        self.assertTrue(configured.is_absolute())
        self.assertEqual(configured, PROJECT_ROOT / ".env")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            env_file = directory / "quant.env"
            env_file.write_text("QUANT_PORT=9123\nQUANT_DATA_DIR=relative-market-data\n")
            elsewhere = directory / "elsewhere"
            elsewhere.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(elsewhere)
                with patch.dict(os.environ, {}, clear=True):
                    settings = RuntimeSettings(_env_file=env_file)
            finally:
                os.chdir(previous)
            self.assertEqual(settings.quant_port, 9123)
            self.assertEqual(settings.quant_data_dir, PROJECT_ROOT / "relative-market-data")

    def test_process_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "quant.env"
            env_file.write_text("QUANT_PORT=9123\nQUANT_MAX_LEVERAGE=2\n")
            with patch.dict(os.environ, {"QUANT_PORT": "9456", "QUANT_MAX_LEVERAGE": "3"},
                            clear=True):
                settings = RuntimeSettings(_env_file=env_file)
            self.assertEqual(settings.quant_port, 9456)
            self.assertEqual(settings.quant_max_leverage, 3)

    def test_invalid_leverage_proxy_and_refresh_intervals_fail_closed(self):
        cases = [
            ({"quant_max_leverage": 4}, "quant_max_leverage"),
            ({"proxy_enabled": True, "proxy_url": None}, "PROXY_URL"),
            ({"quant_observation_seconds": 120, "quant_refresh_seconds": 60},
             "QUANT_REFRESH_SECONDS"),
        ]
        with patch.dict(os.environ, {}, clear=True):
            for values, expected in cases:
                with self.subTest(values=values):
                    with self.assertRaises(ValidationError) as caught:
                        RuntimeSettings(_env_file=None, **values)
                    self.assertIn(expected, str(caught.exception))

    def test_public_status_and_repr_do_not_disclose_credentials_or_proxy(self):
        api_key = "test-api-key-not-for-output"
        secret = "test-secret-not-for-output"
        proxy_password = "test-proxy-password-not-for-output"
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings(
                _env_file=None,
                binance_api_key=api_key,
                binance_secret_key=secret,
                proxy_enabled=True,
                proxy_url=f"http://user:{proxy_password}@127.0.0.1:7890",
                binance_base_url="https://fapi.binance.com?token=hidden-query-token",
            )
        status = settings.public_status()
        serialized = json.dumps(status, sort_keys=True)
        self.assertTrue(status["api_key_configured"])
        self.assertTrue(status["secret_configured"])
        self.assertTrue(status["proxy_configured"])
        self.assertFalse(status["credentials_used_for_market_data"])
        self.assertFalse(status["live_orders_enabled"])
        for sensitive in (api_key, secret, proxy_password, "hidden-query-token"):
            self.assertNotIn(sensitive, serialized)
            self.assertNotIn(sensitive, repr(settings))


class PublicMarketClientTests(unittest.TestCase):
    def test_explicit_proxy_disables_environment_proxy_and_omits_credentials(self):
        proxy = "http://127.0.0.1:7890"
        with patch.dict(os.environ, {"HTTP_PROXY": "http://unwanted.example:8888"},
                        clear=True):
            settings = RuntimeSettings(_env_file=None, proxy_enabled=True,
                                       proxy_url=proxy,
                                       binance_api_key="test-key-not-for-request",
                                       binance_secret_key="test-secret-not-for-request")
            with patch("app.quant.transport.httpx.Client") as client_type, \
                 patch("app.quant.transport.time.sleep"):
                client_type.return_value.get.return_value.status_code = 200
                client_type.return_value.get.return_value.json.return_value = {"serverTime": 123}
                with PublicMarketClient(settings) as transport:
                    result = transport.get("/fapi/v1/time", params={"foo": "bar"})
            options = client_type.call_args.kwargs
            self.assertEqual(options["proxy"], proxy)
            self.assertIs(options["trust_env"], False)
            self.assertEqual(options["base_url"], settings.binance_base_url)
            self.assertNotIn("test-key-not-for-request", repr(options))
            self.assertNotIn("test-secret-not-for-request", repr(options))
            client_type.return_value.get.assert_called_once_with(
                "/fapi/v1/time", params={"foo": "bar"})
            client_type.return_value.close.assert_called_once()
            self.assertEqual(result, {"serverTime": 123})

    def test_http_451_error_does_not_include_url_or_proxy(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings(_env_file=None, proxy_enabled=True,
                                       proxy_url="http://user:test-proxy-secret@127.0.0.1:7890")
        with patch("app.quant.transport.httpx.Client") as client_type, \
             patch("app.quant.transport.time.sleep"):
            client_type.return_value.get.return_value.status_code = 451
            with PublicMarketClient(settings) as transport:
                with self.assertRaises(MarketDataError) as caught:
                    transport.get("/fapi/v1/time", params={"token": "test-query-secret"})
        message = str(caught.exception)
        self.assertIn("451", message)
        self.assertNotIn("test-proxy-secret", message)
        self.assertNotIn("test-query-secret", message)


if __name__ == "__main__":
    unittest.main()
