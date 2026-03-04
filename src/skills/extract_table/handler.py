"""Extract table skill — extract tables from PDF/images/documents."""

import base64
import csv
import io
import json
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.tools.document_reader import extract_tables

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "no_file": "Send a document or image to extract tables from.",
        "no_tables": "No tables found in this document.",
        "header": "Found {count} table(s)",
    },
    "ru": {
        "no_file": "Отправьте документ или изображение для извлечения таблиц.",
        "no_tables": "В этом документе таблицы не найдены.",
        "header": "Найдено {count} таблиц(ы)",
    },
    "es": {
        "no_file": "Envie un documento o imagen para extraer tablas.",
        "no_tables": "No se encontraron tablas en este documento.",
        "header": "Se encontraron {count} tabla(s)",
    },
}
register_strings("extract_table", _STRINGS)

VISION_TABLE_PROMPT = """Extract ALL tables from this image/document.
Return JSON array of tables:
[{
  "headers": ["col1", "col2", ...],
  "rows": [["val1", "val2", ...], ...]
}]
If no tables found, return [].
Return ONLY valid JSON."""


class ExtractTableSkill:
    name = "extract_table"
    intents = ["extract_table"]
    model = "claude-sonnet-4-6"

    @observe(name="extract_table")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        file_bytes = message.document_bytes or message.photo_bytes
        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_file", lang, "extract_table"))

        filename = message.document_file_name or "document"
        mime_type = message.document_mime_type or "image/jpeg"

        # For photos without document metadata
        if not message.document_bytes and message.photo_bytes:
            filename = "photo.jpg"
            mime_type = "image/jpeg"

        is_image = mime_type.startswith("image/")

        if is_image:
            tables_data = await self._extract_from_image(file_bytes, mime_type)
        else:
            tables = await extract_tables(file_bytes, filename, mime_type)
            tables_data = [{"headers": t.headers, "rows": t.rows, "page": t.page} for t in tables]

        if not tables_data:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_tables", lang, "extract_table"))

        # Format response
        lang = context.language or "en"
        hdr = t_cached(_STRINGS, "header", lang, "extract_table", count=len(tables_data))
        parts = [f"<b>{hdr}</b>\n"]
        csv_parts = []
        for i, table in enumerate(tables_data):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            page = table.get("page")

            header_text = f"<b>Table {i + 1}</b>"
            if page:
                header_text += f" (page {page})"
            parts.append(header_text)

            # Format as text table (compact for Telegram)
            if headers:
                parts.append("<code>" + " | ".join(str(h) for h in headers) + "</code>")
            for row in rows[:10]:
                parts.append("<code>" + " | ".join(str(c) for c in row) + "</code>")
            if len(rows) > 10:
                parts.append(f"<i>...and {len(rows) - 10} more rows</i>")
            parts.append("")

            # Build CSV for download
            buf = io.StringIO()
            writer = csv.writer(buf)
            if headers:
                writer.writerow(headers)
            writer.writerows(rows)
            csv_parts.append(buf.getvalue())

        # Combine all tables into one CSV if just one, else note count
        if len(csv_parts) == 1:
            csv_bytes = csv_parts[0].encode("utf-8")
            csv_name = "table.csv"
        else:
            combined = "\n\n".join(f"--- Table {i + 1} ---\n{c}" for i, c in enumerate(csv_parts))
            csv_bytes = combined.encode("utf-8")
            csv_name = "tables.csv"

        return SkillResult(
            response_text="\n".join(parts),
            document=csv_bytes,
            document_name=csv_name,
        )

    @observe(name="extract_table_vision")
    async def _extract_from_image(self, image_bytes: bytes, mime_type: str) -> list[dict]:
        """Extract tables from images using Gemini 3 Flash vision."""
        client = google_client()
        parts = [
            VISION_TABLE_PROMPT,
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode(),
                }
            },
        ]
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=parts,
            config={"response_mime_type": "application/json"},
        )
        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse table extraction response")
            return []

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Extract tables from documents and images."


skill = ExtractTableSkill()
