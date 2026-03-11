# Finance Bot — Полный анализ возможностей

> Дата: 2026-03-09 | Скиллов: 99 | Агентов: 13 | Оркестраторов: 4 | Каналов: 4

---

## 1. ФИНАНСЫ (Finance Agent + Analytics + Finance Specialist)

### Что ЕСТЬ

| Функция | Скилл | Статус | Детали |
|---------|-------|--------|--------|
| Добавление расходов | `add_expense` | ✅ | Кнопки подтверждения, бюджет-чек, мерчант-маппинг, RBAC `create_finance` |
| Добавление доходов | `add_income` | ✅ | Кнопки confirm/cancel, RBAC `create_finance` |
| Установка бюджета | `set_budget` | ✅ | По категории, weekly/monthly, RBAC `manage_budgets` |
| Регулярные платежи | `add_recurring` | ✅ | weekly/monthly/quarterly/yearly |
| Отметить оплату | `mark_paid` | ✅ | Обновление статуса транзакции |
| Коррекция категории | `correct_category` | ✅ | Fuzzy matching (порог 0.6), обучение мерчант-маппинга |
| Отмена последнего | `undo_last` | ✅ | Redis TTL 120s, чистит Mem0 факты |
| Удаление данных | `delete_data` | ✅ | AI-поиск + confirmation flow, rule-specific deletion |
| Статистика | `query_stats` | ✅ | Период, тренды, pie chart, сравнение с пред. периодом |
| Сложные запросы | `complex_query` | ✅ | Graph Agent, pie chart, рекомендации |
| PDF-отчёты | `query_report` | ✅ | WeasyPrint, таблицы/графики |
| Excel-экспорт | `export_excel` | ✅ | expenses/tasks/contacts, openpyxl, summary sheet |
| Финансовый обзор | `financial_summary` | ✅ | Период, категории, top merchants, тренды, pie chart |
| Генерация инвойса | `generate_invoice` | ✅ | Workflow с подтверждением |
| Налоговая оценка | `tax_estimate` | ✅ | Income vs expense, bracket estimation |
| Прогноз cash flow | `cash_flow_forecast` | ✅ | 30/60/90 дней, recurring, тренды (мин. 14 дней истории) |
| Сканирование чеков | `scan_receipt` | ✅ | Gemini Vision OCR, merchant/category extraction |
| Mini App CRUD | `/api/transactions` | ✅ | GET/POST/PUT/DELETE + stats + CSV export |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Schedule C / IFTA export | ❌ Не реализовано |
| Per diem tracking | ❌ Не реализовано |
| Annual tax package | ❌ Не реализовано |
| Google Sheets bidirectional sync | ⚠️ Частично (sheets_sync task есть) |
| Accountant read-only role | ❌ Не реализовано |
| Telegram Stars монетизация | ❌ Не реализовано |
| `generate_invoice_pdf` | ⚠️ Папка есть, но deprecated, не в registry |
| `weekly_digest` | ⚠️ Папка + тесты есть, но не в registry |

---

## 2. ДОКУМЕНТЫ (Document Agent — 19 скиллов)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Сканирование документов | `scan_document` | Gemini Vision OCR, multi-page |
| Конвертация (20+ форматов) | `convert_document` | Batch via Redis, ZIP, 20MB max |
| Список документов | `list_documents` | По metadata |
| Поиск документов | `search_documents` | pg_trgm GIN + pgvector hybrid semantic search |
| Извлечение таблиц | `extract_table` | CSV/JSON output |
| Шаблоны (DOCX/XLSX) | `fill_template` | docxtpl/openpyxl, template library (save/list/delete) |
| Заполнение PDF-форм | `fill_pdf_form` | pypdf |
| Анализ документов | `analyze_document` | Dual: vision (images) + text (PDFs), i18n |
| Объединение документов | `merge_documents` | Multi-file Redis queue |
| PDF-операции | `pdf_operations` | split/rotate/encrypt/decrypt (pypdf) |
| Генерация таблиц | `generate_spreadsheet` | E2B + openpyxl fallback |
| Сравнение документов | `compare_documents` | Text extraction + Claude diff |
| Резюмирование | `summarize_document` | Multi-page, token-aware truncation |
| Генерация документов | `generate_document` | Contracts/NDAs, Claude + WeasyPrint |
| Презентации | `generate_presentation` | E2B + python-pptx fallback |
| Google Sheets чтение | `read_sheets` | Range, multi-sheet, OAuth |
| Google Sheets запись | `write_sheets` | С confirm/edit кнопками |
| Google Sheets append | `append_sheets` | OAuth required |
| Создание Sheets | `create_sheets` | С hyperlink на созданный документ |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| OCR handwritten text (рукописный) | ❌ Не специализирован |
| Watermark добавление | ⚠️ Trigger есть, отдельного скилла нет |
| Batch PDF operations | ❌ Только single-file per operation |
| Document versioning UI | ❌ Версии в БД есть, но нет UI |

