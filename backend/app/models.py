from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from .asset_types import AssetType, normalize_asset_type


class QueryRequest(BaseModel):
    prefecture: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    ward: Optional[str] = ""
    asset_type: AssetType = "塔楼"
    year: int
    month: int = Field(..., ge=1, le=12)
    username: Optional[str] = None

    @field_validator("asset_type", mode="before")
    @classmethod
    def normalize_asset_type_value(cls, value: object) -> object:
        return normalize_asset_type(value)


class QueryResponse(BaseModel):
    query_key: str
    status: str
    cached: bool
    title: str
    job_id: Optional[str] = None
    report: Optional[dict[str, Any]] = None
    message: str


class JobResponse(BaseModel):
    job_id: str
    query_key: Optional[str] = None
    status: str
    progress: int
    current_step: str
    error_message: Optional[str] = None
    report: Optional[dict[str, Any]] = None
