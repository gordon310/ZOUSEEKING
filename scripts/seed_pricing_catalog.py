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
    "free": ("Free", 3, 0, 0, 0),
    "c_plus": ("C Plus", 100, 12, 3, 0),
    "b_data_pro": ("B Data Pro", 500, 100, 10, 10000),
}


async def seed() -> dict[str, int]:
    raw_ids = os.getenv("STRIPE_PRICE_IDS", "{}")
    price_ids = json.loads(raw_ids) if raw_ids.strip() else {}
    counts = {"products": 0, "prices": 0, "regions": 0, "plans": 0}
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for code, (name, mode) in PRODUCTS.items():
                counts["products"] += int(bool(await conn.fetchval("insert into public.pricing_products (product_code,name,checkout_mode) values ($1,$2,$3) on conflict (product_code) do nothing returning product_code", code, name, mode)))
            for code, currency in REGIONS.items():
                counts["regions"] += int(bool(await conn.fetchval("insert into public.pricing_regions (region_code,currency) values ($1,$2) on conflict (region_code) do nothing returning region_code", code, currency)))
            for code, (name, query_limit, report_quota, slots, export_rows) in PLANS.items():
                counts["plans"] += int(bool(await conn.fetchval("insert into public.pricing_plans (plan_code,name,monthly_query_limit,monthly_report_quota,subscription_slots,export_rows_monthly) values ($1,$2,$3,$4,$5,$6) on conflict (plan_code) do nothing returning plan_code", code, name, query_limit, report_quota, slots, export_rows)))
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
