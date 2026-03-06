"""Tests for project_manager skill (Phase 12)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.project_manager.handler import (
    ProjectManagerSkill,
    _extract_project_name,
)

skill = ProjectManagerSkill()


class _MockMessage:
    def __init__(self, text=""):
        self.text = text
        self.chat_id = 123


class _MockContext:
    def __init__(self):
        self.user_id = uuid.uuid4()
        self.family_id = uuid.uuid4()
        self.language = "en"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
class TestExtractProjectName:
    def test_ru_pro(self):
        assert _extract_project_name("это про Титан") == "Титан"

    def test_ru_create(self):
        assert _extract_project_name("создай проект Stridos") == "Stridos"

    def test_en_switch(self):
        assert _extract_project_name("switch to project Alpha") == "Alpha"

    def test_en_work_on(self):
        assert _extract_project_name("work on project Beta") == "Beta"

    def test_plain_text(self):
        assert _extract_project_name("hello") == "hello"


# ---------------------------------------------------------------------------
# Skill metadata
# ---------------------------------------------------------------------------
class TestSkillMetadata:
    def test_intents(self):
        assert "set_project" in skill.intents
        assert "create_project" in skill.intents
        assert "list_projects" in skill.intents

    def test_name(self):
        assert skill.name == "project_manager"


# ---------------------------------------------------------------------------
# Create project
# ---------------------------------------------------------------------------
class TestCreateProject:
    async def test_create_success(self):
        ctx = _MockContext()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        with (
            patch("src.core.db.async_session") as mock_as,
            patch(
                "src.skills.project_manager.handler._set_active_project",
                new_callable=AsyncMock,
            ),
            patch(
                "src.skills.project_manager.handler._mem0_save_project",
                new_callable=AsyncMock,
            ),
        ):
            mock_as.return_value.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            mock_as.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await skill.execute(
                _MockMessage("создай проект Titan"),
                ctx,
                {"_intent": "create_project", "project_name": "Titan"},
            )
        assert "Titan" in result.response_text

    async def test_create_empty_name(self):
        ctx = _MockContext()
        result = await skill.execute(
            _MockMessage(""),
            ctx,
            {"_intent": "create_project", "project_name": ""},
        )
        lower = result.response_text.lower()
        assert "specify" in lower or "укажите" in lower


# ---------------------------------------------------------------------------
# List projects
# ---------------------------------------------------------------------------
class TestListProjects:
    async def test_list_empty(self):
        ctx = _MockContext()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.core.db.async_session") as mock_as:
            mock_as.return_value.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            mock_as.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await skill.execute(
                _MockMessage("мои проекты"),
                ctx,
                {"_intent": "list_projects"},
            )
        lower = result.response_text.lower()
        assert "don't have" in lower or "нет" in lower


# ---------------------------------------------------------------------------
# Set active project
# ---------------------------------------------------------------------------
class TestSetProject:
    async def test_set_not_found(self):
        ctx = _MockContext()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.core.db.async_session") as mock_as:
            mock_as.return_value.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            mock_as.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await skill.execute(
                _MockMessage("переключись на проект Titan"),
                ctx,
                {"_intent": "set_project", "project_name": "Titan"},
            )
        lower = result.response_text.lower()
        assert "not found" in lower or "не найден" in lower
        assert result.buttons
