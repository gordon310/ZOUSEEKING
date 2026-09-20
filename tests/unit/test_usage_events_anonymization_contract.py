from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_forward_migration_allows_only_auth_delete_anonymization() -> None:
    migration = ROOT / "supabase/migrations/20260920000100_usage_events_anonymization_allowance.sql"
    text = migration.read_text(encoding="utf-8")

    assert "new.actor_user_id is null" in text.lower()
    assert "old.scope_key is not distinct from new.scope_key" in text.lower()
    assert "old.created_at is not distinct from new.created_at" in text.lower()
    assert "usage_events is append-only; update is forbidden" in text
    assert "usage_events is append-only; delete is forbidden" in text


def test_member_read_views_are_security_invoker_and_frontend_uses_them() -> None:
    migration = ROOT / "supabase/migrations/20260920000200_member_read_security_invoker_views.sql"
    text = migration.read_text(encoding="utf-8").lower()
    frontend = (ROOT / "web/app.js").read_text(encoding="utf-8")

    for view in ("member_queries", "member_property_reports", "member_profiles"):
        assert f"create or replace view public.{view}" in text
        assert f"alter view public.{view} set (security_invoker = true)" in text
        assert f"grant select on public.{view} to authenticated, service_role" in text
        assert f"revoke all on public.{view} from public, anon" in text

    assert "/member_queries?select=" in frontend
    assert "/member_property_reports?select=" in frontend
    assert "/member_profiles?select=" in frontend


def test_account_deletion_ledger_does_not_block_auth_delete() -> None:
    migration = ROOT / "supabase/migrations/20260920000300_account_deletion_request_auth_anonymization.sql"
    text = migration.read_text(encoding="utf-8").lower()

    assert "alter column user_id drop not null" in text
    assert "on delete set null" in text
