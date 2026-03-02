from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.billing.sales_tax import resolve_sales_tax_for_invoice


def _invoice_payload(**overrides):
    payload = {
        "subtotal": 100.0,
        "total": 100.0,
        "requires_sales_tax": True,
        "seller_state": "NY",
        "buyer_state": "CA",
        "buyer_postal_code": "94105",
        "buyer_city": "San Francisco",
        "buyer_address_line1": "1 Market St",
        "buyer_country": "US",
        "currency": "USD",
        "invoice_tax_category_code": "txcd_10000000",
        "items": [{"amount": 100.0, "description": "Service"}],
        "invoice_date": "2026-03-02",
    }
    payload.update(overrides)
    return payload


async def test_not_required_returns_zero_tax():
    result = await resolve_sales_tax_for_invoice(_invoice_payload(requires_sales_tax=False))
    assert result["ok"] is True
    assert result["tax_amount"] == 0.0
    assert result["total"] == 100.0


async def test_missing_address_fails_fast():
    result = await resolve_sales_tax_for_invoice(
        _invoice_payload(buyer_state="", buyer_postal_code="")
    )
    assert result["ok"] is False
    assert result["message_key"] == "tax_missing_address"


async def test_cache_hit_skips_stripe_call():
    cached = SimpleNamespace(tax_rate=0.0825, source="stripe", jurisdiction="CA")
    with (
        patch(
            "src.billing.sales_tax._get_cached_rate",
            new_callable=AsyncMock,
            return_value=cached,
        ),
    ):
        result = await resolve_sales_tax_for_invoice(_invoice_payload())
    assert result["ok"] is True
    assert result["cached"] is True
    assert result["tax_amount"] == 8.25
    assert result["total"] == 108.25


async def test_missing_tax_category_fails_fast():
    result = await resolve_sales_tax_for_invoice(
        _invoice_payload(
            invoice_tax_category_code="",
            items=[{"amount": 100.0, "description": "X"}],
        )
    )
    assert result["ok"] is False
    assert result["message_key"] == "tax_missing_category"


async def test_stripe_not_configured_returns_error():
    stripe_stub = SimpleNamespace(is_configured=False)
    with (
        patch("src.billing.sales_tax._get_cached_rate", new_callable=AsyncMock, return_value=None),
        patch("src.billing.sales_tax.StripeClient", return_value=stripe_stub),
    ):
        result = await resolve_sales_tax_for_invoice(_invoice_payload())
    assert result["ok"] is False
    assert result["message_key"] == "tax_provider_unavailable"


async def test_stripe_fallback_saves_cache():
    stripe_stub = SimpleNamespace(
        is_configured=True,
        create_tax_calculation=AsyncMock(
            return_value={
                "tax_amount_exclusive": 750,
                "tax_breakdown": [{"jurisdiction": {"display_name": "San Francisco"}}],
            }
        ),
    )
    with (
        patch("src.billing.sales_tax._get_cached_rate", new_callable=AsyncMock, return_value=None),
        patch("src.billing.sales_tax._store_cached_rate", new_callable=AsyncMock) as mock_store,
        patch("src.billing.sales_tax.StripeClient", return_value=stripe_stub),
    ):
        result = await resolve_sales_tax_for_invoice(_invoice_payload())
    assert result["ok"] is True
    assert result["cached"] is False
    assert result["tax_amount"] == 7.5
    assert result["total"] == 107.5
    mock_store.assert_awaited_once()
