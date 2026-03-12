"""Finance Bot — FastAPI entrypoint (webhook + health check)."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from api.browser_connect import router as browser_connect_router
from api.browser_extension import router as extension_router
from api.miniapp import router as miniapp_router
from api.oauth import router as oauth_router
from src.core.access import filter_scope_items
from src.core.config import settings
from src.core.context import SessionContext
from src.core.conversation_analytics import (
    apply_trace_review_suggestion,
    apply_trace_review_suggestions_batch,
    emit_conversation_analytics_event,
    get_conversation_analytics_policy,
    get_dataset_candidates,
    get_golden_dialogues,
    get_review_batches,
    get_review_queue_snapshot,
    get_review_results,
    get_user_feedback,
    get_weekly_curation_snapshot,
    ingest_review_trace,
    submit_trace_review,
)
from src.core.db import async_session, redis
from src.core.models.category import Category
from src.core.models.family import Family
from src.core.models.merchant_mapping import MerchantMapping
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.models.workspace_membership import WorkspaceMembership
from src.core.profiles import ProfileLoader
from src.core.release import (
    apply_release_override,
    get_release_flag_snapshot,
    get_release_health_snapshot,
    get_release_ops_overview,
    get_release_override_snapshot,
    get_release_request_plan,
    get_release_rollout_decision,
    log_runtime_event,
    record_release_event,
)
from src.core.request_context import (
    reset_request_context,
    set_request_context,
    update_request_context,
)
from src.core.router import handle_message
from src.gateway.telegram import TelegramGateway
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage
from src.voice.routes import router as voice_router

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

gateway: TelegramGateway | None = None
profile_loader = ProfileLoader("config/profiles")

# Optional channel gateways — initialised only when configured
_slack_gw = None
_whatsapp_gw = None
_sms_gw = None

# Language code → timezone mapping for auto-detection
LANGUAGE_TIMEZONE_MAP = {
    "ru": "Europe/Moscow",
    "uk": "Europe/Kyiv",
    "es": "America/Mexico_City",
    "pt": "America/Sao_Paulo",
    "de": "Europe/Berlin",
    "fr": "Europe/Paris",
    "it": "Europe/Rome",
    "pl": "Europe/Warsaw",
    "tr": "Europe/Istanbul",
    "ja": "Asia/Tokyo",
    "ko": "Asia/Seoul",
    "zh": "Asia/Shanghai",
    "ar": "Asia/Riyadh",
    "hi": "Asia/Kolkata",
    "ky": "Asia/Bishkek",
    "kk": "Asia/Almaty",
    "uz": "Asia/Tashkent",
}


class TraceReviewSubmission(BaseModel):
    trace_key: str
    reviewer: str
    final_label: str
    action: str
    rubric: dict[str, bool]
    notes: str = ""
    labels: list[str] = Field(default_factory=list)


class TraceCandidateSubmission(BaseModel):
    trace_key: str
    channel: str = "telegram"
    chat_id: str = ""
    user_id: str = ""
    message_id: str = ""
    intent: str = ""
    outcome: str = "error"
    review_label: str = ""
    tags: list[str] = Field(default_factory=list)
    message_preview: str = ""
    response_preview: str = ""
    response_has_text: bool | None = None
    response_length: int | None = None
    queued_for_review: bool | None = None
    source: str = "external_trace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceSuggestionApproval(BaseModel):
    trace_key: str
    reviewer: str
    notes: str = ""
    final_label: str | None = None
    action: str | None = None
    labels: list[str] = Field(default_factory=list)


class TraceSuggestionBatchApproval(BaseModel):
    trace_keys: list[str] = Field(default_factory=list)
    reviewer: str
    notes: str = ""
    final_label: str | None = None
    action: str | None = None
    labels: list[str] = Field(default_factory=list)
    selection_limit: int = 100
    max_selected: int = 50
    review_label: str | None = None
    suggested_action: str | None = None
    suggested_final_label: str | None = None
    tag: str | None = None
    source: str | None = None


class ReleaseOverrideSubmission(BaseModel):
    actor: str
    action: str
    rollout_percent: int | None = None
    shadow_mode: bool | None = None
    notes: str = ""


def _require_ops_auth(request: Request) -> None:
    """Protect operator-facing endpoints when HEALTH_SECRET is configured."""
    if settings.health_secret:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") != settings.health_secret:
            raise HTTPException(status_code=401, detail="Unauthorized")


async def _maybe_set_timezone_from_language(user_id: str, language_code: str) -> None:
    """Low-confidence timezone hint from Telegram language_code (runs once per day).

    Skips ambiguous codes like ``en`` (could be US, UK, Australia, India).
    For non-ambiguous languages (ru, ky, etc.) sets timezone with confidence=30.
    Uses the centralized ``maybe_update_timezone`` helper that respects
    the confidence hierarchy and never overwrites higher-confidence sources.
    """
    if not language_code:
        return

    # "en" is ambiguous — could be US, UK, Australia, India, etc.
    # Don't guess timezone from it.
    tz = LANGUAGE_TIMEZONE_MAP.get(language_code)
    if not tz:
        return

    # Only run once per day per user
    cache_key = f"tz_init:{user_id}"
    try:
        already_set = await redis.get(cache_key)
        if already_set:
            return
        await redis.set(cache_key, "1", ex=86400)
    except Exception:
        pass

    from src.core.timezone import maybe_update_timezone

    await maybe_update_timezone(user_id, tz, "channel_hint", 30)


async def _maybe_set_timezone_from_phone(user_id: str, phone_e164: str) -> None:
    """One-time phone-based timezone detection for WhatsApp users."""
    cache_key = f"tz_phone:{user_id}"
    try:
        if await redis.get(cache_key):
            return
        await redis.set(cache_key, "1", ex=86400 * 30)
    except Exception:
        return

    from src.core.timezone import maybe_update_timezone, timezone_from_phone

    tz, confidence = timezone_from_phone(phone_e164)
    if tz:
        source = "phone_number_single" if confidence >= 80 else "phone_number_multi"
        await maybe_update_timezone(user_id, tz, source, confidence)


async def _maybe_set_timezone_from_slack(user_id: str, slack_user_id: str) -> None:
    """One-time Slack API timezone detection via users.info."""
    cache_key = f"tz_slack:{user_id}"
    retry_key = f"tz_slack_retry:{user_id}"
    try:
        if await redis.get(cache_key):
            return
    except Exception:
        pass

    try:
        if await redis.get(retry_key):
            return
    except Exception:
        pass

    if not _slack_gw:
        return

    from src.gateway.slack_gw import SlackRetryableError

    try:
        tz, _locale, should_cache_result = await _slack_gw.get_user_timezone(slack_user_id)
    except SlackRetryableError:
        try:
            await redis.set(retry_key, "1", ex=300)
        except Exception:
            pass
        return

    if tz:
        from src.core.timezone import maybe_update_timezone

        await maybe_update_timezone(user_id, tz, "slack_api", 85)
    if should_cache_result:
        try:
            await redis.set(cache_key, "1", ex=86400 * 7)
        except Exception:
            pass


def _build_user_profile(prof_row) -> dict:
    """Build user_profile dict from a UserProfile SELECT row.

    Row columns: timezone, city, tone_preference, response_length, occupation, learned_patterns.
    """
    if not prof_row:
        return {}
    profile: dict = {}
    city = prof_row[1]
    if city:
        profile["city"] = city
    profile["tone_preference"] = prof_row[2] or "friendly"
    profile["response_length"] = prof_row[3] or "concise"
    occupation = prof_row[4]
    if occupation:
        profile["occupation"] = occupation
    learned = prof_row[5] or {}
    personality = learned.get("personality")
    if personality:
        profile["personality"] = personality
    return profile


def _resolve_membership_access(
    user_role: str,
    membership: WorkspaceMembership | None,
) -> tuple[str, str | None, list[str]]:
    """Resolve the effective role/permissions from membership with legacy fallback."""
    if membership:
        return (
            membership.role.value,
            membership.membership_type.value,
            membership.permissions or [],
        )
    return user_role, None, []


async def build_session_context(telegram_id: str) -> SessionContext | None:
    """Build SessionContext from database for a telegram user."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == int(telegram_id)))
        user = result.scalar_one_or_none()
        if not user:
            return None

        # Load family for currency
        fam_result = await session.execute(select(Family).where(Family.id == user.family_id))
        family = fam_result.scalar_one()

        membership_result = await session.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.family_id == user.family_id,
                WorkspaceMembership.status == "active",
            )
        )
        membership = membership_result.scalar_one_or_none()
        role, membership_type, permissions = _resolve_membership_access(user.role.value, membership)

        # Load categories
        cat_result = await session.execute(
            select(Category).where(Category.family_id == user.family_id)
        )
        categories = [
            {"id": str(c.id), "name": c.name, "scope": c.scope.value, "icon": c.icon}
            for c in cat_result.scalars()
        ]
        categories = filter_scope_items(categories, role)

        # Load merchant mappings
        map_result = await session.execute(
            select(MerchantMapping).where(MerchantMapping.family_id == user.family_id)
        )
        mappings = [
            {
                "merchant_pattern": m.merchant_pattern,
                "category_id": str(m.category_id),
                "scope": m.scope.value,
            }
            for m in map_result.scalars()
        ]
        mappings = filter_scope_items(mappings, role)

        profile = profile_loader.get(user.business_type) or profile_loader.get("household")

        # Load user profile for timezone, city, and personality
        prof_result = await session.execute(
            select(
                UserProfile.timezone,
                UserProfile.city,
                UserProfile.tone_preference,
                UserProfile.response_length,
                UserProfile.occupation,
                UserProfile.learned_patterns,
            )
            .where(UserProfile.user_id == user.id)
            .limit(1)
        )
        prof_row = prof_result.one_or_none()
        user_timezone = prof_row[0] if prof_row else "UTC"

        return SessionContext(
            user_id=str(user.id),
            family_id=str(user.family_id),
            role=role,
            language=user.language,
            currency=family.currency,
            business_type=user.business_type,
            categories=categories,
            merchant_mappings=mappings,
            profile_config=profile,
            timezone=user_timezone,
            user_profile=_build_user_profile(prof_row),
            membership_type=membership_type,
            permissions=permissions,
        )


