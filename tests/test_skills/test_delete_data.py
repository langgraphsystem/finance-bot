"""Tests for delete_data skill."""

import json
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.search_utils import split_search_words
from src.gateway.types import IncomingMessage, MessageType
from src.skills.delete_data.handler import (
    DeleteDataSkill,
    FoundRecord,
    _format_found_records_preview,
    _parse_ai_search_result,
    _parse_life_event_ref,
    _resolve_date_range,
)

MODULE = "src.skills.delete_data.handler"


@pytest.fixture
def skill():
    return DeleteDataSkill()


@pytest.fixture
def msg():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="удали мои расходы за январь",
    )


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


# ---- _resolve_date_range tests ----


def test_resolve_date_range_today():
    start, end = _resolve_date_range("today", None, None)
    assert start == date.today()
    assert end == date.today()


def test_resolve_date_range_yesterday():
    start, end = _resolve_date_range("yesterday", None, None)
    assert start == date.today() - timedelta(days=1)
    assert end == start


def test_resolve_date_range_week():
    start, end = _resolve_date_range("week", None, None)
    assert start == date.today() - timedelta(days=7)
    assert end == date.today()


def test_resolve_date_range_month():
    start, end = _resolve_date_range("month", None, None)
    assert start == date.today().replace(day=1)
    assert end == date.today()


def test_resolve_date_range_year():
    start, end = _resolve_date_range("year", None, None)
    assert start == date.today().replace(month=1, day=1)
    assert end == date.today()


def test_resolve_date_range_custom():
    start, end = _resolve_date_range("custom", "2026-01-01", "2026-01-31")
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_resolve_date_range_date_from_only():
    start, end = _resolve_date_range(None, "2026-01-01", None)
    assert start == date(2026, 1, 1)
    assert end == date.today()


def test_resolve_date_range_none():
    start, end = _resolve_date_range(None, None, None)
    assert start is None
    assert end is None


# ---- Skill.execute tests ----


async def test_unknown_scope_triggers_ai_fallback(skill, msg, ctx):
    """Unrecognized scope falls through to AI search."""
    with patch(
        f"{MODULE}._parse_life_event_ref", return_value=None
    ), patch.object(
        skill,
        "_ai_search_and_delete",
        new_callable=AsyncMock,
        return_value=MagicMock(response_text="AI result"),
    ) as mock_ai:
        result = await skill.execute(msg, ctx, {"delete_scope": "invalid_scope"})
    mock_ai.assert_awaited_once()
    assert result.response_text == "AI result"


async def test_empty_scope_triggers_ai_fallback(skill, msg, ctx):
    """Empty scope falls through to AI search."""
    with patch(
        f"{MODULE}._parse_life_event_ref", return_value=None
    ), patch.object(
        skill,
        "_ai_search_and_delete",
        new_callable=AsyncMock,
        return_value=MagicMock(response_text="AI result"),
    ) as mock_ai:
        await skill.execute(msg, ctx, {})
    mock_ai.assert_awaited_once()


async def test_zero_records_returns_nothing(skill, msg, ctx):
    """When AI search finds no matching records, user sees 'not found' message."""
    llm_json = json.dumps({
        "tables": ["transactions"],
        "search_text": "расходы",
        "transaction_type": "expense",
        "confidence": 0.9,
        "explanation_ru": "расходы за сегодня",
    })
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await skill.execute(msg, ctx, {"delete_scope": "expenses", "period": "today"})

    assert "ничего не найдено" in result.response_text
    assert result.buttons is None


async def test_returns_confirmation_with_buttons(skill, msg, ctx):
    """When AI search finds records, user sees preview with confirm/cancel buttons."""
    llm_json = json.dumps({
        "tables": ["transactions"],
        "search_text": "",
        "transaction_type": "expense",
        "confidence": 0.9,
        "explanation_ru": "расходы за январь",
    })
    found = [
        FoundRecord(
            table="transactions",
            record_id=str(uuid.uuid4()),
            preview_text=f"📉 Expense #{i}",
            created_at=None,
        )
        for i in range(5)
    ]
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=found,
        ),
        patch(f"{MODULE}.store_pending_action", new_callable=AsyncMock, return_value="abc123"),
    ):
        result = await skill.execute(
            msg, ctx, {"delete_scope": "expenses", "period": "month"}
        )

    assert "5" in result.response_text
    assert "необратимо" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action:abc123" in result.buttons[0]["callback"]
    assert "cancel_action:abc123" in result.buttons[1]["callback"]


