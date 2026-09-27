"""Tamper tests for the offline v6 result provenance chain."""

import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import stop_provenance as provenance


STRATEGY = "D55Fixed"
WINDOW = "validation"
TIMERANGE = "20260501-20260701"


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "reports/quant_v6"
        self.run = self.out / "runs" / WINDOW / STRATEGY
        self.run.mkdir(parents=True)
        root_patch = patch.object(provenance, "ROOT", self.root)
        out_patch = patch.object(provenance, "OUT", self.out)
        root_patch.start()
        out_patch.start()
        self.addCleanup(root_patch.stop)
        self.addCleanup(out_patch.stop)

        self.source = self.root / "research/strategies/StopComparisonStrategies.py"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("class D55Fixed: pass\n")
        manifest = self.root / "reports/quant_v5/freqtrade_data/manifest.json"
        save_json(manifest, {"output_hashes": {}, "sources": {}})
        self.protocol = {
            "strategies": [STRATEGY], "windows": {WINDOW: TIMERANGE},
            "capital": 10000, "wallet_budget": .7, "fees": [.001, .002],
            "sources": {"research/strategies/StopComparisonStrategies.py": provenance.sha(self.source)},
        }
        self.config = {
            "fee": .001, "dry_run": True, "dry_run_wallet": 10000,
            "stake_amount": "unlimited", "tradable_balance_ratio": .7,
            "max_open_trades": 3, "timeframe": "5m",
            "trading_mode": "futures", "margin_mode": "isolated",
            "user_data_dir": "/temporary/user_data", "bot_name": "offline",
            "exchange": {"name": "binance", "key": "", "secret": "",
                         "ccxt_config": {"enableRateLimit": True, "httpProxy": "http://proxy-a"},
                         "ccxt_async_config": {"httpProxy": "http://proxy-a"}},
            "telegram": {"enabled": False, "token": "", "chat_id": ""},
        }
        self.trades = [{"pair": "ZEC/USDT:USDT", "profit_abs": 2.5}]
        self.result = {"timerange": TIMERANGE, "trades": self.trades,
                       "total_trades": 1, "profit_total": .00025,
                       "profit_total_abs": 2.5, "backtest_start": "2026-05-01",
                       "backtest_end": "2026-07-01"}
        self.archive = self.run / "result/synthetic.zip"
        self.archive.parent.mkdir()
        self.write_archive()
        self.summary = {
            "strategy": STRATEGY, "window": WINDOW, "fee": .001,
            "archive": str(self.archive.relative_to(self.root)),
            "identity": {"sources": self.protocol["sources"],
                         "dataset_manifest": provenance.sha(manifest),
                         "strategy": STRATEGY, "window": WINDOW, "fee": .001},
            **{field: self.result[field] for field in (
                "total_trades", "profit_total", "profit_total_abs",
                "backtest_start", "backtest_end")},
        }
        self.save_run()

    def write_archive(self, *, source=None, config=None, result=None):
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("synthetic_D55Fixed.py", self.source.read_bytes() if source is None else source)
            bundle.writestr("synthetic_config.json", json.dumps(self.config if config is None else config))
            bundle.writestr("synthetic.json", json.dumps({"strategy": {
                STRATEGY: self.result if result is None else result,
            }}))

    def save_run(self):
        save_json(self.run / "config.json", self.config)
        save_json(self.run / "summary.json", self.summary)
        save_json(self.run / "trades.json", self.trades)
        (self.run / "run.log").write_text(
            "2026-09-25 10:00:00,000 - freqtrade - INFO - freqtrade 2026.8\n")

    def verify(self, *, expected_config=None):
        return provenance.verify_run(self.run, self.protocol,
                                     expected_config=expected_config, version="2026.8")

    def test_valid_run_and_redacted_archive_credentials_proxy_and_paths(self):
        expected = copy.deepcopy(self.config)
        expected["user_data_dir"] = "/another/safe/path"
        expected["bot_name"] = "different offline name"
        expected["exchange"]["ccxt_config"]["httpProxy"] = "http://proxy-b"
        expected["exchange"]["ccxt_async_config"]["httpProxy"] = "http://proxy-b"
        archived = copy.deepcopy(self.config)
        archived["exchange"]["key"] = "<redacted>"
        archived["exchange"]["secret"] = "<redacted>"
        archived["telegram"]["token"] = "<redacted>"
        self.write_archive(config=archived)
        value = self.verify(expected_config=expected)
        self.assertEqual(value["timerange"], TIMERANGE)
        self.assertEqual(value["config_digest"], provenance.digest(provenance.economic_config(expected)))

    def test_economic_fee_and_capital_changes_are_rejected(self):
        expected = copy.deepcopy(self.config)
        for field, changed in (("fee", .002), ("dry_run_wallet", 20000)):
            with self.subTest(field=field):
                self.config[field] = changed
                self.save_run()
                with self.assertRaisesRegex(ValueError, "economic configuration changed"):
                    self.verify(expected_config=expected)
                self.config[field] = expected[field]
        self.save_run()
        self.config["exchange"]["key"] = "accidental credential"
        self.save_run()
        with self.assertRaisesRegex(ValueError, "credential-free"):
            self.verify()

    def test_consistent_archive_and_config_capital_tamper_still_rejected(self):
        # Analyzer and sealer call verify_run without expected_config, so the
        # protocol itself must bind the backtest wallet even when ZIP agrees.
        self.config["dry_run_wallet"] = 20000
        self.write_archive()
        self.save_run()
        with self.assertRaisesRegex(ValueError, "(?i)capital|wallet|economic"):
            self.verify()

    def test_base_window_cannot_silently_become_double_cost(self):
        self.config["fee"] = .002
        self.summary["fee"] = .002
        self.summary["identity"]["fee"] = .002
        self.write_archive()
        self.save_run()
        with self.assertRaisesRegex(ValueError, "(?i)fee|economic"):
            self.verify()

    def test_nonselection_summary_field_must_match_archive_too(self):
        self.result["profit_factor"] = 1.5
        self.summary["profit_factor"] = 999
        self.write_archive()
        self.save_run()
        with self.assertRaisesRegex(ValueError, "[Ss]ummary mismatch"):
            self.verify()

    def test_archive_timerange_mismatch_is_rejected(self):
        changed = {**self.result, "timerange": "20260502-20260701"}
        self.write_archive(result=changed)
        with self.assertRaisesRegex(ValueError, "timerange mismatch"):
            self.verify()

    def test_exported_trades_must_match_engine_archive(self):
        save_json(self.run / "trades.json", [{"pair": "ZEC/USDT:USDT", "profit_abs": 99}])
        with self.assertRaisesRegex(ValueError, "Exported trades differ"):
            self.verify()

    def test_archived_strategy_must_match_frozen_source(self):
        self.write_archive(source=b"class D55Fixed: changed\n")
        with self.assertRaisesRegex(ValueError, "Archived strategy differs"):
            self.verify()

    def test_summary_must_match_engine_archive(self):
        self.summary["profit_total_abs"] = 3.5
        self.save_run()
        with self.assertRaisesRegex(ValueError, "Result summary mismatch: profit_total_abs"):
            self.verify()

    def test_seal_rejects_changed_hash(self):
        target = self.root / "research/input.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original")
        save_json(self.out / "integrity_seal.json", {
            "hashes": {"research/input.txt": provenance.sha(target)},
            "engine_version": "2026.8", "runs": {},
        })
        with patch.object(provenance, "engine_version", return_value="2026.8"):
            self.assertIsNotNone(provenance.verify_seal(required=True))
            target.write_text("modified")
            with self.assertRaisesRegex(ValueError, "Frozen research input changed"):
                provenance.verify_seal(required=True)


if __name__ == "__main__":
    unittest.main()
