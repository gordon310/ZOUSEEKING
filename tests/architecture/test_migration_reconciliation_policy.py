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


def test_local_canonical_history_does_not_open_the_live_write_gate():
    """Local success must remain distinct from linked/staging authorization."""
    statuses = _gate_statuses()

    assert statuses["fresh_reset"] == "pass"
    assert statuses["schema_assertions"] == "pass"
    assert statuses["rls_identity_matrix"] == "pass"
    assert statuses["canonical_history"] == "selected"
    assert statuses["retained_photo_address_migration"] == "pass"
    assert statuses["policy_version_choice"] == "gist_exclusion"
    assert statuses["staging_inventory"] == "pass"
    assert statuses["drift_review"] == "pass"
    assert statuses["blocking_drift"] == "present"
    assert statuses["schema_only_dump"] == "blocked"
    assert statuses["forward_fix"] == "blocked"
    assert statuses["backup_restore"] == "blocked"
    assert statuses["live_write_approval"] == "required"
    assert statuses["production_reset"] == "forbidden"
    assert (
        statuses["migration_baseline_status"]
        == "canonical_local_pass_live_reconciliation_required"
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
    ):
        assert marker in text
