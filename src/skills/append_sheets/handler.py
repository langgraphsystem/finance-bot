"""Append rows to Google Sheets skill — adds new rows via Composio."""

import json
import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_SHEETS_URL_RE = re.compile(
    r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)"
)

EXTRACT_SYSTEM_PROMPT = """\
Extract row data to append to a Google Sheet from the user message as JSON:
{
  "range": "Sheet1",
  "values": [["col1", "col2", "col3"]]
}
Multiple rows are allowed: "values": [["a","b"],["c","d"]].
If the user says "add a row with X, Y, Z", return [["X", "Y", "Z"]].
Return ONLY valid JSON, nothing else."""


def _extract_spreadsheet_id(text: str) -> str | None:
    m = _SHEETS_URL_RE.search(text)
    if m:
        return m.group(1)
    for word in text.split():
        if len(word) > 20 and re.match(r"^[a-zA-Z0-9_-]+$", word):
            return word
    return None


class AppendSheetsSkill:
    name = "append_sheets"
    intents = ["append_sheets"]
    model = "claude-sonnet-4-6"

    @observe(name="append_sheets")
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

        text = message.text or ""
        sheet_url = intent_data.get("sheet_url") or ""
        spreadsheet_id = _extract_spreadsheet_id(sheet_url or text)

        if not spreadsheet_id:
            return SkillResult(
                response_text="Send me a Google Sheets link so I know "
                "which spreadsheet to append to."
            )

        # Use LLM to extract row data
        try:
            extracted = await generate_text(
                self.model,
                EXTRACT_SYSTEM_PROMPT,
                [{"role": "user", "content": text}],
                max_tokens=512,
            )
            params = json.loads(extracted)
            range_ = params.get("range", "Sheet1")
            values = params.get("values", [])
        except Exception as e:
            logger.warning("append_sheets extraction failed: %s", e)
            return SkillResult(
                response_text="Specify what rows to add. "
                "Example: 'add row: John, 100, paid'"
            )

        if not values:
            return SkillResult(
                response_text="Could not determine row data. "
                "Try: 'add row: name, amount, status'"
            )

        try:
            await google.append_values(spreadsheet_id, range_, values)
        except Exception as e:
            logger.warning("append_values failed: %s", e)
            return SkillResult(
                response_text="Failed to append rows. "
                "Check the link and try again."
            )

        row_count = len(values)
        return SkillResult(
            response_text=(
                f"\u2705 Added {row_count} row{'s' if row_count > 1 else ''} "
                f"to the spreadsheet."
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return EXTRACT_SYSTEM_PROMPT


skill = AppendSheetsSkill()
