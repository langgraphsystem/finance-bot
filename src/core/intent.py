import json
import logging
import re
from datetime import date

from src.core.llm.clients import get_instructor_anthropic, google_client
from src.core.observability import observe
from src.core.schemas.intent import IntentData, IntentDetectionResult

logger = logging.getLogger(__name__)

DELETE_VERBS = (
    "удали",
    "удалить",
    "delete",
    "remove",
    "очисти",
    "сотри",
    "clear",
)

UNDO_LAST_HINTS = (
    "последн",
    "undo",
    "отмени послед",
    "верни обратно",
)

DELETE_SCOPE_KEYWORDS: list[tuple[str, str]] = [
    ("все данные", "all"),
    ("all data", "all"),
    ("расход", "expenses"),
    ("expense", "expenses"),
    ("доход", "income"),
    ("income", "income"),
    ("транзакц", "transactions"),
    ("transaction", "transactions"),
    ("напиток", "drinks"),
    ("напитк", "drinks"),
    ("вода", "drinks"),
    ("кофе", "drinks"),
    ("чай", "drinks"),
    ("drink", "drinks"),
    ("еда", "food"),
    ("питани", "food"),
    ("food", "food"),
    ("настроен", "mood"),
    ("mood", "mood"),
    ("заметк", "notes"),
    ("note", "notes"),
    ("напоминан", "reminders"),
    ("reminder", "reminders"),
    ("задач", "tasks"),
    ("task", "tasks"),
    ("покуп", "shopping"),
    ("shopping", "shopping"),
    ("сообщен", "messages"),
    ("истори", "messages"),
    ("history", "messages"),
    ("life", "life_events"),
    ("жизн", "life_events"),
]

DELETE_PERIOD_KEYWORDS: list[tuple[str, str]] = [
    ("сегодня", "today"),
    ("today", "today"),
    ("вчера", "yesterday"),
    ("yesterday", "yesterday"),
    ("недел", "week"),
    ("week", "week"),
    ("месяц", "month"),
    ("month", "month"),
    ("год", "year"),
    ("year", "year"),
]

LIFE_SCOPES = {"food", "drinks", "mood", "notes", "life_events"}