async def build_context_from_channel(channel: str, channel_user_id: str) -> SessionContext | None:
    """Build SessionContext by resolving a channel user to internal user."""
    from src.gateway.channel_resolver import resolve_user

    user_id, family_id = await resolve_user(channel, channel_user_id)
    if not user_id or not family_id:
        return None

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        fam_result = await session.execute(select(Family).where(Family.id == user.family_id))
        family = fam_result.scalar_one()

        membership_result = await session.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.family_id == user.family_id,
                WorkspaceMembership.status == "active",
            )
        )
        membership = membership_result.scalar_one_or_none()
        role, membership_type, permissions = _resolve_membership_access(user.role.value, membership)

        cat_result = await session.execute(
            select(Category).where(Category.family_id == user.family_id)
        )
        categories = [
            {"id": str(c.id), "name": c.name, "scope": c.scope.value, "icon": c.icon}
            for c in cat_result.scalars()
        ]
        categories = filter_scope_items(categories, role)

        map_result = await session.execute(
            select(MerchantMapping).where(MerchantMapping.family_id == user.family_id)
        )
        mappings = [
            {
                "merchant_pattern": m.merchant_pattern,
                "category_id": str(m.category_id),
                "scope": m.scope.value,
            }
            for m in map_result.scalars()
        ]
        mappings = filter_scope_items(mappings, role)

        profile = profile_loader.get(user.business_type) or profile_loader.get("household")

        prof_result = await session.execute(
            select(
                UserProfile.timezone,
                UserProfile.city,
                UserProfile.tone_preference,
                UserProfile.response_length,
                UserProfile.occupation,
                UserProfile.learned_patterns,
            )
            .where(UserProfile.user_id == user.id)
            .limit(1)
        )
        prof_row = prof_result.one_or_none()
        user_timezone = prof_row[0] if prof_row else "UTC"

        return SessionContext(
            user_id=str(user.id),
            family_id=str(user.family_id),
            role=role,
            language=user.language,
            currency=family.currency,
            business_type=user.business_type,
            categories=categories,
            merchant_mappings=mappings,
            profile_config=profile,
            timezone=user_timezone,
            user_profile=_build_user_profile(prof_row),
            membership_type=membership_type,
            permissions=permissions,
        )


