"""Tests for add_recurring skill."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import PaymentFrequency
from src.gateway.types import IncomingMessage, MessageType
from src.skills.add_recurring.handler import (
    AddRecurringSkill,
    _compute_next_date,
    _resolve_frequency,
)


# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture
def recurring_skill():
    return AddRecurringSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="подписка Netflix 15 каждый месяц",
    )


@pytest.fixture
def sample_ctx():
    cat_id = str(uuid.uuid4())
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[
            {"id": cat_id, "name": "Подписки", "scope": "family", "icon": "📺"},
            {"id": str(uuid.uuid4()), "name": "Продукты", "scope": "family", "icon": "🛒"},
        ],
        merchant_mappings=[],
    )


# ---- Helper function tests --------------------------------------------------


class TestResolveFrequency:
    def test_none_defaults_to_monthly(self):
        assert _resolve_frequency(None) == PaymentFrequency.monthly

    def test_empty_string_defaults_to_monthly(self):
        assert _resolve_frequency("") == PaymentFrequency.monthly

    def test_direct_enum_value(self):
        assert _resolve_frequency("weekly") == PaymentFrequency.weekly
        assert _resolve_frequency("monthly") == PaymentFrequency.monthly
        assert _resolve_frequency("quarterly") == PaymentFrequency.quarterly
        assert _resolve_frequency("yearly") == PaymentFrequency.yearly

    def test_russian_aliases(self):
        assert _resolve_frequency("еженедельно") == PaymentFrequency.weekly
        assert _resolve_frequency("ежемесячно") == PaymentFrequency.monthly
        assert _resolve_frequency("ежеквартально") == PaymentFrequency.quarterly
        assert _resolve_frequency("ежегодно") == PaymentFrequency.yearly

    def test_phrase_aliases(self):
        assert _resolve_frequency("каждую неделю") == PaymentFrequency.weekly
        assert _resolve_frequency("каждый месяц") == PaymentFrequency.monthly
        assert _resolve_frequency("каждый квартал") == PaymentFrequency.quarterly
        assert _resolve_frequency("каждый год") == PaymentFrequency.yearly

    def test_case_insensitive(self):
        assert _resolve_frequency("Weekly") == PaymentFrequency.weekly
        assert _resolve_frequency("MONTHLY") == PaymentFrequency.monthly

    def test_unknown_defaults_to_monthly(self):
        assert _resolve_frequency("biweekly") == PaymentFrequency.monthly


class TestComputeNextDate:
    def test_weekly(self):
        d = date(2025, 6, 1)
        result = _compute_next_date(d, PaymentFrequency.weekly)
        assert result == date(2025, 6, 8)

    def test_monthly(self):
        d = date(2025, 6, 15)
        result = _compute_next_date(d, PaymentFrequency.monthly)
        assert result == date(2025, 7, 15)

    def test_monthly_december_wraps(self):
        d = date(2025, 12, 10)
        result = _compute_next_date(d, PaymentFrequency.monthly)
        assert result == date(2026, 1, 10)

    def test_monthly_clamps_day_to_28(self):
        d = date(2025, 1, 31)
        result = _compute_next_date(d, PaymentFrequency.monthly)
        assert result == date(2025, 2, 28)

    def test_quarterly(self):
        d = date(2025, 3, 15)
        result = _compute_next_date(d, PaymentFrequency.quarterly)
        assert result == date(2025, 6, 15)

    def test_quarterly_year_wrap(self):
        d = date(2025, 11, 10)
        result = _compute_next_date(d, PaymentFrequency.quarterly)
        assert result == date(2026, 2, 10)

    def test_yearly(self):
        d = date(2025, 6, 15)
        result = _compute_next_date(d, PaymentFrequency.yearly)
        assert result == date(2026, 6, 15)


# ---- Skill execution tests --------------------------------------------------


class TestAddRecurringSkill:
    @pytest.mark.asyncio
    async def test_missing_amount_returns_error(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {"description": "Netflix"}
        result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)
        assert "сумму" in result.response_text.lower()

    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {"amount": 15}
        result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)
        assert "название" in result.response_text.lower()

    @pytest.mark.asyncio
    async def test_unknown_category_shows_buttons(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {"amount": 15, "description": "Netflix", "category": "Неизвестная"}
        result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)
        assert "Не нашёл категорию" in result.response_text
        assert result.buttons is not None
        assert len(result.buttons) <= 6

    @pytest.mark.asyncio
    async def test_successful_creation(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {
            "amount": 15,
            "description": "Netflix",
            "category": "Подписки",
        }

        mock_payment = MagicMock()
        mock_payment.id = uuid.uuid4()
        mock_payment.amount = Decimal("15")

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.skills.add_recurring.handler.async_session", return_value=mock_session_ctx), \
             patch("src.skills.add_recurring.handler.log_action", new_callable=AsyncMock):
            result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)

        assert "Регулярный платёж создан" in result.response_text
        assert "Netflix" in result.response_text
        assert "$15" in result.response_text
        assert "ежемесячно" in result.response_text
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_weekly_frequency_in_response(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {
            "amount": 50,
            "description": "Спортзал",
            "category": "Подписки",
            "frequency": "weekly",
        }

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.skills.add_recurring.handler.async_session", return_value=mock_session_ctx), \
             patch("src.skills.add_recurring.handler.log_action", new_callable=AsyncMock):
            result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)

        assert "еженедельно" in result.response_text

    @pytest.mark.asyncio
    async def test_audit_log_called(self, recurring_skill, sample_message, sample_ctx):
        intent_data = {
            "amount": 15,
            "description": "Netflix",
            "category": "Подписки",
        }

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.skills.add_recurring.handler.async_session", return_value=mock_session_ctx), \
             patch("src.skills.add_recurring.handler.log_action", new_callable=AsyncMock) as mock_log:
            await recurring_skill.execute(sample_message, sample_ctx, intent_data)

        mock_log.assert_awaited_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["action"] == "create"
        assert call_kwargs["entity_type"] == "recurring_payment"
        assert call_kwargs["new_data"]["name"] == "Netflix"
        assert call_kwargs["new_data"]["frequency"] == "monthly"

    @pytest.mark.asyncio
    async def test_merchant_used_as_name_fallback(self, recurring_skill, sample_message, sample_ctx):
        """When description is missing, merchant should be used as the name."""
        intent_data = {
            "amount": 10,
            "merchant": "Spotify",
            "category": "Подписки",
        }

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.skills.add_recurring.handler.async_session", return_value=mock_session_ctx), \
             patch("src.skills.add_recurring.handler.log_action", new_callable=AsyncMock):
            result = await recurring_skill.execute(sample_message, sample_ctx, intent_data)

        assert "Spotify" in result.response_text


# ---- Skill attributes -------------------------------------------------------


class TestSkillAttributes:
    def test_skill_name(self, recurring_skill):
        assert recurring_skill.name == "add_recurring"

    def test_skill_intents(self, recurring_skill):
        assert "add_recurring" in recurring_skill.intents

    def test_skill_model(self, recurring_skill):
        assert recurring_skill.model == "claude-haiku-4-5-20251001"

    def test_has_execute_method(self, recurring_skill):
        assert hasattr(recurring_skill, "execute")

    def test_has_get_system_prompt_method(self, recurring_skill):
        assert hasattr(recurring_skill, "get_system_prompt")

    def test_get_system_prompt_contains_categories(self, recurring_skill, sample_ctx):
        prompt = recurring_skill.get_system_prompt(sample_ctx)
        assert "Подписки" in prompt
        assert "Продукты" in prompt
