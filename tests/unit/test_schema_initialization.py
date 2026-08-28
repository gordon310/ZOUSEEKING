import asyncio

from backend.app import main


def run_lifespan(monkeypatch):
    initialized = []

    async def fake_connect():
        return None

    async def fake_init_schema():
        initialized.append(True)

    async def fake_cleanup(*_args):
        return None

    async def fake_close():
        return None

    monkeypatch.setattr(main, "connect", fake_connect)
    monkeypatch.setattr(main, "init_schema", fake_init_schema)
    monkeypatch.setattr(main, "cleanup_expired_sessions", fake_cleanup)
    monkeypatch.setattr(main, "close", fake_close)
    monkeypatch.setattr(main, "get_pool", lambda: object())

    async def exercise():
        async with main.lifespan(main.app):
            pass

    asyncio.run(exercise())
    return initialized


def test_schema_initialization_is_disabled_when_not_configured(monkeypatch):
    monkeypatch.delenv("INIT_SCHEMA", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    assert run_lifespan(monkeypatch) == []


def test_schema_initialization_is_disabled_for_staging_even_when_requested(monkeypatch):
    monkeypatch.setenv("INIT_SCHEMA", "true")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    assert run_lifespan(monkeypatch) == []


def test_schema_initialization_requires_explicit_local_environment(monkeypatch):
    monkeypatch.setenv("INIT_SCHEMA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    assert run_lifespan(monkeypatch) == [True]
