"""Multi-step food delivery ordering flow via Telegram and browser automation."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from src.core.db import redis

logger = logging.getLogger(__name__)

FLOW_TTL = 900
_REDIS_PREFIX = "food_order"
MAX_RESTAURANTS = 5
MAX_MENU_ITEMS = 10

# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------

_PLATFORM_ALIASES: dict[str, str] = {
    "uber eats": "ubereats.com",
    "ubereats": "ubereats.com",
    "ubereats.com": "ubereats.com",
    "doordash": "doordash.com",
    "doordash.com": "doordash.com",
    "grubhub": "grubhub.com",
    "grubhub.com": "grubhub.com",
    "deliveroo": "deliveroo.com",
    "deliveroo.com": "deliveroo.com",
    "glovo": "glovoapp.com",
    "glovo.com": "glovoapp.com",
    "glovoapp.com": "glovoapp.com",
}

_PLATFORM_LABELS: dict[str, str] = {
    "ubereats.com": "Uber Eats",
    "doordash.com": "DoorDash",
    "grubhub.com": "Grubhub",
    "deliveroo.com": "Deliveroo",
    "glovoapp.com": "Glovo",
}

_PLATFORM_START_URLS: dict[str, str] = {
    "ubereats.com": "https://www.ubereats.com",
    "doordash.com": "https://www.doordash.com",
    "grubhub.com": "https://www.grubhub.com",
    "deliveroo.com": "https://deliveroo.com",
    "glovoapp.com": "https://glovoapp.com",
}

# ---------------------------------------------------------------------------
# i18n strings (en / ru / es)
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "need_platform": (
            "Which food delivery service should I use?\n\n"
            "Example: <i>Order pizza from Uber Eats</i>"
        ),
        "need_address": ("What's the delivery address?\n\nSend the address or place name."),
        "searching": "Searching for restaurants on <b>{platform}</b>...",
        "no_restaurants": ("No restaurants found for <b>{query}</b> on {platform} right now."),
        "restaurants_header": ("<b>{platform} — Restaurants</b>\n\nQuery: <b>{query}</b>"),
        "choose_restaurant": "Choose a restaurant or send its number.",
        "loading_menu": "Loading menu for <b>{restaurant}</b>...",
        "menu_header": "<b>{restaurant}</b> — Menu",
        "add_more": "Send item numbers to add, or tap <b>Done</b>.",
        "cart_header": "<b>Your Order</b>",
        "cart_empty": "Your cart is empty. Add items from the menu first.",
        "cart_total": (
            "Subtotal: <b>{subtotal}</b>\n"
            "Delivery: {delivery_fee}\n"
            "Tax: {tax}\n"
            "Total: <b>{total}</b>\n"
            "ETA: {eta}"
        ),
        "confirm_prompt": "Place this order? I'll only order after you confirm.",
        "order_success": (
            "<b>Order placed!</b>\n\n"
            "Order: #{order_id}\n"
            "Restaurant: {restaurant}\n"
            "ETA: {eta}\n"
            "Total: <b>{total}</b>"
        ),
        "order_failed": ("I couldn't complete the order.\n\n<code>{notes}</code>"),
        "price_changed": "<b>The total changed before ordering.</b>\n\n",
        "captcha": (
            "The platform showed a CAPTCHA. Open the connect flow below, "
            "solve it, and I'll continue."
        ),
        "login_needed": (
            "I need access to <b>{platform}</b> to search restaurants.\n\n"
            "Tap the connect button below and log in in your browser.\n"
            "When the login finishes, the session will be saved automatically."
        ),
        "login_still_no_session": ("I still don't see a saved session for this platform."),
        "no_flow": "No active food order.",
        "error_extract": (
            "I couldn't extract restaurant data from the platform.\n\n<code>{raw}</code>"
        ),
        "item_added": "Added <b>{item}</b> to cart ({count} item(s) total).",
        "item_removed": "Removed <b>{item}</b> from cart ({count} item(s) total).",
        # Button labels
        "btn_cancel": "Cancel",
        "btn_confirm": "Confirm order",
        "btn_back": "Back to restaurants",
        "btn_back_menu": "Back to menu",
        "btn_ready": "Ready — continue",
        "btn_done": "Done — review order",
        "btn_confirm_updated": "Confirm updated total",
        "cancelled": "Food order cancelled.",
    },
    "ru": {
        "need_platform": (
            "Какой сервис доставки использовать?\n\nПример: <i>Закажи пиццу через Uber Eats</i>"
        ),
        "need_address": ("Какой адрес доставки?\n\nОтправьте адрес или название места."),
        "searching": "Ищу рестораны на <b>{platform}</b>...",
        "no_restaurants": ("Не нашёл ресторанов по запросу <b>{query}</b> на {platform}."),
        "restaurants_header": ("<b>{platform} — Рестораны</b>\n\nЗапрос: <b>{query}</b>"),
        "choose_restaurant": "Выберите ресторан или отправьте его номер.",
        "loading_menu": "Загружаю меню <b>{restaurant}</b>...",
        "menu_header": "<b>{restaurant}</b> — Меню",
        "add_more": "Отправьте номера блюд или нажмите <b>Готово</b>.",
        "cart_header": "<b>Ваш заказ</b>",
        "cart_empty": "Корзина пуста. Сначала добавьте блюда из меню.",
        "cart_total": (
            "Подитог: <b>{subtotal}</b>\n"
            "Доставка: {delivery_fee}\n"
            "Налог: {tax}\n"
            "Итого: <b>{total}</b>\n"
            "ETA: {eta}"
        ),
        "confirm_prompt": "Оформить заказ? Закажу только после вашего подтверждения.",
        "order_success": (
            "<b>Заказ оформлен!</b>\n\n"
            "Заказ: #{order_id}\n"
            "Ресторан: {restaurant}\n"
            "ETA: {eta}\n"
            "Итого: <b>{total}</b>"
        ),
        "order_failed": ("Не удалось оформить заказ.\n\n<code>{notes}</code>"),
        "price_changed": "<b>Сумма изменилась перед оформлением.</b>\n\n",
        "captcha": ("Платформа показала CAPTCHA. Откройте ссылку ниже, решите её, и я продолжу."),
        "login_needed": (
            "Мне нужен доступ к <b>{platform}</b> для поиска ресторанов.\n\n"
            "Нажмите кнопку ниже и войдите в аккаунт в браузере.\n"
            "После входа сессия сохранится автоматически."
        ),
        "login_still_no_session": ("Всё ещё не вижу сохранённой сессии для этой платформы."),
        "no_flow": "Нет активного заказа еды.",
        "error_extract": ("Не удалось извлечь данные ресторанов.\n\n<code>{raw}</code>"),
        "item_added": "Добавлено <b>{item}</b> в корзину ({count} позиций).",
        "item_removed": "Убрано <b>{item}</b> из корзины ({count} позиций).",
        "btn_cancel": "Отмена",
        "btn_confirm": "Подтвердить заказ",
        "btn_back": "К ресторанам",
        "btn_back_menu": "К меню",
        "btn_ready": "Готово — продолжить",
        "btn_done": "Готово — проверить заказ",
        "btn_confirm_updated": "Подтвердить новую сумму",
        "cancelled": "Заказ еды отменён.",
    },
    "es": {
        "need_platform": (
            "¿Qué servicio de entrega debo usar?\n\nEjemplo: <i>Pide pizza por Uber Eats</i>"
        ),
        "need_address": (
            "¿Cuál es la dirección de entrega?\n\nEnvía la dirección o el nombre del lugar."
        ),
        "searching": "Buscando restaurantes en <b>{platform}</b>...",
        "no_restaurants": ("No encontré restaurantes para <b>{query}</b> en {platform}."),
        "restaurants_header": ("<b>{platform} — Restaurantes</b>\n\nBúsqueda: <b>{query}</b>"),
        "choose_restaurant": "Elige un restaurante o envía su número.",
        "loading_menu": "Cargando menú de <b>{restaurant}</b>...",
        "menu_header": "<b>{restaurant}</b> — Menú",
        "add_more": "Envía los números de los platos o presiona <b>Listo</b>.",
        "cart_header": "<b>Tu pedido</b>",
        "cart_empty": "Tu carrito está vacío. Primero agrega platos del menú.",
        "cart_total": (
            "Subtotal: <b>{subtotal}</b>\n"
            "Envío: {delivery_fee}\n"
            "Impuesto: {tax}\n"
            "Total: <b>{total}</b>\n"
            "ETA: {eta}"
        ),
        "confirm_prompt": "¿Confirmar pedido? Solo ordenaré después de tu confirmación.",
        "order_success": (
            "<b>¡Pedido realizado!</b>\n\n"
            "Pedido: #{order_id}\n"
            "Restaurante: {restaurant}\n"
            "ETA: {eta}\n"
            "Total: <b>{total}</b>"
        ),
        "order_failed": ("No pude completar el pedido.\n\n<code>{notes}</code>"),
        "price_changed": "<b>El total cambió antes del pedido.</b>\n\n",
        "captcha": (
            "La plataforma mostró un CAPTCHA. Abre el enlace abajo, resuélvelo y continuaré."
        ),
        "login_needed": (
            "Necesito acceso a <b>{platform}</b> para buscar restaurantes.\n\n"
            "Presiona el botón y entra a tu cuenta en el navegador.\n"
            "La sesión se guardará automáticamente."
        ),
        "login_still_no_session": ("Aún no veo una sesión guardada para esta plataforma."),
        "no_flow": "No hay pedido de comida activo.",
        "error_extract": ("No pude extraer datos de restaurantes.\n\n<code>{raw}</code>"),
        "item_added": "Agregado <b>{item}</b> al carrito ({count} artículos).",
        "item_removed": "Eliminado <b>{item}</b> del carrito ({count} artículos).",
        "btn_cancel": "Cancelar",
        "btn_confirm": "Confirmar pedido",
        "btn_back": "Volver a restaurantes",
        "btn_back_menu": "Volver al menú",
        "btn_ready": "Listo — continuar",
        "btn_done": "Listo — revisar pedido",
        "btn_confirm_updated": "Confirmar nuevo total",
        "cancelled": "Pedido de comida cancelado.",
    },
}


def _t(key: str, lang: str, **kwargs: Any) -> str:
    strings = _STRINGS.get(lang, _STRINGS["en"])
    template = strings.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


# ---------------------------------------------------------------------------
# Browser task prompts
# ---------------------------------------------------------------------------

_SEARCH_PROMPT = """\
Open {site_url} and search for restaurants.

