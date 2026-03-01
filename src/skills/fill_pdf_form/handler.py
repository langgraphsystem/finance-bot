"""Fill interactive PDF forms using pypdf."""

import asyncio
import io
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You fill interactive PDF forms. Upload a PDF with fillable fields \
and I'll list them or fill them with your data.
Be concise. Use HTML tags for Telegram."""

_STRINGS = {
    "en": {
        "no_file": "Upload a <b>PDF form</b> to fill.",
        "no_fields": "This PDF doesn't have fillable form fields.",
    },
    "ru": {
        "no_file": "Отправьте <b>PDF-форму</b> для заполнения.",
        "no_fields": "В этом PDF нет заполняемых полей.",
    },
    "es": {
        "no_file": "Suba un <b>formulario PDF</b> para completar.",
        "no_fields": "Este PDF no tiene campos rellenables.",
    },
}
register_strings("fill_pdf_form", _STRINGS)


def _read_form_fields(file_bytes: bytes) -> dict[str, str | None]:
    """Read all form fields from a PDF. Returns {field_name: current_value}."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    fields = reader.get_fields()
    if not fields:
        return {}

    result: dict[str, str | None] = {}
    for name, field_obj in fields.items():
        value = field_obj.get("/V")
        if value:
            result[name] = str(value)
        else:
            result[name] = None
    return result


def _fill_form(file_bytes: bytes, values: dict[str, str]) -> bytes:
    """Fill PDF form fields with provided values."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    for page_num in range(len(writer.pages)):
        writer.update_page_form_field_values(writer.pages[page_num], values)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class FillPdfFormSkill:
    name = "fill_pdf_form"
    intents = ["fill_pdf_form"]
    model = "claude-sonnet-4-6"

    @observe(name="fill_pdf_form")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        file_bytes = message.document_bytes
        filename = message.document_file_name or ""

        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_file", lang, "fill_pdf_form"))

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = message.document_mime_type or ""
        if ext != "pdf" and "pdf" not in mime:
            return SkillResult(
                response_text="Please upload a <b>PDF</b> file with fillable form fields."
            )

        # Read form fields
        try:
            fields = await asyncio.to_thread(_read_form_fields, file_bytes)
        except Exception as e:
            logger.exception("Failed to read PDF form fields: %s", e)
            return SkillResult(
                response_text="Failed to read the PDF. Make sure it's a valid PDF file."
            )

        if not fields:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_fields", lang, "fill_pdf_form"))

        # Check if user provided values to fill
        form_values = intent_data.get("form_values") or {}

        if not form_values:
            # List fields for the user
            lines = ["<b>PDF Form Fields</b>\n"]
            for i, (name, current) in enumerate(sorted(fields.items()), 1):
                if current:
                    lines.append(f"{i}. <code>{name}</code> = {current}")
                else:
                    lines.append(f"{i}. <code>{name}</code> <i>(empty)</i>")

            lines.append(
                "\nProvide values to fill. Example:\n"
                "<code>Fill name=John Smith, date=2026-03-01</code>"
            )
            return SkillResult(response_text="\n".join(lines))

        # Fill the form with provided values
        if not isinstance(form_values, dict):
            return SkillResult(
                response_text="Invalid form values. Use: <code>field=value, field2=value2</code>"
            )

        # Only fill fields that exist in the form
        valid_values = {}
        skipped = []
        for key, val in form_values.items():
            if key in fields:
                valid_values[key] = str(val)
            else:
                skipped.append(key)

        if not valid_values:
            return SkillResult(
                response_text="None of the provided fields match the form. "
                f"Available fields: {', '.join(f'<code>{f}</code>' for f in sorted(fields))}"
            )

        try:
            output_bytes = await asyncio.to_thread(_fill_form, file_bytes, valid_values)
        except Exception as e:
            logger.exception("Failed to fill PDF form: %s", e)
            return SkillResult(response_text="Failed to fill the PDF form. Try again.")

        # Build response
        parts = [f"<b>PDF form filled</b> ({len(valid_values)} field(s))"]
        for k, v in valid_values.items():
            parts.append(f"  <code>{k}</code> = {v}")
        if skipped:
            skipped_str = ", ".join(f"<code>{s}</code>" for s in skipped)
            parts.append(f"\nSkipped (not in form): {skipped_str}")

        output_name = filename.replace(".pdf", "_filled.pdf") if filename else "filled_form.pdf"
        return SkillResult(
            response_text="\n".join(parts),
            document=output_bytes,
            document_name=output_name,
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = FillPdfFormSkill()
