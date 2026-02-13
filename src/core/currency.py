"""Multi-currency support via Frankfurter API + Redis cache."""

import logging
from decimal import Decimal

import httpx

from src.core.db import redis

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CACHE_TTL = 3600  # 1 hour


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """Get exchange rate with Redis caching."""
    if from_currency == to_currency:
        return Decimal("1.0")

    cache_key = f"fx:{from_currency}:{to_currency}"
    cached = await redis.get(cache_key)
    if cached:
        return Decimal(cached)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            FRANKFURTER_URL,
            params={"from": from_currency, "to": to_currency},
        )
        response.raise_for_status()
        data = response.json()
        rate = Decimal(str(data["rates"][to_currency]))

    await redis.set(cache_key, str(rate), ex=CACHE_TTL)
    return rate


async def convert_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
) -> tuple[Decimal, Decimal]:
    """Convert amount, return (converted_amount, exchange_rate)."""
    rate = await get_exchange_rate(from_currency, to_currency)
    converted = (amount * rate).quantize(Decimal("0.01"))
    return converted, rate
