"""Research endpoints use only local report files and an ASGI test client."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.quant import api


class ResearchApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch_root = patch.object(api, "ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.app = FastAPI()
        self.app.include_router(api.router)

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def reports(self, rows=None):
        rows = rows if rows is not None else [
            {"window": "full", "strategy": "NFI8Long1x",
             "total_trades": 2, "results_per_pair": [{"pair": "ZEC"}],
             "exit_reason_summary": {"signal": 2}},
        ]
        self.write_json("reports/quant_v5/comparison.json", {"rows": rows})
        self.write_json("reports/quant_v5/strategy_protocol.json", {"version": 1})
        self.write_json("reports/quant_v5/selection_freeze.json", {"chosen": "NFI8Long1x"})

    async def get(self, path, params=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            return await client.get(path, params=params)

    async def test_research_is_summary_only_and_preserves_report(self):
        self.reports()
        response = await self.get("/api/quant/research")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["protocol"], {"version": 1})
        self.assertEqual(body["selection"], {"chosen": "NFI8Long1x"})
        self.assertNotIn("results_per_pair", body["rows"][0])
        self.assertNotIn("exit_reason_summary", body["rows"][0])
        persisted = json.loads((self.root / "reports/quant_v5/comparison.json").read_text())
        self.assertIn("results_per_pair", persisted["rows"][0])

    async def test_detail_paginates_orders_and_validates_bounds(self):
        self.reports()
        base = "reports/quant_v5/runs/full/NFI8Long1x"
        self.write_json(f"{base}/orders.json", [{"trade_id": i} for i in range(5)])
        self.write_json(f"{base}/equity_preview.json", [{"equity": 10000}])
        self.write_json(f"{base}/mark_metrics.json", {"drawdown": 0.1})
        params = {"window": "full", "strategy": "NFI8Long1x", "offset": 2, "limit": 2}
        response = await self.get("/api/quant/research/detail", params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "orders": [{"trade_id": 2}, {"trade_id": 3}],
            "total_orders": 5, "offset": 2,
            "curve": [{"equity": 10000}], "metrics": {"drawdown": 0.1},
        })
        params["offset"] = 9
        self.assertEqual((await self.get("/api/quant/research/detail", params)).json()["orders"], [])
        for invalid in ({"offset": -1}, {"limit": 0}, {"limit": 501}):
            with self.subTest(invalid=invalid):
                self.assertEqual((await self.get("/api/quant/research/detail", {
                    "window": "full", "strategy": "NFI8Long1x", **invalid,
                })).status_code, 422)

    async def test_unknown_run_and_path_traversal_are_rejected(self):
        self.reports()
        endpoint = "/api/quant/research/detail"
        for window, strategy in (("full", "Unknown"), ("../outside", "NFI8Long1x"),
                                 ("full", "../../outside")):
            with self.subTest(window=window, strategy=strategy):
                response = await self.get(endpoint, {"window": window, "strategy": strategy})
                self.assertEqual(response.status_code, 404)

        # Even a compromised comparison index cannot authorize reads outside runs/.
        self.reports([{"window": "..", "strategy": "outside"}])
        response = await self.get(endpoint, {"window": "..", "strategy": "outside"})
        self.assertEqual(response.status_code, 404)

    async def test_missing_report_is_unavailable(self):
        self.assertEqual((await self.get("/api/quant/research")).status_code, 503)
        self.assertEqual((await self.get("/api/quant/research/detail", {
            "window": "full", "strategy": "NFI8Long1x",
        })).status_code, 503)

    async def test_research_script_has_javascript_mime(self):
        script = self.root / "docs/quant_research.js"
        script.parent.mkdir(parents=True)
        script.write_text("window.quantResearch = true;", encoding="utf-8")
        response = await self.get("/api/quant/research.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/javascript")
        self.assertEqual(response.text, "window.quantResearch = true;")

    async def test_stop_details_are_isolated_from_original_study(self):
        self.reports()
        self.write_json("reports/quant_v6/comparison.json", {"rows": [{"window": "validation", "strategy": "A1Fixed"}]})
        base = "reports/quant_v6/runs/validation/A1Fixed"
        self.write_json(f"{base}/orders.json", [{"side": "buy"}, {"side": "sell"}])
        self.write_json(f"{base}/equity_preview.json", [])
        self.write_json(f"{base}/mark_metrics.json", {"reconciled": True})
        params = {"study": "v6", "window": "validation", "strategy": "A1Fixed", "offset": 1}
        response = await self.get("/api/quant/research/detail", params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orders"], [{"side": "sell"}])
        self.assertEqual((await self.get("/api/quant/research/detail", {**params, "study": "../outside"})).status_code, 422)
        self.assertEqual((await self.get("/api/quant/research/detail", {**params, "study": "v5"})).status_code, 404)

    async def test_forward_status_does_not_treat_old_snapshot_as_running_evidence(self):
        response = await self.get("/api/quant/research/forward")
        self.assertEqual(response.json()["state"], "not_started")
        self.write_json("reports/quant_v6/forward/status.json", {"updated_ms": 1, "accounts": [], "live_enabled": False})
        self.write_json("reports/quant_v6/forward/protocol.json", {"assessment": "30 days"})
        response = await self.get("/api/quant/research/forward")
        self.assertTrue(response.json()["status_stale"])
        self.assertFalse(response.json()["live_enabled"])

    async def test_holding_reference_details_use_only_known_reference_directory(self):
        self.write_json("reports/quant_v7/comparison.json", {"rows": [
            {"window": "reused_holdout", "strategy": "A1Fixed", "origin": "v6_frozen_reference"}]})
        base = "reports/quant_v7/reference_runs/reused_holdout/A1Fixed"
        self.write_json(f"{base}/orders.json", [{"side": "sell", "reason": "hourly"}])
        self.write_json(f"{base}/equity_preview.json", [])
        self.write_json(f"{base}/mark_metrics.json", {"return_pct": 26.83})
        params = {"study": "v7", "window": "reused_holdout", "strategy": "A1Fixed"}
        response = await self.get("/api/quant/research/detail", params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orders"][0]["reason"], "hourly")
        self.write_json("reports/quant_v7/comparison.json", {"rows": [
            {"window": "..", "strategy": "outside", "origin": "v6_frozen_reference"}]})
        response = await self.get("/api/quant/research/detail", {"study": "v7", "window": "..", "strategy": "outside"})
        self.assertEqual(response.status_code, 404)

    async def test_cross_study_is_included_and_exposes_only_reduction_snapshots(self):
        self.write_json("reports/quant_v7/comparison.json", {"rows": []})
        self.write_json("reports/quant_v10/comparison.json", {"rows": [
            {"study": "v10", "window": "full", "strategy": "CrossFlex", "artifacts": {"private": "hash"}}]})
        base = "reports/quant_v10/runs/full/CrossFlex"
        self.write_json(f"{base}/orders.json", [{"side": "sell"}])
        self.write_json(f"{base}/equity_preview.json", [])
        self.write_json(f"{base}/mark_metrics.json", {"risk_model_passed": True})
        self.write_json(f"{base}/risk_snapshots.json", [
            {"reason": "known_open_after_actions"}, {"reason": "before_reduce"}, {"reason": "after_reduce"}])
        response = await self.get("/api/quant/research/holding")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["v10_runs"], 1)
        self.assertNotIn("artifacts", response.json()["rows"][0])
        params = {"study": "v10", "window": "full", "strategy": "CrossFlex"}
        response = await self.get("/api/quant/research/detail", params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["risk_reductions"], [{"reason": "before_reduce"}, {"reason": "after_reduce"}])
        self.assertEqual((await self.get("/api/quant/research/detail", {**params, "study": "v100"})).status_code, 422)

    async def test_overlay_details_include_monthly_attribution_and_selection(self):
        self.write_json("reports/quant_v7/comparison.json", {"rows": []})
        self.write_json("reports/quant_v11/comparison.json", {"rows": [
            {"study":"v11","window":"full","strategy":"Enhance40Slow"}],
            "selection":{"selected":"Enhance40Slow"}})
        base="reports/quant_v11/runs/full/Enhance40Slow"
        for filename,value in (("orders",[]),("equity_preview",[]),("mark_metrics",{"core_preserved_until_terminal":True}),
                               ("risk_snapshots",[]),("monthly_returns",[{"month":"2026-01","return_pct":-2}])):
            self.write_json(f"{base}/{filename}.json",value)
        response=await self.get("/api/quant/research/holding")
        self.assertEqual(response.json()["overlay_selection"]["selected"],"Enhance40Slow")
        response=await self.get("/api/quant/research/detail",{"study":"v11","window":"full","strategy":"Enhance40Slow"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["monthly_returns"][0]["return_pct"],-2)

    async def test_expanded_study_exposes_candidate_evidence_and_matching_seed_details(self):
        self.write_json("reports/quant_v7/comparison.json", {"rows": []})
        self.write_json("reports/quant_v12/universe_freeze.json", {"symbols": ["UNIUSDT", "SOLUSDT"]})
        self.write_json("reports/quant_v12/fundamental_sources.json", {"checked_date": "2026-09-26"})
        # Candidate evidence is readable before completed comparisons exist.
        response = await self.get("/api/quant/research/holding")
        self.assertEqual(response.json()["expansion_universe_freeze"]["symbols"], ["UNIUSDT", "SOLUSDT"])
        self.assertNotIn("expansion_selection", response.json())
        self.write_json("reports/quant_v12/comparison.json", {"rows": [
            {"study": "v12", "window": "full", "strategy": "AnchorEnhance", "artifacts": {"private": "hash"}}],
            "selection": {"candidates": [], "selected": None, "execution_changed": False}})
        base = "reports/quant_v12/runs/full/AnchorEnhance"
        for name, value in (("orders", []), ("equity_preview", []), ("mark_metrics", {}),
                            ("risk_snapshots", []), ("monthly_returns", []),
                            ("seed_eligibility", {"UNIUSDT": {"decision": "past_volume_below_10m_keep_slot_cash"}})):
            self.write_json(f"{base}/{name}.json", value)
        response = await self.get("/api/quant/research/holding")
        self.assertEqual(response.json()["v12_runs"], 1)
        self.assertFalse(response.json()["expansion_selection"]["execution_changed"])
        self.assertNotIn("artifacts", response.json()["rows"][0])
        response = await self.get("/api/quant/research/detail", {
            "study": "v12", "window": "full", "strategy": "AnchorEnhance"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["seed_eligibility"]["UNIUSDT"]["decision"], "past_volume_below_10m_keep_slot_cash")


if __name__ == "__main__":
    unittest.main()
