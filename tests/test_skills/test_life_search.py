"""Tests for life_search skill."""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.life_search.handler import (
    LifeSearchSkill,
    _is_duplicate,
    _normalize_text,
)


@pytest.fixture
def skill():
    return LifeSearchSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    """Create an IncomingMessage with given text."""
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def _make_life_event(
    text: str = "test event",
    event_type: LifeEventType = LifeEventType.note,
    tags: list[str] | None = None,
    data: dict | None = None,
) -> MagicMock:
    """Create a mock LifeEvent for search results."""
    event = MagicMock()
    event.text = text
    event.type = event_type
    event.tags = tags
    event.data = data
    event.date = date.today()
    event.created_at = datetime.now()
    return event


@pytest.mark.asyncio
async def test_empty_query_returns_prompt(skill, ctx):
    """Empty search query returns a prompt."""
    msg = _msg("")

    result = await skill.execute(msg, ctx, {})

    assert "Что искать" in result.response_text


@pytest.mark.asyncio
async def test_empty_query_from_intent_data(skill, ctx):
    """Empty query in intent_data falls through to message text."""
    msg = _msg("")

    result = await skill.execute(msg, ctx, {"search_query": "  "})

    assert "Что искать" in result.response_text


@pytest.mark.asyncio
async def test_sql_and_mem0_results_merged(skill, ctx):
    """SQL and Mem0 results are merged without duplicates."""
    msg = _msg("кофе")
    intent_data = {"search_query": "кофе"}

    sql_events = [
        _make_life_event("кофе утром", LifeEventType.drink),
    ]
    mem0_results = [
        {
            "memory": "пил кофе в кафе",
            "metadata": {"type": "drink", "tags": []},
            "created_at": datetime.now().isoformat(),
        },
        {
            "memory": "кофе утром",  # duplicate of SQL result
            "metadata": {"type": "drink"},
            "created_at": datetime.now().isoformat(),
        },
    ]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=sql_events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=mem0_results,
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="formatted timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    # Header shows count, timeline is formatted
    assert "Результаты" in result.response_text
    assert "(2)" in result.response_text
    assert "formatted timeline" in result.response_text


@pytest.mark.asyncio
async def test_no_results_found(skill, ctx):
    """No results found returns an informative message."""
    msg = _msg("несуществующее")
    intent_data = {"search_query": "несуществующее"}

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert "ничего не найдено" in result.response_text.lower()


@pytest.mark.asyncio
async def test_mem0_failure_does_not_crash(skill, ctx):
    """Mem0 search failure is handled gracefully."""
    msg = _msg("заметка")
    intent_data = {"search_query": "заметка"}

    sql_events = [_make_life_event("заметка про идею")]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=sql_events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Mem0 down"),
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline output",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert "Результаты" in result.response_text
    assert "timeline output" in result.response_text


@pytest.mark.asyncio
async def test_query_from_message_text(skill, ctx):
    """Query is taken from message text when not in intent_data."""
    msg = _msg("найди мои заметки про работу")

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query,
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await skill.execute(msg, ctx, {})

    call_kwargs = mock_query.call_args.kwargs
    assert call_kwargs["search_text"] == msg.text


@pytest.mark.asyncio
async def test_timeline_header_contains_result_count(skill, ctx):
    """Response header includes the result count."""
    msg = _msg("кофе")
    intent_data = {"search_query": "кофе"}
    events = [_make_life_event("кофе утром"), _make_life_event("кофе днём")]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert "Результаты" in result.response_text
    assert "(2)" in result.response_text


@pytest.mark.asyncio
async def test_search_returns_buttons(skill, ctx):
    """Search results include period shortcut buttons."""
    msg = _msg("заметки")
    events = [_make_life_event("test")]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, {"search_query": "заметки"})

    assert result.buttons is not None
    assert len(result.buttons) == 3
    assert "life_search:today" in result.buttons[0]["callback"]


# --- Period and type filter tests ---


@pytest.mark.asyncio
async def test_search_with_period_today(skill, ctx):
    """Period 'today' passes date_from and date_to to query_life_events."""
    msg = _msg("что я ел сегодня")
    intent_data = {
        "search_query": "что я ел сегодня",
        "period": "today",
        "life_event_type": "food",
    }

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query,
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_query.call_args.kwargs
    today = date.today()
    assert call_kwargs["date_from"] == today
    assert call_kwargs["date_to"] == today
    assert call_kwargs["event_type"] == LifeEventType.food
    # When period is active, search_text should be None (no ILIKE)
    assert call_kwargs["search_text"] is None


@pytest.mark.asyncio
async def test_search_with_event_type_filter(skill, ctx):
    """Event type filter is passed to query_life_events."""
    msg = _msg("мои заметки")
    intent_data = {"search_query": "мои заметки", "life_event_type": "note"}

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query,
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_query.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.note
    assert call_kwargs["search_text"] is None


@pytest.mark.asyncio
async def test_search_no_ilike_when_period_set(skill, ctx):
    """When period is set, search_text is None (skip ILIKE)."""
    msg = _msg("кофе за неделю")
    intent_data = {"search_query": "кофе за неделю", "period": "week"}

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query,
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_query.call_args.kwargs
    assert call_kwargs["search_text"] is None
    assert call_kwargs["date_from"] is not None


