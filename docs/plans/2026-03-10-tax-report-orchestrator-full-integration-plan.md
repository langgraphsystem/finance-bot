# TaxReportOrchestrator — Полный план интеграции (2026-03-10)

> Глубокий анализ IRS, всех 50 штатов, best practices, LLM-возможностей Claude/GPT,
> open-source инструментов и дорожная карта production-готового оркестратора.

---

## ЧАСТЬ 1: АНАЛИЗ IRS ИНФРАСТРУКТУРЫ

### 1.1 Что есть у IRS для разработчиков

| Система | Тип | Доступность | Применимость |
|---------|-----|-------------|--------------|
| MeF (Modernized e-File) | SOAP/XML | Только авторизованным провайдерам (EFIN) | E-filing returns |
| MeF XML Schemas (XSD) | Free download | Публично | Валидация форм |
| FIRE System | HTTPS upload | Авторизованным | 1099/W-2 payer filing |
| Transcript Delivery System (TDS) | API | Требует e-Services enrollment | Получить данные клиента |
| IRS Direct File | Web UI | Публично | НЕ поддерживает Schedule C |
| IRS Interactive Tax Assistant | Rule-based Q&A | Публично | НЕ LLM |
| IRS Statistics of Income (SOI) | CSV/Excel | Публично | Агрегированные данные |
| IRS2Go | Mobile | Публично | Только статус возврата |

**Ключевой вывод**: Прямой REST API у IRS отсутствует. Для e-filing нужен EFIN (6+ месяцев процесса). Для нашего бота — это advisory/estimation tool, не e-filing, значит EFIN не нужен.

### 1.2 MeF XML Schemas — что можно использовать бесплатно

Схемы скачиваются с https://www.irs.gov/e-file-providers/modernized-e-file-mef-schemas-and-business-rules

Используем для:
- Валидации наших расчётов соответствия IRS-формату
- Генерации PDF-превью с правильными полями
- Понимания структуры каждой формы (что входит в Schedule C Line 28, 30, etc.)

### 1.3 Практические интеграции без EFIN

| Интеграция | API | Стоимость | Что даёт |
|-----------|-----|-----------|---------|
| **TaxJar** | REST `api.taxjar.com/v2/rates/{zip}` | $19/мес | Sales tax по ZIP-коду |
| **Tax1099 / TaxBandits** | REST | $1-3/форма | E-file 1099-NEC за пользователей |
| **Azure Document Intelligence** | REST | $0.001/стр | OCR: W-2, 1099, Schedule C |
| **IRS Pub PDFs** | Direct download | Free | Официальные формы для заполнения |

---

## ЧАСТЬ 2: КРИТИЧЕСКИЕ БАГИ В ТЕКУЩЕМ КОДЕ

### 2.1 Неверные налоговые скобки 2026

**Текущий код** (`deductions.py`):
```python
BRACKETS_2026_SINGLE = [
    (11_925, 0.10),
    (48_475, 0.12),
    (103_350, 0.22),
    (197_300, 0.24),
    (250_525, 0.32),
    (626_350, 0.35),
    (float("inf"), 0.37),
]
```

**Правильные скобки 2026 (после OBBBA, July 4, 2025)**:
```python
BRACKETS_2026_SINGLE = [
    (12_400, 0.10),    # +4% extra inflation adjust (bottom brackets)
    (50_400, 0.12),    # +4% extra
    (107_550, 0.22),   # +2.3%
    (205_600, 0.24),
    (261_100, 0.32),
    (640_600, 0.35),
    (float("inf"), 0.37),
]
# OBBBA: top rate threshold $640,600 (был $626,350)
```

### 2.2 Стандартный вычет не применяется — КРИТИЧЕСКИЙ БАГ

**Проблема**: `calculate_tax()` применяет скобки к `adjusted_income - qbi_deduction`, но не вычитает standard deduction $16,100 (single 2026).

Текущий код:
```python
taxable = max(adjusted_income - qbi_deduction, 0.0)
income_tax = _apply_brackets(taxable)  # НЕВЕРНО — нет standard deduction
```

Правильно:
```python
STANDARD_DEDUCTION_2026 = {
    "single": 16_100,
    "mfj": 32_200,
    "hoh": 24_150,
    "mfs": 16_100,
}
standard_ded = STANDARD_DEDUCTION_2026.get(filing_status, 16_100)
taxable = max(adjusted_income - qbi_deduction - standard_ded, 0.0)
```

**Impact**: Для net_profit $60K переплата = $16,100 × 22% = **$3,542 за год**.

### 2.3 Mileage deduction не применяется к расчёту

**Проблема**: `collect_mileage` возвращает `mileage_miles`, но в `analyze_deductions` они не добавляются в `total_deductible`.

```python
# nodes.py: mileage_miles вычислен, но не используется!
# Нужно добавить в analyze_deductions:
mileage_deduction = state.get("mileage_miles", 0) * MILEAGE_RATE_2026
# И включить в total_deductible
```

**Текущая ставка**: IRS 2025 = **$0.70/mile** (наш код: $0.725 — неверно для 2025)

### 2.4 Proxy-расчёт mileage некорректен

```python
mileage_miles = transport_spend / 0.30  # Неверно! $0.30 не реальная ставка
```

$0.30 — средняя стоимость топлива, не IRS rate. IRS standard mileage = $0.70/mile.
Правильная логика: нельзя конвертировать деньги в мили без данных одометра.

**Решение**: убрать proxy, добавить поле `mileage_miles` напрямую через IntentData или отдельный трекер.

### 2.5 SE Health Insurance — нет проверки лимита

```python
"Медицина": ("health_insurance", 1.0),  # неограниченный вычет
```

IRS правило: SE health insurance deduction ≤ net_profit. Нельзя создать убыток. Нужна проверка.

### 2.6 Новые вычеты OBBBA не реализованы

