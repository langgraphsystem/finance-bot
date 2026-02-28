"""Create Google Sheets skill — creates a new spreadsheet via Composio."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

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
        prompt_result = await require_google_or_prompt(
            context.user_id, service="sheets"
        )
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id, service="sheets")
        if not google:
            return SkillResult(
                response_text="Connection error. Try /connect"
            )

        # Extract title from message
        text = (message.text or "").strip()
        title = _extract_title(text)

        try:
            result = await google.create_spreadsheet(title)
        except Exception as e:
            logger.warning("create_spreadsheet failed: %s", e)
            return SkillResult(
                response_text="Failed to create spreadsheet. Try again."
            )

        spreadsheet_id = (
            result.get("spreadsheetId")
            or result.get("id")
            or ""
        )
        url = result.get(
            "spreadsheetUrl",
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            if spreadsheet_id
            else "",
        )

        return SkillResult(
            response_text=(
                f"\u2705 Created <b>{title}</b>\n"
                f'<a href="{url}">Open in Google Sheets</a>'
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
            rest = text[len(prefix):].strip().strip('"\'')
            if rest:
                return rest
    # If nothing extracted, use the full text or default
    cleaned = text.strip().strip('"\'')
    if len(cleaned) > 3:
        return cleaned
    return "New Spreadsheet"


skill = CreateSheetsSkill()
