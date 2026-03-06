"""Tests for CLARIFY disambiguation flow."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.schemas.intent import (
    ClarifyCandidate,
    IntentDetectionResult,
)
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillResult

MODULE = "src.core.router"


@pytest.fixture
def sample_ctx():
    from src.core.context import SessionContext

    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.fixture
def clarify_result():
    """Intent result with clarify type."""
    return IntentDetectionResult(
        intent="general_chat",
        confidence=0.35,
        intent_type="clarify",
        response="Что именно вы хотите?",
        clarify_candidates=[
            ClarifyCandidate(
                intent="send_email",
                label="Отправить email",
                confidence=0.4,
            ),
            ClarifyCandidate(
                intent="draft_message",
                label="Написать сообщение",
                confidence=0.35,
            ),
        ],
    )


@pytest.fixture
def high_confidence_result():
    """Intent result with high confidence."""
    return IntentDetectionResult(
        intent="add_expense",
        confidence=0.95,
        intent_type="action",
    )


def test_intent_type_defaults_to_action():
    """IntentDetectionResult defaults intent_type to action."""
    result = IntentDetectionResult(intent="add_expense", confidence=0.9)
    assert result.intent_type == "action"
    assert result.clarify_candidates is None


def test_clarify_candidates_parsing():
    """ClarifyCandidate parses correctly."""
    result = IntentDetectionResult(
        intent="general_chat",
        confidence=0.3,
        intent_type="clarify",
        clarify_candidates=[
            ClarifyCandidate(
                intent="send_email",
                label="Email",
                confidence=0.4,
            ),
        ],
    )
    assert len(result.clarify_candidates) == 1
    assert result.clarify_candidates[0].intent == "send_email"


@pytest.mark.asyncio
async def test_low_confidence_triggers_clarify(sample_ctx, clarify_result):
    """When intent_type=clarify with candidates, return buttons."""
    msg = IncomingMessage(
        id="1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="отправь",
    )

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with (
        patch(
            f"{MODULE}.detect_intent",
            new_callable=AsyncMock,
            return_value=clarify_result,
        ),
        patch(
            f"{MODULE}.check_input",
            new_callable=AsyncMock,
            return_value=(True, None),
        ),
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("src.core.db.redis", mock_redis),
        patch("src.tools.browser_login.redis", mock_redis),
        patch("src.tools.browser_booking.redis", mock_redis),
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    assert "Уточните" in result.text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert result.buttons[0]["callback"] == "clarify:send_email"
    assert result.buttons[1]["callback"] == "clarify:draft_message"
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_high_confidence_skips_clarify(sample_ctx, high_confidence_result):
    """When confidence is high, no clarify gate triggered."""
    msg = IncomingMessage(
        id="2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="заправился на 50",
    )

    # Mock the domain router to return a result
    mock_skill_result = MagicMock()
    mock_skill_result.response_text = "Записал: Бензин $50"
    mock_skill_result.buttons = None
    mock_skill_result.document = None
    mock_skill_result.document_name = None
    mock_skill_result.photo_url = None
    mock_skill_result.chart_url = None
    mock_skill_result.background_tasks = []

    mock_dr = MagicMock()
    mock_dr.route = AsyncMock(return_value=mock_skill_result)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with (
        patch(
            f"{MODULE}.detect_intent",
            new_callable=AsyncMock,
            return_value=high_confidence_result,
        ),
        patch(
            f"{MODULE}.check_input",
            new_callable=AsyncMock,
            return_value=(True, None),
        ),
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(f"{MODULE}.get_domain_router", return_value=mock_dr),
        patch(f"{MODULE}._persist_message", new_callable=AsyncMock),
        patch(
            f"{MODULE}.summarize_dialog",
            new_callable=AsyncMock,
        ),
        patch(
            f"{MODULE}.sliding_window.add_message",
            new_callable=AsyncMock,
        ),
        patch("src.tools.browser_login.redis", mock_redis),
        patch("src.tools.browser_booking.redis", mock_redis),
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    # Should have gone through normal flow, not clarify
    assert "Уточните" not in result.text
    mock_dr.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_clarify_callback_resolves_intent(sample_ctx):
    """Pressing a clarify button executes the chosen intent."""
    msg = IncomingMessage(
        id="3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.callback,
        callback_data="clarify:send_email",
    )

    pending_data = json.dumps(
        {
            "original_text": "отправь",
            "candidates": [
                {
                    "intent": "send_email",
                    "label": "Email",
                    "confidence": 0.4,
                }
            ],
            "intent_data": {},
            "created_at": "2026-02-18T12:00:00",
        }
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=pending_data)
    mock_redis.delete = AsyncMock()

    mock_skill_result = MagicMock()
    mock_skill_result.response_text = "Черновик email..."
    mock_skill_result.buttons = None
    mock_skill_result.document = None
    mock_skill_result.document_name = None
    mock_skill_result.chart_url = None
    mock_skill_result.background_tasks = []

    mock_dr = MagicMock()
    mock_dr.route = AsyncMock(return_value=mock_skill_result)

    mock_sw = MagicMock()
    mock_sw.add_message = AsyncMock()

    with (
        patch("src.core.db.redis", mock_redis),
        patch(f"{MODULE}.get_domain_router", return_value=mock_dr),
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "src.core.memory.sliding_window.add_message",
            new_callable=AsyncMock,
        ),
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    assert result.text == "Черновик email..."
    mock_dr.route.assert_awaited_once()
    # Verify chosen intent was passed
    call_args = mock_dr.route.call_args
    assert call_args[0][0] == "send_email"


@pytest.mark.asyncio
async def test_clarify_expired_returns_message(sample_ctx):
    """If clarify state expired, ask user to retype."""
    msg = IncomingMessage(
        id="4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.callback,
        callback_data="clarify:send_email",
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with (
        patch("src.core.db.redis", mock_redis),
        patch(
            f"{MODULE}.check_rate_limit",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, sample_ctx)

    assert "истекло" in result.text.lower()


@pytest.mark.asyncio
async def test_resolve_clarify_preserves_mutated_skill_result_fields(sample_ctx):
    """Clarify callback should forward photo_url and reply keyboard from side effects."""
    from src.core.router import _resolve_clarify

    msg = IncomingMessage(
        id="5",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.callback,
        callback_data="clarify:send_email",
    )

    pending_data = json.dumps(
        {
            "original_text": "отправь письмо",
            "candidates": [
                {
                    "intent": "send_email",
                    "label": "Email",
                    "confidence": 0.4,
                }
            ],
            "intent_data": {},
            "created_at": "2026-02-18T12:00:00",
        }
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=pending_data)
    mock_redis.delete = AsyncMock()

    routed_result = SkillResult(response_text="Черновик email...")
    final_result = SkillResult(
        response_text="Черновик email...",
        photo_url="https://example.com/result.png",
        reply_keyboard=[{"text": "Send now"}],
    )
    mock_dr = MagicMock()
    mock_dr.route = AsyncMock(return_value=routed_result)

    with (
        patch("src.core.db.redis", mock_redis),
        patch(f"{MODULE}.get_domain_router", return_value=mock_dr),
        patch(f"{MODULE}._run_post_skill_side_effects", new_callable=AsyncMock) as mock_side_fx,
    ):
        mock_side_fx.return_value = final_result
        result = await _resolve_clarify("send_email", msg, sample_ctx)

    assert result.text == "Черновик email..."
    assert result.photo_url == "https://example.com/result.png"
    assert result.reply_keyboard == [{"text": "Send now"}]


@pytest.mark.asyncio
async def test_plan_execute_preserves_mutated_skill_result_fields(sample_ctx):
    """Plan execution callback should forward photo_url and reply keyboard from side effects."""
    from src.core.router import _handle_plan_callback

    msg = IncomingMessage(
        id="6",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.callback,
        callback_data="plan:execute",
    )

    routed_result = SkillResult(response_text="Готово")
    final_result = SkillResult(
        response_text="Готово",
        photo_url="https://example.com/plan.png",
        reply_keyboard=[{"text": "Continue"}],
    )
    mock_dr = MagicMock()
    mock_dr.route = AsyncMock(return_value=routed_result)

    with (
        patch(
            "src.core.reverse_prompt.get_pending_plan",
            new_callable=AsyncMock,
            return_value={
                "intent": "send_email",
                "original_text": "отправь письмо",
                "intent_data": {},
            },
        ),
        patch(
            "src.core.reverse_prompt.delete_pending_plan",
            new_callable=AsyncMock,
        ),
        patch(f"{MODULE}.get_domain_router", return_value=mock_dr),
        patch(f"{MODULE}._run_post_skill_side_effects", new_callable=AsyncMock) as mock_side_fx,
    ):
        mock_side_fx.return_value = final_result
        result = await _handle_plan_callback("execute", msg, sample_ctx)

    assert result.text == "Готово"
    assert result.photo_url == "https://example.com/plan.png"
    assert result.reply_keyboard == [{"text": "Continue"}]
