"""Tests for channel onboarding — registration from Slack, WhatsApp, SMS."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import ConversationState
from src.gateway.types import IncomingMessage, MessageType
from src.skills.onboarding.handler import OnboardingSkill


@pytest.fixture
def onboarding_skill():
    with patch(
        "src.skills.onboarding.handler.ProfileLoader"
    ) as mock_loader_cls:
        mock_loader = MagicMock()
        mock_profile = MagicMock()
        mock_profile.name = "Household"
        mock_profile.categories = {"family": [{"name": "Food"}, {"name": "Transport"}]}
        mock_loader.get.return_value = mock_profile
        mock_loader.match.return_value = None
        mock_loader._profiles = {"household": mock_profile}
        mock_loader_cls.return_value = mock_loader
        yield OnboardingSkill()


@pytest.fixture
def empty_context():
    return SessionContext(
        user_id="slack-user-1",
        family_id="",
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.fixture
def slack_message():
    return IncomingMessage(
        id="1",
        user_id="U123ABC",
        chat_id="C456",
        type=MessageType.text,
        text="just tracking expenses",
        channel="slack",
        channel_user_id="U123ABC",
    )


@pytest.fixture
def whatsapp_message():
    return IncomingMessage(
        id="msg-1",
        user_id="+12025551234",
        chat_id="+12025551234",
        type=MessageType.text,
        text="track expenses",
        channel="whatsapp",
        channel_user_id="+12025551234",
    )


@pytest.fixture
def sms_message():
    return IncomingMessage(
        id="SM123",
        user_id="+12025559999",
        chat_id="+12025559999",
        type=MessageType.text,
        text="hi",
        channel="sms",
        channel_user_id="+12025559999",
    )


class TestChannelWelcome:
    """Non-Telegram channels should get language picker first."""

    async def test_slack_first_message_shows_language_picker(
        self, onboarding_skill, slack_message, empty_context
    ):
        intent_data = {"channel": "slack", "channel_user_id": "U123ABC"}
        result = await onboarding_skill.execute(
            slack_message, empty_context, intent_data,
        )
        assert "Welcome!" in result.response_text
        assert len(result.buttons) == 4

    async def test_whatsapp_first_message_shows_language_picker(
        self, onboarding_skill, whatsapp_message, empty_context
    ):
        intent_data = {
            "channel": "whatsapp",
            "channel_user_id": "+12025551234",
        }
        result = await onboarding_skill.execute(
            whatsapp_message, empty_context, intent_data,
        )
        assert "Welcome!" in result.response_text

    async def test_sms_first_message_shows_language_picker(
        self, onboarding_skill, sms_message, empty_context
    ):
        intent_data = {
            "channel": "sms",
            "channel_user_id": "+12025559999",
        }
        result = await onboarding_skill.execute(
            sms_message, empty_context, intent_data,
        )
        assert "Welcome!" in result.response_text


class TestChannelAccountCreation:
    """Non-Telegram channels should use create_family_for_channel."""

    async def test_slack_creates_account_via_channel(
        self, onboarding_skill, slack_message, empty_context
    ):
        intent_data = {
            "onboarding_state": ConversationState.onboarding_awaiting_activity.value,
            "channel": "slack",
            "channel_user_id": "U123ABC",
        }
        mock_family = MagicMock()
        mock_family.invite_code = "ABC12345"
        mock_user = MagicMock()

        with (
            patch("src.skills.onboarding.handler.async_session") as mock_ctx,
            patch(
                "src.skills.onboarding.handler.create_family_for_channel",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ) as mock_create,
            patch(
                "src.skills.onboarding.handler.generate_text",
                new_callable=AsyncMock,
                return_value="household",
            ),
        ):
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await onboarding_skill.execute(
                slack_message, empty_context, intent_data
            )

        assert "All set!" in result.response_text
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["channel"] == "slack"
        assert call_kwargs.kwargs["channel_user_id"] == "U123ABC"

    async def test_whatsapp_join_family_via_channel(
        self, onboarding_skill, empty_context
    ):
        """WhatsApp user joining with invite code should use join_family_for_channel."""
        msg = IncomingMessage(
            id="msg-2",
            user_id="+12025551234",
            chat_id="+12025551234",
            type=MessageType.text,
            text="ABC12345",
            channel="whatsapp",
            channel_user_id="+12025551234",
        )
        intent_data = {
            "onboarding_state": ConversationState.onboarding_awaiting_invite_code.value,
            "channel": "whatsapp",
            "channel_user_id": "+12025551234",
        }
        mock_family = MagicMock()
        mock_family.name = "Test Family"
        mock_user = MagicMock()

        with (
            patch("src.skills.onboarding.handler.async_session") as mock_ctx,
            patch(
                "src.skills.onboarding.handler.join_family_for_channel",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ) as mock_join,
        ):
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await onboarding_skill.execute(msg, empty_context, intent_data)

        assert "Test Family" in result.response_text
        mock_join.assert_called_once()
        call_kwargs = mock_join.call_args
        assert call_kwargs.kwargs["channel"] == "whatsapp"


class TestTelegramUnchanged:
    """Telegram should still use the original create_family path."""

    async def test_telegram_still_uses_create_family(
        self, onboarding_skill, empty_context
    ):
        msg = IncomingMessage(
            id="123",
            user_id="999999999",
            chat_id="999999999",
            type=MessageType.text,
            text="я таксист",
            channel="telegram",
        )
        intent_data = {
            "onboarding_state": ConversationState.onboarding_awaiting_activity.value,
        }
        mock_family = MagicMock()
        mock_family.invite_code = "XYZ789"
        mock_user = MagicMock()

        with (
            patch("src.skills.onboarding.handler.async_session") as mock_ctx,
            patch(
                "src.skills.onboarding.handler.create_family",
                new_callable=AsyncMock,
                return_value=(mock_family, mock_user),
            ) as mock_create,
        ):
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Match profile to skip LLM call
            onboarding_skill._profile_loader.match.return_value = (
                onboarding_skill._profile_loader.get.return_value
            )

            result = await onboarding_skill.execute(msg, empty_context, intent_data)

        assert "All set!" in result.response_text
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["owner_telegram_id"] == 999999999
