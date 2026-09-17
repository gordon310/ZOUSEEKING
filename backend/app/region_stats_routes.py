"""Organization-scoped MLIT regional statistics endpoint."""

from __future__ import annotations

from typing import Any, Optional, Protocol

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import AuthUser, require_user
from .db import get_pool
from .region_stats import aggregate_region_rows

router = APIRouter(prefix="/api/org", tags=["regional statistics"])
TOWER_DISCLOSURE_CODE = "tower_merged_into_apartment"


def normalize_stats_ward(ward: Optional[str]) -> Optional[str]:
    value = (ward or "").strip()
    return None if value in {"", "__not_subdivided__"} else value


class RegionStatsStore(Protocol):
    async def get(self, user: AuthUser, prefecture: str, city: str, ward: Optional[str], asset_type: str, period: str) -> dict[str, Any]: ...


class DbRegionStatsStore:
    async def get(self, user: AuthUser, prefecture: str, city: str, ward: Optional[str], asset_type: str, period: str) -> dict[str, Any]:
        query_asset_type = "公寓" if asset_type == "塔楼" else asset_type
        async with get_pool().acquire() as conn:
            member = await conn.fetchval(
                "select 1 from public.organization_members where user_id=$1 and status='active' limit 1", user.user_id
            )
            if not member:
                raise HTTPException(status_code=403, detail="机构成员权限不足")
            rows = await conn.fetch(
                """select unit_price_jpy_per_sqm from public.mlit_transactions
                   where prefecture=$1 and city=$2 and asset_type=$3
                     and trade_quarter=$4 and ($5::text is null or ward=$5)
                   order by id""",
                prefecture, city, query_asset_type, period, ward,
            )
            result = aggregate_region_rows([dict(row) for row in rows], asset_type=asset_type, period=period)
            source = await conn.fetchrow(
                """select s.id::text as id, s.name, s.url, s.permission_status, s.source_type
                   from public.sources s join public.mlit_transactions t on t.source_id=s.id
                   where t.prefecture=$1 and t.city=$2 and t.asset_type=$3 and t.trade_quarter=$4
                   limit 1""", prefecture, city, query_asset_type, period,
            )
            result.update({
                "ward": ward,
                "sources": [{"id": source["id"], "name": source["name"], "url": source["url"]}] if source else [],
                "license": {"name": "PDL1.0", "attribution": "出典:不動産情報ライブラリ（国土交通省）"},
                "data_class": "scraped_aggregate",
                "limitations": "参考情報；非逐笔成交明细；区域口径=市区町村/区；㎡単価由官方总价除以官方面积计算。",
            })
            if asset_type == "塔楼":
                result["disclosure"] = {"code": TOWER_DISCLOSURE_CODE}
            return result


def get_region_stats_store() -> RegionStatsStore:
    return DbRegionStatsStore()


@router.get("/region-stats")
async def region_stats(
    prefecture: str = Query(..., min_length=1, max_length=80),
    city: str = Query(..., min_length=1, max_length=80),
    asset_type: str = Query(..., min_length=1, max_length=20),
    year: int = Query(..., ge=2005, le=2200),
    quarter: int = Query(..., ge=1, le=4),
    ward: Optional[str] = Query(default=None, max_length=80),
    user: AuthUser = Depends(require_user),
    store: RegionStatsStore = Depends(get_region_stats_store),
) -> dict[str, Any]:
    if asset_type not in {"塔楼", "公寓", "独栋", "土地"}:
        raise HTTPException(status_code=400, detail="物件类型无效")
    period = f"{year}Q{quarter}"
    normalized_ward = normalize_stats_ward(ward)
    result = await store.get(user, prefecture, city, normalized_ward, asset_type, period)
    result["ward"] = normalized_ward
    if asset_type == "塔楼":
        result["disclosure"] = {"code": TOWER_DISCLOSURE_CODE}
    return result