---

## 3. ЗАДАЧИ И НАПОМИНАНИЯ (Tasks Agent — 11 скиллов)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Создание задачи | `create_task` | Priority, deadline, visibility |
| Список задач | `list_tasks` | Фильтр по статусу/приоритету |
| Напоминание | `set_reminder` | Timezone-aware, проверка каждую минуту |
| Запланировать действие | `schedule_action` | Cron-like scheduling |
| Список запланированных | `list_scheduled_actions` | По статусу |
| Управление запланированными | `manage_scheduled_action` | Update/cancel |
| Завершение задачи | `complete_task` | Fuzzy matching, remaining count |
| Список покупок: добавить | `shopping_list_add` | Multi-item |
| Список покупок: просмотр | `shopping_list_view` | Форматированный список |
| Список покупок: удалить | `shopping_list_remove` | По имени |
| Список покупок: очистить | `shopping_list_clear` | Полная очистка |
| Mini App CRUD | `/api/tasks`, `/api/shopping-list` | REST endpoints |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Subtasks / вложенные задачи | ❌ |
| Task dependencies (зависимости) | ❌ |
| Kanban board (Mini App) | ❌ |
| Recurring tasks (повторяющиеся) | ⚠️ Только через scheduled_action |
| Tags / labels для задач | ❌ |
| Task sharing между members | ❌ |

---

## 4. ЖИЗНЬ И WELLNESS (Life Agent — 20 скиллов)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Быстрая заметка | `quick_capture` | LifeEvent + async Mem0 enrichment |
| Трекинг еды | `track_food` | Calories estimation, macros |
| Трекинг напитков | `track_drink` | Water/coffee/tea/juice/alcohol, hydration |
| Настроение | `mood_checkin` | 1-10 шкала, кнопки выбора |
| План дня | `day_plan` | Task list parsing (lines/comma) |
| Рефлексия дня | `day_reflection` | LLM coaching tips |
| Поиск по жизни | `life_search` | Period filtering (today/week/month/year), кнопки |
| Режим общения | `set_comm_mode` | silent/receipt/coaching |
| Вечерний обзор | `evening_recap` | Parallel collectors, plugin sections |
| Алерт цены | `price_alert` | Keyword threshold monitoring |
| Монитор новостей | `news_monitor` | Keyword alerts |
| Показать память | `memory_show` | Mem0 domain search |
| Забыть память | `memory_forget` | Mem0 delete |
| Сохранить память | `memory_save` | Mem0 add |
| Обновить память | `memory_update` | Mem0 update |
| Правила пользователя | `set_user_rule` | Persistent rules → Layer 0 identity |
| История диалогов | `dialog_history` | SessionSummary by period |
| Установить проект | `set_project` | Context switching |
| Создать проект | `create_project` | UserProject model |
| Список проектов | `list_projects` | All user projects |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Sleep tracking | ❌ Нет отдельного скилла |
| Exercise / workout tracking | ❌ |
| Habit tracker с streaks | ❌ |
| Weight tracking | ❌ |
| Water intake goals / прогресс | ❌ Нет визуализации |
| Calorie/macro goals и сравнение | ❌ |
| Health insights dashboard | ❌ Нет в Mini App |

