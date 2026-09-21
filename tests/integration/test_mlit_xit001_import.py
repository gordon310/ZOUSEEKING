import copy
import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest

import backend.app.db as db
import scripts.import_mlit_transactions as importer
from backend.app.region_names import load_field_options
from backend.app.auth import AuthUser
from backend.app.region_stats_routes import DbRegionStatsStore
from tests.support.pg_bootstrap import (
    bootstrap_and_migrate,
    configured_database_url,
    database_url,
    require_postgres_or_skip,
)


FIXTURE = Path("tests/fixtures/mlit_xit001_sample.json")
USER_ID = UUID("00000000-0000-0000-0000-000000000099")
BASE_URL = configured_database_url()


@pytest.fixture
def mlit_database_url():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    return BASE_URL


async def _rowwise_upsert(database_url, rows):
    query = """insert into public.mlit_transactions
        (source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
         unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,raw,imported_at,
         data_class,source_url,retrieved_at,source_period,transformation_version,rights_status,rights_confirmed,
         limitations,missing_value_policy)
        values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::public.data_class,$19,$20,$21,$22,$23,$24,$25,$26)
        on conflict (source_id,source_record_key) do nothing
        returning 1"""
    conn = await asyncpg.connect(database_url)
    try:
        inserted = 0
        async with conn.transaction():
            for row in rows:
                values = tuple(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")) if key == "raw" else value
                    for key, value in row.items()
                )
                inserted += (await conn.fetchval(query, *values)) or 0
        return {"inserted": inserted, "skipped": len(rows) - inserted}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_xit001_local_http_to_local_postgres_is_idempotent_and_queryable(mlit_database_url):
    base_url = mlit_database_url
    database = f"mlit_xit001_{uuid4().hex[:10]}"
    target_url = database_url(base_url, database)
    await bootstrap_and_migrate(base_url, database)
    original_url = importer.XIT001_URL
    server = None
    pool = None
    try:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = payload["data"][:2]
        expanded = []
        prices = [1_000_000, 1_500_000, 2_000_000, 2_500_000, 3_000_000]
        for index, unit_price in enumerate(prices):
            item = copy.deepcopy(rows[index % 2])
            item["Prefecture"] = "新潟県"
            item["Municipality"] = "新潟市中央区" if index % 2 == 0 else "南魚沼郡湯沢町"
            item["DistrictCode"] = f"15103{index + 10:04d}"
            item["DistrictName"] = f"fixture-{index}"
            item["Area"] = "50"
            item["TradePrice"] = str(unit_price * 50)
            item["UnitPrice"] = str(unit_price)
            expanded.append(item)
        body = json.dumps({"status": "OK", "data": expanded}, ensure_ascii=False).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        importer.XIT001_URL = f"http://127.0.0.1:{server.server_port}/ex-api/external/XIT001"
        local_opener = __import__("urllib.request", fromlist=["build_opener"]).build_opener(
            __import__("urllib.request", fromlist=["ProxyHandler"]).ProxyHandler({})
        ).open
        response = importer.request_xit001(
            {"year": "2025", "quarter": "1", "area": "13", "language": "ja"},
            "local-test-key",
            local_opener,
        )
        normalized, skipped_unmapped = importer.normalize_xit001_rows(
            response["data"], datetime(2026, 9, 17, tzinfo=timezone.utc)
        )
        assert len(normalized) == 5
        assert skipped_unmapped == 0
        first = await importer.upsert_rows(target_url, normalized)
        second = await importer.upsert_rows(target_url, normalized)
        assert first == {"inserted": 5, "updated": 0, "skipped": 0}
        assert second == {"inserted": 0, "updated": 0, "skipped": 5}

        async def query_region_stats():
            nonlocal pool
            conn = await asyncpg.connect(target_url)
            try:
                await conn.execute("insert into auth.users(id,email) values($1,$2)", USER_ID, "local@example.test")
                org_id = await conn.fetchval(
                    "insert into public.organizations(name, created_by_user_id) values('local test org',$1) returning id",
                    USER_ID,
                )
                await conn.execute(
                    "insert into public.organization_members(organization_id,user_id,role,status) values($1,$2,'owner','active')",
                    org_id,
                    USER_ID,
                )
            finally:
                await conn.close()
            pool = await asyncpg.create_pool(target_url, min_size=1, max_size=1)
            db.pool = pool
            result = await DbRegionStatsStore().get(
                AuthUser(USER_ID, "local@example.test", "Local"), "新潟县", "新潟市", "中央区", "公寓", "2025Q1"
            )
            return result

        result = await query_region_stats()
        assert result["sample_size"] == 3
        assert result["status"] == "insufficient_sample"
        conn = await asyncpg.connect(target_url)
        try:
            assert await conn.fetchval("select count(*) from mlit_transactions where prefecture='新潟县'") == 5
            assert await conn.fetchval("select count(*) from mlit_transactions where prefecture='新潟県'") == 0
            allowed = load_field_options()["cities"]["新潟县"]
            assert await conn.fetchval("select count(*) from mlit_transactions where city <> all($1::text[])", allowed) == 0
        finally:
            await conn.close()
    finally:
        importer.XIT001_URL = original_url
        if pool is not None:
            await pool.close()
        db.pool = None
        if server is not None:
            server.shutdown()
            server.server_close()
        admin = await asyncpg.connect(base_url, database="postgres")
        try:
            await admin.execute(f'drop database "{database}" with (force)')
        finally:
            await admin.close()


