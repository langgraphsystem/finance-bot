# Scheduled Actions — Текст для E2E-проверки в Telegram

Дата: 2026-03-05
Фича: Scheduled Intelligence Actions (SIA)
Файл предназначен для ручного QA: копируйте фразы из колонки "Отправить в бот".

## Preconditions

1. Включен флаг `ff_scheduled_actions=True`.
2. Пользователь онборжен и привязан к Telegram.
3. У пользователя задан таймзон (например `America/New_York`).
4. Для проверки источников подключены нужные интеграции (calendar/email), иначе допустим fallback-текст.

## 1) Базовый smoke-test (быстрый прогон)

| # | Отправить в бот | Ожидаемый ответ (фрагменты) |
|---|---|---|
| 1 | `List my scheduled actions` | Если пусто: `No scheduled actions yet` / пример с `Try:` |
| 2 | `Schedule a daily morning brief at 8:00 from calendar and tasks` | `✅ <b>Scheduled</b>`, `Sources: calendar, tasks`, `Next run:` |
| 3 | `List my scheduled actions` | Заголовок `Your scheduled actions`, пункт `▶️`, `daily at` |
| 4 | `Move my morning brief to 8:30` | `Rescheduled` или `Action evolved`, есть старое и новое время |
| 5 | `Pause my morning brief` | `⏸ Paused` |
| 6 | `Resume my morning brief` | `▶️ Resumed`, `Next run:` |
| 7 | `Delete my morning brief` | `🗑 Deleted` |
| 8 | `List my scheduled actions` | Снова пустой список (или без удаленного действия) |

## 2) Полный сценарий по всем возможностям фичи

### A. Создание расписаний (all schedule kinds)

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| A1 | `Every day at 08:00 send me calendar, tasks, and email highlights` | Создано daily, источники: calendar/tasks/email |
| A2 | `Every weekday at 09:15 send me my priorities` | Создано weekdays |
| A3 | `Every Monday at 10:00 send me weekly planning brief` | Создано weekly + день недели |
| A4 | `Monthly on day 5 at 11:00 send me finance summary` | Создано monthly + day 5 |
| A5 | `Schedule a one-time brief tomorrow at 14:00` | Создано once |
| A6 | `Create cron digest with cron 0 9 * * 1-5` | `cron schedule` + подтверждение |
| A7 (negative) | `Create cron digest with cron 0 9` | Запрос на корректный cron (`valid cron expression`) |

### B. Источники и outcome-режим

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| B1 | `Every day at 08:00 remind me about unpaid invoices until paid` | Создание persistent/outcome действия (обычно с outstanding) |
| B2 | `Add email to my daily summary` | `Action evolved`/`Updated`, блоки `Before` и `After` |
| B3 | `Remove email from my daily summary` | Источник email исчез в `After` |
| B4 | `Edit my daily summary to use only calendar and tasks` | Источники перезаписаны, видно в `After` |

### C. Редактирование (edit flow)

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| C1 | `Edit my morning brief to weekly at 09:00` | Изменена частота + время, есть `Before/After` |
| C2 | `Move my morning brief to 07:45` | Изменено время, старое `→` новое |
| C3 | `Update instructions for my morning brief: focus on urgent tasks only` | Обновлены инструкции, отражено в изменениях |

### D. Управление статусом

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| D1 | `Pause my morning brief` | `⏸ Paused` |
| D2 | `Pause my morning brief` | `Already paused` |
| D3 | `Resume my morning brief` | `▶️ Resumed` + `Next run` |
| D4 | `Resume my morning brief` | `Already active` |
| D5 | `Delete my morning brief` | `🗑 Deleted` |

### E. Список и поиск target

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| E1 | `List my scheduled actions` | Нумерованный список с иконками статуса |
| E2 | `Pause action 2` | Пауза именно второй записи |
| E3 (negative) | `Pause my unicorn digest` | `No scheduled action matching` / `Не нашёл` |
| E4 (negative) | `Manage my scheduled actions` | Уточнение операции: pause/resume/delete/reschedule/edit |

### F. Мультиязычность

| # | Отправить в бот | Ожидаемый ответ |
|---|---|---|
| F1 | `Каждый день в 8:00 присылай сводку по календарю и задачам` | Ответ на русском: `✅ <b>Запланировано</b>` |
| F2 | `Покажи мои запланированные действия` | Русский список: `📋 <b>Ваши запланированные действия</b>` |
| F3 | `Cada día a las 8 envíame calendario y tareas` | Испанский ответ: `✅ <b>Programado</b>` |
| F4 | `Muéstrame mis acciones programadas` | Испанский список: `📋 <b>Tus acciones programadas</b>` |

### G. Inline-кнопки в сообщении scheduled action

Когда придет автоматическая scheduled-сводка, проверь кнопки:

1. `⏰ +10 min` (или локализованный вариант) -> ответ `Snoozed` / `Отложено`.
2. `▶️ Run now` -> ответ `Queued ... will run now`.
3. `⏸ Pause` -> ответ `Paused`.
4. В paused-состоянии должны быть кнопки `Resume` + `Run now`.
5. Для outcome-действия должна быть кнопка `✅ Done`.

## 3) Короткий copy-paste блок (если нужен одним списком)

```text
List my scheduled actions
Schedule a daily morning brief at 8:00 from calendar and tasks
Move my morning brief to 8:30
Add email to my daily summary
Edit my morning brief to weekly at 09:00
Pause my morning brief
Resume my morning brief
Delete my morning brief
Every day at 08:00 remind me about unpaid invoices until paid
Create cron digest with cron 0 9 * * 1-5
Create cron digest with cron 0 9
Каждый день в 8:00 присылай сводку по календарю и задачам
Muéstrame mis acciones programadas
```

## 4) Критерий приемки

1. Все ответы приходят в Telegram HTML (`<b>`, `<i>`, `<code>`), не Markdown.
2. Для create/edit/reschedule есть явное подтверждение изменения.
3. Для list есть корректные статус-иконки (`▶️`, `⏸`, `✅`, `🗑`).
4. Негативные кейсы не падают в ошибку 500, а дают понятный текст.
5. RU/ES запросы отвечаются на том же языке.
