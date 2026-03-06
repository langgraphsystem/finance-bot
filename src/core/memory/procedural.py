"""Procedural Memory — learns from corrections + detects workflows (Phase 3.3).

Bot learns from user corrections and repeated patterns. Weekly Taskiq job
analyzes correction patterns → generates domain-specific procedure rules.

Procedures stored in Mem0 ``procedures`` domain and cached in
UserProfile.learned_patterns["procedures"].
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.core.observability import observe

logger = logging.getLogger(__name__)

# Max procedures per domain
MAX_PROCEDURES_PER_DOMAIN = 10

# Max total procedures per user
MAX_TOTAL_PROCEDURES = 30

# Domains that can have procedural rules
PROCEDURAL_DOMAINS: frozenset[str] = frozenset({
    "finance",
    "life",
    "writing",
    "email",
    "tasks",
    "booking",
    "calendar",
})

# Intents where procedural context is injected into LLM prompt
PROCEDURAL_INTENTS: frozenset[str] = frozenset({
    "add_expense",
    "add_income",
    "scan_receipt",
    "correct_category",
    "draft_message",
    "draft_reply",
    "write_post",
    "send_email",
    "create_task",
    "create_event",
    "create_booking",
    "generate_document",
    "generate_presentation",
    "generate_spreadsheet",
})

# Map intents to procedure domains
INTENT_PROCEDURE_DOMAIN: dict[str, str] = {
    "add_expense": "finance",
    "add_income": "finance",
    "scan_receipt": "finance",
    "correct_category": "finance",
    "set_budget": "finance",
    "mark_paid": "finance",
    "add_recurring": "finance",
    "draft_message": "writing",
    "draft_reply": "email",
    "write_post": "writing",
    "send_email": "email",
    "follow_up_email": "email",
    "create_task": "tasks",
    "set_reminder": "tasks",
    "create_event": "calendar",
    "create_booking": "booking",
    "receptionist": "booking",
    "generate_document": "writing",
    "generate_presentation": "writing",
    "generate_spreadsheet": "finance",
    "track_food": "life",
    "track_drink": "life",
    "mood_checkin": "life",
}

PROCEDURE_EXTRACTION_PROMPT = """Проанализируй историю коррекций и паттерны пользователя.
Создай список процедурных правил для домена "{domain}".

КОРРЕКЦИИ ПОЛЬЗОВАТЕЛЯ:
{corrections}

ПАТТЕРНЫ ПОВЕДЕНИЯ:
{patterns}

ПРАВИЛА:
1. Каждое правило — конкретная инструкция для бота
2. Правила основаны на РЕАЛЬНЫХ коррекциях (не выдумывай)
3. Формат: "КОГДА [ситуация], ТОГДА [действие]"
4. Максимум 5 правил
5. Приоритет: часто повторяющиеся коррекции > разовые

Примеры:
- КОГДА пользователь добавляет расход на Starbucks, ТОГДА категория = Кафе (не Еда)
- КОГДА пользователь просит написать письмо клиенту, ТОГДА тон = деловой + обращение на "вы"
- КОГДА пользователь добавляет расход на бензин, ТОГДА scope = business

ПРАВИЛА ДЛЯ ДОМЕНА "{domain}":"""


@observe(name="learn_from_correction")
async def learn_from_correction(
    user_id: str,
    intent: str,
    original_value: str,
    corrected_value: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Record a user correction for procedural learning.

    Called when user explicitly corrects bot output (e.g., correct_category,
    rewrite request, category change).

    Corrections are stored in UserProfile.learned_patterns["corrections"]
    for weekly batch analysis.

    Phase 6: If the correction looks like a user rule ("я же сказал без эмодзи",
    "я просил коротко"), it's also saved as an immediate user rule.
    """
    domain = INTENT_PROCEDURE_DOMAIN.get(intent, "general")
    correction = {
        "intent": intent,
        "domain": domain,
        "original": original_value,
        "corrected": corrected_value,
        "timestamp": datetime.now(UTC).isoformat(),
        "context": context or {},
    }

    try:
        import uuid

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_profile import UserProfile

        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(
                    UserProfile.user_id == uuid.UUID(user_id)
                )
            )
            profile = result.scalar_one_or_none()
            if not profile:
                return

            patterns = profile.learned_patterns or {}
            corrections = patterns.get("corrections", [])
            corrections.append(correction)
            # Keep last 100 corrections
            patterns["corrections"] = corrections[-100:]
            profile.learned_patterns = patterns
            await session.commit()
            logger.debug(
                "Recorded correction for user %s: %s → %s",
                user_id, original_value, corrected_value,
            )

        # Phase 6: Detect if correction implies a user rule
        rule = _extract_rule_from_correction(corrected_value)
        if rule:
            try:
                from src.core.identity import _add_user_rule

                await _add_user_rule(user_id, rule)
                logger.info("Realtime rule from correction: %s → %s", user_id, rule)
            except Exception as e:
                logger.debug("Rule extraction from correction failed: %s", e)

    except Exception as e:
        logger.debug("Correction recording failed: %s", e)


# Correction phrases that imply a user rule
_CORRECTION_MARKERS = [
    "я же сказал", "я просил", "я говорил", "опять", "снова",
    "i said", "i asked", "again", "i told you",
    "без эмодзи", "no emoji", "коротко", "кратко", "briefly",
    "на русском", "in english", "по-русски",
]


def _extract_rule_from_correction(text: str) -> str | None:
    """Try to extract a user rule from a correction message."""
    lower = text.lower()
    for marker in _CORRECTION_MARKERS:
        if marker in lower:
            # The correction text IS the rule
            # Clean up: remove "я же сказал" prefix
            for prefix in ["я же сказал ", "я просил ", "я говорил ", "i said ", "i asked "]:
                if lower.startswith(prefix):
                    return text[len(prefix):].strip()
            return text.strip()
    return None


