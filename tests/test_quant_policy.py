"""Core/satellite paper-policy invariants with synthetic quotes only."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from app.advisory.engine import DAY
from app.core.runtime_config import RuntimeSettings
from app.quant.api import app
from app.quant.futures_book import FuturesBook
from app.quant.permissions import check_permissions
from app.quant.policy import PortfolioPolicy, candidate_pool, load_policy


T = 1_780_000_000_000
VERSION = "contracts-v4.0-mtf"


def quote(price=100):
    return {"bid": price, "ask": price, "mark": price}


def target(symbol, weight=.01, *, core=False, leverage=2, stop=90, atr=2):
    return {"symbol": symbol, "weight": weight, "leverage": 1 if core else leverage,
            "stop_price": 0 if core else stop, "entry_zone": [95, 105], "atr": atr,
            "holding_policy": "core" if core else "satellite",
            "stop_mode": "none" if core else "atr"}


def plan(policy, targets, signal, *, exit_signals=None, max_hold_ms=72 * 3_600_000):
    return {"version": VERSION, "signal_id": signal,
            "execution_policy": "multiframe_rotation", "strategy_schema": 4,
            "targets": targets, "policy": policy.model_dump(), "max_positions": policy.max_positions,
            "margin_limit": .85, "core_drawdown_exempt": True,
            "entry_allowed_symbols": [t["symbol"] for t in targets],
            "signal_expires_at": T + 100 * DAY, "max_hold_ms": max_hold_ms,
            "exit_signals": exit_signals or {}, "protective_updates": {},
            "position_risk_budget": .025}


class FakePermissionClient:
    """Only GET is available; any order-capable HTTP method fails the test."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, path, **kwargs):
        self.requests.append((path, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, *_args, **_kwargs):
        raise AssertionError("Permission probe must not send an order")


class PortfolioPolicyTests(unittest.TestCase):
    def test_defaults_normalization_capacity_and_validation(self):
        policy = PortfolioPolicy(preferred_symbols="zec, BTCUSDT,zec, eth")
        self.assertEqual(policy.preferred_symbols, ["ZECUSDT", "BTCUSDT", "ETHUSDT"])
        self.assertEqual((policy.candidate_limit, policy.max_positions), (50, 50))
        self.assertEqual((policy.core_single_weight, policy.core_total_weight,
                          policy.satellite_single_weight), (.7, .7, .1))
        self.assertEqual(policy.core_stop_mode, "none")
        for override in ({"candidate_limit": 51}, {"max_positions": 51},
                         {"max_positions": 2}, {"core_single_weight": .71},
                         {"core_total_weight": .71}, {"satellite_single_weight": .11},
                         {"preferred_symbols": ["BAD/USDT"]}):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                PortfolioPolicy(**override)

    def test_file_override_is_loaded_and_revision_changes(self):
        defaults = PortfolioPolicy()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            settings = SimpleNamespace(**{"quant_" + name: getattr(defaults, name)
                                          for name in PortfolioPolicy.model_fields}, quant_output_dir=output)
            (output / "portfolio_policy.json").write_text(json.dumps({"overrides": {
                "preferred_symbols": "zec,sol", "core_stop_mode": "wide"}}))
            loaded = load_policy(settings)
            self.assertEqual(loaded.preferred_symbols, ["ZECUSDT", "SOLUSDT"])
            self.assertEqual(loaded.core_stop_mode, "wide")
            self.assertNotEqual(loaded.revision(), defaults.revision())
            self.assertEqual(load_policy(settings).revision(), loaded.revision())

    def test_candidate_pool_includes_preferred_then_caps_at_50(self):
        policy = PortfolioPolicy()
        ranking = [{"symbol": f"C{i:03}USDT", "rejections": [], "signal": {}}
                   for i in range(55)]
        ranking += [{"symbol": s, "rejections": ["waiting"], "signal": {}}
                    for s in policy.preferred_symbols]
        selected = candidate_pool(ranking, policy)
        self.assertEqual(len(selected), 50)
        self.assertEqual([r["symbol"] for r in selected[:3]], policy.preferred_symbols)
        self.assertEqual(len({r["symbol"] for r in selected}), 50)


class PermissionProbeTests(unittest.TestCase):
    def setUp(self):
        self.key = "FAKE_KEY_SENTINEL"
        self.secret = "FAKE_SECRET_SENTINEL"
        self.settings = RuntimeSettings(_env_file=None, binance_api_key=self.key,
                                        binance_secret_key=self.secret)

    def test_success_exposes_only_allowlisted_boolean_permissions(self):
        client = FakePermissionClient([
            httpx.Response(200, json={"serverTime": T}),
            httpx.Response(200, json={"enableReading": True, "enableFutures": False,
                                      "ipRestrict": True, "canTrade": True,
                                      "balances": [{"asset": "USDT", "free": "1000"}],
                                      "apiKey": self.key}),
        ])
        with patch("app.quant.permissions.httpx.Client", return_value=client) as make_client:
            result = check_permissions(self.settings)
        self.assertTrue(result["verified"])
        self.assertFalse(result["orders_sent"])
        self.assertEqual(result["permissions"], {
            "ipRestrict": True, "enableReading": True, "enableFutures": False})
        self.assertEqual([path for path, _ in client.requests],
                         ["/api/v3/time", "/sapi/v1/account/apiRestrictions"])
        self.assertEqual(client.requests[1][1]["headers"]["X-MBX-APIKEY"], self.key)
        self.assertNotIn(self.key, json.dumps(result))
        self.assertNotIn(self.secret, json.dumps(result))
        self.assertNotIn("balances", json.dumps(result))
        self.assertFalse(make_client.call_args.kwargs["trust_env"])

    def test_sapi_and_futures_minus_2015_stay_unknown_with_get_only(self):
        client = FakePermissionClient([
            httpx.Response(200, json={"serverTime": T}),
            httpx.Response(401, json={"code": -2015, "msg": "Invalid API key"}),
            httpx.Response(200, json={"serverTime": T + 1}),
            httpx.Response(401, json={"code": -2015, "msg": "Invalid API key"}),
        ])
        with patch("app.quant.permissions.httpx.Client", return_value=client):
            result = check_permissions(self.settings)
        self.assertFalse(result["verified"])
        self.assertEqual(result["error_code"], -2015)
        self.assertEqual(result["futures_authentication"], {
            "verified": False, "http_status": 401, "error_code": -2015})
        self.assertNotIn("permissions", result)
        self.assertEqual([path for path, _ in client.requests], [
            "/api/v3/time", "/sapi/v1/account/apiRestrictions",
            "https://fapi.binance.com/fapi/v1/time",
            "https://fapi.binance.com/fapi/v3/account"])
        self.assertNotIn(self.secret, json.dumps(result))

    def test_exception_text_is_redacted_and_live_mode_rejected(self):
        client = FakePermissionClient([RuntimeError("transport failed " + self.secret)])
        with patch("app.quant.permissions.httpx.Client", return_value=client):
            result = check_permissions(self.settings)
        self.assertEqual(result["error"], "permission_lookup_failed")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertNotIn(self.secret, json.dumps(result))
        with self.assertRaises(ValidationError):
            RuntimeSettings(_env_file=None, quant_execution_mode="live")


class CoreSatelliteBookTests(unittest.TestCase):
    def test_core_can_use_more_than_25_percent_but_combined_entry_budget_stays_70(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT", "BTCUSDT"], core_allow_weight_drift=True)
        book = FuturesBook()
        targets = [target("ZECUSDT", .6, core=True), target("BTCUSDT", .6, core=True)]
        book.apply(plan(policy, targets, "open"), {"ZECUSDT": quote(), "BTCUSDT": quote()}, T, "open")
        self.assertGreater(book.positions["ZECUSDT"]["quantity"] * 100 / book.equity(), .59)
        self.assertLessEqual(book.gross() / book.equity(), .700001)
        self.assertEqual(book.positions["ZECUSDT"]["leverage"], 1)

    def test_actual_fills_reach_50_positions_and_reject_51st(self):
        policy = PortfolioPolicy(preferred_symbols=[])
        symbols = [f"C{i:03}USDT" for i in range(51)]
        targets = [target(s, .005) for s in symbols[:50]]
        book = FuturesBook(100_000)
        quotes = {s: quote() for s in symbols}
        self.assertEqual(book.apply(plan(policy, targets, "first"), quotes, T, "first"), "applied")
        self.assertEqual(len(book.positions), 50)
        self.assertEqual(sum(e["side"] == "buy" for e in book.events), 50)
        book.add(target(symbols[50], .005), 100, 100, T + 1)
        self.assertEqual(len(book.positions), 50)
        self.assertNotIn(symbols[50], book.positions)

    def test_core_ignores_trend_time_rank_and_atr_trailing_while_satellite_exits(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        core = target("ZECUSDT", .2, core=True)
        satellite = target("SOLUSDT", .1)
        book = FuturesBook()
        quotes = {"ZECUSDT": quote(), "SOLUSDT": quote()}
        book.apply(plan(policy, [core, satellite], "open"), quotes, T, "open")
        self.assertEqual(set(book.positions), set(quotes))
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 0)
        self.assertNotIn("trailing_atr", book.positions["ZECUSDT"])
        book.observe(T + 1, {"ZECUSDT": quote(150), "SOLUSDT": quote(100)})
        book.observe(T + 2, {"ZECUSDT": quote(105), "SOLUSDT": quote(100)})
        self.assertIn("ZECUSDT", book.positions)
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 0)
        expired = plan(policy, [core], "expired", exit_signals={"ZECUSDT": "hourly_trend_exit",
                                                             "SOLUSDT": "hourly_trend_exit"})
        book.apply(expired, {"ZECUSDT": quote(105), "SOLUSDT": quote(100)},
                   T + 73 * 3_600_000, "expired")
        self.assertIn("ZECUSDT", book.positions)
        self.assertNotIn("SOLUSDT", book.positions)
        self.assertTrue(any(e["symbol"] == "SOLUSDT" and e["reason"] == "time_exit_72h"
                            for e in book.events if e["side"] == "sell"))

    def test_drawdown_sells_satellite_only_and_starts_28_day_pause(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        book = FuturesBook()
        quotes = {"ZECUSDT": quote(), "SOLUSDT": quote()}
        book.apply(plan(policy, [target("ZECUSDT", .2, core=True),
                                 target("SOLUSDT", .1)], "open"), quotes, T, "open")
        self.assertEqual(set(book.positions), set(quotes))
        # Synthetic account-level loss; isolate the circuit break from coin stops.
        book.wallet = 5_000
        book.observe(T + 1, quotes)
        self.assertIn("ZECUSDT", book.positions)
        self.assertNotIn("SOLUSDT", book.positions)
        self.assertEqual(book.pause_until, T + 1 + 28 * DAY)
        self.assertTrue(any(e["reason"] == "portfolio_drawdown_exit" and e["symbol"] == "SOLUSDT"
                            for e in book.events if e["side"] == "sell"))

    def test_core_appreciation_trims_weight_without_automatic_refill(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"], core_single_weight=.25)
        book = FuturesBook(100_000)
        core = target("ZECUSDT", .2, core=True)
        book.apply(plan(policy, [core], "open"), {"ZECUSDT": quote()}, T, "open")
        initial_quantity = book.positions["ZECUSDT"]["quantity"]
        book.apply(plan(policy, [target("ZECUSDT", .25, core=True)], "rise"),
                   {"ZECUSDT": quote(150)}, T + 1, "rise")
        self.assertLess(book.positions["ZECUSDT"]["quantity"], initial_quantity)
        self.assertLessEqual(book.positions["ZECUSDT"]["quantity"] * 150,
                             .25 * book.equity() + .01)
        self.assertTrue(any(e["reason"] == "policy_weight_cap" for e in book.events
                            if e["side"] == "sell"))
        buys = sum(e["side"] == "buy" for e in book.events)
        book.apply(plan(policy, [target("ZECUSDT", .25, core=True)], "hold"),
                   {"ZECUSDT": quote(150)}, T + 2, "hold")
        self.assertEqual(sum(e["side"] == "buy" for e in book.events), buys)

    def test_authorized_core_drift_preserves_winner_but_not_satellite_caps(self):
        policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"], core_allow_weight_drift=True)
        book = FuturesBook(100_000)
        core = target("ZECUSDT", .25, core=True)
        quotes = {"ZECUSDT": quote(), "SOLUSDT": quote()}
        book.apply(plan(policy, [core, target("SOLUSDT", .1)], "open"), quotes, T, "open")
        quantity = book.positions["ZECUSDT"]["quantity"]
        # No plan sell, including when the winner now exceeds 70% of equity.
        book.apply(plan(policy, [core], "rise"),
                   {"ZECUSDT": quote(2000), "SOLUSDT": quote(1000)}, T + 1, "rise")
        self.assertEqual(book.positions["ZECUSDT"]["quantity"], quantity)
        self.assertGreater(quantity * 2000 / book.equity(), .7)
        self.assertFalse(any(e.get("side") == "sell" and e["symbol"] == "ZECUSDT" for e in book.events))
        self.assertTrue(any(e.get("reason") == "policy_weight_cap" and e["symbol"] == "SOLUSDT" for e in book.events))
        buys = sum(e["side"] == "buy" for e in book.events)
        book.add(core, 1000, 1000, T + 2)
        self.assertEqual(sum(e["side"] == "buy" for e in book.events), buys)

    def test_core_and_satellite_actual_fill_caps_and_no_core_auto_add(self):
        policy = PortfolioPolicy(preferred_symbols=[f"C{i}USDT" for i in range(4)], core_single_weight=.25)
        core_targets = [target(s, .25, core=True) for s in policy.preferred_symbols]
        sat = target("SOLUSDT", .2, leverage=3)
        book = FuturesBook(100_000)
        quotes = {s: quote() for s in [*policy.preferred_symbols, "SOLUSDT"]}
        book.apply(plan(policy, [*core_targets, sat], "open"), quotes, T, "open")
        # The fourth core order may be rejected once the 70% aggregate is full.
        self.assertEqual(len(book.positions), 4)
        self.assertEqual(len(set(book.positions) & set(policy.preferred_symbols)), 3)
        eq = book.equity()
        core_notional = sum(book.positions[s]["quantity"] * book.marks[s]
                            for s in policy.preferred_symbols if s in book.positions)
        self.assertLessEqual(core_notional, .7 * eq + .01)
        for s in policy.preferred_symbols:
            if s not in book.positions:
                continue
            position = book.positions[s]
            self.assertEqual(position["leverage"], 1)
            self.assertEqual(position["stop"], 0)
            self.assertLessEqual(position["quantity"] * book.marks[s], .25 * eq + .01)
        self.assertLessEqual(book.positions["SOLUSDT"]["quantity"] * 100, .1 * eq + .01)
        self.assertLessEqual(book.margin(), .85 * eq + .01)
        with self.assertRaises(ValueError):
            book.add(target("C0USDT", .2, core=True) | {"leverage": 2}, 100, 100, T + 1)
        with self.assertRaises(ValueError):
            book.add(target("SOLUSDT", .1, leverage=4), 100, 100, T + 1)
        held_core = {s: book.positions[s]["quantity"] for s in policy.preferred_symbols
                     if s in book.positions}
        buy_counts = {s: sum(e["side"] == "buy" and e["symbol"] == s for e in book.events)
                      for s in held_core}
        book.apply(plan(policy, core_targets, "again"), quotes, T + 1, "again")
        for s, quantity in held_core.items():
            self.assertLessEqual(book.positions[s]["quantity"], quantity)
            self.assertEqual(sum(e["side"] == "buy" and e["symbol"] == s
                                 for e in book.events), buy_counts[s])

    def test_existing_2x_satellite_exits_before_preferred_1x_core_entry(self):
        ordinary = PortfolioPolicy(preferred_symbols=[])
        preferred = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        book = FuturesBook()
        book.apply(plan(ordinary, [target("ZECUSDT", .1, leverage=2)], "ordinary"),
                   {"ZECUSDT": quote()}, T, "ordinary")
        self.assertEqual(book.positions["ZECUSDT"]["leverage"], 2)
        desired = target("ZECUSDT", .2, core=True) | {"entry_zone": [105, 110]}
        book.apply(plan(preferred, [desired], "preferred"),
                   {"ZECUSDT": quote()}, T + 1, "preferred")
        self.assertNotIn("ZECUSDT", book.positions)
        self.assertTrue(any(e["side"] == "sell" and e["reason"] == "core_leverage_migration_exit"
                            for e in book.events))
        book.apply(plan(preferred, [desired], "preferred"),
                   {"ZECUSDT": quote(107)}, T + 2, "preferred")
        self.assertEqual(book.positions["ZECUSDT"]["leverage"], 1)
        self.assertEqual(book.positions["ZECUSDT"]["holding_policy"], "core")

    def test_incomplete_research_still_demotes_removed_core_and_restores_stop(self):
        preferred = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        ordinary = PortfolioPolicy(preferred_symbols=[])
        book = FuturesBook()
        book.apply(plan(preferred, [target("ZECUSDT", .2, core=True)], "open"),
                   {"ZECUSDT": quote()}, T, "open")
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 0)
        result = book.apply(plan(ordinary, [target("ZECUSDT", .1)], "incomplete"),
                            {"ZECUSDT": quote()}, T + 1, "incomplete", complete=False)
        self.assertEqual(result, "incomplete_research")
        position = book.positions["ZECUSDT"]
        self.assertEqual(position["holding_policy"], "satellite")
        self.assertFalse(position["drawdown_exempt"])
        self.assertGreater(position["stop"], 0)
        book.observe(T + 2, {"ZECUSDT": quote(85)})
        self.assertNotIn("ZECUSDT", book.positions)

    def test_removing_preference_after_restore_restores_satellite_stop_and_exit(self):
        core_policy = PortfolioPolicy(preferred_symbols=["ZECUSDT"])
        book = FuturesBook()
        book.apply(plan(core_policy, [target("ZECUSDT", .2, core=True)], "core"),
                   {"ZECUSDT": quote()}, T, "core")
        self.assertEqual(book.positions["ZECUSDT"]["stop"], 0)
        restored = FuturesBook.restore(json.loads(json.dumps(book.dump())))
        self.assertEqual(restored.positions["ZECUSDT"]["holding_policy"], "core")
        plain_policy = PortfolioPolicy(preferred_symbols=[])
        restored.apply(plan(plain_policy, [target("ZECUSDT", .1)], "ordinary"),
                       {"ZECUSDT": quote()}, T + 1, "ordinary")
        position = restored.positions["ZECUSDT"]
        self.assertEqual(position["holding_policy"], "satellite")
        self.assertFalse(position["drawdown_exempt"])
        self.assertGreater(position["stop"], 0)
        restored.apply(plan(plain_policy, [], "rank-exit"),
                       {"ZECUSDT": quote()}, T + 2, "rank-exit")
        self.assertNotIn("ZECUSDT", restored.positions)
        self.assertTrue(any(e["reason"] == "trend_or_rank_exit" and e["symbol"] == "ZECUSDT"
                            for e in restored.events if e["side"] == "sell"))


class PortfolioPolicyApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_update_requires_local_same_origin_header_and_json(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app.state.settings, "quant_output_dir", Path(directory)):
            (Path(directory) / "latest.json").write_text(json.dumps({"ranking": [
                {"symbol": s} for s in ("ZECUSDT", "BTCUSDT", "ETHUSDT")]}))
            local = httpx.ASGITransport(app=app, client=("127.0.0.1", 123))
            remote = httpx.ASGITransport(app=app, client=("10.0.0.2", 123))
            async with httpx.AsyncClient(transport=local, base_url="http://127.0.0.1") as client:
                current = (await client.get("/api/quant/policy")).json()
                payload = {"revision": current["revision"], "policy": current["policy"]}
                self.assertEqual((await client.put("/api/quant/policy", json=payload)).status_code, 403)
                self.assertEqual((await client.put("/api/quant/policy", json=payload,
                    headers={"X-Quant-Paper": "1", "Origin": "https://other.example"})).status_code, 403)
                self.assertEqual((await client.put("/api/quant/policy", content=json.dumps(payload),
                    headers={"X-Quant-Paper": "1", "Content-Type": "text/plain"})).status_code, 422)
            async with httpx.AsyncClient(transport=remote, base_url="http://127.0.0.1") as client:
                self.assertEqual((await client.put("/api/quant/policy", json=payload,
                    headers={"X-Quant-Paper": "1"})).status_code, 403)
            async with httpx.AsyncClient(transport=local, base_url="http://example.org") as client:
                self.assertEqual((await client.put("/api/quant/policy", json=payload,
                    headers={"X-Quant-Paper": "1"})).status_code, 403)
            self.assertFalse((Path(directory) / "portfolio_policy.json").exists())

    async def test_policy_update_validates_catalog_schema_and_cas_revision(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app.state.settings, "quant_output_dir", Path(directory)):
            output = Path(directory)
            (output / "latest.json").write_text(json.dumps({"ranking": [
                {"symbol": s} for s in ("ZECUSDT", "BTCUSDT", "ETHUSDT")]}))
            local = httpx.ASGITransport(app=app, client=("127.0.0.1", 123))
            async with httpx.AsyncClient(transport=local, base_url="http://127.0.0.1") as client:
                current = (await client.get("/api/quant/policy")).json()
                original = current["policy"]
                headers = {"X-Quant-Paper": "1", "Origin": "http://127.0.0.1"}
                bad = dict(original, preferred_symbols=["UNKNOWNUSDT"])
                self.assertEqual((await client.put("/api/quant/policy", json={
                    "revision": current["revision"], "policy": bad}, headers=headers)).status_code, 422)
                bad = dict(original, max_positions=51)
                self.assertEqual((await client.put("/api/quant/policy", json={
                    "revision": current["revision"], "policy": bad}, headers=headers)).status_code, 422)
                new = dict(original, preferred_symbols=["ZECUSDT"])
                saved = await client.put("/api/quant/policy", json={
                    "revision": current["revision"], "policy": new}, headers=headers)
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json()["policy"]["preferred_symbols"], ["ZECUSDT"])
                self.assertNotEqual(saved.json()["revision"], current["revision"])
                self.assertTrue((output / "portfolio_policy.json").exists())
                self.assertEqual((await client.put("/api/quant/policy", json={
                    "revision": current["revision"], "policy": new}, headers=headers)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
