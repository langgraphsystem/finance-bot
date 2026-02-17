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
    """Escape HTML special characters, preserving Telegram-allowed tags.

    Telegram supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href="...">.
    These tags (and their closing variants) are preserved; everything else
    is escaped.
    """
    # Temporarily replace allowed tags with placeholders
    allowed_re = re.compile(
        r"<(/?(?:b|i|u|s|code|pre|a(?:\s[^>]*)?))\s*>",
        re.IGNORECASE,
    )
    placeholders: list[str] = []

    def _save(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00TAG{len(placeholders) - 1}\x00"

    text = allowed_re.sub(_save, text)

    # Escape everything else
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # Restore preserved tags
    for idx, tag in enumerate(placeholders):
        text = text.replace(f"\x00TAG{idx}\x00", tag)

    return text
