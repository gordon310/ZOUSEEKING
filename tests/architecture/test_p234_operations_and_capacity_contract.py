from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_oncall_runbook_names_alerts_roles_and_change_boundary() -> None:
    text = (ROOT / "docs" / "operations" / "oncall.md").read_text(encoding="utf-8")
    for marker in ("health", "backup", "outbox", "quota", "webhook", "Hermes", "Codex", "最终决策", "只读", "授权变更"):
        assert marker in text


def test_invited_scope_capacity_baseline_is_machine_readable_and_budget_honest() -> None:
    report = json.loads((ROOT / "docs" / "operations" / "invited-scope-capacity-baseline-2026-09-23.json").read_text(encoding="utf-8"))
    assert report["scope"]["invited_users"] == {"minimum": 10, "maximum": 20}
    assert report["scope"]["geographies"] == ["东京23区", "大阪市"]
    assert report["first_month"]["expected"]["queries"]["maximum"] >= report["first_month"]["expected"]["reports"]["maximum"]
    assert report["budget_comparison"]["status"] == "pending_user_budget"
    assert report["production_contacted"] is False