async def _typing_loop(gw, chat_id: str, interval: float = 4.0):
    """Send typing indicator every N seconds until cancelled."""
    try:
        while True:
            await gw.send_typing(chat_id)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def on_message(incoming):
    """Main message handler called by Telegram gateway."""
    request_token = set_request_context(
        request_id=str(uuid.uuid4()),
        correlation_id=f"{incoming.channel}:{incoming.chat_id}:{incoming.id}",
    )
    try:
        context = await build_session_context(incoming.user_id)
        release_plan = await get_release_request_plan(context, subject_id=incoming.user_id)
        update_request_context(
            rollout_cohort=release_plan["cohort"],
            rollout_bucket=release_plan["bucket"],
            release_mode=release_plan["mode"],
            release_enabled=release_plan["release_enabled"],
            shadow_enabled=release_plan["shadow_enabled"],
            release_flags=get_release_flag_snapshot(),
        )
        log_runtime_event(
            logger,
            "info",
            "incoming_message_received",
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            user_id=incoming.user_id,
            message_id=incoming.id,
            message_type=incoming.type,
            release_mode=release_plan["mode"],
            release_enabled=release_plan["release_enabled"],
            shadow_enabled=release_plan["shadow_enabled"],
            rollout_bucket=release_plan["bucket"],
            health_status=release_plan["health_status"],
            recommended_action=release_plan["recommended_action"],
        )
        await record_release_event("requests_total")
        if release_plan["shadow_enabled"]:
            await record_release_event("shadow_requests_total")

        if not context:
            # Unregistered user — handle onboarding callbacks and FSM state
            from src.core.models.enums import ConversationState
            from src.core.router import (
                _clear_onboarding_state,
                _get_onboarding_language,
                _get_onboarding_state,
                _set_onboarding_language,
                _set_onboarding_state,
                get_registry,
            )
            from src.skills.onboarding.handler import (
                ONBOARDING_TEXTS,
                get_onboarding_texts,
            )

            if incoming.type == MessageType.callback and incoming.callback_data:
                parts = incoming.callback_data.split(":")
                if len(parts) >= 2 and parts[0] == "onboard":
                    if parts[1] == "lang" and len(parts) >= 3:
                        chosen_lang = parts[2]
                        if chosen_lang not in ONBOARDING_TEXTS:
                            chosen_lang = "en"
                        await _set_onboarding_language(incoming.user_id, chosen_lang)
                        await _set_onboarding_state(
                            incoming.user_id,
                            ConversationState.onboarding_awaiting_choice,
                        )
                        t = await get_onboarding_texts(chosen_lang)
                        await gateway.send(
                            OutgoingMessage(
                                text=t["welcome"],
                                chat_id=incoming.chat_id,
                                buttons=[
                                    {"text": t["new_account"], "callback": "onboard:new"},
                                    {"text": t["join_family"], "callback": "onboard:join"},
                                ],
                            )
                        )
                        return

                    lang = await _get_onboarding_language(incoming.user_id) or "en"
                    t = await get_onboarding_texts(lang)

                    if parts[1] == "new":
                        await _set_onboarding_state(
                            incoming.user_id, ConversationState.onboarding_awaiting_activity
                        )
                        await gateway.send(
                            OutgoingMessage(text=t["ask_activity"], chat_id=incoming.chat_id)
                        )
                        return
                    if parts[1] == "join":
                        await _set_onboarding_state(
                            incoming.user_id,
                            ConversationState.onboarding_awaiting_invite_code,
                        )
                        await gateway.send(
                            OutgoingMessage(text=t["ask_invite"], chat_id=incoming.chat_id)
                        )
                        return

            registry = get_registry()
            onboarding = registry.get("onboarding")

            onboarding_state = await _get_onboarding_state(incoming.user_id)
            chosen_lang = await _get_onboarding_language(incoming.user_id)
            tg_language = chosen_lang or incoming.language or "en"
            intent_data = {"onboarding_state": onboarding_state} if onboarding_state else {}

            typing_task = asyncio.create_task(_typing_loop(gateway, incoming.chat_id))
            try:
                result = await onboarding.execute(
                    incoming,
                    SessionContext(
                        user_id=incoming.user_id,
                        family_id="",
                        role="owner",
                        language=tg_language,
                        currency="USD",
                        business_type=None,
                        categories=[],
                        merchant_mappings=[],
                    ),
                    intent_data,
                )
            finally:
                typing_task.cancel()

            text_raw = (incoming.text or "").strip()
            if text_raw == "/start" or not onboarding_state:
                await _set_onboarding_state(
                    incoming.user_id,
                    ConversationState.onboarding_awaiting_language,
                )

            onboarding_completed = not result.buttons and onboarding_state is not None
            if onboarding_completed:
                await _clear_onboarding_state(incoming.user_id)

            await gateway.send(
                OutgoingMessage(
                    text=result.response_text,
                    chat_id=incoming.chat_id,
                    buttons=result.buttons,
                )
            )

            if onboarding_completed:
                lang = chosen_lang or incoming.language or "en"
                t = await get_onboarding_texts(lang)
                await gateway.send(
                    OutgoingMessage(
                        text=t["tz_location_prompt"],
                        chat_id=incoming.chat_id,
                        reply_keyboard=[
                            {"text": t["share_location_btn"], "request_location": True},
                        ],
                    )
                )
                await gateway.send(
                    OutgoingMessage(
                        text=t["tz_skip_hint"],
                        chat_id=incoming.chat_id,
                        buttons=[{"text": t["tz_skip_btn"], "callback": "tz_skip"}],
                    )
                )
            return

        if incoming.language:
            asyncio.create_task(
                _maybe_set_timezone_from_language(context.user_id, incoming.language)
            )

        _heavy_callbacks = {"taxi_select", "taxi_confirm", "taxi_back"}
        if incoming.type == MessageType.callback and incoming.callback_data:
            cb_action = incoming.callback_data.split(":")[0]
            if cb_action in _heavy_callbacks:
                lang = context.language or "en"
                ack = (
                    "⏳ Обрабатываю, подождите..."
                    if lang == "ru"
                    else "⏳ Processing, please wait..."
                )
                await gateway.send(OutgoingMessage(text=ack, chat_id=incoming.chat_id))

                async def _run_heavy_callback(msg=incoming, ctx=context):
                    try:
                        resp = await handle_message(msg, ctx)
                        await gateway.send(resp)
                    except Exception:
                        logger.exception("Error in heavy callback for user %s", ctx.user_id)
                        err = (
                            "Произошла ошибка. Попробуйте ещё раз."
                            if lang == "ru"
                            else "An error occurred. Please try again."
                        )
                        await gateway.send(OutgoingMessage(text=err, chat_id=msg.chat_id))

                asyncio.create_task(_run_heavy_callback())
                return

        typing_task = asyncio.create_task(_typing_loop(gateway, incoming.chat_id))
        try:
            response = await handle_message(incoming, context)
        except Exception:
            logger.exception("Unhandled error in handle_message for user %s", incoming.user_id)
            await record_release_event("errors_total")
            emit_conversation_analytics_event(
                logger,
                context=context,
                message=incoming,
                outcome="error",
                tags=["handler_exception"],
                force_sample=True,
            )
            response = OutgoingMessage(
                text="Произошла ошибка. Попробуйте ещё раз через пару секунд.",
                chat_id=incoming.chat_id,
            )
        finally:
            typing_task.cancel()
        await gateway.send(response)
        await record_release_event("completed_total")
        if not response.text:
            await record_release_event("no_reply_total")
        log_runtime_event(
            logger,
            "info",
            "incoming_message_completed",
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            user_id=incoming.user_id,
            message_id=incoming.id,
            has_response_text=bool(response.text),
            has_buttons=bool(response.buttons),
        )
    finally:
        reset_request_context(request_token)


