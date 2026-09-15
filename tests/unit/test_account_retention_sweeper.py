from datetime import datetime, timedelta, timezone

import pytest

from scripts.account_retention_sweeper import (
    SweepSummary,
    is_due,
    plan_retention_actions,
    run_planned_actions,
    validate_limit,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)


def retention_row(**overrides):
    row = {
        "primary_data_deletion_due": NOW - timedelta(seconds=1),
        "backup_expiry_due": NOW - timedelta(seconds=1),
        "backup_expired_at": None,
    }
    row.update(overrides)
    return row


def test_is_due_requires_timezone_aware_values_and_includes_exact_deadline():
    assert is_due(NOW, NOW) is True
    assert is_due(NOW + timedelta(seconds=1), NOW) is False
    assert is_due(None, NOW) is False
    with pytest.raises(ValueError, match="timezone-aware"):
        is_due(datetime(2026, 9, 15), NOW)


@pytest.mark.parametrize("limit", [0, -1])
def test_validate_limit_rejects_non_positive_values(limit):
    with pytest.raises(ValueError, match="limit"):
        validate_limit(limit)


def test_plan_retention_actions_reports_each_due_action_once():
    assert plan_retention_actions(retention_row(), NOW) == (
        "verify_primary_data",
        "record_backup_expiry",
    )
    assert plan_retention_actions(
        retention_row(backup_expired_at=NOW - timedelta(seconds=1)), NOW
    ) == ("verify_primary_data",)


def test_run_planned_actions_honors_limit_and_dry_run_without_writes():
    writes = []
    rows = [retention_row(), retention_row(), retention_row()]

    summary = run_planned_actions(
        rows,
        now=NOW,
        limit=2,
        dry_run=True,
        record_backup_expiry=lambda row: writes.append(row),
    )

    assert summary == SweepSummary(scanned=2, primary_due=2, backup_recorded=0, failures=0)
    assert writes == []


def test_run_planned_actions_is_idempotent_when_record_is_conditional():
    row = retention_row()
    writes = []

    def record_backup_expiry(candidate):
        if candidate["backup_expired_at"] is None:
            candidate["backup_expired_at"] = NOW
            writes.append(NOW)
            return True
        return False

    first = run_planned_actions(
        [row], now=NOW, limit=50, dry_run=False, record_backup_expiry=record_backup_expiry
    )
    second = run_planned_actions(
        [row], now=NOW, limit=50, dry_run=False, record_backup_expiry=record_backup_expiry
    )

    assert first.backup_recorded == 1
    assert second.backup_recorded == 0
    assert writes == [NOW]
