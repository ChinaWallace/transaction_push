# -*- coding: utf-8 -*-
"""Canonical BTC/ETH-only trading universe.

This module is intentionally small and dependency-free so every execution or
backtest entrypoint can apply the same fail-closed symbol policy.
"""

from typing import Iterable, List


ALLOWED_BASE_ASSETS = frozenset({"BTC", "ETH"})
ALLOWED_PROJECT_SYMBOLS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
ALLOWED_FREQTRADE_PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")


def _base_asset(value: str) -> str:
    normalized = (value or "").strip().upper().replace("_", "-")
    aliases = {
        "BTC": "BTC",
        "BTCUSDT": "BTC",
        "BTC-USDT": "BTC",
        "BTC-USDT-SWAP": "BTC",
        "BTC/USDT": "BTC",
        "BTC/USDT:USDT": "BTC",
        "ETH": "ETH",
        "ETHUSDT": "ETH",
        "ETH-USDT": "ETH",
        "ETH-USDT-SWAP": "ETH",
        "ETH/USDT": "ETH",
        "ETH/USDT:USDT": "ETH",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported trading symbol {value!r}; only BTC-USDT-SWAP and "
            "ETH-USDT-SWAP are allowed."
        ) from exc


def normalize_project_symbol(value: str) -> str:
    """Return the canonical project symbol or fail closed."""

    return f"{_base_asset(value)}-USDT-SWAP"


def normalize_freqtrade_pair(value: str) -> str:
    """Return the canonical Binance USDT perpetual pair or fail closed."""

    return f"{_base_asset(value)}/USDT:USDT"


def _normalize_many(values: Iterable[str], normalizer) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        normalized = normalizer(value)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if not result:
        raise ValueError("At least one BTC or ETH trading symbol is required.")
    return result


def normalize_project_symbols(values: Iterable[str]) -> List[str]:
    return _normalize_many(values, normalize_project_symbol)


def normalize_freqtrade_pairs(values: Iterable[str]) -> List[str]:
    return _normalize_many(values, normalize_freqtrade_pair)
