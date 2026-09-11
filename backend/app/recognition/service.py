from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..intake.geocoding import GsiReverseGeocoder, ReverseGeocoderError
from .exif import parse_exif_gps
from .municipality import lookup_municipality


MAX_IMAGE_BYTES = 2 * 1024 * 1024
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
_DATA_URL_RE = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)


class RecognitionNotConfigured(Exception):
    pass


class RecognitionUpstreamTimeout(Exception):
    pass


class RecognitionUpstreamError(Exception):
    pass


def validate_image_data_url(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("图片必须是 data URL。")
    match = _DATA_URL_RE.fullmatch(value)
    if not match or match.group(1).lower() not in SUPPORTED_MEDIA_TYPES:
        raise ValueError("仅支持 JPEG、PNG、WEBP 图片 data URL。")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 data URL 无法解码。") from exc
    if not decoded:
        raise ValueError("图片不能为空。")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("图片解码后不能超过 2 MiB。")


def decode_image_data_url(image: str) -> bytes:
    match = _DATA_URL_RE.fullmatch(image)
    if not match:
        raise ValueError("invalid image data URL")
    return base64.b64decode(match.group(2), validate=True)


def _region_parts(address: str) -> tuple[str, str, str | None]:
    prefecture = ""
    rest = address
    for suffix in ("都", "道", "府", "県"):
        marker = rest.find(suffix)
        if marker >= 0:
            prefecture = rest[: marker + 1]
            rest = rest[marker + 1 :]
            break
    normalised = {
        "東京都": "东京都",
        "神奈川県": "神奈川县",
        "埼玉県": "埼玉县",
        "千葉県": "千葉县",
        "愛知県": "爱知县",
        "兵庫県": "兵庫县",
        "京都府": "京都府",
        "大阪府": "大阪府",
        "渋谷区": "涩谷区",
    }
    prefecture = normalised.get(prefecture, prefecture)
    for japanese, display in normalised.items():
        rest = rest.replace(japanese, display, 1)
    city_end = next((rest.find(suffix) for suffix in ("市", "町", "村") if rest.find(suffix) >= 0), -1)
    ward_end = rest.find("区")
    if city_end >= 0 and (ward_end < 0 or city_end < ward_end):
        city = rest[: city_end + 1]
        ward = rest[city_end + 1 : ward_end + 1] if ward_end >= 0 else None
    elif ward_end >= 0:
        city = rest[: ward_end + 1]
        ward = None
    else:
        city, ward = rest, None
    return prefecture, city, ward


async def resolve_location(image: str) -> dict[str, Any]:
    coordinates = parse_exif_gps(decode_image_data_url(image))
    if coordinates is None:
        return {"location": None, "location_reason": "no_exif_gps"}
    try:
        candidate = await asyncio.to_thread(
            GsiReverseGeocoder().reverse_geocode,
            coordinates["latitude"],
            coordinates["longitude"],
        )
    except ReverseGeocoderError:
        return {"location": None, "location_reason": "geocode_failed"}
    mapped = lookup_municipality(candidate.municipality_code)
    if mapped is None:
        return {"location": None, "location_reason": "code_not_mapped"}
    _, _, address_ward = _region_parts(candidate.address)
    return {
        "location": {
            "prefecture": mapped["prefecture"],
            "city": mapped["city"],
            "ward": mapped.get("ward") or address_ward,
            "latitude": coordinates["latitude"],
            "longitude": coordinates["longitude"],
            "source": "exif",
        },
        "location_reason": None,
    }


async def analyze(image: str, note: str = "") -> dict[str, Any]:
    base_url = os.getenv("JPPSKILL_BASE_URL", "http://jpsskill:8100").strip().rstrip("/")
    if not base_url:
        raise RecognitionNotConfigured()
    try:
        timeout = float(os.getenv("JPPSKILL_TIMEOUT_SECONDS", "30"))
    except ValueError:
        timeout = 30.0
    timeout = max(0.1, timeout)

    payload = {
        "mode": "property-identification",
        "images": [{"id": "recognition-1", "url": image, "room": "exterior"}],
    }
    request = Request(
        f"{base_url}/api/analyze",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        response_body = await asyncio.to_thread(_post, request, timeout)
    except (socket.timeout, TimeoutError, RecognitionUpstreamTimeout) as exc:
        raise RecognitionUpstreamTimeout() from exc
    except (HTTPError, URLError, OSError, RecognitionUpstreamError) as exc:
        raise RecognitionUpstreamError() from exc

    try:
        upstream = json.loads(response_body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RecognitionUpstreamError() from exc
    if not isinstance(upstream, dict):
        raise RecognitionUpstreamError()

    result: dict[str, Any] = {}
    for key in ("matched_listing", "listing_candidates", "confidence"):
        if key in upstream:
            result[key] = upstream[key]
    result.setdefault("matched_listing", None)
    result.setdefault("listing_candidates", [])
    result.setdefault("confidence", None)
    return result


async def recognize(
    image: str,
    note: str = "",
    *,
    resolve_location_only: bool = False,
    use_ai: bool = False,
) -> dict[str, Any]:
    location_result = await resolve_location(image)
    ai_enabled = os.getenv("RECOGNITION_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if use_ai and not ai_enabled:
        return {**location_result, "listing": None, "ai_disabled": True}
    listing = await analyze(image, note) if use_ai and not resolve_location_only else None
    response: dict[str, Any] = {**location_result, "listing": listing}
    if listing is not None:
        response.update(listing)
        response["disclaimer"] = "AI 识别,请核对"
    return response


def _post(request: Request, timeout: float) -> str:
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except HTTPError:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise RecognitionUpstreamTimeout() from exc
    except (URLError, OSError):
        raise
