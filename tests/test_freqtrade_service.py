import pytest

from app.services.trading.freqtrade_service import FreqtradeService
from scripts.freqtrade_signal_backtest import normalize_pairs


def test_normalize_okx_swap_symbols_to_freqtrade_futures_pairs():
    assert FreqtradeService._normalize_pairs(["BTC-USDT-SWAP", "ethusdt", "SOL-USDT"]) == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
    ]


def test_config_file_must_stay_inside_user_data():
    service = FreqtradeService()

    with pytest.raises(ValueError):
        service._config_path("../secrets.json")


def test_auto_backend_prefers_docker_then_native():
    service = FreqtradeService()

    assert service._select_backend(True, True) == "docker"
    assert service._select_backend(False, True) == "native"
    assert service._select_backend(False, False) == "unavailable"


def test_default_strategy_uses_open_source_trend_replacement():
    service = FreqtradeService()

    assert service.default_strategy == "OpenSourceTrendStrategy"


def test_backtest_script_normalizes_project_symbol_inputs():
    assert normalize_pairs(["OP-USDT-SWAP", "arbusdt", "ETH/USDT:USDT"]) == [
        "OP/USDT:USDT",
        "ARB/USDT:USDT",
        "ETH/USDT:USDT",
    ]