INTENT_DETECTION_PROMPT = """Определи намерение пользователя из сообщения.

Возможные интенты:
- add_expense: запись расхода ("заправился на 50", "купил продукты 87.50")
- add_income: запись дохода С СУММОЙ ("заработал 185", "получил зарплату", \
"получил оплату за рейс 2500", "доход 3000", "мне заплатили 500")
- scan_receipt: пользователь отправил фото чека
- scan_document: пользователь отправил фото документа, инвойса, \
rate confirmation, или другого изображения
- query_stats: запрос статистики ("сколько потратил за неделю", "сравни с прошлым месяцем")
- query_report: генерация PDF-отчёта ("отчёт", "report", \
"покажи итоги", "PDF", "сгенерируй отчёт", "месячный отчёт")
- correct_category: исправление категории ("это не продукты, а бензин")
- undo_last: отмена последней операции ("отмени последнюю", "undo", "верни обратно")
- mark_paid: ТОЛЬКО изменить статус груза на "оплачен", БЕЗ суммы \
("оплатили груз", "mark paid", "груз оплачен", "отметь рейс оплаченным"). \
ВАЖНО: если в сообщении есть СУММА — это add_income, НЕ mark_paid!
- onboarding: ТОЛЬКО команда /start или прямая просьба зарегистрироваться. \
НЕ приветствия типа "привет/hello/hi" — это general_chat
- set_budget: установить бюджет или лимит ("бюджет на продукты \
30000", "лимит 5000 в неделю", "set budget")
- add_recurring: добавить регулярный платёж ("подписка", \
"recurring", "каждый месяц плачу", "аренда 50000")
- complex_query: сложный аналитический запрос ("сложный анализ", \
"сравни с бюджетом", "полный отчёт", \
"анализ трат за 3 месяца", "что происходит с финансами")
- quick_capture: заметка, идея, мысль ("идея: ...", "заметка: ...", "запомни: ...", \
"мысль: ...", текст-заметка без финансового контекста и без суммы)
- track_food: запись еды БЕЗ суммы ("съел пиццу", "завтрак: каша", \
"обед: суп и салат", "поел", "ужин: стейк")
- track_drink: напиток БЕЗ суммы ("кофе", "вода", "чай", \
"выпил воду", "2 кофе", "вода 500мл")
- mood_checkin: чек-ин состояния ("настроение 7", "энергия 5", "стресс 3", \
"спал 7 часов", "устал", "feeling great", "checkin")
- day_plan: план дня ("план: ...", "топ задача: ...", \
"сегодня: задеплоить MVP", "план дня")
- day_reflection: рефлексия дня ("рефлексия", "итоги дня", \
"что получилось сегодня", "review", "вечерний обзор")
- life_search: поиск по памяти/заметкам ("что я писал про X?", \
"идеи за неделю", "мои заметки о...", "что я ел вчера?", "поиск: ...")
- set_comm_mode: режим общения ("тихий режим", "coaching mode", \
"молча сохраняй", "режим: квитанция", "silent mode")
- create_task: создать задачу/дело ("add task: ...", "задача: ...", \
"to-do: ...", "добавь в список: ...", "нужно сделать: ...")
- list_tasks: показать список задач ("мои задачи", "что мне нужно сделать", \
"my tasks", "список дел", "what's on my list")
- set_reminder: установить напоминание ("remind me ...", "напомни ...", \
"напоминание: ...", "remind me to pick up Emma at 3:15", \
"напоминай каждый день в 5 утра", "daily reminder at 7pm", \
"напоминание каждую неделю"). Поддерживает повторяющиеся напоминания (daily/weekly/monthly).
- complete_task: отметить задачу выполненной ("done with ...", "готово: ...", \
"выполнил ...", "задача выполнена", "mark done: ...")
- quick_answer: фактический вопрос, ответ из знаний ("сколько чашек в галлоне?", \
"what's the capital of France?", "как перевести фунты в кг?")
- web_search: поиск в интернете, текущая информация ("what time does Costco close?", \
"расценки на ремонт ванной в Queens", "лучший ресторан рядом", "погода завтра")
- compare_options: сравнение двух+ вариантов ("compare PEX vs copper", \
"Costco vs Sam's Club", "Toyota Camry или Honda Accord", "что лучше: X или Y?")
- maps_search: поиск мест на карте, адресов, маршрутов ("кафе рядом", "найди ресторан в Queens", \
"ближайшая заправка", "маршрут до Walmart", "как доехать до аэропорта", \
"coffee near me", "directions to Home Depot", "рестораны в Бруклине", \
"расстояние от X до Y")
- youtube_search: поиск видео на YouTube, инструкции, обзоры товаров ("найди видео", \
"инструкция по замене масла Toyota", "обзор iPhone на youtube", \
"tutorial for X", "how to fix X video", "youtube video about"). \
ТАКЖЕ: если пользователь отправил ссылку YouTube (youtube.com/watch, youtu.be/, \
youtube.com/shorts/) — это ВСЕГДА youtube_search, даже без слова "youtube"
- draft_message: написать сообщение, письмо, email ("write an email to school", \
"напиши письмо", "draft a text to Mike", "compose a message")
- translate_text: перевести текст ("translate to Spanish", "переведи на английский", \
"translate this")
- write_post: написать пост, ответ на отзыв, контент для платформы ("write a review response", \
"напиши ответ на отзыв", "write an Instagram caption", "write a post about...")
- proofread: проверить текст на ошибки ("proofread this", "check my text", \
"проверь грамматику", "fix my spelling")
- read_inbox: проверить почту, сводка по входящим ("check my email", \
"what's in my inbox", "проверь почту", "новые письма")
- send_email: написать и отправить email ("email John about the meeting", \
"отправь письмо", "email Mrs. Rodriguez")
- draft_reply: ответить на письмо ("reply to that email", "ответь на письмо от школы")
- follow_up_email: проверить неотвеченные письма ("any emails I haven't replied to?", \
"на какие письма не ответил?")
- summarize_thread: кратко пересказать переписку ("summarize the thread with Sarah", \
"перескажи переписку с врачом")
- list_events: показать расписание ("what's on my calendar?", "расписание на завтра", \
"что на сегодня?", "my schedule")
- create_event: создать событие ("schedule a meeting tomorrow at 3pm", \
"запиши встречу на пятницу 10:00", "schedule estimate for Mrs. Chen")
- find_free_slots: найти свободное время ("when am I free?", "когда я свободен?", \
"am I free Thursday morning?")
- reschedule_event: перенести событие ("move the dentist to Thursday", \
"перенеси встречу на 15:00", "push Mike's job to 11am")
- morning_brief: утренняя сводка ("morning brief", "what's my day look like?", \
"план на сегодня", "утренняя сводка")
- shopping_list_add: добавить товары в список покупок ("add milk to my list", \
"добавь молоко в список", "need bread and eggs", "нужно купить молоко, яйца", \
"put butter on my grocery list", "в список: хлеб, масло")
- shopping_list_view: показать список покупок ("what's on my list?", "show my grocery list", \
"мой список покупок", "shopping list", "что в списке?", "покажи список")
- shopping_list_remove: отметить/убрать товар из списка ("got the milk", "bought eggs", \
"убери хлеб из списка", "got everything", "купил все", "взял молоко")
- shopping_list_clear: очистить весь список ("clear my list", "очисти список", \
"список готов", "done shopping", "list is done", "удали список")
- evening_recap: вечерний обзор дня ("evening recap", "how was my day?", \
"итоги дня", "recap", "вечерний обзор", "wrap up my day")
- web_action: выполнить действие на сайте через браузер ("go to website and fill form", \
"зайди на сайт и заполни форму", "submit order on Amazon", "book appointment online")
- price_check: проверить цену товара на сайте ("check price of lumber at Home Depot", \
"сколько стоит X на сайте Y", "price of 2x4 at Lowe's")
- price_alert: мониторинг цены, оповещение о цене ("alert me when lumber drops below $5", \
"мониторь цену на X", "notify when price goes below/above")
- news_monitor: мониторинг новостей, подписка на тему ("monitor plumbing industry news", \
"следи за новостями о X", "alert me about school closings")
- create_booking: забронировать, записать клиента ("book John tomorrow 2pm", \
"запиши клиента на завтра 14:00", "schedule appointment for faucet repair")
- list_bookings: расписание бронирований ("my bookings today", \
"мои бронирования", "today's appointments", "schedule")
- cancel_booking: отменить бронирование ("cancel John's appointment", \
"отмени запись", "cancel booking")
- reschedule_booking: перенести бронирование ("move John to Thursday", \
"перенеси запись", "reschedule appointment")
- add_contact: добавить контакт/клиента ("add client John 917-555-1234", \
"добавь клиента", "new contact")
- list_contacts: список контактов ("my contacts", "список клиентов", "all contacts")
- find_contact: найти контакт ("find John", "найди клиента", "search contact")
- send_to_client: написать/позвонить клиенту ("text John I'm running late", \
"напиши клиенту", "call Mrs. Johnson", "SMS клиенту")
- delete_data: удаление данных за период или по типу ("удали расходы за январь", \
"очисти записи о еде за неделю", "delete my expenses for last month", \
"удали все данные за прошлый месяц", "сотри историю сообщений", \
"удали напоминание", "delete reminder"). \
Извлеки delete_scope: expenses/income/transactions/food/drinks/ \
mood/notes/life_events/tasks/shopping/messages/reminders/all
- generate_card: создать визуальную карточку, трекер, чек-лист в виде картинки \
("сделай трекер чтения на 30 дней", "нарисуй карточку списка покупок", \
"create a habit tracker image", "сгенерируй красивую карточку"). \
Извлеки card_topic: полное описание запроса пользователя
- generate_program: написать/создать программу, скрипт, код, парсер, \
калькулятор, утилиту, автоматизацию ("напиши парсер для сайта", \
"сделай калькулятор калорий", "create a CSV converter script", \
"напиши бота для телеграм", "write a Python script"). \
Извлеки program_description: описание программы, \
program_language: язык если указан (python, js, bash...)
- modify_program: изменить/исправить/обновить/доработать уже созданную \
программу ("измени программу", "исправь ошибку в коде", \
"добавь кнопку к программе", "поменяй цвет на синий", \
"modify the program", "fix the code", "update the script"). \
Извлеки program_changes: описание изменений, \
program_id: ID программы если указан
- general_chat: ТОЛЬКО приветствие, благодарность или разговор, \
который НЕВОЗМОЖНО отнести ни к одному из интентов выше

ГЛАВНОЕ ПРАВИЛО: всегда старайся определить конкретный интент по смыслу. \
general_chat — крайний случай. Если сообщение хоть немного похоже на \
финансы, почту, календарь, задачи, заметки, еду, напитки, настроение, \
планирование, поиск — выбирай соответствующий интент.

КРИТИЧНО — modify_program vs generate_program (ПРОВЕРЬ ПЕРВЫМ): \
если пользователь просит ИЗМЕНИТЬ/ИСПРАВИТЬ/ОБНОВИТЬ/ДОРАБОТАТЬ уже \
существующую программу — это modify_program. \
Примеры: "измени программу", "поменяй цвет", "добавь кнопку", "fix the bug". \
Если просит НАПИСАТЬ/СОЗДАТЬ/СДЕЛАТЬ НОВУЮ программу — generate_program. \
Примеры: "напиши калькулятор", "создай скрипт", "create a Python script".

Правила приоритета (shopping list vs tasks):
- "add X to my list/shopping list/grocery list" / "добавь в список покупок" → shopping_list_add
- "show my list/grocery list" / "мой список покупок" / "что в списке" → shopping_list_view
- "got the X" / "bought X" / "купил X" + контекст списка покупок → shopping_list_remove
- "got everything" / "купил все" → shopping_list_remove
- "clear my list" / "очисти список" / "done shopping" → shopping_list_clear
- "need X, Y, Z" (товары без суммы, без "task:") → shopping_list_add
- ВАЖНО: если недавний контекст диалога содержит shopping_list_view или shopping_list_remove, \
и текущее сообщение — одно-два слова (название товара БЕЗ глагола add/need/добавь/нужно/купить), \
то это shopping_list_remove (пользователь отмечает купленный товар), НЕ shopping_list_add. \
Примеры: "хлеб" после просмотра/отметки списка → shopping_list_remove; \
"соль" после "купил макароны" → shopping_list_remove
- "задача: ..." или "add task: ..." → create_task (всегда)
- "напомни ..." или "remind me ..." → set_reminder (всегда)
- "каждый день", "ежедневно", "daily" + напоминание → set_reminder с reminder_recurrence: "daily"
- "каждую неделю", "weekly" + напоминание → set_reminder с reminder_recurrence: "weekly"
- "каждый месяц", "monthly" + напоминание → set_reminder с reminder_recurrence: "monthly"
- ВАЖНО (follow-up): если в недавнем контексте диалога AI Assistant \
установил напоминание (set_reminder), \
и текущее сообщение УТОЧНЯЕТ время, повторение или детали этого напоминания \
("именно по времени", "exactly at 5pm", "каждый день", "в 5:08 и 17:28", \
"по времени когда сухур"), то это set_reminder (follow-up), НЕ general_chat и НЕ quick_answer. \
Извлеки время и частоту из текущего сообщения + контекста диалога.
- "мои задачи" / "my tasks" / "what do I need to do" → list_tasks
- "готово" или "done with ..." + контекст задач → complete_task
- "план дня" (без конкретной задачи) → day_plan (life-tracking)

Правила приоритета (browser + monitoring):
- "go to website", "fill form", "submit", "book online" → web_action
- "check price of X at Y", "сколько стоит X на сайте Y" → price_check
- "alert me when price", "мониторь цену", "notify when price" → price_alert
- "monitor news about", "следи за новостями", "alert me about [topic]" → news_monitor

Правила приоритета (booking + CRM):
- "book/запиши/schedule appointment/забронируй" + клиент/время → create_booking
- "my bookings/мои бронирования/appointments today" → list_bookings
- "cancel booking/отмени запись" → cancel_booking
- "reschedule/перенеси запись/move appointment" → reschedule_booking
- "add client/добавь клиента/new contact" → add_contact
- "my contacts/список клиентов" → list_contacts
- "find contact/найди клиента" → find_contact
- "text client/напиши клиенту/call client/позвони клиенту/SMS" → send_to_client
- ВАЖНО: "book" + конкретный клиент/время → create_booking (НЕ create_event)
- "create_event" — для личного календаря; "create_booking" — для клиентов

Правила приоритета (research vs general_chat):
- Ссылка youtube.com/watch, youtu.be/, youtube.com/shorts/ → youtube_search (ВСЕГДА, приоритет!)
- Вопрос с "?" или "what/how/why/when/сколько/как/почему/где" → quick_answer
- "search ...", "найди ...", "загугли ...", текущие данные → web_search
- "compare", "vs", "или ... или", "что лучше" → compare_options
- "рядом", "near me", "найди место", "маршрут до", "directions to", адреса → maps_search
- "youtube", "видео", "video", "tutorial", "инструкция по X", "обзор" + товар → youtube_search
- Приветствие, болтовня без конкретного вопроса → general_chat

Правило detail_mode (для maps_search и youtube_search):
- detail_mode: true ТОЛЬКО если пользователь ЯВНО просит МАССОВЫЙ список \
или недоволен результатами:
  "покажи больше мест/ещё/more places", "все кофейни/all places/список мест"
  "10 кофеен/покажи 5 ресторанов", "все видео/all videos/больше видео"
  "не то/not what I wanted/покажи другие варианты"
- По умолчанию detail_mode: false или null — Gemini сам описывает места, \
анализирует видео, даёт маршруты, извлекает транскрипции

Правила приоритета (writing vs general_chat):
- СНАЧАЛА ПРОВЕРЬ: "напиши/write/create/сделай" + программу/скрипт/парсер/код/бот/ \
калькулятор/утилиту/конвертер/генератор/автоматизацию → generate_program (НЕ draft_message!)
- "сделай карточку/трекер/картинку" → generate_card (НЕ generate_program)
- "write/draft/compose/напиши/составь" + тема (НЕ код/программа) → draft_message
- "translate/переведи" → translate_text
- "review response/ответ на отзыв/caption/пост" → write_post
- "proofread/check/проверь/fix grammar/исправь" → proofread
- Общая болтовня без запроса на написание → general_chat

Правила приоритета (email/calendar — ВАЖНО):
AI Assistant УМЕЕТ работать с реальной почтой и календарём через Google.
Если пользователь спрашивает о почте, email, календаре, расписании, \
подключении почты, настройке email — это НЕ общий вопрос, а запрос \
к функциям AI Assistant. Маршрутизируй в соответствующий email/calendar intent.
- "check email/inbox/почта/письма/подключить почту" → read_inbox
- "email [кому] about..." / "отправь письмо" → send_email
- "reply to..." / "ответь на письмо" → draft_reply
- "unanswered/не ответил/follow up" → follow_up_email
- "summarize thread/переписка" → summarize_thread

Правила приоритета (calendar):
- "schedule/calendar/расписание/what's on my..." → list_events
- "schedule/create/запиши встречу/назначь" + время → create_event
- "when am I free/свободен" → find_free_slots
- "move/reschedule/перенеси" + событие → reschedule_event
- "morning brief/утренняя сводка/what's my day" → morning_brief

Правила приоритета (удаление данных):
- "удали/delete/очисти/сотри" + тип данных или период → delete_data
- ВАЖНО: "удали напоминание/reminder" → delete_data (scope: reminders), НЕ set_reminder!
- "удали/отмени ПОСЛЕДНЮЮ" (без периода/типа, одна транзакция) → undo_last (как раньше)
- "удали расходы за январь" → delete_data (scope: expenses, period: custom)
- "отмени последнюю" → undo_last

Правила приоритета (финансы vs life-tracking):
- Если в сообщении есть СУММА + финансовый контекст -> add_expense / add_income (приоритет)
- "съел пиццу" (без суммы) -> track_food
- "купил пиццу 500" (с суммой) -> add_expense
- "кофе" (без суммы) -> track_drink; "кофе 150р" -> add_expense
- "настроение 7" -> mood_checkin (число -- шкала, не сумма)
- "идея: ..." или "заметка: ..." -> quick_capture (всегда, даже если в тексте есть число)

Правила извлечения даты:
- Сегодня: {today}
- "вчера" → вчерашняя дата
- "позавчера" → позавчерашняя дата
- "в понедельник", "во вторник" и т.д. → ближайший прошедший день недели
- "10 февраля", "February 10" → конкретная дата
- Если дата НЕ указана в тексте → null (НЕ подставляй сегодня, это сделает код)

Правила извлечения периода (для query_stats, query_report, complex_query, life_search):
- "сегодня", "за сегодня" → period: "today"
- "за неделю", "эту неделю", "на этой неделе" → period: "week"
- "за месяц", "этот месяц", "в этом месяце" → period: "month"
- "за год", "этот год", "в этом году" → period: "year"
- "вчера", "за вчера" → period: "day", date: вчерашняя дата
- "за 15 января", "10 февраля" (конкретный день) → period: "day", date: дата
- "с 1 по 15 февраля", "за первую неделю марта" → period: "custom", \
date_from: "YYYY-MM-DD", date_to: "YYYY-MM-DD"
- "последние N дней" → period: "custom", date_from: today-N, date_to: today
- "между ДАТА1 и ДАТА2" → period: "custom", date_from: ДАТА1, date_to: ДАТА2
- "за прошлый месяц", "прошлую неделю" → period: "prev_month" / "prev_week"
- Если период НЕ указан → period: null (код подставит "month")

Правила извлечения типа записи (для life_search):
- "что я ел", "еда", "питание" → life_event_type: "food"
- "кофе", "вода", "чай", "напитки", "что пил" → life_event_type: "drink"
- "настроение", "mood", "как себя чувствовал" → life_event_type: "mood"
- "задачи", "план", "планы", "tasks" → life_event_type: "task"
- "рефлексия", "итоги", "дневник" → life_event_type: "reflection"
- "заметки", "идеи", "мысли", "notes" → life_event_type: "note"
- Если тип не очевиден → life_event_type: null (искать все типы)

Правила извлечения города (detected_city):
- Если в сообщении упоминается КОНКРЕТНЫЙ город или район → detected_city (на АНГЛИЙСКОМ)
- "рестораны в Бруклине" → detected_city: "Brooklyn"
- "погода в Москве" → detected_city: "Moscow"
- "я живу в Queens" → detected_city: "Queens"
- "переехал в Miami" → detected_city: "Miami"
- "Бишкек" → detected_city: "Bishkek"
- "кафе рядом" → detected_city: null (нет конкретного города)
- Если города нет в тексте → detected_city: null

Классификация intent_type:
- "action" — пользователь хочет ВЫПОЛНИТЬ действие \
(запись расхода/дохода, отправка email, создание события, удаление, поиск, генерация отчёта)
- "chat" — приветствие, благодарность, общий разговор, \
информационный вопрос без конкретного действия
- "clarify" — сообщение НЕОДНОЗНАЧНО, confidence < 0.6, \
или подходит под 2+ интента одинаково. \
Верни топ-2 кандидата в clarify_candidates с описанием на русском.

Примеры intent_type:
"заправился на 50" → intent: "add_expense", intent_type: "action", confidence: 0.95
"привет, как дела?" → intent: "general_chat", intent_type: "chat", confidence: 0.95
"кофе" → intent: "track_drink", intent_type: "action", confidence: 0.85
"отправь" → intent_type: "clarify", confidence: 0.3, \
clarify_candidates: [{{"intent": "send_email", "label": "Отправить email", \
"confidence": 0.4}}, {{"intent": "draft_message", "label": "Написать сообщение", \
"confidence": 0.35}}]
"план" → intent_type: "clarify", confidence: 0.4, \
clarify_candidates: [{{"intent": "day_plan", "label": "План дня", \
"confidence": 0.45}}, {{"intent": "list_events", "label": "Расписание", \
"confidence": 0.35}}]
"удали" → intent_type: "clarify", confidence: 0.35, \
clarify_candidates: [{{"intent": "undo_last", "label": "Отменить транзакцию", \
"confidence": 0.4}}, {{"intent": "complete_task", "label": "Завершить задачу", \
"confidence": 0.3}}]
"запиши встречу с Петром в пятницу в 10" → intent: "create_event", \
intent_type: "action", confidence: 0.92

Ответь ТОЛЬКО валидным JSON:
{{
  "intent": "имя_интента",
  "confidence": 0.0-1.0,
  "intent_type": "action" или "chat" или "clarify",
  "clarify_candidates": [{{"intent": "...", "label": "описание на русском", \
"confidence": 0.0-1.0}}] или null,
  "data": {{
    "amount": число или null,
    "merchant": "название" или null,
    "category": "предполагаемая категория" или null,
    "scope": "business" или "family" или null,
    "date": "YYYY-MM-DD" или null,
    "description": "описание" или null,
    "currency": "валюта" или null,
    "period": "today" или "day" или "week" или "month" или "year" \
или "prev_week" или "prev_month" или "custom" или null,
    "date_from": "YYYY-MM-DD" или null,
    "date_to": "YYYY-MM-DD" или null,
    "tags": ["тег1", "тег2"] или null,
    "project": "название проекта" или null,
    "note": "текст заметки/идеи" или null,
    "reflection": "текст рефлексии" или null,
    "food_item": "что съел" или null,
    "meal_type": "breakfast" или "lunch" или "dinner" или "snack" или null,
    "drink_type": "кофе" или "чай" или "вода" или null,
    "drink_count": число или null,
    "drink_volume_ml": объём в мл или null,
    "mood": 1-10 или null,
    "energy": 1-10 или null,
    "stress": 1-10 или null,
    "sleep_hours": число часов или null,
    "tasks": ["задача1", "задача2"] или null,
    "comm_mode": "receipt" или "silent" или "coaching" или null,
    "search_query": "текст поиска" или null,
    "life_event_type": "food" или "drink" или "mood" или "task" \
или "reflection" или "note" или null,
    "task_title": "название задачи" или null,
    "task_deadline": "YYYY-MM-DDTHH:MM:SS" или null,
    "task_priority": "low" или "medium" или "high" или "urgent" или null,
    "reminder_recurrence": "daily" или "weekly" или "monthly" или null,
    "reminder_end_date": "YYYY-MM-DD" (конец повторений) или null,
    "search_topic": "тема поиска/вопроса" или null,
    "maps_query": "что искать на карте" или null,
    "maps_mode": "search" или "directions" или null,
    "destination": "пункт назначения для маршрута" или null,
    "youtube_query": "запрос для поиска видео" или null,
    "detail_mode": true если пользователь просит подробный список, больше результатов, \
маршрут с шагами, все видео, транскрипт — иначе false или null,
    "writing_topic": "тема/текст для написания" или null,
    "target_language": "целевой язык перевода" или null,
    "target_platform": "платформа для поста (google, instagram, etc.)" или null,
    "email_to": "адресат email" или null,
    "email_subject": "тема письма" или null,
    "email_body_hint": "подсказка для тела письма" или null,
    "event_title": "название события" или null,
    "event_datetime": "YYYY-MM-DDTHH:MM:SS" или null,
    "event_duration_minutes": число минут или null,
    "event_attendees": ["участник1"] или null,
    "shopping_items": ["товар1", "товар2"] или null,
    "shopping_list_name": "grocery" или "hardware" или название списка или null,
    "shopping_item_remove": "товар для удаления" или null,
    "booking_title": "название бронирования/услуги" или null,
    "booking_service_type": "тип услуги" или null,
    "booking_location": "адрес/место" или null,
    "booking_contact_role": "client" или "vendor" или "partner" или null,
    "contact_name": "имя контакта/клиента" или null,
    "contact_phone": "телефон" или null,
    "contact_email": "email" или null,
    "detected_city": "city name IN ENGLISH if user mentions a specific city" или null
  }},
  "response": "краткий ответ для пользователя"
}}"""


