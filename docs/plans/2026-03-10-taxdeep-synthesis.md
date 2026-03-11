# TaxDeep Synthesis — Ключевые находки taxdeep1 + taxdeep2 (2026-03-10)

> Интеграция обоих глубоких исследований в конкретные изменения для нашего проекта.

---

## ЧАСТЬ 1: КРИТИЧЕСКИЕ НАХОДКИ ИЗ TAXDEEP1

### 1.1 IRS AI Governance — IRM 10.24.1 (вступил в силу 10.02.2026)

IRS официально ввёл AI-governance через Internal Revenue Manual. Обязательно учитывать:

| Требование | Что означает для нас |
|-----------|---------------------|
| **Запрет PII/FTI в публичные AI** | Не отправлять SSN, EIN, полные суммы в LLM без токенизации |
| **Human review перед использованием вывода AI** | HITL checkpoint в нашем графе — не опция, а best practice |
| **Audit trail** | Логировать все LLM-вызовы: hash промпта, hash ответа, model snapshot |
| **Prompt logs 1 год** | В Langfuse (уже интегрирован через `@observe`) |
| **Прозрачность AI** | Disclaimer в каждом отчёте: "Создано с помощью AI" |

### 1.2 VITA GenAI Chatbot PoC (IRS, Jan–Apr 2025)

Прецедент: IRS сам использовал **RAG на публичных IRS PDF** для помощи волонтёрам VITA. Архитектура:
- Источник знаний: копии публичных PDF с IRS.gov (Pub 334, 505, 463, 15, etc.)
- Хранение PII: отдельно от LLM-контекста (Teams + invite)
- Инфраструктура: AWS + GCP

**Вывод**: RAG на IRS Publications — это официально одобренный IRS паттерн. Нужно реализовать.

### 1.3 Государственные чатботы — best practices штатов

| Штат | Инструмент | Ключевой паттерн |
|------|-----------|-----------------|
| Missouri | DORA | 11M+ обращений; 24/7 поддержка налоги+DMV |
| Ohio | Virtual Assistant | Явный disclaimer "chatbot, not human" + escalation |
| Illinois | Virtual Assistant | "Это чатбот" в первом сообщении |
| California FTB | Chat | Разделение: general (без аккаунта) vs MyFTB (с аккаунтом) |
| Nevada | ChatGPT-based | Упрощение налоговых текстов для малого бизнеса |

**Применяем в нашем боте**:
- Первое сообщение при tax_report: "Это AI-ассистент. Расчёты информационные, не налоговый совет."
- Эскалация: при needs_cpa=True — "Рекомендую проконсультироваться с CPA"

### 1.4 Fine-tuning — реальность на 2026-03-10

- **GPT-5.4**: `Fine-tuning: Not supported` в документации
- **Claude 4.6**: no self-serve fine-tuning ("ask Anthropic contact")

**Вывод**: Fine-tuning нам недоступен. Стратегия: **RAG + prompt engineering + structured outputs + deterministic engine**.

### 1.5 Инструменты из taxdeep1 — что добавить

| Инструмент | GitHub | Роль у нас |
|-----------|--------|-----------|
| **Tax-Calculator (PSL)** | PSLmodels/Tax-Calculator | Federal deterministic calc (замена нашего `_apply_brackets`) |
| **PolicyEngine US** | PolicyEngine/policyengine-us | Federal + все 50 штатов (замена STATE_TAX_CONFIG) |
| **Ragas** | vibrantlabsai/ragas | RAG evaluation (faithfulness, relevance) |
| **Qdrant** | qdrant/qdrant | Векторный поиск для IRS Publications RAG |
| **Unstructured** | Unstructured-IO/unstructured | Парсинг IRS PDF → элементы для RAG |
| **LiteLLM** | BerriAI/litellm | Унификация вызовов (у нас уже есть свой router, не нужен) |
| **Temporal** | temporalio/temporal | Durable execution (у нас LangGraph — достаточно) |
| **OPA** | open-policy-agent/opa | Policy-as-code для PII-gates (future) |

---

## ЧАСТЬ 2: КРИТИЧЕСКИЕ НАХОДКИ ИЗ TAXDEEP2

