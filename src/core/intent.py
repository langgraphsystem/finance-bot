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
- financial_summary: глубокий финансовый обзор, куда уходят деньги, \
анализ расходов по категориям ("куда уходят деньги?", "where does my money go?", \
"financial summary", "анализ расходов за месяц", "итоги по категориям", \
"покажи структуру расходов", "spending breakdown")
- generate_invoice: создать счёт/инвойс для клиента ("invoice Mike for the job", \
"выставь счёт клиенту", "create invoice", "сделай инвойс")
- tax_estimate: оценка налогов, квартальные платежи, вычеты ("сколько налогов?", \
"tax estimate", "quarterly taxes", "how much do I owe in taxes?", "налоговая оценка")
- cash_flow_forecast: прогноз денежного потока, можем ли позволить \
("can we afford summer camp?", "cash flow forecast", "прогноз расходов", \
"хватит ли денег на отпуск?", "forecast", "что будет через месяц с деньгами")
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
"зайди на сайт и заполни форму", "зайди на сайт и посмотри")
- browser_action: интерактивное действие на сайте, требующее авторизации — бронирование, \
покупка, заказ, оформление ("забронируй отель на booking.com", "купи билеты на aviasales", \
"закажи на Amazon", "book a flight on kayak.com", "order from Uber Eats", \
"submit order on Amazon", "book appointment online"). \
Извлеки browser_target_site: домен сайта, browser_task: что именно нужно сделать. \
Для запросов на бронирование отелей также извлеки: hotel_city (город на английском), \
hotel_check_in (YYYY-MM-DD), hotel_check_out (YYYY-MM-DD), hotel_guests (число, default 2), \
hotel_budget (число без валюты), hotel_platform (если указан конкретный сайт)
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
- receptionist: вопрос о бизнесе — услуги, цены, часы работы, FAQ \
("what services do you offer?", "какие услуги?", "сколько стоит маникюр?", \
"are you open on Saturday?", "часы работы", "what are your hours?", \
"do you have X service?", "есть ли у вас доставка?", "price list", "прайс"). \
Извлеки receptionist_topic: services / hours / faq / general
- delete_data: удаление данных за период или по типу ("удали расходы за январь", \
"очисти записи о еде за неделю", "delete my expenses for last month", \
"удали все данные за прошлый месяц", "сотри историю сообщений", \
"удали напоминание", "delete reminder"). \
Извлеки delete_scope: expenses/income/transactions/food/drinks/ \
mood/notes/life_events/tasks/shopping/messages/reminders/all
- generate_image: сгенерировать/создать/нарисовать фотографию или изображение по описанию \
("нарисуй кота в космосе", "generate a photo of sunset over mountains", \
"сделай картинку единорога", "create an image of a futuristic city", \
"сгенерируй фото", "нарисуй мне"). \
Извлеки image_prompt: полное описание изображения (на языке пользователя). \
ВАЖНО: generate_image — это ФОТОРЕАЛИСТИЧНЫЕ изображения или арт. \
generate_card — это ИНФОГРАФИКА, трекеры, чек-листы, карточки с данными.
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
- convert_document: конвертировать файл в другой формат ("конвертируй в PDF", \
"convert to docx", "в PDF", "save as PDF", "сделай PDF", "сохрани как docx", \
"переведи в формат xlsx", "конвертируй в epub"). \
Извлеки target_format: целевой формат (pdf, docx, xlsx, txt, csv, html, md, \
epub, mobi, fb2, rtf, odt, ods, xls, pptx, jpg, png, tiff)
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
- ВАЖНО для set_reminder: task_title = ДЕЙСТВИЕ (что сделать), НЕ время. \
Относительное время ("через N минут", "in N minutes") → вычисли task_deadline, \
а task_title = текст ПОСЛЕ времени. \
"напомни через 10 минут проверить духовку" → task_title: "проверить духовку", \
task_deadline: текущее время + 10 минут. \
"remind me in 15 minutes to check the oven" → task_title: "check the oven". \
"через 5 минут позвонить маме" → task_title: "позвонить маме"
- Голое "напомни" / "remind me" БЕЗ деталей → set_reminder, task_title: null, confidence: 0.9
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
- "забронируй/закажи/купи [на сайте]", "book/order/buy [on site]" → browser_action
- "зайди на сайт и посмотри/проверь", "go to website", "fill form" → web_action (read-only, no auth)
- "check price of X at Y", "сколько стоит X на сайте Y" → price_check (price lookup)
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
- "what services/prices/hours/FAQ" без запроса на бронирование → receptionist
- "book appointment" или с конкретным временем → create_booking (НЕ receptionist)

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

