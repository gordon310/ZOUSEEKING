import json

from backend.app.renovation.models import RenovationContext
from backend.app.renovation.vision import HttpVisionProvider, VisionInput, get_vision_provider


def test_get_vision_provider_is_optional(monkeypatch):
    monkeypatch.delenv("RENOVATION_VISION_API_URL", raising=False)

    assert get_vision_provider() is None


def test_http_vision_provider_sends_image_and_preserves_manifest_room(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, _limit):
            return json.dumps(
                {
                    "photos": [
                        {
                            "id": "bathroom-01",
                            "observations": [
                                {
                                    "component": "unit_bath",
                                    "condition": "aged",
                                    "scope": "replace",
                                    "confidence": "medium",
                                    "quantity": 1,
                                    "notes": "浴室设备有明显使用痕迹",
                                }
                            ],
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("backend.app.renovation.vision.urlopen", fake_urlopen)

    result = HttpVisionProvider("https://vision.example/analyze", token="secret", timeout_seconds=7).analyze(
        [
            VisionInput(
                id="bathroom-01",
                room="bathroom",
                filename="bathroom-01.jpg",
                media_type="image/jpeg",
                content=b"jpeg-bytes",
            )
        ],
        RenovationContext(location_hint="大阪市大正区"),
    )

    sent = json.loads(captured["request"].data.decode("utf-8"))
    assert captured["timeout"] == 7
    assert captured["request"].get_header("Authorization") == "Bearer secret"
    assert sent["photos"][0]["content_base64"]
    assert result[0].room == "bathroom"
    assert result[0].observations[0].component == "unit_bath"
