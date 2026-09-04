from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/architecture/adr-0002-render-postgres-future-migration.md"
DEPLOY_DOC = ROOT / "docs/render-postgres-deploy.md"
RENDER_CONFIG = ROOT / "render.yaml"


def test_render_postgres_adr_covers_requested_decision_axes_and_gates() -> None:
    text = ADR.read_text(encoding="utf-8")

    for marker in (
        "状态：Accepted（暂缓，非迁移批准）",
        "auth.uid()",
        "Supabase Auth",
        "Storage",
        "备份",
        "恢复",
        "RPO",
        "RTO",
        "跨地区",
        "连接池",
        "PgBouncer",
        "回滚",
        "成本",
        "停机窗口",
        "不迁移条件",
        "canonical_staging_reconciled_production_pending",
        "live_write_approval=required",
        "production_reset=forbidden",
        "staging 不等于 production",
    ):
        assert marker in text


def test_render_postgres_adr_keeps_current_staging_path_non_operational() -> None:
    text = ADR.read_text(encoding="utf-8")

    for marker in (
        "不得更换 `DATABASE_URL`",
        "不得创建 Render PostgreSQL",
        "不得迁移数据",
        "不执行线上数据库、Auth、RLS、Storage 或部署操作",
        "docs/render-postgres-deploy.md",
    ):
        assert marker in text


def test_render_deploy_doc_no_longer_claims_blueprint_creates_a_database() -> None:
    text = DEPLOY_DOC.read_text(encoding="utf-8")

    assert "未来迁移评估" in text
    assert "Blueprint 不会创建 PostgreSQL" in text
    assert "Render 会创建：" not in text


def test_current_render_config_remains_staging_without_database_resource() -> None:
    text = RENDER_CONFIG.read_text(encoding="utf-8")

    assert "zouseeking-api-staging" in text
    assert "ENVIRONMENT" in text and "staging" in text
    assert "INIT_SCHEMA" in text and 'value: "false"' in text
    assert "DATABASE_URL" in text and "sync: false" in text
    assert "databases:" not in text
