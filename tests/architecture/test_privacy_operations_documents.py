import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_privacy_operations_documents_define_versions_slas_and_resolved_operator():
    required = {
        ROOT / "docs/legal/privacy-policy.md": (
            "privacy-2026-08",
            "operator_identity_status = resolved",
            "6120001261672",
            "canaanlife@goo.jp",
            "資料主體",
            "保留",
        ),
        ROOT / "docs/legal/terms-of-service.md": (
            "terms-2026-08",
            "估算",
            "責任",
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
    allowed_contact_emails = {
        "canaanlife@goo.jp",
        "support@zouseeking.example",
    }
    secret_patterns = (
        r"sk_live_[A-Za-z0-9_-]+",
        r"whsec_[A-Za-z0-9_-]+",
        r"service_role",
        r"Bearer\s+[A-Za-z0-9._~+/=-]+",
    )
    email_pattern = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    personal_name_address_pattern = re.compile(
        r"(?:姓名|代表取締役|联系人|聯絡人)\s*[:：为為]?\s*[\u4e00-\u9fff]{2,6}"
        r".{0,80}(?:个人住址|個人住址|自然人地址|自然人地址|家庭地址|住家地址)",
        re.IGNORECASE | re.DOTALL,
    )

    for filename in ("privacy.html", "terms.html", "support.html"):
        text = (ROOT / "web" / filename).read_text(encoding="utf-8")
        assert "privacy-2026-08" in text or "terms-2026-08" in text
        assert set(email_pattern.findall(text)) <= allowed_contact_emails
        for pattern in secret_patterns:
            assert not re.search(pattern, text, re.IGNORECASE)
        assert not personal_name_address_pattern.search(text)
        assert "<form" not in text.lower()
        assert "fetch(" not in text.lower()


def test_setup_docs_record_the_offline_auth_and_deletion_boundary():
    backend_readme = (ROOT / "backend" / "README.md").read_text(encoding="utf-8")
    supabase_setup = (ROOT / "docs" / "supabase-setup.md").read_text(encoding="utf-8")

    for text in (backend_readme, supabase_setup):
        assert "privacy-2026-08" in text
        assert "/api/account/deletion-request" in text
        assert "no account data was changed" in text
        assert "migration_baseline_status = canonical_staging_reconciled_production_pending" in text
        assert "不发送" in text or "不会发送" in text

    assert "Auth Admin" in supabase_setup
    assert "global logout/revocation" in supabase_setup
