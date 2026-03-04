"""Tests for scheduled action collector wrappers."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from src.core.scheduled_actions.collectors import build_brief_state, collect_sources


def _action(sources: list[str]):
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        language="ru",
        sources=sources,
    )


def test_build_brief_state_maps_action_fields():
    action = _action(["calendar"])

    state = build_brief_state(action)

    assert state["intent"] == "morning_brief"
    assert state["user_id"] == str(action.user_id)
    assert state["family_id"] == str(action.family_id)
    assert state["language"] == "ru"
    assert state["active_sections"] == []


async def test_collect_sources_timeout_does_not_block_other_sources():
    async def slow_collector(_state):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return {"calendar_data": "calendar ok"}

    async def fast_collector(_state):  # noqa: ANN001
        return {"tasks_data": "tasks ok"}

    action = _action(["calendar", "tasks"])
    source_map = {
        "calendar": (slow_collector, "calendar_data"),
        "tasks": (fast_collector, "tasks_data"),
    }

    with (
        patch("src.core.scheduled_actions.collectors.SOURCE_TIMEOUT_SECONDS", 0.01),
        patch("src.core.scheduled_actions.collectors._SOURCE_COLLECTOR_MAP", source_map),
    ):
        payload, status = await collect_sources(action)

    assert payload["calendar"] == ""
    assert payload["tasks"] == "tasks ok"
    assert status["calendar"]["status"] == "failed"
    assert status["calendar"]["error"] == "timeout"
    assert status["tasks"]["status"] == "success"
    assert status["calendar"]["duration_ms"] >= 0
    assert status["tasks"]["duration_ms"] >= 0
