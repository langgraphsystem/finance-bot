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
    get_invite_code,
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

# Profile display names per language (YAML names are Russian-only)
PROFILE_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    "household": {
        "en": "Personal",
        "es": "Personal",
        "zh": "个人",
        "ru": "Личный",
    },
    "trucker": {
        "en": "Trucking",
        "es": "Transporte",
        "zh": "卡车运输",
        "ru": "Грузоперевозки",
    },
    "taxi": {
        "en": "Taxi",
        "es": "Taxi",
        "zh": "出租车",
        "ru": "Такси",
    },
    "delivery": {
        "en": "Delivery",
        "es": "Entregas",
        "zh": "配送",
        "ru": "Доставка",
    },
    "flowers": {
        "en": "Flower Shop",
        "es": "Floreria",
        "zh": "花店",
        "ru": "Цветочный бизнес",
    },
    "manicure": {
        "en": "Beauty Salon",
        "es": "Salon de belleza",
        "zh": "美甲沙龙",
        "ru": "Салон красоты",
    },
    "construction": {
        "en": "Construction",
        "es": "Construccion",
        "zh": "建筑",
        "ru": "Строительство",
    },
}

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
            "\U0001f3af <b>Tell me about yourself</b>\n\n"
            "I'll set up the right categories and features "
            "for you.\n\n"
            "Just type what you do:\n"
            "\u2022 <i>I'm a freelance designer</i>\n"
            "\u2022 <i>I run a small restaurant</i>\n"
            "\u2022 <i>I'm a real estate agent</i>\n"
            "\u2022 <i>Just personal finances</i>"
        ),
        "ask_invite": (
            "Enter the invite code that the account owner "
            "shared with you:"
        ),
        "already_registered": (
            "You're already registered! Here's what I can do:\n\n"
            "\U0001f4b0 <b>Finance</b> \u2014 'coffee 5', receipt photo, 'stats', 'invoice'\n"
            "\U0001f4c4 <b>Documents</b> \u2014 'scan PDF', 'convert to Word', 'fill form'\n"
            "\U0001f4e7 <b>Email</b> \u2014 'check inbox', 'send email to...'\n"
            "\U0001f4c5 <b>Calendar</b> \u2014 'events today', 'morning brief'\n"
            "\u2705 <b>Tasks</b> \u2014 'remind me at 5pm', 'shopping list'\n"
            "\U0001f9e0 <b>Life</b> \u2014 'mood 8', 'log lunch', 'remember X'\n"
            "\U0001f50d <b>Search</b> \u2014 'find pizza nearby', YouTube, maps\n"
            "\u270d\ufe0f <b>Write</b> \u2014 'draft message', 'generate image', 'write code'\n"
            "\U0001f465 <b>Clients</b> \u2014 'new booking', 'add contact'\n\n"
            "Just type naturally!"
        ),
        "categories_label": "Categories",
        "invite_code_label": "Family invite code",
        "invite_code_hint": "(share with family for shared tracking)",
        "setup_done": (
            "\u2705 <b>All set!</b> "
            "Your '{profile}' profile is ready."
        ),
        "start_tracking": (
            "Now you can start tracking expenses \u2014 "
            "just type 'coffee 5' or send a receipt photo."
        ),
        "quick_start": (
            "Here's how to get started:\n\n"
            "\U0001f4b0 <b>Finance</b> \u2014 "
            "'coffee 5', receipt photo, 'stats', 'invoice'\n"
            "\U0001f4c4 <b>Documents</b> \u2014 "
            "'scan PDF', 'convert to Word', 'fill form'\n"
            "\U0001f4e7 <b>Email</b> \u2014 "
            "'check inbox', 'send email to...'\n"
            "\U0001f4c5 <b>Calendar</b> \u2014 "
            "'events today', 'morning brief'\n"
            "\u2705 <b>Tasks</b> \u2014 "
            "'remind me at 5pm', 'shopping list'\n"
            "\U0001f9e0 <b>Life</b> \u2014 "
            "'mood 8', 'log lunch', 'remember I like oat milk'\n"
            "\U0001f50d <b>Search</b> \u2014 "
            "'find pizza nearby', 'compare options'\n"
            "\u270d\ufe0f <b>Write</b> \u2014 "
            "'draft a message', 'generate image of sunset'\n"
            "\U0001f465 <b>Clients</b> \u2014 "
            "'add contact', 'new booking'\n\n"
            "Just type naturally \u2014 I'll understand!"
        ),
        "share_location_prompt": (
            "Tap the button below so I can detect your city "
            "for nearby searches."
        ),
        "share_location_btn": "\U0001f4cd Share location",
        "tz_location_prompt": (
            "\U0001f30d <b>One last thing</b> \u2014 share your location "
            "so I get your <b>timezone</b> right.\n\n"
            "This means accurate:\n"
            "\u2022 Morning & evening briefs\n"
            "\u2022 Reminders & notifications\n"
            "\u2022 Greetings & time references\n\n"
            "Tap the button below to share."
        ),
        "tz_skip_hint": "Or skip this step:",
        "tz_skip_btn": "Skip for now",
        "tz_location_confirmed": (
            "\u2705 Got it! Your city is <b>{city}</b> "
            "and timezone is <b>{tz}</b>.\n\n"
            "You're all set \u2014 just start typing!"
        ),
        "tz_skip_confirmed": (
            "No problem! I'll use a default timezone for now.\n"
            "You can share your location anytime."
        ),
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
            "\U0001f3af <b>Cu\u00e9ntame sobre ti</b>\n\n"
            "Configurar\u00e9 las categor\u00edas y funciones "
            "adecuadas para ti.\n\n"
            "Escribe a qu\u00e9 te dedicas:\n"
            "\u2022 <i>Soy dise\u00f1ador freelance</i>\n"
            "\u2022 <i>Tengo un peque\u00f1o restaurante</i>\n"
            "\u2022 <i>Soy agente inmobiliario</i>\n"
            "\u2022 <i>Solo finanzas personales</i>"
        ),
        "ask_invite": (
            "Ingresa el c\u00f3digo de invitaci\u00f3n que te "
            "comparti\u00f3 el due\u00f1o de la cuenta:"
        ),
        "already_registered": (
            "\u00a1Ya est\u00e1s registrado! Esto es lo que puedo hacer:\n\n"
            "\U0001f4b0 <b>Finanzas</b> \u2014 "
            "'caf\u00e9 5', foto de recibo, 'estad\u00edsticas', 'factura'\n"
            "\U0001f4c4 <b>Documentos</b> \u2014 "
            "'escanear PDF', 'convertir a Word', 'llenar formulario'\n"
            "\U0001f4e7 <b>Email</b> \u2014 'revisar inbox', 'enviar email a...'\n"
            "\U0001f4c5 <b>Calendario</b> \u2014 'eventos hoy', 'resumen matutino'\n"
            "\u2705 <b>Tareas</b> \u2014 'recu\u00e9rdame a las 5', 'lista de compras'\n"
            "\U0001f9e0 <b>Vida</b> \u2014 '\u00e1nimo 8', 'registrar almuerzo', 'recuerda X'\n"
            "\U0001f50d <b>Buscar</b> \u2014 'pizza cerca', YouTube, mapas\n"
            "\u270d\ufe0f <b>Escribir</b> \u2014 "
            "'redactar mensaje', 'generar imagen', 'escribir c\u00f3digo'\n"
            "\U0001f465 <b>Clientes</b> \u2014 'nueva reserva', 'agregar contacto'\n\n"
            "\u00a1Solo escribe naturalmente!"
        ),
        "categories_label": "Categor\u00edas",
        "invite_code_label": "C\u00f3digo de invitaci\u00f3n",
        "invite_code_hint": "(compartir para seguimiento conjunto)",
        "setup_done": (
            "\u2705 <b>\u00a1Listo!</b> "
            "Tu perfil '{profile}' est\u00e1 listo."
        ),
        "start_tracking": (
            "Registra gastos \u2014 escribe "
            "'caf\u00e9 5' o env\u00eda un recibo."
        ),
        "quick_start": (
            "Esto es lo que puedo hacer:\n\n"
            "\U0001f4b0 <b>Finanzas</b> \u2014 "
            "'caf\u00e9 5', foto de recibo, 'estad\u00edsticas', 'factura'\n"
            "\U0001f4c4 <b>Documentos</b> \u2014 "
            "'escanear PDF', 'convertir a Word', 'llenar formulario'\n"
            "\U0001f4e7 <b>Email</b> \u2014 "
            "'revisar inbox', 'enviar email a...'\n"
            "\U0001f4c5 <b>Calendario</b> \u2014 "
            "'eventos hoy', 'resumen matutino'\n"
            "\u2705 <b>Tareas</b> \u2014 "
            "'recu\u00e9rdame a las 5', 'lista de compras'\n"
            "\U0001f9e0 <b>Vida</b> \u2014 "
            "'\u00e1nimo 8', 'registrar almuerzo', 'recuerda que me gusta la avena'\n"
            "\U0001f50d <b>Buscar</b> \u2014 "
            "'pizza cerca', 'comparar opciones'\n"
            "\u270d\ufe0f <b>Escribir</b> \u2014 "
            "'redactar mensaje', 'generar imagen de un atardecer'\n"
            "\U0001f465 <b>Clientes</b> \u2014 "
            "'agregar contacto', 'nueva reserva'\n\n"
            "\u00a1Solo escribe naturalmente \u2014 te entender\u00e9!"
        ),
        "share_location_prompt": (
            "Toca el bot\u00f3n de abajo para detectar tu ciudad "
            "y buscar lugares cercanos."
        ),
        "share_location_btn": "\U0001f4cd Compartir ubicaci\u00f3n",
        "tz_location_prompt": (
            "\U0001f30d <b>\u00daltimo paso</b> \u2014 comparte tu ubicaci\u00f3n "
            "para configurar tu <b>zona horaria</b>.\n\n"
            "Esto permite:\n"
            "\u2022 Res\u00famenes de ma\u00f1ana y noche precisos\n"
            "\u2022 Recordatorios a la hora correcta\n"
            "\u2022 Saludos y referencias horarias exactas\n\n"
            "Toca el bot\u00f3n de abajo."
        ),
        "tz_skip_hint": "O puedes omitir este paso:",
        "tz_skip_btn": "Omitir por ahora",
        "tz_location_confirmed": (
            "\u2705 \u00a1Listo! Tu ciudad es <b>{city}</b> "
            "y tu zona horaria es <b>{tz}</b>.\n\n"
            "\u00a1Ya puedes empezar a escribir!"
        ),
        "tz_skip_confirmed": (
            "\u00a1Sin problema! Usar\u00e9 una zona horaria predeterminada.\n"
            "Puedes compartir tu ubicaci\u00f3n en cualquier momento."
        ),
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
            "\U0001f3af <b>介绍一下你自己</b>\n\n"
            "我会为你设置合适的分类和功能。\n\n"
            "告诉我你做什么：\n"
            "\u2022 <i>我是自由设计师</i>\n"
            "\u2022 <i>我经营一家小餐厅</i>\n"
            "\u2022 <i>我做房地产</i>\n"
            "\u2022 <i>只是个人记账</i>"
        ),
        "ask_invite": "请输入账户所有者分享给你的邀请码：",
        "already_registered": (
            "你已经注册了！以下是我的功能：\n\n"
            "\U0001f4b0 <b>财务</b> — '咖啡 5'、收据照片、'统计'、'发票'\n"
            "\U0001f4c4 <b>文档</b> — '扫描PDF'、'转换为Word'、'填写表格'\n"
            "\U0001f4e7 <b>邮件</b> — '查看收件箱'、'发邮件给...'\n"
            "\U0001f4c5 <b>日历</b> — '今天的日程'、'早间简报'\n"
            "\u2705 <b>任务</b> — '下午5点提醒我'、'购物清单'\n"
            "\U0001f9e0 <b>生活</b> — '心情 8'、'记录午餐'、'记住X'\n"
            "\U0001f50d <b>搜索</b> — '附近的披萨'、YouTube、地图\n"
            "\u270d\ufe0f <b>写作</b> — '起草消息'、'生成图片'、'写代码'\n"
            "\U0001f465 <b>客户</b> — '新建预约'、'添加联系人'\n\n"
            "直接输入就行！"
        ),
        "categories_label": "分类",
        "invite_code_label": "家庭邀请码",
        "invite_code_hint": "（分享给家人共同记账）",
        "setup_done": "\u2705 <b>设置完成！</b>'{profile}'配置就绪。",
        "start_tracking": (
            "直接输入'咖啡 5'或发送收据照片。"
        ),
        "quick_start": (
            "以下是我的功能：\n\n"
            "\U0001f4b0 <b>财务</b> — "
            "'咖啡 5'、收据照片、'统计'、'发票'\n"
            "\U0001f4c4 <b>文档</b> — "
            "'扫描PDF'、'转换为Word'、'填写表格'\n"
            "\U0001f4e7 <b>邮件</b> — "
            "'查看收件箱'、'发邮件给...'\n"
            "\U0001f4c5 <b>日历</b> — "
            "'今天的日程'、'早间简报'\n"
            "\u2705 <b>任务</b> — "
            "'下午5点提醒我'、'购物清单'\n"
            "\U0001f9e0 <b>生活</b> — "
            "'心情 8'、'记录午餐'、'记住我喜欢燕麦奶'\n"
            "\U0001f50d <b>搜索</b> — "
            "'附近的披萨'、'比较选项'\n"
            "\u270d\ufe0f <b>写作</b> — "
            "'起草消息'、'生成日落图片'\n"
            "\U0001f465 <b>客户</b> — "
            "'添加联系人'、'新建预约'\n\n"
            "直接输入就行 — 我能理解！"
        ),
        "share_location_prompt": (
            "点击下方按钮，"
            "我可以检测你的城市以便搜索附近地点。"
        ),
        "share_location_btn": "\U0001f4cd 分享位置",
        "tz_location_prompt": (
            "\U0001f30d <b>最后一步</b> \u2014 分享你的位置，"
            "以便我正确设置<b>时区</b>。\n\n"
            "这样可以确保：\n"
            "\u2022 早晚简报时间准确\n"
            "\u2022 提醒和通知准时到达\n"
            "\u2022 问候和时间引用正确\n\n"
            "点击下方按钮分享。"
        ),
        "tz_skip_hint": "或者跳过这一步：",
        "tz_skip_btn": "暂时跳过",
        "tz_location_confirmed": (
            "\u2705 好的！你的城市是<b>{city}</b>，"
            "时区是<b>{tz}</b>。\n\n"
            "一切准备就绪 \u2014 开始使用吧！"
        ),
        "tz_skip_confirmed": (
            "没问题！我会使用默认时区。\n"
            "你可以随时分享位置来更新。"
        ),
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
            "\U0001f3af <b>Расскажите о себе</b>\n\n"
            "Я настрою категории и функции "
            "специально для вас.\n\n"
            "Просто напишите, чем занимаетесь:\n"
            "\u2022 <i>Я фрилансер-дизайнер</i>\n"
            "\u2022 <i>У меня небольшой ресторан</i>\n"
            "\u2022 <i>Я занимаюсь недвижимостью</i>\n"
            "\u2022 <i>Просто личные финансы</i>"
        ),
        "ask_invite": (
            "Введите код приглашения, который вам "
            "прислал владелец аккаунта:"
        ),
        "already_registered": (
            "Вы уже зарегистрированы! Вот что я умею:\n\n"
            "\U0001f4b0 <b>Финансы</b> \u2014 «кофе 150», фото чека, «статистика», «инвойс»\n"
            "\U0001f4c4 <b>Документы</b> \u2014 «скан PDF», «конвертируй в Word», «заполни форму»\n"
            "\U0001f4e7 <b>Почта</b> \u2014 «проверь почту», «отправь email»\n"
            "\U0001f4c5 <b>Календарь</b> \u2014 «события сегодня», «утренний брифинг»\n"
            "\u2705 <b>Задачи</b> \u2014 «напомни в 17:00», «список покупок»\n"
            "\U0001f9e0 <b>Жизнь</b> \u2014 «настроение 8», «обед», «запомни X»\n"
            "\U0001f50d <b>Поиск</b> \u2014 «найди пиццу рядом», YouTube, карты\n"
            "\u270d\ufe0f <b>Тексты</b> \u2014 "
            "«напиши сообщение», «картинку», «код»\n"
            "\U0001f465 <b>Клиенты</b> \u2014 «новая запись», «добавь контакт»\n\n"
            "Просто пишите как обычно!"
        ),
        "categories_label": "Категории",
        "invite_code_label": "Код приглашения для семьи",
        "invite_code_hint": "(отправьте его близким для общего учёта)",
        "setup_done": (
            "\u2705 <b>Готово!</b> "
            "Профиль «{profile}» настроен."
        ),
        "start_tracking": (
            "Теперь можете записывать расходы — просто напишите, "
            "например: «кофе 150» или отправьте фото чека."
        ),
        "quick_start": (
            "Вот что я умею:\n\n"
            "\U0001f4b0 <b>Финансы</b> \u2014 "
            "«кофе 150», фото чека, «статистика», «инвойс»\n"
            "\U0001f4c4 <b>Документы</b> \u2014 "
            "«скан PDF», «конвертируй в Word», «заполни форму»\n"
            "\U0001f4e7 <b>Почта</b> \u2014 "
            "«проверь почту», «отправь email...»\n"
            "\U0001f4c5 <b>Календарь</b> \u2014 "
            "«события сегодня», «утренний брифинг»\n"
            "\u2705 <b>Задачи</b> \u2014 "
            "«напомни в 17:00», «список покупок»\n"
            "\U0001f9e0 <b>Жизнь</b> \u2014 "
            "«настроение 8», «записать обед», «запомни что я люблю овсяное молоко»\n"
            "\U0001f50d <b>Поиск</b> \u2014 "
            "«найди пиццу рядом», «сравни варианты»\n"
            "\u270d\ufe0f <b>Тексты</b> \u2014 "
            "«напиши сообщение», «сгенерируй картинку заката»\n"
            "\U0001f465 <b>Клиенты</b> \u2014 "
            "«добавь контакт», «новая запись»\n\n"
            "Просто пишите как обычно \u2014 я пойму!"
        ),
        "share_location_prompt": (
            "Нажмите кнопку ниже, чтобы я определил ваш город "
            "для поиска мест рядом."
        ),
        "share_location_btn": "\U0001f4cd Поделиться геолокацией",
        "tz_location_prompt": (
            "\U0001f30d <b>Последний шаг</b> \u2014 поделитесь геолокацией, "
            "чтобы я правильно определил ваш <b>часовой пояс</b>.\n\n"
            "Это нужно для:\n"
            "\u2022 Утренних и вечерних брифингов вовремя\n"
            "\u2022 Напоминаний в правильное время\n"
            "\u2022 Корректных приветствий\n\n"
            "Нажмите кнопку ниже."
        ),
        "tz_skip_hint": "Или пропустите этот шаг:",
        "tz_skip_btn": "Пропустить",
        "tz_location_confirmed": (
            "\u2705 Отлично! Ваш город \u2014 <b>{city}</b>, "
            "часовой пояс \u2014 <b>{tz}</b>.\n\n"
            "Всё готово \u2014 просто начните писать!"
        ),
        "tz_skip_confirmed": (
            "Без проблем! Буду использовать часовой пояс по умолчанию.\n"
            "Вы можете поделиться геолокацией в любой момент."
        ),
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


