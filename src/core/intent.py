import json
import logging
import re
from datetime import date

from src.core.llm.clients import get_instructor_anthropic, google_client
from src.core.observability import observe
from src.core.personalization import has_forget_command, strip_forget_command
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
"покажи итоги", "PDF", "сгенерируй отчёт", "месячный отчёт", \
"сделай pdf расходов", "pdf сканов расходов", "отчёт по расходам в pdf", \
"expense report pdf", "скачать отчёт", "выгрузи расходы")
- export_excel: экспорт данных в Excel (.xlsx) — расходы, задачи, контакты \
("экспорт в Excel", "export to Excel", "скачать в Excel", "download xlsx", \
"выгрузи расходы в таблицу", "excel expenses", "таблица расходов xlsx", \
"экспортируй задачи", "export contacts", "export transactions", \
"собери расходы в файл", "save expenses as excel"). \
Извлеки export_type: expenses/tasks/contacts (default: expenses), \
period: week/month/year, date_from/date_to: YYYY-MM-DD
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
- generate_invoice: создать счёт/инвойс/PDF для клиента ("invoice Mike for the job", \
"выставь счёт клиенту", "create invoice", "сделай инвойс", "сделай PDF инвойс", \
"generate invoice PDF", "PDF счёт для клиента", "generar factura PDF"). \
Извлеки contact_name: имя клиента, amount: общая сумма если указана, \
invoice_due_days: число дней (net 15 → 15)
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
- memory_show: показать воспоминания/память ("что ты обо мне знаешь?", \
"мои воспоминания", "my memories", "what do you remember about me?", "покажи память")
- memory_forget: забыть/удалить из памяти ("забудь что...", "удали память о...", \
"forget that...", "delete memory about...", "удали воспоминание")
- memory_save: запомнить явно ("запомни что...", "remember that...", \
"помни что я...", "save to memory", "сохрани в память")
- set_user_rule: установить правило/предпочтение для бота ("отвечай коротко", "без эмодзи", \
"пиши на русском", "зови себя Хюррем", "тебя зовут X", "запомни что ты Y", "твоё имя Z", \
"always respond in English", "no emoji", "keep it brief", "your name is X", "call yourself Y")
- dialog_history: вспомнить прошлые разговоры ("о чём мы говорили вчера?", \
"what did we discuss last week?", "какие идеи были?", "наша история разговоров")
- memory_update: обновить факт в памяти ("обнови мою зарплату", "change my city to X", \
"теперь мой город — Y", "update my occupation")
- set_project: переключить контекст на проект ("это про Титан", "переключись на проект X", \
"work on project Y", "switch to project Z", "про проект Stridos")
- create_project: создать новый проект ("создай проект X", "новый проект для Y", \
"start project called Z", "заведи проект")
- list_projects: список проектов пользователя ("мои проекты", "список проектов", \
"what projects do I have", "покажи проекты")
- create_task: создать задачу/дело ("add task: ...", "задача: ...", \
"to-do: ...", "добавь в список: ...", "нужно сделать: ...")
- list_tasks: показать список задач ("мои задачи", "что мне нужно сделать", \
"my tasks", "список дел", "what's on my list")
- set_reminder: установить напоминание ("remind me ...", "напомни ...", \
"напоминание: ...", "remind me to pick up Emma at 3:15", \
"напоминай каждый день в 5 утра", "daily reminder at 7pm", \
"напоминание каждую неделю"). Поддерживает повторяющиеся напоминания (daily/weekly/monthly).
- schedule_action: запланировать AI-сводку/автодействие \
("every day at 8 send me calendar and tasks", \
"каждое утро в 8 отправляй сводку по задачам и календарю", \
"programa un resumen semanal con tareas y finanzas", \
"remind me every day until done", "каждый день до выполнения"). \
Извлеки schedule_frequency, schedule_time, schedule_day_of_week, \
schedule_sources, schedule_instruction, schedule_output_mode, \
schedule_action_kind, schedule_completion_condition.
- list_scheduled_actions: показать запланированные действия \
("my scheduled actions", "мои запланированные", "show automations", \
"что запланировано", "mis acciones programadas", "what's scheduled")
- manage_scheduled_action: управление запланированным действием — пауза/возобновление/удаление \
или ИЗМЕНЕНИЕ параметров (время, источники, текст) \
("pause my morning brief", "resume daily summary", "удали расписание", \
"добавь почту в утренний отчет", "убери финансы из сводки", \
"измени текст напоминания на 'проверь баланс'"). \
Извлеки managed_action_title, manage_operation (pause/resume/delete/reschedule/modify), \
added_sources, removed_sources, new_instruction.
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
- youtube_search: поиск видео на YouTube или TikTok, инструкции, обзоры товаров ("найди видео", \
"инструкция по замене масла Toyota", "обзор iPhone на youtube", \
"tutorial for X", "how to fix X video", "youtube video about", "tiktok видео"). \
ТАКЖЕ: если пользователь отправил ссылку YouTube (youtube.com/watch, youtu.be/, \
youtube.com/shorts/) или TikTok (tiktok.com/, vm.tiktok.com/, vt.tiktok.com/) \
— это ВСЕГДА youtube_search, даже без слова "youtube" или "tiktok"
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
"переведи в формат xlsx", "конвертируй в epub", "convertir a PDF", "cambiar formato"). \
Извлеки target_format: целевой формат (pdf, docx, xlsx, txt, csv, html, md, \
epub, mobi, fb2, rtf, odt, ods, xls, pptx, jpg, png, tiff)
- list_documents: показать сохранённые документы ("мои документы", "my documents", \
"покажи документы", "list documents", "все документы", "какие документы есть", \
"mis documentos", "mostrar documentos")
- search_documents: поиск по содержимому документов ("найди в документах", \
"search documents for", "найди контракт", "где тот инвойс", "поиск документов", \
"buscar en documentos", "buscar contrato"). \
Извлеки search_query: текст поиска
- extract_table: извлечь таблицу из документа или фото ("извлечь таблицу", \
"extract table", "данные из таблицы", "таблицу из PDF", "parse this table", \
"extraer tabla", "tabla del documento")
- generate_invoice_pdf: DEPRECATED — use generate_invoice instead
- fill_template: заполнить шаблон документа ("заполни шаблон", "fill template", \
"заполни договор данными", "fill this template with my info", \
"llenar plantilla", "completar plantilla"). \
Извлеки template_name: название шаблона если упомянуто
- fill_pdf_form: заполнить PDF-форму ("заполни PDF форму", "fill this PDF form", \
"заполни W-9", "fill out this form", "llenar formulario PDF")
- analyze_document: проанализировать/изучить документ, задать вопрос по документу \
("проанализируй этот документ", "изучи документ", "изучить", "рассмотри файл", \
"analyze this document", "какие риски в контракте?", "что в этом документе?", \
"what's the payment term?", "вопрос по документу", "analizar documento", \
"analizar este documento", "посмотри документ", "разбери этот файл"). \
Извлеки analysis_question: конкретный вопрос пользователя
- merge_documents: объединить несколько PDF ("объедини PDF", "merge these PDFs", \
"склей документы", "combine PDFs into one", "combinar PDFs", "unir documentos")
- pdf_operations: операции с PDF — разделить, повернуть, зашифровать, расшифровать, \
водяной знак, извлечь страницы ("раздели PDF", "split PDF", "повернуть страницу", \
"rotate page", "зашифруй PDF", "encrypt PDF", "добавь водяной знак", "watermark", \
"извлеки страницы 3-7", "extract pages", "dividir PDF", "rotar pagina", \
"cifrar PDF"). \
Извлеки pdf_operation: split/rotate/encrypt/decrypt/watermark/extract_pages, \
pdf_pages: диапазон страниц, pdf_password: пароль если указан
- generate_spreadsheet: создать НОВУЮ Excel-таблицу по описанию ("сделай таблицу в Excel", \
"create a spreadsheet", "generate Excel report", \
"crear hoja de calculo", "generar tabla Excel"). \
НЕ для экспорта реальных данных — для этого используй export_excel
- compare_documents: сравнить документы ("сравни эти документы", "compare documents", \
"что изменилось в контракте?", "разница между версиями", "comparar documentos", \
"diferencias entre versiones")
- summarize_document: резюме документа ("кратко перескажи", "summarize this document", \
"резюме контракта", "summary of this PDF", "о чём этот документ?", \
"resumir documento", "resumen de este PDF")
- generate_document: создать НОВЫЙ документ с нуля \
по описанию ("создай NDA", "generate a contract", \
"сделай прайс-лист", "create a price list", "напиши договор", "make a proposal", \
"crear contrato", "generar documento", "crear NDA"). \
НЕ для экспорта/выгрузки реальных данных (расходов, доходов) — для этого используй \
query_report (PDF) или export_excel (Excel). \
Извлеки document_description: описание документа, output_format: формат (pdf/docx)
- generate_presentation: создать презентацию ("сделай презентацию", \
"create a presentation about", "generate PPTX", "презентация расходов за квартал", \
"crear presentacion", "generar presentacion"). \
Извлеки presentation_topic: тема презентации
- read_sheets: прочитать данные из Google Sheets ("open my spreadsheet", \
"покажи таблицу", "read sheets", "данные из Google Sheets", "show spreadsheet data"). \
Извлеки sheet_url: URL или ID таблицы, sheet_range: диапазон (A1:D10)
- write_sheets: записать/обновить ячейки в Google Sheets ("update cell A1", \
"запиши в таблицу", "change value in sheets", "измени ячейку"). \
Извлеки sheet_url, sheet_range, sheet_data: данные для записи
- append_sheets: добавить строки в Google Sheets ("add row to spreadsheet", \
"добавь строку в таблицу", "log to sheets", "запиши новую строку"). \
Извлеки sheet_url, sheet_range, sheet_data
- create_sheets: создать новую Google Sheets таблицу ("create spreadsheet", \
"new sheet", "создай таблицу", "nueva hoja de cálculo")
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
- "каждый день/каждую неделю/каждый месяц" + "сводка/summary/дайджест/digest" \
или явный запрос "schedule/programar/запланируй" → schedule_action
- "my scheduled actions" / "что запланировано" / "мои запланированные" \
→ list_scheduled_actions
- "pause/resume/delete/reschedule" + контекст расписания \
("пауза утренняя сводка", "resume daily summary", "удали расписание") \
→ manage_scheduled_action
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
- Ссылка tiktok.com/, vm.tiktok.com/, vt.tiktok.com/ → youtube_search (ВСЕГДА, приоритет!)
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
    "schedule_frequency": "once" или "daily" или "weekly" или "monthly" \