def _extract_delete_scope(text: str) -> str | None:
    """Infer delete_data scope from a destructive command text."""
    for keyword, scope in DELETE_SCOPE_KEYWORDS:
        if keyword in text:
            return scope
    return None


def _extract_period_hint(text: str) -> str | None:
    """Infer period from text if it is explicit."""
    for keyword, period in DELETE_PERIOD_KEYWORDS:
        if keyword in text:
            return period
    return None


def _looks_like_specific_life_entry(text: str) -> bool:
    """Detect whether user targets a specific life entry (not all records)."""
    if re.search(r"\d", text):
        return True
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:ml|мл|l|л)\b", text):
        return True
    markers = (
        "(",
        ")",
        "предыдущ",
        "конкретн",
        "эту запись",
        "this entry",
        "напиток",
        "заметку",
        "настроение",
        "вода",
        "кофе",
        "чай",
    )
    return any(marker in text for marker in markers)


def _rule_based_delete_intent(text: str) -> IntentDetectionResult | None:
    """Fast-path delete_data routing to avoid undo_last misclassification."""
    text_lower = text.lower().strip()
    if not text_lower:
        return None

    if not any(verb in text_lower for verb in DELETE_VERBS):
        return None

    scope = _extract_delete_scope(text_lower)
    if not scope:
        return None

    # Keep legacy "undo last transaction" behavior when explicitly requested.
    if scope in {"expenses", "income", "transactions"} and any(
        hint in text_lower for hint in UNDO_LAST_HINTS
    ):
        return None

    period = _extract_period_hint(text_lower)
    if not period and scope in LIFE_SCOPES and _looks_like_specific_life_entry(text_lower):
        period = "today"

    return IntentDetectionResult(
        intent="delete_data",
        confidence=0.96,
        intent_type="action",
        data=IntentData(delete_scope=scope, period=period),
        response=None,
    )


