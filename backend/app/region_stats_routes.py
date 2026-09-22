"""Organization-scoped MLIT regional statistics endpoint."""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Protocol

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import AuthUser, require_user
from .db import get_pool
from .region_stats import aggregate_region_rows
from .region_names import normalize_region_stats_names
from .services.provenance import assert_statistic_provenance, statistic_provenance

router = APIRouter(prefix="/api/org", tags=["regional statistics"])
TOWER_DISCLOSURE_CODE = "tower_merged_into_apartment"
RENT_REFERENCE_122_4 = "estat_housing_land_122_4"
RENT_REFERENCE_122_5 = "estat_housing_land_122_5"
STATS_ASSET_TYPES = frozenset({"塔楼", "公寓", "一户建", "独栋", "土地"})
STORAGE_ASSET_TYPE_BY_STATS_ASSET_TYPE = {"塔楼": "公寓", "一户建": "独栋"}


def normalize_stats_ward(ward: Optional[str]) -> Optional[str]:
    value = (ward or "").strip()
    return None if value in {"", "__not_subdivided__"} else value


def _only_database_value(values: Iterable[object]) -> object | None:
    """Return an unambiguous database value, otherwise expose a contract gap.

    A regional aggregate can cover many transactions.  Categorical provenance
    is publishable only when all populated supporting rows agree; choosing an
    arbitrary row would turn mixed evidence into a false single-source claim.
    """
    unique = {value for value in values if value not in (None, "")}
    return next(iter(unique)) if len(unique) == 1 else None


def _region_statistic_provenance(rows: list[dict[str, Any]]) -> dict[str, object]:
    """Aggregate provenance from the exact transaction rows used for a metric.

    Source-owned values take precedence for categorical fields.  Retrieval time
    is the maximum actual transaction retrieval/import or source observation/
    success time, so it truthfully represents the newest supporting evidence.
    """
    def source_first(source_field: str, transaction_field: str) -> object | None:
        source_value = _only_database_value(row.get(source_field) for row in rows)
        return source_value if source_value is not None else _only_database_value(
            row.get(transaction_field) for row in rows
        )

    def source_period_fallback() -> object | None:
        """Use source metadata only when it declares an actual period."""
        source_period = _only_database_value(row.get("source_period") for row in rows)
        if isinstance(source_period, str) and re.fullmatch(
            r"\d{4}(?:Q[1-4]|-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?",
            source_period,
        ):
            return source_period
        return None

    # A transaction's retrieval timestamp is the evidence for that exact row.
    # Only legacy rows without it fall back to their import/source observation
    # timestamp; mixing both would let a later database import obscure a real
    # source retrieval time.
    retrieved_candidates = [
        row.get("retrieved_at") or row.get("imported_at") or row.get("source_observed_at")
        for row in rows
        if row.get("retrieved_at") or row.get("imported_at") or row.get("source_observed_at")
    ]
    return {
        "data_class": source_first("source_data_class", "data_class"),
        "source_url": source_first("source_url", "transaction_source_url"),
        "retrieved_at": max(retrieved_candidates) if retrieved_candidates else None,
        # This metric is derived from transaction rows, so expose their actual
        # trade period rather than registry/review prose from the source row.
        "source_period": _only_database_value(row.get("trade_quarter") for row in rows) or source_period_fallback(),
        "transformation_version": source_first("source_transformation_version", "transformation_version"),
        "rights_status": source_first("source_permission_status", "rights_status"),
        # ``sources`` has no rights_confirmed column; this is the transaction
        # evidence field and must agree across all rows in the aggregate.
        "rights_confirmed": _only_database_value(row.get("rights_confirmed") for row in rows),
        "limitations": source_first("source_limitations", "transaction_limitations"),
        "license": _only_database_value(row.get("source_license") for row in rows),
    }


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
            rows = [dict(row) for row in await conn.fetch(
                """select t.unit_price_jpy_per_sqm, t.data_class::text as data_class,
                          t.source_url as transaction_source_url, t.retrieved_at, t.imported_at,
                          t.trade_quarter, t.source_period as transaction_source_period, t.transformation_version,
                          t.rights_status, t.rights_confirmed, t.limitations as transaction_limitations,
                          s.id::text as source_id, s.name as source_name, s.url as source_url,
                          s.data_class::text as source_data_class, s.permission_status as source_permission_status,
                          s.observed_at as source_observed_at, s.last_success_at as source_last_success_at,
                          s.source_period, s.transformation_version as source_transformation_version,
                          s.limitations as source_limitations, s.license as source_license
                   from public.mlit_transactions t
                   left join public.sources s on s.id=t.source_id
                   where t.prefecture=$1 and t.city=$2 and t.asset_type=$3
                     and t.trade_quarter=$4 and ($5::text is null or t.ward=$5)
                   order by t.id""",
                prefecture, city, query_asset_type, period, ward,
            )]
            result = aggregate_region_rows(rows, asset_type=asset_type, period=period)
            provenance = _region_statistic_provenance(rows) if result["sample_size"] > 0 else None
            sources = {
                (row["source_id"], row["source_name"], row["source_url"])
                for row in rows if row.get("source_id") and row.get("source_url")
            }
            result.update({
                "ward": ward,
                "sources": [
                    {"id": source_id, "name": source_name, "url": source_url}
                    for source_id, source_name, source_url in sorted(sources)
                ],
                "license": {"name": provenance["license"]} if provenance else {},
            })
            if provenance:
                result.update(statistic_provenance(
                    data_class=provenance["data_class"], source_url=provenance["source_url"],
                    retrieved_at=provenance["retrieved_at"], source_period=provenance["source_period"],
                    transformation_version=provenance["transformation_version"], rights_status=provenance["rights_status"],
                    rights_confirmed=provenance["rights_confirmed"], sample_size=int(result["sample_size"]),
                    # These three constants describe this deterministic calculation,
                    # not source evidence.  Change them when its algorithm changes.
                    aggregation_method="mean_median_quartiles",
                    missing_value_policy="exclude_missing_or_nonpositive_unit_price",
                    limitations=provenance["limitations"], unit="JPY/sqm",
                ))
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
    if result.get("sample_size", 0) > 0:
        assert_statistic_provenance(result)
    return result
