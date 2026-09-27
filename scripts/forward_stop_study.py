#!/usr/bin/env python3
"""Supervise three credential-free Freqtrade virtual accounts, never real orders."""
import argparse
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.runtime_config import get_runtime_settings
from app.quant.transport import PublicMarketClient
from run_strategy_comparison import config, write
from stop_provenance import verify_seal, sha, economic_config

OUT = ROOT / "reports/quant_v6/forward"
SCRIPT = str(Path(__file__).resolve())
PARENTS = ["M4Structure", "A1Fixed", "D55ClosedTrail"]


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def owned_pid(pid, fragment):
    if not isinstance(pid, int) or pid <= 1:
        return False
    command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return fragment in command


def setup():
    seal = verify_seal(required=True)
    registered = read(OUT.parent / "registry.json")
    passed = {r["strategy"] for r in registered["entries"] if r["status"] == "historical_gates_passed"}
    if passed != set(PARENTS):
        raise ValueError("Forward candidates differ from the verified historical shortlist")
    settings = get_runtime_settings()
    if settings.binance_base_url.rstrip("/") != "https://fapi.binance.com" or settings.binance_testnet:
        raise ValueError("Forward study requires the same public Binance futures venue as the historical study")
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = read(OUT / "protocol.json")
    sources = {name: sha(ROOT / name) for name in ["research/strategies/ForwardStopStrategies.py", "scripts/forward_stop_study.py"]}
    identity = {"historical_seal": sha(OUT.parent / "integrity_seal.json"), "sources": sources,
                "strategies": PARENTS, "mode": "dry_run", "engine_version": seal["engine_version"]}
    if frozen is not None and frozen["identity"] != identity:
        raise ValueError("Forward implementation changed; preserve this observation batch and start a new reviewed batch")
    started = frozen["started_ms"] if frozen else int(time.time()*1000)
    configs = {}
    for parent in PARENTS:
        directory = OUT / parent
        directory.mkdir(exist_ok=True)
        cfg = config("Forward" + parent, directory, .001)
        cfg.update(db_url="sqlite:///" + str(directory / "trades.sqlite"), bot_name="forward_" + parent,
            initial_state="running",
            internals={"process_throttle_secs": 5, "heartbeat_interval": 60},
            forward_study={"output_dir": str(directory), "started_ms": started})
        # All connection configuration comes through the project's .env loader.
        cfg["exchange"]["enable_ws"] = False
        for key in ("ccxt_config", "ccxt_async_config"):
            cfg["exchange"][key].pop("httpProxy", None)
            if settings.proxy_enabled:
                # Python CCXT's sync requests client maps httpProxy only to
                # HTTP URLs. Binance is HTTPS; both clients need httpsProxy.
                cfg["exchange"][key]["httpsProxy"] = settings.proxy_url
            cfg["exchange"][key]["timeout"] = int(settings.quant_http_timeout_seconds*1000)
        previous = read(directory / "config.json")
        if previous is not None and economic_config(previous) != economic_config(cfg):
            raise ValueError("Forward economic config changed: " + parent)
        write(directory / "config.json", cfg)
        configs[parent] = str(directory / "config.json")
    if frozen is None:
        write(OUT / "protocol.json", {"identity": identity, "started_ms": started,
            "accounts": {p: {"capital_usdt": 10000, "budget": .7, "leverage": 1} for p in PARENTS},
            "assessment": "At least 30 observed calendar days and 10 closed trades per strategy before assessment; preserve all failures and gaps. No automatic promotion to live or replacement of the core portfolio.",
            "limitation": "Three separate virtual accounts. Public orderbook simulated fills and funding differ from historical OHLC fills. Historical bars warm indicators only; no pre-start entry is permitted."})
    return configs