Food request:
- Search query: "{query}"
- Delivery address: {address}

Steps:
1. Dismiss cookie banners, promos, or overlays.
2. Use the current account session. If login is required, STOP and return exactly:
LOGIN_REQUIRED
3. If the site asks for a delivery address, enter: "{address}"
4. Search for "{query}" using the search bar.
5. Wait until the restaurant results load.
6. Return ONLY a JSON array with up to {max_results} restaurants:

[
  {{
    "name": "Pizza Palace",
    "rating": "4.7",
    "delivery_time": "25-35 min",
    "delivery_fee": "$2.99",
    "cuisine": "Pizza, Italian",
    "price_range": "$$"
  }}
]

Rules:
- If no restaurants are found, return exactly: NO_RESTAURANTS
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED
- Keep strings short and factual
- Do not include markdown or explanation outside the JSON array"""

_MENU_PROMPT = """\
Open {site_url} and navigate to the restaurant "{restaurant}".

Steps:
1. Use the current account session. If login is required, return exactly:
LOGIN_REQUIRED
2. Navigate to the restaurant page for "{restaurant}".
3. Wait for the menu to load.
4. Extract up to {max_items} menu items from the most popular or featured section.
5. Return ONLY a JSON array:

[
  {{
    "name": "Margherita Pizza",
    "price": "$12.99",
    "description": "Fresh mozzarella, tomato sauce, basil",
    "section": "Popular Items"
  }}
]

