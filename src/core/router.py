"""Message router — main orchestration: message → intent → skill → response."""

import asyncio
import base64
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from src.agents import AGENTS, AgentRouter
from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.domain_router import DomainRouter
from src.core.family import create_family
from src.core.guardrails import check_input
from src.core.intent import detect_intent, detect_intent_v2
from src.core.memory import sliding_window
from src.core.memory.summarization import summarize_dialog
from src.core.models.conversation import ConversationMessage
from src.core.models.document import Document
from src.core.models.enums import (
    ConversationState,
    DocumentType,
    LoadStatus,
    MessageRole,
    Scope,
    TransactionType,
)
from src.core.models.load import Load
from src.core.models.transaction import Transaction
from src.core.models.user_context import UserContext
from src.core.rate_limit import check_rate_limit
from src.core.request_context import reset_family_context, set_family_context
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage
from src.skills import create_registry
from src.skills.base import SkillRegistry, SkillResult
from src.tools.storage import upload_document

logger = logging.getLogger(__name__)

_registry: SkillRegistry | None = None
_agent_router: AgentRouter | None = None
_domain_router: DomainRouter | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = create_registry()
    return _registry


def get_agent_router() -> AgentRouter:
    """Lazy-init the AgentRouter (wraps SkillRegistry)."""
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter(AGENTS, get_registry())
    return _agent_router


def get_domain_router() -> DomainRouter:
    """Lazy-init the DomainRouter (wraps AgentRouter).

    Phase 1: thin wrapper — all intents pass through to AgentRouter.
    Phase 2+: complex domains get LangGraph orchestrators.
    """
    global _domain_router
    if _domain_router is None:
        _domain_router = DomainRouter(get_agent_router())

        # Register LangGraph orchestrators for complex domains
        from src.core.domains import Domain
        from src.orchestrators.brief.graph import BriefOrchestrator
        from src.orchestrators.email.graph import EmailOrchestrator

        _domain_router.register_orchestrator(
            Domain.email, EmailOrchestrator(agent_router=get_agent_router())
        )
        _domain_router.register_orchestrator(Domain.brief, BriefOrchestrator())

        from src.core.config import settings as _settings

        if _settings.ff_langgraph_booking:
            from src.orchestrators.booking.graph import BookingOrchestrator

            _domain_router.register_orchestrator(
                Domain.booking, BookingOrchestrator(agent_router=get_agent_router())
            )

        if _settings.ff_langgraph_document:
            from src.orchestrators.document.graph import DocumentOrchestrator

            _domain_router.register_orchestrator(
                Domain.document, DocumentOrchestrator(agent_router=get_agent_router())
            )
    return _domain_router


def _get_intent_detector():
    """Return the appropriate intent detection function based on feature flags.

    When ff_supervisor_routing is enabled, uses two-stage detection:
    Stage 1: keyword-based domain resolution (zero LLM cost).
    Stage 2: scoped intent detection with only the domain's intents.
    """
    from src.core.config import settings as _settings

    if _settings.ff_supervisor_routing:
        return detect_intent_v2
    return detect_intent


async def _persist_message(
    user_id: str,
    family_id: str,
    role: MessageRole,
    content: str,
    intent: str | None = None,
) -> None:
    """Persist a conversation message to PostgreSQL with retry."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with async_session() as session:
                msg = ConversationMessage(
                    user_id=uuid.UUID(user_id),
                    family_id=uuid.UUID(family_id),
                    session_id=uuid.uuid4(),
                    role=role,
                    content=content,
                    intent=intent,
                )
                session.add(msg)
                await session.commit()
            return
        except Exception as e:
            if attempt < max_retries:
                import asyncio as _aio

                await _aio.sleep(0.5 * (attempt + 1))
                continue
            logger.error(
                "Failed to persist conversation message after %d attempts: %s",
                max_retries + 1, e,
            )


# ---------------------------------------------------------------------------
# Session buffer: extract key facts from intent_data after skill execution
# ---------------------------------------------------------------------------
_FACT_BEARING_INTENTS: dict[str, list[tuple[str, str]]] = {
    # intent: [(field_key, category), ...]
    "add_expense": [("amount", "spending_pattern"), ("description", "merchant_mapping")],
    "add_income": [("amount", "income"), ("description", "income")],
    "set_budget": [("amount", "budget_limit")],
    "add_recurring": [("amount", "recurring_expense"), ("description", "recurring_expense")],
    "correct_category": [("new_category", "correction_rule")],
    "track_food": [("food_name", "life_pattern")],
    "track_drink": [("drink_name", "life_pattern")],
}


def _extract_session_facts(
    intent: str, intent_data: dict[str, Any]
) -> list[tuple[str, str]]:
    """Extract human-readable facts from intent_data for session buffer.

    Returns list of (fact_text, category) tuples.
    """
    fields = _FACT_BEARING_INTENTS.get(intent)
    if not fields:
        return []
    facts: list[tuple[str, str]] = []
    for field_key, category in fields:
        value = intent_data.get(field_key)
        if value:
            facts.append((f"{field_key}: {value}", category))
    return facts


_LAST_FILE_TTL = 300  # 5 minutes


async def _cache_last_file(user_id: str, message: IncomingMessage) -> None:
    """Cache file data from a document/photo message in Redis for follow-up conversion."""
    import json

    try:
        from src.core.db import redis

        file_bytes = message.document_bytes or message.photo_bytes
        if not file_bytes or len(file_bytes) > 20 * 1024 * 1024:
            return

        key_data = f"last_file:{user_id}:data"
        key_meta = f"last_file:{user_id}:meta"
        meta = {
            "mime": message.document_mime_type or ("image/jpeg" if message.photo_bytes else None),
            "name": message.document_file_name or ("photo.jpg" if message.photo_bytes else None),
            "is_photo": bool(message.photo_bytes and not message.document_bytes),
        }
        await redis.set(key_data, file_bytes, ex=_LAST_FILE_TTL)
        await redis.set(key_meta, json.dumps(meta), ex=_LAST_FILE_TTL)
    except Exception as e:
        logger.warning("Failed to cache last file: %s", e)


async def _get_cached_file(user_id: str) -> dict | None:
    """Retrieve cached file data from Redis (non-destructive, TTL handles cleanup)."""
    import json

    try:
        from src.core.db import redis

        key_data = f"last_file:{user_id}:data"
        key_meta = f"last_file:{user_id}:meta"
        meta_raw = await redis.get(key_meta)
        if not meta_raw:
            return None
        data = await redis.get(key_data)
        if not data:
            return None
        meta = json.loads(meta_raw)
        return {
            "bytes": data,
            "mime": meta.get("mime"),
            "name": meta.get("name"),
            "is_photo": meta.get("is_photo", False),
        }
    except Exception as e:
        logger.warning("Failed to get cached file: %s", e)
        return None




async def handle_message(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Main message handler: intent detection → skill execution → response."""
    registry = get_registry()

    try:
        rate_ok = await check_rate_limit(message.user_id)
    except Exception as e:
        logger.warning("Rate limit check failed (Redis down?): %s — allowing message", e)
        rate_ok = True
    if not rate_ok:
        return OutgoingMessage(
            text="Слишком много сообщений. Подождите минуту.",
            chat_id=message.chat_id,
        )

    # Set RLS family context so that any DB session opened downstream
    # (inside skills, agents, etc.) automatically applies the correct
    # ``app.current_family_id`` PostgreSQL setting.
    token = set_family_context(context.family_id) if context.family_id else None
    try:
        return await _dispatch_message(message, context, registry)
    finally:
        if token is not None:
            reset_family_context(token)


