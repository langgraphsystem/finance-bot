"""Google Workspace API client — Gmail and Calendar.

Uses aiogoogle for native async access to Google APIs.
Each user has their own OAuth tokens stored encrypted in oauth_tokens table.
"""

import logging
from datetime import datetime

from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ClientCreds, UserCreds

logger = logging.getLogger(__name__)


class GoogleWorkspaceClient:
    """Per-user Google API client. Instantiated with user's OAuth credentials."""

    def __init__(self, user_creds: UserCreds, client_creds: ClientCreds):
        self._user_creds = user_creds
        self._client_creds = client_creds

    # ── Gmail ─────────────────────────────────────────────────────────

    async def list_messages(self, query: str = "is:unread", max_results: int = 20) -> list[dict]:
        """List Gmail messages matching a query."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            gmail = await google.discover("gmail", "v1")
            resp = await google.as_user(
                gmail.users.messages.list(userId="me", q=query, maxResults=max_results)
            )
            messages = resp.get("messages", [])
            results = []
            for msg_ref in messages[:max_results]:
                detail = await google.as_user(
                    gmail.users.messages.get(userId="me", id=msg_ref["id"], format="metadata")
                )
                results.append(detail)
            return results

    async def get_message(self, message_id: str) -> dict:
        """Get a single Gmail message by ID."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            gmail = await google.discover("gmail", "v1")
            return await google.as_user(
                gmail.users.messages.get(userId="me", id=message_id, format="full")
            )

    async def get_thread(self, thread_id: str) -> list[dict]:
        """Get all messages in a Gmail thread."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            gmail = await google.discover("gmail", "v1")
            thread = await google.as_user(
                gmail.users.threads.get(userId="me", id=thread_id, format="metadata")
            )
            return thread.get("messages", [])

    async def send_message(self, raw_message: str) -> dict:
        """Send a raw (base64url-encoded) email message."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            gmail = await google.discover("gmail", "v1")
            return await google.as_user(
                gmail.users.messages.send(userId="me", json={"raw": raw_message})
            )

    async def create_draft(self, raw_message: str) -> dict:
        """Create a Gmail draft."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            gmail = await google.discover("gmail", "v1")
            return await google.as_user(
                gmail.users.drafts.create(userId="me", json={"message": {"raw": raw_message}})
            )

    # ── Calendar ──────────────────────────────────────────────────────

    async def list_events(
        self,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[dict]:
        """List calendar events in a time range."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            calendar = await google.discover("calendar", "v3")
            resp = await google.as_user(
                calendar.events.list(
                    calendarId=calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
            )
            return resp.get("items", [])

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
        event_body: dict = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        if location:
            event_body["location"] = location
        if description:
            event_body["description"] = description

        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            calendar = await google.discover("calendar", "v3")
            return await google.as_user(
                calendar.events.insert(calendarId=calendar_id, json=event_body)
            )

    async def update_event(
        self, event_id: str, calendar_id: str = "primary", **updates: dict
    ) -> dict:
        """Update an existing calendar event."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            calendar = await google.discover("calendar", "v3")
            return await google.as_user(
                calendar.events.patch(calendarId=calendar_id, eventId=event_id, json=updates)
            )

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            calendar = await google.discover("calendar", "v3")
            await google.as_user(calendar.events.delete(calendarId=calendar_id, eventId=event_id))

    async def get_free_busy(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Get free/busy information."""
        async with Aiogoogle(
            user_creds=self._user_creds, client_creds=self._client_creds
        ) as google:
            calendar = await google.discover("calendar", "v3")
            resp = await google.as_user(
                calendar.freebusy.query(
                    json={
                        "timeMin": time_min.isoformat(),
                        "timeMax": time_max.isoformat(),
                        "items": [{"id": "primary"}],
                    }
                )
            )
            return resp.get("calendars", {}).get("primary", {}).get("busy", [])
