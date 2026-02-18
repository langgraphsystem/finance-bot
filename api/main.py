"""Finance Bot — FastAPI entrypoint (webhook + health check)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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
from src.core.profiles import ProfileLoader
from src.core.router import handle_message
from src.gateway.telegram import TelegramGateway
from src.gateway.types import MessageType, OutgoingMessage

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

gateway: TelegramGateway | None = None
profile_loader = ProfileLoader("config/profiles")


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
        )


async def on_message(incoming):
    """Main message handler called by gateway."""
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

        result = await onboarding.execute(
            incoming,
            SessionContext(
                user_id=incoming.user_id,
                family_id="",
                role="owner",
                language="ru",
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
            )
        )
        return

    await gateway.send_typing(incoming.chat_id)
    response = await handle_message(incoming, context)
    await gateway.send(response)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gateway
    logger.info("Starting Finance Bot...")

    gateway = TelegramGateway(
        token=settings.telegram_bot_token,
        webhook_url=settings.telegram_webhook_url,
    )
    gateway.on_message(on_message)
    await gateway.start()

    yield

    if gateway:
        await gateway.stop()
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


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    if gateway:
        await gateway.feed_update(data)
    return Response(status_code=200)
