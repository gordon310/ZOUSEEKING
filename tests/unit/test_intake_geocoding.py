import json

import pytest

from backend.app.intake.geocoding import (
    GsiReverseGeocoder,
    ReverseGeocoderError,
    parse_gsi_response,
)


def test_gsi_response_returns_town_candidate_only():
    candidate = parse_gsi_response(
        {"results": {"muniCd": "27127", "lv01Nm": "大阪府大阪市北区梅田"}}
    )

    assert candidate.address == "大阪府大阪市北区梅田"
    assert candidate.source == "gsi_reverse_geocoder"
    assert candidate.precision == "town"


def test_gsi_response_without_address_is_rejected():
    with pytest.raises(ReverseGeocoderError):
        parse_gsi_response({"results": {"muniCd": "27127", "lv01Nm": ""}})


def test_gsi_adapter_builds_bounded_json_request(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size=-1):
            return json.dumps(
                {"results": {"muniCd": "27127", "lv01Nm": "大阪府大阪市北区梅田"}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse()

    monkeypatch.setattr("backend.app.intake.geocoding.urlopen", fake_urlopen)
    geocoder = GsiReverseGeocoder(url="https://example.test/reverse", timeout_seconds=3)

    candidate = geocoder.reverse_geocode(34.7025, 135.4959)

    assert candidate.address == "大阪府大阪市北区梅田"
    assert "lat=34.7025" in calls[0][0]
    assert "lon=135.4959" in calls[0][0]
    assert calls[0][1] == 3
