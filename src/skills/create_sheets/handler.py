"""Create Google Sheets skill \u2014 creates a new spreadsheet via Composio."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "conn_error": "Connection error. Try /connect",
        "create_failed": "Failed to create spreadsheet. Try again.",
        "created": ('\u2705 Created <b>{title}</b>\n<a href="{url}">Open in Google Sheets</a>'),
    },
    "ru": {
        "conn_error": ("Ошибка подключения. Попробуйте /connect"),
        "create_failed": ("Не удалось создать таблицу. Попробуйте снова."),
        "created": ('\u2705 Создана <b>{title}</b>\n<a href="{url}">Открыть в Google Sheets</a>'),
    },
    "es": {
        "conn_error": "Error de conexión. Intente /connect",
        "create_failed": ("No se pudo crear la hoja. Inténtelo de nuevo."),
        "created": ('\u2705 Creada <b>{title}</b>\n<a href="{url}">Abrir en Google Sheets</a>'),
    },
}
register_strings("create_sheets", _STRINGS)

CREATE_SHEETS_SYSTEM_PROMPT = """\
You help create Google Sheets spreadsheets."""


class CreateSheetsSkill:
    name = "create_sheets"
    intents = ["create_sheets"]
    model = "claude-sonnet-4-6"

    @observe(name="create_sheets")
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
            return SkillResult(
                response_text=t_cached(_STRINGS, "conn_error", lang, "create_sheets")
            )

        # Extract title from message
        text = (message.text or "").strip()
        title = _extract_title(text)

        try:
            result = await google.create_spreadsheet(title)
        except Exception as e:
            logger.warning("create_spreadsheet failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "create_failed", lang, "create_sheets")
            )

        spreadsheet_id = result.get("spreadsheetId") or result.get("id") or ""
        url = result.get(
            "spreadsheetUrl",
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else "",
        )

        return SkillResult(
            response_text=t_cached(
                _STRINGS,
                "created",
                lang,
                "create_sheets",
                title=title,
                url=url,
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CREATE_SHEETS_SYSTEM_PROMPT


def _extract_title(text: str) -> str:
    """Extract spreadsheet title from user message."""
    lower = text.lower()
    # Remove common command prefixes
    for prefix in (
        "create spreadsheet",
        "create a spreadsheet",
        "new spreadsheet",
        "create sheet",
        "new sheet",
        "создай таблицу",
        "новая таблица",
        "crear hoja",
        "nueva hoja",
    ):
        if lower.startswith(prefix):
            rest = text[len(prefix) :].strip().strip("\"'")
            if rest:
                return rest
    # If nothing extracted, use the full text or default
    cleaned = text.strip().strip("\"'")
    if len(cleaned) > 3:
        return cleaned
    return "New Spreadsheet"


skill = CreateSheetsSkill()
