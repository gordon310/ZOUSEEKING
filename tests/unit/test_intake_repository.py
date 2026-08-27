from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from backend.app.intake.repository import IntakeRepository, SessionNotFound


SESSION_ID = UUID("00000000-0000-0000-0000-000000000010")
PROPERTY_ID = UUID("00000000-0000-0000-0000-000000000020")
USER_ID = UUID("00000000-0000-0000-0000-000000000030")
TOKEN_HASH = "a" * 64


class RecordingTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.connection.transaction_committed = True
        return False


class RecordingConnection:
    def __init__(self, session):
        self.session = session
        self.queries = []
        self.arguments = []
        self.transaction_committed = False

    def transaction(self):
        return RecordingTransaction(self)

    def _record(self, query, args):
        self.queries.append(query)
        self.arguments.extend(args)

    async def fetchrow(self, query, *args):
        self._record(query, args)
        if "for update" in query.lower():
            return self.session
        return None

    async def fetchval(self, query, *args):
        self._record(query, args)
        if "insert into public.properties" in query.lower():
            return PROPERTY_ID
        return None

    async def fetch(self, query, *args):
        self._record(query, args)
        return []

    async def execute(self, query, *args):
        self._record(query, args)
        if "update public.analysis_sessions" in query.lower() and self.session is not None:
            self.session.update({"owner_user_id": args[0], "property_id": args[1], "status": "converted"})
        return "UPDATE 1"


class Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return Acquire(self.connection)


@pytest.mark.asyncio
async def test_conversion_locks_session_and_sets_owner_server_side():
    connection = RecordingConnection(
        session={
            "id": SESSION_ID,
            "status": "preview_ready",
            "owner_user_id": None,
            "property_id": None,
            "purpose": "self_use",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    )
    repository = IntakeRepository(FakePool(connection))

    result = await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)

    assert "for update" in connection.queries[0].lower()
    assert USER_ID in connection.arguments
    assert result.owner_user_id == USER_ID
    assert result.property_id == PROPERTY_ID
    assert connection.transaction_committed


@pytest.mark.asyncio
async def test_expired_or_already_owned_session_cannot_be_claimed():
    repository = IntakeRepository(FakePool(RecordingConnection(session=None)))

    with pytest.raises(SessionNotFound):
        await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)
