"""Dedicated tests for SIA intent detection acceptance criteria (B1)."""

from unittest.mock import AsyncMock, patch

import pytest

from src.core.intent import detect_intent_scoped
from src.core.schemas.intent import IntentData, IntentDetectionResult


def _make_sia_result(
    *,
    frequency: str,
    time: str,
    sources: list[str],
    instruction: str,
    confidence: float = 0.9,
) -> IntentDetectionResult:
    return IntentDetectionResult(
        intent="schedule_action",
        confidence=confidence,
        intent_type="action",
        data=IntentData(
            schedule_frequency=frequency,
            schedule_time=time,
            schedule_sources=sources,
            schedule_instruction=instruction,
        ),
        response="ok",
    )


@pytest.mark.parametrize(
    ("text", "llm_result", "expected_frequency", "expected_time", "expected_sources"),
    [
        (
            "Every day at 8 send me calendar and tasks.",
            _make_sia_result(
                frequency="daily",
                time="08:00",
                sources=["calendar", "tasks"],
                instruction="Daily digest with calendar and tasks.",
                confidence=0.93,
            ),
            "daily",
            "08:00",
            ["calendar", "tasks"],
        ),
        (
            "Каждое утро в 8 отправляй сводку по задачам и календарю.",
            _make_sia_result(
                frequency="daily",
                time="08:00",
                sources=["tasks", "calendar"],
                instruction="Утренняя сводка по задачам и календарю.",
                confidence=0.91,
            ),
            "daily",
            "08:00",
            ["tasks", "calendar"],
        ),
        (
            "Programa un resumen semanal con tareas y finanzas a las 07:30.",
            _make_sia_result(
                frequency="weekly",
                time="07:30",
                sources=["tasks", "money_summary"],
                instruction="Resumen semanal con tareas y finanzas.",
                confidence=0.9,
            ),
            "weekly",
            "07:30",
            ["tasks", "money_summary"],
        ),
    ],
)
async def test_detect_intent_scoped_sia_recurring_en_ru_es(
    text: str,
    llm_result: IntentDetectionResult,
    expected_frequency: str,
    expected_time: str,
    expected_sources: list[str],
):
    """Recurring schedule requests must be detected with high confidence."""
    with (
        patch(
            "src.core.intent._detect_with_gemini",
            new_callable=AsyncMock,
            return_value=llm_result,
        ) as mock_gemini,
        patch(
            "src.core.intent._detect_with_claude",
            new_callable=AsyncMock,
        ) as mock_claude,
    ):
        result = await detect_intent_scoped(
            text=text,
            domain="tasks",
            intents=["schedule_action", "set_reminder", "create_task"],
            language="ru",
        )

    assert result.intent == "schedule_action"
    assert result.confidence >= 0.8
    assert result.data is not None
    assert result.data.schedule_frequency == expected_frequency
    assert result.data.schedule_time == expected_time
    assert result.data.schedule_sources == expected_sources
    assert result.data.domain == "tasks"
    mock_gemini.assert_awaited_once()
    mock_claude.assert_not_awaited()


async def test_detect_intent_scoped_sia_one_shot_with_high_confidence():
    """One-shot schedule request must also satisfy confidence >= 0.8."""
    llm_result = _make_sia_result(
        frequency="once",
        time="18:30",
        sources=["calendar"],
        instruction="One-time evening summary.",
        confidence=0.89,
    )

    with patch(
        "src.core.intent._detect_with_gemini",
        new_callable=AsyncMock,
        return_value=llm_result,
    ):
        result = await detect_intent_scoped(
            text="At 6:30 PM today send me a one-time calendar summary.",
            domain="tasks",
            intents=["schedule_action", "set_reminder", "create_task"],
            language="en",
        )

    assert result.intent == "schedule_action"
    assert result.confidence >= 0.8
    assert result.data is not None
    assert result.data.schedule_frequency == "once"
    assert result.data.schedule_time == "18:30"
    assert result.data.schedule_sources == ["calendar"]
    assert result.data.domain == "tasks"
