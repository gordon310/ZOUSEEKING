#!/usr/bin/env python3
"""Import real MLIT transaction-price CSV downloads into PostgreSQL.

The MLIT web download endpoint returns JSON containing either a temporary ZIP
URL or a base64-encoded ZIP.  No fixture or estimate is used by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from backend.app.region_stats import map_asset_type

SOURCE_ID = "bf4b6d56-f7ed-4e66-b599-3900e22001d6"
DOWNLOAD_URL = "https://www.reinfolib.mlit.go.jp/in-api/api-aur/aur/csv/transactionPrices"
DEFAULT_PREFECTURES = ("13", "27", "15")
DEFAULT_YEARS = (2025, 2026)
QUARTER_RE = re.compile(r"^(\d{4})年第([1-4])四半期$")


def request_json(url: str, api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": api_key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def download_zip(params: dict[str, str], api_key: str, opener=urllib.request.urlopen) -> tuple[str, bytes]:
    url = f"{DOWNLOAD_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": api_key, "Accept": "application/json"})
    for attempt in range(12):
        with opener(req, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("processing"):
            time.sleep(min(5 * (attempt + 1), 30))
            continue
        if payload.get("isBase64Encoded"):
            return url, base64.b64decode(payload["body"])
        if payload.get("isExists") and payload.get("url"):
            with opener(urllib.request.Request(payload["url"]), timeout=120) as response:
                return url, response.read()
        if payload.get("body") and payload.get("statusCode") == 200:
            return url, base64.b64decode(payload["body"])
        raise RuntimeError("MLIT download returned an unusable response")
    raise RuntimeError("MLIT download remained in processing state after bounded polling")


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


def normalize_row(row: dict[str, str], imported_at: datetime) -> dict[str, Any] | None:
    raw_kind = (row.get("種類") or "").strip()
    asset_type = map_asset_type(raw_kind)
    quarter = _quarter(row.get("取引時期") or "")
    price = _number(row.get("取引価格（総額）"))
    area = _number(row.get("面積（㎡）"))
    if not asset_type or not quarter or price is None or area is None:
        return None
    raw = dict(row)
    key = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
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


async def upsert_rows(database_url: str, rows: list[dict[str, Any]]) -> int:
    conn = await asyncpg.connect(database_url)
    try:
        before = await conn.fetchval("select count(*) from public.mlit_transactions")
        await conn.executemany(
            """insert into public.mlit_transactions
            (source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
             unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,raw,imported_at)
            values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            on conflict (source_id,source_record_key) do nothing""",
            [tuple(json.dumps(value, ensure_ascii=False, separators=(",", ":")) if key == "raw" else value for key, value in row.items()) for row in rows],
        )
        after = await conn.fetchval("select count(*) from public.mlit_transactions")
        return int(after) - int(before)
    finally:
        await conn.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefecture", action="append", dest="prefectures", default=list(DEFAULT_PREFECTURES), help="MLIT prefecture code; repeatable")
    p.add_argument("--year", action="append", type=int, dest="years", default=list(DEFAULT_YEARS), help="year to include; repeatable")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument("--raw-dir", type=Path, default=Path("/tmp/zouseeking-mlit-raw"))
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    api_key = os.getenv("MLIT_API_KEY", "").strip()
    if not api_key:
        print("MLIT_API_KEY 未配置；官方 CSV 下载接口需要服务端订阅值。", file=sys.stderr)
        return 2
    if not args.dry_run and not args.database_url:
        print("DATABASE_URL 未配置；请只指向一次性本地数据库。", file=sys.stderr)
        return 2
    imported_at = datetime.now(timezone.utc)
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    for prefecture in args.prefectures:
        for year in args.years:
            params = {"language": "ja", "areaCondition": "address", "prefecture": prefecture,
                      "transactionPrice": "true", "closedPrice": "true", "kind": "used",
                      "seasonFrom": f"{year}1", "seasonTo": f"{year}4"}
            # The four-quarter window is narrowed below to the task's latest
            # periods by the caller; keeping each request bounded avoids a
            # giant unreviewable download.
            url, data = download_zip(params, api_key)
            (args.raw_dir / f"{prefecture}-{year}.zip").write_bytes(data)
            rows = rows_from_zip(data, imported_at)
            all_rows.extend(rows)
            print(f"download prefecture={prefecture} year={year} bytes={len(data)} rows={len(rows)} url={url}")
    if args.dry_run:
        print(f"dry_run_rows={len(all_rows)}")
        return 0
    inserted = asyncio.run(upsert_rows(args.database_url, all_rows))
    print(f"normalized_rows={len(all_rows)} attempted_insert_rows={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
