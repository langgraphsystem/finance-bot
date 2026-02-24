"""Shopping list skills — add, view, remove, clear items from shopping lists."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.shopping_list import ShoppingList, ShoppingListItem
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DEFAULT_LIST_NAME = "grocery"

SHOPPING_LIST_SYSTEM_PROMPT = """\
You help users manage shopping lists — grocery, hardware, pharmacy, or any other list.
Add items, show the list, check off items, and clear completed lists.
Be concise: one-line confirmations, structured lists.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""


def _parse_list_name(intent_data: dict[str, Any]) -> str:
    """Extract list name from intent data, default to 'grocery'."""
    raw = intent_data.get("shopping_list_name")
    if raw:
        return raw.strip().lower()[:100]
    return DEFAULT_LIST_NAME


def _parse_items(intent_data: dict[str, Any], text: str) -> list[str]:
    """Extract item names from intent data or raw text."""
    items = intent_data.get("shopping_items")
    if items and isinstance(items, list):
        return [i.strip() for i in items if i and i.strip()]

    # Fallback: parse from text — remove common prefixes
    cleaned = text
    for prefix in [
        "add",
        "put",
        "need",
        "buy",
        "get",
        "добавь",
        "положи",
        "нужно",
        "купи",
        "купить",
        "добавить",
        "в список",
        "to my list",
        "to the list",
        "to my shopping list",
        "в мой список",
        "в список покупок",
    ]:
        cleaned = cleaned.lower().replace(prefix, "")

    # Split on commas and "and"/"и"
    for sep in [",", " and ", " и "]:
        cleaned = cleaned.replace(sep, ",")

    items = [i.strip() for i in cleaned.split(",") if i.strip()]
    return items


async def _get_or_create_list(family_id: uuid.UUID, user_id: uuid.UUID, name: str) -> ShoppingList:
    """Get existing list or create a new one."""
    async with async_session() as session:
        result = await session.execute(
            select(ShoppingList).where(
                ShoppingList.family_id == family_id,
                func.lower(ShoppingList.name) == name.lower(),
            )
        )
        shopping_list = result.scalar_one_or_none()

        if not shopping_list:
            shopping_list = ShoppingList(
                id=uuid.uuid4(),
                family_id=family_id,
                user_id=user_id,
                name=name,
            )
            session.add(shopping_list)
            await session.commit()
            await session.refresh(shopping_list)

        return shopping_list


