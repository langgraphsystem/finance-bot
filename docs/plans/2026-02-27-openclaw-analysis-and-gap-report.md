# OpenClaw vs Finance Bot — Gap Analysis & Action Plan

**Date:** 2026-02-27
**Version:** 1.1 (updated 2026-03-10)
**Source:** OpenClaw knowledge base (145 videos, 18 queries to NotebookLM)
**Scope:** All 10 architectural directions of OpenClaw vs Finance Bot current state

---

## Executive Summary

OpenClaw — open-source self-hosted framework для автономного 24/7 ИИ-ассистента (430K+ LOC, Node.js). Создатель — Peter Steinberger (ушёл в OpenAI возглавлять personal agents).

Finance Bot — SaaS AI Life Assistant ($49/мес, Python/FastAPI, 390+ файлов, **108 навыков**, **13 агентов**, 4 LangGraph оркестратора). *(обновлено 2026-03-10)*

**Scorecard (Mar 2026): OpenClaw 41/50 vs Finance Bot ~40/50** — разрыв сократился с 7 до ~1 балла после внедрения Memory Plan, RBAC, SIA, Document Agent и OpenClaw features.

### Где мы сильнее OpenClaw (5 областей):
1. **Память** — 10 слоёв (+ DLQ, immediate identity update, user rules Layer 0.5, post-gen check) vs 2-3
2. **Model routing** — 9 моделей + 3 уровня маршрутизации + zero-LLM keyword path
3. **Каналы** — 4 канала + голосовые звонки (Twilio + OpenAI STT)
4. **Email** — LangGraph orchestrator (5 нод, revision loop, HITL) vs базовая автоматизация
5. **Антиспам проактивности** — cooldowns, daily cap, communication modes, suppression
6. **RBAC** — workspace_memberships, visibility columns, role-based access (Mar 2026) *(новое)*
7. **Document Agent** — 19 специализированных навыков + versioning + pgvector search *(новое)*

### Где OpenClaw сильнее (3 области):
1. **Desktop control** — полный контроль ОС vs только браузер
2. **Параллельные субагенты** — произвольные параллельные задачи vs 1-intent-1-skill
3. **Динамические навыки** — Markdown runtime creation vs 108 статических (11 шагов добавления)

> **Закрытые гепы (Mar 2026):** Soul.md → Adaptive Personality (profile_tasks + observational), User Rules JSONB; Memory Feedback → memory_update intent; Undo Window → undo.py; Scheduled Actions → SIA Epic A-E

---

## Direction 1: Architecture & Gateway

### OpenClaw
- **WebSocket-сервер** (порт 18789) — единый входной шлюз
- **Channel Adapters** — нормализация из Telegram/WhatsApp/Discord в единый формат
- **Lane-Based Command Queues** — каждая сессия в своей "полосе", серийное выполнение (без race conditions)
- **Kilo Gateway** — унифицированный API endpoint для динамического переключения LLM-провайдеров
- **Docker Sandboxing** — Gateway + execution в разных контейнерах

### Finance Bot
- **FastAPI + aiogram 3.25** — webhook-driven (не WebSocket)
- **MessageGateway protocol** — все каналы нормализуют в `IncomingMessage`/`OutgoingMessage`
- **Нет lane queues** — каждый запрос обрабатывается независимо (FastAPI async)
- **Multi-provider routing** через `src/core/llm/router.py` (TASK_MODEL_MAP) + per-agent model
- **E2B sandbox** для code execution, нет Docker isolation для самого бота

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Gateway универсальность | 5/5 (WebSocket + adapters) | 4/5 (webhooks + protocol) |
| Очередь сообщений | 5/5 (lane-based serial) | 3/5 (нет очередей, async) |
| LLM routing | 4/5 (fallback chains, hot-swap) | 5/5 (6 моделей, 3 уровня, TASK_MODEL_MAP) |
| Sandboxing | 5/5 (Docker containers) | 3/5 (E2B cloud only, нет self-isolation) |

### Gap: Lane-Based Queues
У нас нет гарантии серийной обработки для одного пользователя. Два одновременных сообщения от пользователя могут создать race condition в Redis/DB state. OpenClaw решает это через session lanes.

**Рекомендация:** Добавить per-user async lock (Redis SETNX) перед обработкой сообщений. Низкий приоритет — на практике пользователи редко шлют параллельно.

