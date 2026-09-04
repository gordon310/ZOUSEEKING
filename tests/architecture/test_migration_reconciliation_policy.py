import re
from pathlib import Path


REPORT = Path("docs/architecture/migration-reconciliation-report.md")


def _gate_statuses() -> dict[str, str]:
    text = REPORT.read_text(encoding="utf-8")
    status_block = re.search(
        r"^## Gate status\n\n```text\n(?P<body>.*?)^```$",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert status_block, "missing Gate status block"
    return dict(
        line.split("=", 1)
        for line in status_block.group("body").splitlines()
        if line
    )


def test_staging_reconciliation_closes_m1_without_opening_production_gate():
    """Staging M1 evidence must remain distinct from production authorization."""
    statuses = _gate_statuses()

    assert statuses["fresh_reset"] == "pass"
    assert statuses["schema_assertions"] == "pass"
    assert statuses["rls_identity_matrix"] == "pass"
    assert statuses["staging_transaction_dry_run"] == "pass"
    assert statuses["canonical_history"] == "selected"
    assert statuses["retained_photo_address_migration"] == "pass"
    assert statuses["policy_version_choice"] == "gist_exclusion"
    assert statuses["staging_inventory"] == "pass"
    assert statuses["drift_review"] == "pass"
    assert statuses["blocking_drift"] == "cleared_by_20260902000100"
    assert (
        statuses["service_role_grant_portability"]
        == "pass_20260902000200"
    )
    assert statuses["logical_backup"] == "pass"
    assert statuses["isolated_restore"] == "pass"
    assert statuses["forward_fix"] == "pass"
    assert statuses["backup_restore"] == "pass"
    assert statuses["staging_rls_auth_storage"] == "pass"
    assert statuses["provider_physical_backup"] == "not_available_free"
    assert statuses["future_live_write_approval"] == "required"
    assert statuses["production_reset"] == "forbidden"
    assert (
        statuses["migration_baseline_status"]
        == "canonical_staging_reconciled_production_pending"
    )


def test_report_forbids_remote_shortcuts_and_distinguishes_staging_from_production():
    """The runbook must not turn a staging inventory into production evidence."""
    text = REPORT.read_text(encoding="utf-8")

    for marker in (
        "supabase db push",
        "supabase migration repair",
        "staging reset",
        "production reset",
        "staging 不是 production",
        "不得改写已应用 migration",
        "production database/Auth/Storage 未连接、未修改、未验证",
    ):
        assert marker in text