---

## 5. ИССЛЕДОВАНИЕ (Research Agent — 9 скиллов)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Быстрый ответ | `quick_answer` | Gemini, без web search |
| Веб-поиск | `web_search` | Gemini Google Search Grounding |
| Сравнение опций | `compare_options` | Structured comparison (cost/quality) |
| Поиск на карте | `maps_search` | Dual-mode: Gemini Grounding / Maps Platform API |
| YouTube поиск | `youtube_search` | Dual-mode: Gemini / YouTube Data API v3 |
| Видео анализ | `video_action` | URL analysis via Gemini |
| Проверка цен | `price_check` | Real-time via Gemini |
| Веб-действие (простое) | `web_action` | Headless browser |
| Браузер-действие (сложное) | `browser_action` | Browser-Use + screenshots, hotel/taxi FSM |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| TikTok search | ⚠️ Trigger есть, реальной интеграции нет |
| Deep research с citations | ❌ Нет structured output |
| Saved searches / bookmarks | ❌ |
| Research history | ❌ |

---

## 6. ПИСЬМО И КОНТЕНТ (Writing Agent — 8 скиллов)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Драфт сообщения | `draft_message` | Tone-aware |
| Перевод | `translate_text` | Multi-language |
| Написание поста | `write_post` | LinkedIn/Instagram/Twitter tone |
| Проверка текста | `proofread` | LLM-based |
| Генерация изображений | `generate_image` | Gemini Image API, dual model fallback |
| Открытки | `generate_card` | Image generation |
| Генерация программ | `generate_program` | E2B execution + тесты |
| Модификация программ | `modify_program` | E2B execution |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Content calendar / scheduling | ❌ |
| Brand voice profiles | ❌ Используется user profile |
| Image editing / variations | ❌ |
| Video generation | ❌ |
| Multi-platform auto-posting | ❌ |

---

## 7. EMAIL (Email Agent — 5 скиллов + LangGraph Orchestrator)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Чтение inbox | `read_inbox` | Gmail, unread/important filter |
| Отправка email | `send_email` | HITL confirmation, LangGraph orchestrator |
| Драфт ответа | `draft_reply` | LangGraph: writer → reviewer (max 2 ревизии) |
| Follow-up | `follow_up_email` | Direct skill (bypass graph) |
| Резюме цепочки | `summarize_thread` | Thread context |

**LangGraph Email Orchestrator:**
```
START → planner → reader → writer → reviewer → approval (HITL interrupt) → finalizer → END
```

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Email templates / saved drafts | ❌ |
| Scheduled send | ❌ |
| Multi-account support | ❌ Только один Gmail |
| Attachment handling (полное) | ⚠️ Ограничено |
| Email rules / filters | ❌ |

---

## 8. КАЛЕНДАРЬ (Calendar Agent — 5 скиллов + LangGraph Brief)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Список событий | `list_events` | Google Calendar API |
| Создание события | `create_event` | Conflict check, confirmation flow |
| Свободные слоты | `find_free_slots` | Availability check |
| Перенос события | `reschedule_event` | Modification workflow |
| Утренний брифинг | `morning_brief` | LangGraph parallel collectors |

**LangGraph Brief Orchestrator:**
```
START ──┬── collect_calendar ──┐
        ├── collect_tasks ─────┤
        ├── collect_finance ───┼──► synthesize ──► END
        ├── collect_email ─────┤
        └── collect_outstanding┘
```

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Multi-calendar support | ❌ Только один Google Calendar |
| Recurring events creation | ❌ Через бот нет |
| Calendar sharing / collaboration | ❌ |
| Meeting scheduling с внешними людьми | ❌ |
| Time blocking | ❌ |

---

## 9. БРОНИРОВАНИЕ И CRM (Booking Agent — 9 скиллов + LangGraph)

### Что ЕСТЬ

