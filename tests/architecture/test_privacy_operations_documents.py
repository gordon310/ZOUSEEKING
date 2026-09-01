from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_privacy_operations_documents_define_versions_slas_and_unresolved_owner():
    required = {
        ROOT / "docs/legal/privacy-policy.md": (
            "privacy-2026-08",
            "operator_identity_status = unresolved",
            "资料主体",
            "保留",
        ),
        ROOT / "docs/legal/terms-of-service.md": (
            "terms-2026-08",
            "估算",
            "责任",
            "客服",
        ),
        ROOT / "docs/legal/privacy-operations-runbook.md": (
            "24 小时",
            "30 天",
            "90 天",
            "migration_baseline_status = reconciliation_required",
        ),
        ROOT / "docs/legal/data-subject-request-process.md": (
            "查阅",
            "更正",
            "删除",
            "30 天",
        ),
        ROOT / "docs/legal/incident-response.md": (
            "4 小时",
            "遏制",
            "通知决定",
            "不发送通知",
        ),
    }
    for path, markers in required.items():
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{marker!r} missing from {path}"


def test_legal_and_support_pages_are_static_and_do_not_contain_secrets_or_real_pii():
    for filename in ("privacy.html", "terms.html", "support.html"):
        text = (ROOT / "web" / filename).read_text(encoding="utf-8")
        assert "privacy-2026-08" in text or "terms-2026-08" in text
        assert "support@zouseeking.example" in text
        assert "service_role" not in text.lower()
        assert "Bearer " not in text
        assert "no real customer data" in text.lower() or "不含真实客户资料" in text


def test_setup_docs_record_the_offline_auth_and_deletion_boundary():
    backend_readme = (ROOT / "backend" / "README.md").read_text(encoding="utf-8")
    supabase_setup = (ROOT / "docs" / "supabase-setup.md").read_text(encoding="utf-8")

    for text in (backend_readme, supabase_setup):
        assert "privacy-2026-08" in text
        assert "/api/account/deletion-request" in text
        assert "no account data was changed" in text
        assert "migration_baseline_status = reconciliation_required" in text
        assert "不发送" in text or "不会发送" in text

    assert "Auth Admin" in supabase_setup
    assert "所有 refresh token" in supabase_setup
