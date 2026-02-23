"""Google Sheets sync skill — create and manage live spreadsheet sync.

Supports three sync scopes: expenses, tasks, contacts.
Uses Composio Google Sheets integration via OAuth.
Synced hourly via background cron task.
"""

import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.models.enums import TransactionType
from src.core.models.sheet_sync_config import SheetSyncConfig
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You help the user set up and manage a live Google Sheets sync for their data.
Respond in: {language}."""

_VALID_SCOPES = ("expenses", "tasks", "contacts")


def _detect_sync_scope(intent_data: dict[str, Any], message_text: str) -> str:
    """Determine what to sync from intent_data or message text."""
    scope = intent_data.get("sync_scope") or intent_data.get("export_type")
    if scope in _VALID_SCOPES:
        return scope

    lower = (message_text or "").lower()
    if any(w in lower for w in ("task", "задач", "todo", "дела")):
        return "tasks"
    if any(w in lower for w in ("contact", "контакт", "client", "клиент")):
        return "contacts"
    return "expenses"


def _detect_action(intent_data: dict[str, Any], message_text: str) -> str:
    """Detect whether to create, status, or stop sync."""
    lower = (message_text or "").lower()
    if any(w in lower for w in ("stop", "отключи", "отмени", "disable", "удали sync")):
        return "stop"
    if any(w in lower for w in ("status", "статус", "когда", "last sync")):
        return "status"
    return "create"


class SheetsSyncSkill:
    name = "sheets_sync"
    intents = ["sheets_sync"]
    model = "claude-haiku-4-5"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="sheets_sync")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # Check Google OAuth
        auth_prompt = await require_google_or_prompt(context.user_id, service="sheets")
        if auth_prompt:
            return auth_prompt

        action = _detect_action(intent_data, message.text or "")

        if action == "stop":
            return await self._stop_sync(context)
        if action == "status":
            return await self._sync_status(context)
        return await self._create_or_update_sync(context, intent_data, message.text or "")

    async def _create_or_update_sync(
        self,
        context: SessionContext,
        intent_data: dict[str, Any],
        message_text: str,
    ) -> SkillResult:
        """Create a new Google Sheet or update existing sync config."""
        scope = _detect_sync_scope(intent_data, message_text)
        shared_emails = intent_data.get("shared_emails") or []

        # Check for existing active sync with same scope
        async with async_session() as session:
            result = await session.execute(
                select(SheetSyncConfig).where(
                    SheetSyncConfig.family_id == uuid.UUID(context.family_id),
                    SheetSyncConfig.sync_scope == scope,
                    SheetSyncConfig.is_active.is_(True),
                )
            )
            existing = result.scalar_one_or_none()

        if existing:
            return SkillResult(
                response_text=(
                    f"You already have an active {scope} sync.\n"
                    f"Sheet: https://docs.google.com/spreadsheets/d/{existing.spreadsheet_id}\n"
                    f"Say 'stop sheets sync' to disable, or 'sheets sync status' to check."
                ),
            )

        # Create spreadsheet via Google API
        try:
            spreadsheet_id = await self._create_spreadsheet(context, scope)
        except Exception as e:
            logger.error("Failed to create Google Sheet: %s", e, exc_info=True)
            return SkillResult(
                response_text="Failed to create Google Sheet. Please try again later."
            )

        # Save sync config
        async with async_session() as session:
            config = SheetSyncConfig(
                family_id=uuid.UUID(context.family_id),
                spreadsheet_id=spreadsheet_id,
                sheet_name=scope.capitalize(),
                sync_scope=scope,
                shared_emails=shared_emails if shared_emails else None,
            )
            session.add(config)
            await session.commit()

        # Initial data push
        try:
            await self._push_data(context, spreadsheet_id, scope)
        except Exception as e:
            logger.warning("Initial sheet push failed (will retry on cron): %s", e)

        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        response = (
            f"Created a Google Sheet for your {scope}.\n"
            f"It syncs automatically every hour.\n\n"
            f'<a href="{sheet_url}">Open Sheet</a>'
        )
        if shared_emails:
            response += f"\n\nShared with: {', '.join(shared_emails)}"

        return SkillResult(
            response_text=response,
            buttons=[{"text": "Open Sheet", "url": sheet_url}],
        )

    async def _stop_sync(self, context: SessionContext) -> SkillResult:
        """Disable all active syncs for the family."""
        async with async_session() as session:
            result = await session.execute(
                select(SheetSyncConfig).where(
                    SheetSyncConfig.family_id == uuid.UUID(context.family_id),
                    SheetSyncConfig.is_active.is_(True),
                )
            )
            configs = list(result.scalars().all())

            if not configs:
                return SkillResult(response_text="No active sheet syncs to stop.")

            for config in configs:
                config.is_active = False
            await session.commit()

        count = len(configs)
        return SkillResult(
            response_text=f"Stopped {count} sheet sync(s). Say 'sync sheets' anytime to restart."
        )

    async def _sync_status(self, context: SessionContext) -> SkillResult:
        """Show status of active syncs."""
        async with async_session() as session:
            result = await session.execute(
                select(SheetSyncConfig).where(
                    SheetSyncConfig.family_id == uuid.UUID(context.family_id),
                    SheetSyncConfig.is_active.is_(True),
                )
            )
            configs = list(result.scalars().all())

        if not configs:
            return SkillResult(
                response_text="No active sheet syncs. Say 'sync my expenses to sheets' to start."
            )

        lines = ["<b>Active syncs:</b>"]
        for c in configs:
            last = c.last_synced_at.strftime("%Y-%m-%d %H:%M") if c.last_synced_at else "never"
            url = f"https://docs.google.com/spreadsheets/d/{c.spreadsheet_id}"
            lines.append(f'- {c.sync_scope}: <a href="{url}">sheet</a> (last sync: {last})')

        return SkillResult(response_text="\n".join(lines))

    async def _create_spreadsheet(self, context: SessionContext, scope: str) -> str:
        """Create a new Google Spreadsheet via Composio and return its ID."""
        client = await get_google_client(context.user_id)
        if not client:
            raise RuntimeError("No Google client available")

        title = f"Finance Bot — {scope.capitalize()}"
        result = await client.execute_action(
            "GOOGLESHEETS_CREATE_SPREADSHEET",
            params={"title": title},
        )
        spreadsheet_id = result.get("spreadsheetId") or result.get("spreadsheet_id", "")
        if not spreadsheet_id:
            raise RuntimeError(f"No spreadsheet ID in response: {result}")
        return spreadsheet_id

    async def _push_data(self, context: SessionContext, spreadsheet_id: str, scope: str) -> None:
        """Push current data to the spreadsheet."""
        if scope == "expenses":
            rows = await self._fetch_expenses(context)
        elif scope == "tasks":
            rows = await self._fetch_tasks(context)
        elif scope == "contacts":
            rows = await self._fetch_contacts(context)
        else:
            return

        if not rows:
            return

        client = await get_google_client(context.user_id)
        if not client:
            return

        await client.execute_action(
            "GOOGLESHEETS_BATCH_UPDATE",
            params={
                "spreadsheet_id": spreadsheet_id,
                "range": f"{scope.capitalize()}!A1",
                "values": rows,
            },
        )

    async def _fetch_expenses(self, ctx: SessionContext) -> list[list[str]]:
        """Fetch expenses as rows for sheet."""
        today = date.today()
        date_from = today.replace(day=1)

        async with async_session() as session:
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= date_from,
                    Transaction.date <= today,
                    Transaction.type == TransactionType.expense,
                )
                .order_by(Transaction.date.desc())
                .limit(10000)
            )
            transactions = list(result.scalars().all())

        if not transactions:
            return []

        rows: list[list[str]] = [["Date", "Merchant", "Category", "Amount", "Description"]]
        for tx in transactions:
            rows.append(
                [
                    str(tx.date) if tx.date else "",
                    tx.merchant or "",
                    tx.category or "",
                    str(float(tx.amount)),
                    tx.description or "",
                ]
            )
        return rows

    async def _fetch_tasks(self, ctx: SessionContext) -> list[list[str]]:
        """Fetch tasks as rows for sheet."""
        from src.core.models.task import Task

        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                )
                .order_by(Task.created_at.desc())
                .limit(1000)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return []

        rows: list[list[str]] = [["Title", "Status", "Due Date", "Created"]]
        for t in tasks:
            rows.append(
                [
                    t.title or "",
                    t.status.value if hasattr(t.status, "value") else str(t.status),
                    str(t.due_at) if t.due_at else "",
                    str(t.created_at) if t.created_at else "",
                ]
            )
        return rows

    async def _fetch_contacts(self, ctx: SessionContext) -> list[list[str]]:
        """Fetch contacts as rows for sheet."""
        from src.core.models.contact import Contact

        async with async_session() as session:
            result = await session.execute(
                select(Contact)
                .where(Contact.family_id == uuid.UUID(ctx.family_id))
                .order_by(Contact.name.asc())
                .limit(1000)
            )
            contacts = list(result.scalars().all())

        if not contacts:
            return []

        rows: list[list[str]] = [["Name", "Phone", "Email", "Role", "Notes"]]
        for c in contacts:
            rows.append(
                [
                    c.name or "",
                    c.phone or "",
                    c.email or "",
                    c.role or "",
                    c.notes or "",
                ]
            )
        return rows


skill = SheetsSyncSkill()
