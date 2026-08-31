"""Provider-neutral adapter for optional uploaded-image condition recognition."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .models import PhotoObservation, PhotoRecord, RenovationContext, RenovationModel


class VisionProviderUnavailable(RuntimeError):
    """The configured provider did not return a valid safe response."""


@dataclass(frozen=True)
class VisionInput:
    id: str
    room: str
    filename: str
    media_type: str
    content: bytes


class VisionPhotoResponse(RenovationModel):
    id: str
    observations: List[PhotoObservation]


class VisionResponse(RenovationModel):
    photos: List[VisionPhotoResponse]


class HttpVisionProvider:
    def __init__(self, url: str, token: str = "", timeout_seconds: float = 20) -> None:
        self.url = url
        self.token = token
        self.timeout_seconds = timeout_seconds

    def analyze(self, images: Sequence[VisionInput], context: RenovationContext) -> List[PhotoRecord]:
        payload = {
            "context": context.model_dump(),
            "photos": [
                {
                    "id": image.id,
                    "room": image.room,
                    "filename": image.filename,
                    "media_type": image.media_type,
                    "content_base64": base64.b64encode(image.content).decode("ascii"),
                }
                for image in images
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(2 * 1024 * 1024)
            decoded = VisionResponse.model_validate(json.loads(body.decode("utf-8")))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise VisionProviderUnavailable() from exc

        expected = {image.id: image for image in images}
        if set(item.id for item in decoded.photos) != set(expected):
            raise VisionProviderUnavailable()
        return [
            PhotoRecord(
                id=item.id,
                room=expected[item.id].room,  # room is controlled by the caller manifest
                observations=item.observations,
            )
            for item in decoded.photos
        ]


def get_vision_provider() -> Optional[HttpVisionProvider]:
    url = os.getenv("RENOVATION_VISION_API_URL", "").strip()
    if not url:
        return None
    return HttpVisionProvider(url, os.getenv("RENOVATION_VISION_API_TOKEN", "").strip())
