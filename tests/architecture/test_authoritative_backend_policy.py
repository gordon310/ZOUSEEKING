from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = ROOT / "docs/architecture/adr-0001-authoritative-backend-and-schema.md"
POLICY_PATH = ROOT / "docs/architecture/authoritative-boundaries.json"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_manifest_selects_one_authoritative_path() -> None:
    policy = load_policy()

    assert policy == {
        "decision_id": "ADR-0001",
        "status": "accepted",
        "identity_issuer": "supabase_auth",
        "private_product_boundary": "fastapi",
        "database": "supabase_postgres",
        "forward_migration_history": "supabase/migrations",
        "payment_webhook_boundary": "fastapi_verified_webhook_then_outbox",
        "background_execution": "postgres_job_outbox_single_worker",
        "migration_baseline_status": "reconciliation_required",
        "allowed_browser_supabase_surfaces": [
            "auth/v1",
            "rest/v1/query_field_options:select",
        ],
        "frozen_legacy_components": [
            "web/app.js:direct_private_supabase_and_edge_fallback",
            "supabase/functions/jphouse-run:regional_report_edge_executor",
            "scripts/run_jphouse_worker.py:regional_report_rest_worker",
            "backend/app/main.py:in_process_regional_report_executor",
        ],
    }


def test_adr_records_non_overlapping_responsibilities() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")

    required = (
        "状态：Accepted",
        "Supabase Auth 是唯一身份签发方",
        "FastAPI 是所有私有产品读写的唯一应用边界",
        "`supabase/migrations/` 是唯一前向迁移历史",
        "支付 webhook 先验签，再写入去重事件与 outbox",
        "一个 PostgreSQL-backed durable worker",
        "migration_baseline_status = reconciliation_required",
    )
    for statement in required:
        assert statement in text