@pytest.mark.asyncio
async def test_batch_upsert_deduplicates_repeated_keys_within_one_chunk(mlit_database_url):
    base_url = mlit_database_url
    database = f"mlit_same_chunk_{uuid4().hex[:10]}"
    target_url = database_url(base_url, database)
    await bootstrap_and_migrate(base_url, database)
    try:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source_rows = payload["data"]
        rows = []
        for index in range(5):
            item = copy.deepcopy(source_rows[index % 2])
            item["DistrictName"] = f"same-chunk-fixture-{index}"
            item["TradePrice"] = str((index + 1) * 1_000_000)
            rows.append(importer.normalize_xit001_rows([item], datetime(2026, 9, 17, tzinfo=timezone.utc))[0][0])
        rows.extend([copy.deepcopy(rows[0]), copy.deepcopy(rows[1])])

        actual = await importer.upsert_rows(target_url, rows, chunk_size=7)

        assert actual == {"inserted": 5, "updated": 0, "skipped": 2}
    finally:
        admin = await asyncpg.connect(base_url, database="postgres")
        try:
            await admin.execute(f'drop database "{database}" with (force)')
        finally:
            await admin.close()


@pytest.mark.asyncio
async def test_batch_upsert_handles_more_than_one_chunk(mlit_database_url):
    base_url = mlit_database_url
    database = f"mlit_multi_chunk_{uuid4().hex[:10]}"
    target_url = database_url(base_url, database)
    await bootstrap_and_migrate(base_url, database)
    try:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = []
        for index in range(12):
            item = copy.deepcopy(payload["data"][index % 2])
            item["DistrictName"] = f"multi-chunk-fixture-{index}"
            item["TradePrice"] = str((index + 1) * 1_000_000)
            rows.append(importer.normalize_xit001_rows([item], datetime(2026, 9, 17, tzinfo=timezone.utc))[0][0])

        actual = await importer.upsert_rows(target_url, rows, chunk_size=5)

        assert actual == {"inserted": 12, "updated": 0, "skipped": 0}
        conn = await asyncpg.connect(target_url)
        try:
            assert await conn.fetchval("select count(*) from public.mlit_transactions") == 12
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(base_url, database="postgres")
        try:
            await admin.execute(f'drop database "{database}" with (force)')
        finally:
            await admin.close()


@pytest.mark.asyncio
async def test_batch_upsert_matches_rowwise_counts_and_preserves_raw_for_duplicates(mlit_database_url):
    base_url = mlit_database_url
    database = f"mlit_batch_{uuid4().hex[:10]}"
    target_url = database_url(base_url, database)
    reference_url = database_url(base_url, f"mlit_reference_{uuid4().hex[:10]}")
    await bootstrap_and_migrate(base_url, database)
    await bootstrap_and_migrate(base_url, reference_url.rsplit("/", 1)[-1])
    try:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        normalized, _ = importer.normalize_xit001_rows(
            payload["data"], datetime(2026, 9, 17, tzinfo=timezone.utc)
        )
        rows = normalized + [copy.deepcopy(normalized[0]), copy.deepcopy(normalized[1])]
        expected = await _rowwise_upsert(reference_url, rows)
        actual = await importer.upsert_rows(target_url, rows, chunk_size=2)
        assert actual == {"inserted": 2, "updated": 0, "skipped": 2}
        second = await importer.upsert_rows(target_url, rows, chunk_size=2)
        assert second == {"inserted": 0, "updated": 0, "skipped": 4}
        conn = await asyncpg.connect(target_url)
        try:
            stored = await conn.fetchval(
                "select raw from public.mlit_transactions where source_record_key=$1",
                normalized[0]["source_record_key"],
            )
            assert json.loads(stored) == normalized[0]["raw"]

            await conn.execute(
                "update public.mlit_transactions set prefecture='東京都', city='港区' where source_record_key=$1",
                normalized[0]["source_record_key"],
            )
        finally:
            await conn.close()
        repaired = await importer.upsert_rows(target_url, normalized[:1])
        assert repaired == {"inserted": 0, "updated": 1, "skipped": 0}
        conn = await asyncpg.connect(target_url)
        try:
            repaired_row = await conn.fetchrow(
                "select prefecture, city from public.mlit_transactions where source_record_key=$1",
                normalized[0]["source_record_key"],
            )
            assert (repaired_row["prefecture"], repaired_row["city"]) == ("东京都", "港区")
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(base_url, database="postgres")
        try:
            await admin.execute(f'drop database "{database}" with (force)')
            await admin.execute(f'drop database "{reference_url.rsplit("/", 1)[-1]}" with (force)')
        finally:
            await admin.close()
