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


def html_to_png(html_content: str, scale: int = 3) -> bytes:
    """Convert an HTML string to PNG bytes.

    WeasyPrint >= 53 removed write_png(), so we render to PDF first,
    then convert the first page to PNG via pypdfium2 (PDFium bindings).

    Args:
        html_content: The HTML string to render.
        scale: Rendering scale factor (3 = 216 DPI for crisp Telegram images).
    """
    import io

    import pypdfium2 as pdfium
    from weasyprint import HTML  # lazy import — requires system GTK/Pango libs

    pdf_bytes = HTML(string=html_content).write_pdf()

    pdf = pdfium.PdfDocument(pdf_bytes)
    page = pdf[0]
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()

    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()
