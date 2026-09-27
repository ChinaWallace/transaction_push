"""Fixed strategy-rule comparisons and paper-account exit invariants."""

import copy
import unittest

from app.advisory.engine import DAY
from app.quant.futures_book import FuturesBook
from app.quant.multiframe import PERIODS, features
from app.quant.policy import PortfolioPolicy
from app.quant.strategy_rules import CASES, StrategyRules, apply_rules


T = 1_780_000_000_000
VERSION = "contracts-v4.0-mtf"


def quote(price=100):
    return {"bid": price, "ask": price, "mark": price}


def target(symbol, *, core=False, stop=90, weight=.1, atr=4):
    return {"symbol": symbol, "weight": weight, "leverage": 1 if core else 2,
            "stop_price": 0 if core else stop, "entry_zone": [95, 105], "atr": atr,
            "holding_policy": "core" if core else "satellite",
            "stop_mode": "none" if core else "atr"}


def plan(policy, targets, signal, *, max_hold_ms=72 * 3_600_000,
         exits=None, retain=False):
    return {"version": VERSION, "signal_id": signal,
            "execution_policy": "multiframe_rotation", "strategy_schema": 4,
            "targets": targets, "policy": policy.model_dump(),
            "max_positions": policy.max_positions, "margin_limit": .85,
            "core_drawdown_exempt": True, "position_risk_budget": .025,
            "entry_allowed_symbols": [t["symbol"] for t in targets],
            "signal_expires_at": T + 100 * DAY,
            "max_hold_ms": max_hold_ms, "retain_until_exit": retain,
            "exit_signals": exits or {}, "protective_updates": {}}


def row(symbol="SOLUSDT", *, action="wait_15m_trigger", close4=110,
        high4=105, close15=100):
    four = {"closed_at": T - 1, "close": close4, "ema50": 100,
            "prior_high20": high4, "atr": 8}
    return {"symbol": symbol, "action": action, "rejections": [],
            "features": {"close": close15, "atr": 4},
            "timeframes": {"4h": four, "15m": {"atr": 2}},
            "signal": {"selection_closed_at": T - 1, "trigger_15m": None,
                       "exit_1h": False, "exit_15m": True},
            "entry_zone": [95, 105], "stop_price": 90,
            "hold_eligible": False}