или "weekdays" или "cron" или null,
    "schedule_time": "HH:MM" или null,
    "schedule_day_of_week": "monday"/"понедельник"/"lunes" или null,
    "schedule_day_of_month": число 1..31 или null,
    "schedule_sources": ["calendar", "tasks", "money_summary", \
"email_highlights", "outstanding"] или null,
    "schedule_instruction": "что включать в сводку" или null,
    "schedule_output_mode": "compact" или "decision_ready" или null,
    "schedule_action_kind": "digest" или "outcome" или null,
    "schedule_completion_condition": "empty"/"task_completed"/"invoice_paid" или null,
    "schedule_end_date": "YYYY-MM-DD" или null,
    "schedule_max_runs": число или null,
    "managed_action_title": "название запланированного действия" или null,
    "manage_operation": "pause" или "resume" или "delete" или "reschedule" или null,
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
    "target_format": "целевой формат конвертации (pdf, docx, xlsx, ...)" или null,
    "document_type": "фильтр типа документов (invoice, template, etc.)" или null,
    "template_name": "название шаблона" или null,
    "output_format": "формат результата (pdf, docx, xlsx)" или null,
    "analysis_question": "вопрос по документу" или null,
    "document_description": "описание генерируемого документа" или null,
    "pdf_operation": "split/rotate/encrypt/decrypt/watermark/extract_pages" или null,
    "pdf_pages": "диапазон страниц (1-3, 5, 7-9)" или null,
    "pdf_password": "пароль для шифрования/дешифрования PDF" или null,
    "presentation_topic": "тема презентации" или null,
    "sheet_url": "URL или ID Google Sheets таблицы" или null,
    "sheet_range": "диапазон ячеек (A1:D10)" или null,
    "sheet_data": "данные для записи/добавления" или null
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
    "январ": 1,
    "january": 1,
    "jan": 1,
    "феврал": 2,
    "february": 2,
    "feb": 2,
    "март": 3,
    "марта": 3,
    "march": 3,
    "mar": 3,
    "апрел": 4,
    "april": 4,
    "apr": 4,
    "ма": 5,
    "may": 5,
    "июн": 6,
    "june": 6,
    "jun": 6,
    "июл": 7,
    "july": 7,
    "jul": 7,
    "август": 8,
    "august": 8,
    "aug": 8,
    "сентябр": 9,
    "september": 9,
    "sep": 9,
    "октябр": 10,
    "october": 10,
    "oct": 10,
    "ноябр": 11,
    "november": 11,
    "nov": 11,
    "декабр": 12,
    "december": 12,
    "dec": 12,
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
    "программ",
    "скрипт",
    "код",
    "парсер",
    "бот",
    "калькулятор",
    "конвертер",
    "утилит",
    "автоматизаци",
    "генератор",
    "приложени",
    "игр",
    "сервис",
    "api",
    "сайт",
    "страниц",
)
_PROGRAM_NOUNS_EN = (
    "program",
    "script",
    "code",
    "parser",
    "bot",
    "calculator",
    "converter",
    "utility",
    "automation",
    "generator",
    "app",
    "game",
    "service",
    "api",
    "website",
    "page",
    "tool",
)

