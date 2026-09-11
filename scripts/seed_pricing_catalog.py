"""Idempotently seed the database-backed pricing catalog.

Run during deployment after applying the pricing migration; this module is
deliberately not imported by application startup and is not run by tests.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.billing.catalog import _PRICE_SPECS
from backend.app.db import close, connect, get_pool

PRODUCTS = {
    "risk_report_single": ("标准风险筛查报告", "payment"),
    "c_plus_monthly": ("C Plus", "subscription"),
    "b_data_pro_monthly": ("B Data Pro", "subscription"),
}
REGIONS = {"CN": "CNY", "JP": "JPY", "US": "USD", "TW": "TWD", "HK": "HKD", "SG": "SGD", "MO": "HKD"}
PLANS = {
    "free_c": {"name": "C Free", "audience": "c", "entitlements": {("query", "day"): 3}},
    "c_plus": {"name": "C Plus", "audience": "c", "entitlements": {("query", "month"): 100, ("report", "month"): 12, ("subscription_slot", "month"): 3}},
    "free_b": {"name": "B Free", "audience": "b", "entitlements": {("query", "month"): 30, ("stats_query", "month"): 5}},
    "b_data_pro": {"name": "B Data Pro", "audience": "b", "entitlements": {("query", "month"): 500, ("stats_query", "month"): 100, ("subscription_slot", "month"): 10, ("export_row", "month"): 10000}},
}


def legacy_values(spec: dict) -> tuple[int | None, int | None, int | None, int | None]:
    entitlements = spec["entitlements"]
    return (
        entitlements.get(("query", "month")),
        entitlements.get(("report", "month")),
        entitlements.get(("subscription_slot", "month")),
        entitlements.get(("export_row", "month")),
    )


async def seed() -> dict[str, int]:
    raw_ids = os.getenv("STRIPE_PRICE_IDS", "{}")
    price_ids = json.loads(raw_ids) if raw_ids.strip() else {}
    counts = {"products": 0, "prices": 0, "regions": 0, "plans": 0, "entitlements": 0}
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for code, (name, mode) in PRODUCTS.items():
                counts["products"] += int(bool(await conn.fetchval("insert into public.pricing_products (product_code,name,checkout_mode) values ($1,$2,$3) on conflict (product_code) do nothing returning product_code", code, name, mode)))
            for code, currency in REGIONS.items():
                counts["regions"] += int(bool(await conn.fetchval("insert into public.pricing_regions (region_code,currency) values ($1,$2) on conflict (region_code) do nothing returning region_code", code, currency)))
            await conn.execute("update public.pricing_plans set active=false, note='migrated to free_c/free_b; retained for compatibility' where plan_code='free'")
            for code, spec in PLANS.items():
                entitlements = spec["entitlements"]
                legacy = legacy_values(spec)
                counts["plans"] += int(bool(await conn.fetchval(
                    "insert into public.pricing_plans (plan_code,name,audience,monthly_query_limit,monthly_report_quota,subscription_slots,export_rows_monthly) values ($1,$2,$3,$4,$5,$6,$7) on conflict (plan_code) do update set name=excluded.name, audience=excluded.audience, monthly_query_limit=excluded.monthly_query_limit, monthly_report_quota=excluded.monthly_report_quota, subscription_slots=excluded.subscription_slots, export_rows_monthly=excluded.export_rows_monthly, active=true returning plan_code",
                    code, spec["name"], spec["audience"], *legacy,
                )))
                for (metric, period), limit_units in entitlements.items():
                    counts["entitlements"] += int(bool(await conn.fetchval(
                        "insert into public.plan_entitlements (plan_code,metric,period,limit_units,active,effective_from) values ($1,$2,$3,$4,true,now()) on conflict (plan_code,metric,period) where active do update set limit_units=excluded.limit_units, effective_from=excluded.effective_from returning id",
                        code, metric, period, limit_units,
                    )))
            for product_code, mode, currency, amount_minor in _PRICE_SPECS:
                stripe_id = str(price_ids.get(f"{product_code}:{currency}", "")).strip()
                counts["prices"] += int(bool(await conn.fetchval(
                    "insert into public.pricing_prices (product_code,currency,amount_minor,stripe_price_id,price_version) "
                    "select $1,$2,$3,$4,1 where not exists (select 1 from public.pricing_prices where product_code=$1 and currency=$2 and amount_minor=$3) returning id",
                    product_code, currency, amount_minor, stripe_id,
                )))
    return counts


async def main() -> None:
    await connect()
    try:
        print(json.dumps(await seed(), ensure_ascii=False, sort_keys=True))
    finally:
        await close()


if __name__ == "__main__":
    asyncio.run(main())
