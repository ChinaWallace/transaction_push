"""Safety callbacks for the Freqtrade quant dry-run bridge."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from freqtrade.configuration.config_validation import validate_config_schema
from freqtrade.strategy import stoploss_from_absolute


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "freqtrade" / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGIES))
from QuantFuturesPortfolioStrategy import QuantFuturesPortfolioStrategy  # noqa: E402


PAIR = "BTC/USDT:USDT"


class FakeTrade:
    pair = PAIR
    amount = 10
    stake_amount = 500
    open_rate = 100
    max_rate = 100
    leverage = 3

    def __init__(self, has_open_orders=False):
        self.has_open_orders = has_open_orders
        self.custom = {}

    def get_custom_data(self, key, default=None):
        return self.custom.get(key, default)

    def set_custom_data(self, key, value):
        self.custom[key] = value


class QuantFreqtradeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)
        self.config = {
            "dry_run": True,
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "quant_plan_path": str(Path(self.temp.name) / "plan.json"),
            "dry_run_wallet": 10_000,
        }
        self.strategy = QuantFuturesPortfolioStrategy(self.config)
        self.strategy.bot_start()
        self.strategy.equity = 10_000
        self.strategy.gross = 0
        self.strategy.used_margin = 0
        self.strategy.complete_quotes = True
        self.target = {
            "pair": PAIR,
            "weight": 0.05,
            "leverage": 3,
            "atr": 5,
            "stop_price": 90,
            "entry_zone": [95, 105],
        }
        self.set_fresh_plan()

    def set_fresh_plan(self):
        now_ms = int(self.now.timestamp() * 1000)
        self.strategy.plan = {
            "complete": True,
            "version": "contracts-v3.1",
            "created_at": now_ms,
            "valid_until": now_ms + 180_000,
            "signal_id": "signal-1",
        }
        self.strategy.targets = {PAIR: self.target}

    def test_example_config_passes_freqtrade_schema(self):
        config_path = ROOT / "freqtrade" / "user_data" / "config.quant_v3.dryrun.example.json"
        config = json.loads(config_path.read_text())
        validate_config_schema(config)
        self.assertIs(config["dry_run"], True)
        self.assertEqual(config["trading_mode"], "futures")
        self.assertEqual(config["margin_mode"], "isolated")

    def test_bot_start_rejects_live_and_historical_modes(self):
        for change in ({"dry_run": False}, {"trading_mode": "spot"},
                       {"margin_mode": "cross"}, {"runmode": "backtest"}):
            with self.subTest(change=change):
                strategy = QuantFuturesPortfolioStrategy({**self.config, **change})
                with self.assertRaises(ValueError):
                    strategy.bot_start()

    def test_expired_external_plan_cannot_open_new_position(self):
        after_expiry = self.now + timedelta(minutes=4)
        with patch("QuantFuturesPortfolioStrategy.Trade.get_open_trades", return_value=[]):
            self.assertFalse(
                self.strategy.confirm_trade_entry(
                    PAIR, "limit", 1, 100, "gtc", after_expiry, "signal-1", "long"
                )
            )
        self.assertEqual(
            self.strategy.custom_stake_amount(
                PAIR, after_expiry, 100, 100, 1, 1000, 3, "signal-1", "long"
            ),
            0,
        )
        self.assertTrue(
            self.strategy.check_entry_timeout(PAIR, None, None, after_expiry)
        )

    def test_stoploss_converts_price_distance_using_position_leverage(self):
        trade = FakeTrade()
        actual = self.strategy.custom_stoploss(PAIR, trade, self.now, 100, 0)
        expected = stoploss_from_absolute(90, 100, is_short=False, leverage=3)
        self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(actual, 0.3)
        self.assertEqual(trade.custom["quant_stop"]["stop"], 90)

    def test_open_order_blocks_position_adjustment(self):
        trade = FakeTrade(has_open_orders=True)
        args = (trade, self.now, 100, 0, 1, 1000)
        self.assertIsNone(self.strategy.adjust_trade_position(*args))
        trade.has_open_orders = False
        adjustment = self.strategy.adjust_trade_position(*args)
        self.assertIsNotNone(adjustment)
        self.assertLess(adjustment[0], 0)
        self.assertEqual(adjustment[1], "target_reduce")


if __name__ == "__main__":
    unittest.main()
