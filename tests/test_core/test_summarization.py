"""Tests for Layer 5 — Incremental dialog summarization."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models.enums import MessageRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(role: MessageRole, content: str) -> MagicMock:
    """Create a mock ConversationMessage."""
    msg = MagicMock()
    msg.role = role
    msg.content = content
    msg.created_at = datetime.now(UTC)
    return msg


def _make_summary(summary_text: str, message_count: int) -> MagicMock:
    """Create a mock SessionSummary."""
    s = MagicMock()
    s.summary = summary_text
    s.message_count = message_count
    s.token_count = len(summary_text.split())
    s.updated_at = datetime.now(UTC)
    return s


# ---------------------------------------------------------------------------
# Tests for summarize_dialog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_below_threshold_returns_none():
    """When message_count < 15, summarize_dialog should return None."""
    user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Mock the DB session
    mock_session = AsyncMock()

    # count query returns 10 (below threshold of 15)
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 10
    mock_session.execute = AsyncMock(return_value=mock_count_result)
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx):
        from src.core.memory.summarization import summarize_dialog

        result = await summarize_dialog(user_id, family_id)

    assert result is None


@pytest.mark.asyncio
async def test_summarize_creates_new_summary():
    """When no existing summary and msg_count > 15, create a new summary."""
    user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    messages = [
        _make_message(MessageRole.user, "Потратил 5000 на продукты"),
        _make_message(MessageRole.assistant, "Записал расход 5000 RUB в категорию Продукты."),
    ]

    mock_session = AsyncMock()
    call_count = 0

    async def _mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # count query
            result.scalar.return_value = 20
        elif call_count == 2:
            # existing summary query
            result.scalar_one_or_none.return_value = None
        elif call_count == 3:
            # messages query
            result.scalars.return_value.all.return_value = messages
        return result

    mock_session.execute = AsyncMock(side_effect=_mock_execute)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    # Mock Gemini response
    mock_response = MagicMock()
    mock_response.text = "## Финансовые данные\n- Расход 5000 RUB на продукты"

    mock_google = MagicMock()
    mock_google.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx),
        patch("src.core.memory.summarization.google_client", return_value=mock_google),
    ):
        from src.core.memory.summarization import summarize_dialog

        result = await summarize_dialog(user_id, family_id)

    assert result == "## Финансовые данные\n- Расход 5000 RUB на продукты"
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_updates_existing_summary():
    """When an existing summary exists, it should be updated in place."""
    user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    existing = _make_summary("## Финансовые данные\n- Расход 3000 RUB", message_count=16)
    new_messages = [
        _make_message(MessageRole.user, "Ещё потратил 2000 на кафе"),
        _make_message(MessageRole.assistant, "Записал 2000 RUB в категорию Кафе."),
    ]

    mock_session = AsyncMock()
    call_count = 0

    async def _mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # count query
            result.scalar.return_value = 20
        elif call_count == 2:
            # existing summary query
            result.scalar_one_or_none.return_value = existing
        elif call_count == 3:
            # messages query
            result.scalars.return_value.all.return_value = new_messages
        return result

    mock_session.execute = AsyncMock(side_effect=_mock_execute)
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_response = MagicMock()
    mock_response.text = "## Финансовые данные\n- Расход 3000 RUB\n- Расход 2000 RUB на кафе"

    mock_google = MagicMock()
    mock_google.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx),
        patch("src.core.memory.summarization.google_client", return_value=mock_google),
    ):
        from src.core.memory.summarization import summarize_dialog

        result = await summarize_dialog(user_id, family_id)

    assert result is not None
    assert "2000 RUB" in result
    # Existing summary object should have been mutated (updated in place)
    assert existing.summary == result
    assert existing.message_count == 20
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_no_new_messages_returns_existing():
    """When msg_count equals last_count, return existing summary text."""
    user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    existing = _make_summary("Existing summary", message_count=20)

    mock_session = AsyncMock()
    call_count = 0

    async def _mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # count query — same as existing.message_count
            result.scalar.return_value = 20
        elif call_count == 2:
            # existing summary query
            result.scalar_one_or_none.return_value = existing
        return result

    mock_session.execute = AsyncMock(side_effect=_mock_execute)
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx):
        from src.core.memory.summarization import summarize_dialog

        result = await summarize_dialog(user_id, family_id)

    assert result == "Existing summary"
    # Gemini should not have been called
    mock_session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests for get_session_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_summary_returns_existing():
    """get_session_summary should return the most recent summary."""
    user_id = str(uuid.uuid4())
    existing = _make_summary("Test summary", message_count=20)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx):
        from src.core.memory.summarization import get_session_summary

        result = await get_session_summary(user_id)

    assert result is not None
    assert result.summary == "Test summary"


@pytest.mark.asyncio
async def test_get_session_summary_returns_none_when_empty():
    """get_session_summary should return None when no summaries exist."""
    user_id = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx):
        from src.core.memory.summarization import get_session_summary

        result = await get_session_summary(user_id)

    assert result is None


@pytest.mark.asyncio
async def test_get_session_summary_handles_db_error():
    """get_session_summary should return None on database errors."""
    user_id = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("DB connection lost"))

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx):
        from src.core.memory.summarization import get_session_summary

        result = await get_session_summary(user_id)

    assert result is None


@pytest.mark.asyncio
async def test_summarize_handles_gemini_error():
    """summarize_dialog should return None if Gemini call fails."""
    user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    messages = [_make_message(MessageRole.user, "Test message")]

    mock_session = AsyncMock()
    call_count = 0

    async def _mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar.return_value = 20
        elif call_count == 2:
            result.scalar_one_or_none.return_value = None
        elif call_count == 3:
            result.scalars.return_value.all.return_value = messages
        return result

    mock_session.execute = AsyncMock(side_effect=_mock_execute)
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_google = MagicMock()
    mock_google.aio.models.generate_content = AsyncMock(side_effect=Exception("Gemini API error"))

    with (
        patch("src.core.memory.summarization.async_session", return_value=mock_session_ctx),
        patch("src.core.memory.summarization.google_client", return_value=mock_google),
    ):
        from src.core.memory.summarization import summarize_dialog

        result = await summarize_dialog(user_id, family_id)

    assert result is None
