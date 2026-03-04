"""Message formatter for scheduled action outputs."""

from __future__ import annotations

import html
from typing import Any
from zoneinfo import ZoneInfo

from src.core.llm.clients import generate_text, get_last_usage
from src.core.models.enums import OutputMode
from src.core.models.scheduled_action import ScheduledAction
from src.core.scheduled_actions.i18n import greeting_key_for_hour, t

_SECTION_ICONS = {
    "calendar": "📅",
    "tasks": "✅",
    "money_summary": "💰",
    "email_highlights": "📧",
    "outstanding": "🔴",
}

_DEFAULT_GREETING_ICON = "☀️"
_DECISION_READY_MODELS = [
    "claude-sonnet-4-6",
    "gpt-5.2",
    "gemini-3-flash-preview",
]


def _extract_items(section_text: str, max_items: int = 5) -> list[str]:
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    if lines and lines[0].endswith(":"):
        lines = lines[1:]

    items: list[str] = []
    for line in lines:
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("• "):
            items.append(line[2:].strip())
        else:
            items.append(line)
        if len(items) >= max_items:
            break
    return items


def _source_label(source: str, language: str) -> str:
    return t(f"source_{source}", language)


def format_compact_message(
    action: ScheduledAction,
    payload: dict[str, str],
    sources_status: dict[str, dict[str, Any]] | None = None,
) -> str:
    language = action.language or "en"

    try:
        if action.next_run_at:
            local_now = action.next_run_at.astimezone(ZoneInfo(action.timezone))
        else:
            local_now = None
    except Exception:
        local_now = None
    if local_now is None:
        from datetime import datetime

        local_now = datetime.now(ZoneInfo("UTC"))

    greeting_key = greeting_key_for_hour(local_now.hour)
    greeting = t(greeting_key, language)
    lines = [f"{_DEFAULT_GREETING_ICON} <b>{greeting}!</b>", ""]

    if action.title:
        lines.append(f"📌 <b>{html.escape(action.title)}</b>")
        lines.append("")

    rendered_any = False
    for source in action.sources or []:
        source_text = payload.get(source, "")
        if not source_text:
            continue
        items = _extract_items(source_text)
        if not items:
            continue
        rendered_any = True
        icon = _SECTION_ICONS.get(source, "📋")
        title = t(f"section_{source}", language)
        lines.append(f"{icon} <b>{title}</b>")
        for item in items:
            lines.append(f"• {html.escape(item)}")
        lines.append("")

    if not rendered_any:
        if action.instruction:
            lines.append(html.escape(action.instruction[:300]))
        else:
            lines.append("• ...")
        lines.append("")

    failed_sources = [
        source
        for source, meta in (sources_status or {}).items()
        if meta.get("status") == "failed"
    ]
    if failed_sources:
        labels = ", ".join(_source_label(source, language) for source in failed_sources)
        lines.append(f"<i>{t('degraded_footer', language, sources=labels)}</i>")
        lines.append("")

    lines.append(t("closing_question", language))
    return "\n".join(lines).strip()


def _build_synthesis_input(payload: dict[str, str], ordered_sources: list[str]) -> str:
    blocks: list[str] = []
    for source in ordered_sources:
        text = (payload.get(source) or "").strip()
        if not text:
            continue
        blocks.append(f"[{source}]\n{text}")
    return "\n\n".join(blocks).strip()


def _decision_ready_system(language: str) -> str:
    return (
        "You generate a scheduled intelligence summary for the user.\n"
        "You receive real data from multiple sources.\n"
        "Synthesize into one scannable message.\n\n"
        "Rules:\n"
        "- Start with a short greeting.\n"
        "- Use section headers with emoji for each source that has data.\n"
        "- Bullet points, short lines, no dense paragraphs.\n"
        "- Skip sections with no data.\n"
        "- End with one actionable question.\n"
        "- Max 12 bullet points total.\n"
        "- Use Telegram HTML tags: <b>, <i>, <code> only.\n"
        "- No Markdown.\n"
        f"- Respond in language: {language}."
    )


async def format_action_message(
    action: ScheduledAction,
    payload: dict[str, str],
    sources_status: dict[str, dict[str, Any]] | None = None,
    *,
    allow_synthesis: bool = False,
) -> tuple[str, str | None, int | None]:
    """Return formatted message text and model marker."""
    text = format_compact_message(action, payload, sources_status=sources_status)
    language = action.language or "en"

    if action.output_mode == OutputMode.decision_ready and allow_synthesis:
        input_text = _build_synthesis_input(payload, action.sources or [])
        if input_text:
            system = _decision_ready_system(language)
            for model in _DECISION_READY_MODELS:
                try:
                    generated = await generate_text(
                        model=model,
                        system=system,
                        prompt=input_text,
                        max_tokens=900,
                        trace_name="scheduled_action_synthesis",
                        trace_user_id=str(action.user_id),
                        trace_intent="scheduled_action",
                    )
                    if generated and generated.strip():
                        usage = get_last_usage()
                        tokens_used = usage.tokens_input + usage.tokens_output
                        return generated.strip(), model, tokens_used
                except Exception:
                    continue

        # Fallback to deterministic output if all synthesis models fail.
        return text, "template_fallback", None
    return text, None, None
