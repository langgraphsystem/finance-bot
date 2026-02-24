"""Multi-step FSM onboarding skill.

Owner flow:
  /start -> language picker -> welcome with buttons -> "onboard:new" ->
  describe activity -> AI determines business_type -> create_family -> done.

Family member flow:
  /start -> language picker -> welcome with buttons -> "onboard:join" ->
  enter invite_code -> join_family -> done.
"""

import json
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session, redis
from src.core.family import (
    create_family,
    create_family_for_channel,
    join_family,
    join_family_for_channel,
)
from src.core.llm.clients import generate_text
from src.core.models.enums import ConversationState
from src.core.observability import observe
from src.core.profiles import ProfileLoader
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

profile_loader = ProfileLoader("config/profiles")

ONBOARDING_SYSTEM_PROMPT = (
    "You help a new user set up their AI Assistant. "
    "Determine the user's business type from their description.\n\n"
    "Types: household, trucker, taxi, delivery, flowers, manicure, construction.\n\n"
    "If you can't determine — choose household.\n\n"
    "Reply with ONE WORD — the business type in English."
)

# ---- translations ----------------------------------------------------------

SUPPORTED_LANGUAGES = ("en", "es", "zh", "ru")

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "es": "Spanish", "zh": "Chinese", "ru": "Russian",
    "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
    "tr": "Turkish", "pl": "Polish", "nl": "Dutch", "sv": "Swedish",
    "uk": "Ukrainian", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian",
    "cs": "Czech", "ro": "Romanian", "hu": "Hungarian", "el": "Greek",
    "he": "Hebrew", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "ky": "Kyrgyz", "kk": "Kazakh", "uz": "Uzbek", "tg": "Tajik",
}