_PROGRAM_VERBS_RU = ("напиши", "создай", "сделай", "сгенерируй", "генерируй", "разработай")
_PROGRAM_VERBS_EN = ("write", "create", "make", "generate", "build", "develop", "code")
_PROGRAM_NOUNS_RU = (
    "программ", "скрипт", "код", "парсер", "бот", "калькулятор",
    "конвертер", "утилит", "автоматизаци", "генератор", "приложени",
    "игр", "сервис", "api", "сайт", "страниц",
)
_PROGRAM_NOUNS_EN = (
    "program", "script", "code", "parser", "bot", "calculator",
    "converter", "utility", "automation", "generator", "app",
    "game", "service", "api", "website", "page", "tool",
)


_MODIFY_VERBS_RU = ("измени", "исправь", "обнови", "доработай", "поменяй", "переделай")
_MODIFY_VERBS_EN = ("modify", "fix", "update", "change", "adjust", "tweak", "improve")
_MODIFY_NOUNS_RU = ("программ", "скрипт", "код", "функци", "приложени")
_MODIFY_NOUNS_EN = ("program", "script", "code", "function", "app")


def _rule_based_modify_program(text: str) -> IntentDetectionResult | None:
    """Fast-path modify_program for clear 'edit/fix the code' requests."""
    lower = text.lower().strip()
    if not lower:
        return None

    has_verb = any(v in lower for v in _MODIFY_VERBS_RU + _MODIFY_VERBS_EN)
    if not has_verb:
        return None

    has_noun = any(n in lower for n in _MODIFY_NOUNS_RU + _MODIFY_NOUNS_EN)
    if not has_noun:
        return None

    return IntentDetectionResult(
        intent="modify_program",
        confidence=0.97,
        intent_type="action",
        data=IntentData(program_changes=text.strip()),
        response=None,
    )


