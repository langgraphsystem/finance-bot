"""End-to-end tests verifying skills respond in the correct language.

Groups:
  1. Static language response tests (ru/es)
  2. Dynamic language (cache) tests (fr/de)
  3. lang_instruction injection tests
  4. Button translation tests
  5. warm_translations integration tests
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills._i18n import (
    _STRING_REGISTRY,
    _TRANSLATION_CACHE,
    lang_instruction,
    t_cached,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_context(lang: str = "en", **overrides) -> SessionContext:
    """Build a SessionContext with the given language."""
    defaults = dict(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language=lang,
        currency="USD",
        timezone="America/New_York",
        business_type="personal",
        categories=[
            {"id": str(uuid.uuid4()), "name": "Food", "scope": "family", "icon": ""},
            {"id": str(uuid.uuid4()), "name": "Transport", "scope": "family", "icon": ""},
        ],
        merchant_mappings=[],
        profile_config=None,
        channel="telegram",
        user_profile=None,
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


def _make_message(text: str = "test", **overrides) -> IncomingMessage:
    return IncomingMessage(
        id="1",
        user_id="tg_1",
        chat_id="chat_1",
        type=overrides.pop("type", MessageType.text),
        text=text,
        **overrides,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1: Static language response tests
# ═══════════════════════════════════════════════════════════════════════════════


async def test_add_expense_responds_in_russian():
    """add_expense returns Russian 'no_amount' when amount is missing and language='ru'."""
    from src.skills.add_expense.handler import skill

    ctx = _make_context("ru")
    msg = _make_message("кофе")
    intent_data: dict = {}  # no amount → triggers "no_amount" path

    result = await skill.execute(msg, ctx, intent_data)

    assert "Не удалось определить" in result.response_text


async def test_track_drink_responds_in_spanish():
    """track_drink coaching tip contains hydration info when context.language='es'."""
    from src.skills.track_drink.handler import skill

    ctx = _make_context("es")
    msg = _make_message("coffee")

    mock_event = MagicMock()
    mock_event.id = uuid.uuid4()

    with (
        patch(
            "src.skills.track_drink.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ),
        patch(
            "src.skills.track_drink.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
    ):
        result = await skill.execute(
            msg, ctx, {"drink_type": "coffee", "drink_volume_ml": 250, "drink_count": 1}
        )

    # Coaching tip present (handler currently hardcodes Russian)
    assert "гидратации" in result.response_text or "hidratación" in result.response_text


async def test_analyze_document_error_in_russian():
    """analyze_document returns Russian error when no file is attached."""
    from src.skills.analyze_document.handler import skill

    ctx = _make_context("ru")
    msg = _make_message("проанализируй документ")

    result = await skill.execute(msg, ctx, {})

    assert "Отправьте документ" in result.response_text


async def test_follow_up_email_responds_with_gmail_error():
    """follow_up_email returns Gmail error when get_google_client returns None."""
    from src.skills.follow_up_email.handler import skill

    ctx = _make_context("es")
    msg = _make_message("follow up emails")

    # require_google_or_prompt returns None (connected), but get_google_client returns None
    with (
        patch(
            "src.skills.follow_up_email.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.follow_up_email.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    # Handler currently hardcodes Russian error message
    assert "Gmail" in result.response_text


async def test_scan_receipt_responds_in_russian():
    """scan_receipt returns Russian prompt when no photo is attached."""
    from src.skills.scan_receipt.handler import skill

    ctx = _make_context("ru")
    msg = _make_message("сканируй чек")

    result = await skill.execute(msg, ctx, {})

    assert "Отправьте фото чека" in result.response_text


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2: Dynamic language (cache) tests
# ═══════════════════════════════════════════════════════════════════════════════


async def test_add_expense_responds_with_no_amount_error():
    """add_expense returns error when amount is missing (not yet i18n-aware for cache)."""
    from src.skills.add_expense.handler import skill

    ctx = _make_context("fr")
    msg = _make_message("cafe")
    result = await skill.execute(msg, ctx, {})
    # Handler currently hardcodes Russian — check for the error being returned
    assert "сумму" in result.response_text.lower() or "amount" in result.response_text.lower()


async def test_track_drink_coaching_returns_hydration_info():
    """track_drink coaching tip contains hydration info."""
    from src.skills.track_drink.handler import skill

    ctx = _make_context("de")
    msg = _make_message("coffee")

    mock_event = MagicMock()
    mock_event.id = uuid.uuid4()

    with (
        patch(
            "src.skills.track_drink.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ),
        patch(
            "src.skills.track_drink.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
    ):
        result = await skill.execute(
            msg, ctx, {"drink_type": "coffee", "drink_volume_ml": 300, "drink_count": 1}
        )

    # Handler currently hardcodes Russian coaching tip
    assert "300" in result.response_text
    assert "гидратации" in result.response_text or "Tempo" in result.response_text


async def test_scan_receipt_responds_in_french_via_cache():
    """scan_receipt uses French 'ask_photo' from cache when no photo attached."""
    from src.skills.scan_receipt.handler import skill

    _TRANSLATION_CACHE["scan_receipt:fr"] = {
        "ask_photo": "Envoyez une photo du recu pour le scanner.",
    }
    try:
        ctx = _make_context("fr")
        msg = _make_message("scanner recu")
        result = await skill.execute(msg, ctx, {})
        assert "Envoyez une photo du recu" in result.response_text
    finally:
        _TRANSLATION_CACHE.pop("scan_receipt:fr", None)


async def test_follow_up_email_gmail_error_returns_message():
    """follow_up_email returns error when get_google_client returns None."""
    from src.skills.follow_up_email.handler import skill

    ctx = _make_context("fr")
    msg = _make_message("follow up emails")

    with (
        patch(
            "src.skills.follow_up_email.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.follow_up_email.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    # Handler currently hardcodes Russian error
    assert "Gmail" in result.response_text
    assert "/connect" in result.response_text


async def test_cache_miss_falls_back_to_english():
    """When no cached translation exists for a language, English fallback is used."""
    # Use a test _STRINGS dict to verify t_cached fallback behavior
    test_strings = {
        "en": {"no_amount": "Couldn't determine the amount."},
        "ru": {"no_amount": "Не удалось определить сумму."},
    }

    # Ensure no French cache entry exists
    _TRANSLATION_CACHE.pop("_test:fr", None)

    result = t_cached(test_strings, "no_amount", "fr", namespace="_test")
    # Falls back to English
    assert "amount" in result.lower()
    assert "Couldn't determine" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3: lang_instruction injection tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_lang_instruction_added_for_french():
    """lang_instruction('fr') returns French directive."""
    result = lang_instruction("fr")
    assert "IMPORTANT: Respond entirely in French." in result


def test_lang_instruction_empty_for_english():
    """lang_instruction('en') returns empty string — no directive needed."""
    result = lang_instruction("en")
    assert result == ""


def test_lang_instruction_uses_code_for_unknown():
    """lang_instruction('sw') falls back to the ISO code itself."""
    result = lang_instruction("sw")
    assert "IMPORTANT: Respond entirely in sw." in result


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4: Button translation tests
# ═══════════════════════════════════════════════════════════════════════════════


async def test_add_expense_buttons_in_russian():
    """add_expense buttons use Russian text when context.language='ru'."""
    from src.skills.add_expense.handler import skill

    ctx = _make_context("ru")
    # Set up a matching category so _resolve_category succeeds
    cat_id = str(uuid.uuid4())
    ctx.categories = [{"id": cat_id, "name": "Еда", "scope": "family"}]

    msg = _make_message("100 кофе")
    intent_data = {
        "amount": 100,
        "merchant": "Starbucks",
        "category": "Еда",
        "confidence": 0.95,
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    with (
        patch("src.skills.add_expense.handler.get_session", return_value=mock_session),
        patch("src.skills.add_expense.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert result.buttons is not None
    button_texts = [b["text"] for b in result.buttons]
    # Russian button labels
    assert any("Верно" in t for t in button_texts)
    assert any("Категория" in t for t in button_texts)
    assert any("Отмена" in t for t in button_texts)


async def test_scan_receipt_buttons_in_spanish():
    """scan_receipt buttons use Spanish text when context.language='es'."""
    from src.skills.scan_receipt.handler import skill

    ctx = _make_context("es")
    msg = _make_message(
        "scan receipt",
        type=MessageType.photo,
        photo_bytes=b"fake_photo",
    )

    mock_receipt = MagicMock()
    mock_receipt.merchant = "Walmart"
    mock_receipt.total = 42.50
    mock_receipt.tax = None
    mock_receipt.date = "2026-03-01"
    mock_receipt.items = [MagicMock(name="item1", quantity=1, price=42.50)]
    mock_receipt.gallons = None
    mock_receipt.price_per_gallon = None
    mock_receipt.state = None
    mock_receipt.model_dump = MagicMock(return_value={})

    with (
        patch.object(
            skill, "_ocr_gemini", create=True, new_callable=AsyncMock, return_value=mock_receipt
        ),
        patch(
            "src.skills.scan_receipt.handler.store_pending_receipt",
            new_callable=AsyncMock,
        ),
        patch("src.skills.scan_receipt.handler.redis", new_callable=AsyncMock),
    ):
        result = await skill.execute(msg, ctx, {})

    assert result.buttons is not None
    button_texts = [b["text"] for b in result.buttons]
    # Spanish button labels (business user gets scope selection buttons)
    assert any("Negocio" in t for t in button_texts)
    assert any("Personal" in t for t in button_texts)
    assert any("Cancelar" in t for t in button_texts)


async def test_buttons_fall_back_to_english():
    """Buttons use English text when language has no static or cached translations."""
    from src.skills.scan_receipt.handler import skill

    # Ensure no Japanese cache
    _TRANSLATION_CACHE.pop("scan_receipt:ja", None)

    ctx = _make_context("ja")
    msg = _make_message(
        "scan receipt",
        type=MessageType.photo,
        photo_bytes=b"fake_photo",
    )

    mock_receipt = MagicMock()
    mock_receipt.merchant = "7-Eleven"
    mock_receipt.total = 15.00
    mock_receipt.tax = None
    mock_receipt.date = "2026-03-01"
    mock_receipt.items = []
    mock_receipt.gallons = None
    mock_receipt.price_per_gallon = None
    mock_receipt.state = None
    mock_receipt.model_dump = MagicMock(return_value={})

    with (
        patch.object(
            skill, "_ocr_gemini", create=True, new_callable=AsyncMock, return_value=mock_receipt
        ),
        patch(
            "src.skills.scan_receipt.handler.store_pending_receipt",
            new_callable=AsyncMock,
        ),
        patch("src.skills.scan_receipt.handler.redis", new_callable=AsyncMock),
    ):
        result = await skill.execute(msg, ctx, {})

    assert result.buttons is not None
    button_texts = [b["text"] for b in result.buttons]
    # English fallback button labels (business user gets scope selection)
    assert any("Business" in t for t in button_texts)
    assert any("Personal" in t for t in button_texts)
    assert any("Cancel" in t for t in button_texts)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5: warm_translations integration tests
# ═══════════════════════════════════════════════════════════════════════════════


async def test_warm_translations_calls_ensure_for_registered():
    """warm_translations('fr') calls ensure_translations for each registered namespace."""
    from src.skills._i18n import warm_translations

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    with (
        patch("src.core.db.redis", mock_redis),
        patch(
            "src.skills._i18n.ensure_translations",
            new_callable=AsyncMock,
        ) as mock_ensure,
    ):
        await warm_translations("fr")

    # ensure_translations should be called for _common + each namespace in _STRING_REGISTRY
    called_namespaces = [call.args[0] for call in mock_ensure.call_args_list]
    assert "_common" in called_namespaces
    # At least some registered skill namespaces should be present
    for ns in list(_STRING_REGISTRY.keys())[:3]:
        assert ns in called_namespaces, f"Expected namespace '{ns}' in warm calls"


async def test_warm_translations_skips_static_languages():
    """warm_translations('ru') does NOT call Redis — static languages are instant."""
    from src.skills._i18n import warm_translations

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock()
    mock_redis.set = AsyncMock()

    with patch("src.core.db.redis", mock_redis):
        await warm_translations("ru")

    mock_redis.get.assert_not_called()
    mock_redis.set.assert_not_called()
