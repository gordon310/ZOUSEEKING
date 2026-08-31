from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_render_staging_does_not_provision_a_second_database():
    render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "databases:" not in render_config
    assert "zouseeking-api-staging" in render_config
    assert "zouseeking-web-staging" in render_config


def test_render_staging_declares_consumer_intake_preview_release_phase():
    render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "RELEASE_PHASE" in render_config
    assert "consumer_intake_preview" in render_config


def test_frontend_does_not_contain_service_role_key():
    for path in (ROOT / "web").rglob("*.js"):
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert "service_role" not in content
        assert "SUPABASE_SERVICE_ROLE_KEY" not in content


def test_frontend_release_config_does_not_pin_a_managed_supabase_project():
    config = (ROOT / "web/config.js").read_text(encoding="utf-8")

    assert "supabase.co" not in config