def _rule_based_generate_program(text: str) -> IntentDetectionResult | None:
    """Fast-path generate_program for clear 'write a program' requests."""
    lower = text.lower().strip()
    if not lower:
        return None

    has_verb = any(v in lower for v in _PROGRAM_VERBS_RU + _PROGRAM_VERBS_EN)
    if not has_verb:
        return None

    has_noun = any(n in lower for n in _PROGRAM_NOUNS_RU + _PROGRAM_NOUNS_EN)
    if not has_noun:
        return None

    # Extract description: everything after the verb+noun pattern
    description = lower
    for v in _PROGRAM_VERBS_RU + _PROGRAM_VERBS_EN:
        if v in description:
            idx = description.find(v) + len(v)
            description = description[idx:].strip()
            break

    # Strip leading noun if present (e.g., "программу калькулятор" → "калькулятор")
    for n in _PROGRAM_NOUNS_RU + _PROGRAM_NOUNS_EN:
        if description.startswith(n):
            after = description[len(n):].strip()
            if after:
                description = after
            break

    return IntentDetectionResult(
        intent="generate_program",
        confidence=0.97,
        intent_type="action",
        data=IntentData(program_description=text.strip()),
        response=None,
    )


@observe(name="detect_intent")
async def detect_intent(
    text: str,
    categories: list[dict] | None = None,
    language: str = "ru",
    recent_context: str | None = None,
) -> IntentDetectionResult:
    """Detect user intent using Gemini Flash (primary) with Claude Haiku fallback."""
    delete_fast_path = _rule_based_delete_intent(text)
    if delete_fast_path:
        return delete_fast_path

    modify_fast_path = _rule_based_modify_program(text)
    if modify_fast_path:
        return modify_fast_path

    program_fast_path = _rule_based_generate_program(text)
    if program_fast_path:
        return program_fast_path

    categories_str = ""
    if categories:
        categories_str = "\n".join(
            f"- {c.get('name', '')} ({c.get('scope', '')})" for c in categories
        )

    user_prompt = (
        f"Категории пользователя:\n{categories_str}\n\nСообщение: {text}"
        if categories_str
        else f"Сообщение: {text}"
    )

    if recent_context:
        user_prompt = f"Недавний контекст диалога:\n{recent_context}\n\n{user_prompt}"

    system_prompt = INTENT_DETECTION_PROMPT.format(today=date.today().isoformat())

    # Primary: Gemini Flash
    try:
        return await _detect_with_gemini(system_prompt, user_prompt, language)
    except Exception as e:
        logger.warning("Gemini intent detection failed: %s, falling back to Claude", e)

    # Fallback: Claude Haiku
    try:
        return await _detect_with_claude(system_prompt, user_prompt, language)
    except Exception as e:
        logger.error("Claude intent detection also failed: %s", e)
        return IntentDetectionResult(
            intent="general_chat",
            confidence=0.5,
            response="Не удалось определить намерение. Попробуйте переформулировать.",
        )


