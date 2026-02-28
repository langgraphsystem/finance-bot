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


def test_preserve_existing_html_bold():
    """Pre-existing <b> tags should not be escaped."""
    result = md_to_telegram_html("<b>Заметка</b>\n  текст")
    assert "<b>Заметка</b>" in result
    assert "&lt;" not in result


def test_preserve_existing_html_italic():
    """Pre-existing <i> tags should not be escaped."""
    result = md_to_telegram_html("<i>#тег</i>")
    assert "<i>#тег</i>" in result


def test_preserve_mixed_html_and_markdown():
    """Mix of pre-existing HTML and Markdown should work."""
    result = md_to_telegram_html("<b>Заголовок</b>\n**жирный**")
    assert "<b>Заголовок</b>" in result
    assert "<b>жирный</b>" in result


def test_preserve_html_with_bare_angle_brackets():
    """Bare < > should be escaped but <b>, <i> preserved."""
    result = md_to_telegram_html("<b>ok</b> 3 < 5 > 1")
    assert "<b>ok</b>" in result
    assert "&lt;" in result
    assert "&gt;" in result


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


def test_horizontal_rule_removed():
    result = md_to_telegram_html("Above\n---\nBelow")
    assert "---" not in result
    assert "Above" in result
    assert "Below" in result


def test_horizontal_rule_stars():
    result = md_to_telegram_html("Above\n***\nBelow")
    assert "***" not in result


def test_markdown_table_converted():
    text = "| Category | Amount |\n|----------|--------|\n| Food | $50 |\n| Gas | $30 |"
    result = md_to_telegram_html(text)
    assert "|" not in result
    assert "Food" in result
    assert "$50" in result
    assert "•" in result


def test_markdown_table_single_row():
    text = "| Name | Value |\n|------|-------|\n| Test | 100 |"
    result = md_to_telegram_html(text)
    assert "|" not in result
    assert "Test" in result
