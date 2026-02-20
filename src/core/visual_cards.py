"""Visual card generation — LLM-generated HTML → WeasyPrint PNG."""

import logging
import re

from src.core.llm.clients import generate_text
from src.core.observability import observe

logger = logging.getLogger(__name__)

CARD_SYSTEM_PROMPT = """\
You are a visual card designer. Generate a complete HTML document with inline CSS.

Requirements:
- The card must be exactly 800px wide, height auto.
- Use ONLY WeasyPrint-compatible CSS (it does NOT support flexbox or CSS grid).
- Layout with: display: table / table-row / table-cell, float, inline-block, \
position: absolute/relative.
- Fonts: Arial, Helvetica, Georgia, "Times New Roman", monospace.
- Colors, linear-gradient, border-radius, box-shadow, opacity are OK.
- Use visual elements: checkboxes (☐ / ☑), progress bars (div with width%), \
bullet points, emoji/Unicode icons.
- White or light background. Modern, clean design with good spacing.
- All text in the same language as the user's request.
- Return ONLY the raw HTML. No markdown fences, no explanation, no comments \
outside the HTML."""


def _strip_markdown_fences(text: str) -> str:
    """Remove ```html ... ``` fences if present."""
    text = text.strip()
    pattern = r"^```(?:html)?\s*\n?(.*?)\n?```$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


FALLBACK_MODELS = ["claude-sonnet-4-6", "gpt-5.2"]


@observe(name="generate_card_html")
async def generate_card_html(prompt: str) -> str:
    """Generate HTML+CSS for a visual card with model fallback."""
    messages = [{"role": "user", "content": prompt}]
    last_error = None
    for model in FALLBACK_MODELS:
        try:
            raw = await generate_text(
                model, CARD_SYSTEM_PROMPT, messages, max_tokens=4096
            )
            return _strip_markdown_fences(raw)
        except Exception as e:
            logger.warning("generate_card_html failed with %s: %s", model, e)
            last_error = e
    raise last_error  # type: ignore[misc]


def html_to_png(html_content: str, resolution: int = 192) -> bytes:
    """Convert an HTML string to PNG bytes using WeasyPrint.

    Separated into its own function to allow easy mocking in tests
    (WeasyPrint requires system libraries that may not be available in CI).
    """
    from weasyprint import HTML  # lazy import — requires system GTK/Pango libs

    return HTML(string=html_content).write_png(resolution=resolution)