ONBOARDING_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "\U0001f44b Hi! I'm your <b>personal AI Assistant</b>.\n\n"
            "Here's everything I can help with:\n\n"
            "\U0001f4b0 <b>Finance</b>\n"
            "Expenses, income, receipt scanning, budgets, "
            "analytics, PDF reports, recurring payments\n\n"
            "\U0001f4e7 <b>Email & Calendar</b>\n"
            "Inbox, send & draft emails, events, free slots, "
            "morning & evening briefs\n\n"
            "\u2705 <b>Tasks & Shopping</b>\n"
            "To-dos, reminders, shopping lists\n\n"
            "\U0001f9e0 <b>Life Tracking</b>\n"
            "Food, drinks, mood, quick notes, "
            "day plans & reflections\n\n"
            "\U0001f50d <b>Research</b>\n"
            "Questions, web search, compare options, "
            "maps, YouTube, price tracking\n\n"
            "\u270d\ufe0f <b>Writing & Media</b>\n"
            "Messages, posts, translation, proofreading, "
            "images, documents\n\n"
            "\U0001f465 <b>Clients & Bookings</b>\n"
            "Contacts, appointments, CRM, "
            "send to clients\n\n"
            "\U0001f310 <b>Browser & Monitoring</b>\n"
            "Web actions, price alerts, news monitoring\n\n"
            "Choose an option:"
        ),
        "new_account": "\U0001f195 New account",
        "join_family": "\U0001f46a Join a family",
        "ask_activity": (
            "\U0001f3af <b>What do you do?</b>\n\n"
            "This helps me set up the right categories "
            "for you.\n\n"
            "For example:\n"
            "\u2022 'I'm a freelancer'\n"
            "\u2022 'I run a small business'\n"
            "\u2022 'I'm a real estate agent'\n"
            "\u2022 'Just personal finances'"
        ),
        "ask_invite": (
            "Enter the invite code that the account owner "
            "shared with you:"
        ),
        "already_registered": (
            "You're already registered! Just tell me how I can help.\n\n"
            "Examples: 'coffee 5', 'mood 7', receipt photo, "
            "'check my email', 'my tasks', 'stats for this week'."
        ),
        "categories_label": "Categories",
        "invite_code_label": "Family invite code",
        "invite_code_hint": "(share it with family members for shared tracking)",
        "setup_done": (
            "All set! I configured categories "
            "for the '{profile}' profile."
        ),
        "start_tracking": (
            "Now you can start tracking expenses — just type, "
            "for example: 'coffee 5' or send a receipt photo."
        ),
        "share_location_prompt": (
            "Tap the button below so I can detect your city "
            "for nearby searches."
        ),
        "share_location_btn": "\U0001f4cd Share location",
        "joined_family": "You joined the family '{name}'!",
        "invite_short": "Invite code is too short. Try again:",
        "invite_invalid": (
            "Invalid invite code or you are already registered.\n"
            "Check the code and try again:"
        ),
        "error_setup": (
            "An error occurred during setup. "
            "Please try again with /start."
        ),
        "error_join": (
            "An error occurred while joining. "
            "Please try again with /start."
        ),
        "and_more": "and {n} more",
    },
    "es": {
        "welcome": (
            "\U0001f44b \u00a1Hola! Soy tu "
            "<b>asistente personal de IA</b>.\n\n"
            "Esto es todo lo que puedo hacer:\n\n"
            "\U0001f4b0 <b>Finanzas</b>\n"
            "Gastos, ingresos, escaneo de recibos, "
            "presupuestos, reportes PDF, pagos recurrentes\n\n"
            "\U0001f4e7 <b>Email y Calendario</b>\n"
            "Bandeja, enviar emails, eventos, "
            "resumen matutino y vespertino\n\n"
            "\u2705 <b>Tareas y Compras</b>\n"
            "Pendientes, recordatorios, listas de compras\n\n"
            "\U0001f9e0 <b>Vida</b>\n"
            "Comida, bebidas, \u00e1nimo, notas, "
            "plan y reflexi\u00f3n del d\u00eda\n\n"
            "\U0001f50d <b>B\u00fasqueda</b>\n"
            "Preguntas, web, comparar opciones, "
            "mapas, YouTube, seguimiento de precios\n\n"
            "\u270d\ufe0f <b>Escritura y Medios</b>\n"
            "Mensajes, publicaciones, traducci\u00f3n, "
            "revisi\u00f3n, im\u00e1genes, documentos\n\n"
            "\U0001f465 <b>Clientes y Reservas</b>\n"
            "Contactos, citas, CRM, enviar a clientes\n\n"
            "\U0001f310 <b>Navegador y Monitoreo</b>\n"
            "Acciones web, alertas de precios, noticias\n\n"
            "Elige una opci\u00f3n:"
        ),
        "new_account": "\U0001f195 Nueva cuenta",
        "join_family": "\U0001f46a Unirse a una familia",
        "ask_activity": (
            "\U0001f3af <b>\u00bfA qu\u00e9 te dedicas?</b>\n\n"
            "Esto me ayuda a configurar las categor\u00edas "
            "correctas para ti.\n\n"
            "Por ejemplo:\n"
            "\u2022 'Soy freelancer'\n"
            "\u2022 'Tengo un peque\u00f1o negocio'\n"
            "\u2022 'Soy agente de bienes ra\u00edces'\n"
            "\u2022 'Solo finanzas personales'"
        ),
        "ask_invite": (
            "Ingresa el c\u00f3digo de invitaci\u00f3n que te "
            "comparti\u00f3 el due\u00f1o de la cuenta:"
        ),
        "already_registered": (
            "\u00a1Ya est\u00e1s registrado! Dime en qu\u00e9 puedo ayudarte.\n\n"
            "Ejemplos: 'caf\u00e9 5', '\u00e1nimo 7', foto de recibo, "
            "'revisar mi email', 'mis tareas'."
        ),
        "categories_label": "Categor\u00edas",
        "invite_code_label": "C\u00f3digo de invitaci\u00f3n familiar",
        "invite_code_hint": (
            "(comp\u00e1rtelo con familiares para "
            "seguimiento compartido)"
        ),
        "setup_done": (
            "\u00a1Listo! Configur\u00e9 las categor\u00edas "
            "para el perfil '{profile}'."
        ),
        "start_tracking": (
            "Ahora puedes registrar gastos \u2014 escribe, "
            "por ejemplo: 'caf\u00e9 5' o env\u00eda un recibo."
        ),
        "share_location_prompt": (
            "Toca el bot\u00f3n de abajo para detectar tu ciudad "
            "y buscar lugares cercanos."
        ),
        "share_location_btn": "\U0001f4cd Compartir ubicaci\u00f3n",
        "joined_family": "\u00a1Te uniste a la familia '{name}'!",
        "invite_short": (
            "El c\u00f3digo es muy corto. Int\u00e9ntalo de nuevo:"
        ),
        "invite_invalid": (
            "C\u00f3digo inv\u00e1lido o ya est\u00e1s registrado.\n"
            "Verifica el c\u00f3digo e int\u00e9ntalo de nuevo:"
        ),
        "error_setup": (
            "Ocurri\u00f3 un error durante la configuraci\u00f3n. "
            "Int\u00e9ntalo de nuevo con /start."
        ),
        "error_join": (
            "Ocurri\u00f3 un error al unirse. "
            "Int\u00e9ntalo de nuevo con /start."
        ),
        "and_more": "y {n} m\u00e1s",
    },
    "zh": {
        "welcome": (
            "\U0001f44b 你好！我是你的<b>个人 AI 助手</b>。\n\n"
            "我可以帮你：\n\n"
            "\U0001f4b0 <b>财务</b>\n"
            "支出、收入、扫描收据、预算、"
            "报表、定期付款\n\n"
            "\U0001f4e7 <b>邮件和日历</b>\n"
            "收件箱、发送邮件、日程、"
            "早晚简报\n\n"
            "\u2705 <b>任务和购物</b>\n"
            "待办事项、提醒、购物清单\n\n"
            "\U0001f9e0 <b>生活记录</b>\n"
            "饮食、心情、快速笔记、"
            "日计划和反思\n\n"
            "\U0001f50d <b>搜索</b>\n"
            "提问、网络搜索、比较选项、"
            "地图、YouTube、价格跟踪\n\n"
            "\u270d\ufe0f <b>写作和媒体</b>\n"
            "消息、帖子、翻译、校对、"
            "图片、文档\n\n"
            "\U0001f465 <b>客户和预约</b>\n"
            "联系人、预约管理、CRM\n\n"
            "\U0001f310 <b>浏览器和监控</b>\n"
            "网页操作、价格提醒、新闻监控\n\n"
            "请选择："
        ),
        "new_account": "\U0001f195 新建账户",
        "join_family": "\U0001f46a 加入家庭",
        "ask_activity": (
            "\U0001f3af <b>你做什么工作？</b>\n\n"
            "这能帮我为你设置合适的分类。\n\n"
            "例如：\n"
            "\u2022 '我是自由职业者'\n"
            "\u2022 '我经营小店'\n"
            "\u2022 '我做房地产'\n"
            "\u2022 '只是个人记账'"
        ),
        "ask_invite": "请输入账户所有者分享给你的邀请码：",
        "already_registered": (
            "你已经注册了！直接告诉我需要什么帮助。\n\n"
            "示例：'咖啡 5'、'心情 7'、收据照片、"
            "'查看邮件'、'我的任务'、'本周统计'。"
        ),
        "categories_label": "分类",
        "invite_code_label": "家庭邀请码",
        "invite_code_hint": "（分享给家人以便共同记账）",
        "setup_done": "设置完成！已为'{profile}'配置分类。",
        "start_tracking": (
            "现在你可以开始记录支出 — 直接输入，"
            "例如：'咖啡 5' 或发送收据照片。"
        ),
        "share_location_prompt": (
            "点击下方按钮，"
            "我可以检测你的城市以便搜索附近地点。"
        ),
        "share_location_btn": "\U0001f4cd 分享位置",
        "joined_family": "你已加入家庭'{name}'！",
        "invite_short": "邀请码太短。请再试一次：",
        "invite_invalid": "邀请码无效或你已经注册。\n请检查并重试：",
        "error_setup": "设置时发生错误。请用 /start 重试。",
        "error_join": "加入时发生错误。请用 /start 重试。",
        "and_more": "及其他 {n} 个",
    },
    "ru": {
        "welcome": (
            "\U0001f44b Привет! Я ваш "
            "<b>персональный AI Assistant</b>.\n\n"
            "Вот что я умею:\n\n"
            "\U0001f4b0 <b>Финансы</b>\n"
            "Расходы, доходы, сканирование чеков, "
            "бюджеты, аналитика, PDF-отчёты, "
            "регулярные платежи\n\n"
            "\U0001f4e7 <b>Почта и Календарь</b>\n"
            "Входящие, отправка email, события, "
            "утренний и вечерний брифинг\n\n"
            "\u2705 <b>Задачи и Покупки</b>\n"
            "Дела, напоминания, списки покупок\n\n"
            "\U0001f9e0 <b>Жизнь</b>\n"
            "Еда, напитки, настроение, заметки, "
            "план дня и рефлексия\n\n"
            "\U0001f50d <b>Поиск</b>\n"
            "Вопросы, веб-поиск, сравнение, "
            "карты, YouTube, отслеживание цен\n\n"
            "\u270d\ufe0f <b>Тексты и Медиа</b>\n"
            "Письма, посты, перевод, грамматика, "
            "картинки, документы\n\n"
            "\U0001f465 <b>Клиенты и Записи</b>\n"
            "Контакты, бронирования, CRM, "
            "отправка клиентам\n\n"
            "\U0001f310 <b>Браузер и Мониторинг</b>\n"
            "Действия в браузере, алерты цен, новости\n\n"
            "Выберите вариант:"
        ),
        "new_account": "\U0001f195 Новый аккаунт",
        "join_family": "\U0001f46a Присоединиться к семье",
        "ask_activity": (
            "\U0001f3af <b>Чем вы занимаетесь?</b>\n\n"
            "Это поможет настроить категории "
            "под вас.\n\n"
            "Например:\n"
            "\u2022 «Я фрилансер»\n"
            "\u2022 «У меня свой бизнес»\n"
            "\u2022 «Я риэлтор»\n"
            "\u2022 «Просто личные финансы»"
        ),
        "ask_invite": (
            "Введите код приглашения, который вам "
            "прислал владелец аккаунта:"
        ),
        "already_registered": (
            "Вы уже зарегистрированы! Просто напишите, "
            "чем могу помочь.\n\n"
            "Примеры: «кофе 150», «настроение 7», фото чека, "
            "«проверь почту», «мои задачи»."
        ),
        "categories_label": "Категории",
        "invite_code_label": "Код приглашения для семьи",
        "invite_code_hint": "(отправьте его близким для общего учёта)",
        "setup_done": (
            "Отлично! Я настроил категории "
            "для профиля «{profile}»."
        ),
        "start_tracking": (
            "Теперь можете записывать расходы — просто напишите, "
            "например: «кофе 150» или отправьте фото чека."
        ),
        "share_location_prompt": (
            "Нажмите кнопку ниже, чтобы я определил ваш город "
            "для поиска мест рядом."
        ),
        "share_location_btn": "\U0001f4cd Поделиться геолокацией",
        "joined_family": "Вы присоединились к семье «{name}»!",
        "invite_short": (
            "Код приглашения слишком короткий. "
            "Попробуйте ещё раз:"
        ),
        "invite_invalid": (
            "Неверный код приглашения или вы уже зарегистрированы.\n"
            "Проверьте код и попробуйте ещё раз:"
        ),
        "error_setup": (
            "Произошла ошибка при настройке профиля. "
            "Попробуйте ещё раз /start."
        ),
        "error_join": (
            "Произошла ошибка при присоединении. "
            "Попробуйте ещё раз /start."
        ),
        "and_more": "и ещё {n}",
    },
}

