import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.schemas.intent import IntentData, IntentDetectionResult
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillResult

MODULE = "src.core.router"



def _sample_context():
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


async def test_domain_router_fallback_preserves_memory_intent():
    msg = IncomingMessage(
        id="1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="забудь моё имя",
    )
    ctx = _sample_context()
    detect_result = IntentDetectionResult(
        intent="memory_forget",
        confidence=0.95,
        intent_type="action",
        data=IntentData(memory_query="забудь моё имя"),
    )

    mock_skill = MagicMock()
    mock_skill.execute = AsyncMock(return_value=SkillResult(response_text="ok"))
    mock_registry = MagicMock()
    mock_registry.get.side_effect = lambda intent: mock_skill if intent == "memory_forget" else None
    mock_domain_router = MagicMock()
    mock_domain_router.route = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch(f"{MODULE}.get_registry", return_value=mock_registry),
        patch(f"{MODULE}.get_domain_router", return_value=mock_domain_router),
        patch(f"{MODULE}._get_intent_detector", return_value=AsyncMock(return_value=detect_result)),
        patch(f"{MODULE}.check_input", new_callable=AsyncMock, return_value=(True, None)),
        patch(f"{MODULE}.check_rate_limit", new_callable=AsyncMock, return_value=True),
        patch(f"{MODULE}._check_browser_login_flow", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}._check_browser_booking_flow", new_callable=AsyncMock, return_value=None),
        patch(
            "src.core.rate_limiter.check_rate_limit",
            new_callable=AsyncMock,
            return_value=(True, "free"),
        ),
        patch(
            f"{MODULE}.sliding_window.get_recent_messages",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(f"{MODULE}.sliding_window.add_message", new_callable=AsyncMock),
        patch(f"{MODULE}._persist_message", new_callable=AsyncMock),
        patch(f"{MODULE}.summarize_dialog", new_callable=AsyncMock),
        patch(f"{MODULE}.asyncio.create_task", return_value=None),
        patch(f"{MODULE}.settings.ff_post_gen_check", False),
    ):
        from src.core.router import handle_message

        result = await handle_message(msg, ctx)

    assert result.text == "ok"
    skill_intent_data = mock_skill.execute.await_args.args[2]
    assert skill_intent_data["_intent"] == "memory_forget"
    assert skill_intent_data["memory_query"] == "забудь моё имя"


