"""Profit is a sizing permission, not cash; signals use completed 4h bars."""
import unittest

from app.quant.core_growth import growth_notional


class GrowthBudgetTests(unittest.TestCase):
    def values(self, **overrides):
        value = dict(initial_quantity=20, initial_price=100, current_price=150,
            added_cost=0, last_add_price=100, profit_fraction=.5,
            free_collateral=3000, equity=11000, reserve_cash=1000, breakout=True)
        value.update(overrides)
        return value

    def test_uses_seed_profit_without_double_spending_past_adds(self):
        self.assertEqual(growth_notional(**self.values()), 500)
        self.assertEqual(growth_notional(**self.values(added_cost=450)), 50)
        self.assertEqual(growth_notional(**self.values(added_cost=600)), 0)

    def test_profit_never_creates_cash_or_spends_reserve(self):
        self.assertEqual(growth_notional(**self.values(current_price=1000, free_collateral=1000)), 0)
        self.assertEqual(growth_notional(**self.values(free_collateral=1100)), 100)
        self.assertEqual(growth_notional(**self.values(profit_fraction=1)), 550)

    def test_no_losing_add_no_repeated_add_no_unconfirmed_signal(self):
        for change in [dict(current_price=90), dict(last_add_price=150), dict(breakout=False)]:
            self.assertEqual(growth_notional(**self.values(**change)), 0)

    def test_invalid_inputs_are_rejected(self):
        for change in [dict(current_price=float('nan')), dict(profit_fraction=2), dict(added_cost=-1)]:
            with self.assertRaises(ValueError):growth_notional(**self.values(**change))


if __name__ == '__main__':unittest.main()