@observe(name="detect_workflow")
async def detect_workflow(
    user_id: str,
    intent_sequence: list[str],
) -> list[dict[str, Any]]:
    """Detect repeated intent sequences (workflows).

    Analyzes recent intent history to find patterns like:
    expense → receipt = habit, create_event → set_reminder = standard flow.

    Returns list of detected workflow patterns.
    """
    if len(intent_sequence) < 3:
        return []

    # Find repeated bigrams (2-intent sequences)
    bigrams: dict[tuple[str, str], int] = {}
    for i in range(len(intent_sequence) - 1):
        pair = (intent_sequence[i], intent_sequence[i + 1])
        bigrams[pair] = bigrams.get(pair, 0) + 1

    workflows: list[dict[str, Any]] = []
    for (a, b), count in bigrams.items():
        if count >= 2:
            workflows.append({
                "sequence": [a, b],
                "count": count,
                "suggestion": f"After {a}, suggest {b}",
            })

    return sorted(workflows, key=lambda w: w["count"], reverse=True)[:5]


@observe(name="extract_procedures")
async def extract_procedures(
    domain: str,
    corrections: list[dict[str, Any]],
    patterns: list[str] | None = None,
) -> list[str]:
    """Extract procedural rules from correction history using LLM.

    Called by weekly cron job. Uses Gemini Flash for cheap extraction.
    Returns list of rule strings.
    """
    if not corrections:
        return []

    from src.core.llm.clients import google_client

    corrections_text = "\n".join(
        f"- Интент: {c.get('intent', '?')}, было: {c.get('original', '?')}, "
        f"стало: {c.get('corrected', '?')}"
        + (f" (контекст: {c.get('context', {})})" if c.get("context") else "")
        for c in corrections
    )
    patterns_text = "\n".join(f"- {p}" for p in (patterns or [])) or "Нет данных"

    try:
        client = google_client()
        prompt = PROCEDURE_EXTRACTION_PROMPT.format(
            domain=domain,
            corrections=corrections_text,
            patterns=patterns_text,
        )
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        return _parse_procedures(response.text or "")
    except Exception as e:
        logger.warning("Procedure extraction failed for domain %s: %s", domain, e)
        return []


def _parse_procedures(text: str) -> list[str]:
    """Parse LLM output into procedure rule strings."""
    rules: list[str] = []
    for line in text.strip().split("\n"):
        line = line.strip().lstrip("- ").lstrip("0123456789.").strip()
        if not line:
            continue
        # Accept lines that look like rules (minimum length, contain keywords)
        if len(line) > 15 and ("КОГДА" in line.upper() or "ТОГДА" in line.upper()
                                or "WHEN" in line.upper() or "THEN" in line.upper()
                                or "→" in line or "->" in line):
            rules.append(line)
        elif len(line) > 20:
            # Accept longer lines as implicit rules
            rules.append(line)
    return rules[:MAX_PROCEDURES_PER_DOMAIN]


async def get_procedures(
    user_id: str,
    domain: str | None = None,
) -> list[str]:
    """Get procedural rules for a user, optionally filtered by domain.

    Loads from UserProfile.learned_patterns["procedures"].
    """
    try:
        import uuid

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_profile import UserProfile

        async with async_session() as session:
            result = await session.execute(
                select(UserProfile.learned_patterns).where(
                    UserProfile.user_id == uuid.UUID(user_id)
                )
            )
            patterns = result.scalar_one_or_none()
            if not patterns or not isinstance(patterns, dict):
                return []

            procedures = patterns.get("procedures", {})
            if not isinstance(procedures, dict):
                return []

            if domain:
                return procedures.get(domain, [])[:MAX_PROCEDURES_PER_DOMAIN]

            # All domains
            all_rules: list[str] = []
            for d_rules in procedures.values():
                if isinstance(d_rules, list):
                    all_rules.extend(d_rules)
            return all_rules[:MAX_TOTAL_PROCEDURES]
    except Exception as e:
        logger.debug("Procedures load failed: %s", e)
        return []


async def save_procedures(
    user_id: str,
    domain: str,
    rules: list[str],
) -> None:
    """Save procedural rules for a specific domain."""
    try:
        import uuid

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_profile import UserProfile

        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(
                    UserProfile.user_id == uuid.UUID(user_id)
                )
            )
            profile = result.scalar_one_or_none()
            if not profile:
                return

            patterns = profile.learned_patterns or {}
            procedures = patterns.get("procedures", {})
            if not isinstance(procedures, dict):
                procedures = {}
            procedures[domain] = rules[:MAX_PROCEDURES_PER_DOMAIN]
            patterns["procedures"] = procedures
            profile.learned_patterns = patterns
            await session.commit()
            logger.debug(
                "Saved %d procedures for user %s domain %s",
                len(rules), user_id, domain,
            )
    except Exception as e:
        logger.debug("Procedures save failed: %s", e)


def format_procedures_block(procedures: list[str]) -> str:
    """Format procedures as a context block for LLM injection."""
    if not procedures:
        return ""
    lines = "\n".join(f"- {rule}" for rule in procedures[:MAX_PROCEDURES_PER_DOMAIN])
    return f"\n\n<learned_procedures>\n{lines}\n</learned_procedures>"


def get_domain_for_intent(intent: str) -> str | None:
    """Get the procedure domain for an intent."""
    return INTENT_PROCEDURE_DOMAIN.get(intent)
