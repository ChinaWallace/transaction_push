"""Deterministic gates for the frozen stop-comparison research selection."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_stop_comparison as selection  # noqa: E402


CASES = ("development", "validation", "validation_double_cost")
CHALLENGES = (
    "reused_holdout", "reused_holdout_double_cost",
    "challenge2025", "challenge2025_double_cost",
)


def protocol(strategies, max_retained=3):
    return {
        "strategies": strategies,
        "families": {"D55": "Donchian55", "E4": "EMA4h",
                     "A1": "ADXBreakout1h", "M4": "MTFFourHourExit"},
        "max_retained": max_retained,
        "selection_rule": "frozen-test-rule",
        "sources": {"frozen.py": "sha256"},
        "promotion_rule": "historical gates only",
    }


def row(window, strategy, *, return_pct=5, drawdown=10, reconciled=True, trades=10):
    return {
        "window": window, "strategy": strategy, "total_trades": trades,
        "mark_metrics": {
            "return_pct": return_pct,
            "sampled_mark_drawdown_pct": drawdown,
            "reconciled": reconciled,
        },
    }


def selection_rows(strategies):
    return [row(window, strategy) for strategy in strategies for window in CASES]


class SelectTests(unittest.TestCase):
    def test_at_most_one_per_family_and_three_total(self):
        strategies = [
            "D55Legacy", "D55Wide", "E4Legacy", "E4Wide",
            "A1Legacy", "A1Wide", "M4Legacy", "M4Wide",
        ]
        rows = selection_rows(strategies)
        for item in rows:
            if item["strategy"].endswith("Wide"):
                item["mark_metrics"]["return_pct"] = 8
        selected = selection.select(rows, protocol(strategies))
        retained = selected["retained"]
        self.assertEqual(len(retained), 3)
        self.assertEqual(len({item["family"] for item in retained}), 3)
        self.assertTrue(all(item["strategy"].endswith("Wide") for item in retained))
        self.assertEqual(selected["status"], "historical_screen_complete")
        self.assertEqual(selected["selection_windows"], list(CASES))

    def test_each_selection_window_rejects_bad_return_drawdown_or_accounting(self):
        baseline = selection_rows(["D55Legacy"])
        for window in CASES:
            for change in (
                {"return_pct": -0.01},
                {"drawdown": 35.01},
                {"reconciled": False},
            ):
                with self.subTest(window=window, change=change):
                    rows = [dict(item, mark_metrics=dict(item["mark_metrics"]))
                            for item in baseline]
                    item = next(item for item in rows if item["window"] == window)
                    if "return_pct" in change:
                        item["mark_metrics"]["return_pct"] = change["return_pct"]
                    if "drawdown" in change:
                        item["mark_metrics"]["sampled_mark_drawdown_pct"] = change["drawdown"]
                    if "reconciled" in change:
                        item["mark_metrics"]["reconciled"] = change["reconciled"]
                    selected = selection.select(rows, protocol(["D55Legacy"]))
                    self.assertEqual(selected["retained"], [])
                    self.assertFalse(selected["decisions"][0]["eligible"])
                    self.assertTrue(any(window in reason
                                        for reason in selected["decisions"][0]["rejections"]))

    def test_fewer_than_twelve_development_plus_validation_trades_is_rejected(self):
        rows = selection_rows(["E4Legacy"])
        for item in rows:
            item["total_trades"] = 5 if item["window"] == "development" else 6
        selected = selection.select(rows, protocol(["E4Legacy"]))
        self.assertEqual(selected["retained"], [])
        self.assertIn("fewer than12 combined development/validation trades",
                      selected["decisions"][0]["rejections"])

    def test_total_loss_is_rejected_without_aborting_other_candidates(self):
        strategies = ["D55Legacy", "E4Legacy"]
        rows = selection_rows(strategies)
        next(item for item in rows if item["strategy"] == "D55Legacy"
             and item["window"] == "development")["mark_metrics"]["return_pct"] = -100
        selected = selection.select(rows, protocol(strategies))
        self.assertEqual([item["strategy"] for item in selected["retained"]], ["E4Legacy"])
        self.assertFalse(next(item for item in selected["decisions"]
                              if item["strategy"] == "D55Legacy")["eligible"])

    def test_all_selection_cases_are_required_before_freezing(self):
        rows = selection_rows(["D55Legacy"])
        rows = [item for item in rows if item["window"] != "validation_double_cost"]
        with self.assertRaises(ValueError):
            selection.select(rows, protocol(["D55Legacy"]))

    def test_reused_holdout_and_challenge_returns_do_not_change_selection(self):
        strategies = ["D55Legacy", "E4Legacy"]
        rows = selection_rows(strategies)
        baseline = selection.select(rows, protocol(strategies))
        added = [row(window, strategy, return_pct=10_000 if strategy == "E4Legacy" else -99,
                     drawdown=0, reconciled=False, trades=1000)
                 for strategy in strategies for window in CHALLENGES]
        with_challenges = selection.select(rows + added, protocol(strategies))
        self.assertEqual(baseline["retained"], with_challenges["retained"])
        self.assertEqual(baseline["decisions"], with_challenges["decisions"])
        self.assertIn("challenge2025", with_challenges["not_used_for_selection"])
        self.assertIn("reused_holdout", with_challenges["not_used_for_selection"])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.rules = protocol(["D55Legacy"])
        self.base = selection_rows(["D55Legacy"])
        self.shortlist = selection.select(self.base, self.rules)

    def assert_research_only(self, registered):
        self.assertFalse(registered["live_enabled"])
        self.assertFalse(registered["paper_strategy_replaced"])
        self.assertEqual(registered["limit"], 3)
        self.assertEqual(len(registered["entries"]), 1)
        entry = registered["entries"][0]
        self.assertEqual(entry["execution"], "research_only")
        self.assertEqual(entry["forward_status"], "not_started")
        return entry

    def test_missing_challenge_gates_remain_waiting(self):
        entry = self.assert_research_only(selection.registry(self.base, self.shortlist, self.rules))
        self.assertEqual(entry["status"], "awaiting_challenge")
        self.assertEqual(entry["missing"], list(CHALLENGES))
        self.assertEqual(entry["failed"], [])

    def test_completed_failed_gate_rejects_historical_promotion(self):
        challenges = [row(window, "D55Legacy") for window in CHALLENGES]
        challenges[0]["mark_metrics"]["reconciled"] = False
        challenges[1]["total_trades"] = 9
        entry = self.assert_research_only(selection.registry(
            self.base + challenges, self.shortlist, self.rules))
        self.assertEqual(entry["status"], "historical_gates_failed")
        self.assertEqual(entry["missing"], [])
        self.assertEqual(entry["failed"], list(CHALLENGES[:2]))

    def test_completed_passing_gates_still_only_research(self):
        challenges = [row(window, "D55Legacy") for window in CHALLENGES]
        entry = self.assert_research_only(selection.registry(
            self.base + challenges, self.shortlist, self.rules))
        self.assertEqual(entry["status"], "historical_gates_passed")
        self.assertEqual(entry["missing"], [])
        self.assertEqual(entry["failed"], [])

    def test_failure_is_not_masked_by_another_missing_gate(self):
        failed = row("reused_holdout", "D55Legacy", return_pct=-1)
        entry = self.assert_research_only(selection.registry(
            self.base + [failed], self.shortlist, self.rules))
        self.assertEqual(entry["failed"], ["reused_holdout"])
        self.assertEqual(entry["status"], "historical_gates_failed")


if __name__ == "__main__":
    unittest.main()