Правила извлечения location_specified (для maps_search):
- location_specified: true если пользователь указал КОНКРЕТНОЕ место, адрес, город, район, \
страну или достопримечательность в запросе maps_search
- "кафе в Бруклине" → true (город указан)
- "Times Square" → true (конкретное место)
- "маршрут от Бруклина до Манхэттена" → true (оба пункта указаны)
- "рестораны на Манхэттене" → true (район указан)
- "Eiffel Tower" → true (достопримечательность)
- "123 Main Street" → true (адрес)
- "кафе рядом" → false (нет конкретного места, только "рядом")
- "кафе" → false (место не указано)
- "найди гостиницу" → false (место не указано)
- "coffee near me" → false (только "near me", нет адреса)
- "ближайшая аптека" → false (нет конкретного места)
- Только для maps_search. Для других интентов → null

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
    "detected_city": "city name IN ENGLISH if user mentions a specific city" или null,
    "location_specified": true/false для maps_search (указано ли место/адрес/город), null иначе,
    "target_format": "целевой формат конвертации (pdf, docx, xlsx, ...)" или null
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


_MONTH_MAP: dict[str, int] = {
    "январ": 1, "january": 1, "jan": 1,
    "феврал": 2, "february": 2, "feb": 2,
    "март": 3, "марта": 3, "march": 3, "mar": 3,
    "апрел": 4, "april": 4, "apr": 4,
    "ма": 5, "may": 5,
    "июн": 6, "june": 6, "jun": 6,
    "июл": 7, "july": 7, "jul": 7,
    "август": 8, "august": 8, "aug": 8,
    "сентябр": 9, "september": 9, "sep": 9,
    "октябр": 10, "october": 10, "oct": 10,
    "ноябр": 11, "november": 11, "nov": 11,
    "декабр": 12, "december": 12, "dec": 12,
}