| Функция | Скилл | Детали |
|---------|-------|--------|
| Создание записи | `create_booking` | Contact lookup, timezone |
| Список записей | `list_bookings` | Status + date filter |
| Отмена записи | `cancel_booking` | Fuzzy match |
| Перенос записи | `reschedule_booking` | Availability check |
| Добавить контакт | `add_contact` | Name/phone/email |
| Список контактов | `list_contacts` | Role filter |
| Поиск контакта | `find_contact` | Full-text search |
| Сообщение клиенту | `send_to_client` | Template-based messaging |
| Рецепционист | `receptionist` | Specialist config (services, staff, hours, FAQ) |

**LangGraph Booking Orchestrator:**
```
START → parse_request → preview_prices → ask_platform (interrupt)
    → check_auth → search → present_results (interrupt)
    → confirm_selection (interrupt) → execute_booking → finalize → END
```

**Поддерживаемые платформы:** booking.com, airbnb.com, hotels.com, expedia.com, agoda.com, ostrovok.ru

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Online payment integration | ❌ |
| WhatsApp/SMS уведомления клиентам | ❌ Только через бот |
| Waitlist / queue management | ❌ |
| Staff scheduling (полное) | ⚠️ Только specialist config |
| Client portal | ❌ |

---

## 10. ONBOARDING (2 скилла)

| Функция | Скилл | Детали |
|---------|-------|--------|
| Онбординг | `onboarding` | Multi-step, language/account, 9 capability categories |
| Общий чат | `general_chat` | Fallback для нераспознанных интентов |

---

## 11. ИНФРАСТРУКТУРА

### 11.1 Каналы связи

| Канал | Статус | Библиотека | Лимиты |
|-------|--------|------------|--------|
| **Telegram** | ✅ Primary | aiogram v3 | 4000 char, inline/reply keyboards |
| **Slack** | ✅ Implemented | Events API + Web API | Blocks, interactive buttons |
| **WhatsApp** | ✅ Implemented | Business Cloud API v21.0 | 4096 char, 3 button max |
| **SMS/Twilio** | ✅ Implemented | REST API | 1600 char, plain text only |

### 11.2 Безопасность

| Компонент | Детали |
|-----------|--------|
| **Rate Limiter** | 5 tiers: default 30/min, llm_heavy 10/min, browser 3/5min, doc_gen 5/5min, img_gen 5/5min |
| **Circuit Breaker** | 5 instances: mem0 (3 fails/30s), anthropic (3/60s), openai (3/60s), google (3/60s), redis (5/15s) |
| **Guardrails** | Claude Haiku safety check + personalization whitelist (partial) |
| **RBAC** | owner/member roles, permissions, visibility filters |
| **Data isolation** | family_id FK, PostgreSQL Row-Level Security |
| **Encryption** | Fernet для browser sessions (cookies in Supabase) |
| **Input validation** | Table whitelist (13), column validation, UUID coercion |
| **Confirm-before-delete** | transactions, budgets, recurring_payments, bookings, contacts, documents |

### 11.3 AI Data Tools (LLM Function Calling)

5 универсальных инструментов: `query_data`, `create_record`, `update_record`, `delete_record`, `aggregate_data`

**Включены на 6 агентах:** analytics, chat, tasks, life, booking, finance_specialist

**Allowed Tables (13):** transactions, categories, budgets, recurring_payments, tasks, life_events, bookings, contacts, monitors, shopping_lists, shopping_list_items, documents

**Progressive Tool Loading:** `get_schemas_for_domain(agent_name)` — ~70% token reduction per agent

### 11.4 Модели AI

| Модель | ID | Назначение |
|--------|-----|-----------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Analytics, reports, writing, email, document, finance |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Guardrails, intent fallback, fact extraction |
| GPT-5.4 | `gpt-5.4-2026-03-05` | Chat, tasks, calendar, life, booking agents |
| Gemini 3.1 Flash Lite | `gemini-3.1-flash-lite-preview` | Intent (primary), OCR, research, receipt |
| Gemini 3 Pro | `gemini-3-pro-preview` | Deep reasoning, complex analysis |
| Gemini 3.1 Flash Image | `gemini-3.1-flash-image-preview` | Image generation (primary) |
| Gemini 3 Pro Image | `gemini-3-pro-image-preview` | Image generation (fallback) |