async def _dispatch_message(
    message: IncomingMessage,
    context: SessionContext,
    registry: SkillRegistry,
) -> OutgoingMessage:
    """Inner dispatch logic extracted from *handle_message* for clean RLS wrapping."""

    # Handle callbacks immediately
    if message.type == MessageType.callback:
        return await _handle_callback(message, context)

    # Handle location pins: reverse-geocode and save as user's city + timezone
    if message.type == MessageType.location and message.text:
        city = await _reverse_geocode_city(message.text)
        if city:
            tz_name = await _save_user_city(context.user_id, city)
            # Auto-execute pending maps search if one was stored
            result = await _execute_pending_maps_search(context.user_id, city, message)
            if result:
                return result
            # Localized confirmation with city + timezone
            from src.skills.onboarding.handler import get_onboarding_texts

            t = await get_onboarding_texts(context.language or "en")
            confirm_text = t.get("tz_location_confirmed", "").format(
                city=city,
                tz=tz_name or "UTC",
            )
            if not confirm_text:
                confirm_text = f"Got it — your city is <b>{city}</b> ({tz_name or 'UTC'})."
            return OutgoingMessage(
                text=confirm_text,
                chat_id=message.chat_id,
                remove_reply_keyboard=True,
            )
        return OutgoingMessage(
            text="Could not determine your city from the pin. Please type your city name instead.",
            chat_id=message.chat_id,
            remove_reply_keyboard=True,
        )

    # Voice transcription: convert voice to text, then process as text
    if message.type == MessageType.voice:
        from src.core.voice import transcribe_voice

        if not message.voice_bytes:
            return OutgoingMessage(
                text="Не удалось получить голосовое сообщение.",
                chat_id=message.chat_id,
            )
        transcribed_text = await transcribe_voice(message.voice_bytes)
        if not transcribed_text:
            return OutgoingMessage(
                text="Не удалось распознать речь. Попробуйте ещё раз или напишите текстом.",
                chat_id=message.chat_id,
            )
        # Replace message with transcribed text and continue as text
        message = IncomingMessage(
            id=message.id,
            user_id=message.user_id,
            chat_id=message.chat_id,
            text=transcribed_text,
            type=MessageType.text,
            raw=message.raw,
        )

    # Intercept active browser login flow BEFORE intent detection
    if message.type == MessageType.text and message.text:
        taxi_result = await _check_browser_taxi_flow(message, context)
        if taxi_result:
            return taxi_result

        login_result = await _check_browser_login_flow(message, context)
        if login_result:
            return login_result

        # Intercept booking flow text input (user types hotel number)
        booking_result = await _check_browser_booking_flow(message, context)
        if booking_result:
            return booking_result

    # Handle photos and documents
    if message.type in (MessageType.photo, MessageType.document):
        # Always cache file for potential follow-up conversion text message
        await _cache_last_file(context.user_id, message)

        # Guardrails check on photo/document captions
        if message.text:
            is_safe, refusal_text = await check_input(message.text)
            if not is_safe:
                return OutgoingMessage(
                    text=(refusal_text or "Я не могу помочь с этим запросом."),
                    chat_id=message.chat_id,
                )

        if message.text:
            # Caption present → let LLM decide the intent (convert_document, scan_document, etc.)
            # Add file context hint so intent detection knows a document is attached
            detect_text = message.text
            fname = message.document_file_name or ""
            if fname:
                detect_text = f"[Attached file: {fname}] {message.text}"
            elif message.photo_bytes:
                detect_text = f"[Attached photo] {message.text}"
            _detect = _get_intent_detector()
            result = await _detect(
                text=detect_text,
                categories=context.categories,
                language=context.language,
            )
            intent_name = result.intent
            intent_data = result.data.model_dump() if result.data else {}
            intent_data["confidence"] = result.confidence
        else:
            # No caption → check recent conversation for a document-related intent
            intent_name = "scan_document"
            intent_data: dict[str, Any] = {}
            try:
                recent = await sliding_window.get_recent_messages(context.user_id, limit=3)
                doc_intents = {
                    "analyze_document",
                    "extract_table",
                    "fill_template",
                    "fill_pdf_form",
                    "summarize_document",
                    "compare_documents",
                    "merge_documents",
                    "convert_document",
                }
                for msg in reversed(recent):
                    if msg.get("role") == "user" and msg.get("intent") in doc_intents:
                        intent_name = msg["intent"]
                        break
            except Exception:
                pass  # fallback to scan_document
    else:
        # --- Guardrails check BEFORE intent detection ---
        if message.text:
            is_safe, refusal_text = await check_input(message.text)
            if not is_safe:
                return OutgoingMessage(
                    text=(refusal_text or "Я не могу помочь с этим запросом."),
                    chat_id=message.chat_id,
                )

        # --- Slash commands (before intent detection) ---
        if message.text and message.text.startswith("/"):
            cmd_result = await _handle_slash_command(message, context)
            if cmd_result:
                return cmd_result

        # Fetch recent dialog context for intent disambiguation
        recent_context = None
        recent_msgs: list[dict] = []
        try:
            recent_msgs = await sliding_window.get_recent_messages(context.user_id, limit=2)
            if recent_msgs:
                lines = []
                for m in recent_msgs:
                    role_label = "User" if m["role"] == "user" else "Bot"
                    intent_hint = f" [{m['intent']}]" if m.get("intent") else ""
                    lines.append(f"{role_label}{intent_hint}: {m['content'][:200]}")
                recent_context = "\n".join(lines)
        except Exception as e:
            logger.debug("Failed to fetch recent context for intent: %s", e)

        # Intent detection (supervisor-routed or full)
        _detect = _get_intent_detector()
        result = await _detect(
            text=message.text or "",
            categories=context.categories,
            language=context.language,
            recent_context=recent_context,
        )
        intent_name = result.intent
        intent_data = result.data.model_dump() if result.data else {}
        intent_data["confidence"] = result.confidence

        # Video follow-up override: if LLM picked general intent but active video session
        # exists and message matches follow-up keywords → route to video_action
        if intent_name in ("general_chat", "quick_answer") and message.text:
            video_followup_map: list[tuple[str, list[str]]] = [
                (
                    "content_plan",
                    ["контент-план", "контент план", "content plan", "план контента"],
                ),
                ("steps", ["по шагам", "пошагово", "список шагов", "выпиши шаги", "шаги из"]),
                ("article", ["напиши статью", "сделай статью", "write an article", "blog post"]),
                ("script", ["сценарий", "напиши сценарий", "write a script"]),
                (
                    "summary",
                    ["резюме видео", "сделай резюме", "вкратце перескажи", "summarize video"],
                ),
                ("save", ["сохрани видео", "save video", "запомни видео"]),
                (
                    "save_content",
                    [
                        "сохрани это",
                        "сохрани текст",
                        "запомни это",
                        "save this",
                        "save the text",
                        "сохрани контент",
                        "сохрани план",
                    ],
                ),
                ("remind", ["напомни посмотреть", "remind me to watch"]),
                ("translate", ["переведи видео", "translate video"]),
                ("similar", ["найди похожие", "похожие видео", "ещё видео", "find similar"]),
                ("quotes", ["процитируй", "ключевые цитаты", "key quotes"]),
                (
                    "deeper",
                    [
                        "подробнее",
                        "расскажи ещё",
                        "расскажи еще",
                        "tell me more",
                        "more details",
                        "подробней",
                    ],
                ),
            ]
            text_lower = message.text.lower()
            matched_action = None
            for action, keywords in video_followup_map:
                if any(kw in text_lower for kw in keywords):
                    matched_action = action
                    break
            if matched_action:
                from src.core.video_session import get_video_session as _gvs
                _vsess = await _gvs(context.user_id)
                if _vsess:
                    intent_name = "video_action"
                    intent_data["video_action_type"] = matched_action

        # CLARIFY gate: if LLM is uncertain, present disambiguation buttons
        if (
            result.intent_type == "clarify"
            and result.clarify_candidates
            and len(result.clarify_candidates) >= 2
        ):
            return await _handle_clarify(message, context, result, intent_data)

        # Registered user should never hit onboarding — redirect to general_chat
        if intent_name == "onboarding" and context.family_id:
            intent_name = "general_chat"

        # Low confidence → redirect to universal fallback
        if result.confidence < 0.5 and intent_name != "general_chat":
            logger.info(
                "Low confidence %.2f for intent %s, redirecting to general_chat",
                result.confidence,
                intent_name,
            )
            intent_data["original_intent"] = intent_name
            intent_name = "general_chat"

        logger.info(
            "Intent: %s (%.2f) for user %s",
            intent_name,
            result.confidence,
            context.user_id,
        )

        # Auto-save detected city to user profile (background)
        # Always update — user may have moved to a new city
        detected_city = intent_data.get("detected_city")
        if detected_city and context.user_id and context.family_id:
            if detected_city != context.user_profile.get("city"):
                asyncio.create_task(_save_user_city(context.user_id, detected_city))

    # REVERSE PROMPTING gate: complex requests get a plan proposal
    from src.core.config import settings as _rp_settings

    if _rp_settings.ff_reverse_prompting and message.text and message.type == MessageType.text:
        from src.core.reverse_prompt import should_reverse_prompt

        if should_reverse_prompt(message.text, intent_name, result.confidence):
            try:
                from src.core.reverse_prompt import (
                    generate_plan_proposal,
                    store_pending_plan,
                )

                plan_text = await generate_plan_proposal(
                    message.text,
                    intent_name,
                    context,
                )
                await store_pending_plan(
                    context.user_id,
                    intent_name,
                    message.text,
                    intent_data,
                    plan_text,
                )
                lang = context.language or "en"
                header = "Here's my plan:" if lang == "en" else "Вот мой план:"
                return OutgoingMessage(
                    text=f"<b>{header}</b>\n\n{plan_text}",
                    chat_id=message.chat_id,
                    buttons=[
                        {
                            "text": "Execute" if lang == "en" else "Выполнить",
                            "callback": "plan:execute",
                        },
                        {
                            "text": "Adjust" if lang == "en" else "Изменить",
                            "callback": "plan:adjust",
                        },
                        {
                            "text": "Cancel" if lang == "en" else "Отмена",
                            "callback": "plan:cancel",
                        },
                    ],
                )
            except Exception:
                logger.warning("Reverse prompt failed, executing normally", exc_info=True)

    # If LLM detected a file-requiring intent from a text message, inject cached file
    file_required_intents = {
        "convert_document",
        "analyze_document",
        "extract_table",
        "fill_template",
        "fill_pdf_form",
        "summarize_document",
        "compare_documents",
        "merge_documents",
    }
    if intent_name in file_required_intents and message.type not in (
        MessageType.photo,
        MessageType.document,
    ):
        cached = await _get_cached_file(context.user_id)
        if cached:
            logger.info("Injecting cached file '%s' for %s", cached.get("name"), intent_name)
        else:
            logger.info("No cached file for %s (user %s)", intent_name, context.user_id)
        if cached:
            is_photo = cached["is_photo"]
            message = IncomingMessage(
                id=message.id,
                user_id=message.user_id,
                chat_id=message.chat_id,
                type=MessageType.photo if is_photo else MessageType.document,
                text=message.text,
                document_bytes=None if is_photo else cached["bytes"],
                photo_bytes=cached["bytes"] if is_photo else None,
                document_mime_type=cached["mime"],
                document_file_name=cached["name"],
                raw=message.raw,
                channel=message.channel,
            )

    # Persist user message BEFORE skill execution (audit trail)
    if message.text:
        await sliding_window.add_message(context.user_id, "user", message.text, intent_name)
        asyncio.create_task(
            _persist_message(
                context.user_id,
                context.family_id,
                MessageRole.user,
                message.text,
                intent_name,
            )
        )

    # Incremental personality tracking (lightweight Redis EMA, no DB/LLM)
    if message.text:
        try:
            from src.core.tasks.profile_tasks import incremental_personality_update

            asyncio.create_task(incremental_personality_update(context.user_id, message.text))
        except Exception:
            pass

    # Pre-warm translations for non-static languages (en/ru/es are instant)
    if context.language and context.language not in ("en", "ru", "es"):
        try:
            from src.skills._i18n import warm_translations

            asyncio.create_task(warm_translations(context.language))
        except Exception:
            pass  # Translation warm-up is best-effort

    # Tiered rate limit: check per-intent cost tier after intent detection
    try:
        from src.core.rate_limiter import check_rate_limit as check_tiered_rate_limit
        from src.core.rate_limiter import get_limit_message

        tiered_ok, tier = await check_tiered_rate_limit(context.user_id, intent_name)
        if not tiered_ok:
            return OutgoingMessage(
                text=get_limit_message(tier, context.language or "en"),
                chat_id=message.chat_id,
            )
    except Exception as e:
        logger.debug("Tiered rate limit check failed: %s — allowing", e)

    # Route through DomainRouter (domain -> agent -> context assembly -> skill)
    domain_router = get_domain_router()
    try:
        skill_result = await domain_router.route(intent_name, message, context, intent_data)
    except Exception as e:
        logger.error(
            "DomainRouter failed for %s: %s, falling back to direct skill",
            intent_name,
            e,
            exc_info=True,
        )
        # Fallback: direct skill dispatch (backward compatibility)
        try:
            skill = registry.get(intent_name)
            if not skill:
                skill = registry.get("general_chat")
            intent_data["_intent"] = intent_name
            skill_result = await skill.execute(message, context, intent_data)
        except Exception as inner_e:
            logger.error("Fallback skill %s also failed: %s", intent_name, inner_e, exc_info=True)
            skill_result = SkillResult(response_text="Произошла ошибка. Попробуйте ещё раз.")
    # Phase 13: Post-generation rule check
    if skill_result.response_text and settings.ff_post_gen_check:
        try:
            from src.core.identity import get_user_rules
            from src.core.post_gen_check import (
                check_response_rules,
                regenerate_with_rule_reminder,
            )

            user_rules = await get_user_rules(str(context.user_id))
            if user_rules:
                ok, violation = await check_response_rules(
                    skill_result.response_text, user_rules
                )
                if not ok:
                    skill_result.response_text = await regenerate_with_rule_reminder(
                        skill_result.response_text,
                        violation,
                        user_rules,
                        "",
                        message.text or "",
                    )
        except Exception as pgc_err:
            logger.debug("Post-gen check failed (non-critical): %s", pgc_err)

    if skill_result.response_text:
        await sliding_window.add_message(context.user_id, "assistant", skill_result.response_text)
        asyncio.create_task(
            _persist_message(
                context.user_id,
                context.family_id,
                MessageRole.assistant,
                skill_result.response_text,
            )
        )

    # Log token usage from context assembly (C1: wire log_usage)
    try:
        assembled = intent_data.get("_assembled")
        if assembled and hasattr(assembled, "token_usage"):
            from src.billing.usage_tracker import log_usage

            tu = assembled.token_usage
            overflow_dropped = []
            if tu.get("mem0", 0) == 0 and "mem" in str(
                intent_data.get("_context_config", "")
            ):
                overflow_dropped.append("mem0")
            if tu.get("sql", 0) == 0 and intent_data.get("_context_config_sql"):
                overflow_dropped.append("sql")

            asyncio.create_task(
                log_usage(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    domain=intent_data.get("_agent", ""),
                    skill=intent_name,
                    model=intent_data.get("_model", ""),
                    tokens_input=tu.get("total", 0),
                    tokens_output=0,
                    cache_read_tokens=tu.get("identity", 0),
                    overflow_layers_dropped=(
                        ",".join(overflow_dropped) if overflow_dropped else None
                    ),
                )
            )
    except Exception as e:
        logger.debug("Usage logging failed: %s", e)

    # Layer 5: Trigger incremental dialog summarization in the background
    asyncio.create_task(summarize_dialog(context.user_id, context.family_id))

    # C2: Write key facts to session buffer for immediate availability
    try:
        from src.core.memory.session_buffer import update_session_buffer

        _session_buffer_facts = _extract_session_facts(intent_name, intent_data)
        for fact, category in _session_buffer_facts:
            asyncio.create_task(
                update_session_buffer(context.user_id, fact, category)
            )
    except Exception as e:
        logger.debug("Session buffer write failed: %s", e)

    # Execute background tasks with error logging
    async def _safe_background(coro, task_name: str) -> None:
        try:
            await coro
        except Exception as exc:
            logger.error("Background task %s failed: %s", task_name, exc)

    for idx, task_fn in enumerate(skill_result.background_tasks):
        try:
            result = task_fn()
            if asyncio.iscoroutine(result):
                asyncio.create_task(
                    _safe_background(result, f"{intent_name}#{idx}")
                )
        except Exception as e:
            logger.error("Background task %s#%d dispatch failed: %s", intent_name, idx, e)

    # Undo window: store undo payload and append button for quick-action skills
    try:
        from src.core.undo import UNDO_INTENTS, store_undo

        record_id = intent_data.get("_record_id")
        record_table = intent_data.get("_record_table")
        if intent_name in UNDO_INTENTS and record_id and record_table:
            asyncio.create_task(store_undo(context.user_id, intent_name, record_id, record_table))
            undo_btn = {"text": "\u21a9 Undo", "callback": "undo:last"}
            existing_buttons = skill_result.buttons or []
            skill_result = SkillResult(
                response_text=skill_result.response_text,
                buttons=existing_buttons + [undo_btn],
                document=skill_result.document,
                document_name=skill_result.document_name,
                photo_url=skill_result.photo_url,
                photo_bytes=skill_result.photo_bytes,
                chart_url=skill_result.chart_url,
                background_tasks=[],
                reply_keyboard=skill_result.reply_keyboard,
            )
    except Exception as e:
        logger.warning("Undo window injection failed: %s", e)

    # Smart suggestions: non-intrusive reply keyboard buttons
    if not skill_result.reply_keyboard:
        try:
            from src.core.suggestions import get_suggestions

            suggestions = await get_suggestions(intent_name, context.user_id)
            if suggestions:
                skill_result = SkillResult(
                    response_text=skill_result.response_text,
                    buttons=skill_result.buttons,
                    document=skill_result.document,
                    document_name=skill_result.document_name,
                    photo_url=skill_result.photo_url,
                    photo_bytes=skill_result.photo_bytes,
                    chart_url=skill_result.chart_url,
                    background_tasks=[],
                    reply_keyboard=[{"text": s["text"]} for s in suggestions],
                )
        except Exception as e:
            logger.warning("Suggestions injection failed: %s", e)

    return OutgoingMessage(
        text=skill_result.response_text,
        chat_id=message.chat_id,
        buttons=skill_result.buttons,
        document=skill_result.document,
        document_name=skill_result.document_name,
        photo_url=skill_result.photo_url,
        photo_bytes=skill_result.photo_bytes,
        chart_url=skill_result.chart_url,
        reply_keyboard=skill_result.reply_keyboard,
    )


