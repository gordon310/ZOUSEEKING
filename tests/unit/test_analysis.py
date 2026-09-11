from __future__ import annotations

from uuid import UUID

import pytest

from backend.app.analysis.routes import AnalysisRequest, DbAnalysisStore, aggregate_rows


class MeterConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, query, *args):
        self.statements.append(query)

    async def fetchrow(self, query, *args):
        if "from public.usage_quotas" in query:
            return {"consumed_units": 1, "reserved_units": 0, "limit_units": 5}
        raise AssertionError(f"unexpected fetchrow: {query}")


@pytest.mark.asyncio
async def test_meter_writes_stats_usage_event_and_idempotency() -> None:
    conn = MeterConnection()

    result = await DbAnalysisStore()._meter(
        conn,
        "user:00000000-0000-0000-0000-000000000030",
        5,
        UUID("00000000-0000-0000-0000-000000000030"),
    )

    assert result["remaining"] == 3
    assert any("usage_events" in statement and "stats_query" in statement for statement in conn.statements)
    assert any("usage_idempotency" in statement and "stats_query" in statement for statement in conn.statements)


def test_aggregate_rows_uses_numeric_fields_and_keeps_sample_counts() -> None:
    rows = [
        {
            "year": 2026,
            "month": 8,
            "prefecture": "大阪府",
            "city": "大阪市",
            "ward": "北区",
            "asset_type": "塔楼",
            "title": "大阪府大阪市北区塔楼成交参考",
            "data_class": "scraped_aggregate",
            "sale": [{"layout": "1LDK", "amount_yen": 5_000_000}],
            "rental": [],
            "data_sources": [{"name": "licensed source", "url": "https://example.test", "data_class": "scraped_aggregate"}],
        },
        {
            "year": 2026,
            "month": 8,
            "prefecture": "大阪府",
            "city": "大阪市",
            "ward": "北区",
            "asset_type": "塔楼",
            "title": "大阪府大阪市北区塔楼成交参考 2",
            "data_class": "scraped_aggregate",
            "sale": [{"layout": "1LDK", "amount_yen": 7_000_000}],
            "rental": [],
            "data_sources": [{"name": "licensed source", "url": "https://example.test", "data_class": "scraped_aggregate"}],
        },
        {
            "year": 2026,
            "month": 8,
            "prefecture": "大阪府",
            "city": "大阪市",
            "ward": "北区",
            "asset_type": "塔楼",
            "title": "synthetic",
            "data_class": "synthetic_fixture",
            "sale": [{"layout": "1LDK", "amount_yen": 99_000_000}],
            "rental": [],
            "data_sources": [],
        },
    ]

    result = aggregate_rows(rows, AnalysisRequest(metric="sale", layout="1LDK"))

    assert result["sample_count"] == 2
    assert result["points"] == [{"month": "2026-08", "value": 6_000_000.0, "sample_count": 2}]
    assert result["source_class"] == ["scraped_aggregate"]
    assert result["period"] == {"from": "2026-08", "to": "2026-08"}


def test_aggregate_rows_reports_insufficient_sample_without_zero_fill() -> None:
    result = aggregate_rows(
        [
            {
                "year": 2026,
                "month": 8,
                "prefecture": "大阪府",
                "city": "大阪市",
                "ward": "北区",
                "asset_type": "塔楼",
                "title": "only one",
                "data_class": "scraped_aggregate",
                "sale": [{"layout": "1LDK", "amount_yen": 5_000_000}],
                "rental": [],
                "data_sources": [],
            }
        ],
        AnalysisRequest(metric="sale", layout="1LDK"),
    )

    assert result["status"] == "insufficient_sample"
    assert result["points"] == []
    assert result["sample_count"] == 1
