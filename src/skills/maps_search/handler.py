"""Maps search skill — dual-mode: Gemini Search Grounding (quick) + Google Maps API (detailed)."""

import json
import logging
import re
from typing import Any

import httpx
from google.genai import types

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import redis
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MAPS_GROUNDING_PROMPT = """\
You are a maps assistant with access to Google Search.
You can find real places, addresses, ratings, directions, and detailed info about locations.

Rules:
- Show MAXIMUM 5 places. No more than 5 — this is for a phone screen.
- Show place name (bold), address, rating, and whether it's open/closed.
- If the user asks for directions, provide distance, estimated time, \
and transport options (subway, bus, car, walk).
- Describe places in useful detail — hours, phone, website, what to expect.
- Include Google Maps links where possible.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the language of the user's ORIGINAL message (provided below). \
User's preferred language: {language}.
{location_hint}"""

MAPS_API_PROMPT = """\
You are a maps assistant. Format search results for Telegram.

Rules:
- Use <b>bold</b> for place names.
- Show rating, price level, open/closed status, and address.
- For directions: show total distance, travel time, and numbered steps.
- Present ALL results — the user asked for a detailed list.
- Use HTML tags only (<b>, <i>). No Markdown.
- ALWAYS respond in the same language as the user's message/query."""

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"

FALLBACK_NOTE = (
    "\n\n<i>Based on Google Search — for bulk place lists, configure GOOGLE_MAPS_API_KEY.</i>"
)

_NEARBY_KEYWORDS = (
    "рядом",
    "nearby",
    "near me",
    "ближайш",
    "поблизости",
    "around me",
    "неподалеку",
    "close to me",
)


def _is_nearby_query(query: str) -> bool:
    """Check if query contains nearby/location-dependent keywords."""
    q = query.lower()
    return any(kw in q for kw in _NEARBY_KEYWORDS)


class MapsSearchSkill:
    name = "maps_search"
    intents = ["maps_search"]
    model = "gemini-3-flash-preview"

    @observe(name="maps_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("maps_query")
            or intent_data.get("search_topic")
            or intent_data.get("search_query")
            or message.text
            or ""
        ).strip()

        if not query:
            return SkillResult(response_text="What place are you looking for?")

        language = context.language or "en"
        destination = (intent_data.get("destination") or "").strip()
        maps_mode = intent_data.get("maps_mode") or "search"
        detail_mode = bool(intent_data.get("detail_mode"))
        has_api_key = bool(settings.google_maps_api_key)

        # Location awareness: inject user's city for "nearby" queries
        # Check both extracted query AND original message text —
        # LLM may strip "рядом"/"near me" from maps_query
        user_city = context.user_profile.get("city")
        is_nearby = _is_nearby_query(query) or _is_nearby_query(message.text or "")

        if is_nearby and not user_city:
            # Store pending search so router can auto-execute after location
            pending = {
                "query": query,
                "maps_mode": maps_mode,
                "destination": destination,
                "detail_mode": detail_mode,
                "language": language,
            }
            await redis.set(
                f"maps_pending:{context.user_id}",
                json.dumps(pending),
                ex=1800,  # 30 min TTL
            )

            if language.startswith("ru"):
                return SkillResult(
                    response_text=(
                        "Чтобы найти места рядом, мне нужно знать ваш город.\n\n"
                        "Нажмите кнопку ниже или напишите "
                        'свой город, например: <b>"я в Бруклине"</b>'
                    ),
                    reply_keyboard=[
                        {"text": "\U0001f4cd Поделиться геолокацией", "request_location": True},
                    ],
                )
            return SkillResult(
                response_text=(
                    "To find nearby places, I need to know your location.\n\n"
                    "Tap the button below or tell me your city, "
                    'e.g. <b>"I\'m in Brooklyn"</b>'
                ),
                reply_keyboard=[
                    {"text": "\U0001f4cd Share location", "request_location": True},
                ],
            )

        # Enrich query with city for nearby searches
        if is_nearby and user_city:
            query = f"{query}, {user_city}"
            # Store pending search so user can update location and auto-re-search
            pending = {
                "query": (
                    intent_data.get("maps_query")
                    or intent_data.get("search_topic")
                    or intent_data.get("search_query")
                    or message.text
                    or ""
                ).strip(),
                "maps_mode": maps_mode,
                "destination": destination,
                "detail_mode": detail_mode,
                "language": language,
            }
            await redis.set(
                f"maps_pending:{context.user_id}",
                json.dumps(pending),
                ex=1800,
            )

        location_hint = ""
        if user_city:
            location_hint = (
                f"\nUser's location: {user_city}. "
                "For 'nearby' queries, ONLY show places in or near this city. "
                "Do NOT show places from other cities or countries."
            )

        # API only when user explicitly asks for more / detailed list
        if detail_mode and has_api_key:
            if maps_mode == "directions" and destination:
                answer = await get_directions(query, destination, language)
            else:
                answer = await search_places(query, language)
        else:
            # Default: Gemini grounding handles everything (search + directions)
            grounding_query = query
            if maps_mode == "directions" and destination:
                grounding_query = f"directions from {query} to {destination}"
            answer = await search_places_grounding(
                grounding_query,
                language,
                location_hint=location_hint,
                original_message=message.text or query,
            )

        # For nearby queries with a saved city, offer location update button
        if is_nearby and user_city:
            if language.startswith("ru"):
                hint = (
                    f"\n\n<i>Ищу в {user_city}. Если вы в другом городе — "
                    "нажмите кнопку ниже или напишите "
                    '"я в [город]"</i>'
                )
            else:
                hint = (
                    f"\n\n<i>Searching in {user_city}. Wrong city? "
                    "Tap the button below or type "
                    '"I\'m in [city]"</i>'
                )
            return SkillResult(
                response_text=answer + hint,
                reply_keyboard=[
                    {
                        "text": (
                            "\U0001f4cd Обновить геолокацию"
                            if language.startswith("ru")
                            else "\U0001f4cd Update location"
                        ),
                        "request_location": True,
                    },
                ],
            )

        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return MAPS_GROUNDING_PROMPT.format(
            language=context.language or "en", location_hint=""
        )


