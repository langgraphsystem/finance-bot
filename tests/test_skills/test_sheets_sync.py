"""Tests for Google Sheets sync skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.sheets_sync.handler import (
    SheetsSyncSkill,
    _detect_action,
    _detect_sync_scope,
)


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        text=text,
        type=MessageType.text,
    )


# --- Scope detection ---


def test_detect_scope_from_intent_data():
    assert _detect_sync_scope({"sync_scope": "tasks"}, "") == "tasks"
    assert _detect_sync_scope({"sync_scope": "contacts"}, "") == "contacts"
    assert _detect_sync_scope({"sync_scope": "expenses"}, "") == "expenses"


def test_detect_scope_from_export_type():
    assert _detect_sync_scope({"export_type": "tasks"}, "") == "tasks"


def test_detect_scope_from_message():
    assert _detect_sync_scope({}, "sync my tasks to sheets") == "tasks"
    assert _detect_sync_scope({}, "контакты в гугл таблицу") == "contacts"
    assert _detect_sync_scope({}, "sync expenses") == "expenses"


def test_detect_scope_default():
    assert _detect_sync_scope({}, "sync to sheets") == "expenses"


# --- Action detection ---


def test_detect_action_create():
    assert _detect_action({}, "sync to google sheets") == "create"
    assert _detect_action({}, "создай таблицу") == "create"


def test_detect_action_stop():
    assert _detect_action({}, "stop sheets sync") == "stop"
    assert _detect_action({}, "отключи синхронизацию") == "stop"


def test_detect_action_status():
    assert _detect_action({}, "sheets sync status") == "status"
    assert _detect_action({}, "статус синхронизации") == "status"


# --- Skill execution ---


async def test_execute_requires_google_auth(sample_context):
    """When no Google connection, return auth prompt."""
    skill = SheetsSyncSkill()
    msg = _make_message("sync to sheets")

    with patch(
        "src.skills.sheets_sync.handler.require_google_or_prompt",
        new_callable=AsyncMock,
    ) as mock_auth:
        from src.skills.base import SkillResult

        mock_auth.return_value = SkillResult(
            response_text="Connect Google",
            buttons=[{"text": "Connect", "url": "https://example.com"}],
        )

        result = await skill.execute(msg, sample_context, {})

    assert "Connect Google" in result.response_text
    mock_auth.assert_called_once_with(sample_context.user_id, service="sheets")


async def test_execute_stop_no_active_syncs(sample_context):
    """Stop action with no active syncs returns message."""
    skill = SheetsSyncSkill()
    msg = _make_message("stop sheets sync")

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.skills.sheets_sync.handler.async_session") as mock_session_maker,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session_maker.return_value = mock_session

        result = await skill.execute(msg, sample_context, {})

    assert "No active" in result.response_text


async def test_execute_status_no_syncs(sample_context):
    """Status with no syncs suggests creating one."""
    skill = SheetsSyncSkill()
    msg = _make_message("sheets sync status")

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.skills.sheets_sync.handler.async_session") as mock_session_maker,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session_maker.return_value = mock_session

        result = await skill.execute(msg, sample_context, {})

    assert "No active" in result.response_text


async def test_execute_create_new_sync(sample_context):
    """Create action creates a sheet and saves config."""
    skill = SheetsSyncSkill()
    msg = _make_message("sync my expenses to google sheets")

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.skills.sheets_sync.handler.async_session") as mock_session_maker,
        patch.object(
            skill,
            "_create_spreadsheet",
            new_callable=AsyncMock,
            return_value="spreadsheet123",
        ),
        patch.object(skill, "_push_data", new_callable=AsyncMock),
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing sync
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session_maker.return_value = mock_session

        result = await skill.execute(msg, sample_context, {})

    assert "spreadsheet123" in result.response_text
    assert "syncs automatically" in result.response_text
    assert result.buttons is not None


async def test_execute_existing_sync_returns_info(sample_context):
    """Create action with existing sync returns existing sheet URL."""
    skill = SheetsSyncSkill()
    msg = _make_message("sync expenses to sheets")

    existing_config = MagicMock()
    existing_config.spreadsheet_id = "existing_sheet_id"

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.skills.sheets_sync.handler.async_session") as mock_session_maker,
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_config
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session_maker.return_value = mock_session

        result = await skill.execute(msg, sample_context, {})

    assert "existing_sheet_id" in result.response_text
    assert "already" in result.response_text


def test_skill_has_required_attributes():
    """Skill has all required protocol attributes."""
    skill = SheetsSyncSkill()
    assert skill.name == "sheets_sync"
    assert skill.intents == ["sheets_sync"]
    assert skill.model == "claude-haiku-4-5"
    assert hasattr(skill, "execute")
    assert hasattr(skill, "get_system_prompt")
