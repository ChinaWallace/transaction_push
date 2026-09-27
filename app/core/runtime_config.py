"""Shared, lightweight configuration for every application profile.

No service imports or network access. OS environment overrides the project .env.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_ignore_empty=True,
                                     env_file_encoding="utf-8", case_sensitive=False, extra="ignore", hide_input_in_errors=True)
    binance_api_key: str = Field(default="", repr=False)
    binance_secret_key: str = Field(default="", repr=False)
    binance_testnet: bool = False
    binance_base_url: str = Field(default="https://fapi.binance.com", repr=False)
    binance_websocket_url: str = Field(default="wss://fstream.binance.com/ws/", repr=False)
    binance_enable_websocket: bool = True
    proxy_url: str | None = Field(default=None, repr=False)
    proxy_enabled: bool = False
    app_profile: Literal["quant", "legacy"] = "quant"
    quant_host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    quant_port: int = Field(default=8891, ge=1024, le=65535)
    quant_worker_enabled: bool = True
    quant_observation_seconds: int = Field(default=60, ge=10, le=900)
    quant_refresh_seconds: int = Field(default=300, ge=10, le=3600)
    quant_http_timeout_seconds: float = Field(default=20, ge=1, le=120)
    quant_http_workers: int = Field(default=3, ge=1, le=8)
    quant_history_bars: int = Field(default=240, ge=201, le=1000)
    quant_selection_timeframe: Literal["4h"] = "4h"
    quant_confirmation_timeframe: Literal["1h"] = "1h"
    quant_execution_timeframe: Literal["15m"] = "15m"
    quant_max_positions: int = Field(default=50, ge=1, le=50)
    quant_candidate_limit: int = Field(default=50, ge=1, le=50)
    quant_preferred_symbols: str = "ZECUSDT,BTCUSDT,ETHUSDT"
    quant_core_stop_mode: Literal["none", "wide"] = "none"
    quant_core_stop_distance: float = Field(default=.35, ge=.1, le=.5)
    quant_core_total_weight: float = Field(default=.7, gt=0, le=.7)
    quant_core_single_weight: float = Field(default=.7, gt=0, le=.7)
    quant_core_allow_weight_drift: bool = False
    quant_satellite_single_weight: float = Field(default=.1, gt=0, le=.1)
    quant_execution_mode: Literal["paper"] = "paper"
    quant_max_leverage: int = Field(default=3, ge=1, le=3)
    quant_position_risk: float = Field(default=.025, gt=0, le=.025)
    quant_initial_capital: float = Field(default=10000, gt=0)
    quant_data_dir: Path = PROJECT_ROOT / "reports/quant_v3/futures_universe"
    quant_output_dir: Path = PROJECT_ROOT / "reports/quant_v3/contracts"

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.quant_refresh_seconds < self.quant_observation_seconds:
            raise ValueError("QUANT_REFRESH_SECONDS must be >= QUANT_OBSERVATION_SECONDS")
        if self.proxy_enabled and not self.proxy_url:
            raise ValueError("PROXY_ENABLED requires PROXY_URL")
        url = urlsplit(self.binance_base_url)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("BINANCE_BASE_URL must be an HTTP(S) endpoint without credentials")
        if self.binance_testnet and url.hostname == "fapi.binance.com":
            raise ValueError("BINANCE_TESTNET=true requires an explicit testnet BINANCE_BASE_URL")
        for field in ("quant_data_dir", "quant_output_dir"):
            path = getattr(self, field)
            if not path.is_absolute(): setattr(self, field, PROJECT_ROOT / path)
        return self

    def public_status(self):
        return {"env_file": str(PROJECT_ROOT / ".env"), "env_exists": (PROJECT_ROOT / ".env").exists(),
                "precedence": "process environment > project .env > defaults",
                "binance_endpoint": urlunsplit(urlsplit(self.binance_base_url)._replace(query="",fragment="")), "testnet": self.binance_testnet,
                "api_key_configured": bool(self.binance_api_key), "secret_configured": bool(self.binance_secret_key),
                "credentials_used_for_market_data": False, "account_authentication_verified": False,
                "proxy_enabled": self.proxy_enabled, "proxy_configured": bool(self.proxy_url),
                "transport": "REST polling", "websocket_configured": self.binance_enable_websocket,
                "websocket_used_by_quant": False, "live_orders_enabled": False,
                "timeframes": [self.quant_selection_timeframe, self.quant_confirmation_timeframe, self.quant_execution_timeframe],
                "max_leverage": self.quant_max_leverage, "max_positions": self.quant_max_positions,
                "candidate_limit": self.quant_candidate_limit, "execution_mode": self.quant_execution_mode,
                "observation_seconds": self.quant_observation_seconds, "refresh_seconds": self.quant_refresh_seconds,
                "history_bars": self.quant_history_bars, "worker_enabled": self.quant_worker_enabled}


@lru_cache
def get_runtime_settings():
    return RuntimeSettings()
