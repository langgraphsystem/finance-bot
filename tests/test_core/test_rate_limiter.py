"""Tests for tiered rate limiting."""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.rate_limiter import (
    INTENT_TIER_MAP,
    RATE_LIMITS,
    check_rate_limit,
    get_limit_message,
)


@pytest.fixture
def mock_redis():
    with patch("src.core.rate_limiter.redis") as m:
        m.incr = AsyncMock(return_value=1)
        m.expire = AsyncMock()
        yield m


async def test_default_tier_allowed(mock_redis):
    allowed, tier = await check_rate_limit("user1", "add_expense")
    assert allowed is True
    assert tier == "default"


async def test_browser_tier_mapping():
    assert INTENT_TIER_MAP["browser_action"] == "browser"
    assert INTENT_TIER_MAP["web_action"] == "browser"


async def test_heavy_tier_mapping():
    assert INTENT_TIER_MAP["complex_query"] == "llm_heavy"
    assert INTENT_TIER_MAP["financial_summary"] == "llm_heavy"


async def test_image_tier_mapping():
    assert INTENT_TIER_MAP["generate_image"] == "image_gen"
    assert INTENT_TIER_MAP["generate_card"] == "image_gen"


async def test_rate_limit_exceeded(mock_redis):
    mock_redis.incr = AsyncMock(return_value=31)
    allowed, tier = await check_rate_limit("user1", "add_expense")
    assert allowed is False
    assert tier == "default"


async def test_browser_limit_exceeded(mock_redis):
    mock_redis.incr = AsyncMock(return_value=4)
    allowed, tier = await check_rate_limit("user1", "browser_action")
    assert allowed is False
    assert tier == "browser"


async def test_first_call_sets_expire(mock_redis):
    mock_redis.incr = AsyncMock(return_value=1)
    await check_rate_limit("user1", "add_expense")
    mock_redis.expire.assert_called_once()


async def test_subsequent_call_no_expire(mock_redis):
    mock_redis.incr = AsyncMock(return_value=5)
    await check_rate_limit("user1", "add_expense")
    mock_redis.expire.assert_not_called()


async def test_redis_failure_allows_request():
    with patch("src.core.rate_limiter.redis") as m:
        m.incr = AsyncMock(side_effect=ConnectionError("Redis down"))
        allowed, tier = await check_rate_limit("user1", "add_expense")
        assert allowed is True


def test_limit_messages():
    msg_en = get_limit_message("default", "en")
    assert "requests" in msg_en.lower()

    msg_ru = get_limit_message("default", "ru")
    assert "запрос" in msg_ru.lower()

    msg_es = get_limit_message("default", "es")
    assert "solicitudes" in msg_es.lower()


def test_all_tiers_have_config():
    for tier in set(INTENT_TIER_MAP.values()):
        assert tier in RATE_LIMITS, f"Tier {tier} missing from RATE_LIMITS"
