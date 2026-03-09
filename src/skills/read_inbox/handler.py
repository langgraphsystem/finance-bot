"""Read inbox skill — fetches real Gmail messages and summarizes with LLM."""

import json
import logging
import re
import secrets
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
from src.core.google_auth import get_google_client, parse_email_headers, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

READ_INBOX_SYSTEM_PROMPT = """\
You are an email assistant. Summarize the user's emails.

Rules:
- Filter out promotions, newsletters, and spam.
- List important emails numbered: 1. [Sender] — [Subject summary]
- Group by urgency: needs reply first, then FYI.
- Max 7 items. If more, say "and X more."
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}.
- End with a question in the SAME language asking if user wants to reply."""

DETAIL_SYSTEM_PROMPT = """\
You are an email assistant. The user wants details about a specific email.
Provide a clear summary of this email including:
- Who sent it and when
- Main topic / subject
- Key points or action items
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""

# Redis key for storing last inbox results
INBOX_CACHE_KEY = "inbox_cache:{user_id}"
INBOX_CACHE_TTL = 600  # 10 minutes


def _build_gmail_query(user_text: str) -> str:
    """Build Gmail API query from user's natural language."""
    text = (user_text or "").lower()

    # Sent mail
    if any(kw in text for kw in ["отправил", "отправленн", "sent", "исходящ", "послал", "я писал"]):
        query = "in:sent"
    else:
        query = "is:inbox"

    # Date filters
    if any(kw in text for kw in ["сегодня", "today", "за сегодня"]):
        query += " newer_than:1d"
    elif any(kw in text for kw in ["вчера", "yesterday"]):
        query += " newer_than:2d older_than:1d"
    elif any(kw in text for kw in ["неделю", "week", "за неделю", "эту неделю"]):
        query += " newer_than:7d"
    elif any(kw in text for kw in ["месяц", "month", "за месяц"]):
        query += " newer_than:30d"

    # If no date filter was added and it's inbox, default to unread
    if query == "is:inbox":
        query = "is:unread"

    return query


