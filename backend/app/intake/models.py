"""Validated request and response contracts for property intake."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Purpose = Literal["self_use", "rental_investment"]
InputType = Literal["text", "url"]
ConfirmationStatus = Literal["confirmed", "corrected", "unknown"]
LocationSource = Literal["device_geolocation"]

FIELD_UNITS: Dict[str, Optional[str]] = {
    "building_name": None,
    "address": None,
    "ward": None,
    "station": None,
    "walk_minutes": "minutes",
    "building_year": "year",
    "total_units": "units",
    "floor": "floor",
    "orientation": None,
    "area_sqm": "sqm",
    "balcony_area_sqm": "sqm",
    "land_right": None,
    "land_share": None,
    "asking_price_jpy": "JPY",
    "management_fee_jpy": "JPY/month",
    "repair_reserve_jpy": "JPY/month",
    "monthly_rent_jpy": "JPY/month",
}


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSessionRequest(IntakeModel):
    purpose: Purpose
    consent_version: str = Field(min_length=1, max_length=100)

    @field_validator("consent_version", mode="before")
    @classmethod
    def normalize_consent_version(cls, value: str) -> str:
        return str(value).strip()


class CreateInputRequest(IntakeModel):
    input_type: InputType
    source_url: Optional[str] = Field(default=None, max_length=2048)
    raw_text: Optional[str] = Field(default=None, max_length=20000)

    @field_validator("source_url", mode="before")
    @classmethod
    def validate_source_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if normalized != value or any(character.isspace() for character in normalized):
            raise ValueError("source URL must not contain whitespace")
        try:
            parsed = urlparse(normalized)
            hostname = parsed.hostname or ""
        except ValueError as exc:
            raise ValueError("source URL must be a safe HTTPS URL") from exc
        if (
            parsed.scheme != "https"
            or not hostname
            or "." not in hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("source URL must be a safe HTTPS URL")
        return normalized

    @field_validator("raw_text", mode="before")
    @classmethod
    def normalize_raw_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_input_payload(self) -> "CreateInputRequest":
        if self.input_type == "text":
            if not self.raw_text:
                raise ValueError("text input requires raw_text")
            if self.source_url is not None:
                raise ValueError("text input cannot include source_url")
        elif self.source_url is None:
            raise ValueError("url input requires source_url")
        elif self.raw_text is not None:
            raise ValueError("url input cannot include raw_text")
        return self


class LocationRequest(IntakeModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=100000)
    captured_at: datetime
    consent_version: str = Field(min_length=1, max_length=100)
    source: LocationSource = "device_geolocation"

    @field_validator("latitude", "longitude", "accuracy_m", mode="before")
    @classmethod
    def validate_finite_number(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("location value must be a finite number") from exc
        if not math.isfinite(number):
            raise ValueError("location value must be a finite number")
        return number

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value

    @field_validator("consent_version", mode="before")
    @classmethod
    def normalize_consent_version(cls, value: str) -> str:
        return str(value).strip()


class ConvertSessionRequest(IntakeModel):
    project_name: Optional[str] = Field(default=None, max_length=200)

    @field_validator("project_name", mode="before")
    @classmethod
    def normalize_project_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ConfirmFieldRequest(IntakeModel):
    field_name: str = Field(min_length=1, max_length=100)
    value: Any = None
    confirmation_status: ConfirmationStatus
    source_input_id: Optional[UUID] = None
    locator: str = Field(default="", max_length=200)

    @field_validator("field_name", mode="before")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        normalized = str(value).strip()
        if normalized not in FIELD_UNITS:
            raise ValueError("unsupported field name")
        return normalized

    @field_validator("locator", mode="before")
    @classmethod
    def normalize_locator(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def set_manual_locator(self) -> "ConfirmFieldRequest":
        if self.source_input_id is None and not self.locator:
            self.locator = "用户手动填写"
        return self

    @property
    def unit(self) -> Optional[str]:
        return FIELD_UNITS[self.field_name]


class CreateSessionResponse(IntakeModel):
    session_id: UUID
    session_token: str
    expires_at: datetime
    expires_in_seconds: int


class CreateInputResponse(IntakeModel):
    input_id: UUID
    processing_status: str


class LocationResponse(IntakeModel):
    latitude: float
    longitude: float
    accuracy_m: float
    captured_at: datetime
    location_source: str
    address_candidate: str
    address_source: str
    address_precision: str


class FieldView(IntakeModel):
    field_name: str
    value: Any
    unit: Optional[str]
    source_input_id: Optional[UUID]
    locator: str
    confirmation_status: str
    confidence: str


class FreePreviewResponse(IntakeModel):
    session_id: UUID
    completeness: dict[str, Any]
    acquisition_costs: dict[str, Any]
    risk_summary: dict[str, Any]
    comparable_status: str
    calculation_version: str