def ledger(parent):
    path = OUT / parent / "trades.sqlite"
    if not path.exists():
        return [], 0.0, 0
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trades'").fetchone():
            return [], 0.0, 0
        profit, count = db.execute("SELECT coalesce(sum(close_profit_abs),0),count(*) FROM trades WHERE is_open=0").fetchone()
        rows = [dict(r) for r in db.execute("SELECT id,pair,is_open,open_date,close_date,open_rate,close_rate,amount,stake_amount,leverage,stop_loss,initial_stop_loss,close_profit_abs,funding_fees,fee_open,fee_close,enter_tag,exit_reason FROM trades WHERE is_open=1 OR id IN (SELECT id FROM trades ORDER BY id DESC LIMIT 200) ORDER BY id DESC")]
        return rows, profit, count


def snapshot(children, marks, quote_at):
    now = int(time.time()*1000)
    accounts = []
    previous = {a["strategy"]: a for a in read(OUT / "status.json", {}).get("accounts", [])}
    for parent in PARENTS:
        directory = OUT / parent
        heartbeat = read(directory / "heartbeat.json", {})
        trades, profit, count = ledger(parent)
        opened = [t for t in trades if t["is_open"]]
        fault = read(directory / "callback_fault.json") or read(directory / "entry_block.json")
        market_events = read(directory / "market_events.json", {"failed_entry_attempts": 0, "last_error_ms": 0})
        candle_times = heartbeat.get("candle_close_ms", {})
        data_fresh = len(candle_times) == 3 and all(0 <= now - at <= 420_000 for at in candle_times.values())
        pid = children.get(parent)
        running = owned_pid(pid, str(directory / "config.json"))
        state = "fault_new_entries_blocked" if fault else "stopped" if not running else "observing" if data_fresh else "warming_or_data_stale"
        if state == "observing" and now-market_events["last_error_ms"] < 180_000:
            state = "market_data_degraded"
        equity = 10000 + profit
        for trade in opened:
            quote = marks.get(trade["pair"].split("/")[0] + "USDT")
            if quote is None or not 0 <= now-quote["time"] <= 180_000:
                equity = None
                if state == "observing":state = "market_data_degraded"
                break
            mark = quote["price"]
            equity += trade["amount"] * (mark - trade["open_rate"]) + (trade["funding_fees"] or 0)
            equity -= trade["amount"] * (trade["open_rate"] * trade["fee_open"] + mark * trade["fee_close"])
        old = previous.get(parent, {})
        peak = max(old.get("equity_peak", 10000), equity or 0)
        drawdown = max(old.get("observed_drawdown_pct", 0), 100*(1-equity/peak) if equity is not None else 0)
        accounts.append({"strategy": parent, "pid": pid, "state": state, "data_fresh": data_fresh,
            "candle_close_ms": candle_times, "heartbeat_ms": heartbeat.get("at_ms"), "fault": fault,
            "market_events": market_events,
            "open_positions": len(opened), "closed_trades": count,
            "closed_profit_usdt": profit, "estimated_liquidation_equity": equity,
            "equity_peak": peak, "observed_drawdown_pct": drawdown,
            "recent_trades": trades, "log": str((directory / "run.log").relative_to(ROOT))})
    result = {"updated_ms": now, "started_ms": read(OUT / "protocol.json")["started_ms"],
        "live_enabled": False, "accounts": accounts, "mark_quote_ms": quote_at,
        "note": "Independent 10000 USDT virtual accounts; do not sum these as one 70% portfolio. Equity deducts estimated closing fees; stale marks yield null. No historical entries replayed."}
    write(OUT / "status.json", result)
    with (OUT / "equity_observations.jsonl").open("a") as history:
        history.write(json.dumps({"at_ms": now, "quote_ms": quote_at, "accounts": [
            {k: a[k] for k in ("strategy", "state", "estimated_liquidation_equity", "open_positions", "closed_trades")}
            for a in accounts]}, ensure_ascii=False) + "\n")
    return result


