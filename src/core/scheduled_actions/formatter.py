"""Message formatter for scheduled action outputs."""

from __future__ import annotations

import html
import re
from datetime import datetime
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
    "gemini-3.1-flash-lite-preview",
]
_TOP_PRIORITY_HEADERS = {
    "en": "🎯 <b>Top priorities</b>",
    "ru": "🎯 <b>Топ-приоритеты</b>",
    "es": "🎯 <b>Prioridades principales</b>",
}
_RECOMMENDED_HEADERS = {
    "en": "➡️ <b>Recommended next action</b>",
    "ru": "➡️ <b>Рекомендуемое следующее действие</b>",
    "es": "➡️ <b>Siguiente acción recomendada</b>",
}
_RECOMMENDED_DEFAULT = {
    "en": "• Start with the highest-urgency item now.",
    "ru": "• Начните с самого срочного пункта прямо сейчас.",
    "es": "• Empieza ahora con la tarea de mayor urgencia.",
}
_BUDGET_USAGE_RE = re.compile(
    r"budget usage\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*%",
    flags=re.IGNORECASE,
)
_YESTERDAY_SPENT_RE = re.compile(
    r"yesterday\s*:\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    flags=re.IGNORECASE,
)
_MONTH_SPENT_RE = re.compile(
    r"this month\s*:\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    flags=re.IGNORECASE,
)


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


def _render_budget_bar(ratio: float) -> str:
    """Render a progress bar: █████░░░░░ 52%."""
    width = 10
    filled = max(0, min(width, int(round(ratio * width))))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"<code>{bar}</code> {ratio:.0%}"


def _parse_money_number(raw: str) -> float | None:
    normalized = raw.strip().replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _format_finance_section(items: list[str], language: str) -> list[str]:
    """Epic G2: Format finance section with budget progress bar and risk icons."""
    lines: list[str] = []
    usage_ratio = 0.0
    has_budget = False
    yesterday_spent: float | None = None
    month_spent: float | None = None

    for item in items:
        budget_match = _BUDGET_USAGE_RE.search(item)
        if budget_match:
            ratio_raw = budget_match.group(1).replace(",", ".")
            parsed_ratio = _parse_money_number(ratio_raw)
            if parsed_ratio is not None:
                usage_ratio = parsed_ratio / 100.0
                has_budget = True
                continue

        yesterday_match = _YESTERDAY_SPENT_RE.search(item)
        if yesterday_match:
            yesterday_spent = _parse_money_number(yesterday_match.group(1))

        month_match = _MONTH_SPENT_RE.search(item)
        if month_match:
            month_spent = _parse_money_number(month_match.group(1))

        lines.append(f"• {html.escape(item)}")

    if has_budget:
        icon = "🟢"
        if usage_ratio >= 1.0:
            icon = "🔴"
        elif usage_ratio >= 0.8:
            icon = "🟡"

        lines.append(f"• {icon} {t('budget_usage', language)}")
        lines.append(f"  {_render_budget_bar(usage_ratio)}")
        if yesterday_spent is not None and month_spent is not None:
            avg_daily = month_spent / max(datetime.now().day, 1)
            trend_up = yesterday_spent >= avg_daily
            trend_icon = "📈" if trend_up else "📉"
            trend_key = "budget_trend_up" if trend_up else "budget_trend_down"
            lines.append(f"• {trend_icon} {t(trend_key, language)}")

    return lines


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
        local_now = datetime.now(ZoneInfo("UTC"))

    greeting_key = greeting_key_for_hour(local_now.hour)
    greeting = t(greeting_key, language)
    lines = [f"{_DEFAULT_GREETING_ICON} <b>{greeting}!</b>", ""]

    if action.title:
        badge = ""
        if getattr(action, "action_kind", "digest") == "outcome":
            badge = f" [ 🔄 {t('outcome_badge', language)} ]"
        lines.append(f"📌 <b>{html.escape(action.title)}</b>{badge}")
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

        if source == "money_summary":
            lines.extend(_format_finance_section(items, language))
        else:
            for item in items:
                lines.append(f"• {html.escape(item)}")
        lines.append("")

    if not rendered_any:
        if action.instruction:
            lines.append(html.escape(action.instruction[:300]))
        else:
            lines.append(f"• {t('empty_payload_fallback', language)}")
        lines.append("")

    status_map = sources_status or {}
    total_sources = len(action.sources or [])
    failed_sources = [
        source
        for source, meta in status_map.items()
        if meta.get("status") == "failed"
    ]
    if failed_sources:
        labels = ", ".join(_source_label(source, language) for source in failed_sources)
        lines.append(f"<i>{t('degraded_footer', language, sources=labels)}</i>")
        lines.append("")

    if total_sources > 0:
        ok_count = total_sources - len(failed_sources)
        try:
            freshness_time = local_now.strftime("%H:%M")
        except Exception:
            freshness_time = "—"
        footer = t(
            "trust_footer", language,
            ok=ok_count, total=total_sources, time=freshness_time,
        )
        lines.append(f"<i>{footer}</i>")
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
        "Synthesize into one scannable, decision-ready message.\n\n"
        "Rules:\n"
        "- Start with a short greeting.\n"
        "- First section MUST be top priorities, ranked by urgency.\n"
        "- Rank priorities using deadlines, money impact, and risk signals.\n"
        "- Use section headers with emoji for each source that has data.\n"
        "- Bullet points, short lines, no dense paragraphs.\n"
        "- Skip sections with no data.\n"
        "- End with exactly one recommended next action.\n"
        "- Max 12 bullet points total.\n"
        "- Use Telegram HTML tags: <b>, <i>, <code> only.\n"
        "- No Markdown.\n"
        f"- Respond in language: {language}."
    )


def _ensure_decision_ready_structure(text: str, language: str) -> str:
    lang = language if language in _TOP_PRIORITY_HEADERS else "en"
    normalized = text.strip()

    top_header = _TOP_PRIORITY_HEADERS[lang]
    rec_header = _RECOMMENDED_HEADERS[lang]
    rec_default = _RECOMMENDED_DEFAULT[lang]
    lower = normalized.lower()

    if "top priorit" not in lower and "топ-приоритет" not in lower and "prioridades" not in lower:
        normalized = f"{top_header}\n{normalized}".strip()
        lower = normalized.lower()

    if "recommended next action" not in lower and "следующее действие" not in lower:
        normalized = f"{normalized}\n\n{rec_header}\n{rec_default}".strip()

    return normalized


async def format_action_message(
    action: ScheduledAction,
    payload: dict[str, str],
    sources_status: dict[str, dict[str, Any]] | None = None,
    *,
    allow_synthesis: bool = False,
) -> tuple[str, str | None, int | None, bool]:
    """Return formatted message text and model marker."""
    text = format_compact_message(action, payload, sources_status=sources_status)
    language = action.language or "en"

    if action.output_mode == OutputMode.decision_ready and allow_synthesis:
        input_text = _build_synthesis_input(payload, action.sources or [])
        if input_text:
            system = _decision_ready_system(language)
            for idx, model in enumerate(_DECISION_READY_MODELS):
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
                        normalized = _ensure_decision_ready_structure(
                            generated.strip(),
                            language,
                        )
                        usage = get_last_usage()
                        tokens_used = usage.tokens_input + usage.tokens_output
                        return normalized, model, tokens_used, idx > 0
                except Exception:
                    continue

        # Fallback to deterministic output if all synthesis models fail.
        return text, "template_fallback", None, True
    return text, None, None, False