# ---------------------------------------------------------------------------
# Quick mode: Gemini + Google Search Grounding
# ---------------------------------------------------------------------------


async def search_places_grounding(
    query: str, language: str, *, location_hint: str = "", original_message: str = ""
) -> str:
    """Search for places using Gemini with Google Search grounding."""
    client = google_client()
    system = MAPS_GROUNDING_PROMPT.format(language=language, location_hint=location_hint)
    user_msg = original_message or query
    prompt = (
        f"{system}\n\nUser's original message: {user_msg}\nSearch query: {query}"
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text or ""
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini maps grounding failed: %s, falling back to LLM", e)

    # Fallback: Gemini without grounding
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        text = response.text or ""
        if text:
            return text + FALLBACK_NOTE
    except Exception as e:
        logger.error("Gemini maps fallback also failed: %s", e)

    return "I couldn't find places. Try again or rephrase your query?"


# ---------------------------------------------------------------------------
# Detailed mode: Google Maps REST API
# ---------------------------------------------------------------------------


async def search_places(query: str, language: str) -> str:
    """Search for places using Google Maps Text Search API (detailed mode)."""
    api_key = settings.google_maps_api_key
    url = f"{MAPS_API_BASE}/place/textsearch/json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                params={"query": query, "key": api_key, "language": language},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Maps text search failed: %s", e)
            return "Could not reach Google Maps. Try again later."

    results = data.get("results", [])
    if not results:
        return f"No places found for: <b>{query}</b>"

    places_text = _format_places_raw(results[:5])
    return await _format_with_gemini(places_text, query, language)


async def get_directions(origin: str, destination: str, language: str) -> str:
    """Get directions using Google Maps Directions API."""
    api_key = settings.google_maps_api_key
    url = f"{MAPS_API_BASE}/directions/json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                params={
                    "origin": origin,
                    "destination": destination,
                    "key": api_key,
                    "language": language,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Maps directions failed: %s", e)
            return "Could not get directions. Try again later."

    routes = data.get("routes", [])
    if not routes:
        return f"No route found from <b>{origin}</b> to <b>{destination}</b>."

    leg = routes[0]["legs"][0]
    distance = leg.get("distance", {}).get("text", "?")
    duration = leg.get("duration", {}).get("text", "?")
    steps = leg.get("steps", [])

    step_lines = []
    for i, step in enumerate(steps[:6], 1):
        raw = step.get("html_instructions", "")
        instruction = re.sub(r"<[^>]+>", " ", raw).strip()
        step_dist = step.get("distance", {}).get("text", "")
        step_lines.append(f"{i}. {instruction} ({step_dist})")

    if len(steps) > 6:
        step_lines.append(f"<i>…and {len(steps) - 6} more steps</i>")

    steps_block = "\n".join(step_lines)
    return (
        f"<b>{origin}</b> → <b>{destination}</b>\n"
        f"Distance: {distance} · Time: {duration}\n\n"
        f"{steps_block}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_places_raw(results: list[dict]) -> str:
    """Format Google Maps results as plain text for Gemini to reformat."""
    lines = []
    for i, place in enumerate(results, 1):
        name = place.get("name", "Unknown")
        address = place.get("formatted_address", "")
        rating = place.get("rating", "")
        price_level = place.get("price_level")
        is_open = place.get("opening_hours", {}).get("open_now")

        parts = [f"{i}. {name}"]
        if rating:
            parts.append(f"Rating: {rating}/5")
        if price_level is not None:
            parts.append("Price: " + "$" * int(price_level))
        if is_open is True:
            parts.append("Open now")
        elif is_open is False:
            parts.append("Closed")
        if address:
            parts.append(address)

        lines.append(" | ".join(parts))
    return "\n".join(lines)


async def _format_with_gemini(places_text: str, query: str, language: str) -> str:
    """Ask Gemini Flash to format the places list as Telegram HTML."""
    client = google_client()
    system = MAPS_API_PROMPT.format(language=language)
    prompt = (
        f"{system}\n\n"
        f"User searched for: {query}\n\n"
        f"Results:\n{places_text}\n\n"
        "Format these results nicely for Telegram using HTML tags. "
        "Include name (bold), rating, price, open/closed, and address."
    )
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        return response.text or _html_fallback(places_text)
    except Exception as e:
        logger.warning("Gemini places formatting failed: %s", e)
        return _html_fallback(places_text)


def _html_fallback(places_text: str) -> str:
    lines = ["<b>Search results:</b>", ""]
    lines.extend(places_text.split("\n"))
    return "\n".join(lines)


skill = MapsSearchSkill()