def serve():
    configs = setup()
    with (OUT / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Forward supervisor already running") from None
        processes = {}
        stop = False
        def halt(*_):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, halt)
        signal.signal(signal.SIGINT, halt)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("FREQTRADE__")
               and k.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
        env.update(PYTHONUNBUFFERED="1", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
        try:
            log_offsets = {p: (OUT / p / "run.log").stat().st_size if (OUT / p / "run.log").exists() else 0 for p in PARENTS}
            for parent, cfg in configs.items():
                with (OUT / parent / "run.log").open("a") as log:
                    processes[parent] = subprocess.Popen([str(ROOT / ".venv.freqtrade-quant/bin/freqtrade"),
                        "trade", "--dry-run", "-c", cfg, "--strategy-path", str(ROOT / "research/strategies"),
                        "-s", "Forward" + parent], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log)
            children = {p: process.pid for p, process in processes.items()}
            write(OUT / "service.json", {"pid": os.getpid(), "children": children})
            marks, quote_at, last_quote = {}, None, 0
            while not stop:
                if time.time() - last_quote > 60:
                    last_quote = time.time()
                    try:
                        with PublicMarketClient() as client:
                            data = client.get("/fapi/v1/premiumIndex")
                        marks = {r["symbol"]: {"price":float(r["markPrice"]), "time":int(r["time"])} for r in data}
                        quote_at = int(time.time()*1000)
                    except Exception as exc:
                        print("Mark-price observation unavailable:", type(exc).__name__, flush=True)
                for parent in PARENTS:
                    with (OUT / parent / "run.log").open() as log:
                        log.seek(log_offsets[parent])
                        new = log.read()
                        log_offsets[parent] = log.tell()
                    if " - ERROR - " in new or "Traceback (most recent call last)" in new:
                        write(OUT / parent / "entry_block.json", {"at_ms": int(time.time()*1000),
                            "reason": "Engine error logged; observation needs review", "new_entries_blocked": True})
                    rejected = new.count("Unable to create trade for")
                    if rejected or "RequestTimeout" in new:
                        path = OUT / parent / "market_events.json"
                        events = read(path, {"failed_entry_attempts": 0})
                        events.update(last_error_ms=int(time.time()*1000),
                            failed_entry_attempts=events["failed_entry_attempts"]+rejected,
                            reason="Market request failed; see engine log. A signal may exist without a completed virtual trade.")
                        write(path, events)
                try:
                    snapshot(children, marks, quote_at)
                except sqlite3.Error as exc:
                    print("Ledger snapshot unavailable:", type(exc).__name__, flush=True)
                for _ in range(15):
                    if stop:
                        break
                    time.sleep(1)
        finally:
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
            for process in processes.values():
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    print("Virtual worker still shutting down:", process.pid, flush=True)
            state = read(OUT / "service.json", {})
            snapshot(state.get("children", {}), {}, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status", "serve"])
    args = parser.parse_args()
    state = read(OUT / "service.json", {})
    active = owned_pid(state.get("pid"), SCRIPT + " serve")
    if args.command == "status":
        result = read(OUT / "status.json", {"state": "not_started"})
        result["supervisor_running"] = active
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "stop":
        if active:
            os.kill(state["pid"], signal.SIGTERM)
        else:
            for parent, pid in state.get("children", {}).items():
                if parent in PARENTS and owned_pid(pid, str(OUT / parent / "config.json")):
                    os.kill(pid, signal.SIGTERM)
        print("已请求停止独立模拟，数据库和研究记录保留")
    elif args.command == "serve":
        serve()
    else:
        if active:
            print("三策略独立模拟已运行")
            return
        if any(owned_pid(pid, str(OUT / p / "config.json")) for p, pid in state.get("children", {}).items()):
            raise SystemExit("Existing virtual workers still running; stop them with forward-stop before restarting")
        setup()
        with (OUT / "supervisor.log").open("a") as log:
            process = subprocess.Popen([sys.executable, SCRIPT, "serve"], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True)
        print(f"已启动独立模拟监督进程 {process.pid}；公开行情初始化中，详见 forward-status")


if __name__ == "__main__":
    main()