One Big Beautiful Bill Act (July 4, 2025) ввёл новые above-the-line вычеты (Schedule 1-A):

| Вычет | Лимит | Phase-out | Применимость |
|-------|-------|-----------|-------------|
| Tips (чаевые) | $25,000 | >$150K single | Официанты, доставщики |
| Overtime pay | $12,500 | >$150K single | W-2 + self-employed |
| Auto loan interest | $10,000 | >$100K single | US-assembled vehicles only |
| Senior deduction (65+) | $6,000 | >$75K single | Пожилые клиенты |

---

## ЧАСТЬ 3: АНАЛИЗ ВСЕХ 50 ШТАТОВ

### 3.1 Классификация штатов

**9 штатов без income tax** (нулевой расчёт):
TX, FL, NV, WY, SD, AK, TN, NH (0% с 2026), WA

**13 штатов с flat tax** (один коэффициент):

| Штат | Ставка | Примечание |
|------|--------|-----------|
| AZ | 2.5% | Самая низкая |
| CO | 4.4% | |
| GA | 5.39% | Снижается |
| ID | 5.695% | |
| IL | 4.95% | Конституционный |
| IN | 3.05% | |
| IA | 3.8% | |
| KY | 4.0% | |
| MI | 4.05% | |
| NC | 4.5% | |
| PA | 3.07% | Независимая система |
| UT | 4.65% | |
| MS | 4.7% | |

**Топ-5 высоконалоговых штатов для self-employed**:

| Штат | Top rate | QBID | SE-специфика |
|------|----------|------|-------------|
| CA | 13.3% | Нет | SDI 1.1% (опц) |
| NY | 10.9% + 3.876% NYC | Нет | MCTMT 0.34% |
| NJ | 10.75% | Нет | — |
| OR | 9.9% | Нет | Transit 0.1% |
| MN | 9.85% | Нет | — |

### 3.2 Критическая особенность — CA quarterly schedule

Калифорния: **30%/40%/0%/30%** (НЕ 25% каждый квартал!)

```python
# deductions.py — нужно добавить:
CA_QUARTERLY_SCHEDULE = [0.30, 0.40, 0.00, 0.30]  # Q1/Q2/Q3/Q4
CA_QUARTERLY_DATES = ["April 15", "June 15", None, "January 15"]
```

### 3.3 Штаты без QBID conformity (не принимают federal 20% вычет)

- **California** — нет QBID
- **New York** — нет QBID
- **New Jersey** — нет QBID
- **Pennsylvania** — независимая система

Вывод: для пользователей из этих штатов QBI вычет применяется только на federal уровне.

### 3.4 Городские налоги (дополнительные)

| Город | Налог | Ставка |
|-------|-------|--------|
| NYC | City income tax | 3.078%–3.876% |
| NYC | UBT (Unincorporated Business Tax) | 4% net income |
| NYC | MCTMT | 0.34% SE > $50K |
| Philadelphia | Net Profits Tax | 3.75% residents |
| Philadelphia | NPT non-resident | 2.8% |
| Chicago | Personal property lease | varies |
| Portland OR | Arts tax | $35/year |

### 3.5 Соответствие дедлайнов по штатам

| Штат | Дедлайн | Примечание |
|------|---------|-----------|
| Большинство | April 15 | Следуют federal |
| Virginia | May 1 | Постоянное исключение |
| Louisiana | May 15 | |
| Hawaii | April 20 | |
| Iowa | April 30 | |
| Delaware | April 30 | |

---

## ЧАСТЬ 4: LLM ВОЗМОЖНОСТИ НА 03/10/2026

### 4.1 Claude (Anthropic) — применение в налогах

| Модель | Контекст | Tax Use Case |
|--------|----------|-------------|
| Claude Opus 4.6 | 200K | Анализ сложных сценариев, multi-doc, AMT |
| Claude Sonnet 4.6 | 200K | Объяснение вычетов, деловые советы |
| Claude Haiku 4.5 | 200K | Быстрая классификация, deduction hints |

**Сильные стороны Claude для налогов**:
- 200K контекст = весь налоговый год транзакций одновременно
- Extended thinking (Opus) = многошаговые tax planning сценарии
- Tool use = вызов deterministic tax calculators из LLM
- Document processing = W-2, 1099, Schedule C из base64 PDF
- Structured output = гарантированный JSON для налоговых форм

**Паттерн RAG для налогового кодекса**:
```python
# IRS publications как RAG corpus:
# Publication 334 (Schedule C), 505 (estimated tax), 15, 463, 946
# Суммарно ~3000 страниц → vector embeddings
# Claude делает retrieval + reasoning поверх
```

### 4.2 GPT-5.2 (OpenAI) — применение в налогах

| Сила | Tax Use Case |
|------|-------------|
| Function calling | Вызов tax calculation tools |
| Structured outputs | JSON schema для tax forms |
| Code interpreter | Прямые расчёты в sandbox |
| Vision | Чтение PDF/изображений форм |

**TaxGPT** использует комбинацию GPT-4o + Claude 3.5:
- Архитектура: domain-specific RAG против 800+ IRS.gov citations
- Средняя плотность цитат: 14 источников на ответ (vs 3 у general AI)
- Результат: near-0% hallucination rate

### 4.3 Правильный LLM/deterministic split (production pattern)

**TurboTax GenOS принцип**: LLM НИКОГДА не касается расчётов

```
User Input
  ├─► LLM (понять намерение, задать вопросы, объяснить результат)
  └─► Tax Engine (100% deterministic: скобки, лимиты, формулы)
      └─► LLM (нарративное объяснение результата)
```

