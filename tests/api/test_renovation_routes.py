def renovation_payload():
    return {
        "context": {"location_hint": "大阪市大正区", "floor_area_m2": 80, "structure": "detached"},
        "photos": [
            {
                "id": "bathroom-01",
                "room": "bathroom",
                "observations": [
                    {
                        "component": "unit_bath",
                        "condition": "aged",
                        "scope": "replace",
                        "confidence": "medium",
                        "quantity": 1,
                        "notes": "浴槽と壁面の経年感が見える",
                    }
                ],
            }
        ],
    }


def test_estimate_endpoint_returns_explainable_jpy_result(client):
    response = client.post("/api/renovation/estimates", json=renovation_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["data_class"] == "modeled_estimate"
    assert body["currency"] == "JPY"
    assert body["total_range"] == {"low": 600000, "high": 1500000}
    assert body["items"][0]["photo_observations"] == ["浴槽と壁面の経年感が見える"]
    assert body["items"][0]["source_refs"]
    assert body["sources"][0]["retrieved_on"] == "2026-08-31"


def test_upload_endpoint_requires_a_configured_vision_provider(client):
    manifest = {
        "context": {"location_hint": "大阪市大正区"},
        "photos": [{"id": "bathroom-01", "room": "bathroom", "filename": "bathroom-01.jpg"}],
    }
    response = client.post(
        "/api/renovation/analyses",
        data={"manifest": __import__("json").dumps(manifest)},
        files={"images": ("bathroom-01.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "vision_provider_not_configured"


def test_upload_endpoint_uses_structured_observations_without_vision_provider(client):
    manifest = renovation_payload()
    manifest["photos"][0]["filename"] = "bathroom-01.jpg"
    response = client.post(
        "/api/renovation/analyses",
        data={"manifest": __import__("json").dumps(manifest)},
        files={"images": ("bathroom-01.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["photo_analysis"]["status"] == "structured_observations"


def test_upload_endpoint_rejects_duplicate_or_missing_manifest_filenames(client):
    manifest = {
        "context": {},
        "photos": [
            {"id": "bathroom-01", "room": "bathroom", "filename": "bathroom-01.jpg"},
            {"id": "bathroom-02", "room": "bathroom", "filename": "bathroom-02.jpg"},
        ],
    }
    response = client.post(
        "/api/renovation/analyses",
        data={"manifest": __import__("json").dumps(manifest)},
        files=[
            ("images", ("bathroom-01.jpg", b"\xff\xd8\xff", "image/jpeg")),
            ("images", ("bathroom-01.jpg", b"\xff\xd8\xff", "image/jpeg")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "image_manifest_mismatch"
