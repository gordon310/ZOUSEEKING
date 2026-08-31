"""Immutable, server-owned product and local-price catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Mapping, Optional, Tuple


ProductCode = Literal["risk_report_single", "c_plus_monthly", "b_data_pro_monthly"]
CheckoutMode = Literal["payment", "subscription"]

# Only regions with a confirmed local price may be purchased.  The other V1
# launch regions remain intentionally unavailable until finance/legal approves
# and configures a local price; no client-side exchange rate is applied.
REGION_CURRENCY: Mapping[str, str] = {
    "CN": "CNY",
    "JP": "JPY",
    "US": "USD",
}

PRICE_VERSION = "v1-2026-08"


class PriceUnavailable(ValueError):
    """The requested product/region has no server-approved purchasable price."""


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


_PRICE_SPECS: Tuple[Tuple[str, CheckoutMode, str, int], ...] = (
    ("risk_report_single", "payment", "CNY", 500),
    ("risk_report_single", "payment", "JPY", 100),
    ("risk_report_single", "payment", "USD", 99),
    ("c_plus_monthly", "subscription", "CNY", 4900),
    ("c_plus_monthly", "subscription", "JPY", 990),
    ("c_plus_monthly", "subscription", "USD", 990),
    ("b_data_pro_monthly", "subscription", "CNY", 19900),
    ("b_data_pro_monthly", "subscription", "JPY", 3999),
    ("b_data_pro_monthly", "subscription", "USD", 3990),
)


class PriceCatalog:
    """Resolve a product and verified billing region to one immutable price."""

    def __init__(self, price_ids: Mapping[str, str]) -> None:
        self._price_ids: Dict[str, str] = {
            str(key): str(value or "").strip() for key, value in price_ids.items()
        }

    def list_public(self) -> List[dict]:
        """Return render-safe rows without provider identifiers."""

        rows: List[dict] = []
        for product_code, mode, currency, amount_minor in _PRICE_SPECS:
            price_key = f"{product_code}:{currency}"
            rows.append(
                {
                    "product_code": product_code,
                    "price_version": PRICE_VERSION,
                    "currency": currency,
                    "amount_minor": amount_minor,
                    "mode": mode,
                    "available": bool(self._price_ids.get(price_key)),
                }
            )
        return rows

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
        selected_currency = REGION_CURRENCY.get(region)
        if not selected_currency:
            raise PriceUnavailable("no local price for billing region")

        for candidate_product, mode, candidate_currency, amount_minor in _PRICE_SPECS:
            if candidate_product != product_code or candidate_currency != selected_currency:
                continue
            price_key = f"{candidate_product}:{candidate_currency}"
            stripe_price_id = self._price_ids.get(price_key, "")
            if not stripe_price_id:
                raise PriceUnavailable("price is not configured")
            return PriceDefinition(
                product_code=candidate_product,
                price_version=PRICE_VERSION,
                currency=candidate_currency,
                amount_minor=amount_minor,
                mode=mode,
                stripe_price_id=stripe_price_id,
            )

        raise PriceUnavailable("unknown product")