| Компонент | Должен быть | Никогда не |
|-----------|------------|-----------|
| Налоговые скобки | Deterministic code | LLM |
| Standard deduction | Deterministic code | LLM |
| SE tax формула | Deterministic code | LLM |
| QBI расчёт | Deterministic code | LLM |
| AMT | Deterministic code | LLM |
| Объяснение вычета | LLM + RAG | Hardcode |
| Missed deductions | LLM с whitelist | LLM без whitelist |
| Planning scenarios | LLM + deterministic calc | LLM alone |
| Document Q&A | LLM + RAG | Deterministic |

### 4.4 Azure Document Intelligence для OCR

**Prebuilt tax models** (production-ready):
- `prebuilt-tax.us.w2` → W-2 в JSON
- `prebuilt-tax.us.1099NEC` → 1099-NEC в JSON
- `prebuilt-tax.us.1040ScheduleC` → Schedule C в JSON
- `prebuilt-tax.us` → автодетект типа формы

```python
# Интеграция в новый collect_documents node:
from azure.ai.formrecognizer import DocumentAnalysisClient

async def analyze_tax_document(pdf_bytes: bytes) -> dict:
    client = DocumentAnalysisClient(endpoint, credential)
    poller = await client.begin_analyze_document("prebuilt-tax.us", pdf_bytes)
    result = await poller.result()
    return extract_fields(result)
```

---

## ЧАСТЬ 5: OPEN-SOURCE ИНСТРУМЕНТЫ

### 5.1 Налоговые расчёты

| Библиотека | PyPI | Stars | Что делает |
|-----------|------|-------|-----------|
| **Tax-Calculator** (PSL) | `taxcalc` | 700+ | US individual income tax microsimulation. 1040, SE, credits. Используется Congressional Budget Office. |
| **OpenFisca-US** | `openfisca-us` | 200+ | Policy microsimulation, IRS-aligned. Поддерживает 50 штатов. |
| **TaxBrain** | `taxbrain` | 150+ | Обёртка над Tax-Calculator для web API |
| `python-taxjar` | `taxjar` | Official | Sales tax по ZIP |
| `avalara-sdk` | `avalara` | Official | Enterprise sales tax |

**Tax-Calculator (taxcalc)** — наиболее полная:
```python
import taxcalc as tc

# Создать запись для self-employed
rec = tc.Records.from_dataframe(df_with_income)
pol = tc.Policy()
calc = tc.Calculator(policy=pol, records=rec)
calc.calc_all()
# Получить SE tax, income tax, QBI
df_results = calc.dataframe(['iitax', 'payrolltax', 'combined'])
```

### 5.2 PDF generation для форм

| Библиотека | Применение |
|-----------|-----------|
| `reportlab` | Генерация PDF с точным позиционированием (для IRS-формат) |
| `weasyprint` | HTML → PDF (уже используем) |
| `pypdf` | Заполнение fillable PDF (IRS forms) |
| `pdfrw` | Манипуляция PDF |
| `fpdf2` | Простые PDF |

**Fillable IRS PDFs** — лучший подход для Schedule C, 1040-ES:
```python
import pypdf

def fill_schedule_c(data: dict) -> bytes:
    reader = pypdf.PdfReader("forms/f1040sc.pdf")  # IRS form
    writer = pypdf.PdfWriter()
    writer.append(reader)
    writer.update_page_form_field_values(
        writer.pages[0],
        {
            "f1_1": data["business_name"],
            "f1_2": data["gross_receipts"],
            # ... все поля из MeF schema
        }
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
```

### 5.3 Document extraction

| Инструмент | Применение |
|-----------|-----------|
| `azure-ai-formrecognizer` | OCR tax documents (W-2, 1099) |
| `pdfplumber` | Извлечение текста из PDF |
| `pytesseract` | Fallback OCR |
| `unstract` | OSS framework для structured JSON из tax PDFs |

### 5.4 Mileage tracking

| Инструмент | API | Применение |
|-----------|-----|-----------|
| **MileIQ API** | REST | GPS mileage log import |
| **Everlance** | REST | Mileage + expense tracking |
| **Driversnote** | REST | IRS-compliant mileage reports |
| Google Maps API | REST | Distance calculation для trips |

---

## ЧАСТЬ 6: ПОЛНЫЙ ПЛАН REDESIGN TAXREPORTORCHESTRATOR

### 6.1 Новая архитектура графа

```
START
  ├── collect_income ──────────────────────────────────────┐
  ├── collect_expenses ────────────────────────────────────┤
  ├── collect_recurring ──────────────────────────────────┤
  ├── collect_mileage ───────────────────────────────────┤
  ├── collect_prior_year_tax (для safe harbor) ─────────┤
  ├── collect_w2_income (W-2 + другой доход) ───────────┤
  └── collect_documents (OCR W-2/1099 если загружены) ──┤
                                                          ▼
                                              analyze_deductions
                                                    │
                                                    ▼
                                          calculate_obbba_adjustments
                                          (Tips, Overtime, Auto, Senior)
                                                    │
                                                    ▼
                                          calculate_federal_tax
                                          (SE tax + brackets + QBI + std ded)
                                                    │
                                                    ▼
                                          calculate_state_tax
                                          (по штату из профиля)
                                                    │
                                                    ▼
                                          calculate_retirement_opportunity
                                          (SEP-IRA / Solo 401k savings)
                                                    │
                                                    ▼
                                          ┌─── HITL: review_deductions ──┐
                                          │    interrupt() → user review  │
                                          │    inline buttons: approve/edit│
                                          └───────────────────────────────┘
                                                    │
                                                    ▼
                                          generate_schedule_c_worksheet
                                                    │
                                                    ▼
                                          generate_quarterly_vouchers
                                          (1040-ES: 4 vouchers с датами)
                                                    │
                                                    ▼
                                          generate_pdf (multi-section)
                                                    │
                                                    ▼
                                                   END
```

### 6.2 Обновлённый TaxReportState