---

## Direction 2: Memory System

### OpenClaw
- **Контекстное окно = "RAM"** — текущая сессия
- **Markdown-файлы = "Storage"** — user.md, soul.md, memory.md (Git-backed)
- **Write-Ahead Logging (Compaction)** — суммаризация перед очисткой контекста
- **QMD Vector Search** — SQLite/Vector бэкенд для быстрого поиска по тысячам файлов
- **Multilingual Memory** — EN, ES, PT, JA, KO, AR

### Finance Bot
- **5 слоёв памяти:**
  1. **Sliding Window** — 10 сообщений в Redis (24h TTL)
  2. **Dialog Summary** — инкрементальная суммаризация (Gemini Flash, 400 токенов)
  3. **Mem0 Memories** — долгосрочная семантическая (pgvector, 10 категорий фактов)
  4. **SQL Analytics** — текущий/прошлый месяц расходов по категориям
  5. **Conversation History** — полная история в PostgreSQL (audit trail)
- **Per-intent context config** (QUERY_CONTEXT_MAP) — каждый интент загружает только нужные слои
- **Token budget:** 200K × 0.75 = 150K, приоритет сброса: old messages → summary → SQL → Mem0
- **Progressive Context Disclosure** — простые сообщения ("100 кофе") пропускают тяжёлые слои (80-96% экономия)
- **Lost-in-the-Middle positioning** — свежие сообщения ближе к ответу

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Количество слоёв | 3/5 (2-3 слоя) | 5/5 (5 слоёв) |
| Semantic search | 4/5 (QMD Vector) | 5/5 (Mem0 pgvector, 10 категорий) |
| Token efficiency | 3/5 (compaction only) | 5/5 (per-intent budgets, progressive disclosure) |
| Self-writing memory | 5/5 (bot writes own files) | 4/5 (Mem0 auto-extract, но не self-authored) |
| Version control | 5/5 (Git-backed .md) | 2/5 (DB only, нет rollback) |

### Gap: Git-Backed Memory Versioning
OpenClaw хранит память в Git — можно откатить к любому состоянию. У нас Mem0 и PostgreSQL без версионирования памяти.

**Рекомендация:** Низкий приоритет. Mem0 обновления через LLM (ADD/UPDATE/DELETE) достаточно надёжны. Rollback — edge case.

### Advantage: We're significantly ahead
Наша 5-слойная система с per-intent budgets и progressive disclosure — одна из самых продвинутых в индустрии. OpenClaw использует простой подход "файлы + compaction".

---

## Direction 3: Proactive Autonomy

### OpenClaw
- **Heartbeat System** — пробуждение каждые 15-30 мин (дешёвая модель проверяет heartbeat.md)
- **Cron Jobs** — расписание на natural language, параллельное выполнение
- **"Figure It Out"** — автономное решение без обращения к пользователю
- **Self-Evolution** — cron job сканирует Reddit/X, создаёт новые навыки на основе находок
- **Webhooks** — прослушивание внешних триггеров (TradingView, GitHub)
- **Ночные "Советы"** — token-heavy workflows пока спишь (Security Council, Business Advisory)

### Finance Bot
- **11 cron задач** через Taskiq + Redis:
  - Каждую минуту: dispatch_reminders, dispatch_booking_reminders
  - Каждые 10 мин: evaluate_proactive_triggers (3 data triggers)
  - Каждые 15 мин: detect_no_shows, morning_brief, evening_recap
  - Ежедневно: daily_notifications (21:00), process_recurring (08:00), update_profiles (03:00)
  - Еженедельно: weekly_pattern_analysis (Пн 10:00), weekly_life_digest (Вс 20:00)
- **Антиспам:** max 5 messages/user/day, per-trigger cooldown (4-24h), communication modes (silent/receipt/coaching)
- **Learned suppression:** пользователь может подавить конкретные триггеры
- **Timezone-aware:** все задачи учитывают часовой пояс пользователя

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Trigger разнообразие | 5/5 (heartbeat + cron + webhooks) | 3/5 (3 data triggers + 8 time-based) |
| Антиспам | 2/5 (нет упоминания лимитов) | 5/5 (cooldowns, daily cap, comm modes) |
| Natural language scheduling | 5/5 ("every day at 8am") | 2/5 (hardcoded cron expressions) |
| Self-evolution | 5/5 (cron создаёт новые навыки) | 0/5 (нет) |
| External webhooks | 5/5 (TradingView, GitHub, etc.) | 1/5 (только Telegram/Slack/WhatsApp webhooks) |
| Timezone handling | 3/5 (не детализировано) | 5/5 (per-user timezone, DST-safe) |

