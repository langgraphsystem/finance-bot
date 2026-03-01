"""Fill DOCX/XLSX templates with user data."""

import asyncio
import io
import logging
import re
import uuid as uuid_mod
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.document import Document
from src.core.models.enums import DocumentType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.tools.storage import upload_document

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You fill document templates (DOCX/XLSX) with user data.
Upload a template with placeholders like {{name}}, {{date}}, {{amount}}.
Be concise. Use HTML tags for Telegram."""

# Regex to find Jinja2-style placeholders: {{ variable_name }}
PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

_STRINGS = {
    "en": {
        "no_file": (
            "Please upload a <b>DOCX</b> or <b>XLSX</b> template file.\n"
            "Use placeholders like <code>{{name}}</code>, <code>{{date}}</code>, "
            "<code>{{amount}}</code> in your template."
        ),
    },
    "ru": {
        "no_file": (
            "Загрузите файл-шаблон <b>DOCX</b> или <b>XLSX</b>.\n"
            "Используйте заполнители вроде <code>{{name}}</code>, <code>{{date}}</code>, "
            "<code>{{amount}}</code> в шаблоне."
        ),
    },
    "es": {
        "no_file": (
            "Suba un archivo de plantilla <b>DOCX</b> o <b>XLSX</b>.\n"
            "Use marcadores como <code>{{name}}</code>, <code>{{date}}</code>, "
            "<code>{{amount}}</code> en su plantilla."
        ),
    },
}
register_strings("fill_template", _STRINGS)


def _extract_template_name(text: str, action: str) -> str:
    """Extract template name from phrases like 'save as template Invoice' or
    'delete template Invoice'."""
    patterns = [
        r"(?:save|сохрани)\s+(?:as\s+)?(?:template|шаблон)\s+(.+)",
        r"(?:delete|удали)\s+(?:template|шаблон)\s+(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


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
        text = (message.text or "").strip().lower()

        # Derive extension early so template-save commands can use it
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # --- Template library commands ---

        if "list template" in text or "мои шаблон" in text or "my template" in text:
            return await self._list_templates(context)

        if "delete template" in text or "удали шаблон" in text:
            template_name = intent_data.get("template_name") or _extract_template_name(
                text, "delete"
            )
            return await self._delete_template(context, template_name)

        # Save template: file attached + user asks to save as template
        if (
            file_bytes
            and ("save" in text or "сохрани" in text)
            and ("template" in text or "шаблон" in text)
        ):
            template_name = intent_data.get("template_name") or _extract_template_name(text, "save")
            return await self._save_template(context, file_bytes, filename, ext, template_name)

        # --- Existing fill-template logic ---

        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_file", lang, "fill_template"))

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

    async def _list_templates(self, context: SessionContext) -> SkillResult:
        """List user's saved templates."""
        async with async_session() as session:
            result = await session.execute(
                select(Document)
                .where(Document.family_id == uuid_mod.UUID(context.family_id))
                .where(Document.type == DocumentType.template)
                .order_by(Document.created_at.desc())
                .limit(20)
            )
            templates = result.scalars().all()

        if not templates:
            return SkillResult(
                response_text=(
                    "No saved templates. Upload a DOCX/XLSX and say <b>save as template</b>."
                )
            )

        lines = ["<b>Your templates:</b>"]
        for t in templates:
            name = (t.metadata_extra or {}).get("template_name", t.file_name or "Untitled")
            lines.append(f"  • {name} ({t.file_name})")
        return SkillResult(response_text="\n".join(lines))

    async def _save_template(
        self,
        context: SessionContext,
        file_bytes: bytes,
        filename: str,
        ext: str,
        template_name: str,
    ) -> SkillResult:
        """Save a file as a reusable template."""
        if not template_name:
            template_name = filename.rsplit(".", 1)[0] if filename else "Untitled"

        if ext == "docx":
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        # Upload file bytes to Supabase Storage
        storage_path = await upload_document(
            file_bytes, context.family_id, filename, mime_type=mime, bucket="documents"
        )

        doc = Document(
            family_id=uuid_mod.UUID(context.family_id),
            user_id=uuid_mod.UUID(context.user_id),
            type=DocumentType.template,
            storage_path=storage_path,
            file_name=filename,
            title=template_name,
            mime_type=mime,
            file_size_bytes=len(file_bytes),
            metadata_extra={"template_name": template_name, "format": ext},
        )

        async with async_session() as session:
            session.add(doc)
            await session.commit()

        return SkillResult(
            response_text=(
                f"Template <b>{template_name}</b> saved. Use <b>list templates</b> to see all."
            )
        )

    async def _delete_template(self, context: SessionContext, template_name: str) -> SkillResult:
        """Delete a saved template by name."""
        if not template_name:
            return SkillResult(response_text="Which template? Say <b>delete template {name}</b>.")

        async with async_session() as session:
            result = await session.execute(
                select(Document)
                .where(Document.family_id == uuid_mod.UUID(context.family_id))
                .where(Document.type == DocumentType.template)
                .where(Document.title.ilike(f"%{template_name}%"))
                .limit(1)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                return SkillResult(response_text=f"Template <b>{template_name}</b> not found.")
            await session.delete(doc)
            await session.commit()

        return SkillResult(response_text=f"Template <b>{template_name}</b> deleted.")

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = FillTemplateSkill()