# ---- helpers ---------------------------------------------------------------


def _get_texts(language: str) -> dict[str, str]:
    """Get onboarding texts for a language, defaulting to English."""
    return ONBOARDING_TEXTS.get(language, ONBOARDING_TEXTS["en"])


async def detect_language(text: str) -> tuple[str, str]:
    """Detect language from user input. Returns (iso_code, language_name)."""
    try:
        raw = await generate_text(
            "claude-haiku-4-5",
            (
                "Detect the language of the text. "
                "Return ONLY JSON: "
                '{"code": "xx", "name": "Language Name"}\n'
                "Use ISO 639-1 two-letter codes. "
                'If unsure, return {"code": "en", "name": "English"}'
            ),
            [{"role": "user", "content": text}],
            max_tokens=50,
        )
        data = json.loads(raw.strip())
        code = data.get("code", "en")[:5]
        name = data.get("name", LANGUAGE_NAMES.get(code, "English"))
        return code, name
    except Exception as e:
        logger.warning("Language detection failed: %s", e)
        return "en", "English"


async def translate_onboarding_texts(
    lang_code: str,
    lang_name: str,
) -> dict[str, str]:
    """Translate all onboarding texts to a target language via LLM."""
    source = ONBOARDING_TEXTS["en"]
    texts_json = json.dumps(source, ensure_ascii=False)
    prompt = (
        f"Translate ALL values in this JSON to {lang_name} "
        f"({lang_code}).\nRules:\n"
        "- Keep HTML tags (<b>, <i>, <code>) exactly as they are\n"
        "- Keep emoji characters exactly as they are\n"
        "- Keep {profile}, {name}, {n} placeholders as they are\n"
        "- Return ONLY valid JSON with the same keys\n\n"
        f"{texts_json}"
    )
    try:
        raw = await generate_text(
            "claude-haiku-4-5",
            "You are a professional translator. Return only valid JSON.",
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        translated = json.loads(text.strip())
        return {**source, **translated}
    except Exception as e:
        logger.warning("Translation to %s failed: %s", lang_name, e)
        return source


async def get_onboarding_texts(lang_code: str) -> dict[str, str]:
    """Get onboarding texts for any language. Translates + caches if needed."""
    if lang_code in ONBOARDING_TEXTS:
        return ONBOARDING_TEXTS[lang_code]
    cache_key = f"onboarding_texts:{lang_code}"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
    texts = await translate_onboarding_texts(lang_code, lang_name)
    try:
        await redis.set(
            cache_key,
            json.dumps(texts, ensure_ascii=False),
            ex=86400,
        )
    except Exception:
        pass
    return texts


def _extract_owner_name(message: IncomingMessage) -> str:
    """Try to get the user's first name from the message object.

    Works for Telegram (from_user.first_name), Slack (raw event profile),
    and falls back to 'User' for other channels.
    """
    # Telegram: aiogram Message
    if message.raw and hasattr(message.raw, "from_user"):
        from_user = message.raw.from_user
        if from_user and hasattr(from_user, "first_name") and from_user.first_name:
            return from_user.first_name
    # Slack: event payload with user profile
    if isinstance(message.raw, dict):
        profile = message.raw.get("user_profile", {})
        if profile.get("display_name"):
            return profile["display_name"]
        if profile.get("real_name"):
            return profile["real_name"]
    return "User"


def _language_picker_result() -> SkillResult:
    """Step 0: multilingual greeting with language selection buttons."""
    return SkillResult(
        response_text=(
            "Welcome! / \u00a1Bienvenido! / "
            "\u6b22\u8fce\uff01 / "
            "\u0414\u043e\u0431\u0440\u043e "
            "\u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c!\n\n"
            "Please choose your language:\n"
            "Por favor, elige tu idioma:\n"
            "\u8bf7\u9009\u62e9\u4f60\u7684\u8bed\u8a00\uff1a\n"
            "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 "
            "\u044f\u0437\u044b\u043a:\n\n"
            "<i>\u2328\ufe0f Or just type in your language</i>"
        ),
        buttons=[
            {
                "text": "\ud83c\uddfa\ud83c\uddf8 English",
                "callback": "onboard:lang:en",
            },
            {
                "text": "\ud83c\uddea\ud83c\uddf8 Espa\u00f1ol",
                "callback": "onboard:lang:es",
            },
            {
                "text": "\ud83c\udde8\ud83c\uddf3 \u4e2d\u6587",
                "callback": "onboard:lang:zh",
            },
            {
                "text": "\ud83c\uddf7\ud83c\uddfa "
                "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
                "callback": "onboard:lang:ru",
            },
        ],
    )


def _welcome_result(
    language: str = "en", *, texts: dict | None = None,
) -> SkillResult:
    """Welcome message with new account / join family buttons."""
    t = texts or _get_texts(language)
    return SkillResult(
        response_text=t["welcome"],
        buttons=[
            {"text": t["new_account"], "callback": "onboard:new"},
            {"text": t["join_family"], "callback": "onboard:join"},
        ],
    )


def _ask_activity_result(
    language: str = "en", *, texts: dict | None = None,
) -> SkillResult:
    """Prompt the user to describe their activity (owner path)."""
    t = texts or _get_texts(language)
    return SkillResult(response_text=t["ask_activity"])


def _ask_invite_code_result(
    language: str = "en", *, texts: dict | None = None,
) -> SkillResult:
    """Prompt the user to enter an invite code (family member path)."""
    t = texts or _get_texts(language)
    return SkillResult(response_text=t["ask_invite"])


def _format_categories_text(
    profile, language: str = "en", *, texts: dict | None = None,
) -> str:
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
        t = texts or _get_texts(language)
        display += " " + t["and_more"].format(n=len(names) - 5)
    return display


# ---- main skill ------------------------------------------------------------


class OnboardingSkill:
    name = "onboarding"
    intents = ["onboarding"]
    model = "claude-sonnet-4-6"

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
        channel = intent_data.get("channel", message.channel or "telegram")
        channel_user_id = intent_data.get("channel_user_id")

        lang = context.language or "en"
        t = _get_texts(lang)

        # If user is already registered, don't re-onboard
        if context.family_id and text != "/start":
            return SkillResult(response_text=t["already_registered"])

        # Determine current onboarding sub-state from intent_data
        # (set by api/main.py or router callback handler)
        onboarding_state = intent_data.get("onboarding_state", "")

        # ---- Step 0: /start or first contact → language picker ----
        if text == "/start" or (not context.family_id and not onboarding_state):
            return _language_picker_result()

        # ---- Step 0.5: user typed their language (text, not button) ----
        if (
            onboarding_state
            == ConversationState.onboarding_awaiting_language.value
        ):
            lang_code, _lang_name = await detect_language(text)
            try:
                await redis.set(
                    f"onboarding_lang:{message.user_id}",
                    lang_code,
                    ex=3600,
                )
                await redis.set(
                    f"onboarding_state:{message.user_id}",
                    ConversationState.onboarding_awaiting_choice.value,
                    ex=3600,
                )
            except Exception as e:
                logger.warning("Redis set failed: %s", e)
            t = await get_onboarding_texts(lang_code)
            return SkillResult(
                response_text=t["welcome"],
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

        # ---- Step 1: user chose language, show welcome ----
        if onboarding_state == ConversationState.onboarding_awaiting_choice.value:
            t = await get_onboarding_texts(lang)
            return _welcome_result(texts=t)

        # ---- Step 2a: user chose "New account", now waiting for activity ----
        if onboarding_state == ConversationState.onboarding_awaiting_activity.value:
            return await self._handle_activity_description(
                message, context, text, channel=channel, channel_user_id=channel_user_id
            )

        # ---- Step 2b: user chose "Join family", now waiting for invite code ----
        if onboarding_state == ConversationState.onboarding_awaiting_invite_code.value:
            return await self._handle_invite_code(
                message, context, text, channel=channel, channel_user_id=channel_user_id
            )

        # Default: try to match profile from text (legacy / direct text flow)
        profile = self._profile_loader.match(text)
        if profile:
            profile_key = self._find_profile_key(profile) or "household"
            return await self._create_owner_account(
                message,
                context,
                profile_key,
                channel=channel,
                channel_user_id=channel_user_id,
            )

        # Nothing matched — show language picker again
        return _language_picker_result()

    async def _handle_activity_description(
        self,
        message: IncomingMessage,
        context: SessionContext,
        text: str,
        channel: str = "telegram",
        channel_user_id: str | None = None,
    ) -> SkillResult:
        """User described their activity. Use LLM to determine business_type."""
        # First try simple alias matching (no LLM needed)
        profile = self._profile_loader.match(text)
        if profile:
            profile_key = self._find_profile_key(profile) or "household"
            return await self._create_owner_account(
                message,
                context,
                profile_key,
                channel=channel,
                channel_user_id=channel_user_id,
            )

        # Use LLM to determine business type
        try:
            raw = await generate_text(
                self.model,
                ONBOARDING_SYSTEM_PROMPT,
                [{"role": "user", "content": text}],
                max_tokens=50,
            )
            business_type = raw.strip().lower()
        except Exception as e:
            logger.error("LLM call failed during onboarding: %s", e)
            business_type = "household"

        # Validate against known profiles
        if not self._profile_loader.get(business_type):
            business_type = "household"

        return await self._create_owner_account(
            message,
            context,
            business_type,
            channel=channel,
            channel_user_id=channel_user_id,
        )

    async def _create_owner_account(
        self,
        message: IncomingMessage,
        context: SessionContext,
        business_type: str,
        channel: str = "telegram",
        channel_user_id: str | None = None,
    ) -> SkillResult:
        """Create family, user, and categories for the owner."""
        owner_name = _extract_owner_name(message)

        profile = self._profile_loader.get(business_type) or self._profile_loader.get("household")
        if not profile:
            business_type = "household"

        lang = context.language or "en"
        t = await get_onboarding_texts(lang)

        try:
            async with async_session() as session:
                if channel != "telegram":
                    family, user = await create_family_for_channel(
                        session=session,
                        channel=channel,
                        channel_user_id=channel_user_id or message.user_id,
                        owner_name=owner_name,
                        business_type=business_type if business_type != "household" else None,
                        language=context.language,
                        currency=context.currency,
                    )
                else:
                    family, user = await create_family(
                        session=session,
                        owner_telegram_id=int(message.user_id),
                        owner_name=owner_name,
                        business_type=business_type if business_type != "household" else None,
                        language=context.language,
                        currency=context.currency,
                    )
            invite_code = family.invite_code
            categories_text = _format_categories_text(profile, texts=t)
            cat_line = (
                f"\n{t['categories_label']}: {categories_text}\n" if categories_text else "\n"
            )

            return SkillResult(
                response_text=(
                    f"{t['setup_done'].format(profile=profile.name)}\n"
                    f"{cat_line}\n"
                    f"{t['invite_code_label']}: <b>{invite_code}</b>\n"
                    f"{t['invite_code_hint']}\n\n"
                    f"{t['start_tracking']}\n\n"
                    f"{t['share_location_prompt']}"
                ),
                reply_keyboard=[
                    {"text": t["share_location_btn"], "request_location": True},
                ],
            )
        except Exception as e:
            logger.exception(
                "Onboarding create_family failed for user_id=%s: %s",
                message.user_id,
                e,
            )
            return SkillResult(response_text=t["error_setup"])

    async def _handle_invite_code(
        self,
        message: IncomingMessage,
        context: SessionContext,
        text: str,
        channel: str = "telegram",
        channel_user_id: str | None = None,
    ) -> SkillResult:
        """User entered an invite code. Try to join the family."""
        lang = context.language or "en"
        t = await get_onboarding_texts(lang)
        invite_code = text.strip().upper()

        if not invite_code or len(invite_code) < 4:
            return SkillResult(response_text=t["invite_short"])

        member_name = _extract_owner_name(message)

        try:
            async with async_session() as session:
                if channel != "telegram":
                    result = await join_family_for_channel(
                        session=session,
                        invite_code=invite_code,
                        channel=channel,
                        channel_user_id=channel_user_id or message.user_id,
                        name=member_name,
                        language=context.language,
                    )
                else:
                    result = await join_family(
                        session=session,
                        invite_code=invite_code,
                        telegram_id=int(message.user_id),
                        name=member_name,
                        language=context.language,
                    )
            if result:
                family, user = result
                return SkillResult(
                    response_text=(
                        f"{t['joined_family'].format(name=family.name)}\n\n"
                        f"{t['start_tracking']}\n\n"
                        f"{t['share_location_prompt']}"
                    ),
                    reply_keyboard=[
                        {"text": t["share_location_btn"], "request_location": True},
                    ],
                )
            else:
                return SkillResult(response_text=t["invite_invalid"])
        except Exception as e:
            logger.exception("join_family failed for user_id=%s: %s", message.user_id, e)
            return SkillResult(response_text=t["error_join"])

    def get_system_prompt(self, context: SessionContext) -> str:
        return ONBOARDING_SYSTEM_PROMPT


skill = OnboardingSkill()
