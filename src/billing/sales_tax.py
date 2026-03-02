"""Sales-tax resolution for invoices (cache-first, Stripe fallback)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import desc, select

from src.billing.stripe_client import StripeClient
from src.core.config import settings
from src.core.db import async_session
from src.core.models.sales_tax_rate import SalesTaxRateCache

logger = logging.getLogger(__name__)


def _to_money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_upper(value: str | None) -> str:
    return (value or "").strip().upper()


async def _get_cached_rate(
    *,
    seller_state: str,
    buyer_state: str,
    buyer_postal_code: str,
    tax_category: str,
    currency: str,
) -> SalesTaxRateCache | None:
    now = datetime.now(UTC)
    async with async_session() as session:
        stmt = (
            select(SalesTaxRateCache)
            .where(
                SalesTaxRateCache.seller_state == seller_state,
                SalesTaxRateCache.buyer_state == buyer_state,
                SalesTaxRateCache.buyer_postal_code == buyer_postal_code,
                SalesTaxRateCache.tax_category == tax_category,
                SalesTaxRateCache.currency == currency,
                SalesTaxRateCache.expires_at > now,
            )
            .order_by(desc(SalesTaxRateCache.created_at))
            .limit(1)
        )
        return await session.scalar(stmt)


async def _store_cached_rate(
    *,
    seller_state: str,
    buyer_state: str,
    buyer_postal_code: str,
    tax_category: str,
    currency: str,
    tax_rate: float,
    source: str,
    jurisdiction: str | None,
) -> None:
    ttl = timedelta(hours=max(1, settings.invoice_tax_cache_ttl_hours))
    row = SalesTaxRateCache(
        id=uuid.uuid4(),
        seller_state=seller_state,
        buyer_state=buyer_state,
        buyer_postal_code=buyer_postal_code,
        tax_category=tax_category,
        currency=currency,
        tax_rate=tax_rate,
        source=source,
        jurisdiction=jurisdiction,
        expires_at=datetime.now(UTC) + ttl,
    )
    async with async_session() as session:
        session.add(row)
        await session.commit()


def _build_totals(
    *,
    subtotal: Decimal,
    tax_rate: Decimal,
    source: str,
    jurisdiction: str | None,
    cached: bool,
) -> dict[str, Any]:
    tax_amount = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = (subtotal + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "ok": True,
        "subtotal": float(subtotal),
        "tax_rate": float(tax_rate),
        "tax_amount": float(tax_amount),
        "total": float(total),
        "source": source,
        "jurisdiction": jurisdiction,
        "cached": cached,
    }


def _extract_stripe_tax(calc: dict[str, Any], subtotal: Decimal) -> tuple[Decimal, str | None]:
    tax_cents = int(
        calc.get("tax_amount_exclusive")
        or calc.get("tax_amount_inclusive")
        or 0
    )
    subtotal_cents = int((subtotal * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
    if subtotal_cents <= 0:
        return Decimal("0"), None
    rate = (Decimal(tax_cents) / Decimal(subtotal_cents)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )

    jurisdiction = None
    breakdown = calc.get("tax_breakdown") or []
    if breakdown and isinstance(breakdown, list):
        jurisdiction = breakdown[0].get("jurisdiction", {}).get("display_name")
    return rate, jurisdiction


async def resolve_sales_tax_for_invoice(invoice_data: dict[str, Any]) -> dict[str, Any]:
    """Resolve tax totals for an invoice draft.

    Uses cached DB rates first, then Stripe Tax calculations as fallback.
    """
    subtotal = _to_money(invoice_data.get("subtotal", invoice_data.get("total", 0)))
    if subtotal <= 0:
        return {
            "ok": False,
            "reason": "invalid_subtotal",
            "message_key": "tax_invalid_subtotal",
        }

    if not invoice_data.get("requires_sales_tax"):
        return _build_totals(
            subtotal=subtotal,
            tax_rate=Decimal("0"),
            source="not_required",
            jurisdiction=None,
            cached=True,
        )

    seller_state = _to_upper(invoice_data.get("seller_state"))
    buyer_state = _to_upper(invoice_data.get("buyer_state"))
    buyer_postal_code = (invoice_data.get("buyer_postal_code") or "").strip()
    buyer_city = (invoice_data.get("buyer_city") or "").strip()
    buyer_line1 = (invoice_data.get("buyer_address_line1") or "").strip()
    buyer_country = _to_upper(invoice_data.get("buyer_country") or "US")
    tax_category = (invoice_data.get("invoice_tax_category") or "general").strip().lower()
    currency = (invoice_data.get("currency") or "USD").upper()

    if not seller_state or not buyer_state or not buyer_postal_code:
        return {
            "ok": False,
            "reason": "missing_tax_address",
            "message_key": "tax_missing_address",
        }

    try:
        cached = await _get_cached_rate(
            seller_state=seller_state,
            buyer_state=buyer_state,
            buyer_postal_code=buyer_postal_code,
            tax_category=tax_category,
            currency=currency,
        )
        if cached is not None:
            return _build_totals(
                subtotal=subtotal,
                tax_rate=Decimal(str(cached.tax_rate)),
                source=cached.source,
                jurisdiction=cached.jurisdiction,
                cached=True,
            )
    except Exception:
        logger.exception("Sales-tax cache read failed")

    line_items: list[dict[str, Any]] = []
    invoice_tax_code = str(invoice_data.get("invoice_tax_category_code") or "").strip()
    for idx, item in enumerate(invoice_data.get("items", [])):
        amount = _to_money(item.get("amount"))
        amount_cents = int((amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
        if amount_cents <= 0:
            continue
        line_tax_code = str(item.get("tax_code") or invoice_tax_code).strip()
        if not line_tax_code:
            return {
                "ok": False,
                "reason": "missing_tax_category",
                "message_key": "tax_missing_category",
            }
        line_items.append({
            "amount": amount_cents,
            "reference": f"line_{idx + 1}",
            "tax_code": line_tax_code,
        })

    if not line_items:
        return {
            "ok": False,
            "reason": "no_taxable_items",
            "message_key": "tax_no_taxable_items",
        }

    stripe = StripeClient()
    if not stripe.is_configured:
        return {
            "ok": False,
            "reason": "stripe_not_configured",
            "message_key": "tax_provider_unavailable",
        }

    try:
        calc = await stripe.create_tax_calculation(
            currency=currency,
            line_items=line_items,
            customer_details={
                "country": buyer_country or "US",
                "line1": buyer_line1,
                "city": buyer_city,
                "state": buyer_state,
                "postal_code": buyer_postal_code,
            },
            tax_date=invoice_data.get("invoice_date"),
        )
        tax_rate, jurisdiction = _extract_stripe_tax(calc, subtotal)
        result = _build_totals(
            subtotal=subtotal,
            tax_rate=tax_rate,
            source="stripe",
            jurisdiction=jurisdiction,
            cached=False,
        )
        await _store_cached_rate(
            seller_state=seller_state,
            buyer_state=buyer_state,
            buyer_postal_code=buyer_postal_code,
            tax_category=tax_category,
            currency=currency,
            tax_rate=result["tax_rate"],
            source="stripe",
            jurisdiction=result["jurisdiction"],
        )
        return result
    except Exception:
        logger.exception("Stripe tax calculation failed")
        return {
            "ok": False,
            "reason": "tax_provider_error",
            "message_key": "tax_provider_error",
        }
