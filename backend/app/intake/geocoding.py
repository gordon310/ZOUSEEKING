"""Small, provider-boundary adapter for reverse geocoding device coordinates."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_GSI_REVERSE_GEOCODER_URL = (
    "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
)
MAX_ADDRESS_LENGTH = 500
MAX_RESPONSE_BYTES = 64 * 1024


class ReverseGeocoderError(Exception):
    """Raised when a provider response cannot supply a safe address candidate."""


@dataclass(frozen=True)
class AddressCandidate:
    address: str
    source: str
    precision: str
    municipality_code: str = ""


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\u3000", " ").split())[:MAX_ADDRESS_LENGTH]


def parse_gsi_response(payload: Mapping[str, Any]) -> AddressCandidate:
    """Parse only the documented town-level GSI result from an untrusted payload."""

    results = payload.get("results") if isinstance(payload, Mapping) else None
    if isinstance(results, list):
        results = results[0] if results else None
    if not isinstance(results, Mapping):
        raise ReverseGeocoderError("reverse geocoder response has no results")

    address = _clean_text(results.get("lv01Nm"))
    if not address:
        raise ReverseGeocoderError("reverse geocoder response has no address candidate")

    municipality_code = _clean_text(results.get("muniCd"))
    return AddressCandidate(
        address=address,
        source="gsi_reverse_geocoder",
        precision="town",
        municipality_code=municipality_code,
    )


class GsiReverseGeocoder:
    """Synchronous adapter used from a worker thread by the async API route."""

    def __init__(self, url: str = "", timeout_seconds: Optional[float] = None) -> None:
        configured_url = url.strip() or os.getenv("REVERSE_GEOCODER_URL", "").strip()
        self.url = configured_url or DEFAULT_GSI_REVERSE_GEOCODER_URL
        configured_timeout = timeout_seconds
        if configured_timeout is None:
            try:
                configured_timeout = float(os.getenv("REVERSE_GEOCODER_TIMEOUT_SECONDS", "5"))
            except ValueError:
                configured_timeout = 5
        if not math.isfinite(float(configured_timeout)):
            configured_timeout = 5
        self.timeout_seconds = max(1.0, min(float(configured_timeout), 15.0))

    def reverse_geocode(self, latitude: float, longitude: float) -> AddressCandidate:
        query = urlencode({"lon": str(longitude), "lat": str(latitude)})
        request = Request(
            f"{self.url}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "ZOUBEACON-property-intake/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_payload) > MAX_RESPONSE_BYTES:
                raise ReverseGeocoderError("reverse geocoder response is too large")
            payload = json.loads(raw_payload.decode("utf-8"))
            return parse_gsi_response(payload)
        except ReverseGeocoderError:
            raise
        except Exception as exc:
            raise ReverseGeocoderError("reverse geocoder request failed") from exc