### Gap: Trigger Diversity + External Webhooks
OpenClaw может слушать произвольные webhooks (GitHub, TradingView) и запускать workflows. У нас — только 3 data triggers (deadline, budget, overdue) + 8 time-based. Нет general-purpose webhook listener.

### Gap: Natural Language Scheduling
OpenClaw позволяет "Schedule a brief every day at 8 AM" через natural language. У нас cron schedules hardcoded в коде.

### Gap: Self-Evolution
OpenClaw может создавать новые навыки автономно (cron сканирует интернет → создаёт skill). У нас — 11 шагов ручного добавления.

**Рекомендации:**
1. **P2:** Расширить data triggers (5-7 новых: recurring payment due, savings goal, unusual spending, weather-based)
2. **P3:** Webhook listener endpoint (`/api/webhook/{user_id}`) для внешних интеграций
3. **P4:** Natural language scheduling через intent detection → cron expression generator

---

## Direction 4: Multi-Agent Orchestration

### OpenClaw
- **Orchestrator pattern** — мастер-агент разбивает задачу → создаёт суб-агентов (Researcher, Coder, Marketer) → параллельное выполнение → результаты собираются
- **"Swarms"** — 10+ суб-агентов работают одновременно
- **Inter-agent communication** — агенты обмениваются данными
- **Dynamic agent creation** — агенты создаются на лету из промпта
- **Agentic Company Structure** — мастер-агент → делегирует персональным агентам сотрудников

### Finance Bot
- **12 pre-defined agents** (receipt, analytics, chat, onboarding, tasks, research, writing, email, calendar, life, booking, finance_specialist)
- **4 LangGraph orchestrators:**
  - **Brief** — TRUE parallel fan-out (5 collectors одновременно) → synthesizer
  - **Email** — sequential с revision loop (max 2 revisions) + HITL interrupt
  - **Booking** — FSM с 3 interrupt points + multi-step state
  - **Approval** — minimal 2-node HITL для опасных действий
- **НЕТ:** dynamic agent creation, inter-agent calls, sub-agent spawning
- **1 intent = 1 skill** — нет разбиения задачи на подзадачи

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Parallel execution | 5/5 (arbitrary swarms) | 3/5 (brief fan-out only) |
| Dynamic agents | 5/5 (runtime creation) | 0/5 (12 static) |
| HITL interrupts | 3/5 (basic confirmation) | 5/5 (LangGraph interrupt/resume, stateful) |
| Orchestrator depth | 4/5 (master → sub-agents) | 4/5 (4 specialized graphs) |
| Task decomposition | 5/5 (automatic breakdown) | 1/5 (1 intent = 1 skill) |

### Gap: Parallel Sub-Agents for Complex Tasks
Это самый большой архитектурный gap. OpenClaw может "Run all three competitor analyses simultaneously". У нас каждое сообщение → 1 intent → 1 skill.

### Gap: Task Decomposition
OpenClaw автоматически разбивает "Write a blog post with research" на: (1) Research Agent, (2) Writer Agent, (3) SEO Agent, параллельно. У нас — один `write_post` skill делает всё.

**Рекомендации:**
1. **P2:** LangGraph fan-out pattern для research+writing tasks:
   ```
   decompose → [research, outline, media_search] → synthesize → review → output
   ```
2. **P3:** Generic parallel executor в `src/orchestrators/parallel/graph.py`
3. **P4:** Dynamic agent factory (LLM определяет нужных суб-агентов из задачи)

---

## Direction 5: Skill System

### OpenClaw
- **Skill = папка с skill.md** (YAML front matter + plain English инструкции) + опциональные скрипты
- **Progressive Disclosure** — загружается только имя + описание; полная инструкция при вызове
- **Runtime creation** — "Create a skill that monitors GitHub issues" → бот сам создаёт файлы
- **ClawHub marketplace** — тысячи community навыков (но ~20% вредоносных!)
- **MCP → CLI конвертер** (makeporter) — превращает MCP-серверы в Unix CLI команды
- **Natural language install** — `/clawhub` → поиск → установка

