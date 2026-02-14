"""Tests for Markdown → Telegram HTML converter."""

from src.core.formatting import md_to_telegram_html


def test_bold_double_stars():
    assert md_to_telegram_html("**жирный**") == "<b>жирный</b>"


def test_bold_underscores():
    assert md_to_telegram_html("__жирный__") == "<b>жирный</b>"


def test_italic_single_star():
    assert md_to_telegram_html("*курсив*") == "<i>курсив</i>"


def test_inline_code():
    assert md_to_telegram_html("`код`") == "<code>код</code>"


def test_code_block():
    result = md_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre>" in result
    assert "print" in result


def test_bullet_list_dash():
    result = md_to_telegram_html("- Первый\n- Второй")
    assert "• Первый" in result
    assert "• Второй" in result


def test_bullet_list_star():
    result = md_to_telegram_html("* Первый\n* Второй")
    assert "• Первый" in result


def test_strikethrough():
    assert md_to_telegram_html("~~зачёркнутый~~") == "<s>зачёркнутый</s>"


def test_header():
    result = md_to_telegram_html("### Заголовок")
    assert "<b>Заголовок</b>" in result


def test_html_escaping():
    result = md_to_telegram_html("a < b & c > d")
    assert "&lt;" in result
    assert "&amp;" in result
    assert "&gt;" in result


def test_empty_text():
    assert md_to_telegram_html("") == ""
    assert md_to_telegram_html(None) is None


def test_mixed_formatting():
    text = "**Совет:** используй *правило 50/30/20* для бюджета"
    result = md_to_telegram_html(text)
    assert "<b>" in result
    assert "<i>" in result
    assert "**" not in result
    assert "*правило" not in result


def test_real_llm_response():
    """Test with a real Claude-style response that was getting cut off."""
    text = (
        "Отличный вопрос! 💡 Вот базовая схема:\n\n"
        "**50/30/20 (классический подход):**\n"
        "- **50%** — необходимые расходы\n"
        "- **30%** — желания\n"
        "- **20%** — сбережения"
    )
    result = md_to_telegram_html(text)
    assert "**" not in result
    assert "<b>" in result
    assert "•" in result
