from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.auth import AuthUser
from backend.app.services.account_deletion import ControlledDeletionExecutor


USER = AuthUser(
    UUID("00000000-0000-0000-0000-000000000042"),
    "member@example.invalid",
    "Member",
    access_token="access-token-for-test",
)
NOW = datetime(2026, 9, 15, 1, 2, 3, tzinfo=timezone.utc)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.existing = None
        self.inserted = {
            "id": UUID("00000000-0000-0000-0000-000000000099"),
            "status": "pending",
            "policy_version": "privacy-2026-08",
            "terms_version": "terms-2026-08",
            "requested_at": NOW,
            "acknowledgement_due": datetime(2026, 9, 16, 1, 2, 3, tzinfo=timezone.utc),
            "access_restriction_due": datetime(2026, 9, 16, 1, 2, 3, tzinfo=timezone.utc),
            "primary_data_deletion_due": datetime(2026, 10, 15, 1, 2, 3, tzinfo=timezone.utc),
            "backup_expiry_due": datetime(2026, 12, 14, 1, 2, 3, tzinfo=timezone.utc),
        }

    def transaction(self):
        return FakeTransaction()

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "from public.account_deletion_requests" in query and "insert" not in query:
            return self.existing
        if "insert into public.account_deletion_requests" in query:
            return self.inserted
        if "status='completed'" in query:
            return dict(self.inserted, status="completed")
        return None

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "UPDATE 1"


class FakePool:
    def __init__(self):
        self.connection = FakeConnection()

    def acquire(self):
        pool = self

        class Acquire:
            async def __aenter__(self):
                return pool.connection

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return Acquire()


class FakeAuthAdmin:
    def __init__(self):
        self.calls = []

    def is_configured(self):
        return True

    async def revoke_all_sessions(self, user_id, access_token):
        self.calls.append(("revoke", user_id, access_token))

    async def anonymize_user(self, user_id):
        self.calls.append(("anonymize", user_id))


@pytest.mark.asyncio
async def test_submit_registers_then_revokes_and_anonymizes_and_completes():
    pool = FakePool()
    admin = FakeAuthAdmin()
    executor = ControlledDeletionExecutor(pool=pool, auth_admin=admin)

    receipt = await executor.submit(USER, requested_at=NOW)

    assert receipt["status"] == "completed"
    assert set(receipt) == {
        "status", "request_id", "policy_version", "terms_version", "requested_at",
        "acknowledgement_due", "access_restriction_due", "primary_data_deletion_due",
        "backup_expiry_due",
    }
    assert admin.calls == [("revoke", USER.user_id, USER.access_token), ("anonymize", USER.user_id)]
    assert any("status='completed'" in call[1] for call in pool.connection.calls if call[0] == "fetchrow")


@pytest.mark.asyncio
async def test_submit_is_idempotent_for_existing_completed_request():
    pool = FakePool()
    pool.connection.existing = dict(pool.connection.inserted, status="completed")
    admin = FakeAuthAdmin()
    executor = ControlledDeletionExecutor(pool=pool, auth_admin=admin)

    receipt = await executor.submit(USER, requested_at=NOW)

    assert receipt["status"] == "completed"
    assert admin.calls == []
    assert not any("insert into public.account_deletion_requests" in call[1] for call in pool.connection.calls)