# Words that indicate the message is NOT a programming request
# (e.g., invoice line items mentioning "Website Development")
_PROGRAM_NEGATIVE_EN = (
    "invoice",
    "client name",
    "due date",
    "line item",
    "payment",
    "receipt",
    "booking",
    "reservation",
    "quantity",
    "unit price",
)
_PROGRAM_NEGATIVE_RU = (
    "инвойс",
    "счёт на оплату",
    "счет на оплату",
    "клиент:",
    "срок оплаты",
    "позиции",
    "оплата",
    "бронирован",
    "количество",
    "цена за единицу",
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

_PERSONALIZATION_PREFIXES = (
    "запомни:",
    "запомни,",
    "запомни ",
    "remember that ",
    "remember: ",
    "remember ",
    "save this: ",
)

_QUESTION_NAME_PATTERNS = (
    "как тебя зовут",
    "как вас зовут",
    "как меня зовут",
    "как твое имя",
    "как твоё имя",
    "как мое имя",
    "как моё имя",
    "какое у тебя имя",
    "какое твое имя",
    "какое твоё имя",
    "а как тебя зовут",
    "а как твое имя",
    "а как твоё имя",
    "ты знаешь мое имя",
    "ты знаешь моё имя",
    "ты помнишь мое имя",
    "ты помнишь моё имя",
    "ты помнишь как меня зовут",
    "ты знаешь как меня зовут",
    "знаешь мое имя",
    "помнишь мое имя",
    "помнишь как меня зовут",
    "what is your name",
    "what's your name",
    "what is my name",
    "what's my name",
    "do you know my name",
    "do you remember my name",
    "who are you",
)

_BOT_NAME_MARKERS = (
    "зови себя",
    "тебя зовут",
    "твоё имя",
    "твое имя",
    "your name is",
    "call yourself",
    "имя бота",
    "назовись",
)

_USER_NAME_MARKERS = (
    "меня зовут",
    "моё имя",
    "мое имя",
    "my name is",
    "i am ",
    "я —",
    "я -",
)

_RULE_MARKERS = (
    "отвечай",
    "говори",
    "пиши на",
    "пиши без",
    "без эмодзи",
    "без emoji",
    "на русском",
    "по-русски",
    "по английски",
    "по-английски",
    "коротко",
    "кратко",
    "always respond",
    "reply in",
    "keep it brief",
    "no emoji",
    "in english",
    "in russian",
)

_TRACK_DRINK_MARKERS = (
    "кофе",
    "coffee",
    "чай",
    "tea",
    "вода",
    "water",
    "сок",
    "juice",
    "смузи",
    "smoothie",
    "выпил",
    "пью",
    "drink",
)

_READ_INBOX_MARKERS = (
    "прочитай почту",
    "проверь почту",
    "моя почта",
    "мои письма",
    "входящие",
    "inbox",
    "check my email",
    "read my email",
    "read inbox",
)

_LIST_EVENTS_MARKERS = (
    "мои события",
    "что в календаре",
    "календар",
    "what's on my calendar",
    "what is on my calendar",
    "my calendar",
    "my schedule",
)

_LIST_BOOKINGS_MARKERS = (
    "покажи записи",
    "мои записи",
    "my bookings",
    "appointments today",
    "booking list",
)

_WRITE_POST_MARKERS = (
    "напиши пост",
    "write a post",
    "instagram caption",
    "caption for instagram",
    "ответ на отзыв",
    "review response",
)


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


def _rule_based_memory_forget(text: str) -> IntentDetectionResult | None:
    """Fast-path for direct forget/delete memory commands."""
    stripped = text.strip()
    if not stripped or not has_forget_command(stripped):
        return None
    lower = stripped.lower()
    scope = _extract_delete_scope(lower)
    if scope in {"expenses", "income", "transactions"} and any(
        hint in lower for hint in UNDO_LAST_HINTS
    ):
        return None
    target = strip_forget_command(stripped)
    if not target:
        return None
    return IntentDetectionResult(
        intent="memory_forget",
        confidence=0.95,
        intent_type="action",
        data=IntentData(memory_query=stripped),
        response=None,
    )


def _looks_like_money_message(text: str) -> bool:
    """Detect explicit money amounts so drink/food logs don't steal expense intents."""
    return bool(
        re.search(r"[$€£¥₽₸₹]\s*\d", text)
        or re.search(r"\b\d+(?:[.,]\d+)?\s*(?:usd|eur|rub|kzt|сом|руб|р\.?)\b", text)
    )


def _strip_personalization_prefix(text: str) -> str:
    """Drop leading 'remember/save' wrappers before personalization matching."""
    stripped = text.strip()
    lower = stripped.lower()
    for prefix in _PERSONALIZATION_PREFIXES:
        if lower.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


_NAME_REJECT_WORDS = frozenset({
    # Russian verbs and function words that appear in sentences, not names
    "зовут", "зови", "зовусь", "меня", "тебя", "твоё", "твое", "моё", "мое",
    "имя", "назови", "называй", "буду", "буду", "будет", "зовётся",
    # English equivalents
    "name", "call", "called", "my", "your", "is", "am",
})


def _looks_like_name(text: str) -> bool:
    """Heuristic: short human name reply without digits/punctuation noise.

    Returns True only for bare name strings like "Манас", "John Smith",
    "Мария-Иванова". Rejects full sentences like "Меня зовут Манас".
    """
    candidate = text.strip().strip(".,!?\"'")
    if not candidate or len(candidate) > 40:
        return False
    if any(ch.isdigit() for ch in candidate):
        return False
    parts = [part for part in re.split(r"[\s-]+", candidate) if part]
    if not parts or len(parts) > 3:
        return False
    # Reject if any part is a common verb/function word (not a name)
    lower_parts = {p.lower() for p in parts}
    if lower_parts & _NAME_REJECT_WORDS:
        return False
    return all(re.fullmatch(r"[A-Za-zА-Яа-яЁё]+", part) for part in parts)


def _recent_context_asks_user_name(recent_context: str | None) -> bool:
    """Detect if the bot just asked the user for their name."""
    if not recent_context:
        return False
    lower = recent_context.lower()
    ask_patterns = (
        "как тебя зовут",
        "как вас зовут",
        "how should i call you",
        "what should i call you",
        "what is your name",
        "скажи, пожалуйста: как тебя зовут",
        "как к тебе обращаться",
    )
    return any(pattern in lower for pattern in ask_patterns)


def _is_name_question(text: str) -> bool:
    """Detect if text asks about a saved name instead of setting one."""
    lower = text.lower().strip()
    name_markers = _QUESTION_NAME_PATTERNS + _BOT_NAME_MARKERS + _USER_NAME_MARKERS

    if any(pattern in lower for pattern in _QUESTION_NAME_PATTERNS):
        return True

    if lower.endswith("?") and any(marker in lower for marker in name_markers):
        return True

    question_starts = (
        "как ", "какое ", "какой ", "какая ", "что ", "кто ", "а как ",
        "what ", "who ", "how ", "do you ", "does ",
        "cómo ", "cuál ", "quién ", "cual ",
        "adın ne", "senin adın", "benim adım",
        "сенин атын", "менин атым",
        "сенің атың", "менің атым",
    )
    return any(lower.startswith(prefix) for prefix in question_starts) and any(
        marker in lower for marker in name_markers
    )


def _looks_like_personalization_rule(text: str) -> bool:
    """Only allow messages that explicitly look like persistent bot preferences."""
    from src.core.identity import is_valid_user_rule

    lower = text.lower().strip()
    if not lower:
        return False
    if any(marker in lower for marker in _BOT_NAME_MARKERS + _USER_NAME_MARKERS):
        return True
    if any(marker in lower for marker in _RULE_MARKERS):
        return is_valid_user_rule(text)
    return False


def _rule_based_track_drink(text: str) -> IntentDetectionResult | None:
    """Fast-path common drink logs so they skip the generic chat/tool path."""
    lower = text.lower().strip()
    if not lower or _looks_like_money_message(lower):
        return None
    if any(lower.startswith(prefix) for prefix in _PERSONALIZATION_PREFIXES):
        return None
    if not any(marker in lower for marker in _TRACK_DRINK_MARKERS):
        return None
    return IntentDetectionResult(
        intent="track_drink",
        confidence=0.96,
        intent_type="action",
        data=IntentData(),
        response=None,
    )


def _rule_based_read_inbox(text: str) -> IntentDetectionResult | None:
    """Fast-path direct inbox checks."""
    lower = text.lower().strip()
    if not lower or any(verb in lower for verb in ("отправь", "send ", "reply", "ответь")):
        return None
    has_inbox_marker = any(marker in lower for marker in _READ_INBOX_MARKERS)
    if "почт" in lower or "email" in lower or has_inbox_marker:
        return IntentDetectionResult(
            intent="read_inbox",
            confidence=0.96,
            intent_type="action",
            data=IntentData(),
            response=None,
        )
    return None


def _rule_based_list_events(text: str) -> IntentDetectionResult | None:
    """Fast-path direct calendar listing requests."""
    lower = text.lower().strip()
    if not lower:
        return None
    if any(marker in lower for marker in _LIST_BOOKINGS_MARKERS):
        return None
    if "расписан" in lower and any(word in lower for word in ("клиент", "запис", "booking")):
        return None
    if any(marker in lower for marker in _LIST_EVENTS_MARKERS) or (
        "расписан" in lower and not any(word in lower for word in ("клиент", "запис", "booking"))
    ):
        period = "week" if any(word in lower for word in ("недел", "week")) else "today"
        return IntentDetectionResult(
            intent="list_events",
            confidence=0.95,
            intent_type="action",
            data=IntentData(period=period),
            response=None,
        )
    return None


def _rule_based_list_bookings(text: str) -> IntentDetectionResult | None:
    """Fast-path booking schedule lookups."""
    lower = text.lower().strip()
    if not lower:
        return None
    if any(marker in lower for marker in _LIST_BOOKINGS_MARKERS):
        period = "week" if any(word in lower for word in ("недел", "week")) else "today"
        return IntentDetectionResult(
            intent="list_bookings",
            confidence=0.95,
            intent_type="action",
            data=IntentData(period=period),
            response=None,
        )
    return None


def _rule_based_write_post(text: str) -> IntentDetectionResult | None:
    """Fast-path common content-generation phrasing."""
    stripped = text.strip()
    lower = stripped.lower()
    if not stripped or _looks_like_personalization_rule(stripped):
        return None
    if not any(marker in lower for marker in _WRITE_POST_MARKERS):
        return None
    target_platform = "instagram" if "instagram" in lower else None
    return IntentDetectionResult(
        intent="write_post",
        confidence=0.96,
        intent_type="action",
        data=IntentData(writing_topic=stripped, target_platform=target_platform),
        response=None,
    )



def _rule_based_name_question(text: str) -> IntentDetectionResult | None:
    """Route direct name questions to chat so identity lookup can answer deterministically."""
    if not _is_name_question(text):
        return None
    return IntentDetectionResult(
        intent="general_chat",
        confidence=0.97,
        intent_type="chat",
        data=IntentData(),
        response=None,
    )



def _rule_based_memory_save(text: str) -> IntentDetectionResult | None:
    """Fast-path explicit remember/save commands before they fall into rule routing."""
    if has_forget_command(text):
        return None

    stripped = text.strip()
    normalized = _strip_personalization_prefix(text)
    if normalized == stripped or not normalized or _is_name_question(normalized):
        return None

    if _looks_like_personalization_rule(normalized):
        return IntentDetectionResult(
            intent="set_user_rule",
            confidence=0.98,
            intent_type="action",
            data=IntentData(rule_text=normalized),
            response=None,
        )

    return IntentDetectionResult(
        intent="memory_save",
        confidence=0.97,
        intent_type="action",
        data=IntentData(memory_query=normalized),
        response=None,
    )


def _rule_based_set_user_rule(
    text: str,
    recent_context: str | None = None,
) -> IntentDetectionResult | None:
    """Fast-path personalization so names/rules bypass ambiguous LLM routing."""
    if has_forget_command(text):
        return None

    normalized = _strip_personalization_prefix(text)
    if _is_name_question(normalized):
        return None

    if _recent_context_asks_user_name(recent_context) and _looks_like_name(normalized):
        bare_name = normalized.strip().strip(".,!?\"'")
        normalized = f"меня зовут {bare_name}"

    if _looks_like_personalization_rule(normalized):
        return IntentDetectionResult(
            intent="set_user_rule",
            confidence=0.98,
            intent_type="action",
            data=IntentData(rule_text=normalized),
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
    "минут": 1,
    "час": 60,
    "секунд": 1,
    "minute": 1,
    "hour": 60,
    "second": 1,
    "minuto": 1,
    "hora": 60,
    "segundo": 1,
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

    # Skip if text contains business/financial context markers
    if any(neg in lower for neg in _PROGRAM_NEGATIVE_EN + _PROGRAM_NEGATIVE_RU):
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
            after = description[len(n) :].strip()
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

    track_drink_fast_path = _rule_based_track_drink(text)
    if track_drink_fast_path:
        return track_drink_fast_path

    read_inbox_fast_path = _rule_based_read_inbox(text)
    if read_inbox_fast_path:
        return read_inbox_fast_path

    list_events_fast_path = _rule_based_list_events(text)
    if list_events_fast_path:
        return list_events_fast_path

    list_bookings_fast_path = _rule_based_list_bookings(text)
    if list_bookings_fast_path:
        return list_bookings_fast_path

    write_post_fast_path = _rule_based_write_post(text)
    if write_post_fast_path:
        return write_post_fast_path

    forget_fast_path = _rule_based_memory_forget(text)
    if forget_fast_path:
        return forget_fast_path

    name_question_fast_path = _rule_based_name_question(text)
    if name_question_fast_path:
        return name_question_fast_path

    memory_save_fast_path = _rule_based_memory_save(text)
    if memory_save_fast_path:
        return memory_save_fast_path

    rule_fast_path = _rule_based_set_user_rule(text, recent_context=recent_context)
    if rule_fast_path:
        return rule_fast_path

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
        model="gemini-3.1-flash-lite-preview",
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
        "add_income": 'запись дохода С СУММОЙ ("заработал 185", "получил оплату за рейс 2500")',
        "correct_category": 'исправление категории ("это не продукты, а бензин")',
        "undo_last": 'отмена последней операции ("отмени последнюю", "undo")',
        "set_budget": 'установить бюджет/лимит ("бюджет на продукты 30000")',
        "mark_paid": 'изменить статус на оплачен БЕЗ суммы ("груз оплачен", "mark paid")',
        "add_recurring": 'регулярный платёж ("подписка", "аренда 50000")',
        "delete_data": 'удаление данных ("удали расходы за январь")',
    },
    "analytics": {
        "query_stats": 'статистика ("сколько потратил за неделю")',
        "complex_query": 'сложный аналитический запрос ("анализ трат за 3 месяца")',
        "query_report": 'PDF-отчёт ("отчёт", "report", "месячный отчёт")',
        "export_excel": 'экспорт в Excel ("экспорт в Excel", "скачать xlsx", "export expenses")',
    },
    "finance_specialist": {
        "financial_summary": 'финансовый обзор по категориям ("куда уходят деньги?")',
        "generate_invoice": 'создать инвойс/PDF ("invoice Mike for the job", "invoice PDF")',
        "tax_estimate": 'оценка налогов ("quarterly taxes", "сколько налогов?")',
        "cash_flow_forecast": 'прогноз ("can we afford?", "forecast")',
    },
    "receipt": {
        "scan_receipt": "фото чека — распознать расход",
    },
    "tasks": {
        "create_task": 'создать задачу ("add task: ...", "задача: ...")',
        "list_tasks": 'показать задачи ("мои задачи", "my tasks")',
        "set_reminder": 'напоминание ("напомни ...", "remind me ...")',
        "schedule_action": 'запланировать AI-сводку ("every day at 8 send summary")',
        "list_scheduled_actions": 'показать запланированные действия ("my scheduled actions")',
        "manage_scheduled_action": 'пауза/возобновление/удаление/изменение источников или текста',
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
        "memory_show": 'показать воспоминания ("мои воспоминания", "what do you know")',
        "memory_forget": 'забыть из памяти ("забудь что...", "forget that...")',
        "memory_save": 'запомнить явно ("запомни что...", "remember that...")',
        "set_user_rule": 'правило для бота ("отвечай коротко", "зови себя X")',
        "dialog_history": 'прошлые разговоры ("о чём мы говорили?")',
        "memory_update": 'обновить факт в памяти ("обнови зарплату", "change my city")',
        "set_project": 'переключить на проект ("это про Титан", "work on project X")',
        "create_project": 'создать проект ("создай проект X", "start project called Y")',
        "list_projects": 'список проектов ("мои проекты", "what projects do I have")',
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
    },
    "document": {
        "scan_document": "фото документа, инвойса, rate confirmation",
        "convert_document": 'конвертировать файл ("конвертируй в PDF")',
        "list_documents": 'список документов ("мои документы", "покажи файлы")',
        "search_documents": 'поиск в документах ("найди в документах", "search invoices")',
        "extract_table": 'извлечь таблицу из документа ("вытащи таблицу")',
        "fill_template": 'заполнить шаблон документа ("заполни контракт", "fill template")',
        "fill_pdf_form": 'заполнить PDF форму ("заполни W-9", "fill form")',
        "analyze_document": 'анализ документа ("проанализируй документ", "какие риски?")',
        "merge_documents": 'объединить PDF ("merge PDFs", "объедини файлы")',
        "pdf_operations": 'операции с PDF ("раздели PDF", "зашифруй", "поверни")',
        "generate_spreadsheet": (
            'создать НОВУЮ Excel по описанию'
            ' (НЕ экспорт данных — export_excel)'
        ),
        "compare_documents": 'сравнить документы ("что изменилось?", "compare")',
        "summarize_document": 'резюме документа ("кратко по документу", "summarize")',
        "generate_document": (
            'создать НОВЫЙ документ с нуля'
            ' (НЕ экспорт данных — query_report/export_excel)'
        ),
        "generate_presentation": 'создать презентацию ("make presentation", "pptx")',
    },
    "sheets": {
        "read_sheets": 'прочитать Google Sheets ("покажи таблицу", "read sheets")',
        "write_sheets": 'записать в Google Sheets ("запиши в таблицу", "update cell")',
        "append_sheets": 'добавить строку ("add row to sheets", "добавь строку")',
        "create_sheets": 'создать таблицу ("create spreadsheet", "создай таблицу")',
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
- schedule_frequency: "once"/"daily"/"weekly"/"monthly"/"weekdays"/"cron" или null
- schedule_time: "HH:MM" или null
- schedule_day_of_week: "monday"/"понедельник"/"lunes" или null
- schedule_sources: список источников или null
- schedule_instruction: текст инструкции для сводки или null
- schedule_action_kind: "digest"/"outcome" или null
- schedule_completion_condition: "empty"/"task_completed"/"invoice_paid" или null
- managed_action_title: название запланированного действия или null
- manage_operation: "pause"/"resume"/"delete"/"reschedule" или null
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

    track_drink_fast_path = _rule_based_track_drink(text)
    if track_drink_fast_path:
        return track_drink_fast_path

    read_inbox_fast_path = _rule_based_read_inbox(text)
    if read_inbox_fast_path:
        return read_inbox_fast_path

    list_events_fast_path = _rule_based_list_events(text)
    if list_events_fast_path:
        return list_events_fast_path

    list_bookings_fast_path = _rule_based_list_bookings(text)
    if list_bookings_fast_path:
        return list_bookings_fast_path

    write_post_fast_path = _rule_based_write_post(text)
    if write_post_fast_path:
        return write_post_fast_path

    forget_fast_path = _rule_based_memory_forget(text)
    if forget_fast_path:
        return forget_fast_path

    name_question_fast_path = _rule_based_name_question(text)
    if name_question_fast_path:
        return name_question_fast_path

    memory_save_fast_path = _rule_based_memory_save(text)
    if memory_save_fast_path:
        return memory_save_fast_path

    rule_fast_path = _rule_based_set_user_rule(text, recent_context=recent_context)
    if rule_fast_path:
        return rule_fast_path

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
            domain,
            len(skills),
            text,
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
