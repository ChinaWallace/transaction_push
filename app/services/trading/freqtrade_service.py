# -*- coding: utf-8 -*-
"""
Freqtrade process integration.

The project stays responsible for discovery, filtering, and notifications.
Freqtrade is treated as the execution/backtesting engine and is invoked through
its official Docker image.
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.core.logging import get_logger
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
    DEFAULT_CONFIG = "config.dryrun.example.json"
    DEFAULT_STRATEGY = "OpenSourceTrendStrategy"

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[3]
        self.integration_dir = self.project_root / "freqtrade"
        self.user_data_dir = self.integration_dir / "user_data"
        self.compose_file = self.integration_dir / "docker-compose.yml"
        self.default_config = os.getenv("FREQTRADE_CONFIG_FILE", self.DEFAULT_CONFIG)
        self.default_strategy = os.getenv("FREQTRADE_STRATEGY", self.DEFAULT_STRATEGY)
        self.backend = os.getenv("FREQTRADE_BACKEND", "auto").lower()
        self.freqtrade_bin = os.getenv("FREQTRADE_BIN") or self._default_freqtrade_bin()
        self.timeout_seconds = int(os.getenv("FREQTRADE_COMMAND_TIMEOUT", "1800"))

    async def status(self) -> FreqtradeStatusResponse:
        docker = await self._quick_command(["docker", "--version"])
        compose = await self._quick_command(["docker", "compose", "version"])
        native = await self._quick_command([self.freqtrade_bin, "--version"])
        backend = self._select_backend(docker and compose, native)
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
            compose_file_exists=self.compose_file.exists(),
            user_data_exists=self.user_data_dir.exists(),
            default_config=self.default_config,
            default_strategy=self.default_strategy,
            details=details,
        )

    async def download_data(self, request: FreqtradeDownloadDataRequest) -> FreqtradeCommandResult:
        cmd = self._base_command() + [
            "download-data",
            "--config",
            self._config_path(request.config_file),
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
        cmd = self._base_command() + [
            "backtesting",
            "--config",
            self._config_path(request.config_file),
            "--userdir",
            self._userdir_path(),
            "--strategy",
            request.strategy or self.default_strategy,
            "--timeframe",
            request.timeframe,
        ]
        if request.pairs:
            cmd.append("--pairs")
            cmd.extend(self._normalize_pairs(request.pairs))
        if request.timerange:
            cmd.extend(["--timerange", request.timerange])
        if request.export_trades:
            cmd.extend(["--export", "trades"])
        return await self._run(cmd)

    async def start_bot(self, request: FreqtradeBotStartRequest) -> FreqtradeCommandResult:
        if request.mode == FreqtradeRunMode.LIVE:
            if not request.confirm_live:
                raise ValueError("Live trading requires confirm_live=true.")
            config_file = request.config_file or "config.local.json"
            if config_file == self.DEFAULT_CONFIG:
                raise ValueError("Live trading cannot use the dry-run example config.")
            return await self._run(
                self._base_command(detach=True)
                + [
                    "trade",
                    "--config",
                    self._config_path(config_file),
                    "--userdir",
                    self._userdir_path(),
                    "--strategy",
                    request.strategy or self.default_strategy,
                ]
            )

        if self._current_backend() == "native":
            return await self._spawn_detached(
                self._base_command()
                + [
                    "trade",
                    "--config",
                    self._config_path(request.config_file),
                    "--userdir",
                    self._userdir_path(),
                    "--strategy",
                    request.strategy or self.default_strategy,
                ]
            )
        return await self._run(["docker", "compose", "-f", str(self.compose_file), "up", "-d", "freqtrade"])

    async def stop_bot(self) -> FreqtradeCommandResult:
        if self._current_backend() == "native":
            raise ValueError("Native detached Freqtrade stop is not managed yet; stop it from the process manager or use Docker backend.")
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
        result = []
        seen = set()
        for pair in pairs:
            value = (pair or "").strip().upper()
            if not value:
                continue
            value = value.replace("_", "-")
            if value.endswith("-USDT-SWAP"):
                base = value[: -len("-USDT-SWAP")]
                value = f"{base}/USDT:USDT"
            elif value.endswith("USDT") and "/" not in value:
                base = value[:-4].rstrip("-")
                value = f"{base}/USDT:USDT"
            elif "-" in value and "/" not in value:
                base, quote, *_ = value.split("-")
                value = f"{base}/{quote}:USDT" if quote == "USDT" else f"{base}/{quote}"
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

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

    async def _spawn_detached(self, cmd: List[str]) -> FreqtradeCommandResult:
        started = datetime.now()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.integration_dir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        finished = datetime.now()
        return FreqtradeCommandResult(
            command=cmd,
            return_code=0,
            stdout=f"Started detached Freqtrade process with pid {proc.pid}.",
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
