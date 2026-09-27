"""Offline accounting invariants for a USDT, long-only cross-margin wallet."""

import copy
import unittest

from app.quant.cross_margin import CrossMarginAccount, maintenance


SIMPLE = [dict(minNotional=0, maxNotional=1_000_000,
               maintenanceMarginRate=.01, info={"cum": 0})]
ZEC_TIERS = [
    dict(minNotional=0, maxNotional=20_000, maintenanceMarginRate=.01, info={"cum": 0}),
    dict(minNotional=20_000, maxNotional=200_000,
         maintenanceMarginRate=.015, info={"cum": 100}),
]


def account(capital=1_000, fee=.001):
    book = CrossMarginAccount(capital, {"BTC": SIMPLE, "ETH": SIMPLE,
                                        "ZEC": ZEC_TIERS}, fee=fee)
    book.marks.update(BTC=100, ETH=100, ZEC=100)
    return book


class CrossMarginTests(unittest.TestCase):
    def test_two_x_low_exposure_has_same_economic_risk_as_one_x(self):
        one, two = account(), account()
        one.buy("BTC", 4, 100, 1, "fixture", leverage=1)
        two.buy("BTC", 4, 100, 1, "fixture", leverage=2)
        one.marks["BTC"] = two.marks["BTC"] = 50
        for field in ("wallet", "equity", "gross", "maintenance",
                      "maintenance_buffer", "all_zero_cash_floor",
                      "effective_leverage"):
            self.assertAlmostEqual(one.state()[field], two.state()[field], msg=field)
        self.assertAlmostEqual(one.state()["estimated_initial_margin"], 200)
        self.assertAlmostEqual(two.state()["estimated_initial_margin"], 100)
        self.assertIsNone(one.conditional_liquidation_price("BTC"))
        self.assertIsNone(two.conditional_liquidation_price("BTC"))

    def test_maintenance_uses_current_mark_not_entry_or_initial_margin(self):
        book = account(capital=100_000)
        book.buy("ZEC", 100, 100, 1, "fixture", leverage=2)
        self.assertAlmostEqual(book.state()["maintenance"], 100)
        book.marks["ZEC"] = 300  # Current notional crosses the 20,000 tier.
        self.assertAlmostEqual(book.state()["maintenance"], 350)
        self.assertAlmostEqual(maintenance(30_000, ZEC_TIERS), 350)

    def test_one_coin_zero_safe_does_not_mean_basket_zero_safe(self):
        book = account()
        for symbol in ("BTC", "ETH"):
            book.buy(symbol, 6, 100, 1, "fixture", leverage=2)
        self.assertIsNone(book.conditional_liquidation_price("BTC"))
        self.assertIsNone(book.conditional_liquidation_price("ETH"))
        self.assertLess(book.state()["all_zero_cash_floor"], 0)
        zero = book.state({"BTC": 0, "ETH": 0, "ZEC": 100})
        self.assertTrue(zero["at_liquidation"])

    def test_other_coin_fall_moves_conditional_liquidation_price(self):
        book = account()
        for symbol in ("BTC", "ETH"):
            book.buy(symbol, 6, 100, 1, "fixture", leverage=2)
        self.assertIsNone(book.conditional_liquidation_price("BTC"))
        book.marks["ETH"] = 30
        price = book.conditional_liquidation_price("BTC")
        self.assertIsNotNone(price)
        self.assertGreater(price, 0)
        below = book.state({"BTC": price - .01, "ETH": 30, "ZEC": 100})
        above = book.state({"BTC": price + .01, "ETH": 30, "ZEC": 100})
        self.assertTrue(below["at_liquidation"])
        self.assertFalse(above["at_liquidation"])

    def test_reduce_to_ninety_percent_counts_spread_and_both_fees(self):
        book = account()
        for symbol in ("BTC", "ETH"):
            book.buy(symbol, 6, 100, 1, "fixture", leverage=2)
        before = book.state()
        self.assertGreater(before["effective_leverage"], 1)
        self.assertTrue(book.reduce_to(.9, {"BTC": 98, "ETH": 98}, 2))
        after = book.state()
        self.assertAlmostEqual(after["effective_leverage"], .9, places=9)
        self.assertGreater(after["all_zero_cash_floor"], 0)
        self.assertLess(after["equity"], before["equity"])
        self.assertEqual([e["side"] for e in book.events],
                         ["buy", "buy", "sell", "sell"])
        self.assertFalse(book.reduce_to(.9, {"BTC": 98, "ETH": 98}, 3))

    def test_funding_changes_wallet_once_for_both_payment_signs(self):
        book = account()
        book.buy("BTC", 2, 100, 1, "fixture", leverage=2)
        initial = book.wallet
        book.fund("BTC", 10, .01, 120)
        self.assertAlmostEqual(book.wallet, initial - 2.4)
        book.fund("BTC", 10, .01, 120)
        self.assertAlmostEqual(book.wallet, initial - 2.4)
        book.fund("BTC", 20, -.005, 100)
        self.assertAlmostEqual(book.wallet, initial - 1.4)
        self.assertEqual(len([e for e in book.events if e["side"] == "funding"]), 2)

    def test_reduce_with_missing_second_quote_does_not_sell_first_position(self):
        book = account()
        for symbol in ("BTC", "ETH"):
            book.buy(symbol, 6, 100, 1, "fixture", leverage=2)
        original = (book.wallet, copy.deepcopy(book.positions), copy.deepcopy(book.events))
        with self.assertRaisesRegex(ValueError, "execution price"):
            book.reduce_to(.9, {"BTC": 98}, 2)
        self.assertEqual((book.wallet, book.positions, book.events), original)

    def test_rejected_buy_is_atomic_for_margin_and_leverage_mismatch(self):
        book = account()
        book.buy("BTC", 1, 100, 1, "fixture", leverage=2)
        for quantity, leverage, reason in ((100, 2, "Insufficient"),
                                           (1, 1, "migration")):
            with self.subTest(reason=reason):
                original = (book.wallet, copy.deepcopy(book.positions),
                            copy.deepcopy(book.events))
                with self.assertRaisesRegex(ValueError, reason):
                    book.buy("BTC", quantity, 100, 2, "rejected", leverage=leverage)
                self.assertEqual((book.wallet, book.positions, book.events), original)


if __name__ == "__main__":
    unittest.main()
