import pytest

from backend.app.renovation.models import RenovationEstimateRequest
from backend.app.renovation.pricing import build_estimate


def observation(component, *, condition="aged", scope="replace", quantity=1, area_m2=None):
    return {
        "component": component,
        "condition": condition,
        "scope": scope,
        "confidence": "medium",
        "quantity": quantity,
        "area_m2": area_m2,
        "notes": "现场照片可见",
    }


def test_estimate_returns_jpy_ranges_and_source_evidence():
    request = RenovationEstimateRequest(
        context={
            "location_hint": "大阪市大正区",
            "floor_area_m2": 80,
            "built_year": 1980,
            "structure": "detached",
            "renovation_goal": "purchase_screening",
        },
        photos=[
            {
                "id": "bathroom-01",
                "room": "bathroom",
                "observations": [observation("unit_bath")],
            },
            {
                "id": "living-01",
                "room": "living_room",
                "observations": [observation("wallpaper", scope="surface_refresh", area_m2=20)],
            },
        ],
    )

    result = build_estimate(request)

    assert result["data_class"] == "modeled_estimate"
    assert result["currency"] == "JPY"
    assert result["total_range"] == {"low": 622000, "high": 1531000}
    assert {item["component"] for item in result["items"]} == {"unit_bath", "wallpaper"}
    assert result["items"][0]["source_refs"]
    assert result["sources"]
    assert result["price_snapshot_version"] == "jp-renovation-2026-08-31-v1"


def test_duplicate_photos_same_room_component_are_counted_once():
    request = RenovationEstimateRequest(
        photos=[
            {"id": "bathroom-front", "room": "bathroom", "observations": [observation("unit_bath")]},
            {"id": "bathroom-side", "room": "bathroom", "observations": [observation("unit_bath")]},
        ]
    )

    result = build_estimate(request)

    assert len(result["items"]) == 1
    assert result["items"][0]["range"] == {"low": 600000, "high": 1500000}
    assert "bathroom-front" in result["items"][0]["photo_refs"]
    assert "bathroom-side" in result["items"][0]["photo_refs"]


def test_area_based_component_without_area_is_not_invented():
    request = RenovationEstimateRequest(
        photos=[
            {
                "id": "living-01",
                "room": "living_room",
                "observations": [observation("wallpaper", scope="surface_refresh")],
            }
        ]
    )

    result = build_estimate(request)

    assert result["total_range"] == {"low": 0, "high": 0}
    assert result["items"] == []
    assert any("面积" in limitation for limitation in result["limitations"])


def test_unknown_condition_is_not_treated_as_replacement():
    request = RenovationEstimateRequest(
        photos=[
            {
                "id": "kitchen-01",
                "room": "kitchen",
                "observations": [observation("kitchen", condition="unknown", scope="unknown")],
            }
        ]
    )

    result = build_estimate(request)

    assert result["total_range"] == {"low": 0, "high": 0}
    assert result["items"] == []
    assert any("未计价" in limitation for limitation in result["limitations"])


def test_invalid_observation_is_rejected():
    with pytest.raises(ValueError):
        RenovationEstimateRequest(
            photos=[
                {
                    "id": "bathroom-01",
                    "room": "bathroom",
                    "observations": [observation("not_a_component")],
                }
            ]
        )