async def _handle_slash_command(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage | None:
    """Handle slash commands: /export, /delete_all, /invite."""
    text = (message.text or "").strip()
    if text.startswith("/start"):
        payload = text.split(maxsplit=1)[1].strip() if " " in text else ""
        if payload == "browser_connect":
            return await _resume_browser_connect(message, context)

    if text == "/export":
        import json

        from src.core.gdpr import MemoryGDPR

        gdpr = MemoryGDPR()
        try:
            async with async_session() as session:
                data = await gdpr.export_user_data(session, context.user_id)
            json_bytes = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            return OutgoingMessage(
                text="Ваши данные:",
                chat_id=message.chat_id,
                document=json_bytes,
                document_name="my_data.json",
            )
        except Exception as e:
            logger.error("GDPR export failed: %s", e)
            return OutgoingMessage(text="Ошибка при экспорте данных.", chat_id=message.chat_id)

    elif text == "/delete_all":
        from src.core.pending_actions import store_pending_action

        try:
            pending_id = await store_pending_action(
                intent="delete_all",
                user_id=context.user_id,
                family_id=context.family_id,
                action_data={},
            )
            return OutgoingMessage(
                text=(
                    "Вы собираетесь удалить <b>все</b> свои данные "
                    "(транзакции, заметки, историю сообщений, память).\n\n"
                    "Это действие <b>необратимо</b>. Подтвердите удаление:"
                ),
                chat_id=message.chat_id,
                buttons=[
                    {"text": "🗑 Удалить всё", "callback": f"confirm_action:{pending_id}"},
                    {"text": "❌ Отмена", "callback": f"cancel_action:{pending_id}"},
                ],
            )
        except Exception as e:
            logger.error("GDPR delete confirmation failed: %s", e)
            return OutgoingMessage(text="Ошибка при подготовке удаления.", chat_id=message.chat_id)

    elif text == "/connect":
        from api.oauth import generate_oauth_link

        if not context.family_id:
            return OutgoingMessage(
                text="Сначала зарегистрируйтесь через /start",
                chat_id=message.chat_id,
            )
        try:
            link = await generate_oauth_link(context.user_id)
            return OutgoingMessage(
                text="Подключите Google для работы с почтой и календарём:",
                chat_id=message.chat_id,
                buttons=[{"text": "🔗 Подключить Google", "url": link}],
            )
        except Exception as e:
            logger.error("Failed to generate OAuth link: %s", e)
            return OutgoingMessage(
                text="Ошибка при генерации ссылки. Попробуйте позже.",
                chat_id=message.chat_id,
            )

    elif text == "/extension":
        import secrets

        from src.core.config import settings
        from src.core.db import redis

        if not context.family_id:
            return OutgoingMessage(
                text="First register via /start",
                chat_id=message.chat_id,
            )
        token = secrets.token_urlsafe(24)
        await redis.set(f"ext_token:{token}", context.user_id, ex=86400 * 30)
        api_url = settings.public_base_url or "https://your-app.up.railway.app"
        return OutgoingMessage(
            text=(
                "<b>Browser Connect</b>\n\n"
                "Use your own browser for login. After the one-time setup, I can reuse the "
                "saved session and return you to Telegram automatically.\n\n"
                f"API URL: <code>{api_url}</code>\n"
                f"Your token: <code>{token}</code>\n\n"
                "1. Install/load the browser extension\n"
                "2. Paste the API URL and token into the extension\n"
                "3. After that, use the Connect button inside Telegram flows\n"
                "4. Log in in your browser\n"
                "5. The extension will save the session and return you to Telegram automatically"
            ),
            chat_id=message.chat_id,
        )

    elif text.startswith("/invite"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return OutgoingMessage(
                text="Используйте: /invite КОД\nНапример: /invite ABC12345",
                chat_id=message.chat_id,
            )
        invite_code = parts[1].strip()
        from src.core.family import join_family

        try:
            telegram_id = int(message.user_id)
            owner_name = "User"
            if message.raw and hasattr(message.raw, "from_user"):
                from_user = message.raw.from_user
                if from_user and hasattr(from_user, "first_name") and from_user.first_name:
                    owner_name = from_user.first_name
            async with async_session() as session:
                result = await join_family(
                    session=session,
                    invite_code=invite_code,
                    telegram_id=telegram_id,
                    name=owner_name,
                    language=context.language,
                )
            if result:
                family, user = result
                return OutgoingMessage(
                    text=f"Вы присоединились к семье \u00ab{family.name}\u00bb!",
                    chat_id=message.chat_id,
                )
            else:
                return OutgoingMessage(
                    text="Неверный код приглашения или вы уже в семье.",
                    chat_id=message.chat_id,
                )
        except Exception as e:
            logger.error("Join family failed: %s", e)
            return OutgoingMessage(text="Ошибка при присоединении.", chat_id=message.chat_id)

    return None  # Not a known slash command — continue to intent detection


async def _resume_browser_connect(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Resume an active browser-based task after the user logs in."""
    from src.tools import browser_booking, taxi_booking

    taxi_state = await taxi_booking.get_taxi_state(context.user_id)
    if taxi_state and taxi_state.get("step") == "awaiting_login":
        result = await taxi_booking.handle_login_ready(context.user_id)
        return OutgoingMessage(
            text=result.get("text", "Browser connected."),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    booking_state = await browser_booking.get_booking_state(context.user_id)
    if booking_state and booking_state.get("step") == "awaiting_login":
        result = await browser_booking.handle_login_ready(context.user_id)
        return OutgoingMessage(
            text=result.get("text", "Browser connected."),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    return OutgoingMessage(
        text="Browser connected. Return to your previous request in Telegram.",
        chat_id=message.chat_id,
    )


async def _set_onboarding_state(
    telegram_id: str,
    state: ConversationState,
) -> None:
    """Store onboarding sub-state in Redis for unregistered users."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        await redis.set(key, state.value, ex=3600)  # 1 hour TTL
    except Exception as e:
        logger.warning("Failed to set onboarding state in Redis: %s", e)


async def _get_onboarding_state(telegram_id: str) -> str:
    """Retrieve onboarding sub-state from Redis for unregistered users."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        value = await redis.get(key)
        return value if value else ""
    except Exception as e:
        logger.warning("Failed to get onboarding state from Redis: %s", e)
        return ""


async def _clear_onboarding_state(telegram_id: str) -> None:
    """Clear onboarding sub-state from Redis."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        await redis.delete(key)
        lang_key = f"onboarding_lang:{telegram_id}"
        await redis.delete(lang_key)
    except Exception as e:
        logger.warning("Failed to clear onboarding state from Redis: %s", e)


async def _set_onboarding_language(telegram_id: str, language: str) -> None:
    """Store chosen onboarding language in Redis."""
    try:
        from src.core.db import redis

        key = f"onboarding_lang:{telegram_id}"
        await redis.set(key, language, ex=3600)
    except Exception as e:
        logger.warning("Failed to set onboarding language in Redis: %s", e)


async def _get_onboarding_language(telegram_id: str) -> str:
    """Retrieve chosen onboarding language from Redis."""
    try:
        from src.core.db import redis

        key = f"onboarding_lang:{telegram_id}"
        value = await redis.get(key)
        return value if value else ""
    except Exception as e:
        logger.warning("Failed to get onboarding language from Redis: %s", e)
        return ""


async def _handle_clarify(
    message: IncomingMessage,
    context: SessionContext,
    result: Any,
    intent_data: dict[str, Any],
) -> OutgoingMessage:
    """Present disambiguation buttons and store pending state in Redis."""
    import json as _json
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from src.core.db import redis

    payload = {
        "original_text": message.text or "",
        "candidates": [
            {"intent": c.intent, "label": c.label, "confidence": c.confidence}
            for c in result.clarify_candidates[:3]
        ],
        "intent_data": {
            k: v for k, v in intent_data.items() if k != "confidence" and v is not None
        },
        "created_at": _dt.now(_UTC).isoformat(),
    }

    key = f"clarify_pending:{context.user_id}"
    await redis.set(key, _json.dumps(payload, default=str), ex=1800)  # 30 min TTL

    question = result.response or "Что именно вы хотите?"
    buttons = [
        {"text": c.label, "callback": f"clarify:{c.intent}"} for c in result.clarify_candidates[:3]
    ]

    return OutgoingMessage(
        text=f"<b>Уточните:</b> {question}",
        chat_id=message.chat_id,
        buttons=buttons,
    )


async def _run_post_skill_side_effects(
    intent_name: str,
    original_text: str,
    skill_result: "SkillResult",
    context: "SessionContext",
    intent_data: dict,
) -> "SkillResult":
    """Run the same side effects as the normal pipeline after skill execution.

    Called from callback handlers (clarify, plan:execute) that bypass the main
    message flow. Mirrors the post-skill section of ``handle_message()``:
    post-gen check, persist, usage logging, summarize, session buffer,
    background tasks, undo injection, and smart suggestions.

    Returns the (possibly mutated) SkillResult with undo/suggestion buttons.
    """
    from src.core.memory import sliding_window

    # Post-gen rule check (Phase 13)
    if skill_result.response_text and settings.ff_post_gen_check:
        try:
            from src.core.identity import get_user_rules
            from src.core.post_gen_check import (
                check_response_rules,
                regenerate_with_rule_reminder,
            )

            user_rules = await get_user_rules(str(context.user_id))
            if user_rules:
                ok, violation = await check_response_rules(
                    skill_result.response_text, user_rules
                )
                if not ok:
                    skill_result.response_text = await regenerate_with_rule_reminder(
                        skill_result.response_text, violation, user_rules,
                        "", original_text,
                    )
        except Exception:
            pass

    # Persist messages (Redis + PostgreSQL)
    if original_text:
        await sliding_window.add_message(context.user_id, "user", original_text, intent_name)
        asyncio.create_task(
            _persist_message(
                context.user_id, context.family_id,
                MessageRole.user, original_text, intent_name,
            )
        )
    if skill_result.response_text:
        await sliding_window.add_message(
            context.user_id, "assistant", skill_result.response_text
        )
        asyncio.create_task(
            _persist_message(
                context.user_id, context.family_id,
                MessageRole.assistant, skill_result.response_text,
            )
        )

    # Usage logging
    try:
        assembled = intent_data.get("_assembled")
        if assembled and hasattr(assembled, "token_usage"):
            from src.billing.usage_tracker import log_usage

            tu = assembled.token_usage
            asyncio.create_task(
                log_usage(
                    user_id=context.user_id,
                    family_id=context.family_id,
                    domain=intent_data.get("_agent", ""),
                    skill=intent_name,
                    model=intent_data.get("_model", ""),
                    tokens_input=tu.get("total", 0),
                    tokens_output=0,
                    cache_read_tokens=tu.get("identity", 0),
                )
            )
    except Exception:
        pass

    # Dialog summarization
    asyncio.create_task(summarize_dialog(context.user_id, context.family_id))

    # Session buffer facts
    try:
        from src.core.memory.session_buffer import update_session_buffer

        facts = _extract_session_facts(intent_name, intent_data)
        for fact, category in facts:
            asyncio.create_task(update_session_buffer(context.user_id, fact, category))
    except Exception:
        pass

    # Background tasks from skill
    async def _safe_bg(coro, name: str) -> None:
        try:
            await coro
        except Exception as exc:
            logger.error("Background task %s failed: %s", name, exc)

    for idx, task_fn in enumerate(skill_result.background_tasks):
        try:
            result = task_fn()
            if asyncio.iscoroutine(result):
                asyncio.create_task(_safe_bg(result, f"{intent_name}#{idx}"))
        except Exception:
            pass

    # Undo injection
    try:
        from src.core.undo import UNDO_INTENTS, store_undo

        record_id = intent_data.get("_record_id")
        record_table = intent_data.get("_record_table")
        if intent_name in UNDO_INTENTS and record_id and record_table:
            asyncio.create_task(
                store_undo(context.user_id, intent_name, record_id, record_table)
            )
            undo_btn = {"text": "\u21a9 Undo", "callback": "undo:last"}
            existing_buttons = skill_result.buttons or []
            skill_result = SkillResult(
                response_text=skill_result.response_text,
                buttons=existing_buttons + [undo_btn],
                document=skill_result.document,
                document_name=skill_result.document_name,
                photo_url=skill_result.photo_url,
                photo_bytes=skill_result.photo_bytes,
                chart_url=skill_result.chart_url,
                background_tasks=[],
                reply_keyboard=skill_result.reply_keyboard,
            )
    except Exception:
        pass

    # Smart suggestions
    if not skill_result.reply_keyboard:
        try:
            from src.core.suggestions import get_suggestions

            suggestions = await get_suggestions(intent_name, context.user_id)
            if suggestions:
                skill_result = SkillResult(
                    response_text=skill_result.response_text,
                    buttons=skill_result.buttons,
                    document=skill_result.document,
                    document_name=skill_result.document_name,
                    photo_url=skill_result.photo_url,
                    photo_bytes=skill_result.photo_bytes,
                    chart_url=skill_result.chart_url,
                    background_tasks=[],
                    reply_keyboard=[{"text": s["text"]} for s in suggestions],
                )
        except Exception:
            pass

    return skill_result


async def _resolve_clarify(
    chosen_intent: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Resolve a clarify disambiguation by executing the chosen intent."""
    import json as _json

    from src.core.db import redis

    key = f"clarify_pending:{context.user_id}"
    raw = await redis.get(key)
    if not raw:
        return OutgoingMessage(
            text="Время выбора истекло. Напишите запрос заново.",
            chat_id=message.chat_id,
        )

    pending = _json.loads(raw)
    await redis.delete(key)

    original_text = pending.get("original_text", "")
    intent_data = pending.get("intent_data", {})
    intent_data["confidence"] = 0.9  # User confirmed

    synthetic_message = IncomingMessage(
        id=message.id,
        user_id=message.user_id,
        chat_id=message.chat_id,
        type=MessageType.text,
        text=original_text,
        raw=message.raw,
    )

    domain_router = get_domain_router()
    try:
        skill_result = await domain_router.route(
            chosen_intent, synthetic_message, context, intent_data
        )
    except Exception as e:
        logger.error("Clarify resolve failed for %s: %s", chosen_intent, e)
        return OutgoingMessage(
            text="Произошла ошибка. Попробуйте ещё раз.",
            chat_id=message.chat_id,
        )

    # Run full side effects (post-gen, persist, summarize, undo, suggestions, etc.)
    skill_result = await _run_post_skill_side_effects(
        chosen_intent, original_text, skill_result, context, intent_data,
    )

    return OutgoingMessage(
        text=skill_result.response_text,
        chat_id=message.chat_id,
        buttons=skill_result.buttons,
        document=skill_result.document,
        document_name=skill_result.document_name,
        photo_url=skill_result.photo_url,
        photo_bytes=skill_result.photo_bytes,
        chart_url=skill_result.chart_url,
        reply_keyboard=skill_result.reply_keyboard,
    )


async def _handle_plan_callback(
    sub_action: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Handle reverse prompt plan callbacks: execute, adjust, cancel."""
    from src.core.reverse_prompt import delete_pending_plan, get_pending_plan

    pending = await get_pending_plan(context.user_id)
    if not pending:
        return OutgoingMessage(
            text="Plan expired. Please send your request again.",
            chat_id=message.chat_id,
        )

    if sub_action == "cancel":
        await delete_pending_plan(context.user_id)
        return OutgoingMessage(text="Cancelled.", chat_id=message.chat_id)

    if sub_action == "adjust":
        await delete_pending_plan(context.user_id)
        return OutgoingMessage(
            text="Got it — rephrase your request and I'll try again.",
            chat_id=message.chat_id,
        )

    if sub_action == "execute":
        await delete_pending_plan(context.user_id)
        intent = pending["intent"]
        original_text = pending["original_text"]
        plan_intent_data = pending.get("intent_data", {})

        synthetic = IncomingMessage(
            id=message.id,
            user_id=message.user_id,
            chat_id=message.chat_id,
            type=MessageType.text,
            text=original_text,
            raw=message.raw,
        )

        domain_router = get_domain_router()
        try:
            skill_result = await domain_router.route(
                intent,
                synthetic,
                context,
                plan_intent_data,
            )
        except Exception as e:
            logger.error("Plan execution failed for %s: %s", intent, e)
            return OutgoingMessage(
                text="Execution failed. Please try again.",
                chat_id=message.chat_id,
            )

        # Run full side effects (post-gen, persist, summarize, undo, suggestions, etc.)
        skill_result = await _run_post_skill_side_effects(
            intent, original_text, skill_result, context, plan_intent_data,
        )

        return OutgoingMessage(
            text=skill_result.response_text,
            chat_id=message.chat_id,
            buttons=skill_result.buttons,
            document=skill_result.document,
            document_name=skill_result.document_name,
            photo_url=skill_result.photo_url,
            photo_bytes=skill_result.photo_bytes,
            chart_url=skill_result.chart_url,
            reply_keyboard=skill_result.reply_keyboard,
        )

    return OutgoingMessage(text="Unknown action.", chat_id=message.chat_id)


async def _resume_graph(
    thread_id: str,
    answer: str,
    message: IncomingMessage,
) -> OutgoingMessage:
    """Resume a paused LangGraph (approval or email HITL)."""
    if thread_id.startswith("approval-"):
        from src.orchestrators.approval.graph import resume_approval

        result_text = await resume_approval(thread_id, answer)
        return OutgoingMessage(text=result_text, chat_id=message.chat_id)

    if thread_id.startswith("email-"):
        from src.orchestrators.email.graph import EmailOrchestrator

        orch = EmailOrchestrator()
        skill_result = await orch.resume(thread_id, answer)
        return OutgoingMessage(
            text=skill_result.response_text,
            chat_id=message.chat_id,
        )

    if thread_id.startswith("booking-"):
        from src.orchestrators.booking.graph import BookingOrchestrator

        orch = BookingOrchestrator()
        skill_result = await orch.resume(thread_id, answer)
        return OutgoingMessage(
            text=skill_result.response_text,
            chat_id=message.chat_id,
            buttons=skill_result.buttons,
        )

    return OutgoingMessage(
        text="Unknown graph thread.",
        chat_id=message.chat_id,
    )


async def _execute_pending_action(
    pending_id: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Execute a confirmed pending action (send email, create event, etc.)."""
    from src.core.pending_actions import delete_pending_action, get_pending_action

    pending = await get_pending_action(pending_id)
    if not pending:
        return OutgoingMessage(
            text="Время подтверждения истекло. Повторите запрос.",
            chat_id=message.chat_id,
        )

    # Verify ownership: only the user who created the action can execute it
    if pending.get("user_id") != context.user_id:
        logger.warning(
            "Pending action ownership mismatch: action user %s != caller %s",
            pending.get("user_id"), context.user_id,
        )
        return OutgoingMessage(
            text="Это действие вам не принадлежит.",
            chat_id=message.chat_id,
        )

    intent = pending["intent"]
    action_data = pending["action_data"]
    await delete_pending_action(pending_id)

    try:
        if intent == "send_email":
            from src.skills.send_email.handler import execute_send

            result_text = await execute_send(action_data, context.user_id)

        elif intent == "create_event":
            from src.skills.create_event.handler import execute_create_event

            result_text = await execute_create_event(action_data, context.user_id)

        elif intent == "reschedule_event":
            from src.skills.reschedule_event.handler import (
                execute_reschedule,
            )

            result_text = await execute_reschedule(action_data, context.user_id)

        elif intent == "undo_last":
            from src.skills.undo_last.handler import execute_undo

            result_text = await execute_undo(action_data, context.user_id, context.family_id)

        elif intent == "delete_data":
            from src.skills.delete_data.handler import execute_delete

            result_text = await execute_delete(action_data, context.user_id, context.family_id)

        elif intent == "browser_action":
            from src.tools import browser_service

            task_text = action_data.get("task", "")
            site = action_data.get("site", "")
            result = await browser_service.execute_with_session(
                user_id=context.user_id,
                family_id=context.family_id,
                site=site,
                task=task_text,
            )
            if result["success"]:
                result_text = result["result"]
            else:
                result_text = f"Browser task failed: {result['result']}"

        elif intent == "write_sheets":
            from src.skills.write_sheets.handler import execute_write_sheets

            result_text = await execute_write_sheets(action_data, context.user_id)

        elif intent == "data_tool_delete":
            from src.tools.data_tools import delete_record_confirmed

            result_text = await delete_record_confirmed(
                family_id=context.family_id,
                user_id=context.user_id,
                table=action_data["table"],
                record_id=action_data["record_id"],
            )

        elif intent == "delete_all":
            from src.core.gdpr import MemoryGDPR

            gdpr = MemoryGDPR()
            async with async_session() as session:
                await gdpr.delete_user_data(session, context.user_id)
            result_text = "Все ваши данные удалены. Для нового старта отправьте /start"

        else:
            result_text = "Неизвестное действие."
    except Exception as e:
        logger.error("Pending action %s failed: %s", intent, e)
        result_text = "Ошибка при выполнении. Попробуйте ещё раз."

    return OutgoingMessage(text=result_text, chat_id=message.chat_id)


async def _handle_stats_callback(
    sub: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Handle stats:weekly and stats:trend callbacks with multi-period data."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from src.core.charts import create_pie_chart
    from src.core.models.category import Category

    today = date.today()
    fid = uuid.UUID(context.family_id)

    if sub == "weekly":
        # Last 4 full weeks breakdown
        # Current week start (Monday)
        week_start = today - timedelta(days=today.weekday())
        weeks: list[tuple[date, date, str]] = []
        for i in range(4):
            end = week_start - timedelta(weeks=i)
            start = end - timedelta(days=7)
            label = f"{start.strftime('%d.%m')}–{(end - timedelta(days=1)).strftime('%d.%m')}"
            weeks.append((start, end, label))
        weeks.reverse()

        lines: list[str] = ["<b>📊 Расходы по неделям</b>\n"]
        grand_total = Decimal("0")
        async with async_session() as session:
            for start, end, label in weeks:
                result = await session.execute(
                    select(func.sum(Transaction.amount)).where(
                        Transaction.family_id == fid,
                        Transaction.date >= start,
                        Transaction.date < end,
                        Transaction.type == TransactionType.expense,
                    )
                )
                total = result.scalar() or Decimal("0")
                grand_total += total
                bar = "█" * max(1, int(float(total) / 50)) if total > 0 else "░"
                lines.append(f"{label}: <b>${float(total):.2f}</b> {bar}")

        lines.append(f"\nИтого: <b>${float(grand_total):.2f}</b>")
        return OutgoingMessage(text="\n".join(lines), chat_id=message.chat_id)

    elif sub == "trend":
        # Last 3 months trend with category breakdown
        months: list[tuple[date, date, str]] = []
        for i in range(3):
            if today.month - i > 0:
                m_start = today.replace(month=today.month - i, day=1)
            else:
                m_start = today.replace(year=today.year - 1, month=today.month - i + 12, day=1)
            if m_start.month == 12:
                m_end = m_start.replace(year=m_start.year + 1, month=1, day=1)
            else:
                m_end = m_start.replace(month=m_start.month + 1, day=1)
            month_names = {
                1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр", 5: "Май", 6: "Июн",
                7: "Июл", 8: "Авг", 9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек",
            }
            label = f"{month_names[m_start.month]} {m_start.year}"
            months.append((m_start, m_end, label))
        months.reverse()

        lines = ["<b>📈 Тренд расходов</b>\n"]
        totals: list[float] = []
        chart_labels: list[str] = []
        chart_values: list[float] = []
        async with async_session() as session:
            for m_start, m_end, label in months:
                result = await session.execute(
                    select(func.sum(Transaction.amount)).where(
                        Transaction.family_id == fid,
                        Transaction.date >= m_start,
                        Transaction.date < m_end,
                        Transaction.type == TransactionType.expense,
                    )
                )
                total = float(result.scalar() or 0)
                totals.append(total)
                chart_labels.append(label)
                chart_values.append(total)

                change = ""
                if len(totals) >= 2 and totals[-2] > 0:
                    pct = ((total - totals[-2]) / totals[-2]) * 100
                    arrow = "📈" if pct > 0 else "📉"
                    change = f" {arrow} {pct:+.0f}%"
                lines.append(f"{label}: <b>${total:.2f}</b>{change}")

            # Top categories for the full period
            cat_result = await session.execute(
                select(
                    Category.name,
                    func.sum(Transaction.amount).label("total"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == fid,
                    Transaction.date >= months[0][0],
                    Transaction.date < months[-1][1],
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount).desc())
                .limit(5)
            )
            top_cats = cat_result.all()

        grand = sum(totals)
        lines.append(f"\nИтого за 3 мес: <b>${grand:.2f}</b>")

        if top_cats:
            lines.append("\nТоп категории:")
            for name, amount in top_cats:
                lines.append(f"  • {name}: ${float(amount):.2f}")

        chart_url = None
        if any(v > 0 for v in chart_values):
            chart_url = create_pie_chart(chart_labels, chart_values, "Тренд расходов")

        return OutgoingMessage(
            text="\n".join(lines),
            chat_id=message.chat_id,
            chart_url=chart_url,
        )

    return OutgoingMessage(text="Команда обработана.", chat_id=message.chat_id)


async def _handle_callback(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Handle inline button callbacks."""
    data = message.callback_data or ""
    parts = data.split(":")

    if not parts:
        return OutgoingMessage(text="Неизвестная команда.", chat_id=message.chat_id)

    action = parts[0]

    if action == "confirm":
        # Acknowledge confirmation — transaction stays in DB as-is
        return OutgoingMessage(text="✅ Подтверждено!", chat_id=message.chat_id)

    elif action == "cancel":
        # Delete the transaction from DB
        tx_id = parts[1] if len(parts) > 1 else None
        if tx_id:
            try:
                tx_uuid = uuid.UUID(tx_id)
            except ValueError:
                return OutgoingMessage(text="Неверный формат транзакции.", chat_id=message.chat_id)
            try:
                async with async_session() as session:
                    # Verify the transaction belongs to this user's family
                    tx_result = await session.execute(
                        select(Transaction).where(
                            Transaction.id == tx_uuid,
                            Transaction.family_id == uuid.UUID(context.family_id),
                        )
                    )
                    tx = tx_result.scalar_one_or_none()
                    if not tx:
                        return OutgoingMessage(
                            text="Транзакция не найдена.", chat_id=message.chat_id
                        )
                    await session.execute(delete(Transaction).where(Transaction.id == tx_uuid))
                    await session.commit()
                logger.info("Transaction %s deleted by user %s", tx_id, context.user_id)
            except Exception as e:
                logger.error("Failed to delete transaction %s: %s", tx_id, e)
                return OutgoingMessage(
                    text="Ошибка при удалении транзакции.", chat_id=message.chat_id
                )
        return OutgoingMessage(text="❌ Отменено.", chat_id=message.chat_id)

    elif action == "correct":
        # Set conversation state to "correcting" so the next
        # message is treated as a category correction
        tx_id = parts[1] if len(parts) > 1 else None
        if tx_id:
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(UserContext).where(UserContext.user_id == uuid.UUID(context.user_id))
                    )
                    user_ctx = result.scalar_one_or_none()
                    if user_ctx:
                        user_ctx.conversation_state = ConversationState.correcting
                        user_ctx.last_transaction_id = uuid.UUID(tx_id)
                        await session.commit()
            except Exception as e:
                logger.error("Failed to set correcting state for user %s: %s", context.user_id, e)
        return OutgoingMessage(text="Введите правильную категорию:", chat_id=message.chat_id)

    elif action == "onboard":
        sub_action = parts[1] if len(parts) > 1 else "household"

        if sub_action == "lang" and len(parts) >= 3:
            # Language selection: onboard:lang:en / onboard:lang:ru / etc.
            from src.skills.onboarding.handler import (
                ONBOARDING_TEXTS,
                get_onboarding_texts,
            )

            chosen_lang = parts[2]
            if chosen_lang not in ONBOARDING_TEXTS:
                chosen_lang = "en"
            await _set_onboarding_language(message.user_id, chosen_lang)
            await _set_onboarding_state(
                message.user_id, ConversationState.onboarding_awaiting_choice
            )
            t = await get_onboarding_texts(chosen_lang)
            return OutgoingMessage(
                text=t["welcome"],
                chat_id=message.chat_id,
                buttons=[
                    {"text": t["new_account"], "callback": "onboard:new"},
                    {"text": t["join_family"], "callback": "onboard:join"},
                ],
            )

        if sub_action == "new":
            from src.skills.onboarding.handler import get_onboarding_texts

            lang = await _get_onboarding_language(message.user_id) or "en"
            t = await get_onboarding_texts(lang)
            await _set_onboarding_state(
                message.user_id, ConversationState.onboarding_awaiting_activity
            )
            return OutgoingMessage(text=t["ask_activity"], chat_id=message.chat_id)

        elif sub_action == "join":
            from src.skills.onboarding.handler import get_onboarding_texts

            lang = await _get_onboarding_language(message.user_id) or "en"
            t = await get_onboarding_texts(lang)
            await _set_onboarding_state(
                message.user_id, ConversationState.onboarding_awaiting_invite_code
            )
            return OutgoingMessage(text=t["ask_invite"], chat_id=message.chat_id)

        else:
            # Legacy: direct profile selection (e.g. onboard:trucker)
            profile_name = sub_action
            try:
                telegram_id = int(message.user_id)
                owner_name = context.user_id  # fallback
                async with async_session() as session:
                    family, user = await create_family(
                        session=session,
                        owner_telegram_id=telegram_id,
                        owner_name=owner_name,
                        business_type=profile_name if profile_name != "household" else None,
                        language=context.language,
                        currency=context.currency,
                    )
                logger.info(
                    "Onboarded user %s into family %s with profile '%s'",
                    user.id,
                    family.id,
                    profile_name,
                )
            except Exception as e:
                logger.error("Onboarding failed for user %s: %s", message.user_id, e)
                return OutgoingMessage(
                    text="Ошибка при настройке профиля. Попробуйте ещё раз.",
                    chat_id=message.chat_id,
                )
            return OutgoingMessage(
                text=f"Профиль «{profile_name}» настроен! Можете записывать расходы.",
                chat_id=message.chat_id,
            )

    elif action == "stats":
        sub = parts[1] if len(parts) > 1 else ""
        try:
            result = await _handle_stats_callback(sub, message, context)
            return result
        except Exception as e:
            logger.exception("stats:%s callback failed: %s", sub, e)
            return OutgoingMessage(
                text="Не удалось загрузить статистику. Попробуйте позже.",
                chat_id=message.chat_id,
            )

    elif action == "life_search":
        # Period shortcut buttons from life_search results
        period = parts[1] if len(parts) > 1 else "today"
        registry = get_registry()
        skill = registry.get("life_search")
        if skill:
            search_msg = IncomingMessage(
                id=message.id,
                user_id=message.user_id,
                chat_id=message.chat_id,
                type=MessageType.text,
                text="",
            )
            intent_data: dict[str, Any] = {"period": period, "search_query": ""}
            skill_result = await skill.execute(search_msg, context, intent_data)
            return OutgoingMessage(
                text=skill_result.response_text,
                chat_id=message.chat_id,
                buttons=skill_result.buttons,
            )
        return OutgoingMessage(text="Поиск недоступен.", chat_id=message.chat_id)

    elif action == "clarify":
        chosen_intent = parts[1] if len(parts) > 1 else ""
        return await _resolve_clarify(chosen_intent, message, context)

    elif action == "plan":
        sub_action = parts[1] if len(parts) > 1 else ""
        return await _handle_plan_callback(sub_action, message, context)

    elif action == "sched":
        sub_action = parts[1] if len(parts) > 1 else ""
        action_id = parts[2] if len(parts) > 2 else ""
        from src.core.scheduled_actions.callbacks import handle_sched_callback

        result_text = await handle_sched_callback(
            sub_action=sub_action,
            action_id=action_id,
            context=context,
        )
        return OutgoingMessage(text=result_text, chat_id=message.chat_id)

    elif action == "tz_skip":
        from src.skills.onboarding.handler import get_onboarding_texts

        t = await get_onboarding_texts(context.language or "en")
        return OutgoingMessage(
            text=t["tz_skip_confirmed"],
            chat_id=message.chat_id,
            remove_reply_keyboard=True,
        )

    elif action == "undo":
        from src.core.undo import execute_undo

        result_text = await execute_undo(context.user_id, context.family_id)
        return OutgoingMessage(text=result_text, chat_id=message.chat_id)

    elif action == "memory":
        # Memory Vault callback (clear_all)
        sub_action = parts[1] if len(parts) > 1 else ""
        if sub_action == "clear_all":
            from src.core.memory.mem0_client import delete_all_memories

            await delete_all_memories(context.user_id)
            return OutgoingMessage(text="All memories cleared.", chat_id=message.chat_id)
        return OutgoingMessage(text="Memory action handled.", chat_id=message.chat_id)

    elif action == "suggest":
        # Smart suggestions — re-route as new intent
        suggested_intent = parts[1] if len(parts) > 1 else ""
        extra = parts[2] if len(parts) > 2 else None
        if suggested_intent:
            registry = get_registry()
            skill = registry.get(suggested_intent)
            if skill:
                suggest_msg = IncomingMessage(
                    id=message.id,
                    chat_id=message.chat_id,
                    type=MessageType.text,
                    text=extra or "",
                    user_id=message.user_id,
                )
                intent_data: dict[str, Any] = {}
                if extra:
                    intent_data["period"] = extra
                    intent_data["query"] = extra
                skill_result = await skill.execute(suggest_msg, context, intent_data)
                return OutgoingMessage(
                    text=skill_result.response_text,
                    chat_id=message.chat_id,
                    buttons=skill_result.buttons,
                    chart_url=skill_result.chart_url,
                    reply_keyboard=skill_result.reply_keyboard,
                )
        return OutgoingMessage(text="Suggestion handled.", chat_id=message.chat_id)

    elif action == "confirm_action":
        pending_id = parts[1] if len(parts) > 1 else ""
        return await _execute_pending_action(pending_id, message, context)

    elif action == "cancel_action":
        pending_id = parts[1] if len(parts) > 1 else ""
        from src.core.pending_actions import delete_pending_action, get_pending_action

        pending = await get_pending_action(pending_id)
        if pending and pending.get("user_id") != context.user_id:
            return OutgoingMessage(
                text="Это действие вам не принадлежит.",
                chat_id=message.chat_id,
            )
        await delete_pending_action(pending_id)
        return OutgoingMessage(text="❌ Отменено.", chat_id=message.chat_id)

    elif action == "video":
        # Video follow-up actions (YouTube / TikTok)
        video_action = parts[1] if len(parts) > 1 else "deeper"
        from src.skills.video_action.handler import handle_video_callback

        skill_result = await handle_video_callback(
            video_action, context.user_id, context.language or "en"
        )
        # save / save_content: perform actual Mem0 write here (we have user_id)
        if video_action in ("save", "save_content"):
            from src.core.memory.mem0_client import add_memory
            from src.core.video_session import get_video_session

            session = await get_video_session(context.user_id)
            if session:
                if video_action == "save_content":
                    last_text = session.extra.get("last_text", "")
                    content = last_text or f"Saved video: {session.url}"
                    mem_type = "saved_content"
                else:
                    content = f"Saved video: {session.url}"
                    if session.analysis:
                        content += f"\n\nSummary: {session.analysis[:500]}"
                    mem_type = "saved_video"
                await add_memory(
                    content,
                    user_id=context.user_id,
                    metadata={"category": "content", "type": mem_type},
                )
        return OutgoingMessage(
            text=skill_result.response_text,
            chat_id=message.chat_id,
            buttons=skill_result.buttons,
        )

    elif action == "graph_resume":
        # Resume a paused LangGraph (approval or email HITL)
        thread_id = parts[1] if len(parts) > 1 else ""
        answer = parts[2] if len(parts) > 2 else "no"
        return await _resume_graph(thread_id, answer, message)

    # ── Taxi booking flow callbacks ──

    elif action == "taxi_login_ready":
        from src.tools import taxi_booking

        result = await taxi_booking.handle_login_ready(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "taxi_select":
        from src.tools import taxi_booking

        index = int(parts[2]) if len(parts) > 2 else 0
        result = await taxi_booking.handle_option_selection(context.user_id, index)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "taxi_confirm":
        from src.tools import taxi_booking

        result = await taxi_booking.confirm_booking(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "taxi_back":
        from src.tools import taxi_booking

        result = await taxi_booking.handle_back_to_options(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "taxi_cancel":
        from src.tools import taxi_booking

        await taxi_booking.cancel_flow(context.user_id)
        return OutgoingMessage(text="Taxi booking cancelled.", chat_id=message.chat_id)

    # ── Hotel booking flow callbacks ──

    elif action == "hotel_platform":
        from src.tools import browser_booking

        platform = parts[2] if len(parts) > 2 else ""
        result = await browser_booking.handle_platform_choice(context.user_id, platform)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_login_ready":
        from src.tools import browser_booking

        result = await browser_booking.handle_login_ready(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_select":
        from src.tools import browser_booking

        index = int(parts[2]) if len(parts) > 2 else 0
        result = await browser_booking.handle_hotel_selection(context.user_id, index)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_sort":
        from src.tools import browser_booking

        sort_type = parts[2] if len(parts) > 2 else "price"
        result = await browser_booking.handle_sort_change(context.user_id, sort_type)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_more":
        from src.tools import browser_booking

        result = await browser_booking.handle_more_results(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_confirm":
        from src.tools import browser_booking

        result = await browser_booking.execute_booking(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_confirm_final":
        from src.tools import browser_booking

        result = await browser_booking.confirm_booking(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
        )

    elif action == "hotel_back":
        from src.tools import browser_booking

        result = await browser_booking.handle_back_to_results(context.user_id)
        return OutgoingMessage(
            text=result.get("text", ""),
            chat_id=message.chat_id,
            buttons=result.get("buttons"),
        )

    elif action == "hotel_cancel":
        from src.tools import browser_booking

        await browser_booking.cancel_flow(context.user_id)
        return OutgoingMessage(text="Hotel search cancelled.", chat_id=message.chat_id)

    elif action == "show_code":
        from src.core.db import redis

        prog_id = parts[1] if len(parts) > 1 else ""
        raw = await redis.get(f"program:{prog_id}")
        if raw:
            payload = raw if isinstance(raw, str) else raw.decode("utf-8")
            # Format: "filename\n---\ncode"
            if "\n---\n" in payload:
                filename, code = payload.split("\n---\n", 1)
            else:
                filename, code = "program.py", payload
            return OutgoingMessage(
                text=f"<b>{filename}</b>",
                chat_id=message.chat_id,
                document=code.encode("utf-8"),
                document_name=filename,
            )
        return OutgoingMessage(
            text="Code expired. Generate a new program.",
            chat_id=message.chat_id,
        )

    elif action == "doc_save":
        # Retrieve full data from Redis: doc_save:<pending_id>
        pending_id = parts[1] if len(parts) > 1 else ""
        return await _save_scanned_document(pending_id, message, context)

    elif action == "receipt_confirm":
        # Load full receipt data from Redis pending store
        pending_id = parts[1] if len(parts) > 1 else ""
        from src.skills.scan_receipt.handler import (
            delete_pending_receipt,
            get_pending_receipt,
        )

        pending = await get_pending_receipt(pending_id) if pending_id else None
        if pending:
            from src.core.schemas.receipt import ReceiptData

            receipt = ReceiptData(**pending["receipt"])
            merchant = receipt.merchant or "Unknown"
            total = receipt.total or Decimal("0")
            tx_date = (
                date.fromisoformat(receipt.date) if receipt.date else date.today()
            )
            gallons = receipt.gallons
            price_per_gallon = receipt.price_per_gallon
            state = receipt.state
        else:
            # Fallback: parse from callback parts (legacy format)
            merchant = parts[1] if len(parts) > 1 else "Unknown"
            total = Decimal(parts[2]) if len(parts) > 2 else Decimal("0")
            tx_date = date.today()
            gallons = None
            price_per_gallon = None
            state = None

        try:
            # Resolve category: merchant mapping → fuel detection → smart fallback
            category_id = _resolve_receipt_category(
                merchant, gallons, context,
            )

            async with async_session() as session:
                meta = {"source": "receipt_scan"}
                if gallons:
                    meta["gallons"] = gallons
                    if price_per_gallon:
                        meta["price_per_gallon"] = float(price_per_gallon)

                # Resolve scope from category
                tx_scope = Scope.business if context.business_type else Scope.family
                for cat in context.categories:
                    if cat["id"] == category_id:
                        tx_scope = Scope(cat.get("scope", "family"))
                        break

                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=uuid.UUID(category_id),
                    type=TransactionType.expense,
                    amount=total,
                    merchant=merchant,
                    description=f"Чек: {merchant}",
                    date=tx_date,
                    scope=tx_scope,
                    state=state,
                    ai_confidence=Decimal("0.9"),
                    meta=meta,
                )
                session.add(tx)
                await session.commit()

            if pending_id:
                await delete_pending_receipt(pending_id)

            logger.info(
                "Receipt transaction created: merchant=%s total=%s for user %s",
                merchant,
                total,
                context.user_id,
            )
        except Exception as e:
            logger.error("Failed to create receipt transaction: %s", e)
            return OutgoingMessage(
                text=_receipt_t("save_error", context),
                chat_id=message.chat_id,
            )
        return OutgoingMessage(
            text=_receipt_t("saved_ok", context), chat_id=message.chat_id,
        )

    elif action == "receipt_scope":
        # receipt_scope:{pending_id}:{scope} — user chose business or personal
        pending_id = parts[1] if len(parts) > 1 else ""
        chosen_scope = parts[2] if len(parts) > 2 else "family"
        from src.skills.scan_receipt.handler import (
            delete_pending_receipt,
            get_pending_receipt,
        )

        pending = await get_pending_receipt(pending_id) if pending_id else None
        if not pending:
            return OutgoingMessage(
                text=_receipt_t("receipt_expired", context),
                chat_id=message.chat_id,
            )

        from src.core.schemas.receipt import ReceiptData

        receipt = ReceiptData(**pending["receipt"])
        merchant = receipt.merchant or "Unknown"
        total = receipt.total or Decimal("0")
        tx_date = (
            date.fromisoformat(receipt.date) if receipt.date else date.today()
        )
        gallons = receipt.gallons
        price_per_gallon = receipt.price_per_gallon
        state = receipt.state

        try:
            category_id = _resolve_receipt_category_for_scope(
                merchant, gallons, chosen_scope, context,
            )

            async with async_session() as session:
                meta = {"source": "receipt_scan"}
                if gallons:
                    meta["gallons"] = gallons
                    if price_per_gallon:
                        meta["price_per_gallon"] = float(price_per_gallon)

                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=uuid.UUID(category_id),
                    type=TransactionType.expense,
                    amount=total,
                    merchant=merchant,
                    description=merchant,
                    date=tx_date,
                    scope=Scope(chosen_scope),
                    state=state,
                    ai_confidence=Decimal("0.9"),
                    meta=meta,
                )
                session.add(tx)
                await session.commit()

            await delete_pending_receipt(pending_id)
            scope_label = "\U0001f3e2" if chosen_scope == "business" else "\U0001f3e0"
            return OutgoingMessage(
                text=_receipt_t(
                    "saved_ok_scope", context, scope_label=scope_label,
                ),
                chat_id=message.chat_id,
            )
        except Exception as e:
            logger.error("Failed to save scoped receipt: %s", e)
            return OutgoingMessage(
                text=_receipt_t("save_error", context),
                chat_id=message.chat_id,
            )

    elif action == "receipt_cancel":
        # Clean up pending receipt from Redis
        cancel_pending_id = parts[1] if len(parts) > 1 else ""
        if cancel_pending_id:
            from src.skills.scan_receipt.handler import delete_pending_receipt

            await delete_pending_receipt(cancel_pending_id)
        return OutgoingMessage(text="❌ Отменено.", chat_id=message.chat_id)

    # ------------------------------------------------------------------
    # Invoice callbacks
    # ------------------------------------------------------------------
    elif action == "invoice_confirm":
        pending_id = parts[1] if len(parts) > 1 else ""
        from src.billing.sales_tax import resolve_sales_tax_for_invoice
        from src.skills.generate_invoice.handler import (
            delete_pending_invoice,
            generate_invoice_pdf,
            get_pending_invoice,
            is_pending_invoice_owner,
            save_invoice_to_db,
        )

        inv_data = await get_pending_invoice(pending_id) if pending_id else None
        if not inv_data:
            return OutgoingMessage(
                text=_invoice_t("expired", context),
                chat_id=message.chat_id,
            )
        if not is_pending_invoice_owner(inv_data, context):
            return OutgoingMessage(
                text=_invoice_t("not_allowed", context),
                chat_id=message.chat_id,
            )

        try:
            tax_result = await resolve_sales_tax_for_invoice(inv_data)
            if not tax_result.get("ok"):
                return OutgoingMessage(
                    text=_invoice_t(tax_result.get("message_key", "tax_provider_error"), context),
                    chat_id=message.chat_id,
                )
            inv_data["subtotal"] = tax_result["subtotal"]
            inv_data["tax_amount"] = tax_result["tax_amount"]
            inv_data["tax_rate"] = tax_result["tax_rate"]
            inv_data["tax_source"] = tax_result.get("source")
            inv_data["tax_jurisdiction"] = tax_result.get("jurisdiction")
            inv_data["total"] = tax_result["total"]
            inv_data["draft_state"] = "confirmed"

            pdf_bytes = await generate_invoice_pdf(inv_data)
            await save_invoice_to_db(inv_data)
            await delete_pending_invoice(pending_id)
            filename = f"invoice_{inv_data['invoice_number']}.pdf"
            return OutgoingMessage(
                text=_invoice_t(
                    "generated",
                    context,
                    number=inv_data["invoice_number"],
                    name=inv_data["client_name"],
                    symbol=inv_data["currency_symbol"],
                    total=f"{inv_data['total']:.2f}",
                    due=inv_data["due_date"],
                ),
                chat_id=message.chat_id,
                document=pdf_bytes,
                document_name=filename,
            )
        except Exception as e:
            logger.error("Invoice PDF generation failed: %s", e)
            return OutgoingMessage(
                text=_invoice_t("pdf_failed", context),
                chat_id=message.chat_id,
            )

    elif action == "invoice_edit":
        pending_id = parts[1] if len(parts) > 1 else ""
        return OutgoingMessage(
            text=_invoice_t("edit_hint", context),
            chat_id=message.chat_id,
        )

    elif action == "invoice_cancel":
        pending_id = parts[1] if len(parts) > 1 else ""
        if pending_id:
            from src.skills.generate_invoice.handler import delete_pending_invoice

            await delete_pending_invoice(pending_id)
        return OutgoingMessage(
            text=_invoice_t("cancelled", context),
            chat_id=message.chat_id,
        )

    # ------------------------------------------------------------------
    # Clarification callbacks (period / export type selection)
    # ------------------------------------------------------------------
    elif action == "period_select":
        pending_id = parts[1] if len(parts) > 1 else ""
        chosen_period = parts[2] if len(parts) > 2 else "month"
        return await _handle_period_select(pending_id, chosen_period, message, context)

    elif action == "export_select":
        pending_id = parts[1] if len(parts) > 1 else ""
        chosen_type = parts[2] if len(parts) > 2 else "expenses"
        return await _handle_export_select(pending_id, chosen_type, message, context)

    elif action == "project":
        from src.skills.project_manager.handler import handle_project_callback

        language = context.language or "en"
        text = await handle_project_callback(data, uuid.UUID(context.user_id), language)
        return OutgoingMessage(text=text, chat_id=message.chat_id)

    elif action == "email_reply":
        import json as _json
        from src.core.db import redis as _redis_email
        reply_key = parts[1] if len(parts) > 1 else ""
        raw = await _redis_email.get(f"email_reply:{reply_key}") if reply_key else None
        if not raw:
            return OutgoingMessage(text="Ссылка устарела. Откройте письмо заново.", chat_id=message.chat_id)
        reply_data = _json.loads(raw)
        from src.core.google_auth import get_google_client as _get_gc
        from src.core.llm.clients import generate_text as _gen
        google = await _get_gc(context.user_id)
        if not google:
            return OutgoingMessage(text="Нет подключения к Gmail. Попробуйте /connect", chat_id=message.chat_id)
        thread_msgs = await google.get_thread(reply_data["thread_id"])
        thread_text = "\n---\n".join(
            f"From: {m.get('from','')}\n{m.get('snippet','')}"
            for m in [{"from": t.get("payload",{}).get("headers",[{}])[0].get("value",""), "snippet": t.get("snippet","")} for t in thread_msgs]
        )
        system = f"Draft a reply to this email thread. Be concise, professional. Language: {context.language or 'ru'}."
        reply_body = await _gen("claude-sonnet-4-6", system, [{"role": "user", "content": thread_text}], max_tokens=512)
        from src.core.pending_actions import store_pending_action as _spa
        pending_id = await _spa(
            intent="send_email",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "email_to": reply_data.get("to", ""),
                "email_subject": f"Re: {reply_data.get('subject', '')}",
                "email_body": reply_body,
                "thread_id": reply_data.get("thread_id", ""),
            },
        )
        preview = (
            f"<b>Черновик ответа:</b>\n\n"
            f"<b>To:</b> {reply_data.get('to','')}\n"
            f"<b>Subject:</b> Re: {reply_data.get('subject','')}\n\n"
            f"{reply_body[:500]}"
        )
        return OutgoingMessage(
            text=preview,
            chat_id=message.chat_id,
            buttons=[
                {"text": "📨 Отправить", "callback": f"confirm_action:{pending_id}"},
                {"text": "❌ Отмена", "callback": f"cancel_action:{pending_id}"},
            ],
        )

    elif action == "email_trash":
        message_id = parts[1] if len(parts) > 1 else ""
        if not message_id:
            return OutgoingMessage(text="Ошибка: ID письма не найден.", chat_id=message.chat_id)
        from src.core.google_auth import get_google_client as _get_gc2
        google = await _get_gc2(context.user_id)
        if not google:
            return OutgoingMessage(text="Нет подключения к Gmail.", chat_id=message.chat_id)
        try:
            await google.trash_message(message_id)
            return OutgoingMessage(text="🗑 Письмо перемещено в корзину.", chat_id=message.chat_id)
        except Exception as _e:
            logger.warning("Email trash failed: %s", _e)
            return OutgoingMessage(text="Не удалось переместить письмо. Попробуйте позже.", chat_id=message.chat_id)

    elif action == "email_download":
        import json as _json2
        from src.core.db import redis as _redis_att
        att_key = parts[1] if len(parts) > 1 else ""
        raw = await _redis_att.get(f"email_att:{att_key}") if att_key else None
        if not raw:
            return OutgoingMessage(text="Ссылка устарела. Откройте письмо заново.", chat_id=message.chat_id)
        att_data = _json2.loads(raw)
        from src.core.google_auth import get_google_client as _get_gc3
        google = await _get_gc3(context.user_id)
        if not google:
            return OutgoingMessage(text="Нет подключения к Gmail.", chat_id=message.chat_id)
        try:
            file_bytes = await google.get_attachment(att_data["message_id"], att_data["attachment_id"])
            if not file_bytes:
                return OutgoingMessage(text="Не удалось скачать вложение.", chat_id=message.chat_id)
            return OutgoingMessage(
                text=f"📎 {att_data['filename']}",
                chat_id=message.chat_id,
                document=file_bytes,
                document_name=att_data["filename"],
            )
        except Exception as _e:
            logger.warning("Email attachment download failed: %s", _e)
            return OutgoingMessage(text="Ошибка при скачивании вложения.", chat_id=message.chat_id)

    return OutgoingMessage(text="Команда обработана.", chat_id=message.chat_id)


async def _handle_period_select(
    pending_id: str,
    chosen_period: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Resume a skill after user selected a period."""
    from src.skills._clarification import delete_pending, get_pending

    pending = await get_pending(pending_id) if pending_id else None
    if not pending:
        from src.skills._clarification import _STRINGS as _CLR_STRINGS
        from src.skills._i18n import t_cached

        lang = context.language or "en"
        return OutgoingMessage(
            text=t_cached(_CLR_STRINGS, "expired", lang, namespace="clarification"),
            chat_id=message.chat_id,
        )

    skill_name = pending["skill"]
    intent_data = pending.get("intent_data") or {}
    intent_data["period"] = chosen_period
    original_text = pending.get("text", "")

    await delete_pending(pending_id)

    registry = get_registry()
    skill = registry.get(skill_name)
    if not skill:
        return OutgoingMessage(text="Skill not found.", chat_id=message.chat_id)

    resume_msg = IncomingMessage(
        id=message.id,
        user_id=message.user_id,
        chat_id=message.chat_id,
        type=MessageType.text,
        text=original_text,
    )
    skill_result = await skill.execute(resume_msg, context, intent_data)

    return OutgoingMessage(
        text=skill_result.response_text,
        chat_id=message.chat_id,
        buttons=skill_result.buttons,
        chart_url=skill_result.chart_url,
        document=skill_result.document,
        document_name=skill_result.document_name,
    )


async def _handle_export_select(
    pending_id: str,
    chosen_type: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Resume export_excel after user selected an export type."""
    from src.skills._clarification import delete_pending, get_pending

    pending = await get_pending(pending_id) if pending_id else None
    if not pending:
        from src.skills._clarification import _STRINGS as _CLR_STRINGS
        from src.skills._i18n import t_cached

        lang = context.language or "en"
        return OutgoingMessage(
            text=t_cached(_CLR_STRINGS, "expired", lang, namespace="clarification"),
            chat_id=message.chat_id,
        )

    intent_data = pending.get("intent_data") or {}
    intent_data["export_type"] = chosen_type
    original_text = pending.get("text", "")

    await delete_pending(pending_id)

    registry = get_registry()
    skill = registry.get("export_excel")
    if not skill:
        return OutgoingMessage(text="Skill not found.", chat_id=message.chat_id)

    resume_msg = IncomingMessage(
        id=message.id,
        user_id=message.user_id,
        chat_id=message.chat_id,
        type=MessageType.text,
        text=original_text,
    )
    skill_result = await skill.execute(resume_msg, context, intent_data)

    return OutgoingMessage(
        text=skill_result.response_text,
        chat_id=message.chat_id,
        buttons=skill_result.buttons,
        document=skill_result.document,
        document_name=skill_result.document_name,
    )


def _receipt_t(key: str, context: SessionContext, **kwargs: str) -> str:
    """Get a localized receipt string using scan_receipt i18n."""
    from src.skills._i18n import t_cached
    from src.skills.scan_receipt.handler import _STRINGS

    lang = context.language or "en"
    return t_cached(_STRINGS, key, lang, "scan_receipt", **kwargs)


def _invoice_t(key: str, context: SessionContext, **kwargs: str) -> str:
    """Get a localized invoice string using generate_invoice i18n."""
    from src.skills._i18n import t_cached
    from src.skills.generate_invoice.handler import _STRINGS as _INV_STRINGS

    lang = context.language or "en"
    return t_cached(_INV_STRINGS, key, lang, "generate_invoice", **kwargs)


_FUEL_CATEGORY_NAMES = {"дизель", "diesel", "fuel", "топливо", "gasoline", "бензин"}


def _resolve_receipt_category(
    merchant: str | None,
    gallons: float | None,
    context: SessionContext,
) -> str:
    """Resolve best category for a receipt.

    Priority: merchant mapping → fuel auto-detect → scope-matching fallback.
    """
    # 1. Merchant mapping lookup
    if merchant and context.merchant_mappings:
        merchant_lower = merchant.lower()
        for mapping in context.merchant_mappings:
            pattern = mapping.get("merchant_pattern", "").lower()
            if pattern and pattern in merchant_lower:
                cat_id = mapping.get("category_id")
                if cat_id:
                    return cat_id

    # 2. Fuel auto-detection: gallons present → smart commercial vs personal
    if gallons:
        from src.skills.scan_receipt.handler import _find_fuel_category

        fuel_cat = _find_fuel_category(context, merchant=merchant, gallons=gallons)
        if fuel_cat:
            return fuel_cat

    # 3. Fallback: prefer category matching current scope
    scope = "business" if context.business_type else "family"
    for cat in context.categories:
        if cat.get("scope") == scope:
            return cat["id"]

    # 4. Last resort: first available category
    return context.categories[0]["id"]


def _resolve_receipt_category_for_scope(
    merchant: str | None,
    gallons: float | None,
    scope: str,
    context: SessionContext,
) -> str:
    """Resolve best category for a receipt with user-chosen scope.

    Like _resolve_receipt_category but forces the target scope instead of auto-detecting.
    Priority: merchant mapping → fuel category for scope → first category for scope.
    """
    # 1. Merchant mapping (may override scope)
    if merchant and context.merchant_mappings:
        merchant_lower = merchant.lower()
        for mapping in context.merchant_mappings:
            pattern = mapping.get("merchant_pattern", "").lower()
            if pattern and pattern in merchant_lower:
                cat_id = mapping.get("category_id")
                if cat_id:
                    return cat_id

    # 2. Fuel: find fuel category matching requested scope
    if gallons:
        for cat in context.categories:
            if cat.get("scope") == scope and cat["name"].lower() in _FUEL_CATEGORY_NAMES:
                return cat["id"]
        # Fallback: any fuel category
        for cat in context.categories:
            if cat["name"].lower() in _FUEL_CATEGORY_NAMES:
                return cat["id"]

    # 3. First category matching requested scope
    for cat in context.categories:
        if cat.get("scope") == scope:
            return cat["id"]

    # 4. Last resort
    return context.categories[0]["id"]


async def _save_scanned_document(
    pending_id: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Save a scanned document from Redis pending data to DB.

    Creates Document record (with OCR data + image) and either
    a Transaction (receipt/invoice) or Load (rate_confirmation).
    """
    from src.skills.scan_document.handler import delete_pending_doc, get_pending_doc

    pending = await get_pending_doc(pending_id)
    if not pending:
        return OutgoingMessage(
            text="Данные документа истекли. Отправьте фото ещё раз.",
            chat_id=message.chat_id,
        )

    doc_type = pending["doc_type"]
    ocr_data = pending["ocr_data"]
    image_b64 = pending["image_b64"]
    mime_type = pending["mime_type"]
    fallback_used = pending["fallback_used"]

    ocr_model = "claude-haiku-4-5" if fallback_used else "gemini-3.1-flash-lite-preview"

    doc_type_enum_map = {
        "receipt": DocumentType.receipt,
        "fuel_receipt": DocumentType.fuel_receipt,
        "invoice": DocumentType.invoice,
        "rate_confirmation": DocumentType.rate_confirmation,
        "other": DocumentType.other,
    }

    # Upload image to Supabase Storage before opening the DB session
    image_bytes = base64.b64decode(image_b64) if image_b64 else None
    storage_path = "pending"
    if image_bytes:
        ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"
        storage_path = await upload_document(
            file_bytes=image_bytes,
            family_id=context.family_id,
            filename=f"scan_{uuid.uuid4().hex[:8]}.{ext}",
            mime_type=mime_type,
            bucket="documents",
        )

    try:
        async with async_session() as session:
            # 1. Create Document record with full OCR data + image
            doc = Document(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                type=doc_type_enum_map.get(doc_type, DocumentType.other),
                storage_path=storage_path,
                ocr_model=ocr_model,
                ocr_raw={"image_b64": image_b64, "mime_type": mime_type},
                ocr_parsed=ocr_data,
                ocr_confidence=Decimal("0.9"),
                ocr_fallback_used=fallback_used,
            )
            session.add(doc)
            await session.flush()

            # Queue background embedding for semantic search
            try:
                from src.core.tasks.document_tasks import async_embed_document

                await async_embed_document.kiq(str(doc.id))
            except Exception:
                pass  # Non-critical: batch_embed_documents cron picks up missed docs

            if doc_type == "rate_confirmation":
                # 2a. Save as Load record with all extracted fields
                pickup = None
                if ocr_data.get("pickup_date"):
                    try:
                        pickup = date.fromisoformat(ocr_data["pickup_date"])
                    except (ValueError, TypeError):
                        pickup = date.today()

                delivery = None
                if ocr_data.get("delivery_date"):
                    try:
                        delivery = date.fromisoformat(ocr_data["delivery_date"])
                    except (ValueError, TypeError):
                        pass

                load = Load(
                    family_id=uuid.UUID(context.family_id),
                    broker=ocr_data.get("broker", "Unknown"),
                    origin=ocr_data.get("origin", ""),
                    destination=ocr_data.get("destination", ""),
                    rate=Decimal(str(ocr_data.get("rate", 0))),
                    ref_number=ocr_data.get("ref_number"),
                    pickup_date=pickup or date.today(),
                    delivery_date=delivery,
                    status=LoadStatus.pending,
                    document_id=doc.id,
                )
                session.add(load)
                await session.commit()

                await delete_pending_doc(pending_id)
                broker = ocr_data.get("broker", "")
                rate_val = ocr_data.get("rate", 0)
                logger.info(
                    "Load saved: broker=%s rate=%s doc_id=%s user=%s",
                    broker,
                    rate_val,
                    doc.id,
                    context.user_id,
                )
                return OutgoingMessage(
                    text=(
                        f"\u2705 Груз сохранён: {broker}, ${rate_val}\n"
                        f"\U0001f4c4 Документ ID: {doc.id}"
                    ),
                    chat_id=message.chat_id,
                )

            elif doc_type in ("receipt", "fuel_receipt", "invoice"):
                # 2b. Save as expense Transaction with full extracted data
                # Smart category: merchant mapping → fuel detection → scope fallback
                category_id = uuid.UUID(
                    _resolve_receipt_category(
                        ocr_data.get("merchant") or ocr_data.get("vendor", ""),
                        ocr_data.get("gallons"),
                        context,
                    )
                )

                if doc_type == "invoice":
                    merchant = ocr_data.get("vendor", "Unknown")
                    amount = Decimal(str(ocr_data.get("total", 0)))
                    tx_date_str = ocr_data.get("date")
                    description = f"Invoice: {merchant}"
                    if ocr_data.get("invoice_number"):
                        description += f" #{ocr_data['invoice_number']}"
                else:
                    merchant = ocr_data.get("merchant", "Unknown")
                    amount = Decimal(str(ocr_data.get("total", 0)))
                    tx_date_str = ocr_data.get("date")
                    description = f"Receipt: {merchant}"

                tx_date = date.today()
                if tx_date_str:
                    try:
                        tx_date = date.fromisoformat(tx_date_str)
                    except (ValueError, TypeError):
                        pass

                meta = {"source": f"scan_{doc_type}"}
                if ocr_data.get("gallons"):
                    meta["gallons"] = ocr_data["gallons"]
                    meta["price_per_gallon"] = ocr_data.get("price_per_gallon")
                if ocr_data.get("items"):
                    meta["items"] = ocr_data["items"]
                if ocr_data.get("tax"):
                    meta["tax"] = str(ocr_data["tax"])

                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=category_id,
                    type=TransactionType.expense,
                    amount=amount,
                    merchant=merchant,
                    description=description,
                    date=tx_date,
                    scope=Scope.business if context.business_type else Scope.family,
                    state=ocr_data.get("state"),
                    document_id=doc.id,
                    ai_confidence=Decimal("0.9"),
                    meta=meta,
                )
                session.add(tx)
                await session.commit()

                await delete_pending_doc(pending_id)
                logger.info(
                    "Document saved: type=%s merchant=%s amount=%s doc_id=%s user=%s",
                    doc_type,
                    merchant,
                    amount,
                    doc.id,
                    context.user_id,
                )
                return OutgoingMessage(
                    text=(
                        f"\u2705 {doc_type.replace('_', ' ').capitalize()} "
                        f"сохранён: {merchant}, ${amount}\n"
                        f"\U0001f4c4 Документ ID: {doc.id}"
                    ),
                    chat_id=message.chat_id,
                )

            else:
                # 2c. Generic document — Document record only (no transaction)
                await session.commit()
                await delete_pending_doc(pending_id)
                logger.info("Generic document saved: doc_id=%s user=%s", doc.id, context.user_id)
                return OutgoingMessage(
                    text=f"\u2705 Документ сохранён\n\U0001f4c4 ID: {doc.id}",
                    chat_id=message.chat_id,
                )

    except Exception as e:
        logger.error("Failed to save scanned document: %s", e, exc_info=True)
        return OutgoingMessage(
            text="Ошибка при сохранении. Попробуйте ещё раз.",
            chat_id=message.chat_id,
        )


# ---------------------------------------------------------------------------
# Location helpers (reverse-geocode, save city, city-from-text)
# ---------------------------------------------------------------------------


async def _reverse_geocode_city(coords_text: str) -> str | None:
    """Reverse-geocode 'lat,lng' string to a city name.

    Uses Google Maps Geocoding API when available, falls back to Nominatim.
    """
    import httpx

    from src.core.config import settings

    try:
        lat, lng = coords_text.split(",")
        lat, lng = lat.strip(), lng.strip()
    except ValueError:
        return None

    # Try Google Maps Geocoding API
    if settings.google_maps_api_key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={
                        "latlng": f"{lat},{lng}",
                        "key": settings.google_maps_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                # Search all results for locality component
                for result in results:
                    for component in result.get("address_components", []):
                        if "locality" in component.get("types", []):
                            return component["long_name"]
                # Fallback: first part of formatted address
                if results:
                    formatted = results[0].get("formatted_address", "")
                    if formatted:
                        return formatted.split(",")[0].strip()
        except Exception as e:
            logger.warning("Google reverse geocode failed: %s", e)

    # Fallback: Nominatim (OpenStreetMap) — free, no key needed
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json", "zoom": 10},
                headers={"User-Agent": "FinanceBot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            address = data.get("address", {})
            return address.get("city") or address.get("town") or address.get("village")
    except Exception as e:
        logger.warning("Nominatim reverse geocode failed: %s", e)

    return None


async def _timezone_from_city(city: str) -> str | None:
    """Resolve timezone from city name via geocoding + timezone API.

    Uses Google Maps (if key available) or Nominatim + TimeAPI.
    Returns IANA timezone string (e.g. 'America/Chicago') or None.
    """
    import httpx

    from src.core.config import settings

    lat, lng = None, None

    # Step 1: Geocode city → lat/lng
    if settings.google_maps_api_key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": city, "key": settings.google_maps_api_key},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if results:
                    loc = results[0]["geometry"]["location"]
                    lat, lng = loc["lat"], loc["lng"]
        except Exception as e:
            logger.warning("Google geocode for city '%s' failed: %s", city, e)

    if lat is None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": city, "format": "json", "limit": 1},
                    headers={"User-Agent": "FinanceBot/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data:
                    lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            logger.warning("Nominatim geocode for city '%s' failed: %s", city, e)

    if lat is None or lng is None:
        return None

    # Step 2: Google Time Zone API (if key available)
    if settings.google_maps_api_key:
        try:
            import time as _time

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/timezone/json",
                    params={
                        "location": f"{lat},{lng}",
                        "timestamp": str(int(_time.time())),
                        "key": settings.google_maps_api_key,
                    },
                )
                resp.raise_for_status()
                tz_data = resp.json()
                if tz_data.get("status") == "OK":
                    return tz_data["timeZoneId"]
        except Exception as e:
            logger.warning("Google timezone API failed: %s", e)

    # Fallback: TimeAPI.io (free, no key)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://timeapi.io/api/timezone/coordinate",
                params={"latitude": lat, "longitude": lng},
            )
            resp.raise_for_status()
            tz_data = resp.json()
            tz_name = tz_data.get("timeZone")
            if tz_name:
                return tz_name
    except Exception as e:
        logger.warning("TimeAPI timezone lookup failed: %s", e)

    return None


async def _save_user_city(user_id: str, city: str) -> str | None:
    """Persist city to the user's profile and update timezone from city.

    Returns resolved IANA timezone string or None.
    """
    tz_name: str | None = None
    try:
        from sqlalchemy import update

        from src.core.models.user import User
        from src.core.models.user_profile import UserProfile

        # Resolve timezone from city
        tz_name = await _timezone_from_city(city)
        values: dict[str, Any] = {"city": city}
        if tz_name:
            values["timezone"] = tz_name
            values["timezone_source"] = "city_geocode"
            values["timezone_confidence"] = 80
            logger.info("Resolved timezone for '%s': %s", city, tz_name)

        async with async_session() as session:
            result = await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == uuid.UUID(user_id))
                .values(**values)
            )
            if result.rowcount == 0:
                # Profile missing — create one
                user = await session.scalar(select(User).where(User.id == uuid.UUID(user_id)))
                if user:
                    profile = UserProfile(
                        user_id=user.id,
                        family_id=user.family_id,
                        display_name=user.name,
                        city=city,
                        preferred_language=user.language,
                    )
                    if tz_name:
                        profile.timezone = tz_name
                        profile.timezone_source = "city_geocode"
                        profile.timezone_confidence = 80
                    session.add(profile)
                else:
                    logger.warning("No user found for user_id %s to save city", user_id)
            await session.commit()
    except Exception as e:
        logger.error("Failed to save user city: %s", e)
    return tz_name


async def _execute_pending_maps_search(
    user_id: str, city: str, message: IncomingMessage
) -> OutgoingMessage | None:
    """Auto-execute a pending maps search after the user shares location.

    Returns OutgoingMessage with search results, or None if no pending search.
    """
    import json

    from src.core.db import redis

    pending_key = f"maps_pending:{user_id}"
    pending_raw = await redis.get(pending_key)
    if not pending_raw:
        return None

    await redis.delete(pending_key)

    try:
        pending = json.loads(pending_raw)
    except (json.JSONDecodeError, TypeError):
        return None

    query = pending.get("query", "")
    if not query:
        return None

    language = pending.get("language", "en")
    maps_mode = pending.get("maps_mode", "search")
    destination = pending.get("destination", "")
    detail_mode = pending.get("detail_mode", False)

    # Enrich query with resolved city
    enriched_query = f"{query}, {city}"
    location_hint = (
        f"\nUser's location: {city}. "
        "For 'nearby' queries, ONLY show places in or near this city. "
        "Do NOT show places from other cities or countries."
    )

    from src.core.config import settings
    from src.skills.maps_search.handler import (
        get_directions,
        search_places,
        search_places_grounding,
    )

    has_api_key = bool(settings.google_maps_api_key)

    try:
        if detail_mode and has_api_key:
            if maps_mode == "directions" and destination:
                answer = await get_directions(enriched_query, destination, language)
            else:
                answer = await search_places(enriched_query, language)
        else:
            grounding_query = enriched_query
            if maps_mode == "directions" and destination:
                grounding_query = f"directions from {enriched_query} to {destination}"
            answer = await search_places_grounding(
                grounding_query,
                language,
                location_hint=location_hint,
                original_message=query,
            )
    except Exception as e:
        logger.error("Pending maps search failed: %s", e)
        return OutgoingMessage(
            text=f"Got it — your location is set to <b>{city}</b>. Now try your search again!",
            chat_id=message.chat_id,
            remove_reply_keyboard=True,
        )

    return OutgoingMessage(
        text=answer,
        chat_id=message.chat_id,
        remove_reply_keyboard=True,
    )


async def _check_browser_taxi_flow(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage | None:
    """Check if user has an active taxi booking flow."""
    from src.tools import taxi_booking

    state = await taxi_booking.get_taxi_state(context.user_id)
    if not state:
        return None

    step = state.get("step")
    if step not in ("awaiting_destination", "awaiting_login", "awaiting_selection", "confirming"):
        return None

    result = await taxi_booking.handle_text_input(context.user_id, message.text or "")
    if not result:
        return None

    return OutgoingMessage(
        text=result["text"],
        chat_id=message.chat_id,
        buttons=result.get("buttons"),
    )


async def _check_browser_login_flow(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage | None:
    """Check if user has an active browser login flow and handle the next step.

    Returns an OutgoingMessage if a login step was handled, None otherwise.
    """
    from src.tools import browser_login, browser_service

    login_state = await browser_login.get_login_state(context.user_id)
    if not login_state:
        return None

    # User has an active login flow — intercept this message
    result = await browser_login.handle_step(
        user_id=context.user_id,
        family_id=context.family_id,
        message_text=message.text or "",
        chat_id=message.chat_id,
        message_id=message.id,
    )

    action = result.get("action", "error")
    text = result.get("text", "")
    screenshot = result.get("screenshot_bytes")

    if action == "login_success":
        # Login succeeded — check for pending hotel booking flow first
        from src.tools import browser_booking

        booking_state = await browser_booking.get_booking_state(context.user_id)
        if booking_state and booking_state.get("step") == "awaiting_login":
            # Resume hotel booking flow — search with fresh cookies
            booking_result = await browser_booking.check_auth_and_search(context.user_id)
            booking_text = booking_result.get("text", "")
            return OutgoingMessage(
                text=f"{text}\n\n{booking_text}",
                chat_id=message.chat_id,
                buttons=booking_result.get("buttons"),
            )

        # No booking flow — execute the original task directly
        task = result.get("task", "")
        site = result.get("site", "")
        if task and site:
            browser_result = await browser_service.execute_with_session(
                user_id=context.user_id,
                family_id=context.family_id,
                site=site,
                task=task,
            )
            task_text = (
                browser_result["result"]
                if browser_result["success"]
                else (f"Login successful but task failed: {browser_result['result']}")
            )
            return OutgoingMessage(
                text=f"{text}\n\n{task_text}",
                chat_id=message.chat_id,
            )
        return OutgoingMessage(text=text, chat_id=message.chat_id)

    if action == "no_flow":
        return None

    return OutgoingMessage(
        text=text,
        chat_id=message.chat_id,
        photo_bytes=screenshot,
    )


async def _check_browser_booking_flow(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage | None:
    """Check if user has an active hotel booking flow.

    Handles text input during various states:
    - awaiting_selection: hotel number/name, sort commands, filter requests
    - awaiting_login: "готово"/"ready" to check session
    - confirming: "да"/"yes" to confirm, "нет"/"no" to go back
    """
    from src.tools import browser_booking

    state = await browser_booking.get_booking_state(context.user_id)
    if not state:
        return None

    step = state.get("step")
    # Only intercept text-based states
    if step not in ("awaiting_selection", "awaiting_login", "confirming"):
        return None

    result = await browser_booking.handle_text_input(context.user_id, message.text or "")
    if not result:
        return None

    return OutgoingMessage(
        text=result["text"],
        chat_id=message.chat_id,
        buttons=result.get("buttons"),
    )



