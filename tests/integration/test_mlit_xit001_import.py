import copy
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
from backend.app.auth import AuthUser
from backend.app.region_stats_routes import DbRegionStatsStore
from tests.support.pg_bootstrap import bootstrap_and_migrate, database_url


FIXTURE = Path("tests/fixtures/mlit_xit001_sample.json")
USER_ID = UUID("00000000-0000-0000-0000-000000000099")


async def _rowwise_upsert(database_url, rows):
    query = """insert into public.mlit_transactions
        (source_id,source_record_key,prefecture,city,ward,asset_kind,asset_type,price_jpy,area_sqm,
         unit_price_jpy_per_sqm,trade_quarter,trade_year,nearest_station,distance_minutes,layout,raw,imported_at)
        values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
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
async def test_xit001_local_http_to_local_postgres_is_idempotent_and_queryable():
    base_url = os.getenv("MLIT_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("NOT_EXECUTED: set MLIT_TEST_DATABASE_URL to a disposable local PostgreSQL URL")
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
            item["DistrictCode"] = f"13103{index + 10:04d}"
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
        assert first == {"inserted": 5, "skipped": 0}
        assert second == {"inserted": 0, "skipped": 5}

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
                AuthUser(USER_ID, "local@example.test", "Local"), "東京都", "港区", None, "公寓", "2025Q1"
            )
            return result

        result = await query_region_stats()
        assert result["sample_size"] == 5
        assert result["median_unit_price_jpy_per_sqm"] == 2_000_000
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
async def test_batch_upsert_matches_rowwise_counts_and_preserves_raw_for_duplicates():
    base_url = os.getenv("MLIT_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("NOT_EXECUTED: set MLIT_TEST_DATABASE_URL to a disposable local PostgreSQL URL")
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
        assert actual == expected == {"inserted": 2, "skipped": 2}
        second = await importer.upsert_rows(target_url, rows, chunk_size=2)
        assert second == {"inserted": 0, "skipped": 4}
        conn = await asyncpg.connect(target_url)
        try:
            stored = await conn.fetchval(
                "select raw from public.mlit_transactions where source_record_key=$1",
                normalized[0]["source_record_key"],
            )
            assert json.loads(stored) == normalized[0]["raw"]
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(base_url, database="postgres")
        try:
            await admin.execute(f'drop database "{database}" with (force)')
            await admin.execute(f'drop database "{reference_url.rsplit("/", 1)[-1]}" with (force)')
        finally:
            await admin.close()
