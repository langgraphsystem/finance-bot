"""Sheets sync — live Google Sheets synchronization."""

import logging
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import require_google_or_prompt
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "already_active": (
            "You already have an active <b>{scope}</b> sync.\n"
            '<a href="{url}">Open Sheet</a>\n'
            "Say 'stop sheets sync' to disable."
        ),
        "create_failed": ("Failed to create Google Sheet. Please try again later."),
        "created": (
            "Created a Google Sheet for your <b>{scope}</b>.\n"
            "It syncs automatically every hour.\n"
            '<a href="{url}">Open Sheet</a>'
        ),
        "no_active_stop": "No active syncs to stop.",
        "stopped": "Stopped syncing: <b>{scopes}</b>.",
        "no_active": "No active syncs.",
        "active_header": "<b>Active syncs:</b>",
        "last_sync": "last sync: {time}",
    },
    "ru": {
        "already_active": (
            "У вас уже есть активная синхронизация"
            " <b>{scope}</b>.\n"
            '<a href="{url}">Открыть таблицу</a>\n'
            "Напишите 'отключи sheets sync', чтобы отключить."
        ),
        "create_failed": ("Не удалось создать Google Sheet. Попробуйте позже."),
        "created": (
            "Создана Google Sheet для <b>{scope}</b>.\n"
            "Она синхронизируется автоматически каждый час.\n"
            '<a href="{url}">Открыть таблицу</a>'
        ),
        "no_active_stop": ("Нет активных синхронизаций для отключения."),
        "stopped": "Синхронизация остановлена: <b>{scopes}</b>.",
        "no_active": "Нет активных синхронизаций.",
        "active_header": "<b>Активные синхронизации:</b>",
        "last_sync": "последняя синхронизация: {time}",
    },
    "es": {
        "already_active": (
            "Ya tienes una sincronización <b>{scope}</b>"
            " activa.\n"
            '<a href="{url}">Abrir hoja</a>\n'
            "Di 'detener sheets sync' para desactivar."
        ),
        "create_failed": ("No se pudo crear Google Sheet. Intenta más tarde."),
        "created": (
            "Se creó una Google Sheet para <b>{scope}</b>.\n"
            "Se sincroniza automáticamente cada hora.\n"
            '<a href="{url}">Abrir hoja</a>'
        ),
        "no_active_stop": ("No hay sincronizaciones activas para detener."),
        "stopped": "Sincronización detenida: <b>{scopes}</b>.",
        "no_active": "No hay sincronizaciones activas.",
        "active_header": "<b>Sincronizaciones activas:</b>",
        "last_sync": "última sincronización: {time}",
    },
}

register_strings("sheets_sync", _STRINGS)

_DEFAULT_SYSTEM_PROMPT = """\
You help the user set up and manage a live Google Sheets sync.
Supported scopes: expenses, tasks, contacts.
Sheet updates hourly. Respond in: {language}."""

SHEETS_SYNC_PROMPT = _DEFAULT_SYSTEM_PROMPT


def _detect_scope(intent_data: dict, text: str) -> str:
    """Detect sync scope from intent_data or message keywords."""
    if intent_data.get("sync_scope"):
        return intent_data["sync_scope"]
    if intent_data.get("export_type"):
        return intent_data["export_type"]
    text_lower = (text or "").lower()
    if any(kw in text_lower for kw in ("task", "задач", "todo", "дела")):
        return "tasks"
    if any(kw in text_lower for kw in ("contact", "контакт", "client", "клиент")):
        return "contacts"
    return "expenses"


def _detect_action(text: str) -> str:
    """Detect action from message keywords."""
    text_lower = (text or "").lower()
    if any(kw in text_lower for kw in ("stop", "отключи", "отмени", "disable")):
        return "stop"
    if any(kw in text_lower for kw in ("status", "статус", "когда", "last sync")):
        return "status"
    return "create"