async def test_all_deletes_go_through_ai_search(skill, msg, ctx):
    """All delete requests (including scope aliases) route through AI search."""
    with patch.object(
        skill,
        "_ai_search_and_delete",
        new_callable=AsyncMock,
        return_value=MagicMock(response_text="AI found 3 records", buttons=[]),
    ) as mock_ai:
        result = await skill.execute(
            msg, ctx, {"delete_scope": "расходы", "period": "week"}
        )

    mock_ai.assert_awaited_once_with(msg.text, ctx)
    assert "AI found 3 records" in result.response_text


async def test_specific_drink_entry_goes_through_ai_search(skill, ctx):
    """A specific drink delete request goes through AI search like everything else."""
    message = IncomingMessage(
        id="msg-2",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="удалить Напиток вода (250ml)",
    )
    llm_json = json.dumps({
        "tables": ["life_events"],
        "search_text": "вода",
        "life_event_type": "drink",
        "confidence": 0.95,
        "explanation_ru": "напиток вода 250ml",
    })
    found = [
        FoundRecord(
            table="life_events",
            record_id=str(uuid.uuid4()),
            preview_text="☕ вода x1 (250ml)\nДата: 2026-02-20 16:14",
            created_at=datetime(2026, 2, 20, 16, 14),
        ),
    ]
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=found,
        ),
        patch(
            f"{MODULE}.store_pending_action",
            new_callable=AsyncMock,
            return_value="single123",
        ),
    ):
        result = await skill.execute(message, ctx, {"delete_scope": "drinks"})

    assert "Найдено: 1" in result.response_text
    assert "250ml" in result.response_text
    assert result.buttons is not None
    assert result.buttons[0]["callback"] == "confirm_action:single123"
    assert result.buttons[1]["callback"] == "cancel_action:single123"


# ---- execute_delete tests ----


async def test_execute_delete_commits_and_logs():
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 7

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "expenses",
        "period": "month",
        "date_from": None,
        "date_to": None,
        "count": 7,
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    assert "7" in result
    assert "расходы" in result


async def test_execute_delete_all_scope():
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 2

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "all",
        "period": None,
        "date_from": None,
        "date_to": None,
        "count": 10,
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    # "all" scope deletes across 5 sub-scopes, each returning 2 = 10 total
    assert "10" in result
    assert "все данные" in result


