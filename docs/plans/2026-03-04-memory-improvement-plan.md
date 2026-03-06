# Memory & Personalization Improvement Plan

**Дата:** 2026-03-04
**Статус:** В работе
**Источник:** `stridos_memory_plan.docx` + Production Upgrade Guide + анализ 20 проблем

---

## Контекст

Анализ 20 известных проблем с памятью, персонализацией и поведением бота.
Проблемы выявлены через: продакшн-логи, исследования (arXiv, dev.to, Medium), Production Upgrade Guide.

### Уже реализовано (не трогаем)
- Session Buffer (`src/core/memory/session_buffer.py`) — Redis, 30 мин TTL
- Core Identity (`src/core/identity.py`) — JSONB, Layer 0, NEVER DROP
- Episodic Memory (`src/core/memory/episodic.py`) — few-shot из истории
- Memory Vault (`src/skills/memory_vault/handler.py`) — memory_show/save/forget
- Temporal Fact Tracking (`src/core/memory/mem0_client.py`) — _archive_superseded_fact
- Circuit Breaker (`src/core/circuit_breaker.py`) — Mem0, Anthropic, OpenAI, Google
- Merchant mappings — PostgreSQL таблица (не Mem0)
- Procedural Memory (`src/core/memory/procedural.py`) — еженедельный крон
- Observational Memory (`src/core/memory/observational.py`) — Observer/Reflector

---

## ЧАСТЬ 1 — Фазы 1–10 (базовый план)

### Фаза 1: Guardrails — whitelist персонализации
**Проблема:** "Тебя зовут Хюррем" → "Я не могу помочь" (false positive)
**Файл:** `src/core/guardrails.py`
**Что сделать:**
- В policy промпт добавить: "Персонализация бота (назначение имени, стиля, предпочтений) — разрешена. Это НЕ impersonation."
- Уточнить: impersonation = притворяться реальным человеком/организацией
- Тест: "тебя зовут X", "запомни что ты Y", "отвечай коротко" → должны проходить

### Фаза 2: Расширение Fact Extraction Prompt
**Проблема:** Промпт говорит "Извлеки ТОЛЬКО финансовые факты". Имя, город, проект — не извлекаются.
**Файл:** `src/core/memory/mem0_client.py` → `FINANCIAL_FACT_EXTRACTION_PROMPT`
**Новые категории:**
- `user_identity` — имя, возраст, профессия, город, страна
- `bot_identity` — имя бота, роль, стиль обращения
- `user_rule` — "без эмодзи", "коротко", "на русском", "не используй сложные слова"
- `user_project` — названия проектов, цели, статус
- `user_preference` — формат ответов, детальность, язык общения
**Переименовать:** `FINANCIAL_FACT_EXTRACTION_PROMPT` → `FACT_EXTRACTION_PROMPT` (больше не только финансы)

### Фаза 3: Immediate Identity Update
**Проблема:** "Меня зовут Манас" → Core Identity обновится только ночным кроном.
**Файлы:** `src/core/identity.py`, `src/core/tasks/memory_tasks.py`
**Что сделать:**
- Для категорий `user_identity`, `bot_identity`, `user_rule` → обновлять `user_profiles.core_identity` JSONB синхронно
- Не ждать ночного `profile_tasks.py`
- Поток: факт извлечён → пишем в core_identity → пишем в Mem0 (фоном)
- Redis-кэш identity инвалидировать при обновлении

### Фаза 4: User Rules — NEVER DROP injection
**Проблема:** Бот соглашается "ОК, без эмодзи", но следующий ответ с эмодзи.
**Файлы:** `src/core/memory/context.py`, модели
**Что сделать:**
- Новое поле: `user_profiles.active_rules` JSONB массив
- Загрузка: `assemble_context()` Layer 0.5 (после identity, до system prompt)
- Формат инъекции:
  ```
  ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ПОЛЬЗОВАТЕЛЯ (нарушение запрещено):
  - Не используй эмодзи
  - Отвечай коротко (1-3 предложения)
  - Твоё имя: Хюррем
  ```
- Приоритет overflow: **NEVER DROP** — наравне с system prompt и identity
- Cache-aware: статичный блок → в cached prefix (Anthropic cache_control)

### Фаза 5: Intent Detection — персонализация
**Проблема:** "Запомни что ты Хюррем" → general_chat → просто текст.
**Файлы:** `src/core/intent.py`, `src/core/schemas/intent.py`
**Что сделать:**
- Новый интент `set_user_rule` или расширить `memory_save`
- Триггеры: "зови себя X", "отвечай коротко", "без эмодзи", "пиши на русском", "запомни что ты X"
- В `INTENT_DETECTION_PROMPT` добавить примеры
- Handler: извлечь правило → записать в `active_rules` + Mem0