### 11.5 Фоновые задачи (15 модулей)

| Задача | Расписание | Модуль |
|--------|-----------|--------|
| Напоминания | `* * * * *` (каждую минуту) | reminder_tasks |
| Scheduled actions | `* * * * *` | scheduled_action_tasks |
| Booking reminders (24h + 1h) | `* * * * *` | booking_tasks |
| Proactive triggers | `*/10 * * * *` | proactivity_tasks |
| No-show detection | `*/15 * * * *` | booking_tasks |
| Token stats aggregation | `0 4 * * *` | billing_tasks |
| Nightly profile learning | `0 3 * * *` | profile_tasks |
| Document cleanup (90d retention) | `0 3 * * *` | document_tasks |
| Recurring payments processing | `0 8 * * *` | notification_tasks |
| Recurring docs generation | `0 9 * * *` | document_tasks |
| Budget/anomaly alerts | `0 21 * * *` | notification_tasks |
| Weekly patterns analysis | `0 10 * * 1` (Mon) | notification_tasks |
| Weekly procedural memory | `0 4 * * 0` (Sun) | memory_tasks |
| Cross-domain insights | `0 11 * * 0` (Sun) | crossdomain_tasks |

### 11.6 LangGraph Orchestrators

| Оркестратор | Поток | HITL | Feature Flag |
|-------------|-------|------|-------------|
| **Email** | planner → reader → writer → reviewer → approval → finalizer | ✅ interrupt | `ff_langgraph_email_hitl` |
| **Brief** | parallel fan-out (5 collectors) → synthesize | ❌ | — |
| **Booking** | parse → preview → platform → auth → search → results → confirm → book | ✅ 4 interrupts | `ff_langgraph_booking` |
| **Approval** | ask_approval (interrupt) → execute_action | ✅ interrupt | — |

**Resilience:** `@with_timeout(seconds)`, `@with_retry(max_retries, backoff_base)`, DLQ на fatal failures

### 11.7 Browser Tools

| Модуль | Назначение | Детали |
|--------|-----------|--------|
| `browser.py` | General web automation | Browser-Use (LLM) + Playwright fallback |
| `browser_booking.py` | Hotel booking FSM | 6 платформ, JS extraction, 180s search timeout |
| `browser_login.py` | Telegram login flow | Email → password → 2FA, passwords redacted |
| `browser_service.py` | Session management | Fernet encryption, 30d expiry, 20+ domain configs |

---

## 12. СИСТЕМА ПАМЯТИ (10+ слоёв)

### 12.1 Архитектура слоёв

| # | Слой | Хранение | Размер | Drop Priority |
|---|------|----------|--------|---------------|
| 0 | **Core Identity** | `user_profiles.core_identity` JSONB + Redis 10min | ~3K | 🔒 NEVER DROP |
| 0.75 | **Project Context** | `user_projects` + Mem0 projects domain | ~1K | Mid |
| 1 | **System Prompt** | Agent config + specialist + procedures | ~20K | 🔒 NEVER DROP |
| 1.5 | **Session Buffer** | Redis `session_facts:{uid}` TTL 30min | ~500 | First |
| 2 | **Mem0 Long-term** | pgvector (12 доменов, 1536d embeddings) | 8-30K | Non-core first |
| 2.5 | **Mem0 DLQ** | Redis `mem0_dlq:{uid}` TTL 24h, max 200 | — | — |
| 3 | **Procedures** | `learned_patterns["procedures"]` + Redis realtime | 2-5K | Mid |
| 5 | **Sliding Window** | Redis `conv:{uid}:messages` + PostgreSQL fallback | varies | Old msgs first |
| 6 | **Session Summary** | `session_summaries` table | ~2K | High |
| 7 | **Episodic** | `session_summaries.episode_metadata` JSONB | ~2K | Low |
| 8 | **Observational** | `learned_patterns["observations"]` (max 50) | ~2K | Low |
| 9 | **Graph Memory** | `memory_graph` table (10 relation types, 7 entity types) | ~1K | Mid |
| 10 | **SQL Analytics** | Database aggregates per intent | ~30K | Compress → drop |

