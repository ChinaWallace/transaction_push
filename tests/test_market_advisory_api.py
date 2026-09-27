"""API verification with the project's FastAPI/httpx, no external calls."""

import unittest
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.advisory.api import app
from app.advisory.market import MarketDataError
from app.advisory.service import AdvisoryService


class AdvisoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)

    async def test_scan_returns_research_without_notification(self):
        report = {"status": "ok", "ranking": [{"symbol": "ZECUSDT", "win_probability": None}]}
        with patch("app.advisory.api.advisory_service.report", return_value=report) as scan:
            response = await self.request("/api/market-advisory/scan?watch=ZEC&top=30")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["ranking"][0]["win_probability"])
        scan.assert_called_once_with(["ZEC"], 30, "active")

    async def test_unavailable_data_does_not_return_success(self):
        with patch("app.advisory.api.advisory_service.report", return_value={"status": "unavailable", "ranking": []}):
            self.assertEqual((await self.request("/api/market-advisory/scan")).status_code, 503)

    async def test_exchange_errors_are_visible(self):
        with patch("app.advisory.api.advisory_service.report", side_effect=MarketDataError("HTTP 429")):
            response = await self.request("/api/market-advisory/scan")
        self.assertEqual(response.status_code, 503)
        self.assertIn("429", response.text)

    async def test_request_limits_and_bad_symbol(self):
        self.assertEqual((await self.request("/api/market-advisory/scan?top=151")).status_code, 422)
        self.assertEqual((await self.request("/api/market-advisory/scan?watch=ZEC-USDT-SWAP")).status_code, 422)
        query = "&".join("watch=ZEC" for _ in range(11))
        self.assertEqual((await self.request("/api/market-advisory/scan?"+query)).status_code, 422)

    async def test_paper_local_write_and_remote_rejection(self):
        result = {"simulation": True, "new_events": []}
        with patch("app.advisory.api.paper_cycle", return_value=({}, result)) as cycle:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1",123)),base_url="http://test") as client:
                response = await client.post("/api/market-advisory/paper/step?horizon=long_term")
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.json()["simulation"])
                self.assertEqual((await client.post("/api/market-advisory/paper/step",headers={"Origin":"https://external.example"})).status_code,403)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=("10.0.0.2",123)),base_url="http://test") as client:
                self.assertEqual((await client.post("/api/market-advisory/paper/step")).status_code,403)
            cycle.assert_called_once()


class CacheTests(unittest.TestCase):
    def test_cache_does_not_leak_mutation_or_cross_candle_boundary(self):
        service = AdvisoryService()
        with patch("app.advisory.service.time.time", return_value=14399), patch("app.advisory.service.refresh_quotes", side_effect=lambda r: r) as refresh, patch("app.advisory.service.scan_market", return_value={"ranking": []}) as scan:
            first = service.report()
            first["ranking"].append("modified")
            self.assertEqual(service.report()["ranking"], [])
            self.assertEqual(scan.call_count, 1)
            refresh.assert_called_once()
        with patch("app.advisory.service.time.time", return_value=14400), patch("app.advisory.service.scan_market", return_value={"ranking": []}) as scan:
            service.report()
            scan.assert_called_once()

    def test_busy_scan_fails_fast_instead_of_queueing_threads(self):
        service = AdvisoryService()
        service._lock.acquire()
        try:
            with self.assertRaisesRegex(MarketDataError, "in progress"):
                service.report()
        finally:
            service._lock.release()


class SummaryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Execute the actual bridge without importing legacy DB/ML dependencies."""

    async def test_disabled_notifications_are_not_reported_as_sent(self):
        source = Path(__file__).resolve().parents[1] / "app/services/trading/core_trading_service.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CoreTradingService")
        method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_market_advisory_push")
        module = ast.Module(body=[method], type_ignores=[])
        scope = {"asyncio": asyncio, "Dict": Dict, "Any": Any}
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), scope)
        self_object = SimpleNamespace(settings=SimpleNamespace(advisory_watchlist=["ZEC"], advisory_max_candidates=60),
                                      notification_service=SimpleNamespace(send_notification=AsyncMock(return_value={"disabled": True})),
                                      logger=Mock())
        report = {"ranking": [1], "analyzed_count": 1, "status": "ok", "as_of": "2026-09-24"}
        with patch("app.advisory.service.advisory_service.report", return_value=report), patch("app.advisory.market.notification_summary", return_value="summary"):
            result = await scope["run_market_advisory_push"](self_object)
        self.assertFalse(result["summary_report_sent"])
        self_object.notification_service.send_notification.assert_awaited_once_with("summary")

    async def test_empty_research_cannot_send_notification(self):
        source = Path(__file__).resolve().parents[1] / "app/services/trading/core_trading_service.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CoreTradingService")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_market_advisory_push")
        scope = {"asyncio": asyncio, "Dict": Dict, "Any": Any}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), "exec"), scope)
        notifier = AsyncMock()
        self_object = SimpleNamespace(settings=SimpleNamespace(advisory_watchlist=["ZEC"], advisory_max_candidates=60),
                                      notification_service=SimpleNamespace(send_notification=notifier), logger=Mock())
        with patch("app.advisory.service.advisory_service.report", return_value={"ranking": [], "data_errors": {"ZEC": "stale"}}):
            result = await scope["run_market_advisory_push"](self_object)
        self.assertFalse(result["success"])
        notifier.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