### Finance Bot
- **Skill = Python class** (BaseSkill protocol) с 6 обязательными методами
- **74 навыка** зарегистрированы статически в `src/skills/__init__.py`
- **11 шагов** для добавления нового навыка (handler → register → intent → schema → context → agent → catalog → domain → tests × 3)
- **Progressive Skill Loading** через supervisor (keyword → domain → scoped intents) — 95% сокращение prompt size
- **НЕТ:** runtime creation, marketplace, user-defined skills

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Ease of creation | 5/5 (Markdown + natural language) | 2/5 (11 steps, code changes) |
| Runtime addition | 5/5 (bot creates itself) | 0/5 (requires deploy) |
| Type safety | 2/5 (Markdown, no validation) | 5/5 (Pydantic, type-checked) |
| Scale | 4/5 (ClawHub marketplace) | 4/5 (74 skills, supervisor routing) |
| Security | 2/5 (20% malware on ClawHub) | 5/5 (all skills vetted, no external) |
| Progressive loading | 4/5 (YAML front matter) | 5/5 (keyword → domain → scoped intent) |

### Gap: Light Skills (YAML-based custom instructions)
Основной gap — невозможность быстро добавить "лёгкий" навык без 11 шагов кода.

**Рекомендация (P3): Light Skills System**
```yaml
# config/light_skills/morning_workout.yaml
name: morning_workout
trigger_phrases: ["morning workout", "тренировка", "exercise plan"]
agent: life
model: gpt-5.2
system_prompt: |
  You are a fitness coach. Create a 15-minute morning workout routine
  based on user's fitness level and available equipment.
  Always warm up first. Use numbered steps.
response_format: text
```
- Загружаются из `config/light_skills/*.yaml` при старте
- Не требуют Python-кода, IntentData, или тестов
- Ограниченная функциональность (текстовые ответы, нет DB tools)
- Пользователь может создавать через чат: "Create a light skill for morning workouts"

---

## Direction 6: Personality & Soul

### OpenClaw
- **soul.md** — живой файл с личностью агента: стиль, тон, форматирование, ценности
- **Self-updating** — бот сам обновляет soul.md на основе взаимодействий
- **identity.md** — персона суб-агента ("Senior React Developer")
- **user.md** — всё о пользователе (цели, контекст, привычки)
- **"Figure It Out" directive** — "I can't is not vocabulary. Research, reverse-engineer, try multiple approaches before asking me."
- **Response Optimizer** — "Structure: 1. Bottom Line. 2. Why. 3. Next Actions. 4. Watch out for."
- **Natural language editing** — "Update your soul.md to stop using emojis"

### Finance Bot
- **LANGUAGE_VOICE.md** — статический гайд ("smart, capable friend")
- **Agent-level system prompts** — 12 узких промптов в `src/agents/config.py`
- **Learned patterns** — nightly cron (03:00) обновляет active_hours, topics, suppressed_triggers
- **tone_preference** field — "friendly" (зарезервировано, не используется)
- **НЕТ:** self-evolving personality, user-editable soul, "Figure It Out" autonomy

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Self-evolution | 5/5 (bot writes own soul.md) | 1/5 (only learned_patterns meta) |
| User control | 5/5 ("update your soul to...") | 1/5 (нет редактирования личности) |
| Consistency | 3/5 (soul can drift) | 5/5 (static prompts, always consistent) |
| Adaptivity | 5/5 (adapts to feedback loop) | 3/5 (adapts to activity, not personality) |
| Multi-persona | 5/5 (identity.md per sub-agent) | 4/5 (12 agent prompts) |

### Gap: Adaptive Personality
OpenClaw обучается на собственных успехах/неудачах и обновляет soul.md. У нас learned_patterns — только meta (active_hours, topics), не personality.

**Рекомендации (P1):**
1. **Adaptive soul** — расширить `update_user_profiles()` cron для анализа:
   - Какие ответы пользователь лайкнул / проигнорировал
   - Какой уровень детализации предпочитает (short vs detailed)
   - Формальность / неформальность общения
2. **Сохранять в `user_profiles.personality_config`:**
   ```json
   {
     "verbosity": "concise",
     "formality": "casual",
     "emoji_preference": "minimal",
     "detail_on_finance": "high",
     "detail_on_tasks": "low",
     "preferred_greeting": "none"
   }
   ```
