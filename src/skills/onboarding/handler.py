"""Multi-step FSM onboarding skill.

Owner flow:
  /start -> welcome with buttons -> "onboard:new" -> describe activity ->
  AI determines business_type -> create_family -> done.

Family member flow:
  /start -> welcome with buttons -> "onboard:join" -> enter invite_code ->
  join_family -> done.
"""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.family import create_family, join_family
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.models.enums import ConversationState
from src.core.observability import observe
from src.core.profiles import ProfileLoader
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

profile_loader = ProfileLoader("config/profiles")

ONBOARDING_SYSTEM_PROMPT = """Ты помогаешь новому пользователю настроить финансового бота.
Твоя задача — определить тип деятельности пользователя по его описанию.

Типы: household (домохозяйство), trucker (дальнобойщик), taxi (такси),
delivery (доставка), flowers (цветы), manicure (маникюр), construction (строительство).

Если не можешь определить — выбери household.

Ответь ОДНИМ СЛОВОМ — тип деятельности на английском."""

# ---- helpers ---------------------------------------------------------------


def _extract_owner_name(message: IncomingMessage) -> str:
    """Try to get the user's first name from the Telegram message object."""
    if message.raw and hasattr(message.raw, "from_user"):
        from_user = message.raw.from_user
        if from_user and hasattr(from_user, "first_name") and from_user.first_name:
            return from_user.first_name
    return "User"


def _welcome_result() -> SkillResult:
    """Step 1 response: welcome message with two inline buttons."""
    return SkillResult(
        response_text=(
            "Привет! Я твой финансовый помощник.\n\n"
            "Я помогу с учётом расходов и доходов, "
            "сканированием чеков и аналитикой.\n\n"
            "Выберите вариант:"
        ),
        buttons=[
            {"text": "Новый аккаунт", "callback": "onboard:new"},
            {"text": "Присоединиться к семье", "callback": "onboard:join"},
        ],
    )


def _ask_activity_result() -> SkillResult:
    """Prompt the user to describe their activity (owner path)."""
    return SkillResult(
        response_text=(
            "Расскажите о своей деятельности — чем занимаетесь?\n\n"
            "Например: «я таксист», «у меня трак», "
            "«просто хочу следить за расходами»"
        ),
    )


def _ask_invite_code_result() -> SkillResult:
    """Prompt the user to enter an invite code (family member path)."""
    return SkillResult(
        response_text="Введите код приглашения, который вам прислал владелец аккаунта:",
    )


def _format_categories_text(profile) -> str:
    """Format category names from a profile for display."""
    if not profile or not profile.categories:
        return ""
    # categories can be a dict with "business" key or a flat list
    cats = profile.categories
    if isinstance(cats, dict):
        all_cats = []
        for group in cats.values():
            if isinstance(group, list):
                all_cats.extend(group)
        names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in all_cats]
    elif isinstance(cats, list):
        names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in cats]
    else:
        names = []
    names = [n for n in names if n]
    if not names:
        return ""
    display = ", ".join(names[:5])
    if len(names) > 5:
        display += f" и ещё {len(names) - 5}"
    return display


# ---- main skill ------------------------------------------------------------


