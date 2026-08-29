from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.auth import AuthUser, require_user
from backend.app.main import app


OWNER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000031")
JOB_ID = UUID("00000000-0000-0000-0000-000000000050")
QUERY_ID = UUID("00000000-0000-0000-0000-000000000051")


def job_row(owner_user_id: UUID = OWNER_ID, status: str = "pending") -> dict:
    return {
        "id": JOB_ID,
        "query_id": QUERY_ID,
        "owner_user_id": owner_user_id,
        "status": status,
        "progress": 5,
        "current_step": "任务已创建",
        "error_message": None,
        "prefecture": "大阪府",
        "city": "大阪市",
        "ward": "北区",
        "asset_type": "塔楼",
        "year": 2026,
        "month": 8,
    }


class FakeConnection:
    def __init__(self, row: dict):
        self.row = row
        self.executed: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args):
        if "update generation_jobs" in query.lower():
            job_id, owner_user_id = args
            if (
                str(self.row["id"]) == str(job_id)
                and self.row["owner_user_id"] == owner_user_id
                and self.row["status"] in {"pending", "failed"}
            ):
                self.row.update(status="running", progress=20, current_step="检查本地历史数据")
                return dict(self.row)
            return None
        if len(args) >= 2 and str(self.row["id"]) == str(args[0]) and self.row["owner_user_id"] != args[1]:
            return None
        return dict(self.row)

    async def execute(self, query: str, *args):
        self.executed.append((query, args))


class FakeAcquire:
    def __init__(self, connection: FakeConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, row: dict):
        self.connection = FakeConnection(row)

    def acquire(self):
        return FakeAcquire(self.connection)


def test_owner_can_start_pending_legacy_job_through_fastapi(monkeypatch):
    pool = FakePool(job_row())
    scheduled: list[tuple] = []

    async def fake_run_generation_job(*args):
        scheduled.append(args)

    monkeypatch.setattr(main, "get_pool", lambda: pool)
    monkeypatch.setattr(main, "run_generation_job", fake_run_generation_job)
    app.dependency_overrides[require_user] = lambda: AuthUser(OWNER_ID, "owner@example.com", "用户 A")
    try:
        response = TestClient(app).post(f"/api/jobs/{JOB_ID}/run")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert len(scheduled) == 1
    assert scheduled[0][:3] == (str(JOB_ID), str(QUERY_ID), str(OWNER_ID))
    assert scheduled[0][3].model_dump() == {
        "prefecture": "大阪府",
        "city": "大阪市",
        "ward": "北区",
        "asset_type": "塔楼",
        "year": 2026,
        "month": 8,
        "username": "用户 A",
    }


def test_other_user_cannot_start_legacy_job(monkeypatch):
    pool = FakePool(job_row())
    scheduled: list[tuple] = []

    async def fake_run_generation_job(*args):
        scheduled.append(args)

    monkeypatch.setattr(main, "get_pool", lambda: pool)
    monkeypatch.setattr(main, "run_generation_job", fake_run_generation_job)
    app.dependency_overrides[require_user] = lambda: AuthUser(OTHER_ID, "other@example.com", "用户 B")
    try:
        response = TestClient(app).post(f"/api/jobs/{JOB_ID}/run")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert scheduled == []
