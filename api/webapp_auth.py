"""Telegram WebApp authentication — HMAC-SHA256 validation."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote

from fastapi import HTTPException, Request

from src.core.config import settings

logger = logging.getLogger(__name__)


async def validate_webapp_data(request: Request) -> dict:
    """Validate Telegram WebApp.initData from request header.

    Returns parsed user data dict with keys: id, first_name, last_name, username, etc.
    Raises HTTPException 401 if validation fails.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing Telegram init data")

    try:
        # Parse the query string
        parsed = parse_qs(init_data)

        # Extract hash
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            raise HTTPException(status_code=401, detail="Missing hash in init data")

        # Build data-check-string (sorted key=value pairs, excluding hash)
        data_check_pairs = []
        for key, values in sorted(parsed.items()):
            if key != "hash":
                data_check_pairs.append(f"{key}={values[0]}")
        data_check_string = "\n".join(data_check_pairs)

        # Generate secret key: HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            b"WebAppData",
            settings.telegram_bot_token.encode(),
            hashlib.sha256,
        ).digest()

        # Calculate expected hash: HMAC-SHA256(secret_key, data_check_string)
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Validate
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise HTTPException(status_code=401, detail="Invalid hash")

        # Check auth_date freshness (allow up to 1 hour)
        auth_date_str = parsed.get("auth_date", [None])[0]
        if auth_date_str:
            auth_date = datetime.fromtimestamp(int(auth_date_str), tz=UTC)
            now = datetime.now(UTC)
            if (now - auth_date).total_seconds() > 3600:
                raise HTTPException(status_code=401, detail="Auth data expired")

        # Parse user data
        user_str = parsed.get("user", [None])[0]
        if user_str:
            return json.loads(unquote(user_str))

        raise HTTPException(status_code=401, detail="Missing user data")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("WebApp auth validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Auth validation error")
