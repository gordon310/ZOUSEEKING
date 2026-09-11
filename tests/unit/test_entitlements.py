from datetime import datetime, timezone

import pytest

from backend.app.billing.entitlements import (
    DEFAULT_ENTITLEMENTS,
    entitlement_limit,
    period_key,
)


def test_default_entitlements_cover_c_and_b_plans() -> None:
    assert entitlement_limit("free_c", "query", "day") == 3
    assert entitlement_limit("c_plus", "report", "month") == 12
    assert entitlement_limit("free_b", "stats_query", "month") == 5
    assert entitlement_limit("b_data_pro", "export_row", "month") == 10000


def test_period_key_uses_utc_plus_8_day_and_month_boundaries() -> None:
    before = datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
    assert period_key(before, "day") == "2026-08-31"
    assert period_key(after, "day") == "2026-09-01"
    assert period_key(after, "month") == "2026-09"


def test_db_entitlements_take_priority_over_legacy_and_defaults() -> None:
    rows = [{"metric": "query", "period": "month", "limit_units": 77, "active": True}]
    assert entitlement_limit("c_plus", "query", "month", rows=rows, legacy_limit=100) == 77


def test_invalid_period_is_rejected() -> None:
    with pytest.raises(ValueError):
        period_key(datetime.now(timezone.utc), "week")
