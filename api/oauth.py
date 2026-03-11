"""OAuth endpoints — Composio-managed Google connection for Gmail + Calendar."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.config import settings
from src.core.db import redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _composio_client():
    from composio import Composio

    return Composio(api_key=settings.composio_api_key)


_AUTH_CONFIG_IDS = {
    "gmail": lambda: settings.composio_gmail_auth_config_id,
    "calendar": lambda: settings.composio_calendar_auth_config_id,
    "sheets": lambda: settings.composio_sheets_auth_config_id,
}


@router.get("/google/start")
async def google_oauth_start(state: str = Query(...)):
    """Start Google OAuth flow via Composio connection initiation."""
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    if isinstance(user_id, bytes):
        user_id = user_id.decode()

    # Determine which service this connection is for
    service = await redis.get(f"oauth_service:{state}")
    if isinstance(service, bytes):
        service = service.decode()
    service = service or "gmail"

    getter = _AUTH_CONFIG_IDS.get(service, _AUTH_CONFIG_IDS["gmail"])
    auth_config_id = getter()
    if not auth_config_id:
        logger.error("Composio auth config not set for service: %s", service)
        raise HTTPException(
            status_code=500, detail=f"Auth config not configured for {service}."
        )

    try:
        composio = _composio_client()

        # Build callback URL for when Composio completes the connection
        if settings.google_redirect_uri:
            base_url = settings.google_redirect_uri.rsplit("/oauth/", 1)[0]
        elif settings.telegram_webhook_url:
            base_url = settings.telegram_webhook_url.rsplit("/", 1)[0]
        else:
            base_url = "https://localhost:8000"
        callback_url = f"{base_url}/oauth/google/callback?state={state}"

        def _initiate():
            return composio.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=auth_config_id,
                callback_url=callback_url,
            )

        loop = asyncio.get_running_loop()
        connection_request = await loop.run_in_executor(None, _initiate)

        redirect_url = getattr(connection_request, "redirect_url", None) or str(
            connection_request
        )
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error("Composio connection initiation failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to start Google connection.")


_CONNECTED_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "gmail": "✅ Gmail connected! You can now read and send emails.",
        "calendar": "✅ Google Calendar connected! You can now manage events.",
        "sheets": "✅ Google Sheets connected! You can now read and write spreadsheets.",
        "page_title": "Connected!",
        "page_body": "You can close this window and return to the bot.",
    },
    "ru": {
        "gmail": "✅ Gmail подключён! Теперь можно читать и отправлять письма.",
        "calendar": "✅ Google Календарь подключён! Теперь можно управлять событиями.",
        "sheets": "✅ Google Таблицы подключены! Теперь можно читать и редактировать таблицы.",
        "page_title": "Подключено!",
        "page_body": "Можно закрыть это окно и вернуться в бот.",
    },
    "es": {
        "gmail": "✅ Gmail conectado. Ya puedes leer y enviar correos.",
        "calendar": "✅ Google Calendar conectado. Ya puedes gestionar eventos.",
        "sheets": "✅ Google Sheets conectado. Ya puedes leer y editar hojas.",
        "page_title": "¡Conectado!",
        "page_body": "Puedes cerrar esta ventana y volver al bot.",
    },
}


async def _notify_telegram(chat_id: str, text: str) -> None:
    """Send a Telegram message via Bot API (no gateway dependency)."""
    if not settings.telegram_bot_token:
        return
    try:
        import httpx

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.warning("Failed to send Telegram OAuth notification: %s", e)


@router.get("/google/callback")
async def google_oauth_callback(
    state: str = Query(...),
):
    """Handle the Composio OAuth callback after user authorizes."""
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    if isinstance(user_id, bytes):
        user_id = user_id.decode()

    service = await redis.get(f"oauth_service:{state}") or "gmail"
    if isinstance(service, bytes):
        service = service.decode()

    chat_id = await redis.get(f"oauth_chat_id:{state}")
    if isinstance(chat_id, bytes):
        chat_id = chat_id.decode()

    lang = await redis.get(f"oauth_lang:{state}") or "en"
    if isinstance(lang, bytes):
        lang = lang.decode()

    # Clean up state
    await redis.delete(f"oauth_state:{state}")
    await redis.delete(f"oauth_service:{state}")
    await redis.delete(f"oauth_chat_id:{state}")
    await redis.delete(f"oauth_lang:{state}")

    # Verify connection actually succeeded via Composio
    from src.core.google_auth import has_google_connection

    connected = await has_google_connection(user_id, service=service)

    strings = _CONNECTED_STRINGS.get(lang, _CONNECTED_STRINGS["en"])

    if connected and chat_id:
        msg = strings.get(service, strings.get("gmail", "✅ Connected!"))
        asyncio.create_task(_notify_telegram(chat_id, msg))

    if connected:
        page_title = strings["page_title"]
        page_body = strings["page_body"]
    else:
        page_title = "Connected!"
        page_body = "You can close this window and return to the bot."

    return HTMLResponse(
        f"<html><body><h2>{page_title}</h2>"
        f"<p>{page_body}</p>"
        "</body></html>"
    )


async def generate_composio_connect_link(
    user_id: str,
    service: str = "gmail",
    chat_id: str | None = None,
    lang: str = "en",
) -> str:
    """Generate a Composio connection link for a user. Called by skills."""
    import secrets

    state = secrets.token_urlsafe(32)
    await redis.set(f"oauth_state:{state}", user_id, ex=600)  # 10 min TTL
    await redis.set(f"oauth_service:{state}", service, ex=600)
    if chat_id:
        await redis.set(f"oauth_chat_id:{state}", chat_id, ex=600)
    await redis.set(f"oauth_lang:{state}", lang, ex=600)

    if settings.google_redirect_uri:
        base_url = settings.google_redirect_uri.rsplit("/oauth/", 1)[0]
    elif settings.telegram_webhook_url:
        base_url = settings.telegram_webhook_url.rsplit("/", 1)[0]
    else:
        base_url = "https://localhost:8000"
    return f"{base_url}/oauth/google/start?state={state}"


# Keep backward-compat alias
generate_oauth_link = generate_composio_connect_link