def _profile_display_name(business_type: str, lang: str) -> str:
    """Get profile display name in the user's language."""
    names = PROFILE_DISPLAY_NAMES.get(business_type, {})
    return names.get(lang, names.get("en", business_type.title()))


# Maps native/colloquial language names and common variations → ISO code.
# Covers: native name, English name, short forms, transliterations, demonyms.
_NATIVE_LANGUAGE_NAMES: dict[str, str] = {
    # English
    "english": "en", "eng": "en", "инглиш": "en", "англиский": "en",
    "английский": "en",
    # Spanish
    "español": "es", "espanol": "es", "spanish": "es", "испанский": "es",
    # French
    "français": "fr", "francais": "fr", "french": "fr", "француз": "fr",
    "французский": "fr",
    # German
    "deutsch": "de", "german": "de", "немецкий": "de",
    # Portuguese
    "português": "pt", "portugues": "pt", "portuguese": "pt",
    "португальский": "pt",
    # Italian
    "italiano": "it", "italian": "it", "итальянский": "it",
    # Russian
    "русский": "ru", "russian": "ru", "руский": "ru", "рус": "ru",
    # Chinese
    "chinese": "zh", "中文": "zh", "汉语": "zh", "китайский": "zh",
    # Japanese
    "日本語": "ja", "japanese": "ja", "японский": "ja",
    # Korean
    "한국어": "ko", "korean": "ko", "корейский": "ko",
    # Arabic
    "العربية": "ar", "عربي": "ar", "arabic": "ar", "арабский": "ar",
    # Hindi
    "हिन्दी": "hi", "हिंदी": "hi", "hindi": "hi", "хинди": "hi",
    # Turkish
    "türkçe": "tr", "turkce": "tr", "turkish": "tr", "турецкий": "tr",
    "турок": "tr",
    # Polish
    "polski": "pl", "polish": "pl", "польский": "pl",
    # Dutch
    "nederlands": "nl", "dutch": "nl", "голландский": "nl",
    # Swedish
    "svenska": "sv", "swedish": "sv", "шведский": "sv",
    # Ukrainian
    "українська": "uk", "украинский": "uk", "ukrainian": "uk",
    "украинська": "uk", "укр": "uk",
    # Vietnamese
    "tiếng việt": "vi", "vietnamese": "vi", "вьетнамский": "vi",
    # Thai
    "ไทย": "th", "thai": "th", "тайский": "th",
    # Indonesian
    "bahasa indonesia": "id", "bahasa": "id", "indonesia": "id",
    "indonesian": "id",
    # Czech
    "čeština": "cs", "cestina": "cs", "czech": "cs", "чешский": "cs",
    # Romanian
    "română": "ro", "romana": "ro", "romanian": "ro", "румынский": "ro",
    # Hungarian
    "magyar": "hu", "hungarian": "hu", "венгерский": "hu",
    # Greek
    "ελληνικά": "el", "greek": "el", "греческий": "el",
    # Hebrew
    "עברית": "he", "hebrew": "he", "иврит": "he",
    # Danish
    "dansk": "da", "danish": "da", "датский": "da",
    # Finnish
    "suomi": "fi", "finnish": "fi", "финский": "fi",
    # Norwegian
    "norsk": "no", "norwegian": "no", "норвежский": "no",
    # Kyrgyz — all variations
    "кыргызча": "ky", "кыргыз": "ky", "кыргызский": "ky", "киргиз": "ky",
    "киргизский": "ky", "kyrgyz": "ky",
    # Kazakh
    "қазақша": "kk", "қазақ": "kk", "казахский": "kk", "казах": "kk",
    "kazakh": "kk",
    # Uzbek
    "ўзбекча": "uz", "o'zbekcha": "uz", "узбекский": "uz", "узбек": "uz",
    "uzbek": "uz",
    # Tajik
    "тоҷикӣ": "tg", "тоҷик": "tg", "таджикский": "tg", "таджик": "tg",
    "tajik": "tg",
    # Georgian
    "ქართული": "ka", "georgian": "ka", "грузинский": "ka", "грузин": "ka",
    # Armenian
    "հայերեն": "hy", "armenian": "hy", "армянский": "hy", "армян": "hy",
    # Azerbaijani
    "azərbaycan": "az", "azerbaijani": "az", "азербайджанский": "az",
    "азербайджан": "az",
    # Mongolian
    "монгол": "mn", "mongolian": "mn", "монгольский": "mn",
    # Persian / Farsi
    "فارسی": "fa", "farsi": "fa", "persian": "fa", "персидский": "fa",
    # Swahili
    "kiswahili": "sw", "swahili": "sw",
    # Tagalog / Filipino
    "tagalog": "tl", "filipino": "tl",
    # Malay
    "melayu": "ms", "malay": "ms",
}


