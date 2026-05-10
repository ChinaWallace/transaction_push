import pytest

from app.schemas.paper_trading import PaperPortfolioBucket, PaperTradeSide, PaperTradingMode
from app.schemas.trading import SignalStrength, TradingSignal
from app.services.notification.core_notification_service import CoreNotificationService, NotificationPriority
from app.services.trading.paper_trading_service import PaperTradingService


@pytest.mark.asyncio
async def test_long_only_rejects_short_signal():
    service = PaperTradingService()
    signal = TradingSignal(
        symbol="BTC-USDT-SWAP",
        final_action="sell",
        final_confidence=0.9,
        signal_strength=SignalStrength.STRONG,
        reasoning="test",
        current_price=100.0,
        entry_price=100.0,
        stop_loss=105.0,
        take_profit=90.0,
    )

    plan, reject = await service._build_plan(signal, PaperTradingMode.BALANCED, long_only=True)

    assert plan is None
    assert reject is not None
    assert reject.reason == "short_not_allowed"


def test_action_text_repairs_mojibake_buy_and_sell():
    buy = "\u4e70\u5165".encode("utf-8").decode("latin1")
    sell = "\u5356\u51fa".encode("utf-8").decode("latin1")

    assert PaperTradingService._action_to_side(buy).value == "long"
    assert PaperTradingService._action_to_side(sell).value == "short"


def test_leverage_limits_by_bucket_and_symbol():
    service = PaperTradingService()

    assert service._max_leverage_for_symbol("BTC-USDT-SWAP", PaperPortfolioBucket.CORE) == 3.0
    assert service._max_leverage_for_symbol("ZEC-USDT-SWAP", PaperPortfolioBucket.CORE) == 2.0
    assert service._max_leverage_for_symbol("PEPE-USDT-SWAP", PaperPortfolioBucket.SATELLITE) == 1.5


def test_partial_take_profit_only_for_long_1r_target():
    position = {
        "side": PaperTradingService._action_to_side("buy"),
        "entry_price": 100.0,
        "risk_per_unit": 5.0,
    }

    assert PaperTradingService._partial_take_profit_price(position, {"high": 104.9}) is None
    assert PaperTradingService._partial_take_profit_price(position, {"high": 105.0}) == 105.0


def test_backtest_proactive_exit_on_trend_breakdown():
    service = PaperTradingService()
    position = {
        "side": PaperTradeSide.LONG,
        "entry_price": 100.0,
        "quantity": 1.0,
        "risk_per_unit": 5.0,
    }

    price, reason = service._backtest_proactive_exit_price(
        position=position,
        idx=2,
        candle={"close": 96.0},
        closes=[101.0, 99.0, 96.0],
        ema_fast=[None, 100.0, 98.0],
        ema_slow=[None, 99.0, 99.5],
        rsi=[None, 52.0, 44.0],
    )

    assert price == 96.0
    assert reason == "trend_reversal"


def test_priority_strings_are_normalized_for_notifications():
    assert CoreNotificationService._coerce_priority("high") == NotificationPriority.HIGH
    assert CoreNotificationService._coerce_priority("4") == NotificationPriority.HIGH
    assert CoreNotificationService._coerce_priority("bad-value") == NotificationPriority.NORMAL