class SheetsSyncSkill:
    name = "sheets_sync"
    intents = ["sheets_sync"]
    model = "claude-haiku-4-5"

    @observe(name="sheets_sync")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # Require Google OAuth
        prompt_result = await require_google_or_prompt(context)
        if prompt_result:
            return SkillResult(response_text=prompt_result)

        action = _detect_action(message.text or "")
        scope = _detect_scope(intent_data, message.text or "")

        if action == "stop":
            return await self._stop_sync(context)
        if action == "status":
            return await self._sync_status(context)
        return await self._create_sync(context, scope)

    async def _create_sync(self, context: SessionContext, scope: str) -> SkillResult:
        from sqlalchemy import text

        from src.core.db import async_session

        # Check for existing active sync
        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, spreadsheet_id FROM sheet_sync_configs
                    WHERE family_id = :fid AND sync_scope = :scope AND is_active = true
                    LIMIT 1
                """),
                {"fid": context.family_id, "scope": scope},
            )
            existing = result.first()

        if existing:
            url = f"https://docs.google.com/spreadsheets/d/{existing.spreadsheet_id}"
            return SkillResult(
                response_text=t_cached(
                    _STRINGS,
                    "already_active",
                    context.language or "en",
                    namespace="sheets_sync",
                    scope=scope,
                    url=url,
                ),
            )

        # Create new spreadsheet via Composio
        try:
            from src.tools.google_workspace import get_composio_client

            client = await get_composio_client(context.user_id)
            resp = await client.execute_action(
                "GOOGLESHEETS_CREATE_SPREADSHEET",
                params={"title": f"Finance Bot — {scope.title()}"},
            )
            spreadsheet_id = resp.get("spreadsheet_id") or resp.get("id", "")
        except Exception as e:
            logger.error("Failed to create spreadsheet: %s", e)
            return SkillResult(
                response_text=t_cached(
                    _STRINGS,
                    "create_failed",
                    context.language or "en",
                    namespace="sheets_sync",
                )
            )

        # Save config
        async with async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO sheet_sync_configs
                    (family_id, spreadsheet_id, sheet_name, sync_scope, is_active)
                    VALUES (:fid, :sid, :name, :scope, true)
                """),
                {
                    "fid": context.family_id,
                    "sid": spreadsheet_id,
                    "name": scope.title(),
                    "scope": scope,
                },
            )
            await session.commit()

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        return SkillResult(
            response_text=t_cached(
                _STRINGS,
                "created",
                context.language or "en",
                namespace="sheets_sync",
                scope=scope,
                url=url,
            ),
        )

    async def _stop_sync(self, context: SessionContext) -> SkillResult:
        from sqlalchemy import text

        from src.core.db import async_session

        async with async_session() as session:
            result = await session.execute(
                text("""
                    UPDATE sheet_sync_configs SET is_active = false
                    WHERE family_id = :fid AND is_active = true
                    RETURNING sync_scope
                """),
                {"fid": context.family_id},
            )
            stopped = result.all()
            await session.commit()

        if not stopped:
            return SkillResult(
                response_text=t_cached(
                    _STRINGS,
                    "no_active_stop",
                    context.language or "en",
                    namespace="sheets_sync",
                )
            )

        scopes = ", ".join(r.sync_scope for r in stopped)
        return SkillResult(
            response_text=t_cached(
                _STRINGS,
                "stopped",
                context.language or "en",
                namespace="sheets_sync",
                scopes=scopes,
            )
        )

    async def _sync_status(self, context: SessionContext) -> SkillResult:
        from sqlalchemy import text

        from src.core.db import async_session

        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT sync_scope, spreadsheet_id, last_synced_at
                    FROM sheet_sync_configs
                    WHERE family_id = :fid AND is_active = true
                """),
                {"fid": context.family_id},
            )
            configs = result.all()

        if not configs:
            return SkillResult(
                response_text=t_cached(
                    _STRINGS,
                    "no_active",
                    context.language or "en",
                    namespace="sheets_sync",
                )
            )

        lines = [
            t_cached(
                _STRINGS,
                "active_header",
                context.language or "en",
                namespace="sheets_sync",
            )
        ]
        for c in configs:
            url = f"https://docs.google.com/spreadsheets/d/{c.spreadsheet_id}"
            line = f'  - {c.sync_scope}: <a href="{url}">Sheet</a>'
            if c.last_synced_at:
                last_sync_text = t_cached(
                    _STRINGS,
                    "last_sync",
                    context.language or "en",
                    namespace="sheets_sync",
                    time=c.last_synced_at.strftime("%Y-%m-%d %H:%M"),
                )
                line += f" ({last_sync_text})"
            lines.append(line)

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language)


skill = SheetsSyncSkill()