async def detect_language(text: str) -> tuple[str, str]:
    """Detect which language the user wants from their input.

    The user is answering "choose your language" — they may type:
    - A language name in English ("Kyrgyz", "French")
    - A language name in that language ("кыргызча", "français")
    - Text in their preferred language ("привет" → Russian)

    Returns (iso_code, language_name).
    """
    # Quick match: exact or partial against known language names
    text_lower = text.strip().lower()
    # 1) Exact match in LANGUAGE_NAMES (English names)
    for code, name in LANGUAGE_NAMES.items():
        if text_lower == name.lower() or text_lower == code:
            return code, name
    # 2) Exact match in native names dict
    native = _NATIVE_LANGUAGE_NAMES.get(text_lower)
    if native:
        return native, LANGUAGE_NAMES.get(native, text.strip().title())
    # 3) Partial match: user input starts with or is a prefix of a known name
    #    e.g. "кыргыз" matches "кыргызча", "franc" matches "français"
    for variant, code in _NATIVE_LANGUAGE_NAMES.items():
        if variant.startswith(text_lower) or text_lower.startswith(variant):
            return code, LANGUAGE_NAMES.get(code, text.strip().title())

    try:
        raw = await generate_text(
            "claude-haiku-4-5",
            (
                "The user was asked to choose their preferred language. "
                "They responded with the text below. "
                "Determine WHICH LANGUAGE they want to use.\n\n"
                "If they typed a language name (e.g. 'Kyrgyz', 'français', "
                "'кыргызча'), return that language.\n"
                "If they typed a phrase, detect the language of the phrase.\n\n"
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


_INVITE_KEYWORDS = frozenset({
    "invite", "invite code", "код приглашения", "пригласить",
    "add family", "добавить семью", "family member", "член семьи",
    "добавить члена", "invite member", "пригласить члена",
    "show invite", "показать код", "мой код", "my code",
    "family code", "код семьи", "share code", "поделиться кодом",
})


def _is_invite_request(text: str) -> bool:
    """Check if the message is asking about invite code / adding family member."""
    lower = text.lower().strip()
    return any(kw in lower for kw in _INVITE_KEYWORDS)


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
            # Check if asking for invite code / family member
            if _is_invite_request(text):
                return await self._show_invite_code(context, lang)
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

    async def _show_invite_code(
        self,
        context: SessionContext,
        lang: str,
    ) -> SkillResult:
        """Show the user's family invite code."""
        t = await get_onboarding_texts(lang)
        try:
            async with async_session() as session:
                code = await get_invite_code(session, context.family_id)
            if code:
                msg = {
                    "en": (
                        f"\U0001f465 Your family invite code: <code>{code}</code>\n\n"
                        "Share it with family members. They can join by "
                        "pressing /start and choosing \"Join family\"."
                    ),
                    "ru": (
                        f"\U0001f465 Код приглашения: <code>{code}</code>\n\n"
                        "Отправьте его близким. Они смогут присоединиться, "
                        "нажав /start и выбрав \"Присоединиться к семье\"."
                    ),
                    "es": (
                        f"\U0001f465 Codigo de invitacion: <code>{code}</code>\n\n"
                        "Compartelo con tu familia. Pueden unirse "
                        "presionando /start y eligiendo \"Unirse a familia\"."
                    ),
                }
                return SkillResult(response_text=msg.get(lang, msg["en"]))
            return SkillResult(
                response_text=t.get("already_registered", "You're already registered!")
            )
        except Exception as e:
            logger.exception("Failed to get invite code: %s", e)
            return SkillResult(
                response_text=t.get("already_registered", "You're already registered!")
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
            display_name = _profile_display_name(business_type, lang)
            categories_text = _format_categories_text(profile, texts=t)
            cat_line = (
                f"\n{t['categories_label']}: {categories_text}\n"
                if categories_text
                else "\n"
            )

            invite_line = ""
            if family.invite_code:
                invite_line = (
                    f"\n\U0001f465 <b>{t['invite_code_label']}:</b> "
                    f"<code>{family.invite_code}</code>\n"
                    f"{t['invite_code_hint']}\n"
                )

            return SkillResult(
                response_text=(
                    f"{t['setup_done'].format(profile=display_name)}\n"
                    f"{cat_line}"
                    f"{invite_line}\n"
                    f"{t['quick_start']}"
                ),
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
                        f"{t['quick_start']}"
                    ),
                )
            else:
                return SkillResult(response_text=t["invite_invalid"])
        except Exception as e:
            logger.exception("join_family failed for user_id=%s: %s", message.user_id, e)
            return SkillResult(response_text=t["error_join"])

    def get_system_prompt(self, context: SessionContext) -> str:
        return ONBOARDING_SYSTEM_PROMPT


skill = OnboardingSkill()
