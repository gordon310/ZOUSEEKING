from datetime import datetime, timezone

import pytest

from backend.app.usage.quota import (
    current_period_key,
    select_live_entitlement,
)


def test_current_period_key_uses_utc8_calendar_boundary() -> None:
    assert current_period_key(datetime(2026, 8, 31, 15, 59, tzinfo=timezone.utc), "day") == "2026-08-31"
    assert current_period_key(datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc), "day") == "2026-09-01"
    assert current_period_key(datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc), "month") == "2026-09"


def test_select_live_entitlement_prefers_active_latest_effective_row() -> None:
    rows = [
        {"metric": "report", "period": "month", "limit_units": 12, "active": True, "effective_from": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"metric": "report", "period": "month", "limit_units": 5, "active": False, "effective_from": datetime(2026, 9, 2, tzinfo=timezone.utc)},
        {"metric": "report", "period": "month", "limit_units": 7, "active": True, "effective_from": datetime(2026, 8, 1, tzinfo=timezone.utc)},
    ]
    assert select_live_entitlement(rows, "report", "month") == 12


def test_select_live_entitlement_returns_none_when_metric_is_not_configured() -> None:
    assert select_live_entitlement([], "free_preview", "month") is None

