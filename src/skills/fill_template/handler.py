"""Fill DOCX/XLSX templates with user data."""

import asyncio
import io
import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You fill document templates (DOCX/XLSX) with user data.
Upload a template with placeholders like {{name}}, {{date}}, {{amount}}.
Be concise. Use HTML tags for Telegram."""

# Regex to find Jinja2-style placeholders: {{ variable_name }}
PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _build_context_data(context: SessionContext, intent_data: dict[str, Any]) -> dict[str, str]:
    """Build a dict of available data from user profile and context."""
    data: dict[str, str] = {}

    # Profile fields
    if context.user_profile:
        profile = context.user_profile
        for field in ("name", "first_name", "last_name", "email", "phone", "company", "address"):
            val = getattr(profile, field, None) or profile.__dict__.get(field)
            if val:
                data[field] = str(val)

    # Context fields
    if context.currency:
        data["currency"] = context.currency
    if context.language:
        data["language"] = context.language
    if context.timezone:
        data["timezone"] = context.timezone

    # Any extra values the user passed via intent_data
    extra = intent_data.get("template_values") or {}
    if isinstance(extra, dict):
        data.update({k: str(v) for k, v in extra.items() if v})

    return data


def _fill_docx(file_bytes: bytes, data: dict[str, str]) -> tuple[bytes, list[str], list[str]]:
    """Fill a DOCX template using docxtpl. Returns (output_bytes, filled, unfilled)."""
    from docxtpl import DocxTemplate

    doc = DocxTemplate(io.BytesIO(file_bytes))

    # Get all undeclared variables (placeholders) from the template
    placeholders = doc.get_undeclared_template_variables()

    filled = []
    unfilled = []
    fill_context: dict[str, str] = {}

    for ph in sorted(placeholders):
        key = ph.lower()
        if key in data:
            fill_context[ph] = data[key]
            filled.append(ph)
        else:
            fill_context[ph] = f"[{ph}]"
            unfilled.append(ph)

    doc.render(fill_context)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue(), filled, unfilled


def _fill_xlsx(file_bytes: bytes, data: dict[str, str]) -> tuple[bytes, list[str], list[str]]:
    """Fill an XLSX template by replacing {{placeholder}} patterns in cells."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes))

    filled = []
    unfilled = []
    seen: set[str] = set()

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    matches = PLACEHOLDER_RE.findall(cell.value)
                    for match in matches:
                        key = match.lower()
                        if key not in seen:
                            seen.add(key)
                            if key in data:
                                filled.append(match)
                            else:
                                unfilled.append(match)
                        if key in data:
                            cell.value = cell.value.replace("{{" + match + "}}", data[key])
                            # Also handle spaced variant {{ match }}
                            cell.value = cell.value.replace("{{ " + match + " }}", data[key])

    output = io.BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue(), filled, unfilled


class FillTemplateSkill:
    name = "fill_template"
    intents = ["fill_template"]
    model = "claude-sonnet-4-6"

    @observe(name="fill_template")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        file_bytes = message.document_bytes
        filename = message.document_file_name or ""

        if not file_bytes:
            return SkillResult(
                response_text=(
                    "Please upload a <b>DOCX</b> or <b>XLSX</b> template file.\n"
                    "Use placeholders like <code>{{name}}</code>, <code>{{date}}</code>, "
                    "<code>{{amount}}</code> in your template."
                )
            )

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("docx", "xlsx"):
            return SkillResult(
                response_text=(
                    "Unsupported format. Please upload a <b>.docx</b> or <b>.xlsx</b> template."
                )
            )

        data = _build_context_data(context, intent_data)

        try:
            if ext == "docx":
                output_bytes, filled, unfilled = await asyncio.to_thread(
                    _fill_docx, file_bytes, data
                )
            else:
                output_bytes, filled, unfilled = await asyncio.to_thread(
                    _fill_xlsx, file_bytes, data
                )
        except Exception as e:
            logger.exception("Template fill failed: %s", e)
            return SkillResult(
                response_text="Failed to process the template. Make sure it's a valid file."
            )

        # Build response text
        parts = [f"<b>Template filled</b> ({ext.upper()})"]
        if filled:
            parts.append(f"Filled: {', '.join(f'<code>{f}</code>' for f in filled)}")
        if unfilled:
            parts.append(
                f"Not filled (no data): {', '.join(f'<code>{u}</code>' for u in unfilled)}"
            )
        if not filled and not unfilled:
            parts.append("No placeholders found in the template.")

        output_name = filename.replace(f".{ext}", f"_filled.{ext}")
        return SkillResult(
            response_text="\n".join(parts),
            document=output_bytes,
            document_name=output_name,
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = FillTemplateSkill()