### 12.2 Mem0 Domains (12)

| # | Домен | Что хранит |
|---|-------|-----------|
| 1 | core | name, language, timezone, communication |
| 2 | finance | expenses, income, budgets, merchant mappings |
| 3 | life | food, drink, mood, energy, sleep, notes |
| 4 | contacts | people, relationships, companies |
| 5 | documents | document preferences, templates |
| 6 | content | writing style, tone, post preferences |
| 7 | tasks | habits, routines, reminders |
| 8 | calendar | scheduling preferences, recurring events |
| 9 | research | interests, topics, saved searches |
| 10 | episodes | past interactions, outcomes |
| 11 | procedures | learned rules, corrections, workflows |
| 12 | projects | user projects, goals, status |

### 12.3 Token Budget

- **Max context:** 200K tokens
- **Budget ceiling:** 150K (0.75 ratio)
- **Progressive disclosure:** 80-96% экономия на простых запросах ("100 кофе")

**Overflow drop order:**
1. Mem0 non-core namespaces
2. Session summary (compress/shorten)
3. SQL analytics (compress to 2K → drop)
4. Old history messages
5. Mem0 core + finance (last among Mem0)
6. Remaining history (absolute last resort)
7. 🔒 **NEVER:** System prompt + core identity + user message

### 12.4 Специальные механизмы

| Механизм | Файл | Детали |
|----------|------|--------|
| **Undo Window** | `src/core/undo.py` | Redis TTL 120s, чистит Mem0 факты по transaction_id |
| **Smart Suggestions** | `src/core/suggestions.py` | 12 intent mappings, cooldown 5min |
| **Reverse Prompting** | `src/core/reverse_prompt.py` | Предлагает план перед сложными запросами (>50 слов) |
| **Document Vectors** | `src/core/memory/document_vectors.py` | Chunk (800/100) + text-embedding-3-small + pgvector + pg_trgm RRF |
| **Post-Gen Check** | `src/core/post_gen_check.py` | Проверка ответа после генерации (ff_post_gen_check) |

---

## 13. MINI APP (SPA)

### Что ЕСТЬ

| Функция | Endpoint | Детали |
|---------|----------|--------|
| Auth | `POST /api/auth` | Telegram WebApp token validation |
| Транзакции CRUD | `/api/transactions` | GET/POST/PUT/DELETE, month filter, pagination |
| Категории | `/api/categories` | GET/POST, scope filtering |
| Бюджет | `/api/budget` | GET/PUT monthly |
| Статистика | `/api/stats` | Expense/income breakdown by period |
| CSV Export | `/api/export` | Streaming export |
| Задачи CRUD | `/api/tasks` | GET/POST/PUT/DELETE |
| Список покупок | `/api/shopping-list` | GET/POST/DELETE |
| Recurring Payments | `/api/recurring` | GET/POST/PUT |
| Settings | `/api/settings` | language, currency, timezone |
| RBAC | — | Owner vs member permissions + scope filtering |

### Чего НЕТ

| Функция | Статус |
|---------|--------|
| Dashboard с графиками/трендами | ❌ |
| Booking management UI | ❌ |
| Contact management UI | ❌ |
| Document viewer/uploader | ❌ |
| Calendar integration view | ❌ |
| Life events / wellness dashboard | ❌ |
| Memory/rules management UI | ❌ |
| Notification preferences UI | ❌ |

---

## 14. API ENDPOINTS

### Webhooks

| Endpoint | Канал |
|----------|-------|
| `POST /webhook` | Telegram |
| `POST /webhook/slack/events` | Slack Events |
| `POST /webhook/slack/actions` | Slack interactive |
| `POST /webhook/whatsapp` | WhatsApp Cloud |
| `GET /webhook/whatsapp` | WhatsApp verification |
| `POST /webhook/sms` | Twilio SMS |
| `POST /webhook/stripe` | Stripe billing |

### Health & Static

