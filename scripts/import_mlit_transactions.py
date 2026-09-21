#!/usr/bin/env python3
"""Import official MLIT XIT001 transaction data, with local CSV fallback."""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from backend.app.region_stats import map_asset_type
from backend.app.region_names import RegionMappingReport, map_region_names

SOURCE_ID = "bf4b6d56-f7ed-4e66-b599-3900e22001d6"
XIT001_URL = os.getenv("MLIT_XIT001_URL", "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001")
DEFAULT_PREFECTURES = ("13", "27", "15")
DEFAULT_YEARS = (2025, 2026)
QUARTER_RE = re.compile(r"^(\d{4})年第([1-4])四半期$")
# This names the stable normalizer algorithm, not an individual download;
# increment it when normalization rules change.
TRANSFORMATION_VERSION = "mlit-xit001-normalizer-v1"
SOURCE_URL = "https://www.reinfolib.mlit.go.jp/realEstatePrices/"
LIMITATIONS = "Official closed-transaction observations; exclude incomplete or nonpositive price and area fields."


def decode_xit001_response(payload: bytes, content_encoding: str, *, status_code: int = 200) -> dict[str, Any]:
    if status_code == 404:
        return {"status": "NO_DATA", "data": []}
    if status_code != 200:
        raise RuntimeError(f"XIT001 request failed with HTTP {status_code}")
    if "gzip" in (content_encoding or "").lower() or payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    response = json.loads(payload.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("XIT001 returned a non-object response")
    return response


def request_xit001(params: dict[str, str], api_key: str, opener=urllib.request.urlopen) -> dict[str, Any]:
    url = f"{XIT001_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Ocp-Apim-Subscription-Key": api_key, "Accept": "application/json"},
    )
    try:
        with opener(request, timeout=120) as response:
            return decode_xit001_response(
                response.read(), response.headers.get("Content-Encoding", ""), status_code=response.status
            )
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"status": "NO_DATA", "data": []}
        raise RuntimeError(f"XIT001 request failed with HTTP {error.code}") from None


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text or text in {"-", "不明"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def _quarter(value: str) -> tuple[int, str] | None:
    match = QUARTER_RE.fullmatch(value.strip())
    if not match:
        return None
    year, quarter = int(match.group(1)), int(match.group(2))
    return year, f"{year}Q{quarter}"


def _source_record_key(raw: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize_xit001_row(
    row: dict[str, Any], imported_at: datetime, *, region_report: RegionMappingReport | None = None
) -> dict[str, Any] | None:
    raw_kind = str(row.get("Type") or "").strip()
    asset_type = map_asset_type(raw_kind)
    quarter = _quarter(str(row.get("Period") or ""))
    price = _number(str(row.get("TradePrice") or ""))
    area = _number(str(row.get("Area") or ""))
    if not asset_type or not quarter or price is None or area is None:
        return None
    raw = dict(row)
    municipality = str(row.get("Municipality") or "").strip()
    prefecture, city, ward = map_region_names(
        str(row.get("Prefecture") or ""), municipality, report=region_report
    )
    if not prefecture or not city:
        return None
    unit_price = _number(str(row.get("UnitPrice") or "")) or price / area
    return {
        "source_id": SOURCE_ID,
        "source_record_key": _source_record_key(raw),
        "prefecture": prefecture,
        "city": city,
        "ward": ward,
        "asset_kind": raw_kind,
        "asset_type": asset_type,
        "price_jpy": round(price),
        "area_sqm": area,
        "unit_price_jpy_per_sqm": unit_price,
        "trade_quarter": quarter[1],
        "trade_year": quarter[0],
        "nearest_station": None,
        "distance_minutes": None,
        "layout": str(row.get("FloorPlan") or "").strip() or None,
        "raw": raw,
        "imported_at": imported_at,
        "data_class": "verified_observation",
        "source_url": SOURCE_URL,
        "retrieved_at": imported_at,
        "source_period": quarter[1],
        "transformation_version": TRANSFORMATION_VERSION,
        "rights_status": "rights_confirmed",
        "rights_confirmed": "yes",
        "limitations": LIMITATIONS,
        "missing_value_policy": "exclude_missing_or_nonpositive_price_or_area",
    }


def normalize_xit001_rows(
    rows: list[dict[str, Any]], imported_at: datetime, *, region_report: RegionMappingReport | None = None
) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    skipped_unmapped = 0
    for row in rows:
        raw_type = str(row.get("Type") or "").strip()
        if not map_asset_type(raw_type):
            skipped_unmapped += 1
            if region_report:
                region_report._add_sample(region_report.type_samples, raw_type)
            continue
        item = normalize_xit001_row(row, imported_at, region_report=region_report)
        if item:
            normalized.append(item)
    return normalized, skipped_unmapped


def print_unmapped_samples(*, skipped_unmapped_type: int, report: RegionMappingReport) -> None:
    if report.unmapped_prefecture > 0:
        print(f"unmapped_prefecture_samples={','.join(report.prefecture_samples[:5])}")
    if report.unmapped_city > 0:
        print(f"unmapped_city_samples={','.join(report.city_samples[:5])}")
    if skipped_unmapped_type > 0:
        print(f"skipped_unmapped_type_samples={','.join(report.type_samples[:5])}")


def normalize_row(
    row: dict[str, str], imported_at: datetime, *, region_report: RegionMappingReport | None = None
) -> dict[str, Any] | None:
    raw_kind = (row.get("種類") or "").strip()
    asset_type = map_asset_type(raw_kind)
    quarter = _quarter(row.get("取引時期") or "")
    price = _number(row.get("取引価格（総額）"))
    area = _number(row.get("面積（㎡）"))
    if not asset_type or not quarter or price is None or area is None:
        return None
    raw = dict(row)
    key = _source_record_key(raw)
    municipality = (row.get("市区町村名") or "").strip()
    prefecture, city, ward = map_region_names(
        (row.get("都道府県名") or "").strip(), municipality, report=region_report
    )
    if not prefecture or not city:
        return None
    return {
        "source_id": SOURCE_ID,
        "source_record_key": key,
        "prefecture": prefecture,
        "city": city,
        "ward": ward,
        "asset_kind": raw_kind,
        "asset_type": asset_type,
        "price_jpy": round(price),
        "area_sqm": area,
        "unit_price_jpy_per_sqm": price / area,
        "trade_quarter": quarter[1],
        "trade_year": quarter[0],
        "nearest_station": (row.get("最寄駅：名称") or "").strip() or None,
        "distance_minutes": int(_number(row.get("最寄駅：距離（分）")) or 0) or None,
        "layout": (row.get("間取り") or "").strip() or None,
        "raw": raw,
        "imported_at": imported_at,
        "data_class": "verified_observation",
        "source_url": SOURCE_URL,
        "retrieved_at": imported_at,
        "source_period": quarter[1],
        "transformation_version": TRANSFORMATION_VERSION,
        "rights_status": "rights_confirmed",
        "rights_confirmed": "yes",
        "limitations": LIMITATIONS,
        "missing_value_policy": "exclude_missing_or_nonpositive_price_or_area",
    }


def rows_from_zip(
    data: bytes, imported_at: datetime, *, region_report: RegionMappingReport | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                text = io.TextIOWrapper(stream, encoding="cp932", newline="")
                rows.extend(
                    item for row in csv.DictReader(text)
                    if (item := normalize_row(row, imported_at, region_report=region_report))
                )
    return rows


def rows_from_csv_path(
    path: Path, imported_at: datetime, *, region_report: RegionMappingReport | None = None
) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".zip":
        return rows_from_zip(path.read_bytes(), imported_at, region_report=region_report)
    with path.open("r", encoding="cp932", newline="") as stream:
        return [
            item for row in csv.DictReader(stream)
            if (item := normalize_row(row, imported_at, region_report=region_report))
        ]


MLIT_COLUMNS = (
    "source_id",
    "source_record_key",
    "prefecture",
    "city",
    "ward",
    "asset_kind",
    "asset_type",
    "price_jpy",
    "area_sqm",
    "unit_price_jpy_per_sqm",
    "trade_quarter",
    "trade_year",
    "nearest_station",
    "distance_minutes",
    "layout",
    "raw",
    "imported_at",
    "data_class",
    "source_url",
    "retrieved_at",
    "source_period",
    "transformation_version",
    "rights_status",
    "rights_confirmed",
    "limitations",
    "missing_value_policy",
)


def _row_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        json.dumps(row[column], ensure_ascii=False, separators=(",", ":")) if column == "raw" else row[column]
        for column in MLIT_COLUMNS
    )


def _deduplicate_chunk(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the first row for each source key and count discarded duplicates.

    ``source_record_key`` is the SHA-256 of the complete raw record. Equal keys
    therefore mean equal raw records and equal derived columns, so keeping the
    first occurrence cannot discard information.
    """
    unique_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        key = row["source_record_key"]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_rows.append(row)
    return unique_rows, len(rows) - len(unique_rows)


async def upsert_rows(database_url: str, rows: list[dict[str, Any]], *, chunk_size: int = 5000) -> dict[str, int]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    conn = await asyncpg.connect(database_url)
    try:
        if not rows:
            return {"inserted": 0, "updated": 0, "skipped": 0}
        await conn.execute("""create temporary table _mlit_transactions_import (
            source_id uuid not null,
            source_record_key text not null,
            prefecture text not null,
            city text not null,
            ward text,
            asset_kind text not null,
            asset_type text not null,
            price_jpy numeric(18,0),
            area_sqm numeric(12,2),
            unit_price_jpy_per_sqm numeric(18,2),
            trade_quarter text not null,
            trade_year smallint not null,
            nearest_station text,
            distance_minutes smallint,
            layout text,
            raw text not null,
            imported_at timestamptz not null,
            data_class text not null,
            source_url text not null,
            retrieved_at timestamptz not null,
            source_period text not null,
            transformation_version text not null,
            rights_status text not null,
            rights_confirmed text not null,
            limitations text not null,
            missing_value_policy text not null
        ) on commit preserve rows""")
        inserted = 0
        updated = 0
        for chunk_number, start in enumerate(range(0, len(rows), chunk_size), start=1):
            chunk = rows[start : start + chunk_size]
            unique_chunk, duplicate_count = _deduplicate_chunk(chunk)
            async with conn.transaction():
                await conn.execute("truncate _mlit_transactions_import")
                await conn.copy_records_to_table(
                    "_mlit_transactions_import",
                    records=(_row_values(row) for row in unique_chunk),
                    columns=MLIT_COLUMNS,
                )
            counts = await conn.fetchrow("""with upserted as (
                    insert into public.mlit_transactions
                        (source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
                         unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,raw,imported_at,
                         data_class,source_url,retrieved_at,source_period,transformation_version,rights_status,rights_confirmed,
                         limitations,missing_value_policy)
                    select source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
                           unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,
                           raw::jsonb,imported_at,data_class::public.data_class,source_url,retrieved_at,source_period,
                           transformation_version,rights_status,rights_confirmed,limitations,missing_value_policy
                    from _mlit_transactions_import
                    on conflict (source_id,source_record_key) do update set
                        prefecture=excluded.prefecture,
                        city=excluded.city,
                        ward=excluded.ward,
                        asset_type=excluded.asset_type,
                        layout=excluded.layout,
                        raw=excluded.raw,
                        data_class=excluded.data_class,
                        source_url=excluded.source_url,
                        retrieved_at=excluded.retrieved_at,
                        source_period=excluded.source_period,
                        transformation_version=excluded.transformation_version,
                        rights_status=excluded.rights_status,
                        rights_confirmed=excluded.rights_confirmed,
                        limitations=excluded.limitations,
                        missing_value_policy=excluded.missing_value_policy
                    where public.mlit_transactions.prefecture is distinct from excluded.prefecture
                       or public.mlit_transactions.city is distinct from excluded.city
                       or public.mlit_transactions.ward is distinct from excluded.ward
                       or public.mlit_transactions.asset_type is distinct from excluded.asset_type
                       or public.mlit_transactions.layout is distinct from excluded.layout
                       or public.mlit_transactions.raw is distinct from excluded.raw
                       or public.mlit_transactions.data_class is distinct from excluded.data_class
                       or public.mlit_transactions.source_url is distinct from excluded.source_url
                       or public.mlit_transactions.retrieved_at is distinct from excluded.retrieved_at
                       or public.mlit_transactions.source_period is distinct from excluded.source_period
                       or public.mlit_transactions.transformation_version is distinct from excluded.transformation_version
                       or public.mlit_transactions.rights_status is distinct from excluded.rights_status
                       or public.mlit_transactions.rights_confirmed is distinct from excluded.rights_confirmed
                       or public.mlit_transactions.limitations is distinct from excluded.limitations
                       or public.mlit_transactions.missing_value_policy is distinct from excluded.missing_value_policy
                    returning (xmax = 0) as inserted
                ) select count(*) filter (where inserted) as inserted,
                         count(*) filter (where not inserted) as updated
                    from upserted""")
            chunk_inserted = int(counts["inserted"])
            chunk_updated = int(counts["updated"])
            inserted += chunk_inserted
            updated += chunk_updated
            chunk_skipped = duplicate_count + len(unique_chunk) - chunk_inserted - chunk_updated
            processed = start + len(chunk)
            skipped = processed - inserted - updated
            print(
                f"chunk={chunk_number} input={len(chunk)} inserted={chunk_inserted} updated={chunk_updated} skipped={chunk_skipped} "
                f"cumulative={inserted + updated}/{skipped}"
            )
        skipped = len(rows) - inserted - updated
        return {"inserted": inserted, "updated": updated, "skipped": skipped}
    finally:
        await conn.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", choices=("api", "csv"), default="api")
    p.add_argument("--prefecture", action="append", dest="prefectures", help="MLIT prefecture code; repeatable")
    p.add_argument("--year", action="append", type=int, dest="years", help="year to include; repeatable")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument("--raw-dir", type=Path, default=Path("/tmp/zouseeking-mlit-raw"))
    p.add_argument("--csv-path", type=Path, help="local manually downloaded CSV or ZIP when --source csv")
    p.add_argument("--chunk-size", type=int, default=5000, help="rows per committed database chunk")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    api_key = os.getenv("MLIT_API_KEY", "").strip()
    if args.source == "api" and not api_key:
        print("MLIT_API_KEY 未配置；官方 CSV 下载接口需要服务端订阅值。", file=sys.stderr)
        return 2
    if args.source == "csv" and not args.csv_path:
        print("--csv-path 未配置；CSV 兜底只读取人工下载的本地 CSV/ZIP。", file=sys.stderr)
        return 2
    if not args.dry_run and not args.database_url:
        print("DATABASE_URL 未配置；请只指向一次性本地数据库。", file=sys.stderr)
        return 2
    imported_at = datetime.now(timezone.utc)
    prefectures = tuple(args.prefectures or DEFAULT_PREFECTURES)
    years = tuple(args.years or DEFAULT_YEARS)
    all_rows: list[dict[str, Any]] = []
    skipped_unmapped = 0
    region_report = RegionMappingReport()
    if args.source == "csv":
        all_rows = rows_from_csv_path(args.csv_path, imported_at, region_report=region_report)
        print(f"csv path={args.csv_path.name} rows={len(all_rows)} status=OK")
    requests = 0
    if args.source == "api":
        for prefecture in prefectures:
            for year in years:
                for quarter in range(1, 5):
                    if requests:
                        time.sleep(2)
                    requests += 1
                    payload = request_xit001(
                        {"year": str(year), "quarter": str(quarter), "area": prefecture, "language": "ja"}, api_key
                    )
                    raw_data = payload.get("data") or []
                    rows, unmapped = normalize_xit001_rows(raw_data, imported_at, region_report=region_report)
                    skipped_unmapped += unmapped
                    all_rows.extend(rows)
                    status = payload.get("status", "NO_DATA")
                    print(f"request prefecture={prefecture} year={year} quarter={quarter} rows={len(rows)} status={status}")
    if args.dry_run:
        print(
            f"dry_run_rows={len(all_rows)} skipped_unmapped_type={skipped_unmapped} "
            f"unmapped_prefecture={region_report.unmapped_prefecture} unmapped_city={region_report.unmapped_city}"
        )
        print_unmapped_samples(skipped_unmapped_type=skipped_unmapped, report=region_report)
        return 0
    if args.chunk_size <= 0:
        print("--chunk-size 必须是正整数。", file=sys.stderr)
        return 2
    result = asyncio.run(upsert_rows(args.database_url, all_rows, chunk_size=args.chunk_size))
    print(
        f"normalized_rows={len(all_rows)} inserted={result['inserted']} updated={result['updated']} "
        f"skipped={result['skipped']} skipped_unmapped_type={skipped_unmapped} "
        f"unmapped_prefecture={region_report.unmapped_prefecture} unmapped_city={region_report.unmapped_city}"
    )
    print_unmapped_samples(skipped_unmapped_type=skipped_unmapped, report=region_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
