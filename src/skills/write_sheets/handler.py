"""Write/update Google Sheets skill — updates cells via Composio."""

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
                "which spreadsheet to update."
            )

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
                response_text="Specify what to write and where. "
                "Example: 'write 100 to cell B2'"
            )

        if not values:
            return SkillResult(
                response_text="Could not determine what data to write. "
                "Try: 'write 100 to cell B2 in <link>'"
            )

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

        preview_rows = "\n".join(
            " | ".join(str(c) for c in row) for row in values[:5]
        )
        return SkillResult(
            response_text=(
                f"<b>Write to Google Sheets</b>\n"
                f"Range: <code>{range_}</code>\n"
                f"Data:\n<code>{preview_rows}</code>\n\n"
                "Confirm?"
            ),
            buttons=[
                {"text": "\u2705 Write", "callback": f"confirm_action:{pending_id}"},
                {"text": "\u274c Cancel", "callback": f"cancel_action:{pending_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return EXTRACT_SYSTEM_PROMPT


async def execute_write_sheets(action_data: dict, user_id: str) -> str:
    """Execute confirmed write action."""
    google = await get_google_client(user_id, service="sheets")
    if not google:
        return "Connection error. Try /connect"
    try:
        await google.write_values(
            action_data["spreadsheet_id"],
            action_data["range"],
            action_data["values"],
        )
        return (
            f"\u2705 Written to <code>{action_data['range']}</code>."
        )
    except Exception as e:
        logger.error("write_sheets execute failed: %s", e)
        return "Failed to write to spreadsheet."


skill = WriteSheetsSkill()