```python
class TaxReportState(TypedDict):
    # === Input ===
    user_id: str
    family_id: str
    language: str
    currency: str
    business_type: str | None
    state: str | None           # NEW: US state code (CA, NY, TX...)
    filing_status: str          # NEW: single/mfj/hoh/mfs
    year: int
    quarter: int | None
    home_office_sqft: float     # NEW: для Form 8829
    home_office_total_sqft: float  # NEW

    # === Collected data ===
    gross_income: float
    w2_income: float            # NEW: W-2 wages
    other_income: float         # NEW: interest, dividends
    expenses_by_category: list[dict]
    recurring_payments: list[dict]
    mileage_miles: float        # мили из трекера (не proxy!)
    prior_year_tax: float       # NEW: для safe harbor
    documents_extracted: list[dict]  # NEW: OCR результаты

    # === OBBBA adjustments ===
    tips_income: float          # NEW: чаевые
    overtime_pay: float         # NEW: переработки
    auto_loan_interest: float   # NEW: проценты по авто-кредиту
    is_senior: bool             # NEW: 65+ лет

    # === Deductions ===
    total_deductible: float
    deduction_breakdown: list[dict]
    mileage_deduction: float    # NEW: отдельно
    home_office_deduction: float  # NEW: Form 8829
    retirement_deduction: float   # NEW: SEP-IRA / Solo 401k
    obbba_deductions: float       # NEW: Tips + Overtime + etc
    additional_deductions: list[str]

    # === Federal tax ===
    standard_deduction: float   # NEW
    net_profit: float
    se_tax: float
    se_deduction: float
    qbi_deduction: float
    taxable_income: float       # NEW: после всех вычетов
    income_tax: float
    total_federal_tax: float    # NEW: SE + income tax

    # === State tax ===
    state_taxable_income: float  # NEW
    state_income_tax: float      # NEW
    state_rate_used: float       # NEW
    state_qbid_applies: bool     # NEW: CA/NY/NJ = False
    additional_state_taxes: list[dict]  # NEW: MCTMT, SDI, etc

    # === Retirement opportunity ===
    sep_ira_max: float          # NEW
    solo_401k_max: float        # NEW
    retirement_tax_savings: float  # NEW

    # === Total ===
    total_tax: float
    total_tax_with_state: float  # NEW
    effective_rate: float
    effective_rate_with_state: float  # NEW
    quarterly_payment: float
    quarterly_schedule: list[float]  # NEW: CA = [0.30,0.40,0.00,0.30]

    # === Output ===
    schedule_c_lines: dict      # NEW: line-by-line Schedule C
    quarterly_vouchers: list[dict]  # NEW: 1040-ES vouchers
    narrative: str
    pdf_bytes: bytes | None
    response_text: str
```

### 6.3 Обновлённый deductions.py

