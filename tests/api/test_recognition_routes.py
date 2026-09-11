from __future__ import annotations

import base64
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.recognition import service as recognition_service
from backend.app.intake.geocoding import AddressCandidate, ReverseGeocoderError


TEST_USER = AuthUser(UUID("00000000-0000-0000-0000-000000000030"), "member@example.com", "测试用户")
IMAGE = "data:image/jpeg;base64," + base64.b64encode(b"jpeg-fixture").decode()


@pytest.fixture(autouse=True)
def recognition_test_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RELEASE_PHASE", "development")
    monkeypatch.setenv("JPPSKILL_BASE_URL", "http://jpsskill.test")
    monkeypatch.setenv("RECOGNITION_AI_ENABLED", "false")
    app.dependency_overrides[require_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.clear()


def test_recognition_returns_ai_disabled_without_calling_upstream(monkeypatch):
    calls = []

    async def fake_analyze(image, note):
        calls.append((image, note))
        return {
            "matched_listing": None,
            "listing_candidates": [{"title": "梅田塔楼", "area": "大阪市北区", "url": "https://listing.test/1"}],
            "confidence": 0.82,
        }

    monkeypatch.setattr(recognition_service, "analyze", fake_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "note": "挂牌截图", "use_ai": True})

    assert response.status_code == 200
    assert response.json() == {
        "location": None,
        "location_reason": "no_exif_gps",
        "listing": None,
        "ai_disabled": True,
    }
    assert calls == []


def test_recognition_preserves_low_confidence_without_hard_match(monkeypatch):
    async def fake_analyze(_image, _note):
        return {"matched_listing": None, "listing_candidates": [], "confidence": 0.18}

    monkeypatch.setenv("RECOGNITION_AI_ENABLED", "true")
    monkeypatch.setattr(recognition_service, "analyze", fake_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "use_ai": True})

    assert response.status_code == 200
    assert response.json()["matched_listing"] is None
    assert response.json()["listing_candidates"] == []
    assert response.json()["confidence"] == 0.18


def test_recognition_rejects_oversized_decoded_image():
    oversized = "data:image/png;base64," + base64.b64encode(b"x" * (2 * 1024 * 1024 + 1)).decode()
    response = TestClient(app).post("/api/recognition", json={"image": oversized})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_image"


def test_recognition_maps_upstream_timeout_to_504(monkeypatch):
    async def fake_analyze(_image, _note):
        raise recognition_service.RecognitionUpstreamTimeout()

    monkeypatch.setenv("RECOGNITION_AI_ENABLED", "true")
    monkeypatch.setattr(recognition_service, "analyze", fake_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "use_ai": True})

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "recognition_upstream_timeout"


def test_recognition_requires_login():
    app.dependency_overrides.clear()
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE})

    assert response.status_code == 401


def test_recognition_resolves_exif_location_without_ai(monkeypatch):
    calls = []

    async def fake_resolve(_image):
        calls.append("location")
        return {
            "location": {
                "prefecture": "东京都",
                "city": "涩谷区",
                "ward": None,
                "latitude": 35.0,
                "longitude": 139.0,
                "source": "exif",
            },
            "location_reason": None,
        }

    async def fail_analyze(_image, _note):
        raise AssertionError("AI must not be called when use_ai=false")

    monkeypatch.setattr(recognition_service, "resolve_location", fake_resolve)
    monkeypatch.setattr(recognition_service, "analyze", fail_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "resolve_location_only": True})

    assert response.status_code == 200
    assert response.json()["location"]["source"] == "exif"
    assert response.json()["listing"] is None
    assert calls == ["location"]


