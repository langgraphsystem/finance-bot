"""Write/update Google Sheets skill \u2014 updates cells via Composio."""

import json
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
        "no_url": ("Send me a Google Sheets link so I know which spreadsheet to update."),
        "extract_failed": ("Specify what to write and where. Example: 'write 100 to cell B2'"),
        "no_data": (
            "Could not determine what data to write. Try: 'write 100 to cell B2 in <link>'"
        ),
        "confirm_header": (
            "<b>Write to Google Sheets</b>\n"
            "Range: <code>{range}</code>\n"
            "Data:\n<code>{preview}</code>\n\n"
            "Confirm?"
        ),
        "btn_write": "\u2705 Write",
        "btn_cancel": "\u274c Cancel",
        "written": "\u2705 Written to <code>{range}</code>.",
        "write_failed": "Failed to write to spreadsheet.",
    },
    "ru": {
        "conn_error": "Ошибка подключения. Попробуйте /connect",
        "no_url": ("Отправьте ссылку на Google Sheets, чтобы я знал какую таблицу обновить."),
        "extract_failed": ("Укажите что и куда записать. Пример: 'запиши 100 в ячейку B2'"),
        "no_data": ("Не удалось определить данные. Попробуйте: 'запиши 100 в B2 в <ссылка>'"),
        "confirm_header": (
            "<b>Запись в Google Sheets</b>\n"
            "Диапазон: <code>{range}</code>\n"
            "Данные:\n<code>{preview}</code>\n\n"
            "Подтвердить?"
        ),
        "btn_write": "\u2705 Записать",
        "btn_cancel": "\u274c Отмена",
        "written": "\u2705 Записано в <code>{range}</code>.",
        "write_failed": ("Не удалось записать в таблицу."),
    },
    "es": {
        "conn_error": "Error de conexión. Intente /connect",
        "no_url": ("Envíeme un enlace de Google Sheets para saber qué hoja actualizar."),
        "extract_failed": ("Especifique qué escribir y dónde. Ejemplo: 'escribe 100 en celda B2'"),
        "no_data": (
            "No se pudo determinar qué datos escribir. Intente: 'escribe 100 en B2 en <enlace>'"
        ),
        "confirm_header": (
            "<b>Escribir en Google Sheets</b>\n"
            "Rango: <code>{range}</code>\n"
            "Datos:\n<code>{preview}</code>\n\n"
            "¿Confirmar?"
        ),
        "btn_write": "\u2705 Escribir",
        "btn_cancel": "\u274c Cancelar",
        "written": "\u2705 Escrito en <code>{range}</code>.",
        "write_failed": "No se pudo escribir en la hoja.",
    },
}
register_strings("write_sheets", _STRINGS)

_SHEETS_URL_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)")

EXTRACT_SYSTEM_PROMPT = """\
Extract spreadsheet write parameters from the user message as JSON:
{
  "range": "Sheet1!A1:B2",
  "values": [["Header1", "Header2"], ["val1", "val2"]]
}
If user specifies a cell like "A1" without a sheet name, use "Sheet1!A1".
Return ONLY valid JSON, nothing else."""


def _extract_spreadsheet_id(text: str) -> str | None:
    m = _SHEETS_URL_RE.search(text)
    if m:
        return m.group(1)
    for word in text.split():
        if len(word) > 20 and re.match(r"^[a-zA-Z0-9_-]+$", word):
            return word
    return None


class WriteSheetsSkill:
    name = "write_sheets"
    intents = ["write_sheets"]
    model = "claude-sonnet-4-6"

    @observe(name="write_sheets")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        prompt_result = await require_google_or_prompt(context.user_id, service="sheets", lang=context.language or "en", chat_id=message.chat_id)
        if prompt_result:
            return prompt_result

        lang = context.language or "en"

        google = await get_google_client(context.user_id, service="sheets")
        if not google:
            return SkillResult(response_text=t_cached(_STRINGS, "conn_error", lang, "write_sheets"))

        text = message.text or ""
        sheet_url = intent_data.get("sheet_url") or ""
        spreadsheet_id = _extract_spreadsheet_id(sheet_url or text)

        if not spreadsheet_id:
            return SkillResult(response_text=t_cached(_STRINGS, "no_url", lang, "write_sheets"))

        # Use LLM to extract range + values from user message
        try:
            extracted = await generate_text(
                self.model,
                EXTRACT_SYSTEM_PROMPT,
                [{"role": "user", "content": text}],
                max_tokens=512,
            )
            params = json.loads(extracted)
            range_ = params.get("range", "Sheet1!A1")
            values = params.get("values", [])
        except Exception as e:
            logger.warning("write_sheets extraction failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "extract_failed", lang, "write_sheets")
            )

        if not values:
            return SkillResult(response_text=t_cached(_STRINGS, "no_data", lang, "write_sheets"))

        # Store as pending action for confirmation
        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="write_sheets",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "spreadsheet_id": spreadsheet_id,
                "range": range_,
                "values": values,
            },
        )

        preview_rows = "\n".join(" | ".join(str(c) for c in row) for row in values[:5])
        btn_write = t_cached(_STRINGS, "btn_write", lang, "write_sheets")
        btn_cancel = t_cached(_STRINGS, "btn_cancel", lang, "write_sheets")
        return SkillResult(
            response_text=t_cached(
                _STRINGS,
                "confirm_header",
                lang,
                "write_sheets",
                range=range_,
                preview=preview_rows,
            ),
            buttons=[
                {"text": btn_write, "callback": f"confirm_action:{pending_id}"},
                {"text": btn_cancel, "callback": f"cancel_action:{pending_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return EXTRACT_SYSTEM_PROMPT


async def execute_write_sheets(action_data: dict, user_id: str, lang: str = "en") -> str:
    """Execute confirmed write action."""
    google = await get_google_client(user_id, service="sheets")
    if not google:
        return t_cached(_STRINGS, "conn_error", lang, "write_sheets")
    try:
        await google.write_values(
            action_data["spreadsheet_id"],
            action_data["range"],
            action_data["values"],
        )
        return t_cached(_STRINGS, "written", lang, "write_sheets", range=action_data["range"])
    except Exception as e:
        logger.error("write_sheets execute failed: %s", e)
        return t_cached(_STRINGS, "write_failed", lang, "write_sheets")


skill = WriteSheetsSkill()
