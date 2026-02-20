"""Visual card generation — LLM-generated HTML → WeasyPrint PNG."""

import logging
import re

from src.core.llm.clients import generate_text
from src.core.observability import observe

logger = logging.getLogger(__name__)

CARD_SYSTEM_PROMPT = """\
You are a visual card designer. Generate a COMPLETE, CONTENT-RICH HTML document \
with inline CSS that will be rendered to a PNG image via WeasyPrint.

CRITICAL CSS rules (WeasyPrint compatibility):
- Add this EXACT @page rule: @page { size: 800px auto; margin: 0; }
- Body: width: 800px; margin: 0; padding: 20px; box-sizing: border-box;
- NO flexbox, NO CSS grid — they are NOT supported.
- Layout: use display: table/table-row/table-cell, float, inline-block, \
position: absolute/relative, width percentages.
- Fonts: Arial, Helvetica, Georgia, "Times New Roman", monospace.
- Colors, linear-gradient, border-radius, box-shadow, opacity — all OK.

CONTENT rules:
- Fill the ENTIRE card with meaningful content. NEVER leave blank space.
- For trackers (30-day, weekly, monthly): generate ALL days/rows with \
checkboxes ☐, numbered items, dates. Show every single day.
- For lists: generate all items with checkboxes or bullet points.
- Use visual elements: ☐ ☑ checkboxes, progress bars (div width%), \
emoji/Unicode icons, colored badges, section headers.
- Include a clear title/header at the top.
- Modern, clean design. Good spacing but DENSE with information.
- All text in the same language as the user's request.

EXAMPLES of good output:
- 30-day tracker: title + grid/table of 30 numbered days with ☐ checkboxes
- Shopping list: title + categorized items with ☐ checkboxes
- Habit tracker: title + table with days as columns and habits as rows

Return ONLY the raw HTML. No markdown fences, no explanation."""


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
            html = _strip_markdown_fences(raw)
            logger.info(
                "generate_card_html OK with %s (%d chars)", model, len(html)
            )
            logger.debug("Generated HTML:\n%s", html[:2000])
            return html
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