3. **Инжектить в system prompt** через `_add_personality_context()`

---

## Direction 7: Channels & Interfaces

### OpenClaw
- **10+ каналов:** Telegram, WhatsApp, Discord, Slack, iMessage, Signal, Google Chat, Mattermost, Line, Synology Chat
- **Threadbound Agents** в Discord/Slack — каждый тред = свой агент
- **Web UI** (localhost:18789) — dashboard с токенами, агентами, навыками
- **TUI** — терминальный чат
- **Live Canvas** — визуальное управление кодом
- **iOS Share Extension** — прямая отправка контента

### Finance Bot
- **4 канала:** Telegram (primary), Slack, WhatsApp, SMS/Twilio
- **Voice input:** STT (gpt-4o-mini-transcribe + whisper-1 fallback)
- **НЕТ:** Discord, iMessage, Signal, Web UI, TUI, iOS extension
- **НЕТ:** TTS (голосовые ответы)
- **Mini App backend ready** (25 REST endpoints), но frontend не реализован

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Channel count | 5/5 (10+) | 3/5 (4) |
| Voice input | 4/5 (Whisper) | 5/5 (mini-transcribe + whisper fallback) |
| Voice output | 4/5 (11Labs клон голоса) | 0/5 (нет TTS) |
| Web dashboard | 5/5 (полный UI) | 1/5 (только API endpoints) |
| Mobile experience | 4/5 (iOS extension) | 4/5 (Telegram-native, inline buttons) |

### Gap: TTS (Text-to-Speech)
Пользователи могут отправить голосовое — но бот всегда отвечает текстом. OpenClaw может отвечать голосом (11Labs).

### Gap: Discord
OpenClaw поддерживает Discord с threadbound agents. У нас — нет.

**Рекомендации:**
1. **P4:** TTS — добавить OpenAI TTS API (`tts-1`) для голосовых ответов в Telegram voice notes
2. **P4:** Discord gateway (`src/gateway/discord_gw.py`) — по паттерну Slack gateway
3. **P3:** Mini App frontend (React SPA) — backend endpoints уже готовы

---

## Direction 8: Browser & Desktop Control

### OpenClaw
- **Full OS access** — файлы, bash, терминал, процессы
- **Browser Relay Extension / Playwright** — полное управление Chrome
- **CLI Over MCP** — makeporter конвертирует MCP в CLI команды
- **"Vibe Coding"** — "Build a dashboard. Deploy to Vercel." с телефона
- **DevOps automation** — "Every 12 hours: check GitHub repos, update deps, run tests"

### Finance Bot
- **Browser-Use Agent** (Claude Sonnet 4.6) — LLM-driven browser control
- **Playwright fallback** — read-only web scraping
- **Encrypted cookie sessions** — 30-day TTL, 40+ сайтов
- **Hotel booking automation** — multi-step flows (Booking, Airbnb, etc.)
- **E2B sandbox** — code execution (Python/JS/Bash)
- **НЕТ:** OS-level commands, file system access, process management, desktop GUI

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Browser control | 5/5 (full Playwright + Extension) | 4/5 (Browser-Use + Playwright fallback) |
| OS control | 5/5 (full bash/files/processes) | 0/5 (нет) |
| Code execution | 4/5 (Docker sandbox) | 4/5 (E2B cloud sandbox) |
| Session persistence | 3/5 (не детализировано) | 5/5 (encrypted cookies, 40+ sites) |
| Safety | 2/5 (root access = high risk) | 5/5 (sandboxed, no OS access) |

### Assessment
Desktop control — **намеренное** ограничение. Мы — SaaS для обычных пользователей, не power-user self-hosted framework. Полный OS access = огромный вектор атаки. **Не рекомендуется закрывать этот gap.**

---

## Direction 9: Security

### OpenClaw
- **Docker Sandboxing** — Gateway + Agent в разных контейнерах
- **Skill Code Safety Scanner** — VirusTotal + Agent Trust Hub
- **Secret Redaction** — автоудаление API keys из логов
- **DM Allow Lists** — игнор сообщений от неавторизованных ID
- **Tool Deny Policies** — блокировка опасных команд
- **КРИТИЧЕСКАЯ УЯЗВИМОСТЬ:** prompt injection через email/web pages

