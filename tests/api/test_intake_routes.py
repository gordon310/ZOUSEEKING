from uuid import UUID

from backend.app.intake.geocoding import ReverseGeocoderError


def test_create_session_returns_raw_token_once(client):
    response = client.post(
        "/api/intake/sessions",
        json={"purpose": "self_use", "consent_version": "privacy-2026-08"},
    )

    assert response.status_code == 201
    assert response.json()["expires_in_seconds"] == 86400
    assert response.json()["session_token"]


def test_wrong_session_token_is_uniform_404(client, session):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": "wrong"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "分析项目不存在或已过期。"}


def test_text_input_is_recorded_for_manual_review(client, session):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/inputs",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"input_type": "text", "raw_text": "大阪市北区，售价3500万日元"},
    )

    assert response.status_code == 201
    assert response.json()["processing_status"] == "manual_review"


def test_invalid_file_is_rejected_without_storage_upload(client, session, fake_storage):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/files",
        headers={"X-Analysis-Session": session["session_token"]},
        files={"file": ("bad.exe", b"bad", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "PDF、JPG、PNG" in response.json()["detail"]
    assert fake_storage.uploads == []


def test_field_confirmation_uses_server_unit_and_rejects_owner_field(client, session):
    response = client.put(
        f"/api/intake/sessions/{session['session_id']}/fields/asking_price_jpy",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"field_name": "asking_price_jpy", "value": 35000000, "confirmation_status": "confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["unit"] == "JPY"

    forbidden = client.put(
        f"/api/intake/sessions/{session['session_id']}/fields/owner_user_id",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"field_name": "owner_user_id", "value": "attacker", "confirmation_status": "confirmed"},
    )
    assert forbidden.status_code == 422


def test_field_cannot_reference_input_from_another_session(client, session):
    response = client.put(
        f"/api/intake/sessions/{session['session_id']}/fields/asking_price_jpy",
        headers={"X-Analysis-Session": session["session_token"]},
        json={
            "field_name": "asking_price_jpy",
            "value": 35000000,
            "confirmation_status": "confirmed",
            "source_input_id": str(UUID("00000000-0000-0000-0000-000000000099")),
        },
    )

    assert response.status_code == 404


def test_location_endpoint_returns_candidate_and_saves_coordinates(client, session, fake_repository, fake_geocoder):
    response = client.put(
        f"/api/intake/sessions/{session['session_id']}/location",
        headers={"X-Analysis-Session": session["session_token"]},
        json={
            "latitude": 34.7025,
            "longitude": 135.4959,
            "accuracy_m": 18.5,
            "captured_at": "2026-08-28T03:30:00Z",
            "consent_version": "location-2026-08",
            "source": "device_geolocation",
        },
    )

    assert response.status_code == 200
    assert response.json()["address_candidate"] == "大阪府大阪市北区梅田"
    saved_session = next(iter(fake_repository.sessions.values()))
    assert saved_session["latitude"] == 34.7025


def test_location_provider_failure_keeps_coordinate_and_returns_manual_fallback(
    client, session, fake_repository, fake_geocoder
):
    fake_geocoder.error = ReverseGeocoderError("provider failed")

    response = client.put(
        f"/api/intake/sessions/{session['session_id']}/location",
        headers={"X-Analysis-Session": session["session_token"]},
        json={
            "latitude": 34.7025,
            "longitude": 135.4959,
            "accuracy_m": 18.5,
            "captured_at": "2026-08-28T03:30:00Z",
            "consent_version": "location-2026-08",
            "source": "device_geolocation",
        },
    )

    assert response.status_code == 200
    assert response.json()["address_source"] == "unavailable"
    assert response.json()["address_candidate"] == ""
    saved_session = next(iter(fake_repository.sessions.values()))
    assert saved_session["longitude"] == 135.4959


def test_preview_has_no_fabricated_tax_amount(client, session):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["acquisition_costs"]["estimated_total_jpy"] is None
    assert body["comparable_status"] == "not_checked"


def test_convert_uses_authenticated_user_not_request_body(client, session, auth_header, fake_repository):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={"project_name": "用户房产记录"},
    )

    assert response.status_code == 200
    assert response.json()["owner_user_id"] == str(fake_repository.created_properties[0]["owner_user_id"])


def test_convert_rejects_client_owned_identity_field(client, session, auth_header):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={"owner_user_id": "attacker"},
    )

    assert response.status_code == 422


def test_duplicate_address_requires_manual_project_name(client, session, auth_header, fake_repository):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    fake_repository.duplicate_address = True
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_address"


def test_duplicate_address_can_be_saved_with_manual_name(client, session, auth_header, fake_repository):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    fake_repository.duplicate_address = True
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={"project_name": "大阪市北区梅田｜二次调查"},
    )

    assert response.status_code == 200
    assert fake_repository.created_properties[0]["project_name"] == "大阪市北区梅田｜二次调查"


def test_other_authenticated_user_cannot_convert_existing_session(
    client, session, auth_header, other_auth_header, use_other_auth_user
):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
    )
    use_other_auth_user()
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**other_auth_header, "X-Analysis-Session": session["session_token"]},
    )

    assert response.status_code == 404


def test_converted_session_cannot_be_modified_with_anonymous_token(client, session, auth_header):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    converted = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
    )
    assert converted.status_code == 200

    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/inputs",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"input_type": "text", "raw_text": "不应再写入"},
    )

    assert response.status_code == 404
