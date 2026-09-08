"""Currency conversion service (D5: JPY canonical + CNY/USD display).

Rates live in data/input/fx_rates.json as a dated, sourced snapshot (updated by
file replacement / future scheduled fetch - never hard-coded in code). JPY is the
canonical stored currency; conversions carry rate/as_of for provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FX_PATH = Path(__file__).resolve().parents[3] / "data" / "input" / "fx_rates.json"

_cache: dict[str, Any] | None = None


def load_fx() -> dict[str, Any] | None:
    global _cache
    if _cache is None:
        if not FX_PATH.exists():
            return None
        try:
            _cache = json.loads(FX_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return _cache


def convert_jpy(amount_yen: float | int | None, currency: str) -> dict[str, Any] | None:
    """Convert a JPY amount to a display currency with rate provenance.

    Returns None when the amount is missing, the currency is unsupported, or no
    dated rate snapshot is configured (callers must then omit the conversion
    rather than invent one).
    """
    if amount_yen is None:
        return None
    fx = load_fx()
    if fx is None:
        return None
    rate = fx.get("rates", {}).get(currency)
    if not rate:
        return None
    return {
        "currency": currency,
        "amount": round(amount_yen * float(rate)),
        "rate": float(rate),
        "as_of": fx.get("as_of"),
        "source": fx.get("source"),
        "version": fx.get("version"),
    }


def fx_provenance() -> dict[str, Any] | None:
    fx = load_fx()
    if fx is None:
        return None
    return {
        "as_of": fx.get("as_of"),
        "source": fx.get("source"),
        "version": fx.get("version"),
        "rates": fx.get("rates"),
    }