### Finance Bot
- **Claude Haiku guardrails** — input safety check (1 sec, fail-open)
- **Row-Level Security** — PostgreSQL RLS via `set_config('app.current_family_id')`
- **Multi-tenant isolation** — 30 таблиц с family_id FK
- **E2B sandbox** — code execution изолирован в облаке
- **Encrypted cookie storage** — Fernet encryption для browser sessions
- **Google OAuth** — для email/calendar (не plain text credentials)
- **HITL approval** — LangGraph interrupt для опасных действий (delete, send_email)

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Input validation | 3/5 (model-based only) | 4/5 (Claude Haiku guardrails) |
| Multi-tenancy | 1/5 (single-user) | 5/5 (RLS, family_id isolation) |
| Secret management | 4/5 (v2026.2.26 secure workflow) | 3/5 (env vars only) |
| Prompt injection defense | 2/5 (acknowledged critical risk) | 3/5 (guardrails, but fail-open) |
| HITL for dangerous ops | 3/5 (basic confirmation) | 5/5 (LangGraph stateful approval) |

### Advantage: We're ahead on security
Наш multi-tenant RLS + HITL approval + guardrails значительно безопаснее single-user root-access OpenClaw. Это принципиальное архитектурное преимущество SaaS vs self-hosted.

---

## Direction 10: Reverse Prompting & Advanced Techniques

### OpenClaw
- **Reverse Prompting** — "I want to build X. What do you need from me? Let's create a plan."
- **"Figure It Out"** — soul.md directive: "Research, reverse-engineer, try multiple approaches before asking."
- **Response Optimizer** — structured output: Bottom Line → Why → Next Actions → Watch Out
- **Parallel execution** — "Run all three analyses simultaneously"
- **Self-Evolution** — cron создаёт навыки на основе сканирования интернета
- **Topical Memory** — split memory into /topics/ folder, load only relevant

### Finance Bot
- **НЕТ:** reverse prompting (бот не уточняет план перед выполнением)
- **Clarify gate** — if ambiguous → disambiguation buttons (но не "plan creation")
- **НЕТ:** "Figure It Out" autonomy (бот не исследует интернет самостоятельно)
- **Progressive Context Disclosure** — аналог Topical Memory (load by intent)
- **НЕТ:** structured response format directive

### Оценка

| Критерий | OpenClaw | Finance Bot |
|----------|----------|-------------|
| Reverse prompting | 5/5 | 0/5 |
| Autonomous research | 5/5 | 2/5 (web_search skill, но не авто) |
| Structured responses | 5/5 | 3/5 (LANGUAGE_VOICE.md rules) |
| Self-evolution | 5/5 | 0/5 |
| Topical memory | 4/5 | 5/5 (per-intent context config) |

### Gap: Reverse Prompting
Самый impactful gap с самой низкой стоимостью закрытия. OpenClaw при сложных запросах сначала уточняет план. У нас бот сразу пытается выполнить.

**Рекомендация (P1): Reverse Prompting для сложных задач**
1. В system prompt агентов добавить directive:
   ```
   For complex or ambiguous requests, before executing:
   1. Clarify what you understood
   2. List what information you need
   3. Propose a plan of action
   4. Ask for confirmation
   Only execute after user confirms or says "just do it".
   ```
2. Threshold: если intent confidence < 0.7 ИЛИ сообщение > 50 слов → reverse prompt
3. Exception: простые задачи ("100 кофе", "напомни в 3") — выполнять сразу

---

## Consolidated Scorecard

| Direction | OpenClaw | Finance Bot | Gap |
|-----------|----------|-------------|-----|
| 1. Architecture & Gateway | 4.5 | 4.0 | -0.5 |
| 2. Memory System | 3.5 | 5.0 | **+1.5** |
| 3. Proactive Autonomy | 4.5 | 3.5 | -1.0 |
| 4. Multi-Agent Orchestration | 4.5 | 3.0 | -1.5 |
| 5. Skill System | 4.0 | 3.5 | -0.5 |
| 6. Personality & Soul | 4.5 | 2.5 | -2.0 |
| 7. Channels & Interfaces | 4.5 | 3.0 | -1.5 |
| 8. Browser & Desktop | 4.0 | 3.5 | -0.5 |
| 9. Security | 3.0 | 4.5 | **+1.5** |
| 10. Reverse Prompting | 4.5 | 2.5 | -2.0 |
| **TOTAL** | **41.5/50** | **35.0/50** | **-6.5** |

