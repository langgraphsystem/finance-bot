"""Finance Bot — FastAPI entrypoint (webhook + health check)."""

import asyncio
import logging
import os
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from api.miniapp import router as miniapp_router
from api.oauth import router as oauth_router
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
from src.gateway.types import MessageType, OutgoingMessage

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
    """Update user timezone based on Telegram language_code (runs once per day)."""
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
        from sqlalchemy import update

        async with async_session() as session:
            # Only update if timezone is still the default
            result = await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .where(UserProfile.timezone == "America/New_York")
                .values(timezone=tz)
            )
            if result.rowcount > 0:
                await session.commit()
                logger.info(
                    "Auto-set timezone %s for user %s (lang=%s)", tz, user_id, language_code
                )
            else:
                await session.rollback()
    except Exception as e:
        logger.debug("Failed to auto-set timezone: %s", e)


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

        profile = profile_loader.get(user.business_type) or profile_loader.get("household")

        # Load user profile for timezone + city
        prof_result = await session.execute(
            select(UserProfile.timezone, UserProfile.city)
            .where(UserProfile.user_id == user.id)
            .limit(1)
        )
        prof_row = prof_result.one_or_none()
        user_timezone = prof_row[0] if prof_row else "America/New_York"
        user_city = prof_row[1] if prof_row else None

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
            user_profile={"city": user_city} if user_city else {},
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

        profile = profile_loader.get(user.business_type) or profile_loader.get("household")

        prof_result = await session.execute(
            select(UserProfile.timezone, UserProfile.city)
            .where(UserProfile.user_id == user.id)
            .limit(1)
        )
        prof_row = prof_result.one_or_none()
        user_timezone = prof_row[0] if prof_row else "America/New_York"
        user_city = prof_row[1] if prof_row else None

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
            user_profile={"city": user_city} if user_city else {},
        )


async def on_message(incoming):
    """Main message handler called by Telegram gateway."""
    context = await build_session_context(incoming.user_id)

    if not context:
        # Unregistered user — handle onboarding callbacks and FSM state
        from src.core.models.enums import ConversationState
        from src.core.router import (
            _clear_onboarding_state,
            _get_onboarding_state,
            _set_onboarding_state,
            get_registry,
        )

        # Handle callback buttons (onboard:new / onboard:join)
        if incoming.type == MessageType.callback and incoming.callback_data:
            parts = incoming.callback_data.split(":")
            if len(parts) >= 2 and parts[0] == "onboard":
                if parts[1] == "new":
                    await _set_onboarding_state(
                        incoming.user_id, ConversationState.onboarding_awaiting_activity
                    )
                    await gateway.send(
                        OutgoingMessage(
                            text=(
                                "Расскажите о своей деятельности — чем занимаетесь?\n\n"
                                "Например: «я таксист», «у меня трак», "
                                "«просто хочу следить за расходами»"
                            ),
                            chat_id=incoming.chat_id,
                        )
                    )
                    return
                elif parts[1] == "join":
                    await _set_onboarding_state(
                        incoming.user_id, ConversationState.onboarding_awaiting_invite_code
                    )
                    await gateway.send(
                        OutgoingMessage(
                            text="Введите код приглашения, который вам прислал владелец аккаунта:",
                            chat_id=incoming.chat_id,
                        )
                    )
                    return

        registry = get_registry()
        onboarding = registry.get("onboarding")

        onboarding_state = await _get_onboarding_state(incoming.user_id)
        intent_data = {"onboarding_state": onboarding_state} if onboarding_state else {}

        tg_language = incoming.language or "ru"
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

        # If onboarding completed (no buttons = done), clear state
        if not result.buttons:
            await _clear_onboarding_state(incoming.user_id)

        await gateway.send(
            OutgoingMessage(
                text=result.response_text,
                chat_id=incoming.chat_id,
                buttons=result.buttons,
                reply_keyboard=getattr(result, "reply_keyboard", None),
            )
        )
        return

    # Background: auto-set timezone from Telegram language_code
    if incoming.language:
        asyncio.create_task(_maybe_set_timezone_from_language(context.user_id, incoming.language))

    await gateway.send_typing(incoming.chat_id)
    response = await handle_message(incoming, context)
    await gateway.send(response)


async def _handle_channel_message(incoming, gw):
    """Handle a message from a non-Telegram channel (Slack, WhatsApp, SMS)."""
    context = await build_context_from_channel(incoming.channel, incoming.channel_user_id)

    if not context:
        await gw.send(
            OutgoingMessage(
                text=(
                    "I don't recognize your account yet. "
                    "Please set up your account on Telegram first, "
                    "then link this channel by saying 'connect' there."
                ),
                chat_id=incoming.chat_id,
                channel=incoming.channel,
            )
        )
        return

    await gw.send_typing(incoming.chat_id)
    response = await handle_message(incoming, context)
    response.chat_id = incoming.chat_id
    response.channel = incoming.channel
    await gw.send(response)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(miniapp_router)
app.include_router(oauth_router)


@app.get("/", include_in_schema=False)
async def landing_index():
    """Serve the fully featured landing page."""
    return FileResponse("static/index.html")

@app.get("/miniapp", include_in_schema=False)
async def miniapp_index():
    """Serve the Telegram Mini App SPA."""
    return FileResponse("static/miniapp/index.html")


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
    payload = await request.json()

    # URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if not _slack_gw:
        return Response(status_code=200)

    incoming = _slack_gw.parse_event(payload)
    if incoming:
        await _handle_channel_message(incoming, _slack_gw)

    return Response(status_code=200)


# ------------------------------------------------------------------
# WhatsApp webhook
# ------------------------------------------------------------------
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Handle WhatsApp Business Cloud API webhook."""
    if not _whatsapp_gw:
        return Response(status_code=200)

    payload = await request.json()
    incoming = _whatsapp_gw.parse_webhook(payload)
    if incoming:
        await _handle_channel_message(incoming, _whatsapp_gw)

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
    incoming = _sms_gw.parse_webhook(dict(form_data))
    await _handle_channel_message(incoming, _sms_gw)

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
