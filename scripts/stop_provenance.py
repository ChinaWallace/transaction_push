"""Integrity checks for frozen stop studies (stdlib only, no account access)."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_v6"
CODE = ["scripts/run_stop_comparison.py", "scripts/run_strategy_comparison.py",
        "scripts/analyze_stop_comparison.py", "scripts/analyze_strategy_comparison.py",
        "scripts/stop_provenance.py"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def economic_config(config):
    """Ignore locations/network routes and archive credential redaction only."""
    result = copy.deepcopy(config)
    result.pop("user_data_dir", None)
    result.pop("bot_name", None)
    for key in ("key", "secret", "password", "uid"):
        result.get("exchange", {}).pop(key, None)
    for key in ("token", "chat_id"):
        result.get("telegram", {}).pop(key, None)
    for field in ("ccxt_config", "ccxt_async_config"):
        for key in ("httpProxy", "httpsProxy", "socksProxy", "proxy"):
            result.get("exchange", {}).get(field, {}).pop(key, None)
    return result


def verify_hashes(hashes):
    for name, expected in hashes.items():
        path = ROOT / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError("Frozen research input changed: " + name)


def dataset_hashes(include_challenge=True):
    """Check the original source manifests, including 5m marks used for DD."""
    hashes = {}
    manifests = [ROOT / "reports/quant_v5/data/manifest.json",
                 ROOT / "reports/quant_v5/freqtrade_data/manifest.json"]
    if include_challenge:
        manifests += [OUT / "challenge_data/manifest.json", OUT / "challenge_data/freqtrade_data/manifest.json"]
    for path in manifests:
        hashes[str(path.relative_to(ROOT))] = sha(path)
        manifest = json.loads(path.read_text())
        hashes.update(manifest.get("sources", {}))
        for name, expected in manifest.get("output_hashes", {}).items():
            hashes[str((path.parent / name).relative_to(ROOT))] = expected
        if isinstance(manifest.get("symbols"), dict):
            for symbol in manifest["symbols"].values():
                for item in [*symbol.get("series", {}).values(), symbol.get("funding", {})]:
                    if "sha256" in item:
                        hashes[item["path"]] = item["sha256"]
    verify_hashes(hashes)
    return hashes


def engine_version():
    return subprocess.check_output([str(ROOT / ".venv.freqtrade-quant/bin/python"), "-c",
        "from importlib.metadata import version; print(version('freqtrade'))"], text=True).strip()


def verify_run(run, protocol, expected_config=None, version=None):
    summary = json.loads((run / "summary.json").read_text())
    strategy = summary["strategy"]
    window = summary["window"].removesuffix("_double_cost")
    if strategy not in protocol["strategies"] or summary["window"] != run.parent.name or strategy != run.name:
        raise ValueError("Result path/strategy mismatch: " + str(run))
    config = json.loads((run / "config.json").read_text())
    if expected_config is not None and economic_config(config) != economic_config(expected_config):
        raise ValueError("Cached economic configuration changed: " + str(run))
    if not config.get("dry_run") or config["exchange"].get("key") or config["exchange"].get("secret"):
        raise ValueError("Research configuration must be credential-free and dry-run")
    if config["fee"] != summary["fee"]:
        raise ValueError("Result fee mismatch")
    expected_fee = protocol["fees"][1 if summary["window"].endswith("_double_cost") else 0]
    constraints = {"fee": expected_fee, "dry_run_wallet": protocol["capital"],
        "tradable_balance_ratio": protocol["wallet_budget"], "max_open_trades": 3,
        "stake_amount": "unlimited", "timeframe": "5m", "trading_mode": "futures", "margin_mode": "isolated"}
    if any(config.get(k) != value for k, value in constraints.items()):
        raise ValueError("Economic configuration differs from frozen protocol")
    datadir = OUT / "challenge_data/freqtrade_data" if window == "challenge2025" else ROOT / "reports/quant_v5/freqtrade_data"
    expected_identity = {"sources": protocol["sources"], "dataset_manifest": sha(datadir / "manifest.json"),
                         "strategy": strategy, "window": window, "fee": summary["fee"]}
    if summary.get("identity") != expected_identity:
        raise ValueError("Result source/data identity mismatch: " + str(run))
    with zipfile.ZipFile(ROOT / summary["archive"]) as archive:
        source = next(n for n in archive.namelist() if n.endswith("_" + strategy + ".py"))
        if archive.read(source) != (ROOT / "research/strategies/StopComparisonStrategies.py").read_bytes():
            raise ValueError("Archived strategy differs from frozen source")
        archived_config = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith("_config.json"))))
        subset = {key: archived_config.get(key) for key in config}
        if economic_config(subset) != economic_config(config):
            raise ValueError("Archived configuration mismatch")
        results = [json.loads(archive.read(n)) for n in archive.namelist()
                   if n.endswith(".json") and not n.endswith("_config.json") and ".meta." not in n]
        result = next(x["strategy"][strategy] for x in results if strategy in x.get("strategy", {}))
    if result.get("timerange") != protocol["windows"][window]:
        raise ValueError("Cached timerange mismatch")
    if result["trades"] != json.loads((run / "trades.json").read_text()):
        raise ValueError("Exported trades differ from engine archive")
    for field in summary.keys() & result.keys():
        if summary[field] != result[field]:
            raise ValueError("Result summary mismatch: " + field)
    log = (run / "run.log").read_text()
    match = re.search(r" - freqtrade - INFO - freqtrade (\S+)", log)
    if not match or (version is not None and match[1] != version):
        raise ValueError("Cached engine version mismatch")
    if "Traceback (most recent call last)" in log or " - ERROR - " in log:
        raise ValueError("Engine reported an error")
    return {"strategy": strategy, "window": window, "timerange": result["timerange"],
            "config_digest": digest(economic_config(config)), "engine_version": match[1]}


def verify_seal(required=False):
    path = OUT / "integrity_seal.json"
    if not path.exists():
        if required:
            raise ValueError("Research integrity seal is missing")
        return None
    seal = json.loads(path.read_text())
    verify_hashes(seal["hashes"])
    if seal["engine_version"] != engine_version():
        raise ValueError("Research engine changed; use a new experiment")
    return seal


def seal_results():
    """Bind existing verified artifacts, explicitly after the historical runs."""
    if verify_seal() is not None:
        return
    protocol = json.loads((OUT / "protocol.json").read_text())
    hashes = dataset_hashes()
    hashes.update(protocol["sources"])
    for path in [*(ROOT / s for s in CODE), OUT / "protocol.json", OUT / "selection.json"]:
        hashes[str(path.relative_to(ROOT))] = sha(path)
    version = engine_version()
    runs = {}
    for summary in sorted((OUT / "runs").glob("*/*/summary.json")):
        run = summary.parent
        runs[str(run.relative_to(OUT))] = verify_run(run, protocol, version=version)
        meta = json.loads(summary.read_text())
        for path in [summary, run / "trades.json", run / "config.json", run / "run.log", ROOT / meta["archive"]]:
            hashes[str(path.relative_to(ROOT))] = sha(path)
    value = {"bound_ms": int(time.time()*1000), "engine_version": version, "hashes": hashes, "runs": runs,
             "binding_phase": "post_run_verification",
             "note": "Added after original runs: source archives, configs, timeranges, engine logs, trades and original data hashes verified. This is not a claim of pre-registration."}
    tmp = OUT / "integrity_seal.tmp"
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT / "integrity_seal.json")


if __name__ == "__main__":
    seal_results()
    print("Frozen inputs and result archives verified and bound; no trading action.")
