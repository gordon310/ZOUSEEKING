"""Organization-scoped MLIT regional statistics endpoint."""

from __future__ import annotations

from typing import Any, Optional, Protocol

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import AuthUser, require_user
from .db import get_pool
from .region_stats import aggregate_region_rows
from .region_names import normalize_region_stats_names

router = APIRouter(prefix="/api/org", tags=["regional statistics"])
TOWER_DISCLOSURE_CODE = "tower_merged_into_apartment"
RENT_REFERENCE_122_4 = "estat_housing_land_122_4"
RENT_REFERENCE_122_5 = "estat_housing_land_122_5"
STATS_ASSET_TYPES = frozenset({"塔楼", "公寓", "一户建", "独栋", "土地"})
STORAGE_ASSET_TYPE_BY_STATS_ASSET_TYPE = {"塔楼": "公寓", "一户建": "独栋"}


def normalize_stats_ward(ward: Optional[str]) -> Optional[str]:
    value = (ward or "").strip()
    return None if value in {"", "__not_subdivided__"} else value


class RegionStatsStore(Protocol):
    async def get(self, user: AuthUser, prefecture: str, city: str, ward: Optional[str], asset_type: str, period: str) -> dict[str, Any]: ...


class DbRegionStatsStore:
    @staticmethod
    async def _rent_reference(conn: asyncpg.Connection, prefecture: str, city: str, ward: Optional[str], asset_type: str):
        preferred_dimensions = {
            "公寓": ("共同住宅", "非木造"),
            "塔楼": ("共同住宅", "非木造"),
            "一户建": ("一戸建", "総数"),
        }.get(asset_type)
        location_sql = """prefecture=$2 and
            ((city=$3 and (ward=$4 or ward='__not_subdivided__'))
             or (city='__not_subdivided__' and ward='__not_subdivided__'))"""
        order_sql = """order by case when city=$3 and ward=$4 then 0
                                      when city=$3 and ward='__not_subdivided__' then 1
                                      else 2 end, survey_year desc limit 1"""
        if preferred_dimensions:
            preferred_location_sql = """prefecture=$3 and
                ((city=$4 and (ward=$5 or ward='__not_subdivided__'))
                 or (city='__not_subdivided__' and ward='__not_subdivided__'))"""
            preferred_order_sql = """order by case when city=$4 and ward=$5 then 0
                                                when city=$4 and ward='__not_subdivided__' then 1
                                                else 2 end,
                                           case when source_key=$1 then 0 else 1 end,
                                           survey_year desc limit 1"""
            return await conn.fetchrow(
                f"""select source_key, rent_jpy_per_sqm_month_excl_zero, scope_label, survey_label, survey_year,
                          geo_level, source_label, source_url, license_label
                   from public.rent_reference_stats
                  where ((source_key=$1 and building_type=$6 and structure_type=$7) or source_key=$2)
                    and {preferred_location_sql}
                  {preferred_order_sql}""",
                RENT_REFERENCE_122_5, RENT_REFERENCE_122_4, prefecture, city,
                ward or "__not_subdivided__", *preferred_dimensions,
            )
        return await conn.fetchrow(
            f"""select source_key, rent_jpy_per_sqm_month_excl_zero, scope_label, survey_label, survey_year,
                      geo_level, source_label, source_url, license_label
               from public.rent_reference_stats
              where source_key=$1 and {location_sql}
              {order_sql}""",
            RENT_REFERENCE_122_4, prefecture, city, ward or "__not_subdivided__",
        )

    async def get(self, user: AuthUser, prefecture: str, city: str, ward: Optional[str], asset_type: str, period: str) -> dict[str, Any]:
        query_asset_type = STORAGE_ASSET_TYPE_BY_STATS_ASSET_TYPE.get(asset_type, asset_type)
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
            rent_reference = await self._rent_reference(conn, prefecture, city, ward, asset_type)
            monthly_rent = await conn.fetchrow(
                """select city, rent_jpy_per_sqm_month, observed_month, source_label, source_url, license_label
                     from public.rent_reference_stats
                    where source_key='estat_kouri_3001' and prefecture=$1 and city=$2
                    order by observed_month desc nulls last limit 1""", prefecture, city,
            )
            if not monthly_rent and prefecture == "东京都":
                monthly_rent = await conn.fetchrow(
                    """select city, rent_jpy_per_sqm_month, observed_month, source_label, source_url, license_label
                         from public.rent_reference_stats
                        where source_key='estat_kouri_3001' and prefecture=$1 and city='东京23区'
                        order by observed_month desc nulls last limit 1""", prefecture,
                )
            result["rent_reference"] = (
                {
                    "source_key": rent_reference["source_key"],
                    "rent_jpy_per_sqm_month": float(rent_reference["rent_jpy_per_sqm_month_excl_zero"]),
                    "scope_label": rent_reference["scope_label"], "survey_label": rent_reference["survey_label"],
                    "survey_year": rent_reference["survey_year"], "geo_level": rent_reference["geo_level"],
                    "geo_level_label": {"prefecture": "都道府県", "city": "市区町村", "ward": "区", "special_wards": "东京23区"}.get(rent_reference["geo_level"], rent_reference["geo_level"]),
                    "source_label": rent_reference["source_label"], "source_url": rent_reference["source_url"],
                    "license_label": rent_reference["license_label"],
                } if rent_reference else None
            )
            result["monthly_rent_reference"] = (
                {key: (float(value) if key == "rent_jpy_per_sqm_month" else value) for key, value in dict(monthly_rent).items()}
                if monthly_rent else None
            )
            denominator = result.get("mean_unit_price_jpy_per_sqm")
            result["rent_to_price_ratio"] = (
                {"gross_value": 12 * float(rent_reference["rent_jpy_per_sqm_month_excl_zero"]) / float(denominator),
                 "formula_label": "12 × 月租(円/㎡) ÷ ㎡単価(円/㎡)",
                 "numerator_label": f"官方家賃・{rent_reference['scope_label']}・家賃0円を含まない",
                 "denominator_label": "本市官方成交均值㎡単価", "survey_label": rent_reference["survey_label"],
                 "geo_level": rent_reference["geo_level"]}
                if rent_reference and denominator and float(denominator) > 0 else None
            )
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
    if asset_type not in STATS_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="物件类型无效")
    period = f"{year}Q{quarter}"
    normalized_ward = normalize_stats_ward(ward)
    normalized_prefecture, normalized_city, normalized_ward = normalize_region_stats_names(
        prefecture, city, normalized_ward
    )
    result = await store.get(user, normalized_prefecture, normalized_city, normalized_ward, asset_type, period)
    result["ward"] = normalized_ward
    if asset_type == "塔楼":
        result["disclosure"] = {"code": TOWER_DISCLOSURE_CODE}
    return result
