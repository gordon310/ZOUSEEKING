"""Canonical property asset-type values and accepted request aliases."""

from __future__ import annotations

from typing import Literal


AssetType = Literal["塔楼", "公寓", "一户建"]

_ASSET_TYPE_ALIASES = {
    "tower": "塔楼",
    "apartment": "公寓",
    "condo": "公寓",
    "house": "一户建",
    "detached_house": "一户建",
    "detached-house": "一户建",
    "detached house": "一户建",
    "一戸建て": "一户建",
    "戸建て": "一户建",
}


def normalize_asset_type(value: object) -> object:
    """Return the canonical Chinese value for a supported alias."""

    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if normalized in {"塔楼", "公寓", "一户建"}:
        return normalized
    return _ASSET_TYPE_ALIASES.get(normalized.casefold(), normalized)