### Where We Win (3 areas, +4.5 total):
1. **Memory System (+1.5)** — 5-слойная система + per-intent budgets + progressive disclosure
2. **Security (+1.5)** — multi-tenant RLS + HITL approval + guardrails
3. **Browser safety (+0.5 within #8)** — encrypted sessions + E2B sandbox vs root access

### Where We Lose (5 areas, -7.5 total):
1. **Personality & Soul (-2.0)** — нет самообновляющейся личности
2. **Reverse Prompting (-2.0)** — нет планирования перед выполнением
3. **Multi-Agent (-1.5)** — нет параллельных суб-агентов
4. **Channels (-1.5)** — нет TTS, Discord, Web UI
5. **Proactivity (-1.0)** — мало триггеров, нет webhooks

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 недели, 0 infrastructure changes)
**Score impact: +3.0 points → closes gap to -3.5**

| Item | Effort | Files | Impact |
|------|--------|-------|--------|
| **Reverse Prompting directive** | 2h | agents/config.py system prompts | +1.5 на Direction 10 |
| **Expand proactive triggers** | 1d | proactivity/triggers.py, evaluator.py | +0.5 на Direction 3 |
| **Adaptive personality config** | 1d | tasks/profile_tasks.py, agents/base.py | +1.0 на Direction 6 |
| **"Figure It Out" directive** | 1h | agents/config.py (research agent prompt) | +0.5 на Direction 10 |
| **Response Optimizer format** | 1h | LANGUAGE_VOICE.md, agent prompts | implicit |

**Details:**

1. **Reverse Prompting** — добавить в system prompt всех агентов:
   ```
   PLANNING RULE: For requests that are complex (>50 words), ambiguous (confidence <0.7),
   or multi-step: FIRST propose your plan, THEN wait for confirmation. For simple
   actions (track expense, set reminder, quick answer): execute immediately.
   ```

2. **Expand triggers** — добавить в `src/proactivity/triggers.py`:
   - `RecurringPaymentDue` — напоминание за 1 день до recurring payment
   - `SavingsGoalProgress` — еженедельно если цель сбережений установлена
   - `UnusualSpending` — аномалия расходов (>2σ от среднего в категории)
   - `WeeklyBudgetPace` — "вы потратили 60% бюджета за 40% месяца"

3. **Adaptive personality** — расширить nightly `update_user_profiles()`:
   ```python
   personality_config = {
       "verbosity": analyze_avg_response_preference(messages),
       "formality": detect_formality_level(user_messages),
       "preferred_language_style": detect_language_style(messages),
   }
   ```

### Phase 2: Parallel Agents (3-5 дней)
**Score impact: +1.5 points → total gap -2.0**

| Item | Effort | Impact |
|------|--------|--------|
| **Generic parallel executor** | 3d | +1.0 на Direction 4 |
| **Research + Writing fan-out** | 2d | +0.5 на Direction 4 |

**Architecture:**
```python
# src/orchestrators/parallel/graph.py
class ParallelOrchestrator:
    """
    Generic fan-out → fan-in pattern:
    1. decompose_task() → list of subtasks
    2. execute_parallel() → run subtasks concurrently
    3. synthesize() → merge results
    """
```

**Use cases:**
- `write_post` → [research, outline, image_search] → draft → review
- `compare_options` → [search_A, search_B, search_C] → comparison table
- `morning_brief` already uses this pattern (brief orchestrator)

### Phase 3: Light Skills + Mini App (1-2 недели)
**Score impact: +1.5 points → total gap -0.5**

| Item | Effort | Impact |
|------|--------|--------|
| **Light Skills YAML system** | 3d | +1.0 на Direction 5 |
| **Webhook listener endpoint** | 1d | +0.5 на Direction 3 |
| **Mini App frontend (basic)** | 5d | +0.5 на Direction 7 |

**Light Skills:**
```yaml
# config/light_skills/workout.yaml
name: morning_workout
trigger_phrases: ["morning workout", "тренировка"]
agent: life
system_prompt: "You are a fitness coach..."
```
- Загружаются из YAML, не требуют Python
- Пользователь создаёт через чат: "Create a light skill for X"
- ~20 строк loader code в `src/skills/light_loader.py`