### 2.1 FIRE System EOL — КРИТИЧНО для продакшна

**FIRE system (форма 1099 от плательщиков) прекращает работу 31 декабря 2026!**

Замена: **IRIS (Information Returns Intake System)** — REST API вместо SOAP.

| | FIRE (старый) | IRIS (новый) |
|--|--------------|-------------|
| Тип | HTTPS file upload | REST API |
| Auth | Пароль | API Client ID + JWT |
| Deadline | EOL 31.12.2026 | Обязательно с 2027 |
| Критичное | — | **XSD ошибки = нет замены = штрафы** |

**Для нашего бота**: мы не пайер, не подаём 1099 — прямо не касается. Но пользователи (бизнесы) ДОЛЖНЫ знать: если они выдают 1099-NEC подрядчикам, FIRE уходит. Добавить в narrative.

### 2.2 MeF WSDL R10.9 — технические стандарты e-filing

Если когда-нибудь будем делать actual e-filing:
- SOAP + MTOM + ZIP-контейнеры
- SHA-256 обязательно (SHA-1 удалён)
- TLS 1.2+
- X.509 сертификаты (IDenTrust/ORC)
- SOR (Secure Object Repository) для скачивания схем — 60-дней авто-удаление

**Сейчас**: наш бот — advisory, не e-filing. MeF не нужен. Фиксируем для будущего.

### 2.3 PolicyEngine — ГЛАВНАЯ НАХОДКА для нас

**PolicyEngine US** — open-source библиотека, покрывающая федеральный + все 50 штатов.

```python
# Установка
# pip install policyengine-us

import policyengine_us as pe

sim = pe.Simulator(period=2026)
sim.set_input("employment_income", 75_000)
sim.set_input("self_employment_income", 50_000)
sim.set_input("state_code", "CA")
sim.set_input("filing_status", "single")

# Все расчёты детерминированные
federal_income_tax = sim.calculate("income_tax")
state_income_tax = sim.calculate("state_income_tax")
se_tax = sim.calculate("self_employment_tax")
qbi_deduction = sim.calculate("qualified_business_income_deduction")
```

**Это заменяет:**
- Наш `BRACKETS_2026_SINGLE` (ошибочный)
- Наш `STATE_TAX_CONFIG` (неполный)
- Наш `_apply_brackets()` (упрощённый)
- Наш `calculate_state_tax()` (примерный)

**Архитектура PolicyEngine**:
- YAML параметры (версионированные по году): `gov.irs.credits.ctc.amount.base_amount`
- Variables как вычисляемые узлы (AGI → deductions → tax)
- NumPy-векторизация для быстрых расчётов
- Обновляется сообществом (экономисты + юристы)

### 2.4 Synedrion — Metamorphic Testing для наших расчётов

**Synedrion** — фреймворк для логической консистентности без ground truth:

```python
# Логика метаморфного тестирования для нашего calculate_tax:
def metamorphic_tax_test(base_income: float, tax_result: float) -> bool:
    """Проверяем монотонность: +$10 дохода → налог должен вырасти."""
    shifted_result = calculate_tax_sync(base_income + 10)
    delta = shifted_result - tax_result

    # Налог НЕ может уменьшиться при росте дохода (монотонность)
    if delta < 0:
        logger.error("METAMORPHIC FAIL: income+$10 → tax decreased by $%.2f", abs(delta))
        return False

    # Налог не должен расти более чем на $10 (ставка ≤ 100%)
    if delta > 10:
        logger.error("METAMORPHIC FAIL: tax increased by $%.2f on $10 income", delta)
        return False

    return True
```

**Добавить в наш `calculate_tax` нод**: пост-расчётная проверка монотонности.

### 2.5 Claude 4.6 Agent Teams — паттерн для нашего оркестратора

Из taxdeep2: Claude 4.6 поддерживает **2-16 независимых агентов** с:
- Shared task list (`~/.claude/tasks/{team-name}/`)
- P2P mailbox protocol (SendMessage/broadcast)
- Delegate Mode: главный агент только декомпозирует, не выполняет
- Shell hooks: TeammateIdle → авто-запуск тестов → отчёт в inbox

