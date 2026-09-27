"""Three isolated virtual accounts; the frozen historical classes stay unchanged."""
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import sys
import time

from freqtrade.enums import RunMode
from freqtrade.strategy import IStrategy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from StopComparisonStrategies import A1Fixed, D55ClosedTrail, M4Structure


class ForwardOnly:
    def __init__(self, config):
        exchange = config.get("exchange", {})
        if config.get("runmode") != RunMode.DRY_RUN or config.get("dry_run") is not True:
            raise ValueError("Forward study only permits virtual dry-run accounts")
        if any(exchange.get(k) for k in ("key", "secret", "password", "uid", "privateKey", "walletAddress")):
            raise ValueError("Forward study forbids exchange credentials")
        if config.get("trading_mode") != "futures" or config.get("max_open_trades") != 3:
            raise ValueError("Forward study requires the frozen three-pair futures configuration")
        if config.get("tradable_balance_ratio") != .7 or config.get("fee") != .001:
            raise ValueError("Forward account budget/cost differs from frozen study")
        if set(exchange.get("pair_whitelist", [])) != {"BTC/USDT:USDT", "ETH/USDT:USDT", "ZEC/USDT:USDT"}:
            raise ValueError("Unexpected forward universe")
        # ResearchBudget.__init__ only guards research run modes and calls this
        # same initializer. These three parents have no other initialization.
        IStrategy.__init__(self, config)
        self.can_short = False
        self.forward_dir = Path(config["forward_study"]["output_dir"])
        self.forward_start = config["forward_study"]["started_ms"]
        self.forward_fault = (self.forward_dir / "callback_fault.json").exists()
        self._last_heartbeat = 0
        self._stop_seen = {}
        previous = self.forward_dir / "heartbeat.json"
        self._seen = json.loads(previous.read_text()).get("candle_close_ms", {}) if previous.exists() else {}

    def _write(self, name, value):
        path = self.forward_dir / name
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        temp.replace(path)

    def _fault(self, callback, error):
        self.forward_fault = True
        try:
            self._write("callback_fault.json", {"at_ms": int(time.time()*1000),
                "callback": callback, "error_type": type(error).__name__,
                "new_entries_blocked": True, "observation_valid": False})
        except OSError:
            # The in-memory latch still rejects entries when the disk is broken.
            pass

    def _decision(self, kind, **fields):
        with (self.forward_dir / "decisions.jsonl").open("a") as log:
            log.write(json.dumps({"recorded_ms": int(time.time()*1000), "kind": kind, **fields}, default=str)+"\n")
            if kind in {"entry_approved", "exit_approved"}:
                log.flush()
                os.fsync(log.fileno())

    def populate_entry_trend(self, dataframe, metadata):
        result = super().populate_entry_trend(dataframe, metadata)
        try:
            if not result.empty:
                row = result.iloc[-1]
                closed = int((row["date"]+timedelta(minutes=5)).timestamp()*1000)
                if closed >= self.forward_start:
                    self._decision("entry_signal", pair=metadata["pair"], candle_close_ms=closed,
                        enter_long=int(row.get("enter_long", 0)), tag=row.get("enter_tag") if isinstance(row.get("enter_tag"),str) else None, close=float(row["close"]))
        except Exception as exc:
            self._fault("entry_evidence", exc)
        if self.forward_fault:
            result["enter_long"] = 0
        return result

    def bot_loop_start(self, current_time, **kwargs):
        try:
            self._observe_loop(current_time, **kwargs)
        except Exception as exc:
            self._fault("observation", exc)
            raise

    def _observe_loop(self, current_time, **kwargs):
        super().bot_loop_start(current_time=current_time, **kwargs)
        if time.time() - self._last_heartbeat < 15:
            return
        self._last_heartbeat = time.time()
        candles = {}
        for pair in self.dp.current_whitelist():
            frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if not frame.empty:
                row = frame.iloc[-1]
                closed = int((row["date"] + timedelta(minutes=5)).timestamp()*1000)
                candles[pair] = closed
                prior = self._seen.get(pair)
                if closed >= self.forward_start and closed != prior:
                    observed = {"received_ms": int(time.time()*1000), "pair": pair, "close_ms": closed,
                        "unobserved_gap_bars": max(0, (closed-prior)//300_000-1) if prior else 0,
                        "values": {key: row.get(key) for key in ("open", "high", "low", "close", "volume",
                            "enter_long", "exit_long", "enter_tag", "exit_tag", "atr_1h", "atr_4h")}}
                    observed["values"] = {k: None if isinstance(v,float) and not math.isfinite(v) else v
                                          for k,v in observed["values"].items()}
                    with (self.forward_dir / "candle_observations.jsonl").open("a") as log:
                        log.write(json.dumps(observed, default=str) + "\n")
                self._seen[pair] = closed
        self._write("heartbeat.json", {"at_ms": int(time.time()*1000), "candle_close_ms": candles,
            "callback_fault": self.forward_fault, "dry_run": True})

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        if self.forward_fault or (self.forward_dir / "entry_block.json").exists() or side != "long":
            return False
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if frame.empty:
            return False
        closed = frame.iloc[-1]["date"] + timedelta(minutes=5)
        age = (current_time - closed).total_seconds()
        # Warmup is allowed; entries based on pre-start or stale signals are not.
        if int(closed.timestamp()*1000) < self.forward_start or not 0 <= age <= 90:
            return False
        approved = super().confirm_trade_entry(pair=pair, order_type=order_type,
            amount=amount, rate=rate, time_in_force=time_in_force, current_time=current_time,
            entry_tag=entry_tag, side=side, **kwargs)
        if approved:
            try:
                self._decision("entry_approved", pair=pair, current_time=current_time,
                    candle_close_ms=int(closed.timestamp()*1000), amount=amount, rate=rate, tag=entry_tag)
            except Exception as exc:
                self._fault("entry_approval_evidence", exc)
                return False
        return approved

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        try:
            self._decision("exit_approved", pair=pair, trade_id=trade.id, current_time=current_time,
                amount=amount, rate=rate, reason=exit_reason)
        except Exception as exc:
            # Loss of logging must never trap an existing virtual position.
            self._fault("exit_evidence", exc)
        return super().confirm_trade_exit(pair=pair, trade=trade, order_type=order_type,
            amount=amount, rate=rate, time_in_force=time_in_force, exit_reason=exit_reason,
            current_time=current_time, **kwargs)

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill, **kwargs):
        try:
            result = super().custom_stoploss(pair=pair, trade=trade, current_time=current_time,
                current_rate=current_rate, current_profit=current_profit, after_fill=after_fill, **kwargs)
            state = trade.get_custom_data("v6_stop_"+self.stop_profile)
            if state and self._stop_seen.get(trade.id) != state["stop"]:
                self._decision("stop_proposed", pair=pair, trade_id=trade.id,
                    current_time=current_time, current_rate=current_rate, state=state)
                self._stop_seen[trade.id] = state["stop"]
            return result
        except Exception as exc:
            self._fault("custom_stoploss", exc)
            raise

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        try:
            return super().custom_exit(pair=pair, trade=trade, current_time=current_time,
                current_rate=current_rate, current_profit=current_profit, **kwargs)
        except Exception as exc:
            self._fault("custom_exit", exc)
            raise


class ForwardM4Structure(ForwardOnly, M4Structure): pass
class ForwardA1Fixed(ForwardOnly, A1Fixed): pass
class ForwardD55ClosedTrail(ForwardOnly, D55ClosedTrail): pass
