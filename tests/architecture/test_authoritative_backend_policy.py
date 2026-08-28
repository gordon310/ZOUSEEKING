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


MIGRATION_POLICY_PATH = ROOT / "supabase/migrations/README.md"
LEGACY_SQL_POLICY_PATH = ROOT / "backend/sql/README.md"


def test_migration_policy_blocks_v1_until_reconciliation() -> None:
    text = MIGRATION_POLICY_PATH.read_text(encoding="utf-8")

    assert "唯一前向迁移历史" in text
    assert "20260825000400_property_intake.sql" in text
    assert "依赖尚未进入迁移历史的基础表" in text
    assert "migration_baseline_status = reconciliation_required" in text
    assert "基线协调完成前，不得增加 V1 业务迁移" in text
    assert "不得执行 linked repair、db push 或 production reset" in text


def test_backend_sql_is_non_authoritative_reference() -> None:
    text = LEGACY_SQL_POLICY_PATH.read_text(encoding="utf-8")

    assert "backend/sql/ 不是迁移历史" in text
    assert "backend/sql/schema.sql" in text
    assert "backend/sql/supabase_schema.sql" in text
    assert "backend/sql/001_foundation_data_contract.sql" in text
    assert "新 schema 变更只能新增到 supabase/migrations/" in text


INVENTORY_PATH = ROOT / "docs/architecture/runtime-conflict-inventory.md"
SPEC_PATH = (
    ROOT
    / "docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md"
)


def test_conflict_inventory_covers_every_frozen_component() -> None:
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    policy = load_policy()

    for component in policy["frozen_legacy_components"]:
        path = component.split(":", 1)[0]
        assert path in inventory
    assert "docs/supabase-setup.md" in inventory
    assert "backend/sql/" in inventory
    assert "supabase/migrations/" in inventory
    assert "不得承载 V1 新功能" in inventory


def test_approved_spec_links_to_adr_without_losing_core_rules() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "**状态：** 产品规则已确认；架构采用 ADR-0001" in text
    assert "adr-0001-authoritative-backend-and-schema.md" in text
    assert "C Plus／月" in text
    assert "B Data Pro／月" in text
    assert "平台不参与报价、议价、付款、佣金、托管、发票或任务费用退款" in text
