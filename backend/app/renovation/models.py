"""Request and response contracts for the Japanese renovation estimator."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Room = Literal["exterior", "bathroom", "kitchen", "living_room", "bedroom", "balcony"]
Component = Literal["unit_bath", "wallpaper", "flooring", "kitchen", "toilet", "washstand", "tatami"]
Condition = Literal[
    "new",
    "good",
    "aged",
    "worn",
    "stained",
    "damaged",
    "mold_or_stain",
    "water_damage_suspected",
    "unknown",
]
Scope = Literal["replace", "surface_refresh", "repair", "monitor", "unknown"]
Confidence = Literal["low", "medium", "high"]
Structure = Literal["condo", "detached", "unknown"]


class RenovationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RenovationContext(RenovationModel):
    location_hint: Optional[str] = Field(default=None, max_length=200)
    floor_area_m2: Optional[float] = Field(default=None, gt=0, le=10000)
    built_year: Optional[int] = Field(default=None, ge=1800, le=2100)
    structure: Structure = "unknown"
    renovation_goal: Optional[str] = Field(default=None, max_length=200)

    @field_validator("location_hint", "renovation_goal", mode="before")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class PhotoObservation(RenovationModel):
    component: Component
    condition: Condition = "unknown"
    scope: Scope = "unknown"
    confidence: Confidence = "low"
    quantity: float = Field(default=1, gt=0, le=1000)
    area_m2: Optional[float] = Field(default=None, gt=0, le=10000)
    notes: str = Field(default="", max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: Any) -> str:
        return str(value or "").strip()


class PhotoRecord(RenovationModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    room: Room
    image_ref: Optional[str] = Field(default=None, max_length=300)
    observations: List[PhotoObservation] = Field(default_factory=list, max_length=20)


class UploadPhotoRecord(PhotoRecord):
    filename: str = Field(min_length=1, max_length=255)


class RenovationEstimateRequest(RenovationModel):
    context: RenovationContext = Field(default_factory=RenovationContext)
    photos: List[PhotoRecord] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def require_unique_photo_ids(self) -> "RenovationEstimateRequest":
        ids = [photo.id for photo in self.photos]
        if len(ids) != len(set(ids)):
            raise ValueError("photo ids must be unique")
        return self


class RenovationUploadManifest(RenovationModel):
    context: RenovationContext = Field(default_factory=RenovationContext)
    photos: List[UploadPhotoRecord] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def require_unique_manifest_values(self) -> "RenovationUploadManifest":
        ids = [photo.id for photo in self.photos]
        filenames = [photo.filename for photo in self.photos]
        if len(ids) != len(set(ids)):
            raise ValueError("photo ids must be unique")
        if len(filenames) != len(set(filenames)):
            raise ValueError("photo filenames must be unique")
        return self


class MoneyRange(RenovationModel):
    low: int = Field(ge=0)
    high: int = Field(ge=0)

    @model_validator(mode="after")
    def low_must_not_exceed_high(self) -> "MoneyRange":
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class PriceSource(RenovationModel):
    url: str
    title: str
    purpose: str
    retrieved_on: str
    tax_basis: Literal["tax_included", "tax_excluded", "approximate"]
    notes: str


class EstimateItem(RenovationModel):
    room: Room
    component: Component
    name: str
    unit: Literal["job", "m2", "mat"]
    quantity: float
    condition: Condition
    confidence: Confidence
    photo_refs: List[str]
    photo_observations: List[str]
    estimate_assumptions: List[str]
    range: MoneyRange
    source_refs: List[str]


class PhotoAnalysis(RenovationModel):
    status: Literal["structured_observations", "vision_provider", "no_observations"]
    provider: str
    photos: List[Dict[str, Any]]


class RenovationEstimateResponse(RenovationModel):
    analysis_id: str
    status: Literal["completed"]
    data_class: Literal["modeled_estimate"]
    currency: Literal["JPY"]
    tax_basis: Literal["approximate"]
    price_snapshot_version: str
    total_range: MoneyRange
    items: List[EstimateItem]
    photo_analysis: PhotoAnalysis
    assumptions: List[str]
    excluded_items: List[str]
    sources: List[PriceSource]
    limitations: List[str]
    confidence: Confidence
