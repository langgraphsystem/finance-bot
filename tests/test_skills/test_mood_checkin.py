"""Tests for mood_checkin skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.mood_checkin.handler import MoodCheckinSkill


@pytest.fixture
def skill():
    return MoodCheckinSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="настроение 7",
    )


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


def _patch_helpers(mode: str = "receipt"):
    """Patch save_life_event and get_communication_mode."""
    return (
        patch(
            "src.skills.mood_checkin.handler.save_life_event",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.mood_checkin.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value=mode,
        ),
    )


@pytest.mark.asyncio
async def test_mood_energy_stress_sleep_recorded(skill, message, ctx):
    """All four metrics are saved in data dict."""
    intent_data = {
        "mood": 7,
        "energy": 6,
        "stress": 4,
        "sleep": 8,
    }
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.mood
    data = call_kwargs["data"]
    assert data["mood"] == 7
    assert data["energy"] == 6
    assert data["stress"] == 4
    assert data["sleep"] == 8
    assert "настроение" in call_kwargs["text"]
    assert result.response_text


@pytest.mark.asyncio
async def test_buttons_returned_when_no_metrics(skill, message, ctx):
    """Interactive buttons are returned when no metrics provided."""
    result = await skill.execute(message, ctx, {})

    assert "Как дела" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) > 0
    # Verify button structure
    assert "text" in result.buttons[0]
    assert "callback" in result.buttons[0]


@pytest.mark.asyncio
async def test_values_clamped_to_min_1(skill, message, ctx):
    """Values below 1 are clamped to 1."""
    intent_data = {"mood": -5, "energy": 0}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(message, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["mood"] == 1
    assert data["energy"] == 1


@pytest.mark.asyncio
async def test_values_clamped_to_max_10(skill, message, ctx):
    """Values above 10 are clamped to 10."""
    intent_data = {"mood": 15, "stress": 99}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(message, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["mood"] == 10
    assert data["stress"] == 10


@pytest.mark.asyncio
async def test_coaching_tip_high_average(skill, message, ctx):
    """Coaching tip for high average (>= 7) is positive."""
    intent_data = {"mood": 8, "energy": 9}
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    assert "\U0001f4a1" in result.response_text
    assert "Отличный день" in result.response_text


@pytest.mark.asyncio
async def test_coaching_tip_medium_average(skill, message, ctx):
    """Coaching tip for medium average (4-6) suggests rest."""
    intent_data = {"mood": 5, "energy": 5}
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    assert "Средний день" in result.response_text


@pytest.mark.asyncio
async def test_coaching_tip_low_average(skill, message, ctx):
    """Coaching tip for low average (< 4) suggests self-care."""
    intent_data = {"mood": 2, "energy": 3}
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    assert "Непростой день" in result.response_text


@pytest.mark.asyncio
async def test_silent_mode(skill, message, ctx):
    """Silent mode returns empty response."""
    intent_data = {"mood": 7}
    p_save, p_mode = _patch_helpers(mode="silent")

    with p_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_partial_metrics_accepted(skill, message, ctx):
    """Only mood is provided; other metrics are absent."""
    intent_data = {"mood": 6}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(message, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert "mood" in data
    assert "energy" not in data
    assert "stress" not in data
    assert "sleep" not in data
    assert result.response_text