async def _process_channel_message(incoming, gw) -> None:
    """Process a channel message in the background (like Telegram _process_update)."""
    try:
        await _handle_channel_message(incoming, gw)
    except Exception:
        logger.exception(
            "Error processing %s message from %s",
            incoming.channel,
            incoming.channel_user_id,
        )


async def _handle_channel_message(incoming, gw):
    """Handle a message from a non-Telegram channel (Slack, WhatsApp, SMS)."""
    typing_task = None
    request_token = set_request_context(
        request_id=str(uuid.uuid4()),
        correlation_id=f"{incoming.channel}:{incoming.chat_id}:{incoming.id}",
    )
    try:
        context = await build_context_from_channel(incoming.channel, incoming.channel_user_id)
        release_plan = await get_release_request_plan(
            context,
            subject_id=incoming.channel_user_id or incoming.user_id,
        )
        update_request_context(
            rollout_cohort=release_plan["cohort"],
            rollout_bucket=release_plan["bucket"],
            release_mode=release_plan["mode"],
            release_enabled=release_plan["release_enabled"],
            shadow_enabled=release_plan["shadow_enabled"],
            release_flags=get_release_flag_snapshot(),
        )
        log_runtime_event(
            logger,
            "info",
            "channel_message_received",
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            user_id=incoming.user_id,
            message_id=incoming.id,
            message_type=incoming.type,
            release_mode=release_plan["mode"],
            release_enabled=release_plan["release_enabled"],
            shadow_enabled=release_plan["shadow_enabled"],
            rollout_bucket=release_plan["bucket"],
            health_status=release_plan["health_status"],
            recommended_action=release_plan["recommended_action"],
        )
        await record_release_event("requests_total")
        if release_plan["shadow_enabled"]:
            await record_release_event("shadow_requests_total")

        if not context:
            # Unregistered channel user — run onboarding (same as Telegram)
            await _handle_channel_onboarding(incoming, gw)
            return

        # Background: channel-specific timezone detection
        if incoming.channel == "whatsapp" and incoming.channel_user_id:
            asyncio.create_task(
                _maybe_set_timezone_from_phone(context.user_id, incoming.channel_user_id)
            )
        elif incoming.channel == "slack" and incoming.channel_user_id:
            asyncio.create_task(
                _maybe_set_timezone_from_slack(context.user_id, incoming.channel_user_id)
            )

        typing_task = asyncio.create_task(_typing_loop(gw, incoming.chat_id))
        response = await handle_message(incoming, context)
        response.chat_id = incoming.chat_id
        response.channel = incoming.channel
        await gw.send(response)
        await record_release_event("completed_total")
        if not response.text:
            await record_release_event("no_reply_total")
        log_runtime_event(
            logger,
            "info",
            "channel_message_completed",
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            user_id=incoming.user_id,
            message_id=incoming.id,
            has_response_text=bool(response.text),
            has_buttons=bool(response.buttons),
        )
    except Exception:
        logger.exception(
            "Unhandled error while processing %s message for %s",
            incoming.channel, incoming.channel_user_id,
        )
        await record_release_event("errors_total")
        emit_conversation_analytics_event(
            logger,
            context=context if "context" in locals() else None,
            message=incoming,
            outcome="error",
            tags=["channel_handler_exception"],
            force_sample=True,
        )
        fallback = OutgoingMessage(
            text="Произошла ошибка. Попробуйте ещё раз через пару секунд.",
            chat_id=incoming.chat_id,
            channel=incoming.channel,
        )
        try:
            await gw.send(fallback)
        except Exception:
            logger.exception(
                "Failed to send fallback for %s user %s",
                incoming.channel,
                incoming.channel_user_id,
            )
    finally:
        if typing_task is not None:
            typing_task.cancel()
        reset_request_context(request_token)


