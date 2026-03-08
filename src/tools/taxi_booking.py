"""Multi-step taxi booking flow via Telegram and browser automation."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from src.core.db import redis

logger = logging.getLogger(__name__)

FLOW_TTL = 900
_REDIS_PREFIX = "taxi_booking"
MAX_OPTIONS = 5

_PROVIDER_ALIASES = {
    "uber": "uber.com",
    "uber.com": "uber.com",
    "lyft": "lyft.com",
    "lyft.com": "lyft.com",
}

_PROVIDER_LABELS = {
    "uber.com": "Uber",
    "lyft.com": "Lyft",
}

_OPTIONS_PROMPT = """\
Open {site_url} and prepare a ride search for the authenticated user.

Ride request:
- Pickup: {pickup}
- Destination: {destination}

Steps:
1. Dismiss cookie banners, promos, or overlays.
2. Make sure you are on the ride booking page.
3. Use the current account session. If login is required, STOP and return exactly:
LOGIN_REQUIRED
4. Enter the pickup location {pickup_instruction}
5. Enter the destination exactly as: "{destination}"
6. Wait until the available ride options fully load.
7. Do NOT place an order.
8. Return ONLY a JSON array with up to {max_options} options:

[
  {{
    "label": "UberX",
    "price": "$18.50",
    "eta": "4 min",
    "capacity": "4",
    "notes": "Cheapest option"
  }}
]

Rules:
- If no rides are available, return exactly: NO_RIDES
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED
- Keep strings short and factual
- Do not include markdown or explanation outside the JSON array"""

_REVIEW_PROMPT = """\
Open {site_url} and prepare the final confirmation screen for this ride.

Ride request:
- Pickup: {pickup}
- Destination: {destination}
- Selected option: {option_label}

Steps:
1. Use the saved authenticated session. If login is required, return exactly:
LOGIN_REQUIRED
2. Enter pickup {pickup_instruction}
3. Enter destination "{destination}"
4. Select the ride option "{option_label}".
5. Advance to the last review / confirmation screen.
6. DO NOT click the final request / confirm / order button.
7. Return ONLY valid JSON:

{{
  "status": "READY_TO_CONFIRM",
  "label": "{option_label}",
  "pickup": "123 Main St",
  "destination": "Airport Terminal 1",
  "price": "$18.50",
  "eta": "4 min",
  "notes": "Surge pricing included"
}}

Rules:
- If the chosen option is unavailable, return {{"status": "UNAVAILABLE"}}
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED
- Do not click the final order button"""

_CONFIRM_PROMPT = """\
You are on the final review screen at {site_url}.

Expected booking details:
- Ride option: {option_label}
- Pickup: {pickup}
- Destination: {destination}
- Expected price: {expected_price}

Steps:
1. Verify the screen still matches the expected ride option and destination.
2. If login is required, return exactly: LOGIN_REQUIRED
3. If the final price changed materially or the option changed, DO NOT confirm.
   Return ONLY:
   {{"status": "PRICE_CHANGED", "price": "new price", "notes": "what changed"}}
4. Otherwise click the final request / confirm button and wait for the result.
5. Return ONLY valid JSON:

{{
  "status": "BOOKED",
  "label": "{option_label}",
  "price": "$18.50",
  "eta": "3 min",
  "driver_name": "John",
  "car": "Toyota Camry",
  "plate": "ABC123",
  "trip_status": "Driver assigned",
  "notes": ""
}}