class OnboardingSkill:
    name = "onboarding"
    intents = ["onboarding"]
    model = "claude-sonnet-4-5-20250929"

    def __init__(self):
        self._profile_loader = ProfileLoader("config/profiles")

    def _find_profile_key(self, profile) -> str | None:
        """Find the dict key (stem name) for a matched ProfileConfig."""
        for key, p in self._profile_loader._profiles.items():
            if p is profile:
                return key
        return None

    @observe(name="onboarding")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Multi-step onboarding wizard driven by conversation state."""
        text = (message.text or "").strip()

        # Determine current onboarding sub-state from intent_data
        # (set by api/main.py or router callback handler)
        onboarding_state = intent_data.get("onboarding_state", "")

        # ---- Step 1: /start or first contact ----
        if text == "/start" or (not context.family_id and not onboarding_state):
            return _welcome_result()

        # ---- Step 2a: user chose "New account", now waiting for activity ----
        if onboarding_state == ConversationState.onboarding_awaiting_activity.value:
            return await self._handle_activity_description(message, context, text)

        # ---- Step 2b: user chose "Join family", now waiting for invite code ----
        if onboarding_state == ConversationState.onboarding_awaiting_invite_code.value:
            return await self._handle_invite_code(message, context, text)

        # ---- Fallback: user is in generic "onboarding" state ----
        # If they sent /start again or something unexpected, show welcome
        if onboarding_state == ConversationState.onboarding_awaiting_choice.value:
            return _welcome_result()

        # Default: try to match profile from text (legacy / direct text flow)
        profile = self._profile_loader.match(text)
        if profile:
            profile_key = self._find_profile_key(profile) or "household"
            return await self._create_owner_account(
                message,
                context,
                profile_key,
            )

        # Nothing matched — show welcome again
        return _welcome_result()

    async def _handle_activity_description(
        self,
        message: IncomingMessage,
        context: SessionContext,
        text: str,
    ) -> SkillResult:
        """User described their activity. Use LLM to determine business_type."""
        # First try simple alias matching (no LLM needed)
        profile = self._profile_loader.match(text)
        if profile:
            profile_key = self._find_profile_key(profile) or "household"
            return await self._create_owner_account(message, context, profile_key)

        # Use LLM to determine business type
        try:
            client = anthropic_client()
            prompt_data = PromptAdapter.for_claude(
                system=ONBOARDING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
            )
            response = await client.messages.create(
                model=self.model,
                max_tokens=50,
                **prompt_data,
            )
            business_type = response.content[0].text.strip().lower()
        except Exception as e:
            logger.error("LLM call failed during onboarding: %s", e)
            business_type = "household"

        # Validate against known profiles
        if not self._profile_loader.get(business_type):
            business_type = "household"

        return await self._create_owner_account(message, context, business_type)

    async def _create_owner_account(
        self,
        message: IncomingMessage,
        context: SessionContext,
        business_type: str,
    ) -> SkillResult:
        """Create family, user, and categories for the owner."""
        telegram_id = int(message.user_id)
        owner_name = _extract_owner_name(message)

        profile = self._profile_loader.get(business_type) or self._profile_loader.get("household")
        if not profile:
            business_type = "household"

        try:
            async with async_session() as session:
                family, user = await create_family(
                    session=session,
                    owner_telegram_id=telegram_id,
                    owner_name=owner_name,
                    business_type=business_type if business_type != "household" else None,
                    language=context.language,
                    currency=context.currency,
                )
            invite_code = family.invite_code

            categories_text = _format_categories_text(profile)
            cat_line = f"\nКатегории: {categories_text}\n" if categories_text else "\n"

            return SkillResult(
                response_text=(
                    f"Отлично! Я настроил категории для профиля «{profile.name}».\n"
                    f"{cat_line}\n"
                    f"Код приглашения для семьи: <b>{invite_code}</b>\n"
                    f"(отправьте его близким для общего учёта)\n\n"
                    f"Теперь можете записывать расходы — просто напишите, "
                    f"например: «кофе 150» или отправьте фото чека."
                ),
            )
        except Exception as e:
            logger.exception(
                "Onboarding create_family failed for telegram_id=%s: %s",
                message.user_id,
                e,
            )
            return SkillResult(
                response_text="Произошла ошибка при настройке профиля. Попробуйте ещё раз /start.",
            )

    async def _handle_invite_code(
        self,
        message: IncomingMessage,
        context: SessionContext,
        text: str,
    ) -> SkillResult:
        """User entered an invite code. Try to join the family."""
        invite_code = text.strip().upper()

        if not invite_code or len(invite_code) < 4:
            return SkillResult(
                response_text="Код приглашения слишком короткий. Попробуйте ещё раз:",
            )

        telegram_id = int(message.user_id)
        member_name = _extract_owner_name(message)

        try:
            async with async_session() as session:
                result = await join_family(
                    session=session,
                    invite_code=invite_code,
                    telegram_id=telegram_id,
                    name=member_name,
                    language=context.language,
                )
            if result:
                family, user = result
                return SkillResult(
                    response_text=(
                        f"Вы присоединились к семье «{family.name}»!\n\n"
                        f"Теперь можете записывать расходы — просто напишите, "
                        f"например: «кофе 150» или отправьте фото чека."
                    ),
                )
            else:
                return SkillResult(
                    response_text=(
                        "Неверный код приглашения или вы уже зарегистрированы.\n"
                        "Проверьте код и попробуйте ещё раз:"
                    ),
                )
        except Exception as e:
            logger.exception("join_family failed for telegram_id=%s: %s", message.user_id, e)
            return SkillResult(
                response_text="Произошла ошибка при присоединении. Попробуйте ещё раз /start.",
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return ONBOARDING_SYSTEM_PROMPT


skill = OnboardingSkill()