async def test_execute_delete_single_life_event():
    """execute_delete should handle single life event deletion path."""
    from src.skills.delete_data.handler import execute_delete

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "drinks",
        "single_life_event_id": str(uuid.uuid4()),
        "single_life_event_preview": "Напиток: вода (250ml)\nДата: 2026-02-20 16:14",
    }

    with (
        patch(f"{MODULE}.async_session", return_value=mock_ctx),
        patch(
            f"{MODULE}._delete_single_life_event",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_single_delete,
    ):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    assert "Удалена 1 запись" in result
    assert "250ml" in result
    mock_single_delete.assert_awaited_once()


def test_skill_attributes():
    s = DeleteDataSkill()
    assert s.name == "delete_data"
    assert s.intents == ["delete_data"]
    assert s.model == "claude-sonnet-4-6"
    assert hasattr(s, "execute")
    assert hasattr(s, "get_system_prompt")


# ---- _parse_ai_search_result tests ----


def test_parse_ai_search_result_valid_json():
    raw = json.dumps({
        "tables": ["life_events"],
        "search_text": "кнопка",
        "confidence": 0.9,
        "explanation_ru": "заметка про кнопку",
    })
    result = _parse_ai_search_result(raw)
    assert result is not None
    assert result["tables"] == ["life_events"]
    assert result["search_text"] == "кнопка"
    assert result["confidence"] == 0.9


def test_parse_ai_search_result_markdown_wrapped():
    raw = '```json\n{"tables": ["tasks"], "search_text": "молоко", "confidence": 0.8}\n```'
    result = _parse_ai_search_result(raw)
    assert result is not None
    assert result["tables"] == ["tasks"]


def test_parse_ai_search_result_invalid():
    assert _parse_ai_search_result("not json at all") is None
    assert _parse_ai_search_result("{}") is None  # no "tables" key
    assert _parse_ai_search_result("") is None


def test_parse_ai_search_result_no_tables_key():
    raw = json.dumps({"search_text": "test", "confidence": 0.5})
    assert _parse_ai_search_result(raw) is None


# ---- split_search_words tests ----


def testsplit_search_words_basic():
    """Splits text into meaningful words, dropping stop words."""
    assert split_search_words("сухур и ифтар") == ["сухур", "ифтар"]


def testsplit_search_words_drops_short():
    assert split_search_words("a и b") == []


def testsplit_search_words_mixed_lang():
    assert split_search_words("delete notes for January") == ["delete", "notes", "january"]


def testsplit_search_words_empty():
    assert split_search_words("") == []


def testsplit_search_words_single_keyword():
    assert split_search_words("молоко") == ["молоко"]


# ---- _parse_life_event_ref tests ----


def test_parse_life_event_ref_full():
    text = "удалить 17.02.2026 19:46 📝 нужно исправить кнопку"
    ref = _parse_life_event_ref(text)
    assert ref is not None
    assert ref["date"] == date(2026, 2, 17)
    assert ref["time"] == (19, 46)
    assert ref["text"] == "нужно исправить кнопку"


def test_parse_life_event_ref_emoji_only():
    text = "📝 заметка без даты"
    ref = _parse_life_event_ref(text)
    assert ref is not None
    assert ref["date"] is None
    assert ref["time"] is None
    assert ref["text"] == "заметка без даты"


def test_parse_life_event_ref_no_match():
    assert _parse_life_event_ref("удали расходы за январь") is None


# ---- _format_found_records_preview tests ----


def test_format_found_records_preview_basic():
    records = [
        FoundRecord(
            table="life_events",
            record_id="id1",
            preview_text="📝 заметка",
            created_at=datetime(2026, 2, 20, 10, 0),
        ),
    ]
    text = _format_found_records_preview(records, "заметка про кнопку")
    assert "Найдено: 1" in text
    assert "заметка про кнопку" in text
    assert "заметка" in text
    assert "необратимо" in text


def test_format_found_records_preview_truncates_at_10():
    records = [
        FoundRecord(
            table="tasks",
            record_id=f"id{i}",
            preview_text=f"⬜ задача {i}",
            created_at=None,
        )
        for i in range(15)
    ]
    text = _format_found_records_preview(records, "задачи")
    assert "Найдено: 15" in text
    assert "ещё 5" in text


# ---- _ai_search_and_delete tests ----


async def test_ai_search_llm_failure_returns_disambiguation(skill, ctx):
    """If LLM call fails, fall back to disambiguation prompt."""
    with patch(
        f"{MODULE}.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    ):
        result = await skill._ai_search_and_delete("удали что-то", ctx)
    assert "Укажите" in result.response_text


async def test_ai_search_low_confidence_returns_disambiguation(skill, ctx):
    """If LLM returns low confidence, fall back to disambiguation."""
    llm_json = json.dumps({
        "tables": ["life_events"],
        "search_text": "",
        "confidence": 0.1,
        "explanation_ru": "не уверен",
    })
    with patch(
        f"{MODULE}.generate_text",
        new_callable=AsyncMock,
        return_value=llm_json,
    ):
        result = await skill._ai_search_and_delete("удали", ctx)
    assert "Укажите" in result.response_text


async def test_ai_search_no_results_returns_not_found(skill, ctx):
    """If AI search finds nothing, show 'not found' message."""
    llm_json = json.dumps({
        "tables": ["life_events"],
        "search_text": "единорог",
        "confidence": 0.9,
        "explanation_ru": "заметки про единорогов",
    })
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await skill._ai_search_and_delete("удали заметки про единорогов", ctx)
    assert "ничего не найдено" in result.response_text
    assert "единорогов" in result.response_text


async def test_ai_search_too_many_results(skill, ctx):
    """If >50 records found, ask user to narrow down."""
    llm_json = json.dumps({
        "tables": ["transactions"],
        "search_text": "",
        "confidence": 0.8,
        "explanation_ru": "все транзакции",
    })
    many_records = [
        FoundRecord(
            table="transactions", record_id=f"id{i}", preview_text=f"tx {i}", created_at=None
        )
        for i in range(51)
    ]
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=many_records,
        ),
    ):
        result = await skill._ai_search_and_delete("удали все транзакции", ctx)
    assert "слишком много" in result.response_text