def test_recognition_maps_exif_coordinates_through_gsi_without_ai(monkeypatch):
    class FakeGeocoder:
        def reverse_geocode(self, latitude, longitude):
            assert (latitude, longitude) == (35.675, 139.68333333333334)
            return AddressCandidate("東京都渋谷区神南", "gsi_reverse_geocoder", "town", "13113")

    monkeypatch.setattr(recognition_service, "parse_exif_gps", lambda _image: {
        "latitude": 35.675,
        "longitude": 139.68333333333334,
    })
    monkeypatch.setattr(recognition_service, "GsiReverseGeocoder", FakeGeocoder)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "resolve_location_only": True})

    assert response.status_code == 200
    assert response.json()["location"] == {
        "prefecture": "东京都",
        "city": "涩谷区",
        "ward": None,
        "latitude": 35.675,
        "longitude": 139.68333333333334,
        "source": "exif",
    }


def test_recognition_returns_no_exif_reason_without_ai(monkeypatch):
    async def fake_resolve(_image):
        return {"location": None, "location_reason": "no_exif_gps"}

    async def fail_analyze(_image, _note):
        raise AssertionError("AI must not be called when use_ai=false")

    monkeypatch.setattr(recognition_service, "resolve_location", fake_resolve)
    monkeypatch.setattr(recognition_service, "analyze", fail_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE})

    assert response.status_code == 200
    assert response.json()["location"] is None
    assert response.json()["location_reason"] == "no_exif_gps"
    assert response.json()["listing"] is None


def test_recognition_only_calls_ai_when_explicitly_enabled(monkeypatch):
    calls = []

    async def fake_resolve(_image):
        return {"location": None, "location_reason": "no_exif_gps"}

    async def fake_analyze(image, note):
        calls.append((image, note))
        return {"matched_listing": None, "listing_candidates": [], "confidence": 0.7}

    monkeypatch.setenv("RECOGNITION_AI_ENABLED", "true")
    monkeypatch.setattr(recognition_service, "resolve_location", fake_resolve)
    monkeypatch.setattr(recognition_service, "analyze", fake_analyze)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "note": "x", "use_ai": True})

    assert response.status_code == 200
    assert response.json()["listing"]["confidence"] == 0.7
    assert response.json()["confidence"] == 0.7
    assert calls == [(IMAGE, "x")]


def test_recognition_maps_jis_municipality_code_to_city_and_ward(monkeypatch):
    monkeypatch.setattr(recognition_service, "parse_exif_gps", lambda _image: {"latitude": 34.7, "longitude": 135.5})
    monkeypatch.setattr(
        recognition_service,
        "GsiReverseGeocoder",
        lambda: type("FakeGeocoder", (), {"reverse_geocode": lambda self, _lat, _lon: AddressCandidate("大阪府大阪市北区", "gsi_reverse_geocoder", "town", "27100")})(),
    )
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "resolve_location_only": True})

    assert response.status_code == 200
    assert response.json()["location"]["prefecture"] == "大阪府"
    assert response.json()["location"]["city"] == "大阪市"
    assert response.json()["location"]["ward"] == "北区"


def test_recognition_returns_code_not_mapped_without_failing(monkeypatch):
    monkeypatch.setattr(recognition_service, "parse_exif_gps", lambda _image: {"latitude": 34.7, "longitude": 135.5})
    monkeypatch.setattr(
        recognition_service,
        "GsiReverseGeocoder",
        lambda: type("FakeGeocoder", (), {"reverse_geocode": lambda self, _lat, _lon: AddressCandidate("大阪府大阪市北区", "gsi_reverse_geocoder", "town", "99999")})(),
    )
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "resolve_location_only": True})

    assert response.status_code == 200
    assert response.json()["location"] is None
    assert response.json()["location_reason"] == "code_not_mapped"


def test_recognition_converts_geocoder_failure_to_location_reason(monkeypatch):
    async def fake_resolve(_image):
        return {"location": None, "location_reason": "geocode_failed"}

    monkeypatch.setattr(recognition_service, "resolve_location", fake_resolve)
    response = TestClient(app).post("/api/recognition", json={"image": IMAGE, "resolve_location_only": True})

    assert response.status_code == 200
    assert response.json()["location"] is None
    assert response.json()["location_reason"] == "geocode_failed"
