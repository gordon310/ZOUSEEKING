from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


AssetType = Literal["塔楼", "公寓", "一户建"]


class QueryRequest(BaseModel):
    prefecture: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    ward: Optional[str] = ""
    asset_type: AssetType = "塔楼"
    year: int
    month: int = Field(..., ge=1, le=12)
    username: Optional[str] = None


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
    status: str
    progress: int
    current_step: str
    error_message: Optional[str] = None
    report: Optional[dict[str, Any]] = None
