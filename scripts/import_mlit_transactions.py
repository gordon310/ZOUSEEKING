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

SOURCE_ID = "bf4b6d56-f7ed-4e66-b599-3900e22001d6"
XIT001_URL = os.getenv("MLIT_XIT001_URL", "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001")
DEFAULT_PREFECTURES = ("13", "27", "15")
DEFAULT_YEARS = (2025, 2026)
QUARTER_RE = re.compile(r"^(\d{4})年第([1-4])四半期$")


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


def normalize_xit001_row(row: dict[str, Any], imported_at: datetime) -> dict[str, Any] | None:
    raw_kind = str(row.get("Type") or "").strip()
    asset_type = map_asset_type(raw_kind)
    quarter = _quarter(str(row.get("Period") or ""))
    price = _number(str(row.get("TradePrice") or ""))
    area = _number(str(row.get("Area") or ""))
    if not asset_type or not quarter or price is None or area is None:
        return None
    raw = dict(row)
    municipality = str(row.get("Municipality") or "").strip()
    ward = None
    city = municipality
    if municipality.startswith("大阪市") and municipality.endswith("区"):
        city, ward = "大阪市", municipality.removeprefix("大阪市")
    unit_price = _number(str(row.get("UnitPrice") or "")) or price / area
    return {
        "source_id": SOURCE_ID,
        "source_record_key": _source_record_key(raw),
        "prefecture": str(row.get("Prefecture") or "").strip(),
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
    }


def normalize_xit001_rows(rows: list[dict[str, Any]], imported_at: datetime) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    skipped_unmapped = 0
    for row in rows:
        if not map_asset_type(str(row.get("Type") or "").strip()):
            skipped_unmapped += 1
            continue
        item = normalize_xit001_row(row, imported_at)
        if item:
            normalized.append(item)
    return normalized, skipped_unmapped


def normalize_row(row: dict[str, str], imported_at: datetime) -> dict[str, Any] | None:
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
    ward = None
    city = municipality
    if municipality.startswith("大阪市") and municipality.endswith("区"):
        city, ward = "大阪市", municipality.removeprefix("大阪市")
    return {
        "source_id": SOURCE_ID,
        "source_record_key": key,
        "prefecture": (row.get("都道府県名") or "").strip(),
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
    }


def rows_from_zip(data: bytes, imported_at: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                text = io.TextIOWrapper(stream, encoding="cp932", newline="")
                rows.extend(item for row in csv.DictReader(text) if (item := normalize_row(row, imported_at)))
    return rows


def rows_from_csv_path(path: Path, imported_at: datetime) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".zip":
        return rows_from_zip(path.read_bytes(), imported_at)
    with path.open("r", encoding="cp932", newline="") as stream:
        return [item for row in csv.DictReader(stream) if (item := normalize_row(row, imported_at))]


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
)


def _row_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        json.dumps(row[column], ensure_ascii=False, separators=(",", ":")) if column == "raw" else row[column]
        for column in MLIT_COLUMNS
    )


async def upsert_rows(database_url: str, rows: list[dict[str, Any]], *, chunk_size: int = 5000) -> dict[str, int]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    conn = await asyncpg.connect(database_url)
    try:
        if not rows:
            return {"inserted": 0, "skipped": 0}
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
            imported_at timestamptz not null
        ) on commit preserve rows""")
        inserted = 0
        for chunk_number, start in enumerate(range(0, len(rows), chunk_size), start=1):
            chunk = rows[start : start + chunk_size]
            async with conn.transaction():
                await conn.execute("truncate _mlit_transactions_import")
                await conn.copy_records_to_table(
                    "_mlit_transactions_import",
                    records=(_row_values(row) for row in chunk),
                    columns=MLIT_COLUMNS,
                )
                chunk_inserted = await conn.fetchval("""with inserted as (
                    insert into public.mlit_transactions
                        (source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
                         unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,raw,imported_at)
                    select source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
                           unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,
                           raw::jsonb,imported_at
                    from _mlit_transactions_import
                    on conflict (source_id,source_record_key) do nothing
                    returning 1
                ) select count(*) from inserted""")
            inserted += int(chunk_inserted)
            chunk_skipped = len(chunk) - int(chunk_inserted)
            processed = start + len(chunk)
            skipped = processed - inserted
            print(
                f"chunk={chunk_number} input={len(chunk)} inserted={chunk_inserted} skipped={chunk_skipped} "
                f"cumulative={inserted}/{skipped}"
            )
        skipped = len(rows) - inserted
        return {"inserted": inserted, "skipped": skipped}
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
    if args.source == "csv":
        all_rows = rows_from_csv_path(args.csv_path, imported_at)
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
                    rows, unmapped = normalize_xit001_rows(raw_data, imported_at)
                    skipped_unmapped += unmapped
                    all_rows.extend(rows)
                    status = payload.get("status", "NO_DATA")
                    print(f"request prefecture={prefecture} year={year} quarter={quarter} rows={len(rows)} status={status}")
    if args.dry_run:
        print(f"dry_run_rows={len(all_rows)}")
        return 0
    if args.chunk_size <= 0:
        print("--chunk-size 必须是正整数。", file=sys.stderr)
        return 2
    result = asyncio.run(upsert_rows(args.database_url, all_rows, chunk_size=args.chunk_size))
    print(f"normalized_rows={len(all_rows)} inserted={result['inserted']} skipped={result['skipped']} skipped_unmapped={skipped_unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
