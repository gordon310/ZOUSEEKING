"""Small, allow-listed helpers for Auth user metadata."""

from __future__ import annotations

from typing import Any, Mapping, Optional


def audience_from_user_metadata(metadata: Optional[Mapping[str, Any]]) -> str:
    """Return the only profile audiences accepted at signup."""
    return "b" if str((metadata or {}).get("audience") or "").strip() == "b" else "c"
