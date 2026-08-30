from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_render_staging_does_not_provision_a_second_database():
    render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "databases:" not in render_config
    assert "zouseeking-api-staging" in render_config
    assert "zouseeking-web-staging" in render_config


def test_frontend_does_not_contain_service_role_key():
    for path in (ROOT / "web").rglob("*.js"):
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert "service_role" not in content
        assert "SUPABASE_SERVICE_ROLE_KEY" not in content


def test_render_staging_allows_its_static_frontend_origin():
    render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "https://zouseeking-web-staging.onrender.com" in render_config
