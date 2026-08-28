from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from backend.app.intake.geocoding import AddressCandidate
from backend.app.intake.models import LocationRequest
from backend.app.intake.repository import IntakeRepository, SessionNotFound, normalize_address
from backend.app.intake.repository import DuplicateAddress


SESSION_ID = UUID("00000000-0000-0000-0000-000000000010")
PROPERTY_ID = UUID("00000000-0000-0000-0000-000000000020")
USER_ID = UUID("00000000-0000-0000-0000-000000000030")
TOKEN_HASH = "a" * 64


def test_normalize_address_collapses_japanese_whitespace():
    assert normalize_address(" 大阪府　大阪市北区  梅田 ") == "大阪府大阪市北区梅田"


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


class LocationConnection(RecordingConnection):
    async def fetchrow(self, query, *args):
        self._record(query, args)
        if "for update" in query.lower():
            return self.session
        if "update public.analysis_sessions" in query.lower():
            saved = dict(self.session)
            saved.update(
                {
                    "latitude": args[1],
                    "longitude": args[2],
                    "location_accuracy_m": args[3],
                    "location_source": args[4],
                    "location_captured_at": args[5],
                    "address_candidate": args[7],
                    "address_source": args[8],
                    "address_precision": args[9],
                }
            )
            return saved
        return None


class ConversionConnection(RecordingConnection):
    def __init__(self, session, field_rows, duplicate_address=False):
        super().__init__(session)
        self.field_rows = field_rows
        self.duplicate_address = duplicate_address

    async def fetch(self, query, *args):
        self._record(query, args)
        return self.field_rows

    async def fetchval(self, query, *args):
        self._record(query, args)
        lowered = query.lower()
        if "insert into public.properties" in lowered:
            return PROPERTY_ID
        if "address_normalized" in lowered and self.duplicate_address:
            return 1
        return None


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

    result = await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID, "大阪市北区梅田")

    assert "for update" in connection.queries[0].lower()
    assert USER_ID in connection.arguments
    assert result.owner_user_id == USER_ID
    assert result.property_id == PROPERTY_ID
    assert connection.transaction_committed


@pytest.mark.asyncio
async def test_save_location_persists_candidate_metadata():
    connection = LocationConnection(
        session={
            "id": SESSION_ID,
            "status": "preview_ready",
            "owner_user_id": None,
            "property_id": None,
        }
    )
    repository = IntakeRepository(FakePool(connection))
    request = LocationRequest(
        latitude=34.7025,
        longitude=135.4959,
        accuracy_m=18.5,
        captured_at="2026-08-28T03:30:00Z",
        consent_version="location-2026-08",
    )

    saved = await repository.save_location(
        SESSION_ID,
        request,
        AddressCandidate("大阪府大阪市北区梅田", "gsi_reverse_geocoder", "town"),
    )

    assert saved["latitude"] == 34.7025
    assert saved["address_candidate"] == "大阪府大阪市北区梅田"
    assert saved["address_source"] == "gsi_reverse_geocoder"


@pytest.mark.asyncio
async def test_duplicate_default_address_is_rejected_before_property_insert():
    connection = ConversionConnection(
        session={
            "id": SESSION_ID,
            "status": "preview_ready",
            "owner_user_id": None,
            "property_id": None,
            "purpose": "self_use",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        field_rows=[{"field_name": "address", "confirmed_value": '大阪府　大阪市北区  梅田'}],
        duplicate_address=True,
    )
    repository = IntakeRepository(FakePool(connection))

    with pytest.raises(DuplicateAddress):
        await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)

    assert not any("insert into public.properties" in query.lower() for query in connection.queries)


@pytest.mark.asyncio
async def test_expired_or_already_owned_session_cannot_be_claimed():
    repository = IntakeRepository(FakePool(RecordingConnection(session=None)))

    with pytest.raises(SessionNotFound):
        await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)