| Endpoint | Детали |
|----------|--------|
| `GET /health` | Basic 200/503 |
| `GET /health/detailed` | Circuit breakers, checkpointer, auth |
| `GET /` | Landing page |
| `GET /miniapp` | Mini App SPA |
| `GET /privacy` | Privacy policy |
| `GET /terms` | Terms of service |

---

## 15. DEPLOYMENT

| Компонент | Детали |
|-----------|--------|
| **Platform** | Railway |
| **Database** | Supabase (PostgreSQL + pgvector) |
| **Cache** | Redis |
| **Migrations** | Alembic (28+ migrations) |
| **CI/CD** | GitHub Actions: lint → test → docker → Railway deploy |
| **Docker** | python:3.12-slim, WeasyPrint deps, healthcheck |
| **Worker** | Separate Railway service (Taskiq worker + scheduler) |
| **Entrypoint** | `scripts/entrypoint.sh` → `alembic upgrade head` → `uvicorn` |

---

## 16. ПОЛНЫЙ BACKLOG (НЕ РЕАЛИЗОВАНО)

### Финансы
- [ ] Schedule C / IFTA export
- [ ] Per diem tracking
- [ ] Annual tax package
- [ ] Google Sheets full bidirectional sync

### Доступ и роли
- [ ] Accountant read-only role
- [ ] Client portal для booking

### Жизнь / Wellness
- [ ] Sleep tracking
- [ ] Exercise / workout tracking
- [ ] Habit tracker с streaks
- [ ] Weight tracking
- [ ] Health insights dashboard

### Задачи
- [ ] Subtasks / вложенные задачи
- [ ] Task dependencies
- [ ] Kanban board (Mini App)
- [ ] Tags / labels
- [ ] Task sharing между members

### Контент
- [ ] Content calendar / scheduling
- [ ] Brand voice profiles
- [ ] Image editing / variations
- [ ] Video generation
- [ ] Multi-platform auto-posting

### Email / Calendar
- [ ] Multi-account email
- [ ] Email templates / scheduled send
- [ ] Multi-calendar
- [ ] Meeting scheduling с внешними
- [ ] Recurring events creation через бот

### Booking / CRM
- [ ] Online payment integration
- [ ] WhatsApp/SMS уведомления клиентам
- [ ] Waitlist / queue management
- [ ] Staff scheduling (полное)

### Инфраструктура
- [ ] Telegram Stars монетизация
- [ ] Mem0 OpenMemory MCP
- [ ] Redis → LangGraph Store migration
- [ ] Wire `is_healthy()` into `/health`

### Memory Plan (незавершённые фазы)
- [ ] Phase 1: Guardrails whitelist для персонализации
- [ ] Phase 3: Immediate identity update (полная интеграция)
- [ ] Phase 7: Contradiction handling (приоритет при конфликте фактов)
- [ ] Phase D: 20-scenario regression test suite
- [ ] Phase B: Episodic memory validation

### Mini App
- [ ] Dashboard с графиками
- [ ] Booking / contacts / documents UI
- [ ] Calendar / life events views
- [ ] Memory management UI
- [ ] Notification preferences

---

## 17. СТАТИСТИКА ПРОЕКТА

| Метрика | Значение |
|---------|----------|
| **Скиллов зарегистрировано** | 99 |
| **Агентов** | 13 |
| **LangGraph оркестраторов** | 4 |
| **Каналов связи** | 4 (Telegram, Slack, WhatsApp, SMS) |
| **Доменов маршрутизации** | 16 |
| **AI моделей** | 8 (3 Anthropic, 1 OpenAI, 4 Google) |
| **Слоёв памяти** | 10+ |
| **Mem0 доменов** | 12 |
| **Таблиц в БД** | 35+ |
| **Alembic миграций** | 28+ |
| **Фоновых задач (cron)** | 14 |
| **Mini App endpoints** | 20+ |
| **Бизнес-профилей** | 3 (manicure, flowers, construction) |
| **Триггерных ключевых слов** | 200+ (EN/RU/ES) |
| **Token budget** | 200K (ceiling 150K) |