Rules:
- If the app stays on "searching for driver", still return status BOOKED with trip_status
- If booking fails, return {{"status": "FAILED", "notes": "reason"}}
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED"""


async def get_taxi_state(user_id: str) -> dict[str, Any] | None:
    try:
        raw = await redis.get(f"{_REDIS_PREFIX}:{user_id}")
    except Exception as e:
        logger.warning("Failed to read taxi flow state for %s: %s", user_id, e)
        return None
    if not raw:
        return None
    return json.loads(raw)


async def _set_state(user_id: str, state: dict[str, Any]) -> None:
    try:
        await redis.set(
            f"{_REDIS_PREFIX}:{user_id}",
            json.dumps(state, ensure_ascii=False, default=str),
            ex=FLOW_TTL,
        )
    except Exception as e:
        logger.warning("Failed to store taxi flow state for %s: %s", user_id, e)


async def _clear_state(user_id: str) -> None:
    try:
        await redis.delete(f"{_REDIS_PREFIX}:{user_id}")
    except Exception as e:
        logger.warning("Failed to clear taxi flow state for %s: %s", user_id, e)


def parse_taxi_request(task: str, site_hint: str | None = None) -> dict[str, Any]:
    text = (task or "").strip()
    lower = text.lower()

    provider = _normalize_provider(site_hint or _extract_provider_alias(lower))
    pickup = _extract_location(
        text,
        (
            r"\b(?:from|pickup(?: at)?|pick me up at)\s+(.+?)(?=\s+\bto\b|\s+\bvia\b|$)",
            r"\b(?:из|забери(?: меня)?(?: от)?|подай(?: такси)?(?: от)?)\s+(.+?)(?=\s+\bдо\b|$)",
        ),
    )
    destination = _extract_location(
        text,
        (
            r"\b(?:to|destination(?: is)?|drop(?: me)? off at)\s+(.+?)(?=\s+\bwith\b|$)",
            r"\b(?:до|на адрес)\s+(.+?)(?=\s+\bчерез\b|$)",
        ),
    )

    for filler in ("uber", "lyft", "uber.com", "lyft.com"):
        if destination:
            destination = re.sub(
                rf"\b{re.escape(filler)}\b", "", destination, flags=re.IGNORECASE
            )
            destination = re.sub(r"\s{2,}", " ", destination).strip(" ,.")
        if pickup:
            pickup = re.sub(rf"\b{re.escape(filler)}\b", "", pickup, flags=re.IGNORECASE)
            pickup = re.sub(r"\s{2,}", " ", pickup).strip(" ,.")

    return {
        "provider": provider,
        "pickup": pickup,
        "destination": destination,
        "task": text,
    }


async def start_flow(
    user_id: str,
    family_id: str,
    task: str,
    language: str = "en",
    site_hint: str | None = None,
) -> dict[str, Any]:
    parsed = parse_taxi_request(task, site_hint)
    provider = parsed["provider"]
    destination = parsed["destination"]

    if not provider:
        return {
            "action": "need_provider",
            "text": (
                "Which taxi service should I use?\n\n"
                "Example: <i>Order an Uber to 123 Main St</i>"
            ),
        }

    flow_id = str(uuid.uuid4())
    state = {
        "flow_id": flow_id,
        "family_id": family_id,
        "language": language,
        "provider": provider,
        "provider_label": _provider_label(provider),
        "pickup": parsed["pickup"],
        "destination": destination,
        "task": task,
    }

    if not destination:
        state["step"] = "awaiting_destination"
        await _set_state(user_id, state)
        return {
            "action": "need_destination",
            "text": (
                f"Where should I order the {_provider_label(provider)} ride?\n\n"
                "Send the destination address or place name."
            ),
            "buttons": [
                {"text": "Cancel", "callback": f"taxi_cancel:{flow_id}"},
            ],
        }

    state["step"] = "checking_auth"
    await _set_state(user_id, state)
    return await check_auth_and_fetch_options(user_id)


async def check_auth_and_fetch_options(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_taxi_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active taxi request."}

    provider = state["provider"]
    storage_state = await browser_service.get_storage_state(user_id, provider)
    if not storage_state:
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return _build_login_prompt(state)

    state["step"] = "fetching_options"
    await _set_state(user_id, state)
    return await _execute_options_search(user_id)


async def handle_login_ready(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_taxi_state(user_id)
    if not state or state.get("step") != "awaiting_login":
        return {"action": "no_flow", "text": "No taxi login is waiting right now."}

    provider = state["provider"]
    storage_state = await browser_service.get_storage_state(user_id, provider)
    if not storage_state:
        return _build_login_prompt(
            state,
            prefix="I still don't see a saved session for this provider.",
        )

    state["step"] = "fetching_options"
    await _set_state(user_id, state)
    return await _execute_options_search(user_id)


async def handle_option_selection(user_id: str, index: int) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_taxi_state(user_id)
    if not state or state.get("step") != "awaiting_selection":
        return {"action": "no_flow", "text": "No ride options are waiting for selection."}

    options = state.get("options", [])
    if index < 0 or index >= len(options):
        return {"action": "error", "text": f"Invalid option. Choose 1-{len(options)}."}

    selected = options[index]
    provider = state["provider"]
    prompt = _REVIEW_PROMPT.format(
        site_url=f"https://{provider}",
        pickup=state.get("pickup") or "current location from the account",
        destination=state.get("destination", ""),
        option_label=selected.get("label", ""),
        pickup_instruction=_pickup_instruction(state.get("pickup")),
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=provider,
        task=prompt,
        max_steps=25,
        timeout=180,
    )

    raw = result.get("result", "")
    review = _extract_json_object(raw)
    status = (review or {}).get("status", "").upper()

    if "LOGIN_REQUIRED" in raw.upper() or status == "LOGIN_REQUIRED":
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return _build_login_prompt(state)

    if "CAPTCHA_DETECTED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return {
            "action": "captcha",
            "text": (
                "The provider showed a CAPTCHA. Please open the site in your browser, "
                "solve it, save the session again, then tap <b>Ready</b>."
            ),
            "buttons": [
                {
                    "text": f"Open {_provider_label(provider)}",
                    "url": browser_service.get_login_url(provider),
                },
                {"text": "Ready — continue", "callback": f"taxi_login_ready:{state['flow_id']}"},
                {"text": "Cancel", "callback": f"taxi_cancel:{state['flow_id']}"},
            ],
        }

    if status == "UNAVAILABLE":
        return {
            "action": "unavailable",
            "text": (
                f"{selected.get('label', 'That option')} is no longer available.\n\n"
                "Choose another ride option."
            ),
            "buttons": _build_option_buttons(options, state["flow_id"]),
        }

    if not review:
        return {
            "action": "error",
            "text": (
                "I couldn't prepare the final ride confirmation screen.\n\n"
                f"Raw result: <code>{_escape_html(raw[:300])}</code>"
            ),
        }

    state["selected_option"] = selected
    state["review"] = review
    state["step"] = "confirming"
    await _set_state(user_id, state)
    return {
        "action": "confirming",
        "text": _format_review_text(state),
        "buttons": [
            {"text": "Confirm ride", "callback": f"taxi_confirm:{state['flow_id']}"},
            {"text": "Back to options", "callback": f"taxi_back:{state['flow_id']}"},
            {"text": "Cancel", "callback": f"taxi_cancel:{state['flow_id']}"},
        ],
    }


async def confirm_booking(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_taxi_state(user_id)
    if not state or state.get("step") != "confirming":
        return {"action": "no_flow", "text": "No taxi booking is waiting for confirmation."}

    review = state.get("review", {})
    selected = state.get("selected_option", {})
    provider = state["provider"]
    prompt = _CONFIRM_PROMPT.format(
        site_url=f"https://{provider}",
        option_label=selected.get("label", ""),
        pickup=review.get("pickup") or state.get("pickup") or "current location",
        destination=review.get("destination") or state.get("destination", ""),
        expected_price=review.get("price") or selected.get("price", ""),
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=provider,
        task=prompt,
        max_steps=20,
        timeout=180,
    )
    raw = result.get("result", "")
    booked = _extract_json_object(raw)
    status = (booked or {}).get("status", "").upper()

    if "LOGIN_REQUIRED" in raw.upper() or status == "LOGIN_REQUIRED":
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return _build_login_prompt(state)

    if status == "PRICE_CHANGED":
        state["review"] = {
            **review,
            "price": booked.get("price", review.get("price", "")),
            "notes": booked.get("notes", review.get("notes", "")),
        }
        await _set_state(user_id, state)
        return {
            "action": "price_changed",
            "text": (
                "<b>The price changed before booking.</b>\n\n"
                f"{_format_review_text(state)}"
            ),
            "buttons": [
                {
                    "text": "Confirm updated price",
                    "callback": f"taxi_confirm:{state['flow_id']}",
                },
                {"text": "Back to options", "callback": f"taxi_back:{state['flow_id']}"},
                {"text": "Cancel", "callback": f"taxi_cancel:{state['flow_id']}"},
            ],
        }

    if not booked or status not in {"BOOKED", "REQUESTED"}:
        notes = booked.get("notes", "") if booked else raw[:200]
        await _clear_state(user_id)
        return {
            "action": "failed",
            "text": (
                "I couldn't complete the ride request.\n\n"
                f"<code>{_escape_html(notes)}</code>"
            ),
        }

    await _clear_state(user_id)
    return {
        "action": "booked",
        "text": _format_booking_success(state, booked),
    }


async def handle_back_to_options(user_id: str) -> dict[str, Any]:
    state = await get_taxi_state(user_id)
    if not state or not state.get("options"):
        return {"action": "no_flow", "text": "No ride options are available."}

    state["step"] = "awaiting_selection"
    state.pop("review", None)
    state.pop("selected_option", None)
    await _set_state(user_id, state)
    return {
        "action": "results",
        "text": _format_options_text(state),
        "buttons": _build_option_buttons(state["options"], state["flow_id"]),
    }


async def handle_text_input(user_id: str, text: str) -> dict[str, Any] | None:
    state = await get_taxi_state(user_id)
    if not state:
        return None

    step = state.get("step")
    lowered = (text or "").strip().lower()

    if step == "awaiting_destination":
        destination = (text or "").strip()
        if not destination:
            return None
        state["destination"] = destination
        state["step"] = "checking_auth"
        await _set_state(user_id, state)
        return await check_auth_and_fetch_options(user_id)

    if step == "awaiting_login":
        if any(word in lowered for word in ("ready", "готово", "done", "saved", "сохранил")):
            return await handle_login_ready(user_id)
        return None

    if step == "awaiting_selection":
        options = state.get("options", [])
        if lowered.isdigit():
            index = int(lowered) - 1
            if 0 <= index < len(options):
                return await handle_option_selection(user_id, index)
        for index, option in enumerate(options):
            if lowered and lowered in option.get("label", "").lower():
                return await handle_option_selection(user_id, index)
        return None

    if step == "confirming":
        if any(word in lowered for word in ("yes", "да", "confirm", "подтверж")):
            return await confirm_booking(user_id)
        if any(word in lowered for word in ("back", "назад", "no", "нет", "cancel", "отмена")):
            return await handle_back_to_options(user_id)
        return None

    return None


async def cancel_flow(user_id: str) -> None:
    await _clear_state(user_id)


async def _execute_options_search(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_taxi_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active taxi request."}

    provider = state["provider"]
    prompt = _OPTIONS_PROMPT.format(
        site_url=f"https://{provider}",
        pickup=state.get("pickup") or "current location from the account",
        destination=state.get("destination", ""),
        pickup_instruction=_pickup_instruction(state.get("pickup")),
        max_options=MAX_OPTIONS,
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=provider,
        task=prompt,
        max_steps=25,
        timeout=180,
    )
    raw = result.get("result", "")

    if "LOGIN_REQUIRED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return _build_login_prompt(state)

    if "CAPTCHA_DETECTED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return {
            "action": "captcha",
            "text": (
                "The provider asked for a CAPTCHA. Open the site in your browser, "
                "solve it, save the session again, then tap <b>Ready</b>."
            ),
            "buttons": [
                {
                    "text": f"Open {_provider_label(provider)}",
                    "url": browser_service.get_login_url(provider),
                },
                {"text": "Ready — continue", "callback": f"taxi_login_ready:{state['flow_id']}"},
                {"text": "Cancel", "callback": f"taxi_cancel:{state['flow_id']}"},
            ],
        }

    if "NO_RIDES" in raw.upper():
        await _clear_state(user_id)
        return {
            "action": "no_rides",
            "text": (
                f"I couldn't find available rides in {_provider_label(provider)} for "
                f"<b>{_escape_html(state.get('destination', 'this route'))}</b> right now."
            ),
        }

    options = _extract_json_array(raw)
    if not options:
        await _clear_state(user_id)
        return {
            "action": "error",
            "text": (
                "I couldn't extract ride options from the provider.\n\n"
                f"<code>{_escape_html(raw[:300])}</code>"
            ),
        }

    state["step"] = "awaiting_selection"
    state["options"] = options[:MAX_OPTIONS]
    await _set_state(user_id, state)
    return {
        "action": "results",
        "text": _format_options_text(state),
        "buttons": _build_option_buttons(state["options"], state["flow_id"]),
    }


def _build_login_prompt(
    state: dict[str, Any],
    prefix: str | None = None,
) -> dict[str, Any]:
    from src.tools import browser_service

    provider = state["provider"]
    flow_id = state["flow_id"]
    provider_label = _provider_label(provider)
    intro = prefix or (
        f"I need access to <b>{provider_label}</b> before I can show live ride options."
    )
    return {
        "action": "need_login",
        "text": (
            f"{intro}\n\n"
            "1. Open the provider in your browser\n"
            "2. Log in to your account\n"
            "3. Click the Finance Bot extension and save the session\n"
            "4. Come back here and tap <b>Ready — continue</b>\n\n"
            "If you still need the browser extension setup, send /extension."
        ),
        "buttons": [
            {"text": f"Open {provider_label}", "url": browser_service.get_login_url(provider)},
            {"text": "Ready — continue", "callback": f"taxi_login_ready:{flow_id}"},
            {"text": "Cancel", "callback": f"taxi_cancel:{flow_id}"},
        ],
    }


def _build_option_buttons(options: list[dict[str, Any]], flow_id: str) -> list[dict[str, str]]:
    buttons = []
    for index, option in enumerate(options[:MAX_OPTIONS]):
        label = option.get("label") or f"Option {index + 1}"
        price = option.get("price") or ""
        eta = option.get("eta") or ""
        suffix = " ".join(part for part in (price, eta) if part).strip()
        text = f"{index + 1}. {label}"
        if suffix:
            text = f"{text} {suffix}"
        buttons.append({"text": text[:64], "callback": f"taxi_select:{flow_id}:{index}"})
    buttons.append({"text": "Cancel", "callback": f"taxi_cancel:{flow_id}"})
    return buttons


def _format_options_text(state: dict[str, Any]) -> str:
    provider = _provider_label(state["provider"])
    destination = _escape_html(state.get("destination", ""))
    pickup = state.get("pickup")
    lines = [
        f"<b>{provider} ride options</b>",
        "",
        f"Destination: <b>{destination}</b>",
    ]
    if pickup:
        lines.append(f"Pickup: <b>{_escape_html(pickup)}</b>")
    lines.append("")
    for index, option in enumerate(state.get("options", []), start=1):
        bits = [f"<b>{index}. {_escape_html(option.get('label', 'Option'))}</b>"]
        meta = " • ".join(
            _escape_html(part)
            for part in (
                option.get("price", ""),
                option.get("eta", ""),
                option.get("capacity", ""),
            )
            if part
        )
        if meta:
            bits.append(meta)
        if option.get("notes"):
            bits.append(_escape_html(option["notes"]))
        lines.append("\n".join(bits))
        lines.append("")
    lines.append("Choose an option or send its number.")
    return "\n".join(lines).strip()


def _format_review_text(state: dict[str, Any]) -> str:
    review = state.get("review", {})
    label = review.get("label") or state.get("selected_option", {}).get("label", "Ride")
    lines = [
        "<b>Confirm this ride?</b>",
        "",
        f"Service: <b>{_escape_html(label)}</b>",
    ]
    if review.get("pickup") or state.get("pickup"):
        lines.append(f"Pickup: {_escape_html(review.get('pickup') or state.get('pickup', ''))}")
    if review.get("destination") or state.get("destination"):
        destination = review.get("destination") or state.get("destination", "")
        lines.append(f"Destination: {_escape_html(destination)}")
    if review.get("price"):
        lines.append(f"Price: <b>{_escape_html(review['price'])}</b>")
    if review.get("eta"):
        lines.append(f"ETA: {_escape_html(review['eta'])}")
    if review.get("notes"):
        lines.append(f"Notes: {_escape_html(review['notes'])}")
    lines.append("")
    lines.append("I will place the ride only after you confirm.")
    return "\n".join(lines)


def _format_booking_success(state: dict[str, Any], booked: dict[str, Any]) -> str:
    label = booked.get("label") or state.get("selected_option", {}).get("label", "Ride")
    lines = [
        "<b>Ride requested.</b>",
        "",
        f"Service: <b>{_escape_html(label)}</b>",
    ]
    if booked.get("price"):
        lines.append(f"Price: <b>{_escape_html(booked['price'])}</b>")
    if booked.get("eta"):
        lines.append(f"ETA: {_escape_html(booked['eta'])}")
    if booked.get("driver_name"):
        lines.append(f"Driver: {_escape_html(booked['driver_name'])}")
    if booked.get("car"):
        car_line = booked["car"]
        if booked.get("plate"):
            car_line = f"{car_line} ({booked['plate']})"
        lines.append(f"Car: {_escape_html(car_line)}")
    if booked.get("trip_status"):
        lines.append(f"Status: {_escape_html(booked['trip_status'])}")
    if booked.get("notes"):
        lines.append(f"Notes: {_escape_html(booked['notes'])}")
    return "\n".join(lines)


def _extract_provider_alias(text: str) -> str | None:
    for alias in _PROVIDER_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", text, flags=re.IGNORECASE):
            return alias
    return None


def _normalize_provider(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower().strip()
    return _PROVIDER_ALIASES.get(lowered, lowered if "." in lowered else None)


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)


def _extract_location(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,!?:;")
            if value:
                return value
    return None


def _pickup_instruction(pickup: str | None) -> str:
    if pickup:
        return f'exactly as: "{pickup}"'
    return "from the account's current/default pickup if available"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            result = json.loads(stripped)
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    match = re.search(r"\{[\s\S]*\}", stripped)
    if match:
        try:
            result = json.loads(match.group())
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            result = json.loads(stripped)
            return result if isinstance(result, list) else None
        except (json.JSONDecodeError, ValueError):
            pass
    match = re.search(r"\[[\s\S]*\]", stripped)
    if match:
        try:
            result = json.loads(match.group())
            return result if isinstance(result, list) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )





