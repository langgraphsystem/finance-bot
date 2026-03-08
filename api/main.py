"""Finance Bot — FastAPI entrypoint (webhook + health check)."""

import asyncio
import logging
import os
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from api.browser_connect import router as browser_connect_router
from api.browser_extension import router as extension_router
from api.miniapp import router as miniapp_router
from api.oauth import router as oauth_router
from src.core.access import filter_scope_items
from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session, redis
from src.core.models.category import Category
from src.core.models.family import Family
from src.core.models.merchant_mapping import MerchantMapping
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.profiles import ProfileLoader
from src.core.router import handle_message
from src.gateway.telegram import TelegramGateway
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

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


async def _maybe_set_timezone_from_language(user_id: str, language_code: str) -> None:
    """Update user timezone based on Telegram language_code (runs once per day).

    When ``ff_locale_v2_write`` is enabled the function also records
    ``timezone_source='channel_hint'`` and ``timezone_confidence=30`` and
    refuses to overwrite timezones already set by a higher-confidence source.
    """
    if not language_code or language_code == "en":
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

    tz = LANGUAGE_TIMEZONE_MAP.get(language_code)
    if not tz:
        return

    try:
        from datetime import datetime

        from sqlalchemy import update

        async with async_session() as session:
            if settings.ff_locale_v2_write:
                # v2: only overwrite if timezone_source is 'default' (low confidence)
                result = await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == _uuid.UUID(user_id))
                    .where(UserProfile.timezone_source == "default")
                    .values(
                        timezone=tz,
                        timezone_source="channel_hint",
                        timezone_confidence=30,
                        locale_updated_at=datetime.now(UTC),
                    )
                )
            else:
                # Legacy: only update if timezone is still the default value
                result = await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == _uuid.UUID(user_id))
                    .where(UserProfile.timezone == "America/New_York")
                    .values(timezone=tz)
                )
            if result.rowcount > 0:
                await session.commit()
                logger.info(
                    "Auto-set timezone %s for user %s (lang=%s, v2=%s)",
                    tz,
                    user_id,
                    language_code,
                    settings.ff_locale_v2_write,
                )
            else:
                await session.rollback()
    except Exception as e:
        logger.debug("Failed to auto-set timezone: %s", e)


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

        # Load categories
        cat_result = await session.execute(
            select(Category).where(Category.family_id == user.family_id)
        )
        categories = [
            {"id": str(c.id), "name": c.name, "scope": c.scope.value, "icon": c.icon}
            for c in cat_result.scalars()
        ]
        categories = filter_scope_items(categories, user.role.value)

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
        mappings = filter_scope_items(mappings, user.role.value)

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
        user_timezone = prof_row[0] if prof_row else "America/New_York"

        return SessionContext(
            user_id=str(user.id),
            family_id=str(user.family_id),
            role=user.role.value,
            language=user.language,
            currency=family.currency,
            business_type=user.business_type,
            categories=categories,
            merchant_mappings=mappings,
            profile_config=profile,
            timezone=user_timezone,
            user_profile=_build_user_profile(prof_row),
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

        cat_result = await session.execute(
            select(Category).where(Category.family_id == user.family_id)
        )
        categories = [
            {"id": str(c.id), "name": c.name, "scope": c.scope.value, "icon": c.icon}
            for c in cat_result.scalars()
        ]
        categories = filter_scope_items(categories, user.role.value)

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
        mappings = filter_scope_items(mappings, user.role.value)

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
        user_timezone = prof_row[0] if prof_row else "America/New_York"

        return SessionContext(
            user_id=str(user.id),
            family_id=str(user.family_id),
            role=user.role.value,
            language=user.language,
            currency=family.currency,
            business_type=user.business_type,
            categories=categories,
            merchant_mappings=mappings,
            profile_config=profile,
            timezone=user_timezone,
            user_profile=_build_user_profile(prof_row),
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
    context = await build_session_context(incoming.user_id)

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

        # Handle callback buttons (onboard:lang:XX / onboard:new / onboard:join)
        if incoming.type == MessageType.callback and incoming.callback_data:
            parts = incoming.callback_data.split(":")
            if len(parts) >= 2 and parts[0] == "onboard":
                if parts[1] == "lang" and len(parts) >= 3:
                    # Language selection via button
                    chosen_lang = parts[2]
                    if chosen_lang not in ONBOARDING_TEXTS:
                        chosen_lang = "en"
                    await _set_onboarding_language(
                        incoming.user_id, chosen_lang,
                    )
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
                                {
                                    "text": t["new_account"],
                                    "callback": "onboard:new",
                                },
                                {
                                    "text": t["join_family"],
                                    "callback": "onboard:join",
                                },
                            ],
                        )
                    )
                    return

                lang = await _get_onboarding_language(
                    incoming.user_id,
                ) or "en"
                t = await get_onboarding_texts(lang)

                if parts[1] == "new":
                    await _set_onboarding_state(
                        incoming.user_id, ConversationState.onboarding_awaiting_activity
                    )
                    await gateway.send(
                        OutgoingMessage(text=t["ask_activity"], chat_id=incoming.chat_id)
                    )
                    return
                elif parts[1] == "join":
                    await _set_onboarding_state(
                        incoming.user_id, ConversationState.onboarding_awaiting_invite_code
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

        # After /start or fresh entry: reset to awaiting_language
        # so the user can type their preferred language.
        # Always reset on /start to clear any stale state.
        text_raw = (incoming.text or "").strip()
        if text_raw == "/start" or not onboarding_state:
            await _set_onboarding_state(
                incoming.user_id,
                ConversationState.onboarding_awaiting_language,
            )

        # Detect onboarding completion (no buttons = done)
        onboarding_completed = not result.buttons and onboarding_state is not None
        if onboarding_completed:
            await _clear_onboarding_state(incoming.user_id)

        # Send main response
        await gateway.send(
            OutgoingMessage(
                text=result.response_text,
                chat_id=incoming.chat_id,
                buttons=result.buttons,
            )
        )

        # After onboarding completion: send timezone location request
        if onboarding_completed:
            lang = chosen_lang or incoming.language or "en"
            t = await get_onboarding_texts(lang)
            # Message 1: location request with reply keyboard
            await gateway.send(
                OutgoingMessage(
                    text=t["tz_location_prompt"],
                    chat_id=incoming.chat_id,
                    reply_keyboard=[
                        {"text": t["share_location_btn"], "request_location": True},
                    ],
                )
            )
            # Message 2: skip option (inline button)
            await gateway.send(
                OutgoingMessage(
                    text=t["tz_skip_hint"],
                    chat_id=incoming.chat_id,
                    buttons=[
                        {"text": t["tz_skip_btn"], "callback": "tz_skip"},
                    ],
                )
            )

        return

    # Background: auto-set timezone from Telegram language_code
    if incoming.language:
        asyncio.create_task(_maybe_set_timezone_from_language(context.user_id, incoming.language))

    typing_task = asyncio.create_task(_typing_loop(gateway, incoming.chat_id))
    try:
        response = await handle_message(incoming, context)
    except Exception:
        logger.exception("Unhandled error in handle_message for user %s", incoming.user_id)
        response = OutgoingMessage(
            text="Произошла ошибка. Попробуйте ещё раз через пару секунд.",
            chat_id=incoming.chat_id,
        )
    finally:
        typing_task.cancel()
    await gateway.send(response)


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
    try:
        context = await build_context_from_channel(incoming.channel, incoming.channel_user_id)

        if not context:
            # Unregistered channel user — run onboarding (same as Telegram)
            await _handle_channel_onboarding(incoming, gw)
            return

        typing_task = asyncio.create_task(_typing_loop(gw, incoming.chat_id))
        response = await handle_message(incoming, context)
        response.chat_id = incoming.chat_id
        response.channel = incoming.channel
        await gw.send(response)
    except Exception:
        logger.exception(
            "Unhandled error while processing %s message for %s",
            incoming.channel, incoming.channel_user_id,
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
    intent_data = {"onboarding_state": onboarding_state} if onboarding_state else {}
    # Pass channel info so onboarding skill uses channel-agnostic registration
    intent_data["channel"] = incoming.channel
    intent_data["channel_user_id"] = incoming.channel_user_id or incoming.user_id

    msg_language = incoming.language or "en"
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
    if settings.health_secret:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") != settings.health_secret:
            raise HTTPException(status_code=401, detail="Unauthorized")
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

    core_checks = {k: v for k, v in checks.items() if k in ("api", "redis", "database")}
    status = "ok" if all(v == "ok" for v in core_checks.values()) else "degraded"
    return {"status": status, **checks}


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