```python
# ИСПРАВЛЕНИЯ И ДОПОЛНЕНИЯ

# 2026 brackets ПОСЛЕ OBBBA (July 4, 2025)
BRACKETS_2026_SINGLE = [
    (12_400, 0.10),
    (50_400, 0.12),
    (107_550, 0.22),
    (205_600, 0.24),
    (261_100, 0.32),
    (640_600, 0.35),
    (float("inf"), 0.37),
]

BRACKETS_2026_MFJ = [
    (24_800, 0.10),
    (100_800, 0.12),
    (215_100, 0.22),
    (411_200, 0.24),
    (522_200, 0.32),
    (768_600, 0.35),
    (float("inf"), 0.37),
]

BRACKETS_2026_HOH = [
    (18_600, 0.10),
    (75_600, 0.12),
    (111_275, 0.22),
    (205_600, 0.24),
    (261_100, 0.32),
    (640_600, 0.35),
    (float("inf"), 0.37),
]

STANDARD_DEDUCTION_2026 = {
    "single": 16_100,
    "mfj": 32_200,
    "hoh": 24_150,
    "mfs": 16_100,
}

MILEAGE_RATE_2025 = 0.700   # 70 cents/mile (IRS 2025)
MILEAGE_RATE_2026 = 0.725   # estimate (IRS announces Dec 2025)

# OBBBA Schedule 1-A deductions (NEW July 4, 2025)
OBBBA_TIPS_LIMIT = 25_000
OBBBA_OVERTIME_LIMIT_SINGLE = 12_500
OBBBA_OVERTIME_LIMIT_MFJ = 25_000
OBBBA_AUTO_LOAN_LIMIT = 10_000
OBBBA_SENIOR_DEDUCTION = 6_000
OBBBA_TIPS_PHASEOUT_SINGLE = 150_000
OBBBA_TIPS_PHASEOUT_MFJ = 300_000

# SALT cap (OBBBA)
SALT_CAP_2026 = 40_400          # $40,000 * 1.01
SALT_PHASEOUT_START_MFJ = 500_000

# QBI 2026 (OBBBA permanent)
QBI_RATE = 0.20
QBI_PHASEOUT_START_SINGLE = 203_000   # 2026
QBI_PHASEOUT_END_SINGLE = 272_300
QBI_PHASEOUT_START_MFJ = 406_000
QBI_PHASEOUT_END_MFJ = 544_600

# SE tax
SE_TAX_RATE = 0.153
SE_NET_FACTOR = 0.9235
SE_DEDUCTION_FACTOR = 0.50
SS_WAGE_BASE_2026 = 176_100

# Home office simplified method
HOME_OFFICE_SIMPLIFIED_RATE = 5.0   # $5/sq ft
HOME_OFFICE_SIMPLIFIED_MAX_SQFT = 300
HOME_OFFICE_SIMPLIFIED_MAX = 1_500   # $5 * 300

# Retirement limits 2026
SEP_IRA_PCT = 0.25          # 25% of net SE income
SEP_IRA_MAX = 70_000        # 2025: $69K, 2026 est: $70K
SOLO_401K_EMPLOYEE_2026 = 23_500
SOLO_401K_CATCHUP_2026 = 7_500     # если 50+
SOLO_401K_EMPLOYEE_MAX = 31_000    # с catch-up

# State tax rates (flat или max для progressive)
# Источник: Tax Foundation, 2025 данные
STATE_TAX_CONFIG = {
    # format: {"type": "none"|"flat"|"progressive", "rate": float, "qbid": bool, "quarterly": [...]}
    "AK": {"type": "none", "qbid": True},
    "FL": {"type": "none", "qbid": True},
    "NV": {"type": "none", "qbid": True},
    "NH": {"type": "none", "qbid": True},   # 0% income tax 2026
    "SD": {"type": "none", "qbid": True},
    "TN": {"type": "none", "qbid": True},
    "TX": {"type": "none", "qbid": True},
    "WA": {"type": "none", "qbid": True},
    "WY": {"type": "none", "qbid": True},
    "AZ": {"type": "flat", "rate": 0.025, "qbid": True},
    "CO": {"type": "flat", "rate": 0.044, "qbid": True},
    "GA": {"type": "flat", "rate": 0.0539, "qbid": True},
    "IL": {"type": "flat", "rate": 0.0495, "qbid": False},
    "IN": {"type": "flat", "rate": 0.0305, "qbid": True},
    "IA": {"type": "flat", "rate": 0.038, "qbid": True},
    "KY": {"type": "flat", "rate": 0.040, "qbid": True},
    "MI": {"type": "flat", "rate": 0.0405, "qbid": True},
    "MS": {"type": "flat", "rate": 0.047, "qbid": True},
    "NC": {"type": "flat", "rate": 0.045, "qbid": True},
    "PA": {"type": "flat", "rate": 0.0307, "qbid": False},  # independent system
    "UT": {"type": "flat", "rate": 0.0465, "qbid": True},
    # Progressive (top rate для estimate):
    "CA": {"type": "progressive", "rate": 0.093, "qbid": False,
           "quarterly": [0.30, 0.40, 0.00, 0.30],
           "extras": [{"name": "SDI", "rate": 0.011, "optional": True}]},
    "NY": {"type": "progressive", "rate": 0.0965, "qbid": False,
           "extras": [{"name": "MCTMT", "rate": 0.0034, "threshold": 50000}]},
    "NJ": {"type": "progressive", "rate": 0.0637, "qbid": False},
    "OR": {"type": "progressive", "rate": 0.099, "qbid": True},
    "MN": {"type": "progressive", "rate": 0.0985, "qbid": True},
    "VT": {"type": "progressive", "rate": 0.0875, "qbid": True},
    "DC": {"type": "progressive", "rate": 0.0875, "qbid": True},
    "HI": {"type": "progressive", "rate": 0.11, "qbid": True},
    "ME": {"type": "progressive", "rate": 0.0715, "qbid": True},
    "ID": {"type": "flat", "rate": 0.05695, "qbid": True},
    "MT": {"type": "progressive", "rate": 0.059, "qbid": True},
    "WI": {"type": "progressive", "rate": 0.0765, "qbid": True},
    # ... добавить остальные
}

# Деловые дедлайны 2026
TAX_DEADLINES_2026 = {
    "w2_1099_send": "February 2, 2026",
    "partnership_1065": "March 16, 2026",
    "s_corp_1120s": "March 16, 2026",
    "individual_1040": "April 15, 2026",
    "q1_estimated": "April 15, 2026",
    "q2_estimated": "June 15, 2026",
    "q3_estimated": "September 15, 2026",
    "extension_deadline": "October 15, 2026",
    "q4_estimated": "January 15, 2027",
    "sep_ira_contribution": "October 15, 2026",  # с extension
    "solo_401k_establish": "December 31, 2026",  # plan creation deadline
}
```

### 6.4 Новые ноды

#### collect_prior_year_tax
```python
@with_timeout(10)
async def collect_prior_year_tax(state: TaxReportState) -> TaxReportState:
    """Fetch prior year total tax for safe harbor calculation."""
    family_id = state["family_id"]
    year = state["year"]
    prior_year = year - 1

    async with async_session() as session:
        # Предполагаем что сохраняем tax_filings в БД
        stmt = select(TaxFiling.total_tax).where(
            TaxFiling.family_id == uuid.UUID(family_id),
            TaxFiling.year == prior_year,
        )
        prior_tax = await session.scalar(stmt)

    return {**state, "prior_year_tax": float(prior_tax or 0)}
```

#### calculate_state_tax
```python
@observe(name="tax_calculate_state")
async def calculate_state_tax(state: TaxReportState) -> TaxReportState:
    """Calculate state income tax based on user's state."""
    user_state = state.get("state") or "TX"  # default no-tax
    config = STATE_TAX_CONFIG.get(user_state, {"type": "none"})

    state_tax = 0.0
    state_qbid_applies = config.get("qbid", True)

    if config["type"] == "none":
        state_tax = 0.0
    elif config["type"] == "flat":
        # Apply to net_profit (or adjusted income without QBID if state doesn't conform)
        base = state.get("net_profit", 0)
        if not state_qbid_applies:
            # No QBID for this state — use higher income base
            base = state.get("adjusted_income", base)
        state_tax = base * config["rate"]
    elif config["type"] == "progressive":
        # Use top-rate approximation (для точного расчёта нужна полная таблица скобок)
        base = state.get("net_profit", 0)
        state_tax = base * config["rate"]  # упрощение — заменить на bracket calc

    # Additional state taxes (MCTMT, SDI, etc.)
    additional = []
    for extra in config.get("extras", []):
        if extra.get("threshold") and base < extra["threshold"]:
            continue
        extra_tax = base * extra["rate"]
        additional.append({"name": extra["name"], "amount": extra_tax})
        state_tax += extra_tax

    # State quarterly schedule
    quarterly_schedule = config.get("quarterly", [0.25, 0.25, 0.25, 0.25])

    return {
        **state,
        "state_income_tax": state_tax,
        "state_rate_used": config.get("rate", 0.0),
        "state_qbid_applies": state_qbid_applies,
        "additional_state_taxes": additional,
        "quarterly_schedule": quarterly_schedule,
    }
```

