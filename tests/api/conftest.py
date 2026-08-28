from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.intake.completeness import FieldValue, build_free_preview
from backend.app.intake.geocoding import AddressCandidate
from backend.app.intake.models import ConfirmFieldRequest, CreateInputRequest, FIELD_UNITS
from backend.app.intake.repository import ConvertedProject, DuplicateAddress, ProjectNameTaken, SessionNotFound
from backend.app.intake.storage import StorageObject
from backend.app.main import app
from backend.app.routes.intake import get_intake_repository, get_reverse_geocoder, get_storage


TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")
PROPERTY_ID = UUID("00000000-0000-0000-0000-000000000020")
FIXED_NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self):
        self.sessions: Dict[UUID, dict] = {}
        self.inputs: List[dict] = []
        self.fields: Dict[UUID, Dict[str, dict]] = {}
        self.previews: Dict[UUID, dict] = {}
        self.created_properties: List[dict] = []
        self.rate_counts: Dict[tuple, int] = {}
        self.reverse_geocoder_result = AddressCandidate(
            address="大阪府大阪市北区梅田",
            source="gsi_reverse_geocoder",
            precision="town",
        )
        self.duplicate_address = False
        self.project_name_taken = False

    async def create_session(self, purpose, consent_version, token_hash, expires_at):
        session_id = uuid4()
        session = {
            "id": session_id,
            "purpose": purpose,
            "consent_version": consent_version,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "owner_user_id": None,
            "property_id": None,
            "status": "draft",
        }
        self.sessions[session_id] = session
        self.fields[session_id] = {}
        return session

    async def require_session(self, session_id, token_hash):
        session = self.sessions.get(session_id)
        if not session or session["token_hash"] != token_hash:
            raise SessionNotFound()
        if session["status"] != "converted" and session["expires_at"] <= FIXED_NOW:
            raise SessionNotFound()
        return session

    async def add_input(self, session_id, request, **kwargs):
        item = {
            "id": uuid4(),
            "session_id": session_id,
            "input_type": request.input_type,
            "source_url": request.source_url,
            "raw_text": request.raw_text,
            "processing_status": "manual_review",
            **kwargs,
        }
        self.inputs.append(item)
        return item

    async def add_file_input(self, session_id, storage_object):
        item = {
            "id": uuid4(),
            "session_id": session_id,
            "input_type": "pdf" if storage_object.media_type == "application/pdf" else "image",
            "storage_path": storage_object.path,
            "original_name": storage_object.original_name,
            "media_type": storage_object.media_type,
            "size_bytes": storage_object.size_bytes,
            "content_hash": storage_object.content_hash,
            "processing_status": "pending",
        }
        self.inputs.append(item)
        return item

    async def upsert_field(self, session_id, request: ConfirmFieldRequest):
        if request.source_input_id and not any(
            item["id"] == request.source_input_id and item["session_id"] == session_id
            for item in self.inputs
        ):
            raise SessionNotFound()
        item = {
            "field_name": request.field_name,
            "confirmed_value": request.value,
            "unit": request.unit,
            "confirmation_status": request.confirmation_status,
            "source_input_id": request.source_input_id,
            "locator": request.locator,
            "confidence": "unreviewed",
            "has_evidence": request.source_input_id is not None,
        }
        self.fields[session_id][request.field_name] = item
        return item

    async def get_fields(self, session_id):
        return {
            name: FieldValue(
                value=item["confirmed_value"],
                confirmation_status=item["confirmation_status"],
                confidence=item["confidence"],
                has_evidence=item["has_evidence"],
            )
            for name, item in self.fields[session_id].items()
        }

    async def save_preview(self, session_id, preview):
        self.previews[session_id] = preview
        self.sessions[session_id]["status"] = "preview_ready"
        self.sessions[session_id]["purpose_locked_at"] = FIXED_NOW
        return preview

    async def save_location(self, session_id, request, candidate):
        session = self.sessions[session_id]
        session.update(
            {
                "latitude": request.latitude,
                "longitude": request.longitude,
                "location_accuracy_m": request.accuracy_m,
                "location_captured_at": request.captured_at,
                "location_source": request.source,
                "address_candidate": candidate.address if candidate else "",
                "address_source": candidate.source if candidate else "unavailable",
                "address_precision": candidate.precision if candidate else "",
            }
        )
        return session

    async def convert_to_user(self, session_id, token_hash, user_id, project_name=None):
        session = await self.require_session(session_id, token_hash)
        if session["owner_user_id"] is not None:
            if session["owner_user_id"] == user_id:
                return ConvertedProject(user_id, session["property_id"])
            raise SessionNotFound()
        if session["status"] != "preview_ready":
            raise SessionNotFound()
        if self.duplicate_address and not project_name:
            raise DuplicateAddress()
        if self.project_name_taken:
            raise ProjectNameTaken()
        session["owner_user_id"] = user_id
        session["property_id"] = PROPERTY_ID
        session["status"] = "converted"
        self.created_properties.append(
            {"id": PROPERTY_ID, "owner_user_id": user_id, "project_name": project_name or "大阪市北区梅田"}
        )
        return ConvertedProject(user_id, PROPERTY_ID)

    async def get_project(self, property_id, user_id):
        for item in self.created_properties:
            if item["id"] == property_id and item["owner_user_id"] == user_id:
                return item
        raise SessionNotFound()

    async def consume_rate_limit(self, abuse_key_hash, action, window_started_at, limit, expires_at):
        key = (abuse_key_hash, action, window_started_at)
        current = self.rate_counts.get(key, 0)
        if current >= limit:
            return None
        self.rate_counts[key] = current + 1
        return current + 1

    async def expire_sessions(self, limit=100):
        return []


class FakeStorage:
    def __init__(self):
        self.uploads = []
        self.deleted = []

    def upload_private_file(self, session_id, filename, media_type, content):
        object_path = f"{session_id}/synthetic-{len(self.uploads) + 1}.pdf"
        result = StorageObject(object_path, filename, media_type, len(content), "b" * 64)
        self.uploads.append(result)
        return result

    def delete_private_file(self, path):
        self.deleted.append(path)


class FakeReverseGeocoder:
    def __init__(self):
        self.result = AddressCandidate(
            address="大阪府大阪市北区梅田",
            source="gsi_reverse_geocoder",
            precision="town",
        )
        self.error = None

    def reverse_geocode(self, latitude, longitude):
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ABUSE_HASH_SALT", "test-salt")


@pytest.fixture
def fake_repository():
    return FakeRepository()


@pytest.fixture
def fake_storage():
    return FakeStorage()


@pytest.fixture
def fake_geocoder():
    geocoder = FakeReverseGeocoder()
    app.dependency_overrides[get_reverse_geocoder] = lambda: geocoder
    yield geocoder
    app.dependency_overrides.pop(get_reverse_geocoder, None)


@pytest.fixture
def client(fake_repository, fake_storage):
    app.dependency_overrides[get_intake_repository] = lambda: fake_repository
    app.dependency_overrides[get_storage] = lambda: fake_storage
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_header():
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "test@example.com", "测试用户")
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def other_auth_header():
    return {"Authorization": "Bearer other-token"}


@pytest.fixture
def use_other_auth_user():
    def apply_other_user():
        app.dependency_overrides[require_user] = lambda: AuthUser(
            OTHER_USER_ID, "other@example.com", "其他用户"
        )

    return apply_other_user


@pytest.fixture
def session(client):
    response = client.post(
        "/api/intake/sessions",
        json={"purpose": "self_use", "consent_version": "privacy-2026-08"},
    )
    assert response.status_code == 201
    return response.json()
