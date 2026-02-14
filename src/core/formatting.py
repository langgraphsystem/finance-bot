"""Convert LLM Markdown output to Telegram-safe HTML."""

import re


def md_to_telegram_html(text: str) -> str:
    """Convert common Markdown patterns to Telegram HTML.

    Handles: **bold**, *italic*, `code`, ```code blocks```,
    - bullet lists, numbered lists.
    Escapes bare HTML characters that Telegram rejects.
    """
    if not text:
        return text

    # Escape bare HTML characters first (but preserve our own tags later)
    text = _escape_html(text)

    # Code blocks (``` ... ```) → <pre>
    text = re.sub(
        r"```(?:\w*)\n?(.*?)```",
        r"<pre>\1</pre>",
        text,
        flags=re.DOTALL,
    )

    # Inline code (`text`) → <code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Markdown bullet lists (- item or * item at line start) → • item
    # Must run BEFORE italic to avoid `* item` being treated as *italic*
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.MULTILINE)

    # Bold (**text** or __text__) → <b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic (*text* or _text_) — but not inside words like file_name
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough (~~text~~) → <s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Headers (### text, ## text, # text) → <b>text</b> + newline
    text = re.sub(r"^#{1,3}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    return text.strip()


def _escape_html(text: str) -> str:
    """Escape HTML special characters that aren't part of our formatting."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text
