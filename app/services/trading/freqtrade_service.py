# -*- coding: utf-8 -*-
"""
Freqtrade process integration.

The project stays responsible for discovery, filtering, and notifications.
Freqtrade is treated as the execution/backtesting engine and is invoked through
its official Docker image.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.core.logging import get_logger
from app.core.trading_universe import (
    ALLOWED_FREQTRADE_PAIRS,
    normalize_freqtrade_pairs,
)
from app.schemas.freqtrade import (
    FreqtradeBacktestRequest,
    FreqtradeBotStartRequest,
    FreqtradeCommandResult,
    FreqtradeDownloadDataRequest,
    FreqtradeRunMode,
    FreqtradeStatusResponse,
)


logger = get_logger(__name__)


class FreqtradeService:
    DEFAULT_CONFIG = "config.btc_eth.dryrun.example.json"
    DEFAULT_STRATEGY = "BtcEth4hStrategy"

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[3]
        self.integration_dir = self.project_root / "freqtrade"
        self.user_data_dir = self.integration_dir / "user_data"
        self.compose_file = self.integration_dir / "docker-compose.yml"
        self.default_config = self.DEFAULT_CONFIG
        self.default_strategy = self.DEFAULT_STRATEGY
        self.backend = os.getenv("FREQTRADE_BACKEND", "auto").lower()
        self.freqtrade_bin = os.getenv("FREQTRADE_BIN") or self._default_freqtrade_bin()
        self.timeout_seconds = int(os.getenv("FREQTRADE_COMMAND_TIMEOUT", "1800"))
        self.native_pid_file = self.user_data_dir / "freqtrade_native.pid"
        self.native_log_file = self.project_root / "logs" / "freqtrade_native.log"

    async def status(self) -> FreqtradeStatusResponse:
        docker = await self._quick_command(["docker", "--version"])
        compose = await self._quick_command(["docker", "compose", "version"])
        native = await self._quick_command([self.freqtrade_bin, "--version"])
        backend = self._select_backend(docker and compose, native)
        bot_pid = self._read_native_pid() if backend == "native" else None
        details = []
        if not docker:
            details.append("Docker is not available on PATH.")
        if not compose:
            details.append("Docker Compose v2 is not available on PATH.")
        if not native:
            details.append(f"Native Freqtrade CLI is not available: {self.freqtrade_bin}")
        if not self.compose_file.exists():
            details.append(f"Compose file missing: {self.compose_file}")
        if not self.user_data_dir.exists():
            details.append(f"Freqtrade user_data directory missing: {self.user_data_dir}")
        return FreqtradeStatusResponse(
            docker_available=docker,
            compose_available=compose,
            native_available=native,
            selected_backend=backend,
            bot_running=bot_pid is not None,
            bot_pid=bot_pid,
            compose_file_exists=self.compose_file.exists(),
            user_data_exists=self.user_data_dir.exists(),
            default_config=self.default_config,
            default_strategy=self.default_strategy,
            details=details,
        )

    async def download_data(self, request: FreqtradeDownloadDataRequest) -> FreqtradeCommandResult:
        config_path = self._validated_dry_run_config_path(request.config_file)
        if request.timeframes != ["4h"]:
            raise ValueError("The BTC/ETH baseline only downloads the 4h timeframe.")
        cmd = self._base_command() + [
            "download-data",
            "--config",
            config_path,
            "--userdir",
            self._userdir_path(),
        ]
        for timeframe in request.timeframes:
            cmd.extend(["--timeframes", timeframe])
        pairs = self._normalize_pairs(request.pairs)
        if pairs:
            cmd.append("--pairs")
            cmd.extend(pairs)
        if request.timerange:
            cmd.extend(["--timerange", request.timerange])
        return await self._run(cmd)

    async def backtest(self, request: FreqtradeBacktestRequest) -> FreqtradeCommandResult:
        strategy = self._validated_strategy(request.strategy)
        config_path = self._validated_dry_run_config_path(request.config_file)
        if request.timeframe != "4h":
            raise ValueError("The BTC/ETH baseline only supports the 4h timeframe.")
        if not request.enable_protections:
            raise ValueError("Freqtrade protections are mandatory in the BTC/ETH baseline.")
        cmd = self._base_command() + [
            "backtesting",
            "--config",
            config_path,
            "--userdir",
            self._userdir_path(),
            "--strategy",
            strategy,
            "--timeframe",
            request.timeframe,
        ]
        if request.pairs:
            cmd.append("--pairs")
            cmd.extend(self._normalize_pairs(request.pairs))
        if request.timerange:
            cmd.extend(["--timerange", request.timerange])
        if request.enable_protections:
            cmd.append("--enable-protections")
        if request.cache:
            cmd.extend(["--cache", request.cache])
        if request.export_trades:
            cmd.extend(["--export", "trades"])
        return await self._run(cmd)

    async def start_bot(self, request: FreqtradeBotStartRequest) -> FreqtradeCommandResult:
        if request.mode == FreqtradeRunMode.LIVE:
            raise ValueError(
                "Live trading is disabled in the BTC/ETH baseline. "
                "Use dry_run until authentication, testnet validation, and live risk controls are implemented."
            )

        strategy = self._validated_strategy(request.strategy)
        config_path = self._validated_dry_run_config_path(request.config_file)

        backend = self._current_backend()
        if backend == "unavailable":
            raise ValueError("Neither Docker Compose nor native Freqtrade CLI is available.")
        if backend == "native":
            existing_pid = self._read_native_pid()
            if existing_pid is not None:
                now = datetime.now()
                cmd = [
                    self.freqtrade_bin,
                    "trade",
                    "--config",
                    config_path,
                    "--userdir",
                    self._userdir_path(),
                    "--strategy",
                    strategy,
                ]
                return FreqtradeCommandResult(
                    command=cmd,
                    return_code=0,
                    stdout=f"Freqtrade dry-run is already running with pid {existing_pid}.",
                    stderr="",
                    started_at=now,
                    finished_at=now,
                    elapsed_seconds=0.0,
                    success=True,
                )
            return await self._spawn_detached(
                self._base_command()
                + [
                    "trade",
                    "--config",
                    config_path,
                    "--userdir",
                    self._userdir_path(),
                    "--strategy",
                    strategy,
                ]
            )
        return await self._run(["docker", "compose", "-f", str(self.compose_file), "up", "-d", "freqtrade"])

    async def stop_bot(self) -> FreqtradeCommandResult:
        if self._current_backend() == "native":
            return await self._stop_native_bot()
        return await self._run(["docker", "compose", "-f", str(self.compose_file), "down"])

    def _base_command(self, detach: bool = False) -> List[str]:
        backend = self._current_backend()
        if backend == "native":
            if detach:
                return [self.freqtrade_bin]
            return [self.freqtrade_bin]
        if backend == "unavailable":
            raise ValueError("Neither Docker Compose nor native Freqtrade CLI is available.")
        return self._base_run_command(detach=detach)

    def _base_run_command(self, detach: bool = False) -> List[str]:
        cmd = ["docker", "compose", "-f", str(self.compose_file), "run"]
        if detach:
            cmd.append("-d")
        else:
            cmd.append("--rm")
        cmd.append("freqtrade")
        return cmd

    def _config_path(self, config_file: Optional[str]) -> str:
        value = config_file or self.default_config
        if any(part in value for part in ("..", "/", "\\")):
            raise ValueError("config_file must be a file name inside freqtrade/user_data")
        host_path = self.user_data_dir / value
        if not host_path.exists():
            raise ValueError(f"Freqtrade config does not exist: {host_path}")
        if self._current_backend() == "native":
            return str(host_path)
        return f"/freqtrade/user_data/{value}"

    def _validated_dry_run_config_path(self, config_file: Optional[str]) -> str:
        value = config_file or self.default_config
        if value != self.DEFAULT_CONFIG:
            raise ValueError(
                f"Only the BTC/ETH dry-run config is allowed: {self.DEFAULT_CONFIG}"
            )

        host_path = self.user_data_dir / value
        try:
            config = json.loads(host_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Freqtrade config does not exist: {host_path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Freqtrade config is not valid JSON: {host_path}") from exc

        if config.get("dry_run") is not True:
            raise ValueError("BTC/ETH baseline config must keep dry_run=true.")
        if config.get("trading_mode") != "futures" or config.get("margin_mode") != "isolated":
            raise ValueError("BTC/ETH baseline requires isolated futures mode.")
        if config.get("timeframe") != "4h":
            raise ValueError("BTC/ETH baseline config must use the 4h timeframe.")
        try:
            max_open_trades = int(config.get("max_open_trades", 0))
            stake_amount = float(config.get("stake_amount", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Freqtrade risk limits must be numeric.") from exc
        if max_open_trades not in {1, 2}:
            raise ValueError("BTC/ETH baseline allows at most two open trades.")
        if not 0 < stake_amount <= 100:
            raise ValueError("BTC/ETH baseline stake_amount must be between 0 and 100 USDT.")

        exchange = config.get("exchange") or {}
        if str(exchange.get("name", "")).lower() != "binance":
            raise ValueError("BTC/ETH baseline config must use Binance.")
        if exchange.get("key") or exchange.get("secret"):
            raise ValueError("The checked-in dry-run baseline must not contain exchange credentials.")
        whitelist = tuple(normalize_freqtrade_pairs(exchange.get("pair_whitelist") or []))
        if set(whitelist) != set(ALLOWED_FREQTRADE_PAIRS):
            raise ValueError("Freqtrade pair_whitelist must contain exactly BTC and ETH USDT perpetuals.")
        if (config.get("api_server") or {}).get("enabled") is not False:
            raise ValueError("Freqtrade API server must remain disabled in the dry-run baseline.")

        return self._config_path(value)

    def _validated_strategy(self, strategy: Optional[str]) -> str:
        value = strategy or self.default_strategy
        if value != self.DEFAULT_STRATEGY:
            raise ValueError(f"Only {self.DEFAULT_STRATEGY} is allowed in the BTC/ETH baseline.")
        return value

    def _userdir_path(self) -> str:
        if self._current_backend() == "native":
            return str(self.user_data_dir)
        return "/freqtrade/user_data"

    def _current_backend(self) -> str:
        if self.backend == "native":
            return "native"
        if self.backend == "docker":
            return "docker"
        docker_ready = self._command_exists_sync(["docker", "--version"]) and self._command_exists_sync(["docker", "compose", "version"])
        native_ready = self._command_exists_sync([self.freqtrade_bin, "--version"])
        return self._select_backend(docker_ready, native_ready)

    def _select_backend(self, docker_ready: bool, native_ready: bool) -> str:
        if self.backend == "docker":
            return "docker"
        if self.backend == "native":
            return "native"
        if docker_ready:
            return "docker"
        if native_ready:
            return "native"
        return "unavailable"

    def _default_freqtrade_bin(self) -> str:
        suffix = "Scripts/freqtrade.exe" if os.name == "nt" else "bin/freqtrade"
        candidate = self.project_root / ".venv" / Path(suffix)
        return str(candidate) if candidate.exists() else "freqtrade"

    @staticmethod
    def _normalize_pairs(pairs: List[str]) -> List[str]:
        return normalize_freqtrade_pairs(pairs)

    async def _quick_command(self, cmd: List[str]) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _command_exists_sync(cmd: List[str]) -> bool:
        import subprocess

        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    def _read_native_pid(self) -> Optional[int]:
        try:
            if not self.native_pid_file.exists():
                return None
            pid = int(self.native_pid_file.read_text(encoding="utf-8").strip())
            if self._is_process_running(pid):
                return pid
            self.native_pid_file.unlink(missing_ok=True)
            return None
        except Exception:
            return None

    @staticmethod
    def _is_process_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    async def _stop_native_bot(self) -> FreqtradeCommandResult:
        started = datetime.now()
        pid = self._read_native_pid()
        if pid is None:
            finished = datetime.now()
            return FreqtradeCommandResult(
                command=[],
                return_code=0,
                stdout="Freqtrade dry-run is not running.",
                stderr="",
                started_at=started,
                finished_at=finished,
                elapsed_seconds=(finished - started).total_seconds(),
                success=True,
            )

        if os.name == "nt":
            cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
        else:
            cmd = ["kill", str(pid)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await proc.communicate()
        self.native_pid_file.unlink(missing_ok=True)
        finished = datetime.now()
        return FreqtradeCommandResult(
            command=cmd,
            return_code=proc.returncode or 0,
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
            started_at=started,
            finished_at=finished,
            elapsed_seconds=(finished - started).total_seconds(),
            success=(proc.returncode == 0),
        )

    async def _spawn_detached(self, cmd: List[str]) -> FreqtradeCommandResult:
        started = datetime.now()
        self.native_log_file.parent.mkdir(exist_ok=True)
        log_handle = self.native_log_file.open("ab")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.integration_dir),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            close_fds=True,
            creationflags=creationflags,
        )
        log_handle.close()
        self.native_pid_file.write_text(str(proc.pid), encoding="utf-8")
        finished = datetime.now()
        return FreqtradeCommandResult(
            command=cmd,
            return_code=0,
            stdout=f"Started detached Freqtrade process with pid {proc.pid}. Log: {self.native_log_file}",
            stderr="",
            started_at=started,
            finished_at=finished,
            elapsed_seconds=(finished - started).total_seconds(),
            success=True,
        )

    async def _run(self, cmd: List[str]) -> FreqtradeCommandResult:
        started = datetime.now()
        logger.info("Running Freqtrade command: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.integration_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            stdout_raw, stderr_raw = await proc.communicate()
            finished = datetime.now()
            return FreqtradeCommandResult(
                command=cmd,
                return_code=-1,
                stdout=stdout_raw.decode("utf-8", errors="replace"),
                stderr=(stderr_raw.decode("utf-8", errors="replace") + "\nCommand timed out.").strip(),
                started_at=started,
                finished_at=finished,
                elapsed_seconds=(finished - started).total_seconds(),
                success=False,
            )

        finished = datetime.now()
        return FreqtradeCommandResult(
            command=cmd,
            return_code=proc.returncode or 0,
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
            started_at=started,
            finished_at=finished,
            elapsed_seconds=(finished - started).total_seconds(),
            success=(proc.returncode == 0),
        )


_freqtrade_service: Optional[FreqtradeService] = None


def get_freqtrade_service() -> FreqtradeService:
    global _freqtrade_service
    if _freqtrade_service is None:
        _freqtrade_service = FreqtradeService()
    return _freqtrade_service
