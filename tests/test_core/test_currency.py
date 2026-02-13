"""Tests for currency conversion."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal


@pytest.mark.asyncio
async def test_get_exchange_rate_same_currency():
    """Same currency should return rate of 1.0 without any API call."""
    from src.core.currency import get_exchange_rate

    with patch("src.core.currency.redis") as mock_redis:
        rate = await get_exchange_rate("USD", "USD")
        assert rate == Decimal("1.0")
        mock_redis.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_exchange_rate_from_cache():
    """Cached rate should be returned without HTTP call."""
    with patch("src.core.currency.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value="0.85")

        from src.core.currency import get_exchange_rate

        rate = await get_exchange_rate("USD", "EUR")
        assert rate == Decimal("0.85")


@pytest.mark.asyncio
async def test_get_exchange_rate_from_api():
    """When cache misses, should fetch from Frankfurter API and cache result."""
    with patch("src.core.currency.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"rates": {"EUR": 0.85}}

        with patch("src.core.currency.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from src.core.currency import get_exchange_rate

            rate = await get_exchange_rate("USD", "EUR")
            assert rate == Decimal("0.85")
            mock_redis.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_convert_amount_returns_tuple():
    """convert_amount should return (converted_amount, rate) tuple."""
    with patch("src.core.currency.get_exchange_rate", new_callable=AsyncMock) as mock_rate:
        mock_rate.return_value = Decimal("0.85")

        from src.core.currency import convert_amount

        result = await convert_amount(Decimal("100"), "USD", "EUR")
        assert isinstance(result, tuple)
        assert len(result) == 2
        converted, rate = result
        assert converted == Decimal("85.00")
        assert rate == Decimal("0.85")


@pytest.mark.asyncio
async def test_convert_amount_same_currency():
    """Same currency conversion should return original amount with rate 1.0."""
    with patch("src.core.currency.get_exchange_rate", new_callable=AsyncMock) as mock_rate:
        mock_rate.return_value = Decimal("1.0")

        from src.core.currency import convert_amount

        converted, rate = await convert_amount(Decimal("100"), "USD", "USD")
        assert converted == Decimal("100.00")
        assert rate == Decimal("1.0")


@pytest.mark.asyncio
async def test_convert_amount_quantizes_to_cents():
    """Result should be quantized to 2 decimal places."""
    with patch("src.core.currency.get_exchange_rate", new_callable=AsyncMock) as mock_rate:
        mock_rate.return_value = Decimal("0.333333")

        from src.core.currency import convert_amount

        converted, rate = await convert_amount(Decimal("100"), "USD", "XXX")
        assert converted == Decimal("33.33")