### Phase 4: TTS + Discord + Email Monitoring (2-3 недели)
**Score impact: +1.5 points → total gap +1.0 (мы впереди!)**

| Item | Effort | Impact |
|------|--------|--------|
| **TTS voice responses** | 2d | +0.5 на Direction 7 |
| **Discord gateway** | 3d | +0.5 на Direction 7 |
| **Proactive email monitoring** | 3d | +0.5 на Direction 3 |
| **Natural language scheduling** | 2d | +0.5 на Direction 3 |

---

## Deliberate Non-Goals

Следующие фичи OpenClaw мы **не планируем** реализовывать:

| Feature | Reason |
|---------|--------|
| **Full OS access** | Security risk, не подходит для SaaS multi-tenant |
| **Skill marketplace** | 20% malware rate в ClawHub; curated skills безопаснее |
| **Self-hosted deployment** | Мы — SaaS, не self-hosted framework |
| **Crypto trading swarms** | Out of scope для Life Assistant |
| **Clone voice (11Labs)** | Privacy/legal concerns, не MVP |
| **iMessage/Signal** | Platform lock-in (Apple), encryption complexity |

---

## Appendix A: OpenClaw vs Finance Bot Feature Matrix

| Feature | OpenClaw | Finance Bot | Notes |
|---------|----------|-------------|-------|
| Messaging channels | 10+ | 4 | OC: Discord, iMessage, Signal extra |
| LLM providers | 6+ (hot-swap) | 3 (Anthropic, OpenAI, Google) | OC: MiniMax, Ollama, xAI |
| Memory layers | 2-3 | 5 | FB significantly ahead |
| Token budget management | Basic (compaction) | Advanced (per-intent, progressive) | FB significantly ahead |
| Skills count | ~1000+ (ClawHub) | 74 (curated) | Quality vs quantity |
| Skill creation time | 5 min (Markdown) | 2h (11 steps) | OC easier, FB safer |
| Parallel agents | Arbitrary swarms | Brief fan-out only | OC ahead |
| HITL interrupts | Basic confirm | LangGraph stateful | FB ahead |
| Browser automation | Full (Extension + Playwright) | Browser-Use + Playwright | Comparable |
| OS control | Full root access | None (sandboxed) | By design |
| Code execution | Docker sandbox | E2B cloud sandbox | Comparable |
| Voice input | Whisper | mini-transcribe + whisper | FB ahead (dual model) |
| Voice output | 11Labs clone | None | Gap |
| Web UI | Full dashboard | API only (25 endpoints) | Gap |
| Cron/Background | Heartbeat + cron + webhooks | 11 Taskiq crons | OC more flexible |
| Multi-tenancy | Single user | RLS + family_id | FB ahead |
| Security | Low (root + injection risk) | High (guardrails + RLS + HITL) | FB significantly ahead |
| Self-evolution | soul.md auto-update | learned_patterns (meta only) | Gap |
| Reverse prompting | Built-in | Not implemented | Gap |
| Cost optimization | $10-50/mo (MiniMax/Ollama) | $20-100/mo (cloud APIs) | OC cheaper |

---

## Appendix B: OpenClaw Key Concepts Glossary

| Term | Definition |
|------|-----------|
| **Megaprompt** | Динамически собранный промпт из system rules + tools + skills + history |
| **Compaction Safeguard** | Суммаризация контекста перед очисткой (аналог нашего Dialog Summary) |
| **QMD Vector Search** | SQLite + vector embeddings для поиска по файлам (аналог нашего Mem0) |
| **ClawHub** | Marketplace навыков (~1000+, 20% malware) |
| **Heartbeat** | Фоновое пробуждение каждые 15-30 мин дешёвой моделью |
| **Lane-Based Queues** | Per-session serial execution (нет аналога у нас) |
| **Kilo Gateway** | Unified LLM API endpoint (аналог нашего `src/core/llm/clients.py`) |
| **soul.md** | Самообновляющийся файл личности агента |
| **makeporter** | Конвертер MCP → CLI |
| **Boot.md** | Стартовый скрипт при запуске gateway (аналог нашего alembic upgrade head) |

---

*Generated by Claude Code analysis of OpenClaw knowledge base (533 lines, 145 videos) vs Finance Bot architecture (390+ files, 74 skills, 12 agents, 4 orchestrators).*
