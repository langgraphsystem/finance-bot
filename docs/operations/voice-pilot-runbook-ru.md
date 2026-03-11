# Runbook: Voice Pilot

Дата: 2026-03-10  
Контур: OpenAI Realtime GA + Twilio Voice + Twilio SMS + Redis

## 1. Цель пилота

Пилот должен запускать voice как новый канал того же агента, что и Telegram-бот.

На первом этапе voice должен:

- принимать inbound calls;
- отвечать как receptionist;
- уметь брать message;
- уметь запускать callback fallback;
- уметь отправлять approval в Telegram;
- уметь делать SMS verification;
- не выходить за rollout switches.

## 2. Рекомендуемый rollout profile

### Phase 1: Safe receptionist pilot

```env
VOICE_ENABLED=true
VOICE_ALLOW_OUTBOUND=false
VOICE_ALLOW_WRITE_TOOLS=false
VOICE_RECEPTIONIST_ONLY=true
VOICE_FORCE_CALLBACK_MODE=true
```

Ожидаемое поведение:

- voice отвечает на входящий звонок;
- voice не делает write actions;
- voice может взять message;
- voice может создать callback task;
- owner получает Telegram summary.

### Phase 2: Verified inbound operations

```env
VOICE_ENABLED=true
VOICE_ALLOW_OUTBOUND=false
VOICE_ALLOW_WRITE_TOOLS=true
VOICE_RECEPTIONIST_ONLY=false
VOICE_FORCE_CALLBACK_MODE=false
```

Ожидаемое поведение:

- verified callers могут делать ограниченные booking updates;
- approval-required actions остаются через Telegram;
- callback fallback остаётся доступным.

### Phase 3: Outbound confirmation pilot

```env
VOICE_ENABLED=true
VOICE_ALLOW_OUTBOUND=true
VOICE_ALLOW_WRITE_TOOLS=true
VOICE_RECEPTIONIST_ONLY=false
VOICE_FORCE_CALLBACK_MODE=false
```

Ожидаемое поведение:

- outbound confirmation/reschedule calls разрешены;
- ops team следит за `/voice/ops/overview`.

## 3. Предстартовые проверки

### Конфиг

Проверить:

- `OPENAI_API_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `REDIS_URL`
- `VOICE_PUBLIC_BASE_URL`
- `VOICE_WS_BASE_URL`
- `VOICE_DEFAULT_OWNER_TELEGRAM_ID`

### Readiness endpoint

Проверить:

```bash
curl https://<app>/voice/ops/readiness
```

Ожидаемо:

- `"ready": true`
- обязательные checks имеют `"ok": true`

### Rollout switches

Проверить:

```bash
curl https://<app>/voice/ops/switches
```

Ожидаемо:

- switches соответствуют выбранной фазе rollout

## 4. Smoke run sequence

### Smoke 1: Disabled mode

1. Поставить `VOICE_ENABLED=false`
2. Позвонить на номер Twilio
3. Убедиться, что TwiML возвращает graceful fallback

### Smoke 2: Safe receptionist mode

1. Поставить Phase 1 rollout profile
2. Позвонить с неизвестного номера
3. Спросить про услуги/часы
4. Попросить callback
5. Проверить:
   - создан callback task;
   - caller получает SMS confirmation;
   - owner получает Telegram summary;
   - `/voice/review/recent` содержит новый call review

### Smoke 3: Verification flow

1. Поставить Phase 2 rollout profile
2. Позвонить с номера, который не matched в CRM
3. Попросить действие, требующее verification
4. Запустить `request_verification`
5. Продиктовать code через `verify_caller`
6. Проверить:
   - auth state в review = `verified_by_sms`
   - action policy поднимается до verified tier

### Smoke 4: Approval flow

1. Позвонить и запросить sensitive action
2. Проверить:
   - Telegram approval пришёл owner'у
   - в trace есть `approval_requested`
   - review содержит approvals count

### Smoke 5: Outbound pilot

1. Поставить Phase 3 rollout profile
2. Запустить outbound call на тестовый номер
3. Проверить:
   - Twilio outbound webhook отрабатывает;
   - realtime session отвечает;
   - summary сохраняется;
   - `/voice/ops/overview` отражает звонок

## 5. Dry run перед первым реальным клиентом

Сделать 3 внутренних звонка:

1. неизвестный caller, только FAQ;
2. callback scenario;
3. verification + booking update scenario.

Для каждого проверить:

- summary;
- review snapshot;
- QA flags;
- Telegram follow-up;
- SMS fallback;
- отсутствие realtime errors.

## 6. Аварийные режимы

### Если booking actions ведут себя нестабильно

Переключить:

```env
VOICE_ALLOW_WRITE_TOOLS=false
VOICE_RECEPTIONIST_ONLY=true
VOICE_FORCE_CALLBACK_MODE=true
```

### Если outbound path нестабилен

Переключить:

```env
VOICE_ALLOW_OUTBOUND=false
```

### Если voice целиком нужно отключить

Переключить:

```env
VOICE_ENABLED=false
```

## 7. Что смотреть в первые 24 часа

- `/voice/ops/overview`
- `/voice/review/recent`
- `approval_requested` volume
- `schedule_callback` volume
- `handoff_to_owner` volume
- `realtime_error` flags
- verification completion rate
- average duration

## 8. Критерий успешного пилота

Пилот считается успешным, если:

- inbound receptionist flow стабилен;
- callback fallback отрабатывает без ручного ремонта;
- approval delivery в Telegram стабильна;
- verification flow работает на реальных номерах;
- нет критических realtime transport errors;
- owner принимает summaries и handoffs без потери контекста.