async def _get_most_recent_list(family_id: uuid.UUID) -> ShoppingList | None:
    """Get the most recently updated list for this family."""
    async with async_session() as session:
        result = await session.execute(
            select(ShoppingList)
            .where(ShoppingList.family_id == family_id)
            .order_by(ShoppingList.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _get_unchecked_items(list_id: uuid.UUID) -> list[ShoppingListItem]:
    """Get unchecked items for a list."""
    async with async_session() as session:
        result = await session.execute(
            select(ShoppingListItem)
            .where(
                ShoppingListItem.list_id == list_id,
                ShoppingListItem.is_checked.is_(False),
            )
            .order_by(ShoppingListItem.created_at.asc())
        )
        return list(result.scalars().all())


async def _get_all_items(list_id: uuid.UUID) -> list[ShoppingListItem]:
    """Get all items for a list."""
    async with async_session() as session:
        result = await session.execute(
            select(ShoppingListItem)
            .where(ShoppingListItem.list_id == list_id)
            .order_by(ShoppingListItem.is_checked.asc(), ShoppingListItem.created_at.asc())
        )
        return list(result.scalars().all())


_STRINGS = {
    "en": {
        "add_ask": "What do you want to add to your list?",
        "add_already": "Already on your list: {items}.",
        "add_one": "Added <b>{item}</b> to your {list_name} list.",
        "add_many": "Added {count} items to your {list_name} list.",
        "add_already_short": "Already on list: {items}.",
        "add_total": "{total} items total.",
        "view_no_lists": "No lists yet. Text me items to start one.",
        "view_empty": "Your {name} list is empty. Text me items to add.",
        "view_header": "\U0001f6d2 <b>{name} list</b> ({count} items):",
        "view_checked": "\n<i>Checked off: {count}</i>",
        "remove_no_lists": "No lists found.",
        "remove_empty": "Your {name} list is already empty.",
        "remove_all_done": "All done \u2014 checked off {count} items from your {name} list.",
        "remove_ask": "Which item did you get?",
        "remove_done": "\u2705 Checked off: {items}.",
        "remove_remaining": " {count} remaining.",
        "remove_not_found": "Didn't find: {items}.",
        "clear_no_lists": "No lists to clear.",
        "clear_empty": "Your {name} list is already empty.",
        "clear_done": "\U0001f5d1 Cleared your {name} list ({count} items removed).",
    },
    "ru": {
        "add_ask": "Что добавить в список?",
        "add_already": "Уже в списке: {items}.",
        "add_one": "Добавлено: <b>{item}</b> в список \u00ab{list_name}\u00bb.",
        "add_many": "Добавлено {count} позиций в список \u00ab{list_name}\u00bb.",
        "add_already_short": "Уже в списке: {items}.",
        "add_total": "Всего: {total}.",
        "view_no_lists": "Списков пока нет. Напиши, что добавить.",
        "view_empty": "Список \u00ab{name}\u00bb пуст. Напиши, что добавить.",
        "view_header": "\U0001f6d2 <b>Список \u00ab{name}\u00bb</b> ({count}):",
        "view_checked": "\n<i>Куплено: {count}</i>",
        "remove_no_lists": "Списков нет.",
        "remove_empty": "Список \u00ab{name}\u00bb уже пуст.",
        "remove_all_done": (
            "Всё куплено \u2014 отмечено {count} позиций в списке \u00ab{name}\u00bb."
        ),
        "remove_ask": "Что уже купил?",
        "remove_done": "\u2705 Куплено: {items}.",
        "remove_remaining": " Осталось: {count}.",
        "remove_not_found": "Не нашёл: {items}.",
        "clear_no_lists": "Нечего очищать.",
        "clear_empty": "Список \u00ab{name}\u00bb уже пуст.",
        "clear_done": "\U0001f5d1 Список \u00ab{name}\u00bb очищен ({count} удалено).",
    },
}


# ─── Add Items Skill ──────────────────────────────────────────────


class ShoppingListAddSkill:
    name = "shopping_list_add"
    intents = ["shopping_list_add"]
    model = "gpt-5.2"

    @observe(name="shopping_list_add")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        items = _parse_items(intent_data, message.text or "")
        if not items:
            return SkillResult(response_text=t(_STRINGS, "add_ask", lang))

        list_name = _parse_list_name(intent_data)
        family_id = uuid.UUID(context.family_id)
        user_id = uuid.UUID(context.user_id)

        shopping_list = await _get_or_create_list(family_id, user_id, list_name)

        # Dedup: skip items already on the list (case-insensitive)
        unchecked_existing = await _get_unchecked_items(shopping_list.id)
        existing_names = {item.name.lower() for item in unchecked_existing}

        new_items = []
        skipped = []
        for item_name in items:
            if item_name.lower() in existing_names:
                skipped.append(item_name)
            else:
                new_items.append(item_name)
                existing_names.add(item_name.lower())

        if not new_items and skipped:
            return SkillResult(
                response_text=t(_STRINGS, "add_already", lang, items=", ".join(skipped))
            )

        if new_items:
            async with async_session() as session:
                for item_name in new_items:
                    item = ShoppingListItem(
                        id=uuid.uuid4(),
                        list_id=shopping_list.id,
                        family_id=family_id,
                        name=item_name,
                    )
                    session.add(item)
                await session.commit()

        total = len(unchecked_existing) + len(new_items)

        count = len(new_items)
        parts = []
        if count == 1:
            parts.append(t(_STRINGS, "add_one", lang, item=new_items[0], list_name=list_name))
        elif count > 1:
            parts.append(t(_STRINGS, "add_many", lang, count=str(count), list_name=list_name))
        if skipped:
            parts.append(t(_STRINGS, "add_already_short", lang, items=", ".join(skipped)))
        parts.append(t(_STRINGS, "add_total", lang, total=str(total)))

        return SkillResult(response_text=" ".join(parts))

    def get_system_prompt(self, context: SessionContext) -> str:
        return SHOPPING_LIST_SYSTEM_PROMPT.format(language=context.language or "en")


# ─── View List Skill ──────────────────────────────────────────────


class ShoppingListViewSkill:
    name = "shopping_list_view"
    intents = ["shopping_list_view"]
    model = "gpt-5.2"

    @observe(name="shopping_list_view")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        family_id = uuid.UUID(context.family_id)
        list_name = intent_data.get("shopping_list_name")

        if list_name:
            shopping_list = await _get_or_create_list(
                family_id, uuid.UUID(context.user_id), list_name.strip().lower()
            )
        else:
            shopping_list = await _get_most_recent_list(family_id)

        if not shopping_list:
            return SkillResult(response_text=t(_STRINGS, "view_no_lists", lang))

        all_items = await _get_all_items(shopping_list.id)
        unchecked = [i for i in all_items if not i.is_checked]
        checked = [i for i in all_items if i.is_checked]

        if not all_items:
            return SkillResult(
                response_text=t(_STRINGS, "view_empty", lang, name=shopping_list.name)
            )

        lines = [
            t(
                _STRINGS,
                "view_header",
                lang,
                name=shopping_list.name.title(),
                count=str(len(unchecked)),
            )
        ]
        for i, item in enumerate(unchecked, 1):
            qty = f" ({item.quantity})" if item.quantity else ""
            lines.append(f"{i}. {item.name}{qty}")

        if checked:
            lines.append(t(_STRINGS, "view_checked", lang, count=str(len(checked))))

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return SHOPPING_LIST_SYSTEM_PROMPT.format(language=context.language or "en")


# ─── Remove / Check Off Items Skill ──────────────────────────────


class ShoppingListRemoveSkill:
    name = "shopping_list_remove"
    intents = ["shopping_list_remove"]
    model = "gpt-5.2"

    @observe(name="shopping_list_remove")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        family_id = uuid.UUID(context.family_id)
        text = (message.text or "").lower()

        # Check for "got everything" / "bought everything" pattern
        everything_keywords = [
            "got everything",
            "bought everything",
            "all done",
            "купил все",
            "все купил",
            "взял все",
            "все взял",
        ]
        is_everything = any(kw in text for kw in everything_keywords)

        list_name = intent_data.get("shopping_list_name")
        if list_name:
            shopping_list = await _get_or_create_list(
                family_id, uuid.UUID(context.user_id), list_name.strip().lower()
            )
        else:
            shopping_list = await _get_most_recent_list(family_id)

        if not shopping_list:
            return SkillResult(response_text=t(_STRINGS, "remove_no_lists", lang))

        unchecked = await _get_unchecked_items(shopping_list.id)
        if not unchecked:
            return SkillResult(
                response_text=t(_STRINGS, "remove_empty", lang, name=shopping_list.name)
            )

        now = datetime.now(UTC)

        if is_everything:
            async with async_session() as session:
                await session.execute(
                    update(ShoppingListItem)
                    .where(
                        ShoppingListItem.list_id == shopping_list.id,
                        ShoppingListItem.is_checked.is_(False),
                    )
                    .values(is_checked=True, checked_at=now)
                )
                await session.commit()
            return SkillResult(
                response_text=t(
                    _STRINGS,
                    "remove_all_done",
                    lang,
                    count=str(len(unchecked)),
                    name=shopping_list.name,
                )
            )

        # Parse items to remove
        remove_items = intent_data.get("shopping_items") or []
        if isinstance(remove_items, str):
            remove_items = [remove_items]
        remove_single = intent_data.get("shopping_item_remove")
        if remove_single:
            remove_items.append(remove_single)

        # Also try parsing from text if no items found
        if not remove_items:
            for prefix in [
                "got the",
                "got",
                "bought",
                "picked up",
                "remove",
                "delete",
                "купил",
                "взял",
                "убери",
                "удали",
            ]:
                if text.startswith(prefix):
                    text = text[len(prefix) :]
                    break
            for sep in [",", " and ", " и "]:
                text = text.replace(sep, ",")
            remove_items = [i.strip() for i in text.split(",") if i.strip()]

        if not remove_items:
            return SkillResult(response_text=t(_STRINGS, "remove_ask", lang))

        # Match items by substring
        checked_names = []
        not_found = []
        for remove_name in remove_items:
            matched = False
            for item in unchecked:
                if (
                    remove_name.lower() in item.name.lower()
                    or item.name.lower() in remove_name.lower()
                ):
                    async with async_session() as session:
                        await session.execute(
                            update(ShoppingListItem)
                            .where(ShoppingListItem.id == item.id)
                            .values(is_checked=True, checked_at=now)
                        )
                        await session.commit()
                    checked_names.append(item.name)
                    matched = True
                    break
            if not matched:
                not_found.append(remove_name)

        remaining = len(unchecked) - len(checked_names)
        parts = []
        if checked_names:
            parts.append(t(_STRINGS, "remove_done", lang, items=", ".join(checked_names)))
            parts.append(t(_STRINGS, "remove_remaining", lang, count=str(remaining)))
        if not_found:
            parts.append(t(_STRINGS, "remove_not_found", lang, items=", ".join(not_found)))

        return SkillResult(response_text=" ".join(parts))

    def get_system_prompt(self, context: SessionContext) -> str:
        return SHOPPING_LIST_SYSTEM_PROMPT.format(language=context.language or "en")


# ─── Clear List Skill ─────────────────────────────────────────────


class ShoppingListClearSkill:
    name = "shopping_list_clear"
    intents = ["shopping_list_clear"]
    model = "gpt-5.2"

    @observe(name="shopping_list_clear")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        family_id = uuid.UUID(context.family_id)

        list_name = intent_data.get("shopping_list_name")
        if list_name:
            shopping_list = await _get_or_create_list(
                family_id, uuid.UUID(context.user_id), list_name.strip().lower()
            )
        else:
            shopping_list = await _get_most_recent_list(family_id)

        if not shopping_list:
            return SkillResult(response_text=t(_STRINGS, "clear_no_lists", lang))

        all_items = await _get_all_items(shopping_list.id)
        if not all_items:
            return SkillResult(
                response_text=t(_STRINGS, "clear_empty", lang, name=shopping_list.name)
            )

        count = len(all_items)
        async with async_session() as session:
            from sqlalchemy import delete

            await session.execute(
                delete(ShoppingListItem).where(ShoppingListItem.list_id == shopping_list.id)
            )
            await session.commit()

        return SkillResult(
            response_text=t(_STRINGS, "clear_done", lang, name=shopping_list.name, count=str(count))
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SHOPPING_LIST_SYSTEM_PROMPT.format(language=context.language or "en")


# ─── Module-level skill instances ─────────────────────────────────

shopping_list_add_skill = ShoppingListAddSkill()
shopping_list_view_skill = ShoppingListViewSkill()
shopping_list_remove_skill = ShoppingListRemoveSkill()
shopping_list_clear_skill = ShoppingListClearSkill()