#### calculate_obbba_adjustments
```python
@observe(name="tax_calculate_obbba")
async def calculate_obbba_adjustments(state: TaxReportState) -> TaxReportState:
    """Apply One Big Beautiful Bill Act (July 4, 2025) above-the-line deductions."""
    filing_status = state.get("filing_status", "single")
    gross_income = state.get("gross_income", 0)

    obbba_total = 0.0
    obbba_breakdown = []

    # 1. No Tax on Tips
    tips = state.get("tips_income", 0.0)
    if tips > 0 and gross_income <= OBBBA_TIPS_PHASEOUT_SINGLE:
        tips_ded = min(tips, OBBBA_TIPS_LIMIT)
        obbba_total += tips_ded
        obbba_breakdown.append({"type": "tips", "amount": tips_ded})

    # 2. No Tax on Overtime
    overtime = state.get("overtime_pay", 0.0)
    if overtime > 0:
        ot_limit = OBBBA_OVERTIME_LIMIT_MFJ if filing_status == "mfj" else OBBBA_OVERTIME_LIMIT_SINGLE
        ot_ded = min(overtime, ot_limit)
        obbba_total += ot_ded
        obbba_breakdown.append({"type": "overtime", "amount": ot_ded})

    # 3. Auto Loan Interest
    auto_interest = state.get("auto_loan_interest", 0.0)
    if auto_interest > 0:
        auto_ded = min(auto_interest, OBBBA_AUTO_LOAN_LIMIT)
        obbba_total += auto_ded
        obbba_breakdown.append({"type": "auto_loan", "amount": auto_ded})

    # 4. Senior Deduction (65+)
    if state.get("is_senior", False):
        obbba_total += OBBBA_SENIOR_DEDUCTION
        obbba_breakdown.append({"type": "senior", "amount": OBBBA_SENIOR_DEDUCTION})

    return {**state, "obbba_deductions": obbba_total, "obbba_breakdown": obbba_breakdown}
```

#### calculate_retirement_opportunity
```python
@observe(name="tax_retirement_opportunity")
async def calculate_retirement_opportunity(state: TaxReportState) -> TaxReportState:
    """Calculate retirement contribution opportunities and tax savings."""
    net_profit = state.get("net_profit", 0.0)
    effective_rate = state.get("effective_rate", 0.0)

    # SEP-IRA
    sep_max = min(net_profit * SEP_IRA_PCT, SEP_IRA_MAX)

    # Solo 401(k) — employee contribution (simpler estimate)
    solo_max = min(SOLO_401K_EMPLOYEE_MAX, net_profit)

    # Tax savings estimate (marginal rate)
    marginal_rate = _get_marginal_rate(state)
    sep_savings = sep_max * marginal_rate
    solo_savings = solo_max * marginal_rate

    return {
        **state,
        "sep_ira_max": sep_max,
        "solo_401k_max": solo_max,
        "retirement_tax_savings": sep_savings,  # показываем max savings
    }
```

#### calculate_federal_tax (исправленный)
```python
@observe(name="tax_calculate_federal")
async def calculate_federal_tax(state: TaxReportState) -> TaxReportState:
    """Deterministic federal tax — no LLM. Includes OBBBA and standard deduction."""
    gross_income = state.get("gross_income", 0.0)
    total_deductible = state.get("total_deductible", 0.0)
    obbba_deductions = state.get("obbba_deductions", 0.0)
    filing_status = state.get("filing_status", "single")
    quarter = state.get("quarter")

    # Net profit after Schedule C deductions
    net_profit = max(gross_income - total_deductible, 0.0)

    # SE tax (15.3% on 92.35%)
    se_base = net_profit * SE_NET_FACTOR
    se_tax = se_base * SE_TAX_RATE
    se_deduction = se_tax * SE_DEDUCTION_FACTOR

    # Adjusted income (after SE deduction + OBBBA)
    adjusted_income = net_profit - se_deduction - obbba_deductions

    # QBI §199A deduction (permanent per OBBBA)
    qbi_deduction = _calculate_qbi(adjusted_income, filing_status)

    # Standard deduction
    standard_ded = STANDARD_DEDUCTION_2026.get(filing_status, 16_100)

    # Taxable income
    taxable = max(adjusted_income - qbi_deduction - standard_ded, 0.0)

    # Income tax from brackets
    brackets = {
        "single": BRACKETS_2026_SINGLE,
        "mfj": BRACKETS_2026_MFJ,
        "hoh": BRACKETS_2026_HOH,
        "mfs": BRACKETS_2026_SINGLE,  # same as single
    }.get(filing_status, BRACKETS_2026_SINGLE)

    income_tax = _apply_brackets(taxable, brackets)
    total_federal_tax = se_tax + income_tax
    effective_rate = (total_federal_tax / gross_income * 100) if gross_income > 0 else 0.0
    quarterly_payment = total_federal_tax / 4

    return {
        **state,
        "net_profit": net_profit,
        "se_tax": se_tax,
        "se_deduction": se_deduction,
        "qbi_deduction": qbi_deduction,
        "standard_deduction": standard_ded,
        "taxable_income": taxable,
        "income_tax": income_tax,
        "total_federal_tax": total_federal_tax,
        "effective_rate": effective_rate,
        "quarterly_payment": quarterly_payment,
    }
```

### 6.5 Schedule C — line-by-line mapping