async def test_ai_search_success_returns_preview_with_buttons(skill, ctx):
    """Successful AI search shows preview and confirm/cancel buttons."""
    llm_json = json.dumps({
        "tables": ["life_events"],
        "search_text": "кнопка",
        "life_event_type": "note",
        "confidence": 0.95,
        "explanation_ru": "заметка про кнопку",
    })
    found = [
        FoundRecord(
            table="life_events",
            record_id=str(uuid.uuid4()),
            preview_text="📝 нужно исправить кнопку",
            created_at=datetime(2026, 2, 17, 19, 46),
        ),
    ]
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=found,
        ),
        patch(f"{MODULE}.store_pending_action", new_callable=AsyncMock, return_value="ai-123"),
    ):
        result = await skill._ai_search_and_delete("удалить запись про кнопку", ctx)
    assert "Найдено: 1" in result.response_text
    assert "кнопку" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action:ai-123" in result.buttons[0]["callback"]
    assert "cancel_action:ai-123" in result.buttons[1]["callback"]


async def test_ai_search_invalid_table_filtered(skill, ctx):
    """Tables not in _VALID_AI_TABLES should be filtered out."""
    llm_json = json.dumps({
        "tables": ["fake_table", "life_events"],
        "search_text": "test",
        "confidence": 0.8,
        "explanation_ru": "test",
    })
    found = [
        FoundRecord(
            table="life_events",
            record_id=str(uuid.uuid4()),
            preview_text="📝 test",
            created_at=None,
        ),
    ]
    with (
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json),
        patch(
            f"{MODULE}._search_records_for_deletion",
            new_callable=AsyncMock,
            return_value=found,
        ) as mock_search,
        patch(f"{MODULE}.store_pending_action", new_callable=AsyncMock, return_value="x"),
    ):
        await skill._ai_search_and_delete("удали test", ctx)
    # Only valid table should be passed
    called_params = mock_search.call_args[0][0]
    assert "fake_table" not in called_params["tables"]
    assert "life_events" in called_params["tables"]


async def test_ai_search_all_invalid_tables_returns_disambiguation(skill, ctx):
    """If all tables from LLM are invalid, fall back to disambiguation."""
    llm_json = json.dumps({
        "tables": ["nonexistent"],
        "search_text": "test",
        "confidence": 0.8,
        "explanation_ru": "test",
    })
    with patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=llm_json):
        result = await skill._ai_search_and_delete("удали test", ctx)
    assert "Укажите" in result.response_text


# ---- execute_delete with found_records (AI path) ----


async def test_execute_delete_ai_found_records():
    """execute_delete should handle the AI search found_records path."""
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 2

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "ai_search",
        "found_records": [
            {"table": "life_events", "id": str(uuid.uuid4())},
            {"table": "life_events", "id": str(uuid.uuid4())},
        ],
        "explanation": "заметки про кнопку",
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    assert "2" in result
    assert "записей" in result


async def test_execute_delete_ai_multi_table():
    """execute_delete with found_records spanning multiple tables."""
    from src.skills.delete_data.handler import execute_delete

    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 1

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_exec_result
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "scope": "ai_search",
        "found_records": [
            {"table": "life_events", "id": str(uuid.uuid4())},
            {"table": "tasks", "id": str(uuid.uuid4())},
        ],
        "explanation": "разные записи",
    }

    with patch(f"{MODULE}.async_session", return_value=mock_ctx):
        result = await execute_delete(action_data, str(uuid.uuid4()), str(uuid.uuid4()))

    # Each table returns rowcount=1, so total = 2
    assert "2" in result