def _detect_detail_request(user_text: str) -> int | None:
    """Check if user is asking about a specific numbered email. Returns 1-based index or None."""
    text = (user_text or "").lower().strip()
    # Patterns: "о чем 1 письмо", "подробнее о 2", "1 письмо", "расскажи о 3", "#2"
    patterns = [
        r"(?:о\s*ч[её]м|подробнее|расскажи|что\s*в|покажи|детали)\s*(?:о\s*)?(\d+)",
        r"#(\d+)",
        r"^(\d+)\s*(?:письм|email|сообщ)",
        r"(?:письм|email)\s*(?:номер|#|№)?\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            idx = int(match.group(1))
            if 1 <= idx <= 20:
                return idx
    return None


register_strings("read_inbox", {"en": {}, "ru": {}, "es": {}})


class ReadInboxSkill:
    name = "read_inbox"
    intents = ["read_inbox"]
    model = "gpt-5.2"

    @observe(name="read_inbox")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # OAuth check
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text="Не удалось подключиться к Gmail. Попробуйте /connect")

        user_text = message.text or ""

        # Check if user is asking about a specific email from previous listing
        detail_idx = _detect_detail_request(user_text)
        if detail_idx:
            return await self._handle_detail(google, context, detail_idx)

        # Build query from user's message
        gmail_query = _build_gmail_query(user_text)

        # Fetch real emails
        try:
            messages = await google.list_messages(gmail_query, max_results=10)
        except Exception as e:
            logger.warning("Gmail list_messages failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке почты. Попробуйте позже.")

        if not messages:
            return SkillResult(response_text="📭 Новых писем нет.")

        # Parse headers + preserve full message data for attachments
        parsed = []
        for m in messages:
            info = parse_email_headers(m)
            info["message_id"] = m.get("id", "")
            info["attachments"] = m.get("attachments", [])
            parsed.append(info)

        # Cache parsed results for follow-up queries
        await self._cache_inbox(context.user_id, parsed)

        def _att_icon(e: dict) -> str:
            return " 📎" if e.get("attachments") else ""

        email_text = "\n".join(
            (
                f"{i}. From: {e['from']}\n"
                f"   Subject: {e['subject']}{_att_icon(e)}\n"
                f"   {e['snippet'][:100]}"
            )
            for i, e in enumerate(parsed, 1)
        )

        # LLM summarizes real data
        result = await _summarize_with_llm(email_text, context.language or "ru")
        return SkillResult(response_text=result)

    async def _handle_detail(self, google, context: SessionContext, idx: int) -> SkillResult:
        """Show details of a specific email from the cached inbox."""
        try:
            cache_key = INBOX_CACHE_KEY.format(user_id=context.user_id)
            raw = await redis.get(cache_key)
            if not raw:
                return SkillResult(
                    response_text="Кэш писем истёк. Попросите показать почту заново."
                )

            cached = json.loads(raw)
            if idx < 1 or idx > len(cached):
                return SkillResult(
                    response_text=f"Письмо #{idx} не найдено. Доступны #{1}–#{len(cached)}."
                )

            email_info = cached[idx - 1]
            message_id = email_info.get("message_id") or email_info.get("id", "")
            thread_id = email_info.get("thread_id", "")

            # Fetch full thread for richer context
            thread_text = f"From: {email_info['from']}\nSubject: {email_info['subject']}\n"
            thread_text += f"Date: {email_info['date']}\n\n{email_info['snippet']}"

            if thread_id:
                try:
                    thread_msgs = await google.get_thread(thread_id)
                    thread_parsed = [parse_email_headers(m) for m in thread_msgs]
                    thread_text = "\n---\n".join(
                        f"From: {e['from']}\nSubject: {e['subject']}\n"
                        f"Date: {e['date']}\n{e['snippet']}"
                        for e in thread_parsed
                    )
                except Exception as e:
                    logger.warning("Thread fetch failed: %s", e)

            # Mark as read automatically
            if message_id:
                try:
                    await google.mark_as_read(message_id)
                except Exception as e:
                    logger.warning("Mark as read failed: %s", e)

            result = await _detail_with_llm(thread_text, context.language or "ru")

            # Build action buttons
            buttons = []
            if thread_id and message_id:
                # Store reply context in Redis
                reply_key = secrets.token_urlsafe(8)
                await redis.set(
                    f"email_reply:{reply_key}",
                    json.dumps(
                        {
                            "thread_id": thread_id,
                            "to": email_info.get("from", ""),
                            "subject": email_info.get("subject", ""),
                            "user_id": context.user_id,
                        }
                    ),
                    ex=1800,
                )
                buttons.append({"text": "↩️ Ответить", "callback": f"email_reply:{reply_key}"})

            if message_id:
                trash_key = f"{message_id}"
                buttons.append({"text": "🗑 В корзину", "callback": f"email_trash:{trash_key}"})

            # Attachment download buttons
            attachments = email_info.get("attachments", [])
            for att in attachments[:3]:  # max 3 buttons
                filename = att.get("filename", "file")
                att_id = att.get("attachment_id", "")
                if att_id and message_id:
                    att_key = secrets.token_urlsafe(8)
                    await redis.set(
                        f"email_att:{att_key}",
                        json.dumps(
                            {
                                "message_id": message_id,
                                "attachment_id": att_id,
                                "filename": filename,
                                "mime_type": att.get(
                                    "mime_type",
                                    "application/octet-stream",
                                ),
                                "user_id": context.user_id,
                            }
                        ),
                        ex=1800,
                    )
                    buttons.append(
                        {
                            "text": f"📥 {filename[:20]}",
                            "callback": f"email_download:{att_key}",
                        }
                    )

            return SkillResult(response_text=result, buttons=buttons or None)

        except Exception as e:
            logger.warning("Email detail failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке деталей письма.")

    async def _cache_inbox(self, user_id: str, parsed: list[dict]) -> None:
        """Cache parsed inbox results for follow-up queries."""
        try:
            cache_key = INBOX_CACHE_KEY.format(user_id=user_id)
            await redis.set(cache_key, json.dumps(parsed, ensure_ascii=False), ex=INBOX_CACHE_TTL)
        except Exception as e:
            logger.warning("Failed to cache inbox: %s", e)

    def get_system_prompt(self, context: SessionContext) -> str:
        return READ_INBOX_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _summarize_with_llm(email_data: str, language: str) -> str:
    """Summarize real email data using GPT-5.2."""
    system = READ_INBOX_SYSTEM_PROMPT.format(language=language)
    prompt = f"Here are the emails:\n\n{email_data}\n\nSummarize them."
    try:
        return await generate_text(
            "gpt-5.2", system, [{"role": "user", "content": prompt}], max_tokens=1024
        )
    except Exception as e:
        logger.warning("Read inbox LLM failed: %s", e)
        return "Не удалось обработать почту. Попробуйте позже."


async def _detail_with_llm(email_data: str, language: str) -> str:
    """Get details of a specific email using GPT-5.2."""
    system = DETAIL_SYSTEM_PROMPT.format(language=language)
    try:
        return await generate_text(
            "gpt-5.2",
            system,
            [{"role": "user", "content": f"Email details:\n{email_data}"}],
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("Email detail LLM failed: %s", e)
        return "Не удалось получить детали письма."


skill = ReadInboxSkill()
