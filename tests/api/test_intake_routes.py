from uuid import UUID

from backend.app import main
from backend.app.intake.geocoding import ReverseGeocoderError
from backend.app.routes.intake import get_report_pipeline


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


def test_location_rate_limit_rejects_the_sixth_request_in_one_session(client, session, fake_geocoder):
    payload = {
        "latitude": 34.7025,
        "longitude": 135.4959,
        "accuracy_m": 18.5,
        "captured_at": "2026-08-28T03:30:00Z",
        "consent_version": "location-2026-08",
        "source": "device_geolocation",
    }

    responses = [
        client.put(
            f"/api/intake/sessions/{session['session_id']}/location",
            headers={"X-Analysis-Session": session["session_token"]},
            json=payload,
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429
    assert responses[5].headers["Retry-After"] == "3600"


def test_preview_has_no_fabricated_tax_amount(client, session):
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["acquisition_costs"]["estimated_total_jpy"] is None
    assert body["comparable_status"] == "not_checked"


def test_phase_one_allows_preview_but_blocks_project_conversion(
    client, session, auth_header, monkeypatch, fake_repository
):
    monkeypatch.setenv("RELEASE_PHASE", "consumer_intake_preview")

    preview = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    converted = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={"project_name": "不应在第一阶段创建"},
    )

    assert preview.status_code == 200
    assert converted.status_code == 404
    assert converted.json() == {"detail": "operation unavailable in current release phase"}
    assert fake_repository.created_properties == []


def test_managed_environment_without_release_phase_fails_closed(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RELEASE_PHASE", raising=False)

    health = client.get("/health/live")
    create = client.post(
        "/api/intake/sessions",
        json={"purpose": "self_use", "consent_version": "privacy-2026-08"},
    )

    assert health.status_code == 200
    assert create.status_code == 404
    assert create.json() == {"detail": "operation unavailable in current release phase"}


def test_convert_rejects_missing_report_parameters_before_conversion(client, session, auth_header, fake_repository):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={"project_name": "用户房产记录"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "convert_parameters_required"
    assert fake_repository.created_properties == []


def test_convert_starts_shared_report_pipeline_and_returns_query_key(
    client, session, auth_header, monkeypatch
):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    scheduled = []

    async def fake_create_or_get_query_job(request, user_id, background_tasks):
        scheduled.append((request, user_id, background_tasks))
        return {"query_key": f"{user_id}::大阪府::大阪市::北区::塔楼::2026::9", "job_id": "job-1"}

    client.app.dependency_overrides[get_report_pipeline] = lambda: fake_create_or_get_query_job
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={
            "project_name": "用户房产记录",
            "prefecture": "大阪府",
            "city": "大阪市",
            "ward": "北区",
            "asset_type": "塔楼",
            "year": 2026,
            "month": 9,
        },
    )

    assert response.status_code == 200
    assert response.json()["query_key"].endswith("::塔楼::2026::9")
    assert scheduled[0][0].model_dump() == {
        "prefecture": "大阪府",
        "city": "大阪市",
        "ward": "北区",
        "asset_type": "塔楼",
        "year": 2026,
        "month": 9,
        "username": "测试用户",
    }


def test_convert_normalizes_english_asset_type_before_report_pipeline(client, session, auth_header):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    scheduled = []

    async def fake_create_or_get_query_job(request, user_id, background_tasks):
        scheduled.append(request)
        return {"query_key": f"{user_id}::东京都::涩谷区::未細分::公寓::2026::9", "job_id": "job-1"}

    client.app.dependency_overrides[get_report_pipeline] = lambda: fake_create_or_get_query_job
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={
            "project_name": "涩谷区公寓英文别名",
            "prefecture": "东京都",
            "city": "涩谷区",
            "asset_type": "apartment",
            "year": 2026,
            "month": 9,
        },
    )

    assert response.status_code == 200
    assert response.json()["query_key"].endswith("::未細分::公寓::2026::9")
    assert scheduled[0].asset_type == "公寓"


def test_convert_accepts_missing_ward_and_normalizes_it_for_the_pipeline(
    client, session, auth_header
):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    scheduled = []

    async def fake_create_or_get_query_job(request, user_id, background_tasks):
        scheduled.append(request)
        return {"query_key": f"{user_id}::东京都::涩谷区::未細分::公寓::2026::9", "job_id": "job-1"}

    client.app.dependency_overrides[get_report_pipeline] = lambda: fake_create_or_get_query_job
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={
            "project_name": "涩谷区公寓",
            "prefecture": "东京都",
            "city": "涩谷区",
            "asset_type": "公寓",
            "year": 2026,
            "month": 9,
        },
    )

    assert response.status_code == 200
    assert response.json()["query_key"].endswith("::东京都::涩谷区::未細分::公寓::2026::9")
    assert scheduled[0].ward == "未細分"


def test_convert_missing_prefecture_city_or_asset_type_remains_actionable_422(
    client, session, auth_header, fake_repository
):
    for missing in ("prefecture", "city", "asset_type"):
        payload = {"prefecture": "东京都", "city": "涩谷区", "asset_type": "公寓"}
        payload.pop(missing)
        response = client.post(
            f"/api/intake/sessions/{session['session_id']}/convert",
            headers={**auth_header, "X-Analysis-Session": session["session_token"]},
            json=payload,
        )
        assert response.status_code == 422
        assert response.json()["detail"] == {
            "code": "convert_parameters_required",
            "message": "prefecture, city and asset_type are required before conversion",
        }
    assert fake_repository.created_properties == []


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
        json={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 9},
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
        json={"project_name": "大阪市北区梅田｜二次调查", "prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 9},
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
        json={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 9},
    )
    use_other_auth_user()
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**other_auth_header, "X-Analysis-Session": session["session_token"]},
        json={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 9},
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
        json={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 9},
    )
    assert converted.status_code == 200

    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/inputs",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"input_type": "text", "raw_text": "不应再写入"},
    )

    assert response.status_code == 404


def test_consumer_active_phase_allows_business_routes(client, monkeypatch):
    monkeypatch.setenv("RELEASE_PHASE", "consumer_active")
    response = client.post("/api/intake/sessions", json={})
    assert response.status_code != 404