def _extract_specific_date(text: str) -> str | None:
    """Extract a specific date (e.g. '16 февраля 2026') from text. Returns ISO format."""
    # Pattern: "16 февраля 2026" or "16 февраля"
    m = re.search(r"(\d{1,2})\s+([а-яa-z]+)(?:\s+(\d{4}))?", text, re.IGNORECASE)
    if not m:
        return None
    day = int(m.group(1))
    month_text = m.group(2).lower()
    year = int(m.group(3)) if m.group(3) else date.today().year
    if day < 1 or day > 31:
        return None
    for prefix, month_num in _MONTH_MAP.items():
        if month_text.startswith(prefix):
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                return None
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
    specific_date = _extract_specific_date(text_lower) if not period else None
    is_specific = _looks_like_specific_life_entry(text_lower)
    if not period and not specific_date and scope in LIFE_SCOPES and is_specific:
        period = "today"

    data = IntentData(delete_scope=scope, period=period)
    if specific_date:
        data.date_from = specific_date
        data.date_to = specific_date
        data.period = "custom"

    return IntentDetectionResult(
        intent="delete_data",
        confidence=0.96,
        intent_type="action",
        data=data,
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


_BARE_REMINDER_WORDS = {
    "напомни",
    "напоминай",
    "напоминание",
    "remind",
    "remind me",
    "reminder",
    "set reminder",
    "set a reminder",
    "recuérdame",
    "recordatorio",
}


def _rule_based_bare_reminder(text: str) -> IntentDetectionResult | None:
    """Fast-path: bare 'напомни' / 'remind me' without details → set_reminder with no title."""
    if text.lower().strip() in _BARE_REMINDER_WORDS:
        return IntentDetectionResult(
            intent="set_reminder",
            confidence=0.95,
            intent_type="action",
            data=IntentData(),
            response=None,
        )
    return None


# Relative time reminder patterns: extract action + compute deadline
_RELATIVE_TIME_PATTERNS = [
    # RU: "напомни через N минут/часов X"
    re.compile(
        r"^(?:напомни(?:те)?)\s+через\s+(\d+)\s+(минут\w*|час\w*|секунд\w*)\s+(.+)",
        re.IGNORECASE,
    ),
    # EN: "remind me in N minutes/hours to X"
    re.compile(
        r"^remind\s+me\s+in\s+(\d+)\s+(minute|hour|second)s?\s+(?:to\s+)?(.+)",
        re.IGNORECASE,
    ),
    # ES: "recuérdame en N minutos/horas X"
    re.compile(
        r"^recuérdame\s+en\s+(\d+)\s+(minuto|hora|segundo)s?\s+(.+)",
        re.IGNORECASE,
    ),
]

_TIME_UNIT_MINUTES = {
    "минут": 1, "час": 60, "секунд": 1,
    "minute": 1, "hour": 60, "second": 1,
    "minuto": 1, "hora": 60, "segundo": 1,
}


def _rule_based_relative_reminder(text: str) -> IntentDetectionResult | None:
    """Fast-path: 'напомни через 10 минут X' / 'remind me in 15 minutes to X'."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    stripped = text.strip()
    for pattern in _RELATIVE_TIME_PATTERNS:
        m = pattern.match(stripped)
        if not m:
            continue
        amount = int(m.group(1))
        unit_raw = m.group(2).lower()
        action = m.group(3).strip()
        if not action:
            continue

        # Determine minutes multiplier
        multiplier = 1
        for prefix, mins in _TIME_UNIT_MINUTES.items():
            if unit_raw.startswith(prefix):
                multiplier = mins
                break
        total_minutes = amount * multiplier

        # Compute deadline (UTC+3 fallback; actual timezone applied in handler)
        try:
            now = datetime.now(ZoneInfo("UTC"))
        except Exception:
            now = datetime.utcnow()
        deadline = now + timedelta(minutes=total_minutes)
        deadline_iso = deadline.replace(microsecond=0).isoformat()

        return IntentDetectionResult(
            intent="set_reminder",
            confidence=0.97,
            intent_type="action",
            data=IntentData(task_title=action, task_deadline=deadline_iso),
            response=None,
        )
    return None


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

    relative_reminder = _rule_based_relative_reminder(text)
    if relative_reminder:
        return relative_reminder

    bare_reminder = _rule_based_bare_reminder(text)
    if bare_reminder:
        return bare_reminder

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


# ── Two-stage intent detection (Supervisor + Scoped Prompts) ────────
# Stage 1: keyword-based domain resolution (zero LLM cost) via supervisor.
# Stage 2: scoped intent detection with only the domain's intents (~2K tokens).
# Fallback: full INTENT_DETECTION_PROMPT when domain cannot be resolved (~10K tokens).

# Per-domain compact intent descriptions for scoped prompts.
# Each domain lists only its own intents + general_chat fallback.
# ~500-2K tokens per domain vs ~10K for the full prompt.
SCOPED_INTENT_DEFS: dict[str, dict[str, str]] = {
    "finance": {
        "add_expense": 'запись расхода ("заправился на 50", "купил продукты 87.50")',
        "add_income": "запись дохода С СУММОЙ "
        '("заработал 185", "получил оплату за рейс 2500")',
        "correct_category": 'исправление категории ("это не продукты, а бензин")',
        "undo_last": 'отмена последней операции ("отмени последнюю", "undo")',
        "set_budget": 'установить бюджет/лимит ("бюджет на продукты 30000")',
        "mark_paid": "изменить статус на оплачен БЕЗ суммы "
        '("груз оплачен", "mark paid")',
        "add_recurring": 'регулярный платёж ("подписка", "аренда 50000")',
        "delete_data": 'удаление данных ("удали расходы за январь")',
    },
    "analytics": {
        "query_stats": 'статистика ("сколько потратил за неделю")',
        "complex_query": 'сложный аналитический запрос ("анализ трат за 3 месяца")',
        "query_report": 'PDF-отчёт ("отчёт", "report", "месячный отчёт")',
        "financial_summary": 'финансовый обзор по категориям ("куда уходят деньги?")',
        "generate_invoice": 'создать инвойс ("invoice Mike for the job")',
        "tax_estimate": 'оценка налогов ("quarterly taxes", "сколько налогов?")',
        "cash_flow_forecast": 'прогноз ("can we afford?", "forecast")',
    },
    "receipt": {
        "scan_receipt": "фото чека — распознать расход",
        "scan_document": "фото документа, инвойса, rate confirmation",
    },
    "tasks": {
        "create_task": 'создать задачу ("add task: ...", "задача: ...")',
        "list_tasks": 'показать задачи ("мои задачи", "my tasks")',
        "set_reminder": 'напоминание ("напомни ...", "remind me ...")',
        "complete_task": 'отметить выполненной ("готово", "done with ...")',
        "shopping_list_add": 'добавить товары в список ("добавь молоко")',
        "shopping_list_view": 'показать список покупок ("мой список")',
        "shopping_list_remove": 'отметить купленное ("купил молоко")',
        "shopping_list_clear": 'очистить список ("очисти список")',
    },
    "life": {
        "quick_capture": 'заметка, идея ("идея: ...", "запомни: ...")',
        "track_food": 'запись еды БЕЗ суммы ("съел пиццу", "обед: суп")',
        "track_drink": 'напиток БЕЗ суммы ("кофе", "вода", "2 кофе")',
        "mood_checkin": 'чек-ин состояния ("настроение 7", "устал")',
        "day_plan": 'план дня ("план: ...", "топ задача: ...")',
        "day_reflection": 'рефлексия дня ("итоги дня", "review")',
        "life_search": 'поиск по памяти ("что я ел вчера?", "идеи за неделю")',
        "set_comm_mode": 'режим общения ("тихий режим", "coaching")',
        "evening_recap": 'вечерний обзор ("evening recap", "итоги дня")',
        "price_alert": 'мониторинг цены ("мониторь цену", "alert when price")',
        "news_monitor": 'мониторинг новостей ("следи за новостями")',
    },
    "email": {
        "read_inbox": 'проверить почту ("check email", "проверь почту")',
        "send_email": 'отправить email ("email John about meeting")',
        "draft_reply": 'ответить на письмо ("reply to email")',
        "follow_up_email": 'неотвеченные письма ("any unanswered emails?")',
        "summarize_thread": 'пересказать переписку ("summarize thread")',
    },
    "calendar": {
        "list_events": 'расписание ("what\'s on my calendar?", "расписание")',
        "create_event": 'создать событие ("schedule meeting at 3pm")',
        "find_free_slots": 'свободное время ("when am I free?")',
        "reschedule_event": 'перенести событие ("move dentist to Thursday")',
        "morning_brief": 'утренняя сводка ("morning brief")',
    },
    "research": {
        "quick_answer": 'фактический вопрос ("what\'s the capital of France?")',
        "web_search": 'поиск в интернете ("what time does Costco close?")',
        "compare_options": 'сравнение ("compare PEX vs copper")',
        "maps_search": 'поиск мест ("кафе рядом", "directions to Walmart")',
        "youtube_search": 'поиск видео ("найди видео", YouTube ссылка)',
        "price_check": 'проверить цену ("check price at Home Depot")',
        "web_action": 'действие на сайте ("зайди на сайт и посмотри")',
        "browser_action": 'бронирование/покупка через браузер ("закажи на Amazon")',
    },
    "writing": {
        "draft_message": 'написать сообщение ("write email to school")',
        "translate_text": 'перевести ("translate to Spanish")',
        "write_post": 'написать пост ("write review response")',
        "proofread": 'проверить текст ("proofread this")',
        "generate_image": 'сгенерировать изображение ("нарисуй кота")',
        "generate_card": 'создать карточку/трекер ("сделай трекер")',
        "generate_program": 'написать программу ("напиши парсер")',
        "modify_program": 'изменить программу ("измени программу")',
        "convert_document": 'конвертировать файл ("конвертируй в PDF")',
    },
    "booking": {
        "create_booking": 'записать клиента ("book John tomorrow 2pm")',
        "list_bookings": 'расписание бронирований ("my bookings today")',
        "cancel_booking": 'отменить ("cancel appointment")',
        "reschedule_booking": 'перенести запись ("move John to Thursday")',
        "add_contact": 'добавить контакт ("add client John 917-555-1234")',
        "list_contacts": 'список контактов ("my contacts")',
        "find_contact": 'найти контакт ("find John")',
        "send_to_client": 'написать клиенту ("text John I\'m running late")',
        "receptionist": 'вопрос о бизнесе: услуги, цены, часы ("what services?", "часы работы")',
    },
    "onboarding": {
        "onboarding": "команда /start или просьба зарегистрироваться",
        "general_chat": "приветствие, благодарность, общий разговор",
    },
}

# Data extraction rules shared across all scoped prompts.
# Kept compact — covers only universal fields; domain-specific fields
# are extracted best-effort by the LLM.
_SCOPED_DATA_RULES = """\
Извлеки данные в поле "data":
- amount: число или null
- merchant: название или null
- category: категория или null
- date: "YYYY-MM-DD" или null (не подставляй сегодня)
- description: описание или null
- period: "today"/"week"/"month"/"year"/"prev_month"/"prev_week"/"custom" или null
- date_from/date_to: "YYYY-MM-DD" для custom периода или null
- task_title: название задачи или null
- task_deadline: "YYYY-MM-DDTHH:MM:SS" или null
- reminder_recurrence: "daily"/"weekly"/"monthly" или null
- search_query/search_topic: текст поиска или null
- Остальные поля: извлеки если релевантны

Сегодня: {today}"""

_SCOPED_PROMPT_TEMPLATE = """\
Определи намерение пользователя из сообщения.
Домен: {domain_name}

Возможные интенты:
{intent_list}
- general_chat: общий разговор, если ни один интент не подходит

{data_rules}

Классификация intent_type:
- "action" — пользователь хочет выполнить действие
- "chat" — приветствие, благодарность, общий разговор
- "clarify" — сообщение неоднозначно, confidence < 0.6

Ответь ТОЛЬКО валидным JSON:
{{"intent": "имя_интента", "confidence": 0.0-1.0, \
"intent_type": "action"/"chat"/"clarify", \
"clarify_candidates": [{{"intent": "...", "label": "описание", \
"confidence": 0.0-1.0}}] или null, \
"data": {{...}}, "response": "краткий ответ"}}"""


def _build_scoped_prompt(domain: str, intents: list[str]) -> str:
    """Build a compact intent detection prompt for a single domain.

    Uses ~500-2K tokens instead of ~10K for the full prompt.
    """
    domain_defs = SCOPED_INTENT_DEFS.get(domain, {})
    lines = []
    for intent_name in intents:
        desc = domain_defs.get(intent_name)
        if desc:
            lines.append(f"- {intent_name}: {desc}")
        else:
            lines.append(f"- {intent_name}")

    return _SCOPED_PROMPT_TEMPLATE.format(
        domain_name=domain,
        intent_list="\n".join(lines),
        data_rules=_SCOPED_DATA_RULES.format(today=date.today().isoformat()),
    )


@observe(name="detect_intent_scoped")
async def detect_intent_scoped(
    text: str,
    domain: str,
    intents: list[str],
    categories: list[dict] | None = None,
    language: str = "ru",
    recent_context: str | None = None,
) -> IntentDetectionResult:
    """Scoped intent detection within a single domain.

    Uses a compact prompt with only the domain's intents (~2K tokens).
    """
    # Fast-path rules still apply
    delete_fast_path = _rule_based_delete_intent(text)
    if delete_fast_path:
        return delete_fast_path

    relative_reminder = _rule_based_relative_reminder(text)
    if relative_reminder:
        return relative_reminder

    bare_reminder = _rule_based_bare_reminder(text)
    if bare_reminder:
        return bare_reminder

    modify_fast_path = _rule_based_modify_program(text)
    if modify_fast_path:
        return modify_fast_path

    program_fast_path = _rule_based_generate_program(text)
    if program_fast_path:
        return program_fast_path

    system_prompt = _build_scoped_prompt(domain, intents)

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

    # Primary: Gemini Pro (same as full detection)
    try:
        result = await _detect_with_gemini(system_prompt, user_prompt, language)
        if result.data:
            result.data.domain = domain
        return result
    except Exception as e:
        logger.warning("Scoped Gemini detection failed: %s, falling back to Claude", e)

    # Fallback: Claude Haiku
    try:
        result = await _detect_with_claude(system_prompt, user_prompt, language)
        if result.data:
            result.data.domain = domain
        return result
    except Exception as e:
        logger.error("Scoped Claude detection also failed: %s", e)
        return IntentDetectionResult(
            intent="general_chat",
            confidence=0.3,
            intent_type="chat",
        )


async def detect_intent_v2(
    text: str,
    categories: list[dict] | None = None,
    language: str = "ru",
    recent_context: str | None = None,
) -> IntentDetectionResult:
    """Two-stage intent detection using supervisor + scoped prompts.

    Stage 1: keyword-based domain resolution (zero LLM cost).
    Stage 2: scoped intent detection within domain (~2K tokens).
    Fallback: full INTENT_DETECTION_PROMPT if domain not resolved (~10K tokens).
    """
    from src.core.supervisor import resolve_domain_and_skills

    # Stage 1: resolve domain via keyword triggers (no LLM call)
    domain, skills = resolve_domain_and_skills(text)

    if domain and skills:
        logger.info(
            "Supervisor resolved domain=%s (%d skills) for: %.60s",
            domain, len(skills), text,
        )
        # Stage 2: scoped intent detection
        result = await detect_intent_scoped(
            text=text,
            domain=domain,
            intents=skills,
            categories=categories,
            language=language,
            recent_context=recent_context,
        )
        # Verify the detected intent is in the expected skill set
        if result.intent not in skills and result.intent != "general_chat":
            logger.warning(
                "Scoped detection returned intent=%s outside domain=%s, "
                "falling back to full detection",
                result.intent,
                domain,
            )
            # Detected intent doesn't match domain — fall back to full detection
            result = await detect_intent(
                text=text,
                categories=categories,
                language=language,
                recent_context=recent_context,
            )
        return result

    # Fallback: full detection when supervisor can't resolve domain
    logger.debug("Supervisor could not resolve domain, using full detection for: %.60s", text)
    return await detect_intent(
        text=text,
        categories=categories,
        language=language,
        recent_context=recent_context,
    )
