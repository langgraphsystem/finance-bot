"""Tests for the multi-step FSM onboarding skill."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import ConversationState
from src.gateway.types import IncomingMessage, MessageType
from src.skills.onboarding.handler import (
    OnboardingSkill,
    _ask_activity_result,
    _ask_invite_code_result,
    _format_categories_text,
    _welcome_result,
)

# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture
def onboarding_skill():
    return OnboardingSkill()


@pytest.fixture
def empty_context():
    """Context for an unregistered user (no family_id)."""
    return SessionContext(
        user_id="999999999",
        family_id="",
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.fixture
def start_message():
    return IncomingMessage(
        id="1",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="/start",
    )


@pytest.fixture
def activity_message():
    """Message that does NOT match any profile alias, so LLM will be invoked."""
    return IncomingMessage(
        id="2",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="Я занимаюсь перевозкой людей по городу на своей машине",
    )


@pytest.fixture
def trucker_message():
    return IncomingMessage(
        id="3",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="у меня трак",
    )


@pytest.fixture
def invite_code_message():
    return IncomingMessage(
        id="4",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="ABC12345",
    )


@pytest.fixture
def short_code_message():
    return IncomingMessage(
        id="5",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="AB",
    )


@pytest.fixture
def household_message():
    return IncomingMessage(
        id="6",
        user_id="999999999",
        chat_id="chat_999",
        type=MessageType.text,
        text="просто хочу следить за расходами",
    )


# ---- Helper function tests --------------------------------------------------


class TestHelpers:
    def test_welcome_result_has_two_buttons(self):
        result = _welcome_result()
        assert result.buttons is not None
        assert len(result.buttons) == 2
        callbacks = [b["callback"] for b in result.buttons]
        assert "onboard:new" in callbacks
        assert "onboard:join" in callbacks

    def test_welcome_result_text(self):
        result = _welcome_result()
        assert "AI Assistant" in result.response_text

    def test_ask_activity_result(self):
        result = _ask_activity_result()
        assert "деятельности" in result.response_text
        assert result.buttons is None

    def test_ask_invite_code_result(self):
        result = _ask_invite_code_result()
        assert "код приглашения" in result.response_text.lower()
        assert result.buttons is None

    def test_format_categories_text_with_dict(self):
        from src.core.profiles import ProfileConfig

        profile = ProfileConfig(
            name="Test",
            categories={
                "business": [
                    {"name": "Cat1", "icon": "A"},
                    {"name": "Cat2", "icon": "B"},
                ],
            },
        )
        text = _format_categories_text(profile)
        assert "Cat1" in text
        assert "Cat2" in text

    def test_format_categories_text_empty(self):
        from src.core.profiles import ProfileConfig

        profile = ProfileConfig(name="Test", categories={})
        text = _format_categories_text(profile)
        assert text == ""

    def test_format_categories_text_none_profile(self):
        text = _format_categories_text(None)
        assert text == ""

    def test_format_categories_text_more_than_five(self):
        from src.core.profiles import ProfileConfig

        cats = [{"name": f"Cat{i}", "icon": "X"} for i in range(8)]
        profile = ProfileConfig(name="Test", categories={"business": cats})
        text = _format_categories_text(profile)
        assert "и ещё 3" in text


# ---- Step 1: /start → welcome -----------------------------------------------


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start_returns_welcome_with_buttons(
        self, onboarding_skill, start_message, empty_context
    ):
        result = await onboarding_skill.execute(start_message, empty_context, {})
        assert result.buttons is not None
        assert len(result.buttons) == 2
        assert "AI Assistant" in result.response_text

    @pytest.mark.asyncio
    async def test_start_buttons_have_correct_callbacks(
        self, onboarding_skill, start_message, empty_context
    ):
        result = await onboarding_skill.execute(start_message, empty_context, {})
        callbacks = [b["callback"] for b in result.buttons]
        assert "onboard:new" in callbacks
        assert "onboard:join" in callbacks

    @pytest.mark.asyncio
    async def test_no_family_no_state_shows_welcome(self, onboarding_skill, empty_context):
        """User with no family and no onboarding state should see welcome."""
        msg = IncomingMessage(
            id="10",
            user_id="999999999",
            chat_id="chat_999",
            type=MessageType.text,
            text="hello",
        )
        result = await onboarding_skill.execute(msg, empty_context, {})
        # Should show welcome since family_id is empty and no state
        assert result.buttons is not None


# ---- Step 2a: activity description → LLM → create family --------------------


class TestActivityDescription:
    @pytest.mark.asyncio
    async def test_alias_match_skips_llm(self, onboarding_skill, trucker_message, empty_context):
        """When text matches a profile alias, LLM should not be called."""
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_activity.value}
        mock_family = MagicMock()
        mock_family.invite_code = "TESTCODE"
        mock_user = MagicMock()

        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.create_family",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ):
                result = await onboarding_skill.execute(trucker_message, empty_context, intent_data)

        assert "Отлично!" in result.response_text
        assert "TESTCODE" in result.response_text
        assert result.buttons is None

    @pytest.mark.asyncio
    async def test_llm_determines_business_type(
        self, onboarding_skill, activity_message, empty_context
    ):
        """When alias does not match, LLM determines business type."""
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_activity.value}
        mock_family = MagicMock()
        mock_family.invite_code = "TAXICODE"
        mock_user = MagicMock()

        # Mock LLM response
        mock_response = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = "taxi"
        mock_response.content = [mock_content_block]

        mock_gen = AsyncMock(return_value="taxi")

        with patch(
            "src.skills.onboarding.handler.generate_text",
            mock_gen,
        ):
            with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch(
                    "src.skills.onboarding.handler.create_family",
                    new_callable=AsyncMock,
                    return_value=(mock_family, mock_user),
                ) as mock_create:
                    result = await onboarding_skill.execute(
                        activity_message, empty_context, intent_data
                    )
                    # Verify create_family was called with taxi
                    call_kwargs = mock_create.call_args
                    assert call_kwargs.kwargs.get("business_type") == "taxi"

        assert "Отлично!" in result.response_text
        assert result.buttons is None

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_household(
        self, onboarding_skill, activity_message, empty_context
    ):
        """When LLM fails, should fall back to household."""
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_activity.value}
        mock_family = MagicMock()
        mock_family.invite_code = "FALLBACK"
        mock_user = MagicMock()

        mock_gen = AsyncMock(side_effect=Exception("API error"))

        with patch(
            "src.skills.onboarding.handler.generate_text",
            mock_gen,
        ):
            with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch(
                    "src.skills.onboarding.handler.create_family",
                    new_callable=AsyncMock,
                    return_value=(mock_family, mock_user),
                ) as mock_create:
                    result = await onboarding_skill.execute(
                        activity_message, empty_context, intent_data
                    )
                    call_kwargs = mock_create.call_args
                    # household -> business_type=None
                    assert call_kwargs.kwargs.get("business_type") is None

        assert "Отлично!" in result.response_text

    @pytest.mark.asyncio
    async def test_create_family_failure_returns_error(
        self, onboarding_skill, trucker_message, empty_context
    ):
        """When create_family raises, return error message."""
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_activity.value}
        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.create_family",
                new_callable=AsyncMock,
                side_effect=Exception("DB error"),
            ):
                result = await onboarding_skill.execute(trucker_message, empty_context, intent_data)

        assert "ошибка" in result.response_text.lower()


# ---- Step 2b: invite code → join family -------------------------------------


class TestInviteCode:
    @pytest.mark.asyncio
    async def test_valid_invite_code_joins_family(
        self, onboarding_skill, invite_code_message, empty_context
    ):
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_invite_code.value}
        mock_family = MagicMock()
        mock_family.name = "Семья Тест"
        mock_user = MagicMock()

        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.join_family",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ):
                result = await onboarding_skill.execute(
                    invite_code_message, empty_context, intent_data
                )

        assert "присоединились" in result.response_text.lower()
        assert "Семья Тест" in result.response_text
        assert result.buttons is None

    @pytest.mark.asyncio
    async def test_invalid_invite_code_returns_error(
        self, onboarding_skill, invite_code_message, empty_context
    ):
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_invite_code.value}
        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.join_family",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await onboarding_skill.execute(
                    invite_code_message, empty_context, intent_data
                )

        assert "неверный" in result.response_text.lower()

    @pytest.mark.asyncio
    async def test_short_invite_code_rejected(
        self, onboarding_skill, short_code_message, empty_context
    ):
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_invite_code.value}
        result = await onboarding_skill.execute(short_code_message, empty_context, intent_data)
        assert "короткий" in result.response_text.lower()

    @pytest.mark.asyncio
    async def test_join_family_failure_returns_error(
        self, onboarding_skill, invite_code_message, empty_context
    ):
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_invite_code.value}
        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.join_family",
                new_callable=AsyncMock,
                side_effect=Exception("DB error"),
            ):
                result = await onboarding_skill.execute(
                    invite_code_message, empty_context, intent_data
                )

        assert "ошибка" in result.response_text.lower()


# ---- Awaiting choice state --------------------------------------------------


class TestAlreadyRegistered:
    @pytest.mark.asyncio
    async def test_registered_user_greeting_not_reonboard(self, onboarding_skill):
        """Registered user sending 'привет' should NOT see onboarding flow."""
        ctx = SessionContext(
            user_id="11111111-1111-1111-1111-111111111111",
            family_id="22222222-2222-2222-2222-222222222222",
            role="owner",
            language="ru",
            currency="USD",
            business_type="trucker",
            categories=[],
            merchant_mappings=[],
        )
        msg = IncomingMessage(
            id="100",
            user_id="999999999",
            chat_id="chat_999",
            type=MessageType.text,
            text="привет",
        )
        result = await onboarding_skill.execute(msg, ctx, {})
        assert "уже зарегистрированы" in result.response_text
        assert result.buttons is None

    @pytest.mark.asyncio
    async def test_registered_user_start_still_works(self, onboarding_skill):
        """Registered user sending /start should still see welcome."""
        ctx = SessionContext(
            user_id="11111111-1111-1111-1111-111111111111",
            family_id="22222222-2222-2222-2222-222222222222",
            role="owner",
            language="ru",
            currency="USD",
            business_type="trucker",
            categories=[],
            merchant_mappings=[],
        )
        msg = IncomingMessage(
            id="101",
            user_id="999999999",
            chat_id="chat_999",
            type=MessageType.text,
            text="/start",
        )
        result = await onboarding_skill.execute(msg, ctx, {})
        assert result.buttons is not None
        assert len(result.buttons) == 2


class TestDuplicateUser:
    @pytest.mark.asyncio
    async def test_existing_user_returns_success_not_error(
        self, onboarding_skill, trucker_message, empty_context
    ):
        """When user already exists, onboarding returns success (existing family)."""
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_activity.value}
        mock_family = MagicMock()
        mock_family.invite_code = "EXISTING"
        mock_user = MagicMock()

        with patch("src.skills.onboarding.handler.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.skills.onboarding.handler.create_family",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ):
                result = await onboarding_skill.execute(trucker_message, empty_context, intent_data)

        # Should succeed, NOT return error
        assert "Отлично!" in result.response_text
        assert "EXISTING" in result.response_text


# ---- Awaiting choice state --------------------------------------------------


class TestAwaitingChoice:
    @pytest.mark.asyncio
    async def test_awaiting_choice_shows_welcome(self, onboarding_skill, empty_context):
        msg = IncomingMessage(
            id="20",
            user_id="999999999",
            chat_id="chat_999",
            type=MessageType.text,
            text="что-то",
        )
        intent_data = {"onboarding_state": ConversationState.onboarding_awaiting_choice.value}
        result = await onboarding_skill.execute(msg, empty_context, intent_data)
        assert result.buttons is not None
        assert len(result.buttons) == 2


# ---- Skill attributes -------------------------------------------------------


class TestSkillAttributes:
    def test_skill_name(self, onboarding_skill):
        assert onboarding_skill.name == "onboarding"

    def test_skill_intents(self, onboarding_skill):
        assert "onboarding" in onboarding_skill.intents

    def test_skill_model(self, onboarding_skill):
        model = onboarding_skill.model.lower()
        assert "claude" in model or "sonnet" in model

    def test_get_system_prompt(self, onboarding_skill, empty_context):
        prompt = onboarding_skill.get_system_prompt(empty_context)
        assert "household" in prompt
        assert "taxi" in prompt

    def test_has_execute_method(self, onboarding_skill):
        assert hasattr(onboarding_skill, "execute")

    def test_has_get_system_prompt_method(self, onboarding_skill):
        assert hasattr(onboarding_skill, "get_system_prompt")
