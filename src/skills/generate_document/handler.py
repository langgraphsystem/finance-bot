"""Generate documents from scratch — contracts, NDAs, proposals, price lists."""

import asyncio
import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DOCUMENT_SYSTEM_PROMPT = """\
You are a professional document generator. You create business documents in clean HTML
suitable for PDF conversion via WeasyPrint.

Rules:
- Output ONLY valid HTML with embedded CSS (no external stylesheets)
- Use professional styling: clean fonts (Arial/Helvetica), proper margins, spacing
- Include proper document structure: header, body sections, footer
- Use the company/business info provided to personalize the document
- Add placeholder markers like [CLIENT NAME] or [DATE] only where specific info is missing
- For contracts/NDAs: include standard legal clauses appropriate to the type
- For price lists: use well-formatted tables with clear pricing
- For proposals: include executive summary, scope, timeline, pricing sections
- For letters: use standard business letter format
- Current date should be used where a date is needed
- Respond ONLY with the HTML document, no explanations"""


class GenerateDocumentSkill:
    name = "generate_document"
    intents = ["generate_document"]
    model = "claude-sonnet-4-6"

    @observe(name="generate_document")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        description = (intent_data.get("description") or message.text or "").strip()

        if not description:
            lang = context.language or "en"
            if lang == "ru":
                prompt = (
                    "Какой документ создать? Например:\n"
                    "- <i>NDA для моего бизнеса</i>\n"
                    "- <i>прайс-лист для салона</i>\n"
                    "- <i>шаблон договора на услуги</i>"
                )
            elif lang == "es":
                prompt = (
                    "Que documento debo crear? Por ejemplo:\n"
                    "- <i>NDA para mi negocio</i>\n"
                    "- <i>lista de precios para servicios</i>\n"
                    "- <i>plantilla de contrato de servicios</i>"
                )
            else:
                prompt = (
                    "What document should I create? For example:\n"
                    "- <i>NDA for my plumbing business</i>\n"
                    "- <i>price list for salon services</i>\n"
                    "- <i>service agreement template</i>"
                )
            return SkillResult(response_text=prompt)

        target_format = (intent_data.get("target_format") or "pdf").strip().lower()

        # Gather business profile info for personalization
        company_name = "My Business"
        company_address = ""
        company_phone = ""
        business_type = context.business_type or ""

        profile = context.profile_config
        if profile:
            company_name = getattr(profile, "business_name", None) or company_name
            company_address = getattr(profile, "address", None) or ""
            company_phone = getattr(profile, "phone", None) or ""

        # Build the generation prompt
        from datetime import date

        today = date.today()
        business_context = (
            f"\nBusiness info:\n"
            f"- Company: {company_name}\n"
            f"- Address: {company_address}\n"
            f"- Phone: {company_phone}\n"
            f"- Business type: {business_type}\n"
            f"- Date: {today.strftime('%B %d, %Y')}\n"
            f"- Currency: {context.currency or 'USD'}"
        )

        prompt = (
            f"Generate a professional document: {description}"
            f"{business_context}\n\n"
            "Create the full HTML document with embedded CSS styling."
        )

        try:
            html_content = await generate_text(
                model=self.model,
                system=DOCUMENT_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error("Document HTML generation failed: %s", e)
            return SkillResult(response_text="Failed to generate the document. Try again?")

        # Strip markdown fences if present
        html_content = _strip_markdown_fences(html_content)

        # Ensure it looks like HTML
        if not html_content.strip().startswith("<"):
            html_content = f"<html><body>{html_content}</body></html>"

        # Convert to PDF
        if target_format == "pdf":
            try:
                pdf_bytes = await asyncio.to_thread(_html_to_pdf, html_content)
            except Exception as e:
                logger.error("PDF generation failed: %s", e)
                # Fallback: return as HTML
                filename = _make_filename(description, "html")
                return SkillResult(
                    response_text=(
                        f"<b>{filename}</b>\n<i>PDF generation unavailable, sending as HTML.</i>"
                    ),
                    document=html_content.encode("utf-8"),
                    document_name=filename,
                )

            filename = _make_filename(description, "pdf")
            logger.info(
                "Document generated for user %s: %s (%d bytes)",
                context.user_id,
                filename,
                len(pdf_bytes),
            )
            return SkillResult(
                response_text=f"<b>{filename}</b> — your document is ready.",
                document=pdf_bytes,
                document_name=filename,
            )

        # HTML output
        filename = _make_filename(description, "html")
        return SkillResult(
            response_text=f"<b>{filename}</b> — your document is ready.",
            document=html_content.encode("utf-8"),
            document_name=filename,
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return DOCUMENT_SYSTEM_PROMPT


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes using WeasyPrint. Runs in thread."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def _strip_markdown_fences(text: str) -> str:
    """Remove ```html ... ``` wrappers from LLM output."""
    text = text.strip()
    match = re.match(r"^```\w*\n(.*?)```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _make_filename(description: str, ext: str) -> str:
    """Generate a short filename from the description."""
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", description.lower())
    slug = "_".join(slug.split()[:5])
    if not slug:
        slug = "document"
    if len(slug) > 40:
        slug = slug[:40].rstrip("_")
    return f"{slug}.{ext}"


skill = GenerateDocumentSkill()