**Применимо к нашему TaxReportOrchestrator**:

```yaml
# Концептуальная схема команды агентов:
team: tax_report_team
agents:
  - name: federal_agent
    model: claude-haiku-4-5
    task: "Analyze federal deductions from expense data"

  - name: state_agent
    model: claude-haiku-4-5
    task: "Apply state-specific tax rules for {state}"

  - name: audit_agent
    model: claude-opus-4-6
    task: "Verify consistency of all calculations"
    mode: delegate  # только проверяет, не считает
```

**В нашей реализации**: используем LangGraph параллельные ноды вместо Claude Agent Teams — это эквивалентно и уже реализовано.

### 2.6 GPT-5.4 новые возможности (для будущего)

| Функция | Возможность |
|---------|------------|
| **Responses API** | Stateful reasoning: `previous_response_id` = 80% cache hit rate |
| **defer_loading tools** | 47% reduction для 1000+ API schemas |
| **Computer Use API** | Автоматизация legacy порталов (county tax offices) |

**Для нашего бота**: GPT-5.2 уже интегрирован. GPT-5.4 — следующая версия. Не меняем пока.

### 2.7 Zero Trust + PII Tokenization — паттерн безопасности

```python
# Обязательный паттерн перед передачей данных в LLM:

class PiiTokenizer:
    """Tokenize PII before LLM context."""

    def __init__(self):
        self._map: dict[str, str] = {}
        self._counter = 0

    def tokenize(self, value: str, pii_type: str) -> str:
        """Replace PII with token."""
        token = f"[{pii_type.upper()}_{self._counter}]"
        self._map[token] = value
        self._counter += 1
        return token

    def detokenize(self, text: str) -> str:
        """Restore original values after LLM processing."""
        for token, value in self._map.items():
            text = text.replace(token, value)
        return text

# Использование в collect_documents:
tokenizer = PiiTokenizer()
safe_ssn = tokenizer.tokenize(ssn_last4, "ssn")     # → "[SSN_0]"
safe_ein = tokenizer.tokenize(employer_ein, "ein")   # → "[EIN_1]"
# Передаём safe_* в LLM, детокенизируем результат
```

### 2.8 Local XSD Validation — обязательный gate

```python
from lxml import etree

def validate_tax_xml(xml_content: bytes, xsd_path: str) -> list[str]:
    """Validate XML against IRS XSD schema BEFORE any API call."""
    schema_doc = etree.parse(xsd_path)
    schema = etree.XMLSchema(schema_doc)
    doc = etree.fromstring(xml_content)

    if not schema.validate(doc):
        errors = [str(e) for e in schema.error_log]
        logger.error("XSD validation failed: %s", errors)
        return errors
    return []

# В пайплайне: XSD validate → если ошибки → СТОП (не отправлять в IRS!)
# Критично для IRIS: ошибки XSD = нет замены = штрафы
```

---

## ЧАСТЬ 3: ПРИОРИТИЗАЦИЯ ИЗМЕНЕНИЙ ДЛЯ НАШЕГО ПРОЕКТА

### 3.1 Немедленно (Phase 1 — эта неделя)

#### A. Исправить математику через PolicyEngine

```python
# Установить: uv add policyengine-us
# Заменить calculate_federal_tax и calculate_state_tax:

import policyengine_us as pe

async def calculate_tax_policyengine(state: TaxReportState) -> TaxReportState:
    """Replace all manual bracket calculations with PolicyEngine."""
    sim = pe.Simulator(period=state["year"])

    # Input
    sim.set_input("self_employment_income", state["gross_income"])
    sim.set_input("state_code", state.get("state", "TX"))
    sim.set_input("filing_status", state.get("filing_status", "single"))

    # All outputs — deterministic and correct
    return {
        **state,
        "se_tax": float(sim.calculate("self_employment_tax")),
        "se_deduction": float(sim.calculate("self_employment_tax_deduction")),
        "qbi_deduction": float(sim.calculate("qualified_business_income_deduction")),
        "standard_deduction": float(sim.calculate("standard_deduction")),
        "taxable_income": float(sim.calculate("taxable_income")),
        "income_tax": float(sim.calculate("income_tax")),
        "state_income_tax": float(sim.calculate("state_income_tax")),
        "total_federal_tax": float(sim.calculate("income_tax"))
                           + float(sim.calculate("self_employment_tax")),
    }
```

