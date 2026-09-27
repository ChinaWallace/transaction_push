"""Data-integrity regression checks; no network, accounts or research writes."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("expanded", Path(__file__).resolve().parents[1] / "scripts/prepare_expanded_core_data.py")
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)


class ExpandedDataIntegrityTests(unittest.TestCase):
    def row(self, close="100"):
        return [DATA.START, "100", "101", "99", close, "1", DATA.START + DATA.STEP - 1, "100", "1", "1", "100", "0"]

    def test_identical_numeric_duplicate_is_accepted(self):
        rows = {}
        DATA.add_rows(rows, [self.row(), self.row("100.000")], "local")
        self.assertEqual(len(rows), 1)

    def test_conflicting_duplicate_is_rejected(self):
        rows = {}
        DATA.add_rows(rows, [self.row()], "local")
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            DATA.add_rows(rows, [self.row("100.5")], "conflict")

    def funding(self):
        rates = [{"symbol": "BTCUSDT", "fundingTime": at, "fundingRate": "0.0001", "markPrice": "100"}
                 for at in range(DATA.START, DATA.END, 8 * 3_600_000)]
        archive = [[str(row["fundingTime"]), "8", row["fundingRate"]]
                   for row in rates if DATA.YEAR_2025 <= row["fundingTime"] < DATA.YEAR_2026]
        return rates, archive

    def test_full_true_event_window_matches_archive(self):
        rates, archive = self.funding()
        result = DATA.validate_funding("BTCUSDT", rates, archive)
        self.assertEqual(result["events"], 2169)
        self.assertEqual(result["archive_2025_rate_event_matches"], 1095)

    def test_missing_event_is_not_accepted_as_zero(self):
        rates, archive = self.funding()
        rates.pop(400)
        with self.assertRaisesRegex(ValueError, "Funding gap"):
            DATA.validate_funding("BTCUSDT", rates, archive)

    def test_missing_actual_settlement_mark_is_rejected(self):
        rates, archive = self.funding()
        rates[0]["markPrice"] = "nan"
        with self.assertRaisesRegex(ValueError, "Invalid true funding"):
            DATA.validate_funding("BTCUSDT", rates, archive)


if __name__ == "__main__":
    unittest.main()
