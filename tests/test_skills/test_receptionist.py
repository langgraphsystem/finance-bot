"""Tests for ReceptionistSkill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.specialist import SpecialistConfig, SpecialistService, SpecialistStaff, WorkingHours
from src.gateway.types import IncomingMessage, MessageType
from src.skills.receptionist.handler import skill


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


def _make_specialist() -> SpecialistConfig:
    return SpecialistConfig(
        greeting={"ru": "Здравствуйте!", "en": "Hello!"},
        services=[
            SpecialistService(
                name="Маникюр", duration_min=60, price=2000, currency="RUB",
            ),
            SpecialistService(
                name="Педикюр", duration_min=90, price=2500, currency="RUB",
            ),
        ],
        staff=[
            SpecialistStaff(name="Мастер 1", specialties=["маникюр"]),
        ],
        working_hours=WorkingHours(
            default="10:00-20:00", sat="10:00-18:00", sun="closed",
        ),
        capabilities=["booking", "price_inquiry", "faq", "reminder"],
        faq=[
            {"q": "Сколько стоит маникюр?", "a": "2000 руб."},
            {"q": "Как записаться?", "a": "Напишите удобное время."},
        ],
        system_prompt_extra="Ты — администратор салона.",
    )


def _make_context_with_specialist(specialist=None, language="ru"):
    """Build a SessionContext mock with specialist config."""
    from src.core.context import SessionContext

    profile = MagicMock()
    profile.specialist = specialist or _make_specialist()
    profile.name = "Маникюр / Салон красоты"

    return SessionContext(
        user_id="u1",
        family_id="fam-123",
        role="owner",
        language=language,
        currency="RUB",
        business_type="manicure",
        categories=[],
        merchant_mappings=[],
        profile_config=profile,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_skill_attributes():
    """Skill has required attributes."""
    assert skill.name == "receptionist"
    assert "receptionist" in skill.intents
    assert hasattr(skill, "execute")
    assert hasattr(skill, "get_system_prompt")


async def test_no_specialist_config():
    """Returns fallback message when no specialist config."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id="fam-123", role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    message = _make_message("what services do you offer?")
    result = await skill.execute(message, ctx, {})
    assert "business profile" in result.response_text.lower()


async def test_no_profile_config():
    """Returns fallback when profile_config is None."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id="fam-123", role="owner",
        language="en", currency="USD",
        business_type="manicure", categories=[], merchant_mappings=[],
    )
    message = _make_message("what services?")
    result = await skill.execute(message, ctx, {})
    assert "business profile" in result.response_text.lower()


async def test_services_topic():
    """Topic 'services' shows service list."""
    ctx = _make_context_with_specialist()
    message = _make_message("какие услуги?")
    intent_data = {"receptionist_topic": "services"}

    result = await skill.execute(message, ctx, intent_data)

    assert "Маникюр" in result.response_text
    assert "Педикюр" in result.response_text
    assert "2000" in result.response_text
    assert "2500" in result.response_text
    # Should have booking button
    assert result.buttons is not None
    assert any("booking" in str(b.get("callback_data", "")) for b in result.buttons)


async def test_hours_topic():
    """Topic 'hours' shows working hours."""
    ctx = _make_context_with_specialist()
    message = _make_message("часы работы")
    intent_data = {"receptionist_topic": "hours"}

    result = await skill.execute(message, ctx, intent_data)

    assert "10:00-20:00" in result.response_text
    assert "10:00-18:00" in result.response_text
    # Sunday should show as closed
    assert "закрыто" in result.response_text.lower() or "closed" in result.response_text.lower()


async def test_hours_topic_english():
    """Topic 'hours' in English uses English labels."""
    ctx = _make_context_with_specialist(language="en")
    message = _make_message("what are your hours?")
    intent_data = {"receptionist_topic": "hours"}

    result = await skill.execute(message, ctx, intent_data)

    assert "Working hours" in result.response_text
    assert "10:00-20:00" in result.response_text


async def test_faq_topic():
    """Topic 'faq' shows FAQ entries."""
    ctx = _make_context_with_specialist()
    message = _make_message("FAQ")
    intent_data = {"receptionist_topic": "faq"}

    result = await skill.execute(message, ctx, intent_data)

    assert "Сколько стоит маникюр?" in result.response_text
    assert "2000 руб." in result.response_text


async def test_general_topic_calls_llm():
    """General receptionist question calls LLM with business data."""
    ctx = _make_context_with_specialist()
    message = _make_message("расскажи про ваш салон")
    intent_data = {}

    with patch(
        "src.skills.receptionist.handler.generate_text",
        new_callable=AsyncMock,
        return_value="Наш салон предлагает маникюр и педикюр.",
    ) as mock_llm:
        result = await skill.execute(message, ctx, intent_data)

    mock_llm.assert_called_once()
    assert result.response_text is not None
    # Should have quick action buttons
    assert result.buttons is not None


async def test_services_no_price():
    """Services without price display correctly."""
    specialist = SpecialistConfig(
        services=[
            SpecialistService(name="Free Consultation", duration_min=30),
        ],
        capabilities=["booking"],
    )
    ctx = _make_context_with_specialist(specialist=specialist, language="en")
    message = _make_message("services")
    intent_data = {"receptionist_topic": "services"}

    result = await skill.execute(message, ctx, intent_data)

    assert "Free Consultation" in result.response_text
    assert "30 min" in result.response_text


async def test_empty_services():
    """Empty services list returns appropriate message."""
    specialist = SpecialistConfig(services=[])
    ctx = _make_context_with_specialist(specialist=specialist)
    message = _make_message("услуги")
    intent_data = {"receptionist_topic": "services"}

    result = await skill.execute(message, ctx, intent_data)
    assert "no services" in result.response_text.lower()


async def test_empty_hours():
    """No hours configured returns appropriate message."""
    specialist = SpecialistConfig(working_hours=WorkingHours())
    ctx = _make_context_with_specialist(specialist=specialist)
    message = _make_message("hours")
    intent_data = {"receptionist_topic": "hours"}

    result = await skill.execute(message, ctx, intent_data)
    assert "not configured" in result.response_text.lower()


async def test_empty_faq():
    """No FAQ configured returns appropriate message."""
    specialist = SpecialistConfig(faq=[])
    ctx = _make_context_with_specialist(specialist=specialist)
    message = _make_message("FAQ")
    intent_data = {"receptionist_topic": "faq"}

    result = await skill.execute(message, ctx, intent_data)
    assert "no faq" in result.response_text.lower()


async def test_quick_buttons_include_all_sections():
    """Quick action buttons include services, hours, FAQ, and book."""
    ctx = _make_context_with_specialist()
    message = _make_message("расскажи о салоне")
    intent_data = {}

    with patch(
        "src.skills.receptionist.handler.generate_text",
        new_callable=AsyncMock,
        return_value="Наш салон...",
    ):
        result = await skill.execute(message, ctx, intent_data)

    assert result.buttons is not None
    button_texts = [b["text"] for b in result.buttons]
    assert "Услуги" in button_texts
    assert "Часы работы" in button_texts
    assert "FAQ" in button_texts
    assert "Записать" in button_texts


async def test_get_system_prompt():
    """System prompt includes language."""
    ctx = _make_context_with_specialist()
    prompt = skill.get_system_prompt(ctx)
    assert "ru" in prompt
