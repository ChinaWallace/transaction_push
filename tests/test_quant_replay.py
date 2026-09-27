"""Causal futures replay checks using a tiny synthetic exchange history."""

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.advisory.engine import DAY
from app.quant.futures_replay import prepare, run


ROOT = Path(__file__).resolve().parents[1]
START = 1_767_225_600_000  # 2026-01-01 UTC
SYMBOL = "ZECUSDT"


def bar(opened, price, *, high=None, low=None, close=None):
    high = price * 1.02 if high is None else high
    low = price * 0.98 if low is None else low
    close = price if close is None else close
    return [opened, str(price), str(high), str(low), str(close), "100000",
            opened + DAY - 1, "10000000"]


def day(opened, *, high=120, low=90, close=100, funding=()):
    return {
        "time": opened,
        "ranking": [{"symbol": SYMBOL}],
        "bars": {SYMBOL: bar(opened, 100, high=high, low=low, close=close)},
        "funding": list(funding),
    }


def target_plan(*_args, **_kwargs):
    return {"targets": [{"symbol": SYMBOL, "weight": 0.2, "leverage": 1,
                          "stop_price": 80, "entry_zone": [95, 105], "atr": 4}]}


class SyntheticReplayTests(unittest.TestCase):
    def test_future_ohlc_does_not_change_earlier_cross_section(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            funding_dir = Path(temporary) / "funding"
            (data / "klines").mkdir(parents=True)
            funding_dir.mkdir()
            spec = {"symbols": [{"symbol": SYMBOL, "baseAsset": "ZEC", "quoteAsset": "USDT",
                                  "status": "TRADING", "contractType": "PERPETUAL",
                                  "underlyingType": "COIN", "onboardDate": START - 90 * DAY}]}
            (data / "exchange_info.json").write_text(json.dumps(spec))
            (data / "history_request.json").write_text(json.dumps({"symbols": [SYMBOL]}))
            rows = [bar(START + i * DAY, 100 * 1.005 ** (i + 30)) for i in range(-30, 2)]
            history_path = data / "klines" / f"{SYMBOL}.json"
            history_path.write_text(json.dumps({"rows": rows}))
            interval = 8 * 60 * 60 * 1000
            rates = [{"fundingTime": at, "fundingRate": "0", "markPrice": "100"}
                     for at in range(START - DAY, START + 2 * DAY, interval)]
            (funding_dir / f"{SYMBOL}.json").write_text(json.dumps({
                "validation": {"complete": True, "errors": []}, "rates": rates,
            }))
            with patch("app.quant.futures_replay.START", START), \
                 patch("app.quant.futures_replay.END", START + 2 * DAY):
                baseline, coverage = prepare(data, funding_dir, progress=lambda _: None)
                self.assertEqual(coverage["funding_complete_symbols"], 1)
                changed = json.loads(history_path.read_text())
                changed["rows"][-2][2] = "260"
                changed["rows"][-2][3] = "90"
                changed["rows"][-2][4] = "250"
                history_path.write_text(json.dumps(changed))
                altered, _ = prepare(data, funding_dir, progress=lambda _: None)
            self.assertEqual(len(baseline), 2)
            self.assertEqual(baseline[0]["ranking"], altered[0]["ranking"])
            self.assertNotEqual(
                baseline[1]["ranking"][0]["features"]["close"],
                altered[1]["ranking"][0]["features"]["close"],
            )

    def test_unheld_zero_mark_funding_is_ignored_and_final_account_is_flat(self):
        unheld_event = ("ETHUSDT", {"fundingTime": START + 8 * 60 * 60 * 1000,
                                     "fundingRate": "0.01", "markPrice": "0"})
        held_event = (SYMBOL, {"fundingTime": START + 8 * 60 * 60 * 1000,
                               "fundingRate": "0", "markPrice": "100"})
        with patch("app.quant.futures_replay.target_portfolio", side_effect=target_plan):
            baseline = run([day(START)], fee_bps=0, slippage_bps=0)
            with_funding = run([day(START, funding=(unheld_event, held_event))],
                               fee_bps=0, slippage_bps=0)
        self.assertEqual(with_funding["funding_net_paid"], 0)
        self.assertEqual(with_funding["return_pct"], baseline["return_pct"])
        self.assertEqual(with_funding["round_trips"], 1)
        final = with_funding["curve"][-1]
        self.assertEqual(final["positions"], 0)
        self.assertEqual(final["gross_pct"], 0)
        self.assertEqual(final["margin"], 0)
        self.assertAlmostEqual(final["wallet"], final["equity"])
        self.assertAlmostEqual(final["equity"], with_funding["final_equity"])

    def test_intraday_stress_counts_high_to_low_drawdown(self):
        with patch("app.quant.futures_replay.target_portfolio", side_effect=target_plan):
            modest_high = run([day(START, high=110)], fee_bps=0, slippage_bps=0)
            large_high = run([day(START, high=150)], fee_bps=0, slippage_bps=0)
        self.assertGreater(large_high["intraday_stress_drawdown_pct"],
                           modest_high["intraday_stress_drawdown_pct"])
        self.assertGreater(large_high["intraday_stress_drawdown_pct"], 10)


class RouteWiringAstTests(unittest.TestCase):
    def test_main_registers_quant_and_preserves_core_default_analysis_route(self):
        main = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
        imports = [node for node in main.body if isinstance(node, ast.ImportFrom)]
        self.assertTrue(any(node.module == "app.quant.api" and
                            any(alias.name == "router" and alias.asname == "quant_contracts_router"
                                for alias in node.names) for node in imports))
        create = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
        registered = {call.args[0].id for call in ast.walk(create)
                      if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                      and call.func.attr == "include_router" and call.args
                      and isinstance(call.args[0], ast.Name)}
        self.assertIn("quant_contracts_router", registered)
        self.assertIn("core_trading_router", registered)

        core = ast.parse((ROOT / "app" / "api" / "core_trading.py").read_text(encoding="utf-8-sig"))
        request = next(node for node in core.body if isinstance(node, ast.ClassDef)
                       and node.name == "TradingAnalysisRequest")
        default = next(node.value for node in request.body if isinstance(node, ast.AnnAssign)
                       and isinstance(node.target, ast.Name) and node.target.id == "analysis_type")
        self.assertTrue(any(keyword.arg == "default" and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value == "integrated" for keyword in default.keywords))
        self.assertTrue(any(isinstance(node, ast.AsyncFunctionDef) and node.name == "analyze_trading_signal"
                            for node in core.body))


if __name__ == "__main__":
    unittest.main()