Rules:
- Prioritise "Popular", "Featured", or "Most Ordered" sections.
- If no menu loads, return exactly: NO_MENU
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED"""

_CART_PROMPT = """\
You are on {site_url} viewing the restaurant "{restaurant}".

Add these items to the cart:
{items_list}

Steps:
1. Use the current session. If login is required, return exactly: LOGIN_REQUIRED
2. Add each item to the cart by clicking its "Add" / "+" button.
   If an item has required customisation (size, toppings), pick the default / first option.
3. After all items are added, open the cart / checkout page.
4. Do NOT click the final "Place Order" button.
5. Return ONLY valid JSON:

{{
  "status": "READY_TO_ORDER",
  "items": [
    {{"name": "Margherita Pizza", "price": "$12.99", "quantity": 1}}
  ],
  "subtotal": "$25.98",
  "delivery_fee": "$2.99",
  "tax": "$2.08",
  "total": "$31.05",
  "eta": "30-40 min",
  "address": "123 Main St"
}}

Rules:
- If an item is unavailable, skip it and note in "notes" field.
- If the cart total exceeds expectations, return {{"status": "PRICE_WARNING", ...}}
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED"""

_CONFIRM_PROMPT = """\
You are on the checkout / order review screen at {site_url}.

Expected order:
- Restaurant: {restaurant}
- Items: {item_count} item(s)
- Expected total: {expected_total}

Steps:
1. Verify the screen still shows the expected order.
2. If login is required, return exactly: LOGIN_REQUIRED
3. If the total changed materially, DO NOT confirm.
   Return: {{"status": "PRICE_CHANGED", "total": "new total", "notes": "what changed"}}
4. Click the final "Place Order" / "Confirm" button and wait for confirmation.
5. Return ONLY valid JSON:

{{
  "status": "ORDERED",
  "order_id": "ABC123",
  "restaurant": "{restaurant}",
  "eta": "30-40 min",
  "total": "$31.05",
  "items_count": {item_count},
  "notes": ""
}}