#### B. Добавить PII tokenization перед LLM

```python
# В collect_documents: токенизировать SSN/EIN до передачи в Gemini OCR
# Детокенизировать только для хранения в БД (not in LLM context)
```

#### C. Добавить metamorphic test в calculate_tax

```python
# После calculate_tax: проверить монотонность
# income + $100 → tax должен вырасти на $10-$37 (по marginal rate)
```

### 3.2 Phase 2 (следующая неделя)

#### D. RAG на IRS Publications

```
Источники для RAG:
1. IRS Pub 334 (Schedule C guide) — https://www.irs.gov/pub/irs-pdf/p334.pdf
2. IRS Pub 505 (Estimated Tax) — https://www.irs.gov/pub/irs-pdf/p505.pdf
3. IRS Pub 463 (Travel, Vehicle) — https://www.irs.gov/pub/irs-pdf/p463.pdf
4. IRS Pub 946 (Depreciation) — https://www.irs.gov/pub/irs-pdf/p946.pdf
5. IRS Pub 587 (Home Office) — https://www.irs.gov/pub/irs-pdf/p587.pdf

Пайплайн:
PDF → Unstructured (парсинг) → chunks → embeddings → Qdrant (vector store)
Query → similarity search → Claude Haiku (generates answer + cites source)

Хранить:
- pub_number, section, year, page (для citation)
- Обновлять ежегодно (pub 334 выходит каждый январь)
```

#### E. Добавить уведомление о FIRE EOL

```python
# В generate_narrative: если business_type and year == 2026:
fire_note = (
    "\n\n<b>⚠️ Важно для вашего бизнеса:</b> "
    "Система FIRE (подача 1099 в IRS) прекращает работу 31.12.2026. "
    "С 2027 года — только IRIS REST API. Обновите ваше ПО для 1099."
)
```

### 3.3 Phase 3+ (будущее)

| Идея | Источник | Сложность |
|------|---------|----------|
| Unstract для локальной обработки FTI | taxdeep2 | Высокая |
| Ragas eval для нашего RAG | taxdeep1 | Средняя |
| OPA policy gates для PII | taxdeep1 | Высокая |
| DSPy для оптимизации промптов | taxdeep2 | Средняя |
| Synedrion полная реализация | taxdeep2 | Средняя |

---

## ЧАСТЬ 4: ОБНОВЛЁННЫЙ ПОЛНЫЙ ГРАФ (с учётом всех находок)

```
START
  ├── collect_income [SQL, no LLM]
  ├── collect_expenses [SQL, no LLM]
  ├── collect_recurring [SQL, no LLM]
  ├── collect_prior_year [SQL, no LLM]
  └── collect_documents [Gemini Flash Lite OCR + PII tokenizer]
                    │
                    ▼
         analyze_deductions [Claude Haiku 4.5 + RAG IRS Publications + whitelist]
                    │
                    ▼
         calculate_obbba_adjustments [Python deterministic]
                    │
                    ▼
         calculate_tax_policyengine [PolicyEngine US — федеральный + штат]
                    │
                    ▼
         metamorphic_consistency_check [Python: monotonicity test]
                    │
         ┌──────────┤
         │ FAIL     │ PASS
         ▼          ▼
      flag+log   calculate_retirement_opportunity [Python]
                    │
              ┌─────┤ если needs_cpa или gross > $100K
              │     │
              ▼     ▼
    analyze_complex  │
    [Claude Opus +   │
     extended think] │
              │     │
              └──┬──┘
                 │
                 ▼
        ── HITL: review_deductions ──
           interrupt() → кнопки Telegram
        ─────────────────────────────
                 │ approved
                 ▼
         generate_narrative [Claude Sonnet 4.6]
         + FIRE EOL notice если бизнес
                 │
                 ▼
         generate_schedule_c_worksheet [Python]
                 │
                 ▼
         generate_quarterly_vouchers [Python, CA=30/40/0/30]
                 │
                 ▼
         generate_pdf [WeasyPrint]
         + audit_log [prompt hashes, model snapshots]
                 │
                 ▼
                END
```