@observe(name="intent_gemini")
async def _detect_with_gemini(
    system_prompt: str, user_prompt: str, language: str
) -> IntentDetectionResult:
    client = google_client()
    response = await client.aio.models.generate_content(
        model="gemini-3-pro-preview",
        contents=f"{system_prompt}\n\nЯзык ответа: {language}\n\n{user_prompt}",
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(response.text)
    return IntentDetectionResult(**data)


@observe(name="intent_claude")
async def _detect_with_claude(
    system_prompt: str, user_prompt: str, language: str
) -> IntentDetectionResult:
    client = get_instructor_anthropic()
    result = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        response_model=IntentDetectionResult,
        max_retries=2,
        system=f"{system_prompt}\n\nЯзык ответа: {language}",
        messages=[{"role": "user", "content": user_prompt}],
    )
    return result


# ── Two-stage intent detection (Phase 1 scaffold) ─────────────────
# Activates when total registered intents exceed STAGE2_THRESHOLD.
# Stage 1: classify domain (Gemini Flash) → Stage 2: classify intent within domain.

STAGE2_THRESHOLD = 25

DOMAIN_CLASSIFICATION_PROMPT = """\
Classify the user's message into exactly one domain.

Domains:
- finance: expenses, income, receipts, budgets, reports, recurring payments
- email: inbox, send, reply, draft, follow-up
- calendar: events, schedule, meetings, free slots
- booking: client bookings, appointments, scheduling clients, CRM outreach
- tasks: to-do, reminders, deadlines, planning
- shopping: shopping lists, grocery lists, items to buy
- research: search, compare, analyze, investigate
- writing: draft, translate, proofread, compose
- contacts: people, CRM, follow-ups, add/find contacts
- general: life tracking, chat, mood, food, drinks, notes, reflections
- onboarding: setup, connect accounts, first use

Respond with JSON: {{"domain": "...", "confidence": 0.0-1.0}}
"""

