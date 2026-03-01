"""Read Google Sheets skill \u2014 fetches data from user's spreadsheets via Composio."""

import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "conn_error": "Connection error. Try /connect",
        "list_failed": ("Could not list spreadsheets. Send me a Google Sheets link."),
        "no_sheets": ("No spreadsheets found. Send me a Google Sheets link to read."),
        "your_sheets": ("Your spreadsheets:\n{items}\n\nSend a link or ID to read data."),
        "read_failed": ("Could not read spreadsheet. Check the link and try again."),
        "empty_sheet": "Spreadsheet is empty or range not found.",
    },
    "ru": {
        "conn_error": "Ошибка подключения. Попробуйте /connect",
        "list_failed": ("Не удалось получить список таблиц. Отправьте ссылку на Google Sheets."),
        "no_sheets": ("Таблицы не найдены. Отправьте ссылку на Google Sheets."),
        "your_sheets": ("Ваши таблицы:\n{items}\n\nОтправьте ссылку или ID для чтения."),
        "read_failed": ("Не удалось прочитать таблицу. Проверьте ссылку и попробуйте снова."),
        "empty_sheet": ("Таблица пуста или диапазон не найден."),
    },
    "es": {
        "conn_error": "Error de conexión. Intente /connect",
        "list_failed": ("No se pudieron listar las hojas. Envíeme un enlace de Google Sheets."),
        "no_sheets": ("No se encontraron hojas. Envíeme un enlace de Google Sheets para leer."),
        "your_sheets": ("Sus hojas de cálculo:\n{items}\n\nEnvíe un enlace o ID para leer datos."),
        "read_failed": ("No se pudo leer la hoja. Verifique el enlace e inténtelo de nuevo."),
        "empty_sheet": ("La hoja está vacía o el rango no se encontró."),
    },
}
register_strings("read_sheets", _STRINGS)

READ_SHEETS_SYSTEM_PROMPT = """\
You format spreadsheet data for Telegram. Use HTML tags (<b>, <i>).
- Show data as bullet points or numbered list, NOT as a table.
- If headers exist, use them as labels: • <b>Name</b>: John, <b>Amount</b>: 150
- Keep it concise — max 20 rows shown, mention total if more.
- Respond in: {language}."""

# Match Google Sheets URL → extract spreadsheet ID
_SHEETS_URL_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)")


def _extract_spreadsheet_id(text: str) -> str | None:
    """Extract spreadsheet ID from URL or return raw ID-like string."""
    m = _SHEETS_URL_RE.search(text)
    if m:
        return m.group(1)
    # If it looks like a raw ID (long alphanumeric)
    for word in text.split():
        if len(word) > 20 and re.match(r"^[a-zA-Z0-9_-]+$", word):
            return word
    return None


class ReadSheetsSkill:
    name = "read_sheets"
    intents = ["read_sheets"]
    model = "claude-sonnet-4-6"

    @observe(name="read_sheets")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        prompt_result = await require_google_or_prompt(context.user_id, service="sheets")
        if prompt_result:
            return prompt_result

        lang = context.language or "en"

        google = await get_google_client(context.user_id, service="sheets")
        if not google:
            return SkillResult(response_text=t_cached(_STRINGS, "conn_error", lang, "read_sheets"))

        text = message.text or ""
        sheet_url = intent_data.get("sheet_url") or ""
        sheet_range = intent_data.get("sheet_range") or "Sheet1"

        spreadsheet_id = _extract_spreadsheet_id(sheet_url or text)

        # If no ID found, list user's spreadsheets
        if not spreadsheet_id:
            try:
                sheets = await google.list_spreadsheets()
            except Exception as e:
                logger.warning("list_spreadsheets failed: %s", e)
                return SkillResult(
                    response_text=t_cached(_STRINGS, "list_failed", lang, "read_sheets")
                )
            if not sheets:
                return SkillResult(
                    response_text=t_cached(_STRINGS, "no_sheets", lang, "read_sheets")
                )
            items = []
            for s in sheets[:10]:
                name = s.get("name", s.get("title", "Untitled"))
                sid = s.get("id", s.get("spreadsheetId", ""))
                items.append(f"\u2022 <b>{name}</b> (ID: <code>{sid}</code>)")
            return SkillResult(
                response_text=t_cached(
                    _STRINGS,
                    "your_sheets",
                    lang,
                    "read_sheets",
                    items="\n".join(items),
                )
            )

        try:
            values = await google.read_values(spreadsheet_id, sheet_range)
        except Exception as e:
            logger.warning("read_values failed: %s", e)
            return SkillResult(response_text=t_cached(_STRINGS, "read_failed", lang, "read_sheets"))

        if not values:
            return SkillResult(response_text=t_cached(_STRINGS, "empty_sheet", lang, "read_sheets"))

        # Format for LLM
        rows_text = "\n".join(" | ".join(str(c) for c in row) for row in values[:30])
        total_note = ""
        if len(values) > 30:
            total_note = f"\n(showing 30 of {len(values)} rows)"

        lang = context.language or "en"
        system = READ_SHEETS_SYSTEM_PROMPT.format(language=lang)
        try:
            result = await generate_text(
                self.model,
                system,
                [{"role": "user", "content": rows_text + total_note}],
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning("read_sheets LLM format failed: %s", e)
            result = rows_text + total_note

        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return READ_SHEETS_SYSTEM_PROMPT.format(language=context.language or "en")


skill = ReadSheetsSkill()