async def _handle_channel_onboarding(incoming, gw):
    """Run onboarding for an unregistered non-Telegram channel user."""
    from src.core.models.enums import ConversationState
    from src.core.router import (
        _clear_onboarding_state,
        _get_onboarding_language,
        _get_onboarding_state,
        _set_onboarding_language,
        _set_onboarding_state,
        get_registry,
    )
    from src.skills.onboarding.handler import ONBOARDING_TEXTS, get_onboarding_texts

    # Use channel_user_id as the state key (e.g. Slack "U123ABC", WhatsApp "+1234567890")
    state_key = incoming.channel_user_id or incoming.user_id

    # Handle callback buttons (onboard:lang:XX / onboard:new / onboard:join)
    if incoming.type == MessageType.callback and incoming.callback_data:
        parts = incoming.callback_data.split(":")
        if len(parts) >= 2 and parts[0] == "onboard":
            # Language selection via button
            if parts[1] == "lang" and len(parts) >= 3:
                chosen_lang = parts[2]
                if chosen_lang not in ONBOARDING_TEXTS:
                    chosen_lang = "en"
                await _set_onboarding_language(state_key, chosen_lang)
                await _set_onboarding_state(
                    state_key, ConversationState.onboarding_awaiting_choice
                )
                t = await get_onboarding_texts(chosen_lang)
                await gw.send(
                    OutgoingMessage(
                        text=t["welcome"],
                        chat_id=incoming.chat_id,
                        buttons=[
                            {"text": t["new_account"], "callback": "onboard:new"},
                            {"text": t["join_family"], "callback": "onboard:join"},
                        ],
                        channel=incoming.channel,
                    )
                )
                return

            lang = await _get_onboarding_language(state_key) or "en"
            t = await get_onboarding_texts(lang)

            if parts[1] == "new":
                await _set_onboarding_state(
                    state_key, ConversationState.onboarding_awaiting_activity
                )
                await gw.send(
                    OutgoingMessage(
                        text=t["ask_activity"],
                        chat_id=incoming.chat_id,
                        channel=incoming.channel,
                    )
                )
                return
            elif parts[1] == "join":
                await _set_onboarding_state(
                    state_key, ConversationState.onboarding_awaiting_invite_code
                )
                await gw.send(
                    OutgoingMessage(
                        text=t["ask_invite"],
                        chat_id=incoming.chat_id,
                        channel=incoming.channel,
                    )
                )
                return

    registry = get_registry()
    onboarding = registry.get("onboarding")

    onboarding_state = await _get_onboarding_state(state_key)
    chosen_lang = await _get_onboarding_language(state_key)
    intent_data = {"onboarding_state": onboarding_state} if onboarding_state else {}
    # Pass channel info so onboarding skill uses channel-agnostic registration
    intent_data["channel"] = incoming.channel
    intent_data["channel_user_id"] = incoming.channel_user_id or incoming.user_id

    msg_language = chosen_lang or incoming.language or "en"
    result = await onboarding.execute(
        incoming,
        SessionContext(
            user_id=incoming.user_id,
            family_id="",
            role="owner",
            language=msg_language,
            currency="USD",
            business_type=None,
            categories=[],
            merchant_mappings=[],
        ),
        intent_data,
    )

    # If onboarding completed (no buttons = done), clear state
    if not result.buttons:
        await _clear_onboarding_state(state_key)

    await gw.send(
        OutgoingMessage(
            text=result.response_text,
            chat_id=incoming.chat_id,
            buttons=result.buttons,
            channel=incoming.channel,
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gateway, _slack_gw, _whatsapp_gw, _sms_gw
    logger.info("Starting Finance Bot...")

    gateway = TelegramGateway(
        token=settings.telegram_bot_token,
        webhook_url=settings.telegram_webhook_url,
    )
    gateway.on_message(on_message)
    await gateway.start()

    # Initialise optional channel gateways
    if settings.slack_bot_token:
        from src.gateway.slack_gw import SlackGateway

        _slack_gw = SlackGateway()
        logger.info("Slack gateway configured")

    if settings.whatsapp_api_token:
        from src.gateway.whatsapp_gw import WhatsAppGateway

        _whatsapp_gw = WhatsAppGateway()
        logger.info("WhatsApp gateway configured")

    if settings.twilio_account_sid:
        from src.gateway.sms_gw import SMSGateway

        _sms_gw = SMSGateway()
        logger.info("SMS gateway configured")

    # Set up LangGraph checkpoint tables (PostgreSQL)
    if settings.ff_langgraph_checkpointer:
        from src.orchestrators.checkpointer import setup_checkpointer

        await setup_checkpointer()

        # Recover interrupted graphs from previous run
        try:
            from src.orchestrators.recovery import recover_pending_graphs

            stats = await recover_pending_graphs()
            if stats.get("hitl_pending"):
                logger.info("Graph recovery: %s", stats)
        except Exception as e:
            logger.warning("Graph recovery failed (non-critical): %s", e)

    yield

    if gateway:
        await gateway.stop()
    if _slack_gw:
        await _slack_gw.close()
    if _whatsapp_gw:
        await _whatsapp_gw.close()
    if _sms_gw:
        await _sms_gw.close()
    await redis.aclose()
    logger.info("Shutting down Finance Bot...")


app = FastAPI(title="Finance Bot", lifespan=lifespan)

cors_origins = os.getenv(
    "CORS_ORIGINS", "https://web.telegram.org"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["X-Telegram-Init-Data", "Content-Type"],
)

app.include_router(miniapp_router)
app.include_router(oauth_router)
app.include_router(extension_router)
app.include_router(browser_connect_router)
app.include_router(voice_router)


@app.get("/", include_in_schema=False)
async def landing_index():
    """Serve the fully featured landing page."""
    return FileResponse("static/index.html")


@app.get("/miniapp", include_in_schema=False)
async def miniapp_index():
    """Serve the Telegram Mini App SPA."""
    return FileResponse("static/miniapp/index.html")


@app.get("/privacy", include_in_schema=False)
async def privacy_policy():
    """Serve the Privacy Policy page."""
    return FileResponse("static/privacy.html")


@app.get("/terms", include_in_schema=False)
async def terms_of_service():
    """Serve the Terms of Service page."""
    return FileResponse("static/terms.html")


# Mount static files (CSS, JS, assets) — after all API routes
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    checks = {"api": "ok"}
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}


@app.get("/health/detailed")
async def health_detailed(request: Request):
    """Detailed health check with circuit breaker states, Mem0, and Langfuse.

    Protected by HEALTH_SECRET when configured: pass Authorization: Bearer <token>.
    """
    _require_ops_auth(request)
    checks: dict[str, Any] = {"api": "ok"}

    # Redis
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    # Database
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    # Circuit breakers
    try:
        from src.core.circuit_breaker import all_circuit_statuses

        checks["circuits"] = all_circuit_statuses()
    except Exception:
        checks["circuits"] = "unavailable"

    # Mem0
    try:
        from src.core.memory.mem0_client import get_memory

        get_memory()
        checks["mem0"] = "ok"
    except Exception:
        checks["mem0"] = "error"

    # Langfuse
    try:
        from src.core.observability import get_langfuse

        lf = get_langfuse()
        checks["langfuse"] = "ok" if lf else "not_configured"
    except Exception:
        checks["langfuse"] = "error"

    # Release health
    try:
        checks["release_health"] = await get_release_health_snapshot()
    except Exception:
        checks["release_health"] = "unavailable"

    core_checks = {k: v for k, v in checks.items() if k in ("api", "redis", "database")}
    status = "ok" if all(v == "ok" for v in core_checks.values()) else "degraded"
    return {"status": status, **checks}


@app.get("/ops/release/overview")
async def release_ops_overview(request: Request) -> dict[str, Any]:
    """Return operator-facing release switches, flags, and health snapshot."""
    _require_ops_auth(request)
    return await get_release_ops_overview()


@app.get("/ops/release/decision")
async def release_ops_decision(request: Request) -> dict[str, Any]:
    """Return rollout progression guidance based on current release health gates."""
    _require_ops_auth(request)
    return await get_release_rollout_decision()


@app.get("/ops/release/overrides")
async def release_ops_overrides(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return the active release override and recent operator action history."""
    _require_ops_auth(request)
    return await get_release_override_snapshot(limit=max(1, min(limit, 100)))


@app.post("/ops/release/overrides")
async def release_ops_apply_override(
    request: Request,
    submission: ReleaseOverrideSubmission,
) -> dict[str, Any]:
    """Apply a rollout override for canary progression, hold, rollback, or clear."""
    _require_ops_auth(request)
    try:
        return await apply_release_override(
            actor=submission.actor,
            action=submission.action,
            rollout_percent=submission.rollout_percent,
            shadow_mode=submission.shadow_mode,
            notes=submission.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/ops/analytics/policy")
async def analytics_policy(request: Request) -> dict[str, Any]:
    """Return the active analytics sampling policy."""
    _require_ops_auth(request)
    return get_conversation_analytics_policy()


@app.get("/ops/analytics/review-queue")
async def analytics_review_queue(
    request: Request,
    limit: int = 25,
    review_label: str | None = None,
    suggested_action: str | None = None,
    suggested_final_label: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    max_selected: int = 50,
) -> dict[str, Any]:
    """Return recent review candidates and exported traces."""
    _require_ops_auth(request)
    return await get_review_queue_snapshot(
        limit=max(1, min(limit, 100)),
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
        max_selected=max(1, min(max_selected, 100)),
    )


@app.post("/ops/analytics/reviews")
async def analytics_submit_review(
    request: Request,
    submission: TraceReviewSubmission,
) -> dict[str, Any]:
    """Persist operator review for a trace and optionally promote it to a dataset candidate."""
    _require_ops_auth(request)
    try:
        return await submit_trace_review(
            trace_key=submission.trace_key,
            reviewer=submission.reviewer,
            final_label=submission.final_label,
            action=submission.action,
            rubric=submission.rubric,
            notes=submission.notes,
            labels=submission.labels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ops/analytics/reviews/apply-suggestion")
async def analytics_apply_review_suggestion(
    request: Request,
    submission: TraceSuggestionApproval,
) -> dict[str, Any]:
    """Apply a stored review suggestion with optional operator overrides."""
    _require_ops_auth(request)
    try:
        return await apply_trace_review_suggestion(
            trace_key=submission.trace_key,
            reviewer=submission.reviewer,
            notes=submission.notes,
            final_label=submission.final_label,
            action=submission.action,
            labels=submission.labels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ops/analytics/reviews/apply-suggestions-batch")
async def analytics_apply_review_suggestions_batch(
    request: Request,
    submission: TraceSuggestionBatchApproval,
) -> dict[str, Any]:
    """Apply stored review suggestions for multiple traces in one operator action."""
    _require_ops_auth(request)
    try:
        return await apply_trace_review_suggestions_batch(
            trace_keys=submission.trace_keys,
            reviewer=submission.reviewer,
            notes=submission.notes,
            final_label=submission.final_label,
            action=submission.action,
            labels=submission.labels,
            selection_limit=max(1, min(submission.selection_limit, 100)),
            review_label=submission.review_label,
            suggested_action=submission.suggested_action,
            suggested_final_label=submission.suggested_final_label,
            tag=submission.tag,
            source=submission.source,
            max_selected=max(1, min(submission.max_selected, 100)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ops/analytics/review-candidates")
async def analytics_ingest_review_candidate(
    request: Request,
    submission: TraceCandidateSubmission,
) -> dict[str, Any]:
    """Store an externally supplied trace as a review candidate/export artifact."""
    _require_ops_auth(request)
    try:
        trace_payload = await ingest_review_trace(submission.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "policy": get_conversation_analytics_policy(),
        "trace": trace_payload,
    }


@app.get("/ops/analytics/dataset-candidates")
async def analytics_dataset_candidates(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return reviewed traces promoted to dataset candidates."""
    _require_ops_auth(request)
    candidates = await get_dataset_candidates(limit=max(1, min(limit, 100)))
    return {
        "policy": get_conversation_analytics_policy(),
        "dataset_candidate_size": len(candidates),
        "dataset_candidates": candidates,
    }


@app.get("/ops/analytics/review-results")
async def analytics_review_results(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return recent structured review results."""
    _require_ops_auth(request)
    results = await get_review_results(limit=max(1, min(limit, 100)))
    return {
        "policy": get_conversation_analytics_policy(),
        "review_result_size": len(results),
        "review_results": results,
    }


@app.get("/ops/analytics/review-batches")
async def analytics_review_batches(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return recent batch review actions for audit and weekly reporting."""
    _require_ops_auth(request)
    batches = await get_review_batches(limit=max(1, min(limit, 100)))
    return {
        "policy": get_conversation_analytics_policy(),
        "review_batch_size": len(batches),
        "review_batches": batches,
    }


@app.get("/ops/analytics/feedback")
async def analytics_user_feedback(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return recent user feedback captured through inline bot actions."""
    _require_ops_auth(request)
    feedback_items = await get_user_feedback(limit=max(1, min(limit, 100)))
    return {
        "policy": get_conversation_analytics_policy(),
        "feedback_size": len(feedback_items),
        "feedback": feedback_items,
    }


@app.get("/ops/analytics/golden-dialogues")
async def analytics_golden_dialogues(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return reviewed production traces formatted as golden dialogues."""
    _require_ops_auth(request)
    golden_dialogues = await get_golden_dialogues(limit=max(1, min(limit, 100)))
    return {
        "policy": get_conversation_analytics_policy(),
        "golden_dialogue_size": len(golden_dialogues),
        "golden_dialogues": golden_dialogues,
    }


@app.get("/ops/analytics/weekly-curation")
async def analytics_weekly_curation(request: Request, limit: int = 25) -> dict[str, Any]:
    """Return a weekly curation snapshot for trace review and dataset growth."""
    _require_ops_auth(request)
    return await get_weekly_curation_snapshot(limit=max(1, min(limit, 100)))


# ------------------------------------------------------------------
# Telegram webhook
# ------------------------------------------------------------------

# Deduplication: track recently seen update_ids to prevent Telegram retries
# from processing the same message multiple times.
_DEDUP_TTL = 300  # 5 minutes


async def _is_duplicate_update(update_id: int) -> bool:
    """Check if this Telegram update was already processed (Redis-based dedup)."""
    key = f"tg_update:{update_id}"
    # SET NX returns True only if the key was newly created
    was_set = await redis.set(key, "1", ex=_DEDUP_TTL, nx=True)
    return not was_set  # If not set → key already existed → duplicate


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    if not gateway:
        return Response(status_code=200)

    # Deduplicate: Telegram retries webhooks if we don't respond quickly
    update_id = data.get("update_id")
    if update_id and await _is_duplicate_update(update_id):
        logger.debug("Skipping duplicate Telegram update %s", update_id)
        return Response(status_code=200)

    # Return 200 immediately, process in background to avoid Telegram retries
    asyncio.create_task(_process_update(data))
    return Response(status_code=200)


async def _process_update(data: dict) -> None:
    """Process a Telegram update in the background."""
    try:
        await gateway.feed_update(data)
    except Exception:
        logger.exception("Error processing Telegram update %s", data.get("update_id"))


# ------------------------------------------------------------------
# Slack webhook
# ------------------------------------------------------------------
@app.post("/webhook/slack/events")
async def slack_events(request: Request):
    """Handle Slack Events API and URL verification."""
    body = await request.body()

    # URL verification challenge (parse before signature check)
    import json as _json

    payload = _json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if not _slack_gw:
        return Response(status_code=200)

    # Verify Slack signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if timestamp and signature:
        if not _slack_gw.verify_signature(body, timestamp, signature):
            logger.warning("Slack signature verification failed")
            return Response(status_code=401)

    incoming = _slack_gw.parse_event(payload)
    if incoming:
        asyncio.create_task(_process_channel_message(incoming, _slack_gw))

    return Response(status_code=200)


@app.post("/webhook/slack/actions")
async def slack_actions(request: Request):
    """Handle Slack block_actions (button clicks)."""
    if not _slack_gw:
        return Response(status_code=200)

    form = await request.form()
    payload_str = form.get("payload", "")
    if not payload_str:
        return Response(status_code=200)

    import json as _json

    payload = _json.loads(payload_str)
    actions = payload.get("actions", [])
    if not actions:
        return Response(status_code=200)

    action = actions[0]
    user = payload.get("user", {})
    channel = payload.get("channel", {})

    incoming = IncomingMessage(
        id=action.get("action_id", ""),
        user_id=user.get("id", ""),
        chat_id=channel.get("id", ""),
        type=MessageType.callback,
        callback_data=action.get("value", ""),
        channel="slack",
        channel_user_id=user.get("id", ""),
    )
    asyncio.create_task(_process_channel_message(incoming, _slack_gw))
    return Response(status_code=200)


# ------------------------------------------------------------------
# WhatsApp webhook
# ------------------------------------------------------------------
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Handle WhatsApp Business Cloud API webhook."""
    if not _whatsapp_gw:
        return Response(status_code=200)

    body = await request.body()

    # Verify X-Hub-Signature-256
    signature = request.headers.get("X-Hub-Signature-256", "")
    if signature and not _whatsapp_gw.verify_signature(body, signature):
        logger.warning("WhatsApp signature verification failed")
        return Response(status_code=401)

    import json as _json

    payload = _json.loads(body)
    incoming = await _whatsapp_gw.parse_webhook(payload)
    if incoming:
        asyncio.create_task(_process_channel_message(incoming, _whatsapp_gw))

    return {"status": "ok"}


@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification challenge."""
    if not _whatsapp_gw:
        return Response(status_code=403)

    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    result = _whatsapp_gw.verify_webhook(mode, token, challenge)
    if result:
        return Response(content=result, media_type="text/plain")
    return Response(status_code=403)


# ------------------------------------------------------------------
# SMS webhook (Twilio)
# ------------------------------------------------------------------
@app.post("/webhook/sms")
async def sms_webhook(request: Request):
    """Handle Twilio SMS webhook."""
    if not _sms_gw:
        return Response(content="<Response></Response>", media_type="text/xml", status_code=200)

    form_data = await request.form()
    form_dict = dict(form_data)

    # Verify Twilio signature
    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    if twilio_sig:
        url = str(request.url)
        if not _sms_gw.verify_signature(url, form_dict, twilio_sig):
            logger.warning("Twilio signature verification failed")
            return Response(content="<Response></Response>", media_type="text/xml", status_code=401)

    incoming = _sms_gw.parse_webhook(form_dict)
    asyncio.create_task(_process_channel_message(incoming, _sms_gw))

    # Twilio expects TwiML response
    return Response(content="<Response></Response>", media_type="text/xml")


# ------------------------------------------------------------------
# Stripe webhook
# ------------------------------------------------------------------
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription events."""
    from src.billing.stripe_client import StripeClient
    from src.billing.subscription import update_from_stripe_event

    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if settings.stripe_webhook_secret:
        if not StripeClient.verify_webhook_signature(body, sig, settings.stripe_webhook_secret):
            return Response(status_code=400)

    import json

    event = json.loads(body)
    event_type = event.get("type", "")
    data = event.get("data", {})

    handled_events = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }

    if event_type in handled_events:
        await update_from_stripe_event(event_type, data)

    return Response(status_code=200)
