import asyncio
from pathlib import Path

from backend.app import main


ROOT = Path(__file__).resolve().parents[2]


def run_lifespan(monkeypatch):
    lifecycle_calls = []

    async def fake_connect():
        return None

    async def fake_cleanup(*_args):
        lifecycle_calls.append("cleanup")
        return None

    async def fake_close():
        return None

    monkeypatch.setattr(main, "connect", fake_connect)
    monkeypatch.setattr(main, "cleanup_expired_sessions", fake_cleanup)
    monkeypatch.setattr(main, "close", fake_close)
    monkeypatch.setattr(main, "get_pool", lambda: object())

    async def exercise():
        async with main.lifespan(main.app):
            pass

    asyncio.run(exercise())
    return lifecycle_calls


def test_application_lifespan_never_initializes_schema_even_when_legacy_env_is_set(monkeypatch):
    monkeypatch.setenv("INIT_SCHEMA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    assert run_lifespan(monkeypatch) == ["cleanup"]


def test_runtime_sources_do_not_expose_legacy_schema_bootstrap_or_ddl() -> None:
    db_source = (ROOT / "backend/app/db.py").read_text(encoding="utf-8").lower()
    main_source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8").lower()

    assert "init_schema" not in db_source
    assert "backend/sql" not in db_source
    assert "create table" not in db_source
    assert "init_schema" not in main_source
    assert "init_schema" not in main_source
    assert "create table" not in main_source