class FuturesBookRuleTests(unittest.TestCase):
    def test_72_hour_expiry_closes_satellite_but_not_core(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        core = target("ZECUSDT", core=True, weight=.2)
        satellite = target("SOLUSDT")
        book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
        quotes = {"ZECUSDT": quote(), "SOLUSDT": quote()}
        book.apply(plan(policy, [core, satellite], "open"), quotes, T, "open")
        self.assertEqual(set(book.positions), {"ZECUSDT", "SOLUSDT"})
        expiry = T + 72 * 3_600_000
        book.apply(plan(policy, [core, satellite], "open"), quotes, expiry, "open")
        self.assertEqual(set(book.positions), {"ZECUSDT"})
        self.assertEqual(book.closed[-1]["reason"], "time_exit_72h")

    def test_zero_duration_is_unlimited_but_signal_exit_still_closes(self):
        policy = PortfolioPolicy(preferred_symbols=[])
        satellite = target("SOLUSDT")
        book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
        book.apply(plan(policy, [satellite], "open", max_hold_ms=0),
                   {"SOLUSDT": quote()}, T, "open")
        later = T + 20 * DAY
        book.apply(plan(policy, [satellite], "open", max_hold_ms=0),
                   {"SOLUSDT": quote()}, later, "open")
        self.assertIn("SOLUSDT", book.positions)
        book.apply(plan(policy, [satellite], "open", max_hold_ms=0,
                        exits={"SOLUSDT": "hourly_trend_exit"}),
                   {"SOLUSDT": quote()}, later + 1, "open")
        self.assertNotIn("SOLUSDT", book.positions)
        self.assertEqual(book.closed[-1]["reason"], "hourly_trend_exit")

    def test_retain_ignores_rank_removal_but_not_stop_cap_or_circuit_breaker(self):
        policy = PortfolioPolicy(preferred_symbols=[])
        for hazard in ("rank", "stop", "weight", "drawdown"):
            with self.subTest(hazard=hazard):
                book = FuturesBook(10_000, fee_bps=0, slippage_bps=0)
                satellite = target("SOLUSDT", atr=100)
                book.apply(plan(policy, [satellite], "open", max_hold_ms=0),
                           {"SOLUSDT": quote()}, T, "open")
                if hazard == "drawdown":
                    book.risk_peak = 20_000
                price = {"rank": 100, "stop": 85, "weight": 200,
                         "drawdown": 100}[hazard]
                original_qty = book.positions["SOLUSDT"]["quantity"]
                book.apply(plan(policy, [], "next", max_hold_ms=0, retain=True),
                           {"SOLUSDT": quote(price)}, T + 1, "next")
                if hazard == "rank":
                    self.assertEqual(book.positions["SOLUSDT"]["quantity"], original_qty)
                elif hazard == "weight":
                    self.assertLess(book.positions["SOLUSDT"]["quantity"], original_qty)
                    self.assertEqual(book.events[-1]["reason"], "policy_weight_cap")
                else:
                    self.assertNotIn("SOLUSDT", book.positions)
                    expected = "gap_stop" if hazard == "stop" else "portfolio_drawdown_exit"
                    self.assertEqual(book.closed[-1]["reason"], expected)


class StrategyRuleTests(unittest.TestCase):
    def test_rule_variants_do_not_mutate_source_or_preferred_signal(self):
        preferred = row("ZECUSDT", action="candidate")
        ordinary = row("SOLUSDT")
        ranking = [preferred, ordinary]
        pristine = copy.deepcopy(ranking)
        modified = apply_rules(ranking, CASES["four_hour_breakout"], ["ZECUSDT"])
        self.assertEqual(ranking, pristine)
        self.assertEqual(modified[0], preferred)
        self.assertIsNot(modified[1]["signal"], ordinary["signal"])
        self.assertEqual(modified[1]["signal"]["trigger_15m"], "closed_4h_breakout")

    def test_four_hour_breakout_uses_closed_four_hour_features(self):
        rules = StrategyRules(entry_mode="4h_breakout")
        no_breakout = row(close4=99, high4=100, close15=150)
        closed_breakout = row(close4=110, high4=105, close15=90)
        self.assertEqual(no_breakout["timeframes"]["4h"]["closed_at"], T - 1)
        self.assertEqual(apply_rules([no_breakout], rules)[0]["action"], "wait_4h_breakout")
        self.assertEqual(apply_rules([closed_breakout], rules)[0]["action"], "candidate")
        period = PERIODS["4h"]
        as_of = T // period * period
        history = []
        for i in range(80):
            opened = as_of - (80 - i) * period
            close = 100 + i
            history.append([opened, str(close - .2), str(close + .1),
                            str(close - .4), str(close), "100000",
                            opened + period - 1, "5000000"])
        baseline = features(history, "4h", as_of)
        current_unclosed = [as_of, "179", "1000000", "1", "999999",
                            "100000", as_of + period - 1, "999999999"]
        self.assertEqual(features(history + [current_unclosed], "4h", as_of), baseline)
        closed_breakout["timeframes"]["4h"] = baseline
        self.assertEqual(apply_rules([closed_breakout], rules)[0]["action"], "candidate")

    def test_four_hour_breakout_cannot_override_leveraged_underlying_review(self):
        reviewed = row("BTC3LUSDT", action="underlying_leverage_requires_review")
        result = apply_rules([reviewed], CASES["four_hour_breakout"])[0]
        self.assertEqual(result["action"], "underlying_leverage_requires_review")
        self.assertIsNone(result["signal"]["trigger_15m"])


if __name__ == "__main__":
    unittest.main()
