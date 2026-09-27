import pytest

from app.schemas.freqtrade import FreqtradeBotStartRequest, FreqtradeRunMode
from app.services.trading.freqtrade_service import FreqtradeService
from scripts.freqtrade_signal_backtest import normalize_pairs


def test_normalize_okx_swap_symbols_to_freqtrade_futures_pairs():
    assert FreqtradeService._normalize_pairs(["BTC-USDT-SWAP", "ethusdt", "BTC/USDT:USDT"]) == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
    ]


def test_non_btc_eth_pair_is_rejected():
    with pytest.raises(ValueError, match="only BTC-USDT-SWAP and ETH-USDT-SWAP"):
        FreqtradeService._normalize_pairs(["SOL-USDT-SWAP"])


def test_config_file_must_stay_inside_user_data():
    service = FreqtradeService()

    with pytest.raises(ValueError):
        service._config_path("../secrets.json")


def test_auto_backend_prefers_docker_then_native():
    service = FreqtradeService()

    assert service._select_backend(True, True) == "docker"
    assert service._select_backend(False, True) == "native"
    assert service._select_backend(False, False) == "unavailable"


def test_default_strategy_uses_btc_eth_4h_baseline():
    service = FreqtradeService()

    assert service.default_strategy == "BtcEth4hStrategy"
    assert service.default_config == "config.btc_eth.dryrun.example.json"


def test_backtest_script_normalizes_project_symbol_inputs():
    assert normalize_pairs(["BTC-USDT-SWAP", "ethusdt", "ETH/USDT:USDT"]) == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
    ]


def test_checked_in_baseline_config_is_valid_and_native_resolvable(monkeypatch):
    service = FreqtradeService()
    monkeypatch.setattr(service, "_current_backend", lambda: "native")

    path = service._validated_dry_run_config_path(None)

    assert path.endswith("config.btc_eth.dryrun.example.json")


@pytest.mark.asyncio
async def test_live_mode_is_unconditionally_disabled():
    service = FreqtradeService()

    with pytest.raises(ValueError, match="Live trading is disabled"):
        await service.start_bot(
            FreqtradeBotStartRequest(
                mode=FreqtradeRunMode.LIVE,
                confirm_live=True,
            )
        )
