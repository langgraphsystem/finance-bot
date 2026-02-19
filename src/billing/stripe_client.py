"""Stripe API wrapper — checkout, subscription, portal, webhook handling."""

import logging
from typing import Any

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"
PLAN_PRICE_CENTS = 4900  # $49/month
TRIAL_DAYS = 7


class StripeClient:
    """Thin async wrapper around the Stripe REST API (no SDK dependency)."""

    def __init__(self, secret_key: str = "") -> None:
        self._key = secret_key or settings.stripe_secret_key
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=STRIPE_API_BASE,
                auth=(self._key, ""),
                timeout=15.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    async def create_customer(self, email: str = "", name: str = "") -> dict[str, Any]:
        client = await self._get_client()
        data: dict[str, str] = {}
        if email:
            data["email"] = email
        if name:
            data["name"] = name
        resp = await client.post("/customers", data=data)
        return resp.json()

    # ------------------------------------------------------------------
    # Checkout sessions
    # ------------------------------------------------------------------
    async def create_checkout_session(
        self,
        customer_id: str,
        success_url: str,
        cancel_url: str,
        price_id: str = "",
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session for subscription."""
        client = await self._get_client()
        data: dict[str, Any] = {
            "customer": customer_id,
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if price_id:
            data["line_items[0][price]"] = price_id
            data["line_items[0][quantity]"] = "1"
        else:
            data["line_items[0][price_data][currency]"] = "usd"
            data["line_items[0][price_data][unit_amount]"] = str(PLAN_PRICE_CENTS)
            data["line_items[0][price_data][recurring][interval]"] = "month"
            data["line_items[0][price_data][product_data][name]"] = "AI Life Assistant"
            data["line_items[0][quantity]"] = "1"

        resp = await client.post("/checkout/sessions", data=data)
        return resp.json()

    # ------------------------------------------------------------------
    # Customer portal
    # ------------------------------------------------------------------
    async def create_portal_session(
        self, customer_id: str, return_url: str
    ) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post(
            "/billing_portal/sessions",
            data={"customer": customer_id, "return_url": return_url},
        )
        return resp.json()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------
    async def cancel_subscription(self, subscription_id: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.delete(f"/subscriptions/{subscription_id}")
        return resp.json()

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------
    @staticmethod
    def verify_webhook_signature(
        payload: bytes, sig_header: str, webhook_secret: str
    ) -> bool:
        """Verify Stripe webhook signature (v1)."""
        import hashlib
        import hmac
        import time

        parts = dict(item.split("=", 1) for item in sig_header.split(",") if "=" in item)
        timestamp = parts.get("t", "")
        expected_sig = parts.get("v1", "")

        if not timestamp or not expected_sig:
            return False

        # Reject old timestamps (> 5 minutes)
        if abs(time.time() - int(timestamp)) > 300:
            return False

        signed_payload = f"{timestamp}.{payload.decode()}"
        computed = hmac.new(
            webhook_secret.encode(), signed_payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, expected_sig)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Module-level singleton
stripe_client = StripeClient()