```python
SCHEDULE_C_LINES = {
    # Part I — Income
    "1": "Gross receipts or sales",
    "2": "Returns and allowances",
    "4": "Cost of goods sold (from line 42)",
    "7": "Gross income (subtract lines 2, 3, 4 from line 1)",
    # Part II — Expenses
    "8": "Advertising",
    "9": "Car and truck expenses",
    "10": "Commissions and fees",
    "11": "Contract labor",
    "12": "Depletion",
    "13": "Depreciation and section 179",
    "14": "Employee benefit programs",
    "15": "Insurance (other than health)",
    "16": "Interest (mortgage + other)",
    "17": "Legal and professional services",
    "18": "Office expense",
    "19": "Pension and profit-sharing plans",
    "20": "Rent or lease (vehicles, machinery, property)",
    "21": "Repairs and maintenance",
    "22": "Supplies",
    "23": "Taxes and licenses",
    "24": "Travel and meals (50% meals)",
    "25": "Utilities",
    "26": "Wages (minus employment credits)",
    "27": "Other expenses",
    "28": "Total expenses (sum 8-27)",
    "29": "Tentative profit or (loss)",
    "30": "Home office deduction",
    "31": "Net profit or (loss)",
}

def build_schedule_c_lines(state: TaxReportState) -> dict:
    """Map our expense categories to Schedule C line numbers."""
    expenses = state.get("expenses_by_category", [])
    lines = {}

    CATEGORY_TO_LINE = {
        "Связь/Интернет": "25",      # Utilities
        "Подписки": "18",             # Office expense
        "Образование": "27",          # Other expenses
        "Транспорт": "9",             # Car and truck
        "Такси": "24",                # Travel
        "Питание/Рестораны": "24",    # Meals (50%)
        "Электроника": "13",          # Section 179
        "Медицина": "15",             # Insurance
        "Аренда": "20b",             # Rent - property
        "Коммунальные": "25",         # Utilities
    }

    for expense in expenses:
        line = CATEGORY_TO_LINE.get(expense["category"])
        if line:
            lines[line] = lines.get(line, 0) + expense.get("deductible_amount", 0)

    # Add mileage to line 9
    lines["9"] = lines.get("9", 0) + state.get("mileage_deduction", 0)
    # Add home office to line 30
    lines["30"] = state.get("home_office_deduction", 0)

    return lines
```

### 6.6 1040-ES Quarterly Vouchers

```python
def build_quarterly_vouchers(state: TaxReportState) -> list[dict]:
    """Generate 4 quarterly payment vouchers."""
    year = state.get("year")
    total_federal = state.get("total_federal_tax", 0)
    total_state = state.get("state_income_tax", 0)
    prior_year = state.get("prior_year_tax", 0)
    user_state = state.get("state", "")

    # Safe harbor: min(90% current year, 100% prior year, 110% prior if AGI > $150K)
    safe_harbor_90pct = total_federal * 0.90
    safe_harbor_100pct = prior_year * 1.00
    safe_harbor_110pct = prior_year * 1.10  # если AGI > $150K
    recommended = min(safe_harbor_90pct, safe_harbor_100pct)

    # State quarterly schedule (CA = 30/40/0/30, others = 25/25/25/25)
    schedule = state.get("quarterly_schedule", [0.25, 0.25, 0.25, 0.25])

    deadlines_2026 = [
        ("Q1", "April 15, 2026"),
        ("Q2", "June 15, 2026"),
        ("Q3", "September 15, 2026"),
        ("Q4", "January 15, 2027"),
    ]

    vouchers = []
    for i, (qname, deadline) in enumerate(deadlines_2026):
        pct = schedule[i]
        if pct == 0:
            continue  # CA пропускает Q3
        federal_amount = recommended / 4
        state_amount = total_state * pct

        vouchers.append({
            "quarter": qname,
            "deadline": deadline,
            "federal_amount": federal_amount,
            "state_amount": state_amount,
            "total_amount": federal_amount + state_amount,
            "state": user_state,
            "form": "1040-ES",
        })

    return vouchers
```

---

## ЧАСТЬ 7: ФАЗИРОВАННЫЙ ПЛАН РЕАЛИЗАЦИИ

### Phase 1 — Критические исправления (Неделя 1, 3-5 дней)

**Файлы**: `deductions.py`, `nodes.py`, `state.py`

| Задача | Сложность | Impact |
|--------|----------|--------|
| Исправить brackets 2026 (OBBBA) | Низкая | 🔴 Critical |
| Добавить standard deduction | Низкая | 🔴 Critical — $3.5K+ ошибка |
| Применить mileage к расчёту | Низкая | 🔴 Critical |
| Исправить mileage rate (0.70 vs 0.725) | Низкая | Средний |
| SE health insurance limit | Низкая | Средний |
| Filing status parameter | Средняя | Высокий |
| Обновить тесты | Средняя | Обязательно |

### Phase 2 — State Tax Engine (Неделя 2, 5-7 дней)

**Новые файлы**: `state_tax.py`, обновить `nodes.py`, `graph.py`

| Задача | Сложность | Impact |
|--------|----------|--------|
| `STATE_TAX_CONFIG` для 50 штатов | Средняя | 🔴 Critical для точности |
| `calculate_state_tax` node | Средняя | Высокий |
| CA quarterly schedule (30/40/0/30) | Низкая | Высокий для CA users |
| NY MCTMT расчёт | Низкая | Средний |
| Хранить штат в профиле пользователя | Средняя | Зависимость |
| Добавить state в IntentData | Низкая | |
| Тесты (NY, CA, TX как минимум) | Средняя | Обязательно |

### Phase 3 — OBBBA Deductions (Неделя 2-3, 3-5 дней)

**Новые файлы**: обновить `nodes.py`