DOMAIN_INTENT_PROMPTS: dict[str, str] = {
    "finance": "Finance domain intents — placeholder for Phase 2+ expansion.",
    "email": "Email domain intents — placeholder for Phase 2.",
    "calendar": "Calendar domain intents — placeholder for Phase 2.",
    "tasks": "Tasks domain intents — placeholder for Phase 3.",
    "shopping": "Shopping list intents — add, view, remove, clear items.",
    "research": "Research domain intents — placeholder for Phase 3.",
    "writing": "Writing domain intents — placeholder for Phase 3.",
    "contacts": "Contacts domain intents — placeholder for Phase 3.",
    "booking": "Booking domain intents — create/list/cancel/reschedule bookings, CRM.",
    "general": "General domain intents — placeholder for Phase 2+ expansion.",
    "onboarding": "Onboarding domain intents — placeholder.",
}


@observe(name="classify_domain")
async def _classify_domain(text: str, language: str = "ru") -> str:
    """Stage 1: classify message into a domain using Gemini Pro."""
    client = google_client()
    prompt = f"{DOMAIN_CLASSIFICATION_PROMPT}\n\nЯзык: {language}\n\nСообщение: {text}"
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-pro-preview",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
        return data.get("domain", "general")
    except Exception as e:
        logger.warning("Domain classification failed: %s, defaulting to general", e)
        return "general"


async def detect_intent_v2(
    text: str,
    categories: list[dict] | None = None,
    language: str = "ru",
) -> IntentDetectionResult:
    """Two-stage intent detection for >25 intents.

    Stage 1: classify domain (fast, cheap).
    Stage 2: classify intent within domain (focused prompt).

    Not yet active — will be enabled when intent count exceeds STAGE2_THRESHOLD.
    Currently falls through to single-stage detect_intent().
    """
    # Stage 1: classify domain
    domain = await _classify_domain(text, language)

    # Stage 2: for now, fall back to single-stage detection
    # In Phase 2+, each domain will have its own focused prompt
    result = await detect_intent(text=text, categories=categories, language=language)

    # Attach domain to result data
    if result.data:
        result.data.domain = domain

    return result
