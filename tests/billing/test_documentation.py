from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backend_runbook_has_disabled_by_default_billing_safety_contract() -> None:
    text = (ROOT / "backend/README.md").read_text(encoding="utf-8")

    required = (
        "BILLING_ENABLED",
        "默认关闭",
        "Stripe-Signature",
        "event.id",
        "不连接 live Stripe",
        "不产生真实收费",
    )
    for statement in required:
        assert statement in text


def test_supabase_runbook_keeps_billing_and_provider_rollout_gates_explicit() -> None:
    text = (ROOT / "docs/supabase-setup.md").read_text(encoding="utf-8")

    required = (
        "migration_baseline_status = reconciliation_required",
        "不得执行 linked repair、db push 或 production reset",
        "webhook",
        "Customer Portal",
        "provider backup/restore",
    )
    for statement in required:
        assert statement in text