| Задача | Сложность | Impact |
|--------|----------|--------|
| `calculate_obbba_adjustments` node | Средняя | Новый закон 2025 |
| Tips deduction ($25K) | Низкая | Для gig workers |
| Overtime deduction ($12.5K) | Низкая | Для W-2 + SE |
| Auto loan interest ($10K) | Низкая | |
| Senior deduction ($6K) | Низкая | |
| IntentData: tips_income, overtime_pay | Низкая | |
| Тесты | Средняя | |

### Phase 4 — Retirement Optimizer (Неделя 3, 3-5 дней)

| Задача | Сложность | Impact |
|--------|----------|--------|
| `calculate_retirement_opportunity` node | Средняя | Высокий — $5K-$15K savings |
| SEP-IRA max calculator | Низкая | |
| Solo 401(k) max calculator | Низкая | |
| Marginal rate calculator | Средняя | |
| Отображение в PDF и Telegram | Средняя | |
| "What-if" scenarios | Высокая | Phase 5+ |

### Phase 5 — Document OCR (Неделя 4, 5-7 дней)

| Задача | Сложность | Impact |
|--------|----------|--------|
| Azure Document Intelligence SDK | Средняя | Огромный — zero manual entry |
| `collect_documents` node | Средняя | |
| W-2 JSON schema + validation | Средняя | |
| 1099-NEC extraction | Средняя | |
| Cross-field validation | Высокая | Accuracy |
| Reconciliation multiple docs | Высокая | |
| Хранить extracted docs в БД | Средняя | |

### Phase 6 — HITL Review + Schedule C Worksheet (Неделя 5, 3-5 дней)

| Задача | Сложность | Impact |
|--------|----------|--------|
| `interrupt()` перед generate_pdf | Средняя | UX |
| Inline buttons: Approve / Edit deductions | Средняя | Trust |
| Schedule C line-by-line worksheet | Высокая | Tax-ready output |
| 1040-ES vouchers в PDF | Средняя | Ready-to-pay |
| Multi-section PDF (federal + state + retirement) | Высокая | |

### Phase 7 — Prior Year Safe Harbor + NOL (Неделя 6+)

| Задача | Сложность | Impact |
|--------|----------|--------|
| `collect_prior_year_tax` node | Высокая | Accurate quarterly payments |
| TaxFiling DB model + migration | Средняя | |
| NOL carryforward tracking | Очень высокая | Advanced users |
| AMT detection + CPA escalation | Высокая | Compliance |
| Passive loss tracking | Очень высокая | Phase 8+ |

### Phase 8 — RAG над IRS Publications

| Задача | Сложность | Impact |
|--------|----------|--------|
| Vector store IRS Pubs 334, 505, 463, 946 | Высокая | LLM accuracy |
| RAG pipeline для deduction Q&A | Высокая | |
| Confidence-gated escalation (< 0.75 → CPA) | Средняя | |
| Версионирование IRS данных (ежегодное обновление) | Средняя | Maintenance |

---

## ЧАСТЬ 8: COMPLIANCE И DISCLAIMERS

### Обязательные disclaimers (Circular 230)

```python
# Каждый ответ с налоговыми цифрами ДОЛЖЕН содержать:
DISCLAIMER_EN = (
    "⚠️ This estimate is for informational purposes only and does not "
    "constitute professional tax advice. Tax laws vary by state and individual "
    "circumstances. Consult a licensed CPA or tax professional before filing. "
    "QBI deduction made permanent by One Big Beautiful Bill Act (July 4, 2025)."
)

# Триггеры обязательной CPA-эскалации:
CPA_ESCALATION_TRIGGERS = [
    "total_tax > 10_000",
    "passive_losses_detected",
    "nol_carryforward > 0",
    "amt_detected",
    "foreign_income > 0",
    "crypto_transactions > 20",
]
```

### Accuracy requirements (TurboTax standard)

- **Детерминированные расчёты**: 100% верны при правильных входных данных
- **LLM deduction hints**: всегда с disclaimer, никогда без RAG-источника
- **Цитаты**: минимум IRS Publication + section для каждого вычета
- **Ежегодное обновление**: до 1 января каждого года обновлять ставки + скобки

---

## ЧАСТЬ 9: ИТОГОВАЯ ТАБЛИЦА ПРИОРИТЕТОВ

| Приоритет | Фаза | Задача | Статус |
|-----------|------|--------|--------|
| 🔴 P0 | 1 | Исправить brackets 2026 (OBBBA) | TODO |
| 🔴 P0 | 1 | Добавить standard deduction $16,100 | TODO |
| 🔴 P0 | 1 | Применить mileage deduction | TODO |
| 🔴 P1 | 1 | Filing status (single/MFJ/HoH) | TODO |
| 🔴 P1 | 2 | State tax engine (50 штатов) | TODO |
| 🟡 P2 | 2 | CA quarterly 30/40/0/30 | TODO |
| 🟡 P2 | 3 | OBBBA Tips/Overtime deductions | TODO |
| 🟡 P2 | 4 | SEP-IRA / Solo 401k optimizer | TODO |
| 🟡 P2 | 5 | Azure Doc Intelligence OCR | TODO |
| 🟢 P3 | 6 | HITL deduction review | TODO |
| 🟢 P3 | 6 | Schedule C line-by-line | TODO |
| 🟢 P3 | 6 | 1040-ES vouchers в PDF | TODO |
| 🟢 P3 | 7 | Prior year safe harbor | TODO |
| ⚪ P4 | 7 | NOL carryforward | TODO |
| ⚪ P4 | 7 | AMT detection | TODO |
| ⚪ P4 | 8 | RAG IRS Publications | TODO |
| ⚪ P4 | 8 | Multi-state filer support | TODO |

---

*Документ составлен: 2026-03-10. Источники: IRS.gov, Tax Foundation, One Big Beautiful Bill Act (July 4, 2025), TurboTax GenOS architecture, Azure Document Intelligence docs, FlyFin/Keeper/TaxGPT product analysis.*