Rules:
- If the order fails, return {{"status": "FAILED", "notes": "reason"}}
- If a CAPTCHA appears, return exactly: CAPTCHA_DETECTED"""

# ---------------------------------------------------------------------------
# Redis state management
# ---------------------------------------------------------------------------


async def get_food_state(user_id: str) -> dict[str, Any] | None:
    try:
        raw = await redis.get(f"{_REDIS_PREFIX}:{user_id}")
    except Exception as e:
        logger.warning("Failed to read food order state for %s: %s", user_id, e)
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
        logger.warning("Failed to store food order state for %s: %s", user_id, e)


async def _clear_state(user_id: str) -> None:
    try:
        await redis.delete(f"{_REDIS_PREFIX}:{user_id}")
    except Exception as e:
        logger.warning("Failed to clear food order state for %s: %s", user_id, e)


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def parse_food_request(task: str, site_hint: str | None = None) -> dict[str, Any]:
    text = (task or "").strip()
    lower = text.lower()

    platform = _normalize_platform(site_hint or _extract_platform_alias(lower))
    query = _extract_food_query(text, lower)
    address = _extract_address(text)

    return {
        "platform": platform,
        "query": query,
        "address": address,
        "task": text,
    }


# ---------------------------------------------------------------------------
# Public flow API
# ---------------------------------------------------------------------------


async def start_flow(
    user_id: str,
    family_id: str,
    task: str,
    language: str = "en",
    site_hint: str | None = None,
) -> dict[str, Any]:
    parsed = parse_food_request(task, site_hint)
    platform = parsed["platform"]
    query = parsed["query"]

    flow_id = str(uuid.uuid4())[:8]
    state: dict[str, Any] = {
        "flow_id": flow_id,
        "user_id": user_id,
        "family_id": family_id,
        "language": language,
        "platform": platform,
        "platform_label": _platform_label(platform) if platform else "",
        "query": query or task,
        "address": parsed["address"],
        "task": task,
        "cart": [],
    }

    if not platform:
        state["step"] = "selecting_platform"
        await _set_state(user_id, state)
        buttons = [
            {
                "text": label,
                "callback": f"food_platform:{flow_id}:{domain}",
            }
            for domain, label in _PLATFORM_LABELS.items()
        ]
        buttons.append({"text": _t("btn_cancel", language), "callback": f"food_cancel:{flow_id}"})
        return {
            "action": "need_platform",
            "text": _t("need_platform", language),
            "buttons": buttons,
        }

    state["step"] = "checking_auth"
    await _set_state(user_id, state)
    return await _check_auth_and_search(user_id)


async def handle_platform_selection(user_id: str, platform: str) -> dict[str, Any]:
    state = await get_food_state(user_id)
    if not state or state.get("step") != "selecting_platform":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    normalized = _normalize_platform(platform)
    if not normalized:
        normalized = platform

    state["platform"] = normalized
    state["platform_label"] = _platform_label(normalized)
    state["step"] = "checking_auth"
    await _set_state(user_id, state)
    return await _check_auth_and_search(user_id)


async def handle_login_ready(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state or state.get("step") != "awaiting_login":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    platform = state["platform"]
    storage_state = await browser_service.get_storage_state(user_id, platform)
    if not storage_state:
        return await _build_login_prompt(
            state,
            prefix=_t("login_still_no_session", lang),
        )

    state["step"] = "searching"
    await _set_state(user_id, state)
    return await _execute_restaurant_search(user_id)


async def handle_restaurant_selection(user_id: str, index: int) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state or state.get("step") != "awaiting_restaurant":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    restaurants = state.get("restaurants", [])
    if index < 0 or index >= len(restaurants):
        return {
            "action": "error",
            "text": f"Invalid option. Choose 1-{len(restaurants)}.",
        }

    selected = restaurants[index]
    state["selected_restaurant"] = selected
    state["step"] = "loading_menu"
    await _set_state(user_id, state)

    platform = state["platform"]
    restaurant_name = selected.get("name", "")
    prompt = _MENU_PROMPT.format(
        site_url=_start_url(platform),
        restaurant=restaurant_name,
        max_items=MAX_MENU_ITEMS,
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=platform,
        task=prompt,
        max_steps=20,
        timeout=120,
    )
    raw = result.get("result", "")

    if "LOGIN_REQUIRED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_login_prompt(state)

    if "CAPTCHA_DETECTED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_captcha_prompt(state)

    if "NO_MENU" in raw.upper():
        state["step"] = "awaiting_restaurant"
        await _set_state(user_id, state)
        return {
            "action": "no_menu",
            "text": f"Couldn't load menu for <b>{_escape_html(restaurant_name)}</b>. Try another.",
            "buttons": _build_restaurant_buttons(restaurants, state["flow_id"], lang),
        }

    menu_items = _extract_json_array(raw)
    if not menu_items:
        return {
            "action": "error",
            "text": _t("error_extract", lang, raw=_escape_html(raw[:300])),
        }

    state["menu_items"] = menu_items[:MAX_MENU_ITEMS]
    state["cart"] = []
    state["step"] = "viewing_menu"
    await _set_state(user_id, state)
    return {
        "action": "menu",
        "text": _format_menu_text(state),
        "buttons": _build_menu_buttons(menu_items[:MAX_MENU_ITEMS], state["flow_id"], lang),
    }


async def handle_menu_item_toggle(user_id: str, index: int) -> dict[str, Any]:
    state = await get_food_state(user_id)
    if not state or state.get("step") != "viewing_menu":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    menu_items = state.get("menu_items", [])
    cart: list[dict[str, Any]] = state.get("cart", [])

    if index < 0 or index >= len(menu_items):
        return {
            "action": "error",
            "text": f"Invalid item. Choose 1-{len(menu_items)}.",
        }

    item = menu_items[index]
    item_name = item.get("name", f"Item {index + 1}")

    # Toggle: if already in cart, remove; else add
    existing_idx = next(
        (i for i, c in enumerate(cart) if c.get("name") == item_name),
        None,
    )
    if existing_idx is not None:
        cart.pop(existing_idx)
        state["cart"] = cart
        await _set_state(user_id, state)
        return {
            "action": "item_removed",
            "text": (
                _t("item_removed", lang, item=_escape_html(item_name), count=len(cart))
                + "\n\n"
                + _format_menu_text(state)
            ),
            "buttons": _build_menu_buttons(menu_items, state["flow_id"], lang),
        }

    cart.append({"name": item_name, "price": item.get("price", ""), "index": index})
    state["cart"] = cart
    await _set_state(user_id, state)
    return {
        "action": "item_added",
        "text": (
            _t("item_added", lang, item=_escape_html(item_name), count=len(cart))
            + "\n\n"
            + _format_menu_text(state)
        ),
        "buttons": _build_menu_buttons(menu_items, state["flow_id"], lang),
    }


async def handle_done_selecting(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state or state.get("step") != "viewing_menu":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    cart = state.get("cart", [])
    if not cart:
        return {
            "action": "cart_empty",
            "text": _t("cart_empty", lang),
            "buttons": _build_menu_buttons(state.get("menu_items", []), state["flow_id"], lang),
        }

    state["step"] = "building_cart"
    await _set_state(user_id, state)

    platform = state["platform"]
    restaurant = state.get("selected_restaurant", {}).get("name", "")
    items_list = "\n".join(f"- {c.get('name', 'item')} ({c.get('price', '')})" for c in cart)
    prompt = _CART_PROMPT.format(
        site_url=_start_url(platform),
        restaurant=restaurant,
        items_list=items_list,
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=platform,
        task=prompt,
        max_steps=25,
        timeout=180,
    )
    raw = result.get("result", "")

    if "LOGIN_REQUIRED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_login_prompt(state)

    if "CAPTCHA_DETECTED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_captcha_prompt(state)

    review = _extract_json_object(raw)
    if not review:
        await _clear_state(user_id)
        return {
            "action": "error",
            "text": _t("error_extract", lang, raw=_escape_html(raw[:300])),
        }

    status = (review.get("status") or "").upper()
    if status in ("READY_TO_ORDER", "PRICE_WARNING"):
        state["review"] = review
        state["step"] = "confirming"
        await _set_state(user_id, state)
        return {
            "action": "confirming",
            "text": _format_cart_review_text(state),
            "buttons": [
                {"text": _t("btn_confirm", lang), "callback": f"food_confirm:{state['flow_id']}"},
                {
                    "text": _t("btn_back_menu", lang),
                    "callback": f"food_back_menu:{state['flow_id']}",
                },
                {"text": _t("btn_cancel", lang), "callback": f"food_cancel:{state['flow_id']}"},
            ],
        }

    await _clear_state(user_id)
    return {
        "action": "error",
        "text": _t("error_extract", lang, raw=_escape_html(raw[:300])),
    }


async def confirm_order(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state or state.get("step") != "confirming":
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    review = state.get("review", {})
    restaurant = state.get("selected_restaurant", {}).get("name", "")
    cart = state.get("cart", [])
    platform = state["platform"]

    prompt = _CONFIRM_PROMPT.format(
        site_url=_start_url(platform),
        restaurant=restaurant,
        item_count=len(cart),
        expected_total=review.get("total", ""),
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=platform,
        task=prompt,
        max_steps=20,
        timeout=180,
    )
    raw = result.get("result", "")
    ordered = _extract_json_object(raw)
    status = (ordered or {}).get("status", "").upper()

    if "LOGIN_REQUIRED" in raw.upper() or status == "LOGIN_REQUIRED":
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_login_prompt(state)

    if status == "PRICE_CHANGED":
        state["review"] = {
            **review,
            "total": ordered.get("total", review.get("total", "")),
            "notes": ordered.get("notes", ""),
        }
        await _set_state(user_id, state)
        return {
            "action": "price_changed",
            "text": _t("price_changed", lang) + _format_cart_review_text(state),
            "buttons": [
                {
                    "text": _t("btn_confirm_updated", lang),
                    "callback": f"food_confirm:{state['flow_id']}",
                },
                {"text": _t("btn_back", lang), "callback": f"food_back:{state['flow_id']}"},
                {"text": _t("btn_cancel", lang), "callback": f"food_cancel:{state['flow_id']}"},
            ],
        }

    if not ordered or status not in ("ORDERED", "CONFIRMED"):
        notes = ordered.get("notes", "") if ordered else raw[:200]
        await _clear_state(user_id)
        return {
            "action": "failed",
            "text": _t("order_failed", lang, notes=_escape_html(notes)),
        }

    await _clear_state(user_id)
    return {
        "action": "ordered",
        "text": _t(
            "order_success",
            lang,
            order_id=_escape_html(ordered.get("order_id", "—")),
            restaurant=_escape_html(ordered.get("restaurant", restaurant)),
            eta=_escape_html(ordered.get("eta", "—")),
            total=_escape_html(ordered.get("total", "")),
        ),
    }


async def handle_back_to_restaurants(user_id: str) -> dict[str, Any]:
    state = await get_food_state(user_id)
    if not state or not state.get("restaurants"):
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    state["step"] = "awaiting_restaurant"
    state.pop("selected_restaurant", None)
    state.pop("menu_items", None)
    state.pop("cart", None)
    state.pop("review", None)
    state["cart"] = []
    await _set_state(user_id, state)
    return {
        "action": "results",
        "text": _format_restaurants_text(state),
        "buttons": _build_restaurant_buttons(state["restaurants"], state["flow_id"], lang),
    }


async def handle_back_to_menu(user_id: str) -> dict[str, Any]:
    state = await get_food_state(user_id)
    if not state or not state.get("menu_items"):
        lang = state.get("language", "en") if state else "en"
        return {"action": "no_flow", "text": _t("no_flow", lang)}

    lang = state.get("language", "en")
    state["step"] = "viewing_menu"
    state.pop("review", None)
    await _set_state(user_id, state)
    return {
        "action": "menu",
        "text": _format_menu_text(state),
        "buttons": _build_menu_buttons(state.get("menu_items", []), state["flow_id"], lang),
    }


async def handle_text_input(user_id: str, text: str) -> dict[str, Any] | None:
    state = await get_food_state(user_id)
    if not state:
        return None

    step = state.get("step")
    lowered = (text or "").strip().lower()

    if step == "awaiting_address":
        address = (text or "").strip()
        if not address:
            return None
        state["address"] = address
        state["step"] = "checking_auth"
        await _set_state(user_id, state)
        return await _check_auth_and_search(user_id)

    if step == "awaiting_login":
        if any(w in lowered for w in ("ready", "готово", "done", "saved", "listo")):
            return await handle_login_ready(user_id)
        return None

    if step == "awaiting_restaurant":
        restaurants = state.get("restaurants", [])
        if lowered.isdigit():
            index = int(lowered) - 1
            if 0 <= index < len(restaurants):
                return await handle_restaurant_selection(user_id, index)
        for index, r in enumerate(restaurants):
            if lowered and lowered in r.get("name", "").lower():
                return await handle_restaurant_selection(user_id, index)
        return None

    if step == "viewing_menu":
        menu_items = state.get("menu_items", [])
        # "done" / "готово" / "listo" → proceed to cart
        if any(w in lowered for w in ("done", "готово", "listo", "order", "заказ")):
            return await handle_done_selecting(user_id)
        # Number → toggle menu item
        if lowered.isdigit():
            index = int(lowered) - 1
            if 0 <= index < len(menu_items):
                return await handle_menu_item_toggle(user_id, index)
        return None

    if step == "confirming":
        if any(w in lowered for w in ("yes", "да", "confirm", "подтверж", "sí", "confirmar")):
            return await confirm_order(user_id)
        if any(w in lowered for w in ("back", "назад", "no", "нет", "cancel", "отмена")):
            return await handle_back_to_restaurants(user_id)
        return None

    return None


async def cancel_flow(user_id: str) -> None:
    await _clear_state(user_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _check_auth_and_search(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state:
        return {"action": "no_flow", "text": _t("no_flow", "en")}

    platform = state["platform"]
    storage_state = await browser_service.get_storage_state(user_id, platform)
    if not storage_state:
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_login_prompt(state)

    state["step"] = "searching"
    await _set_state(user_id, state)
    return await _execute_restaurant_search(user_id)


async def _execute_restaurant_search(user_id: str) -> dict[str, Any]:
    from src.tools import browser_service

    state = await get_food_state(user_id)
    if not state:
        return {"action": "no_flow", "text": _t("no_flow", "en")}

    lang = state.get("language", "en")
    platform = state["platform"]
    query = state.get("query", "")
    address = state.get("address") or "use default address from account"

    prompt = _SEARCH_PROMPT.format(
        site_url=_start_url(platform),
        query=query,
        address=address,
        max_results=MAX_RESTAURANTS,
    )
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=platform,
        task=prompt,
        max_steps=25,
        timeout=180,
    )
    raw = result.get("result", "")

    if "LOGIN_REQUIRED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_login_prompt(state)

    if "CAPTCHA_DETECTED" in raw.upper():
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await _build_captcha_prompt(state)

    if "NO_RESTAURANTS" in raw.upper():
        await _clear_state(user_id)
        return {
            "action": "no_restaurants",
            "text": _t(
                "no_restaurants",
                lang,
                query=_escape_html(query),
                platform=_platform_label(platform),
            ),
        }

    restaurants = _extract_json_array(raw)
    if not restaurants:
        await _clear_state(user_id)
        return {
            "action": "error",
            "text": _t("error_extract", lang, raw=_escape_html(raw[:300])),
        }

    state["step"] = "awaiting_restaurant"
    state["restaurants"] = restaurants[:MAX_RESTAURANTS]
    await _set_state(user_id, state)
    return {
        "action": "results",
        "text": _format_restaurants_text(state),
        "buttons": _build_restaurant_buttons(state["restaurants"], state["flow_id"], lang),
    }


async def _build_login_prompt(
    state: dict[str, Any],
    prefix: str | None = None,
) -> dict[str, Any]:
    connect_url = await _get_connect_url(state)
    lang = state.get("language", "en")
    platform = state["platform"]
    platform_label = _platform_label(platform)
    flow_id = state["flow_id"]

    intro = prefix or _t("login_needed", lang, platform=platform_label)
    return {
        "action": "need_login",
        "text": intro,
        "buttons": [
            {"text": f"Connect {platform_label}", "url": connect_url},
            {"text": _t("btn_ready", lang), "callback": f"food_login_ready:{flow_id}"},
            {"text": _t("btn_cancel", lang), "callback": f"food_cancel:{flow_id}"},
        ],
    }


async def _build_captcha_prompt(state: dict[str, Any]) -> dict[str, Any]:
    connect_url = await _get_connect_url(state)
    lang = state.get("language", "en")
    platform = state["platform"]
    platform_label = _platform_label(platform)
    flow_id = state["flow_id"]

    return {
        "action": "captcha",
        "text": _t("captcha", lang),
        "buttons": [
            {"text": f"Connect {platform_label}", "url": connect_url},
            {"text": _t("btn_ready", lang), "callback": f"food_login_ready:{flow_id}"},
            {"text": _t("btn_cancel", lang), "callback": f"food_cancel:{flow_id}"},
        ],
    }


async def _get_connect_url(state: dict[str, Any]) -> str:
    from src.tools import browser_service, remote_browser_connect

    platform = state["platform"]
    user_id = state.get("user_id")
    family_id = state.get("family_id")
    if user_id and family_id:
        try:
            return await remote_browser_connect.create_connect_url(user_id, family_id, platform)
        except Exception as e:
            logger.warning("Connect URL fallback for %s: %s", platform, e)
    return browser_service.get_connect_url(platform)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _build_restaurant_buttons(
    restaurants: list[dict[str, Any]], flow_id: str, lang: str
) -> list[dict[str, str]]:
    buttons = []
    for i, r in enumerate(restaurants[:MAX_RESTAURANTS]):
        name = r.get("name") or f"Restaurant {i + 1}"
        rating = r.get("rating") or ""
        time_ = r.get("delivery_time") or ""
        suffix = " • ".join(p for p in (rating, time_) if p).strip()
        text = f"{i + 1}. {name}"
        if suffix:
            text = f"{text} ({suffix})"
        buttons.append({"text": text[:64], "callback": f"food_select:{flow_id}:{i}"})
    buttons.append({"text": _t("btn_cancel", lang), "callback": f"food_cancel:{flow_id}"})
    return buttons


def _build_menu_buttons(
    menu_items: list[dict[str, Any]], flow_id: str, lang: str
) -> list[dict[str, str]]:
    buttons = []
    for i, item in enumerate(menu_items[:MAX_MENU_ITEMS]):
        name = item.get("name") or f"Item {i + 1}"
        price = item.get("price") or ""
        text = f"{i + 1}. {name}"
        if price:
            text = f"{text} {price}"
        buttons.append({"text": text[:64], "callback": f"food_item:{flow_id}:{i}"})
    buttons.append({"text": _t("btn_done", lang), "callback": f"food_done:{flow_id}"})
    buttons.append({"text": _t("btn_back", lang), "callback": f"food_back:{flow_id}"})
    buttons.append({"text": _t("btn_cancel", lang), "callback": f"food_cancel:{flow_id}"})
    return buttons


def _format_restaurants_text(state: dict[str, Any]) -> str:
    lang = state.get("language", "en")
    platform = _platform_label(state.get("platform", ""))
    query = _escape_html(state.get("query", ""))

    lines = [_t("restaurants_header", lang, platform=platform, query=query), ""]

    for i, r in enumerate(state.get("restaurants", []), start=1):
        name = _escape_html(r.get("name", "Restaurant"))
        bits = [f"<b>{i}. {name}</b>"]
        meta = " • ".join(
            _escape_html(p)
            for p in (
                r.get("rating", ""),
                r.get("delivery_time", ""),
                r.get("delivery_fee", ""),
                r.get("cuisine", ""),
            )
            if p
        )
        if meta:
            bits.append(meta)
        lines.append("\n".join(bits))
        lines.append("")

    lines.append(_t("choose_restaurant", lang))
    return "\n".join(lines).strip()


def _format_menu_text(state: dict[str, Any]) -> str:
    lang = state.get("language", "en")
    restaurant = _escape_html(state.get("selected_restaurant", {}).get("name", "Restaurant"))
    cart = state.get("cart", [])
    cart_names = {c.get("name") for c in cart}

    lines = [_t("menu_header", lang, restaurant=restaurant), ""]

    for i, item in enumerate(state.get("menu_items", []), start=1):
        name = item.get("name", "Item")
        price = item.get("price", "")
        desc = item.get("description", "")
        in_cart = "  ✓" if name in cart_names else ""
        bits = [f"<b>{i}. {_escape_html(name)}</b> {_escape_html(price)}{in_cart}"]
        if desc:
            bits.append(f"  <i>{_escape_html(desc[:80])}</i>")
        lines.append("\n".join(bits))

    lines.append("")
    if cart:
        lines.append(f"Cart: {len(cart)} item(s)")
    lines.append(_t("add_more", lang))
    return "\n".join(lines).strip()


def _format_cart_review_text(state: dict[str, Any]) -> str:
    lang = state.get("language", "en")
    review = state.get("review", {})
    restaurant = _escape_html(state.get("selected_restaurant", {}).get("name", "Restaurant"))

    lines = [_t("cart_header", lang), "", f"Restaurant: <b>{restaurant}</b>", ""]

    items = review.get("items", state.get("cart", []))
    for item in items:
        name = _escape_html(item.get("name", ""))
        price = _escape_html(item.get("price", ""))
        qty = item.get("quantity", 1)
        line = f"  • {name} — {price}"
        if qty and qty > 1:
            line += f" ×{qty}"
        lines.append(line)

    lines.append("")
    lines.append(
        _t(
            "cart_total",
            lang,
            subtotal=_escape_html(review.get("subtotal", "—")),
            delivery_fee=_escape_html(review.get("delivery_fee", "—")),
            tax=_escape_html(review.get("tax", "—")),
            total=_escape_html(review.get("total", "—")),
            eta=_escape_html(review.get("eta", "—")),
        )
    )
    lines.append("")
    lines.append(_t("confirm_prompt", lang))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _extract_platform_alias(text: str) -> str | None:
    # Check multi-word aliases first (e.g. "uber eats" before "uber")
    for alias in sorted(_PLATFORM_ALIASES, key=len, reverse=True):
        if alias in text:
            return alias
    return None


def _normalize_platform(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower().strip()
    if lowered in _PLATFORM_ALIASES:
        return _PLATFORM_ALIASES[lowered]
    for alias, canonical in sorted(_PLATFORM_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lowered:
            return canonical
    if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", lowered):
        return lowered
    return None


def _platform_label(platform: str) -> str:
    return _PLATFORM_LABELS.get(platform, platform)


def _start_url(platform: str) -> str:
    return _PLATFORM_START_URLS.get(platform, f"https://{platform}")


def _extract_food_query(text: str, lower: str) -> str | None:
    """Extract cuisine/restaurant name from the request."""
    patterns = (
        # English: "order pizza from ...", "get sushi on ..."
        r"\b(?:order|get|find|search|deliver)\s+(.+?)(?:\s+(?:from|on|via|through|at)\b|$)",
        # Russian: "закажи пиццу", "доставка суши", "доставка из McDonald's"
        r"\b(?:закажи|заказать|найди|доставк[аиу])\s+(.+?)(?:\s+(?:из|через|на|от|с)\b|$)",
        r"\b(?:доставк[аиу]|доставить)\s+(?:из\s+)?(.+?)$",
        # Spanish: "pide pizza", "ordena sushi"
        r"\b(?:pide|ordena|busca|entrega)\s+(.+?)(?:\s+(?:de|en|por|desde)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" .,!?:;")
            # Remove platform names from query
            for alias in _PLATFORM_ALIASES:
                query = re.sub(rf"\b{re.escape(alias)}\b", "", query, flags=re.IGNORECASE)
            query = re.sub(r"\s{2,}", " ", query).strip(" ,.")
            if query and len(query) >= 2:
                return query
    return None


def _extract_address(text: str) -> str | None:
    """Extract delivery address from the request."""
    patterns = (
        r"\b(?:to|deliver to|address|at)\s+(.+?)(?:\s*$)",
        r"\b(?:на адрес|по адресу|доставить на|доставка на)\s+(.+?)(?:\s*$)",
        r"\b(?:a la dirección|entregar en|dirección)\s+(.+?)(?:\s*$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            addr = match.group(1).strip(" .,!?:;")
            if addr and len(addr) >= 5:
                return addr
    return None


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


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
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
