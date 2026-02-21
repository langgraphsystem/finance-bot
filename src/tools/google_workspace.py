"""Google Workspace API client — Gmail and Calendar via Composio.

Each user is identified by a Composio entity (user_id). Composio manages
OAuth tokens and refresh transparently on their servers.
"""

import logging
from datetime import datetime

from composio import Composio

from src.core.config import settings

logger = logging.getLogger(__name__)


def _composio_client() -> Composio:
    """Return a Composio SDK client (singleton-safe, lightweight)."""
    return Composio(api_key=settings.composio_api_key)


class GoogleWorkspaceClient:
    """Per-user Google API client powered by Composio.

    The ``user_id`` maps to a Composio entity that holds the user's
    Google OAuth connection.
    """

    def __init__(self, user_id: str):
        self._user_id = user_id
        self._composio = _composio_client()

    # ── helpers ─────────────────────────────────────────────────────────

    def _execute(self, slug: str, arguments: dict | None = None) -> dict:
        """Synchronous Composio tool execution (for internal wrapping)."""
        return self._composio.tools.execute(
            slug=slug,
            user_id=self._user_id,
            arguments=arguments or {},
        )

    async def _aexecute(self, slug: str, arguments: dict | None = None) -> dict:
        """Execute a Composio action.

        The Composio Python SDK v3 ``tools.execute`` is synchronous.
        We wrap it in a thread to stay async-compatible.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._execute, slug, arguments or {}
        )

    # ── Gmail ─────────────────────────────────────────────────────────

    async def list_messages(self, query: str = "is:unread", max_results: int = 20) -> list[dict]:
        """List Gmail messages matching a query.

        Returns messages in a format compatible with Gmail API metadata
        (id, threadId, payload.headers).
        """
        result = await self._aexecute(
            "GMAIL_FETCH_EMAILS",
            {
                "query": query,
                "max_results": max_results,
                "user_id": "me",
            },
        )
        data = result.get("data", result)
        messages = data.get("messages", []) if isinstance(data, dict) else []
        # Normalize to Gmail-API-like format for parse_email_headers()
        return [self._normalize_message(m) for m in messages[:max_results]]

    async def get_message(self, message_id: str) -> dict:
        """Get a single Gmail message by ID."""
        result = await self._aexecute(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
            {"message_id": message_id, "user_id": "me", "format": "full"},
        )
        data = result.get("data", result)
        return self._normalize_message(data) if isinstance(data, dict) else data

    async def get_thread(self, thread_id: str) -> list[dict]:
        """Get all messages in a Gmail thread."""
        result = await self._aexecute(
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
            {"thread_id": thread_id, "user_id": "me"},
        )
        data = result.get("data", result)
        messages = data.get("messages", []) if isinstance(data, dict) else []
        return [self._normalize_message(m) for m in messages]

    async def send_message(
        self, *, to: str, subject: str, body: str, is_html: bool = False
    ) -> dict:
        """Send an email via Composio GMAIL_SEND_EMAIL action."""
        result = await self._aexecute(
            "GMAIL_SEND_EMAIL",
            {
                "recipient_email": to,
                "subject": subject,
                "body": body,
                "is_html": is_html,
                "user_id": "me",
            },
        )
        return result.get("data", result)

    async def reply_to_thread(
        self, *, thread_id: str, to: str, body: str, is_html: bool = False
    ) -> dict:
        """Reply to an existing email thread."""
        result = await self._aexecute(
            "GMAIL_REPLY_TO_THREAD",
            {
                "thread_id": thread_id,
                "recipient_email": to,
                "message_body": body,
                "is_html": is_html,
                "user_id": "me",
            },
        )
        return result.get("data", result)

    async def create_draft(
        self, *, to: str, subject: str, body: str, is_html: bool = False
    ) -> dict:
        """Create a Gmail draft."""
        result = await self._aexecute(
            "GMAIL_CREATE_EMAIL_DRAFT",
            {
                "recipient_email": to,
                "subject": subject,
                "body": body,
                "is_html": is_html,
                "user_id": "me",
            },
        )
        return result.get("data", result)

    # ── Calendar ──────────────────────────────────────────────────────

    async def list_events(
        self,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[dict]:
        """List calendar events in a time range."""
        result = await self._aexecute(
            "GOOGLECALENDAR_FIND_EVENT",
            {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "calendar_id": calendar_id,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            },
        )
        data = result.get("data", result)
        if isinstance(data, dict):
            return data.get("items", data.get("events", []))
        return []

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        description: str | None = None,
        calendar_id: str = "primary",
        timezone: str = "America/New_York",
    ) -> dict:
        """Create a new calendar event."""
        params: dict = {
            "summary": title,
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat(),
            "timezone": timezone,
            "calendar_id": calendar_id,
        }
        if location:
            params["location"] = location
        if description:
            params["description"] = description

        result = await self._aexecute("GOOGLECALENDAR_CREATE_EVENT", params)
        return result.get("data", result)

    async def update_event(
        self, event_id: str, calendar_id: str = "primary", **updates: dict
    ) -> dict:
        """Update an existing calendar event."""
        params = {"event_id": event_id, "calendar_id": calendar_id, **updates}
        result = await self._aexecute("GOOGLECALENDAR_PATCH_EVENT", params)
        return result.get("data", result)

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event."""
        await self._aexecute(
            "GOOGLECALENDAR_DELETE_EVENT",
            {"event_id": event_id, "calendar_id": calendar_id},
        )

    async def get_free_busy(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Get free/busy information."""
        result = await self._aexecute(
            "GOOGLECALENDAR_FREE_BUSY_QUERY",
            {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": "primary"}],
            },
        )
        data = result.get("data", result)
        if isinstance(data, dict):
            return data.get("calendars", {}).get("primary", {}).get("busy", [])
        return []

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _normalize_message(msg: dict) -> dict:
        """Normalize a Composio Gmail response into Gmail-API-like format.

        Ensures ``parse_email_headers()`` can extract id, threadId,
        snippet, and payload.headers (from, subject, date).
        """
        if not msg or not isinstance(msg, dict):
            return msg

        # If already in Gmail API format (has payload.headers), return as-is
        if msg.get("payload", {}).get("headers"):
            return msg

        # Build Gmail-API-compatible structure from Composio flat response
        headers = []
        for key in ("from", "to", "subject", "date"):
            value = msg.get(key) or msg.get(key.capitalize(), "")
            if value:
                name = key.capitalize() if key != "from" else "From"
                headers.append({"name": name, "value": value})

        # Try to build a subject header
        if not any(h["name"].lower() == "subject" for h in headers):
            subject = msg.get("subject") or msg.get("Subject", "")
            if subject:
                headers.append({"name": "Subject", "value": subject})

        return {
            "id": msg.get("id", msg.get("messageId", "")),
            "threadId": msg.get("threadId", msg.get("thread_id", "")),
            "snippet": msg.get("snippet", msg.get("body", "")[:200] if msg.get("body") else ""),
            "payload": {"headers": headers},
        }
