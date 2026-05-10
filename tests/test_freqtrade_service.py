import pytest

from app.services.trading.freqtrade_service import FreqtradeService


def test_normalize_okx_swap_symbols_to_freqtrade_futures_pairs():
    assert FreqtradeService._normalize_pairs(["BTC-USDT-SWAP", "ethusdt", "SOL-USDT"]) == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
    ]


def test_config_file_must_stay_inside_user_data():
    service = FreqtradeService()

    with pytest.raises(ValueError):
        service._container_config_path("../secrets.json")

