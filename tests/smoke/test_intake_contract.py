from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
INTAKE_JS = [WEB / "js" / "api-client.js", WEB / "js" / "property-intake.js"]


def test_frontend_never_contains_service_role_or_owner_assignment():
    # The legacy regional-data bundle remains a separate migration surface. This
    # contract covers only the new FastAPI-only property-intake bundle.
    content = "\n".join(path.read_text(encoding="utf-8") for path in INTAKE_JS)

    assert "SUPABASE_SERVICE_ROLE_KEY" not in content
    assert "owner_user_id" not in content


def test_intake_page_uses_session_storage_not_local_storage():
    content = (WEB / "js" / "property-intake.js").read_text(encoding="utf-8")

    assert "sessionStorage" in content
    assert "localStorage" not in content
