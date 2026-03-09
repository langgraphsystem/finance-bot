import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.project_context import get_active_project_block
from src.core.models.enums import ProjectStatus


def _mock_session_with_results(*results):
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(results))
    ctx = AsyncMock()
    ctx.__aenter__.return_value = session
    ctx.__aexit__.return_value = False
    return ctx


class TestProjectContext:
    async def test_loads_active_project_block(self):
        project_id = uuid.uuid4()
        user_id = uuid.uuid4()
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = project_id

        project = MagicMock()
        project.name = "Titan"
        project.description = "Main rollout"
        project.status = ProjectStatus.active
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        with (
            patch(
                "src.core.memory.project_context.async_session",
                return_value=_mock_session_with_results(active_result, project_result),
            ),
            patch(
                "src.core.memory.project_context._load_project_facts",
                new_callable=AsyncMock,
                return_value=["Launch in April"],
            ),
        ):
            block = await get_active_project_block(str(user_id))

        assert "<active_project>" in block
        assert "Titan" in block
        assert "Launch in April" in block

    async def test_falls_back_to_latest_active_project(self):
        user_id = uuid.uuid4()
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = None

        project = MagicMock()
        project.name = "Fallback"
        project.description = None
        project.status = ProjectStatus.paused
        fallback_result = MagicMock()
        fallback_result.scalar_one_or_none.return_value = project

        with (
            patch(
                "src.core.memory.project_context.async_session",
                return_value=_mock_session_with_results(active_result, fallback_result),
            ),
            patch(
                "src.core.memory.project_context._load_project_facts",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            block = await get_active_project_block(str(user_id))

        assert "Fallback" in block
        assert "paused" in block

    async def test_returns_empty_for_invalid_user_id(self):
        block = await get_active_project_block("not-a-uuid")
        assert block == ""