### Фаза 6: Realtime Procedural Update
**Проблема:** Procedural memory — еженедельный крон. Исправление сегодня → бот повторит завтра.
**Файлы:** `src/core/memory/procedural.py`, `src/core/tasks/memory_tasks.py`
**Что сделать:**
- При коррекции ("я же сказал без эмодзи", "не так") → сразу в `active_rules` + Mem0 `procedures`
- Еженедельный крон остаётся для паттернов
- Распознавание коррекции: intent_data или эвристика ("я же сказал", "я просил", "опять")

### Фаза 7: Противоречия + приоритет фактов
**Проблемы:** #15 (два города одновременно), #18 (кофе = ребёнок по весу)
**Файлы:** `src/core/memory/mem0_client.py`, `src/core/memory/context.py`
**Что сделать:**
- `priority` поле в Mem0 metadata: `critical` / `important` / `normal`
- Маппинг: identity→critical, project→important, habits→normal
- При overflow: дропать `normal` раньше `critical`
- Temporal: `updated_at` в каждый факт. В промпт: "Город: Бишкек (обновлено 2026-03-01)"
- Проверить что `_archive_superseded_fact` работает для identity фактов

### Фаза 8: Mem0 DLQ
**Проблема:** Async fire-and-forget. Mem0 упал → факт потерян.
**Файлы:** `src/core/memory/mem0_client.py`, новый `src/core/memory/mem0_dlq.py`
**Что сделать:**
- При ошибке `add_memory()` → Redis list `mem0_dlq:{user_id}`
- Фоновый Taskiq-воркер ретраит каждые 5 минут
- Идемпотентный ключ: `hash(user_id + category + content)` — нет дублей при ретрае
- Circuit breaker открыт → копить в очередь
- Алерт если очередь > 100 элементов

### Фаза 9: Undo + Mem0 Sync
**Проблема:** Undo откатывает транзакцию, но Mem0 факт остаётся.
**Файлы:** `src/core/undo.py`, `src/core/memory/mem0_client.py`
**Что сделать:**
- При создании записи → `transaction_id` в Mem0 metadata
- При Undo → искать в Mem0 по `transaction_id` → удалить связанные факты
- Атомарность: DB откат + Mem0 откат в одном flow

### Фаза 10: Dialog History Search
**Проблема:** "О чём мы говорили вчера?" → бот не может ответить.
**Файлы:** новый `src/skills/dialog_history/handler.py`
**Что сделать:**
- Скилл `dialog_history` — поиск по `session_summaries`
- Интент: "о чём мы говорили", "что обсуждали вчера", "какие идеи были на неделе"
- Поиск: pg_trgm по date + text
- Ответ: краткое саммари тем за период

---

## ЧАСТЬ 2 — Архитектурные дополнения (A–F)

### A: Cache-aware Context Assembly
**Что сделать:**
- User Rules (Layer 0.5) → в cached prefix (статичный блок)
- Core Identity (Layer 0) → в cached prefix (статичный блок)
- Динамический контекст (Mem0, SQL, history) → после кэшированного префикса
- Выигрыш: Anthropic cache reads = 10% от базовой цены

### B: Episodic Memory — Layer 4.5
**Статус:** Уже реализовано (`src/core/memory/episodic.py`)
**Проверить:** подтягиваются ли эпизоды в контексте для generative skills

### C: Session Buffer Race Condition
**Статус:** Уже реализовано (`src/core/memory/session_buffer.py`)

### D: Regression Test Suite — 20 сценариев
**Что сделать:**
- Тест-файл: `tests/test_memory_regression.py`
- 20 тестов (по одному на каждую проблему из списка)
- Метрики: intent accuracy, rule compliance, fact retention
- Запуск в CI после каждого деплоя

### E: Graceful Degradation Policy
**Что сделать:**
- Документировать поведение при недоступности:
  - Redis down → читать из PostgreSQL (fallback), ответ медленнее но корректный
  - Mem0 down → circuit breaker уже есть, добавить DLQ (Фаза 8)
  - Supabase медленный → timeout + cached identity из Redis
  - LLM rate limit → fallback chain уже есть (Gemini → Claude → GPT)

### F: Core Identity Layer 0
**Статус:** Уже реализовано (`src/core/identity.py`)
**Дополнение:** Redis-кэш с инвалидацией при обновлении (Фаза 3)

---

## ЧАСТЬ 3 — Дополнения (Фазы 11–13)

### Фаза 11: Memory Feedback + memory_update
**Что сделать:**
- Подтверждение при сохранении: "Запомнил: твоё имя — Манас"
- Новый интент `memory_update`: изменить факт без удаления
- Пример: "обнови мою зарплату" → find → patch → save с новым updated_at
- Команды: "что ты помнишь?", "забудь X", "обнови X"

### Фаза 12: Project Context Entity
**Что сделать:**
- Новая сущность `user_projects`: project_id, name, description, status, related_sessions
- Привязка разговоров к проекту: "это про Stridos" → тег на сессию
- В `assemble_context()`: если проект определён → подгружать project-specific facts
- Clarification: "о каком проекте речь?" если неоднозначно

