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

    # Convert unsupported HTML list tags to bullet points BEFORE escaping
    text = _convert_html_lists(text)

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

    # Horizontal rules (---, ***, ___) → empty line
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Markdown tables → clean text
    text = _convert_tables(text)

    return text.strip()


def fix_unclosed_tags(text: str) -> str:
    """Fix unclosed/unmatched Telegram HTML tags to prevent parse errors.

    Closes unclosed <b>, <i>, <u>, <s>, <code>, <pre> tags
    and removes orphan closing tags.
    """
    if not text:
        return text

    tags = ("b", "i", "u", "s", "code", "pre")
    for tag in tags:
        open_count = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", text, re.IGNORECASE))
        close_count = len(re.findall(rf"</{tag}>", text, re.IGNORECASE))
        if open_count > close_count:
            text += f"</{tag}>" * (open_count - close_count)
        elif close_count > open_count:
            # Remove excess closing tags from the start
            for _ in range(close_count - open_count):
                text = re.sub(rf"</{tag}>", "", text, count=1, flags=re.IGNORECASE)
    return text


def _convert_html_lists(text: str) -> str:
    """Convert HTML list tags to Telegram-safe bullet points.

    <li>item</li>  → • item
    <ul>, </ul>, <ol>, </ol>  → stripped
    """
    # <li>...</li> → • ...
    text = re.sub(
        r"<li[^>]*>(.*?)</li>",
        lambda m: f"• {m.group(1).strip()}",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Bare <li> without closing tag
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    # Strip container tags
    text = re.sub(r"</?(?:ul|ol)[^>]*>", "", text, flags=re.IGNORECASE)
    return text


def _convert_tables(text: str) -> str:
    """Convert Markdown pipe-delimited tables to clean text.

    Turns:
        | Name | Amount |
        |------|--------|
        | Food | $50    |

    Into:
        • Name: Amount
        • Food: $50
    """
    lines = text.split("\n")
    result: list[str] = []
    headers: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        # Detect table row: starts and ends with |
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip separator rows (|---|---|)
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue
            if not in_table:
                # First row = headers
                headers = cells
                in_table = True
            else:
                # Data row: pair with headers
                if headers and len(headers) >= 2 and len(cells) >= 2:
                    parts = [f"{cells[0]}: {', '.join(cells[1:])}"]
                    result.append(f"• {parts[0]}")
                else:
                    result.append(f"• {', '.join(cells)}")
        else:
            if in_table and headers:
                in_table = False
                headers = []
            result.append(line)

    return "\n".join(result)


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
