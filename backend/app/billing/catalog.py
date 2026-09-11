"""Immutable, server-owned product and local-price catalog."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from ..db import get_pool
from .entitlements import PLAN_AUDIENCE, normalize_entitlements


ProductCode = Literal["risk_report_single", "c_plus_monthly", "b_data_pro_monthly"]
CheckoutMode = Literal["payment", "subscription"]

# Only regions with a confirmed local price may be purchased. Prices are
# server-owned local amounts; no client-side exchange rate is applied.
REGION_CURRENCY: Mapping[str, str] = {
    "CN": "CNY",
    "JP": "JPY",
    "US": "USD",
    "TW": "TWD",
    "HK": "HKD",
    "SG": "SGD",
    # Macau commonly settles in HKD; add MOP only in a later price release.
    "MO": "HKD",
}

PRICE_VERSION = "v1-2026-08"


class PriceUnavailable(ValueError):
    """The requested product/region has no server-approved purchasable price."""


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceDefinition:
    product_code: str
    price_version: str
    currency: str
    amount_minor: int
    mode: CheckoutMode
    stripe_price_id: str

    @property
    def available(self) -> bool:
        return bool(self.stripe_price_id)


@dataclass(frozen=True)
class PlanDefinition:
    plan_code: str
    name: str
    monthly_query_limit: Optional[int]
    monthly_report_quota: Optional[int]
    subscription_slots: Optional[int]
    export_rows_monthly: Optional[int]
    audience: str = "c"
    entitlements: Mapping[Tuple[str, str], int] = None

    def limit(self, metric: str, period: str) -> Optional[int]:
        if self.entitlements and (metric, period) in self.entitlements:
            return self.entitlements[(metric, period)]
        return None


def _optional_int(value: Any) -> Optional[int]:
    return None if value is None else int(value)


_PRICE_SPECS: Tuple[Tuple[str, CheckoutMode, str, int], ...] = (
    ("risk_report_single", "payment", "CNY", 500),
    ("risk_report_single", "payment", "JPY", 100),
    ("risk_report_single", "payment", "USD", 99),
    ("risk_report_single", "payment", "TWD", 3000),
    ("risk_report_single", "payment", "HKD", 800),
    ("risk_report_single", "payment", "SGD", 150),
    ("c_plus_monthly", "subscription", "CNY", 4900),
    ("c_plus_monthly", "subscription", "JPY", 990),
    ("c_plus_monthly", "subscription", "USD", 990),
    ("c_plus_monthly", "subscription", "TWD", 30000),
    ("c_plus_monthly", "subscription", "HKD", 8000),
    ("c_plus_monthly", "subscription", "SGD", 1500),
    ("b_data_pro_monthly", "subscription", "CNY", 19900),
    ("b_data_pro_monthly", "subscription", "JPY", 3999),
    ("b_data_pro_monthly", "subscription", "USD", 3990),
    ("b_data_pro_monthly", "subscription", "TWD", 120000),
    ("b_data_pro_monthly", "subscription", "HKD", 32000),
    ("b_data_pro_monthly", "subscription", "SGD", 6000),
)


class PriceCatalog:
    """Resolve a product and verified billing region to one immutable price."""

    def __init__(self, price_ids: Mapping[str, str], *, pool: Any = None, cache_ttl: Optional[float] = None) -> None:
        self._price_ids: Dict[str, str] = {
            str(key): str(value or "").strip() for key, value in price_ids.items()
        }
        self._pool = pool
        self._cache_ttl = float(cache_ttl if cache_ttl is not None else os.getenv("PRICING_CACHE_TTL_SECONDS", "60"))
        self._loaded_at = 0.0
        self._db_rows: Optional[dict[str, Any]] = None
        # asyncio primitives are bound to the running loop on older Python
        # versions; construct lazily so sync callers and test fixtures remain
        # compatible.
        self._load_lock: Optional[asyncio.Lock] = None

    def _fallback_rows(self) -> dict[str, Any]:
        return {
            "regions": dict(REGION_CURRENCY),
            "products": {code: {"mode": mode} for code, mode, _, _ in _PRICE_SPECS},
            "prices": {
                (code, currency): {
                    "product_code": code,
                    "price_version": PRICE_VERSION,
                    "currency": currency,
                    "amount_minor": amount,
                    "mode": mode,
                    "stripe_price_id": self._price_ids.get(f"{code}:{currency}", ""),
                    "active": True,
                }
                for code, mode, currency, amount in _PRICE_SPECS
            },
            "plans": {
                **({"free": PlanDefinition("free", "Free", 3, 0, 0, 0, "c", normalize_entitlements("free_c", legacy={"monthly_query_limit": 3}))}),
                **{code: PlanDefinition(
                    code, name, legacy[0], legacy[1], legacy[2], legacy[3], PLAN_AUDIENCE[code],
                    normalize_entitlements(code, legacy={
                        "monthly_query_limit": legacy[0], "monthly_report_quota": legacy[1],
                        "subscription_slots": legacy[2], "export_rows_monthly": legacy[3],
                    }),
                ) for code, (name, *legacy) in {
                    "free_c": ("C Free", 3, 0, 0, 0),
                    "c_plus": ("C Plus", 100, 12, 3, 0),
                    "free_b": ("B Free", 30, 0, 0, 0),
                    "b_data_pro": ("B Data Pro", 500, 100, 10, 10000),
                }.items()}
            },
        }

    async def ensure_loaded(self, *, force: bool = False) -> None:
        if not force and self._db_rows is not None and time.monotonic() - self._loaded_at < self._cache_ttl:
            return
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        async with self._load_lock:
            if not force and self._db_rows is not None and time.monotonic() - self._loaded_at < self._cache_ttl:
                return
            try:
                pool = self._pool if self._pool is not None else get_pool()
                async with pool.acquire() as conn:
                    products = await conn.fetch("select product_code, checkout_mode as mode, active from public.pricing_products where active = true")
                    regions = await conn.fetch("select region_code, currency from public.pricing_regions where active = true")
                    prices = await conn.fetch(
                        "select distinct on (pp.product_code, pp.currency) pp.product_code, pp.currency, pp.amount_minor, pp.stripe_price_id, pp.price_version, pp.active, pp.effective_from, p.checkout_mode as mode "
                        "from public.pricing_prices pp join public.pricing_products p on p.product_code = pp.product_code "
                        "where pp.active = true and p.active = true order by pp.product_code, pp.currency, pp.price_version desc, pp.effective_from desc, pp.created_at desc"
                    )
                    plans = await conn.fetch("select plan_code, name, audience, monthly_query_limit, monthly_report_quota, subscription_slots, export_rows_monthly from public.pricing_plans where active = true")
                    try:
                        entitlements = await conn.fetch("select plan_code, metric, limit_units, period, active from public.plan_entitlements where active = true")
                    except Exception as exc:
                        logger.warning("plan entitlements table unavailable; using legacy plan columns: %s", type(exc).__name__)
                        entitlements = []
                if not products or not regions or not prices:
                    raise LookupError("pricing catalog is empty")
                self._db_rows = {
                    "regions": {str(row["region_code"]): str(row["currency"]) for row in regions},
                    "products": {str(row["product_code"]): dict(row) for row in products},
                    "prices": {(str(row["product_code"]), str(row["currency"])): dict(row) for row in prices},
                        "plans": {
                            str(row["plan_code"]): PlanDefinition(
                                str(row["plan_code"]), str(row["name"]), _optional_int(row["monthly_query_limit"]),
                                _optional_int(row["monthly_report_quota"]), _optional_int(row["subscription_slots"]), _optional_int(row["export_rows_monthly"]),
                                str(dict(row).get("audience") or PLAN_AUDIENCE.get(str(row["plan_code"]), "c")),
                                normalize_entitlements(str(row["plan_code"]), rows=[e for e in entitlements if str(e["plan_code"]) == str(row["plan_code"])], legacy=dict(row)),
                            ) for row in plans
                        },
                }
            except Exception as exc:
                logger.warning("pricing DB catalog unavailable; using fallback defaults: %s", type(exc).__name__)
                self._db_rows = self._fallback_rows()
            self._loaded_at = time.monotonic()

    def load_rows_for_test(self, rows: dict[str, Any]) -> None:
        """Install a snapshot without I/O for deterministic catalog tests."""
        self._db_rows = rows
        self._loaded_at = time.monotonic()

    def _rows(self) -> dict[str, Any]:
        return self._db_rows or self._fallback_rows()

    def list_public(self) -> List[dict]:
        """Return render-safe rows without provider identifiers."""

        rows: List[dict] = []
        for item in self._rows()["prices"].values():
            rows.append({key: item[key] for key in ("product_code", "price_version", "currency", "amount_minor", "mode") if key in item} | {"available": bool(item.get("stripe_price_id"))})
        return sorted(rows, key=lambda row: (row["product_code"], row["currency"]))

    async def list_public_async(self) -> List[dict]:
        await self.ensure_loaded()
        return self.list_public()

    def get_plan(self, plan_code: str) -> PlanDefinition:
        plan = self._rows()["plans"].get(plan_code)
        if plan is None:
            raise PriceUnavailable("plan is not configured")
        return plan

    async def get_plan_async(self, plan_code: str) -> PlanDefinition:
        await self.ensure_loaded()
        return self.get_plan(plan_code)

    def resolve(
        self,
        product_code: str,
        billing_region: str,
        *,
        currency: Optional[str] = None,
    ) -> PriceDefinition:
        if currency is not None:
            raise PriceUnavailable("currency is selected by billing region")

        region = str(billing_region or "").strip().upper()
        selected_currency = self._rows()["regions"].get(region)
        if not selected_currency:
            raise PriceUnavailable("no local price for billing region")

        item = self._rows()["prices"].get((product_code, selected_currency))
        if item is not None:
            stripe_price_id = str(item.get("stripe_price_id") or "")
            if not stripe_price_id or not item.get("active", True):
                raise PriceUnavailable("price is not configured")
            mode = self._rows()["products"].get(product_code, {}).get("mode", item.get("mode"))
            return PriceDefinition(product_code, str(item["price_version"]), selected_currency, int(item["amount_minor"]), mode, stripe_price_id)

        raise PriceUnavailable("unknown product")