### Фаза 13: Post-generation Rule Check
**Что сделать:**
- Haiku промпт (~200 токенов): "Этот ответ нарушает правила пользователя?"
- Проверяет: язык, эмодзи, длину, имя бота, стиль
- Нарушение → regenerate с напоминанием нарушенного правила
- Лог нарушений → усиливает правило в Layer 0.5
- Опционально: feature flag `ff_post_gen_check` (добавляет ~1с latency)

---

## ЧАСТЬ 4 — План внедрения

### Неделя 1 — Разблокеры и фундамент
| # | Задача | Файлы | Закрывает |
|---|--------|-------|-----------|
| 1 | Guardrails whitelist | guardrails.py | Фаза 1 |
| 2 | Fact extraction расширение | mem0_client.py | Фаза 2 |
| 3 | Immediate identity update | identity.py, memory_tasks.py | Фаза 3 |
| 4 | User Rules JSONB + injection | context.py, модели | Фаза 4 |
| 5 | Интенты персонализации | intent.py, schemas/intent.py | Фаза 5 |
| 6 | Cache-aware context | context.py, prompts.py | A |
| 7 | Core Identity Redis кэш | identity.py | F |

### Неделя 2 — Надёжность и интеллект
| # | Задача | Файлы | Закрывает |
|---|--------|-------|-----------|
| 8 | Realtime procedural update | procedural.py, memory_tasks.py | Фаза 6 |
| 9 | Противоречия + priority | mem0_client.py, context.py | Фаза 7 |
| 10 | Mem0 DLQ | mem0_dlq.py (новый) | Фаза 8 |
| 11 | Undo + Mem0 sync | undo.py, mem0_client.py | Фаза 9 |
| 12 | Regression test suite | test_memory_regression.py | D |
| 13 | Graceful degradation docs | degradation policy | E |

### Неделя 3 — UX и качество
| # | Задача | Файлы | Закрывает |
|---|--------|-------|-----------|
| 14 | Dialog history search | dialog_history/handler.py | Фаза 10 |
| 15 | Memory feedback + update | memory_vault/handler.py | Фаза 11 |
| 16 | Post-generation rule check | новый модуль | Фаза 13 |
| 17 | Episodic memory проверка | episodic.py | B |

### Бэклог (Неделя 4+)
- Фаза 12: Project Context Entity
- Расширение episodic memory
- Cache optimization метрики
- behavioral_patterns cron

---

## ЧАСТЬ 5 — Полный pipeline после внедрения

```
Сообщение пользователя
  → Guardrails (персонализация в whitelist)           ← Фаза 1
  → Intent Detection (set_user_rule, memory_save)      ← Фаза 5
  → Context Assembly:
      Layer 0:   Core Identity (NEVER DROP, cached)    ← F
      Layer 0.5: User Rules (NEVER DROP, cached)       ← Фаза 4
      Layer 1:   System Prompt (cached prefix)         ← A
      Layer 2:   Procedural Memory                     ← Фаза 6
      Layer 3:   Session Buffer                        ← C (есть)
      Layer 4:   Mem0 Memories (priority-aware)        ← Фаза 7
      Layer 4.5: Episodic Memory                       ← B (есть)
      Layer 5:   SQL Analytics
      Layer 6:   Summary
      Layer 7:   History
  → Skill Execution
  → Post-generation Rule Check                         ← Фаза 13
  → Response to User
  → Background:
      Fact Extraction (расширенный промпт)             ← Фаза 2
      Immediate Identity Update                        ← Фаза 3
      Mem0 Update (с DLQ на ошибку)                    ← Фаза 8
      Undo payload (с transaction_id)                  ← Фаза 9
```

---

## Метрики успеха

| Метрика | Текущее | Цель |
|---------|---------|------|
| "Тебя зовут X" → сохранено | 0% (блокируется) | 100% |
| Правила соблюдаются через 10 сообщений | ~30% | >90% |
| Факты пользователя запоминаются | ~50% (только финансы) | >90% |
| "О чём мы говорили?" → ответ | 0% | 100% |
| Mem0 write failures → потеря данных | 100% потеря | 0% (DLQ) |
| Undo + память синхронизированы | Нет | Да |

---

## Список 20 проблем (reference)

1. Забывает правила ("отвечай коротко")
2. Забывает имя бота
3. Забывает язык общения
4. Не запоминает факты о пользователе
5. Не различает команды и разговор
6. Теряет тему разговора
7. Не помнит прошлые разговоры
8. Не проверяет правила перед ответом
9. Теряет роль/специализацию
10. Context drift
11. Preference drift
12. Echoing (эхо-эффект)
13. Hallucinated memory (ложные воспоминания)
14. Memory poisoning
15. Противоречивые факты
16. Lost-in-the-middle
17. Cross-session amnesia
18. Не различает важность информации
19. Контекстно-зависимые предпочтения
20. Невидимая память
