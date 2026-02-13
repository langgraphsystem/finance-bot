"""Tests for financial pattern detection (src.core.patterns)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAMILY_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tx_row(dt: date, category: str, merchant: str | None, description: str, amount: float):
    """Build a mock row matching the SELECT projection in detect_patterns."""
    row = MagicMock()
    row.date = dt
    row.category = category
    row.merchant = merchant
    row.description = description
    row.amount = Decimal(str(amount))
    return row


def _rows_result(rows):
    mock = MagicMock()
    mock.all.return_value = rows
    return mock


def _build_session_ctx(execute_return):
    """Return (async-context-manager mock, session_mock)."""
    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(return_value=execute_return)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# detect_patterns — not enough data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_insufficient_data():
    """Returns None when fewer than 5 transactions exist."""
    today = date.today()
    rows = [
        _make_tx_row(today, "Food", "Walmart", "groceries", 25.00),
        _make_tx_row(today, "Food", "Target", "snacks", 12.50),
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    with patch("src.core.patterns.async_session", return_value=ctx):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    assert result is None


# ---------------------------------------------------------------------------
# detect_patterns — successful LLM response
# ---------------------------------------------------------------------------

VALID_LLM_JSON = """{
  "patterns": ["Еженедельные покупки продуктов ~$150"],
  "anomalies": ["Необычная трата $500 в категории Развлечения"],
  "recommendations": ["Рассмотреть снижение расходов на рестораны"]
}"""


@pytest.mark.asyncio
async def test_detect_patterns_success():
    """Successful pattern detection with valid JSON from LLM."""
    today = date.today()
    rows = [
        _make_tx_row(today - timedelta(days=i), "Food", f"Store{i}", "desc", 20.0 + i)
        for i in range(10)
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    # Mock Gemini response
    response_mock = MagicMock()
    response_mock.text = VALID_LLM_JSON

    client_mock = MagicMock()
    client_mock.aio.models.generate_content = AsyncMock(return_value=response_mock)

    with (
        patch("src.core.patterns.async_session", return_value=ctx),
        patch("src.core.patterns.google_client", return_value=client_mock),
    ):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    assert result is not None
    assert len(result["patterns"]) == 1
    assert len(result["anomalies"]) == 1
    assert len(result["recommendations"]) == 1
    assert "продуктов" in result["patterns"][0]


# ---------------------------------------------------------------------------
# detect_patterns — JSON wrapped in markdown fences
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_markdown_fences():
    """LLM response with markdown code fences around JSON is parsed correctly."""
    today = date.today()
    rows = [
        _make_tx_row(today - timedelta(days=i), "Transport", "Uber", "ride", 15.0)
        for i in range(7)
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    fenced_json = '```json\n{"patterns": ["p1"], "anomalies": [], "recommendations": ["r1"]}\n```'
    response_mock = MagicMock()
    response_mock.text = fenced_json

    client_mock = MagicMock()
    client_mock.aio.models.generate_content = AsyncMock(return_value=response_mock)

    with (
        patch("src.core.patterns.async_session", return_value=ctx),
        patch("src.core.patterns.google_client", return_value=client_mock),
    ):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    assert result is not None
    assert result["patterns"] == ["p1"]
    assert result["anomalies"] == []
    assert result["recommendations"] == ["r1"]


# ---------------------------------------------------------------------------
# detect_patterns — LLM returns no JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_no_json_in_response():
    """Returns None when LLM response contains no parseable JSON."""
    today = date.today()
    rows = [
        _make_tx_row(today - timedelta(days=i), "Food", "Shop", "food", 10.0)
        for i in range(6)
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    response_mock = MagicMock()
    response_mock.text = "Извините, я не могу проанализировать данные."

    client_mock = MagicMock()
    client_mock.aio.models.generate_content = AsyncMock(return_value=response_mock)

    with (
        patch("src.core.patterns.async_session", return_value=ctx),
        patch("src.core.patterns.google_client", return_value=client_mock),
    ):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    assert result is None


# ---------------------------------------------------------------------------
# detect_patterns — LLM call raises exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_llm_exception():
    """Returns None when the LLM call raises an exception."""
    today = date.today()
    rows = [
        _make_tx_row(today - timedelta(days=i), "Food", "Shop", "food", 10.0)
        for i in range(6)
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    client_mock = MagicMock()
    client_mock.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("API down"))

    with (
        patch("src.core.patterns.async_session", return_value=ctx),
        patch("src.core.patterns.google_client", return_value=client_mock),
    ):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    assert result is None


# ---------------------------------------------------------------------------
# detect_patterns — merchant fallback to description
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_patterns_merchant_fallback():
    """When merchant is None, description is used in the prompt text."""
    today = date.today()
    rows = [
        _make_tx_row(today - timedelta(days=i), "Food", None, f"описание-{i}", 10.0)
        for i in range(6)
    ]
    ctx = _build_session_ctx(_rows_result(rows))

    response_mock = MagicMock()
    response_mock.text = '{"patterns": ["test"], "anomalies": [], "recommendations": []}'

    client_mock = MagicMock()
    client_mock.aio.models.generate_content = AsyncMock(return_value=response_mock)

    with (
        patch("src.core.patterns.async_session", return_value=ctx),
        patch("src.core.patterns.google_client", return_value=client_mock),
    ):
        from src.core.patterns import detect_patterns

        result = await detect_patterns(FAMILY_ID)

    # Verify the prompt was built with description (not None)
    call_args = client_mock.aio.models.generate_content.call_args
    prompt_sent = call_args.kwargs.get("contents") or call_args[1].get("contents")
    assert "описание-0" in prompt_sent
    assert result == {"patterns": ["test"], "anomalies": [], "recommendations": []}


# ---------------------------------------------------------------------------
# store_patterns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_patterns_calls_add_memory():
    """store_patterns persists patterns via Mem0 add_memory."""
    patterns = {
        "patterns": ["p1", "p2"],
        "anomalies": ["a1"],
        "recommendations": ["r1"],
    }

    with patch(
        "src.core.memory.mem0_client.add_memory", new_callable=AsyncMock
    ) as mock_add:
        from src.core.patterns import store_patterns

        await store_patterns(FAMILY_ID, patterns)

    mock_add.assert_called_once()
    call_kwargs = mock_add.call_args
    content = call_kwargs[1]["content"] if "content" in call_kwargs[1] else call_kwargs[0][0]
    assert "Паттерн: p1" in content
    assert "Паттерн: p2" in content
    assert "Аномалия: a1" in content
    assert "Рекомендация: r1" in content
    user_id = call_kwargs[1].get("user_id") or call_kwargs[0][1]
    assert user_id == f"family:{FAMILY_ID}"


@pytest.mark.asyncio
async def test_store_patterns_empty():
    """store_patterns does not call add_memory when all lists are empty."""
    patterns = {"patterns": [], "anomalies": [], "recommendations": []}

    with patch(
        "src.core.memory.mem0_client.add_memory", new_callable=AsyncMock
    ) as mock_add:
        from src.core.patterns import store_patterns

        await store_patterns(FAMILY_ID, patterns)

    mock_add.assert_not_called()