---

## ЧАСТЬ 5: ОБЯЗАТЕЛЬНЫЕ DISCLAIMERS (IRS IRM паттерн)

### По аналогии с IRS AI governance:

```python
TAX_AI_DISCLAIMERS = {
    "en": (
        "⚠️ This report was generated using AI and deterministic tax calculations. "
        "It is for informational purposes only and does not constitute professional "
        "tax advice. AI-assisted content — please review with a licensed CPA before filing. "
        "Calculations based on IRS publications and PolicyEngine US model."
    ),
    "ru": (
        "⚠️ Этот отчёт создан с помощью AI и детерминированных налоговых расчётов. "
        "Носит информационный характер и не является профессиональной налоговой консультацией. "
        "Создано с помощью AI — проверьте с лицензированным CPA перед подачей декларации."
    ),
}

# Audit log entry для каждого tax report:
AUDIT_LOG_FIELDS = {
    "timestamp": "ISO-8601",
    "user_id": "hashed",  # не raw
    "family_id": "hashed",
    "model_snapshot": "claude-haiku-4-5 / claude-sonnet-4-6",
    "prompt_hash": "SHA-256 of system prompt",
    "policyengine_version": "pe.__version__",
    "report_hash": "SHA-256 of output",
    "hitl_approved_by": "user_id or 'auto'",
}
```

---

## ИТОГОВАЯ ТАБЛИЦА ПРИОРИТЕТОВ (обновлённая с taxdeep1 + taxdeep2)

| # | Задача | Источник | Приоритет | Сложность |
|---|--------|---------|-----------|----------|
| 1 | **PolicyEngine US** вместо ручных brackets | taxdeep2 | 🔴 P0 | Средняя |
| 2 | Исправить standard deduction (критический баг) | наш анализ | 🔴 P0 | Низкая |
| 3 | Исправить brackets 2026 (OBBBA) | наш анализ | 🔴 P0 | Низкая |
| 4 | Применить mileage deduction | наш анализ | 🔴 P0 | Низкая |
| 5 | PII tokenization перед LLM | taxdeep2 | 🔴 P1 | Средняя |
| 6 | Metamorphic consistency check | taxdeep2 | 🟡 P1 | Низкая |
| 7 | State tax (50 штатов через PolicyEngine) | оба файла | 🔴 P1 | Средняя |
| 8 | FIRE EOL notice в narrative | taxdeep2 | 🟡 P2 | Низкая |
| 9 | CA quarterly 30/40/0/30 | наш анализ | 🟡 P2 | Низкая |
| 10 | OBBBA Tips/Overtime вычеты | наш анализ | 🟡 P2 | Низкая |
| 11 | SEP-IRA / Solo 401k optimizer | наш анализ | 🟡 P2 | Средняя |
| 12 | Audit logging (prompt hash, model snapshot) | taxdeep1 | 🟡 P2 | Низкая |
| 13 | RAG на IRS Publications (Pub 334, 505, 463) | taxdeep1 | 🟢 P3 | Высокая |
| 14 | OCR документов (Gemini Flash Lite) | наш план | 🟢 P3 | Средняя |
| 15 | HITL review checkpoint | наш план | 🟢 P3 | Средняя |
| 16 | Schedule C line-by-line PDF | наш план | 🟢 P3 | Высокая |
| 17 | 1040-ES vouchers | наш план | 🟢 P3 | Средняя |
| 18 | Ragas eval для RAG | taxdeep1 | ⚪ P4 | Средняя |
| 19 | Unstructured для FTI-safe OCR | taxdeep2 | ⚪ P4 | Высокая |
| 20 | DSPy prompt optimization | taxdeep2 | ⚪ P4 | Высокая |

---

*Синтез: taxdeep1.md + taxdeep2.md + наш предыдущий анализ. 2026-03-10.*
