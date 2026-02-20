"""Tests for generate_card skill."""

from unittest.mock import AsyncMock, patch

from src.skills.generate_card.handler import GenerateCardSkill

SAMPLE_HTML = """<!DOCTYPE html>
<html><head><style>body{width:800px;font-family:Arial;}</style></head>
<body><h1>30-Day Reading Tracker</h1></body></html>"""


def _make_message(text="трекер чтения на 30 дней"):
    from src.gateway.types import IncomingMessage, MessageType

    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


def _make_context():
    from src.core.context import SessionContext

    return SessionContext(
        user_id="test-uid",
        family_id="test-fid",
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_execute_generates_png():
    skill = GenerateCardSkill()
    msg = _make_message()
    ctx = _make_context()

    with (
        patch(
            "src.core.visual_cards.generate_card_html",
            new_callable=AsyncMock,
            return_value=SAMPLE_HTML,
        ),
        patch(
            "src.core.visual_cards.html_to_png",
            return_value=b"fake-png-bytes",
        ),
    ):
        result = await skill.execute(msg, ctx, {"card_topic": "трекер чтения на 30 дней"})

    assert result.photo_bytes == b"fake-png-bytes"
    assert result.response_text == ""


async def test_execute_uses_message_text_as_fallback():
    skill = GenerateCardSkill()
    msg = _make_message("habit tracker")
    ctx = _make_context()

    with (
        patch(
            "src.core.visual_cards.generate_card_html",
            new_callable=AsyncMock,
            return_value=SAMPLE_HTML,
        ) as mock_gen,
        patch(
            "src.core.visual_cards.html_to_png",
            return_value=b"png",
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    # card_topic was empty, so message.text should be used
    mock_gen.assert_called_once_with("habit tracker")
    assert result.photo_bytes == b"png"


async def test_execute_empty_topic_returns_help():
    skill = GenerateCardSkill()
    msg = _make_message("")
    ctx = _make_context()

    result = await skill.execute(msg, ctx, {"card_topic": ""})

    assert "Опишите" in result.response_text
    assert result.photo_bytes is None


async def test_strip_markdown_fences():
    from src.core.visual_cards import _strip_markdown_fences

    fenced = "```html\n<html><body>Hello</body></html>\n```"
    assert _strip_markdown_fences(fenced) == "<html><body>Hello</body></html>"

    # Without fences — returns as-is
    plain = "<html><body>Hello</body></html>"
    assert _strip_markdown_fences(plain) == plain

    # With just ``` (no lang hint)
    fenced_no_lang = "```\n<div>Test</div>\n```"
    assert _strip_markdown_fences(fenced_no_lang) == "<div>Test</div>"


async def test_generate_card_html_calls_generate_text():
    with patch(
        "src.core.visual_cards.generate_text",
        new_callable=AsyncMock,
        return_value="```html\n<div>Card</div>\n```",
    ) as mock_gen:
        from src.core.visual_cards import generate_card_html

        result = await generate_card_html("shopping list card")

    mock_gen.assert_called_once()
    assert result == "<div>Card</div>"


async def test_skill_attributes():
    skill = GenerateCardSkill()
    assert skill.name == "generate_card"
    assert skill.intents == ["generate_card"]
    assert skill.model == "claude-sonnet-4-6"


async def test_get_system_prompt():
    skill = GenerateCardSkill()
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "карточки" in prompt