@pytest.mark.asyncio
async def test_search_header_shows_period(skill, ctx):
    """Header includes period label when period is set."""
    msg = _msg("за сегодня")
    events = [_make_life_event("test")]
    intent_data = {"search_query": "за сегодня", "period": "today"}

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert "сегодня" in result.response_text
    assert "Результаты" in result.response_text


@pytest.mark.asyncio
async def test_mem0_always_called_with_query(skill, ctx):
    """Mem0 semantic search runs even when date/type filters are active."""
    msg = _msg("что я ел за неделю")
    intent_data = {
        "search_query": "что я ел за неделю",
        "period": "week",
        "life_event_type": "food",
    }

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_mem0,
    ):
        await skill.execute(msg, ctx, intent_data)

    # Mem0 should be called even with period/type filters
    mock_mem0.assert_called_once()
    assert mock_mem0.call_args.kwargs["query"] == "что я ел за неделю"


@pytest.mark.asyncio
async def test_mem0_not_called_without_query(skill, ctx):
    """Mem0 is not called when query is empty (period-only search)."""
    msg = _msg("")
    intent_data = {"search_query": "", "period": "today"}

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=[_make_life_event("something")],
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_mem0,
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        await skill.execute(msg, ctx, intent_data)

    mock_mem0.assert_not_called()


# --- Deduplication tests ---


def test_normalize_text():
    """_normalize_text collapses whitespace and lowercases."""
    assert _normalize_text("  Hello   World  ") == "hello world"
    assert _normalize_text("КОФЕ утром") == "кофе утром"
    assert _normalize_text("") == ""


def test_is_duplicate_exact_match():
    """Exact text is detected as duplicate."""
    assert _is_duplicate("кофе утром", "кофе утром") is True


def test_is_duplicate_case_insensitive():
    """Case difference is detected as duplicate."""
    assert _is_duplicate("Кофе Утром", "кофе утром") is True


def test_is_duplicate_containment():
    """Substring containment is detected as duplicate."""
    assert _is_duplicate("кофе утром", "пил кофе утром в кафе") is True


def test_is_duplicate_similar_text():
    """High-similarity text is detected as duplicate."""
    assert _is_duplicate("кофе утром с молоком", "кофе утром с молоком!") is True


def test_is_duplicate_different_text():
    """Different texts are not duplicates."""
    assert _is_duplicate("кофе утром", "обед с коллегами") is False


def test_is_duplicate_empty_text():
    """Empty texts are not considered duplicates."""
    assert _is_duplicate("", "кофе") is False
    assert _is_duplicate("кофе", "") is False
    assert _is_duplicate("", "") is False


@pytest.mark.asyncio
async def test_near_duplicate_mem0_result_filtered(skill, ctx):
    """Mem0 result similar to SQL result is filtered out by similarity dedup."""
    msg = _msg("кофе")
    intent_data = {"search_query": "кофе"}

    sql_events = [_make_life_event("кофе утром с молоком", LifeEventType.drink)]
    mem0_results = [
        {
            # Near-duplicate: same text with minor variation
            "memory": "Кофе утром с молоком!",
            "metadata": {"type": "drink"},
            "created_at": datetime.now().isoformat(),
            "score": 0.92,
        },
        {
            # Genuinely different
            "memory": "обед в ресторане с друзьями",
            "metadata": {"type": "food"},
            "created_at": datetime.now().isoformat(),
            "score": 0.65,
        },
    ]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=sql_events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=mem0_results,
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    # 1 SQL + 1 unique Mem0 (near-duplicate filtered out)
    assert "(2)" in result.response_text


@pytest.mark.asyncio
async def test_mem0_results_with_filters_supplement_sql(skill, ctx):
    """Mem0 results supplement SQL results even when date/type filters active."""
    msg = _msg("что я ел сегодня")
    intent_data = {
        "search_query": "что я ел сегодня",
        "period": "today",
        "life_event_type": "food",
    }

    sql_events = [_make_life_event("завтрак: овсянка", LifeEventType.food)]
    mem0_results = [
        {
            "memory": "любит овсянку по утрам с бананом",
            "metadata": {"type": "food"},
            "created_at": datetime.now().isoformat(),
            "score": 0.85,
        },
    ]

    with (
        patch(
            "src.skills.life_search.handler.query_life_events",
            new_callable=AsyncMock,
            return_value=sql_events,
        ),
        patch(
            "src.skills.life_search.handler.search_memories",
            new_callable=AsyncMock,
            return_value=mem0_results,
        ),
        patch(
            "src.skills.life_search.handler.format_timeline",
            return_value="timeline",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    # Both SQL event and unique Mem0 memory included
    assert "(2)" in result.response_text


@pytest.mark.asyncio
async def test_pseudo_event_preserves_score(skill, ctx):
    """_PseudoLifeEvent preserves the Mem0 score."""
    from src.skills.life_search.handler import _PseudoLifeEvent

    mem = {
        "memory": "test memory",
        "metadata": {"type": "note"},
        "score": 0.87,
        "created_at": datetime.now().isoformat(),
    }
    pseudo = _PseudoLifeEvent(mem)
    assert pseudo.score == 0.87
    assert pseudo.text == "test memory"
    assert pseudo.type == LifeEventType.note
