# TaxReportOrchestrator — Единый Мастер-План (2026-03-10)

> **Единый документ**: объединяет глубокий анализ IRS, все 50 штатов, open-source инструменты,
> возможности LLM на 03/10/2026, ключевые находки taxdeep1 и taxdeep2, критические баги текущего
> кода и полный production-roadmap TaxReportOrchestrator.
>
> **Правило**: LLM используем ТОЛЬКО интегрированные в проект. Никакого Azure, никакого внешнего OCR.

---

## РАЗДЕЛ 0: EXECUTIVE SUMMARY

### Что сломано прямо сейчас (до старта планирования)

| Баг | Файл | Impact |
|-----|------|--------|
| Standard deduction ($16,100) не вычитается | `deductions.py`, `nodes.py` | **Переплата ~$3,542 на $60K дохода** |
| Brackets 2026 — pre-OBBBA значения | `deductions.py` | Неверные ставки |
| Mileage deduction вычислен, но не применён | `nodes.py` | Утерянный вычет |
| Mileage proxy (`spend / 0.30`) некорректен | `nodes.py` | Нельзя конвертировать $ → мили |
| Filing status — только single | `nodes.py`, `state.py` | MFJ/HoH не поддержаны |
| Нет state tax | весь оркестратор | CA/NY пользователи видят только federal |
| SE health insurance — нет лимита | `nodes.py` | Может создать незаконный убыток |
| OBBBA вычеты (Tips/Overtime/Auto/Senior) | не реализованы | Новый закон July 4, 2025 |

### Главная находка из taxdeep

**PolicyEngine US** (`policyengine-us`) — open-source, покрывает federal + все 50 штатов детерминированно. Заменяет наш ошибочный `_apply_brackets()` + неполный `STATE_TAX_CONFIG`.

### LLM-распределение (только интегрированные модели)

```
Математика → Python deterministic (никогда LLM!)
OCR документов → Gemini 3.1 Flash Lite → fallback Claude Sonnet
Деления вычетов → Claude Haiku 4.5 (+ RAG IRS Pub)
Сложные сценарии → Claude Opus 4.6 + extended thinking
Глубокий анализ → Gemini 3 Pro + thinking (доход > $100K)
Нарратив → Claude Sonnet 4.6 (только объясняет, не считает)
Актуальные ставки → Grok 4.20 (web search, опционально)
```

---

## РАЗДЕЛ 1: IRS ИНФРАСТРУКТУРА

### 1.1 Что есть у IRS для разработчиков

| Система | Тип | Доступность | Применимость |
|---------|-----|-------------|--------------|
| MeF (Modernized e-File) | SOAP/XML | Только авторизованным (EFIN) | E-filing returns |
| MeF XML Schemas (XSD) | Free download | Публично | Валидация форм |
| FIRE System | HTTPS upload | Авторизованным | 1099/W-2 payer filing |
| **IRIS** (новый) | REST API | Авторизованным | Замена FIRE с 2027 |
| Transcript Delivery System | API | e-Services enrollment | Данные клиента |
| IRS Direct File | Web UI | Публично | НЕ поддерживает Schedule C |
| IRS Interactive Tax Assistant | Rule-based | Публично | Не LLM |
| IRS Pub PDFs | Direct download | Free | Официальные формы |

**Ключевые выводы**:
- Прямой REST API у IRS отсутствует (только MeF SOAP для EFIN-holders)
- Наш бот — **advisory/estimation tool**, не e-filing → EFIN не нужен
- FIRE System EOL: **31 декабря 2026** → заменяется IRIS REST API (критично для бизнесов-пользователей)

### 1.2 FIRE System EOL — критично для пользователей-бизнесов

| | FIRE (старый) | IRIS (новый) |
|--|--------------|-------------|
| Тип | HTTPS file upload | REST API |
| Auth | Пароль | API Client ID + JWT |
| Deadline | **EOL 31.12.2026** | Обязательно с 2027 |
| Критичность | — | XSD ошибки = нет замены = штрафы IRS |

**Для нашего бота**: в `generate_narrative` добавить уведомление для business users в 2026 году.

### 1.3 MeF WSDL R10.9 — технические стандарты (для будущего e-filing)

- SOAP + MTOM + ZIP-контейнеры
- SHA-256 обязательно (SHA-1 удалён)
- TLS 1.2+, X.509 сертификаты (IDenTrust/ORC)
- SOR (Secure Object Repository) — 60-дней авто-удаление схем

**Сейчас**: advisory-only. MeF не нужен. Фиксируем для Phase 8+.

### 1.4 IRS AI Governance — IRM 10.24.1 (вступил 10.02.2026)

IRS официально ввёл AI-governance. Обязательно учитывать:

| Требование | Что означает для нас |
|-----------|---------------------|
| **Запрет PII/FTI в публичные AI** | Токенизировать SSN/EIN до передачи в LLM |
| **Human review перед использованием AI-вывода** | HITL checkpoint — не опция, best practice |
| **Audit trail** | Логировать: hash промпта, hash ответа, model snapshot |
| **Prompt logs 1 год** | Langfuse (уже интегрирован через `@observe`) |
| **Прозрачность AI** | Disclaimer в каждом отчёте: "Создано с помощью AI" |

### 1.5 VITA GenAI PoC — официальный прецедент (IRS, Jan–Apr 2025)

IRS сам использовал **RAG на публичных IRS PDF** для волонтёров VITA:
- Источники: Pub 334, 505, 463, 15 (публичные PDF с IRS.gov)
- PII хранился отдельно от LLM-контекста
- Инфраструктура: AWS + GCP

**Вывод**: RAG на IRS Publications — **официально одобренный IRS паттерн**. Реализуем в Phase 3.

---

## РАЗДЕЛ 2: КРИТИЧЕСКИЕ БАГИ В ТЕКУЩЕМ КОДЕ

### 2.1 Стандартный вычет не применяется — P0 КРИТИЧЕСКИЙ БАГ

**Файл**: `src/orchestrators/tax_report/nodes.py`

**Проблема**: `calculate_tax()` применяет скобки к `adjusted_income - qbi_deduction`,
но не вычитает standard deduction $16,100 (single 2026).

```python
# ❌ ТЕКУЩИЙ КОД (неверно):
taxable = max(adjusted_income - qbi_deduction, 0.0)
income_tax = _apply_brackets(taxable)

# ✅ ИСПРАВЛЕНИЕ:
STANDARD_DEDUCTION_2026 = {
    "single": 16_100,
    "mfj":    32_200,
    "hoh":    24_150,
    "mfs":    16_100,
}
standard_ded = STANDARD_DEDUCTION_2026.get(filing_status, 16_100)
taxable = max(adjusted_income - qbi_deduction - standard_ded, 0.0)
```

**Impact**: $60K дохода → переплата **$3,542** в год.

### 2.2 Неверные налоговые скобки 2026 — P0

**Файл**: `src/orchestrators/tax_report/deductions.py`

```python
# ❌ ТЕКУЩИЙ КОД (pre-OBBBA, неверно):
BRACKETS_2026_SINGLE = [
    (11_925, 0.10),
    (48_475, 0.12),
    (103_350, 0.22),
    ...
]

# ✅ ПРАВИЛЬНЫЕ скобки 2026 (после OBBBA, July 4, 2025):
BRACKETS_2026_SINGLE = [
    (12_400,       0.10),
    (50_400,       0.12),
    (107_550,      0.22),
    (205_600,      0.24),
    (261_100,      0.32),
    (640_600,      0.35),
    (float("inf"), 0.37),
]

BRACKETS_2026_MFJ = [
    (24_800,       0.10),
    (100_800,      0.12),
    (215_100,      0.22),
    (411_200,      0.24),
    (522_200,      0.32),
    (768_600,      0.35),
    (float("inf"), 0.37),
]

BRACKETS_2026_HOH = [
    (18_600,       0.10),
    (75_600,       0.12),
    (111_275,      0.22),
    (205_600,      0.24),
    (261_100,      0.32),
    (640_600,      0.35),
    (float("inf"), 0.37),
]
```

### 2.3 Mileage deduction вычислен, но не применён — P0

```python
# ❌ ПРОБЛЕМА: collect_mileage возвращает mileage_miles,
# но analyze_deductions не добавляет его в total_deductible!

# ✅ ИСПРАВЛЕНИЕ в analyze_deductions:
mileage_rate = state.get("mileage_rate_override", MILEAGE_RATE_2026)
mileage_deduction = state.get("mileage_miles", 0) * mileage_rate
total_deductible += mileage_deduction
```

### 2.4 Proxy-расчёт mileage — P0

```python
# ❌ НЕВЕРНО (transport_spend / $0.30 → мили):
mileage_miles = transport_spend / 0.30  # $0.30 не реальная IRS ставка!

# ✅ ПРАВИЛЬНО: нельзя конвертировать деньги → мили без одометра
# Убрать proxy. Добавить прямой ввод miles из трекера или IntentData.
```

### 2.5 SE Health Insurance — нет лимита

```python
# ❌ ПРОБЛЕМА: unlimited deduction может создать убыток
"Медицина": ("health_insurance", 1.0),

# ✅ IRS правило: SE health insurance ≤ net_profit
health_insurance_ded = min(
    expenses_by_category.get("health_insurance", 0),
    net_profit  # cannot exceed net profit
)
```

### 2.6 Ставка mileage неверная

```python
# ❌ ТЕКУЩИЙ КОД:
MILEAGE_RATE_2026 = 0.725  # неверно для 2025

# ✅ IRS официальные ставки:
MILEAGE_RATE_2025 = 0.700  # $0.70/mile (IRS 2025, официально)
MILEAGE_RATE_2026 = 0.725  # оценка (IRS объявит декабрь 2025)
# Grok может проверить актуальную ставку через web search
```

---

## РАЗДЕЛ 3: ONE BIG BEAUTIFUL BILL ACT (July 4, 2025)

### 3.1 Новые above-the-line вычеты (Schedule 1-A)

| Вычет | Лимит | Phase-out | Применимость |
|-------|-------|-----------|-------------|
| **No Tax on Tips** | $25,000 | >$150K single (>$300K MFJ) | Официанты, доставщики |
| **No Tax on Overtime** | $12,500 single / $25,000 MFJ | >$150K single | W-2 + self-employed |
| **Auto loan interest** | $10,000 | >$100K single | US-assembled vehicles only |
| **Senior deduction (65+)** | $6,000 | >$75K single | Пожилые клиенты |

### 3.2 QBI (§199A) — постоянный

OBBBA сделал QBI permanent. 20% вычет от qualified business income.

```python
# OBBBA constants:
OBBBA_TIPS_LIMIT = 25_000
OBBBA_OVERTIME_LIMIT_SINGLE = 12_500
OBBBA_OVERTIME_LIMIT_MFJ = 25_000
OBBBA_AUTO_LOAN_LIMIT = 10_000
OBBBA_SENIOR_DEDUCTION = 6_000
OBBBA_TIPS_PHASEOUT_SINGLE = 150_000
OBBBA_TIPS_PHASEOUT_MFJ = 300_000

# SALT cap (OBBBA):
SALT_CAP_2026 = 40_400          # $40,000 * 1.01
SALT_PHASEOUT_START_MFJ = 500_000

# QBI 2026 phase-out:
QBI_PHASEOUT_START_SINGLE = 203_000
QBI_PHASEOUT_END_SINGLE = 272_300
QBI_PHASEOUT_START_MFJ = 406_000
QBI_PHASEOUT_END_MFJ = 544_600
```

### 3.3 Нод `calculate_obbba_adjustments`

```python
@observe(name="tax_calculate_obbba")
async def calculate_obbba_adjustments(state: TaxReportState) -> TaxReportState:
    """Apply OBBBA (July 4, 2025) above-the-line deductions. Deterministic."""
    filing_status = state.get("filing_status", "single")
    gross_income = state.get("gross_income", 0)
    obbba_total = 0.0
    obbba_breakdown = []

    # 1. No Tax on Tips
    tips = state.get("tips_income", 0.0)
    phaseout = OBBBA_TIPS_PHASEOUT_MFJ if filing_status == "mfj" else OBBBA_TIPS_PHASEOUT_SINGLE
    if tips > 0 and gross_income <= phaseout:
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

---

## РАЗДЕЛ 4: ВСЕ 50 ШТАТОВ

### 4.1 Классификация

**9 штатов без income tax** (нулевой расчёт): TX, FL, NV, WY, SD, AK, TN, NH (0% с 2026), WA

**13 штатов с flat tax**:

| Штат | Ставка | QBID | Примечание |
|------|--------|------|-----------|
| AZ | 2.5% | Да | Самая низкая |
| CO | 4.4% | Да | |
| GA | 5.39% | Да | Снижается |
| ID | 5.695% | Да | |
| IL | 4.95% | Нет | Конституционный запрет прогрессии |
| IN | 3.05% | Да | |
| IA | 3.8% | Да | |
| KY | 4.0% | Да | |
| MI | 4.05% | Да | |
| MS | 4.7% | Да | |
| NC | 4.5% | Да | |
| PA | 3.07% | Нет | Независимая система |
| UT | 4.65% | Да | |

**Топ-5 высоконалоговых штатов для self-employed**:

| Штат | Top rate | QBID | SE-специфика |
|------|----------|------|-------------|
| CA | 13.3% | **Нет** | SDI 1.1% (опц.), CA quarterly 30/40/0/30 |
| NY | 10.9% + 3.876% NYC | **Нет** | MCTMT 0.34% (SE > $50K) |
| NJ | 10.75% | **Нет** | — |
| OR | 9.9% | Да | Transit 0.1% |
| MN | 9.85% | Да | — |

**Важно**: CA, NY, NJ, PA **не применяют QBID** — federal 20% вычет только на federal уровне.

### 4.2 CA Quarterly Schedule — критическая особенность

Калифорния: **30% / 40% / 0% / 30%** (НЕ 25% каждый квартал!)

```python
CA_QUARTERLY_SCHEDULE = [0.30, 0.40, 0.00, 0.30]  # Q1/Q2/Q3/Q4
CA_QUARTERLY_DATES = ["April 15", "June 15", None, "January 15"]
# Q3 пропускается — нет платежа в сентябре!
```

### 4.3 Городские налоги

| Город | Налог | Ставка |
|-------|-------|--------|
| NYC | City income tax | 3.078%–3.876% |
| NYC | UBT (Unincorporated Business Tax) | 4% net income |
| NYC | MCTMT | 0.34% SE > $50K |
| Philadelphia | Net Profits Tax | 3.75% residents |
| Portland OR | Arts tax | $35/year |

### 4.4 Дедлайны по штатам

| Штат | Дедлайн | Примечание |
|------|---------|-----------|
| Большинство | April 15 | Следуют federal |
| Virginia | May 1 | Постоянное исключение |
| Louisiana | May 15 | |
| Hawaii | April 20 | |
| Iowa | April 30 | |
| Delaware | April 30 | |

### 4.5 STATE_TAX_CONFIG — полный словарь

```python
# src/orchestrators/tax_report/deductions.py
STATE_TAX_CONFIG = {
    # No income tax states
    "AK": {"type": "none", "qbid": True},
    "FL": {"type": "none", "qbid": True},
    "NV": {"type": "none", "qbid": True},
    "NH": {"type": "none", "qbid": True},
    "SD": {"type": "none", "qbid": True},
    "TN": {"type": "none", "qbid": True},
    "TX": {"type": "none", "qbid": True},
    "WA": {"type": "none", "qbid": True},
    "WY": {"type": "none", "qbid": True},
    # Flat tax states
    "AZ": {"type": "flat", "rate": 0.025,  "qbid": True},
    "CO": {"type": "flat", "rate": 0.044,  "qbid": True},
    "GA": {"type": "flat", "rate": 0.0539, "qbid": True},
    "ID": {"type": "flat", "rate": 0.05695,"qbid": True},
    "IL": {"type": "flat", "rate": 0.0495, "qbid": False},
    "IN": {"type": "flat", "rate": 0.0305, "qbid": True},
    "IA": {"type": "flat", "rate": 0.038,  "qbid": True},
    "KY": {"type": "flat", "rate": 0.040,  "qbid": True},
    "MI": {"type": "flat", "rate": 0.0405, "qbid": True},
    "MS": {"type": "flat", "rate": 0.047,  "qbid": True},
    "NC": {"type": "flat", "rate": 0.045,  "qbid": True},
    "PA": {"type": "flat", "rate": 0.0307, "qbid": False},
    "UT": {"type": "flat", "rate": 0.0465, "qbid": True},
    # Progressive states (top-rate approximation)
    "CA": {
        "type": "progressive", "rate": 0.093, "qbid": False,
        "quarterly": [0.30, 0.40, 0.00, 0.30],
        "extras": [{"name": "SDI", "rate": 0.011, "optional": True}],
    },
    "NY": {
        "type": "progressive", "rate": 0.0965, "qbid": False,
        "extras": [{"name": "MCTMT", "rate": 0.0034, "threshold": 50_000}],
    },
    "NJ": {"type": "progressive", "rate": 0.0637, "qbid": False},
    "OR": {"type": "progressive", "rate": 0.099,  "qbid": True,
           "extras": [{"name": "Transit", "rate": 0.001}]},
    "MN": {"type": "progressive", "rate": 0.0985, "qbid": True},
    "VT": {"type": "progressive", "rate": 0.0875, "qbid": True},
    "DC": {"type": "progressive", "rate": 0.0875, "qbid": True},
    "HI": {"type": "progressive", "rate": 0.11,   "qbid": True},
    "ME": {"type": "progressive", "rate": 0.0715, "qbid": True},
    "MT": {"type": "progressive", "rate": 0.059,  "qbid": True},
    "WI": {"type": "progressive", "rate": 0.0765, "qbid": True},
    "CT": {"type": "progressive", "rate": 0.0699, "qbid": True},
    "MA": {"type": "flat",        "rate": 0.09,   "qbid": True},  # 9% on short-term gains
    "SC": {"type": "progressive", "rate": 0.065,  "qbid": True},
    "AL": {"type": "progressive", "rate": 0.05,   "qbid": True},
    "AR": {"type": "progressive", "rate": 0.0475, "qbid": True},
    "LA": {"type": "progressive", "rate": 0.045,  "qbid": True},
    "KS": {"type": "progressive", "rate": 0.057,  "qbid": True},
    "MO": {"type": "progressive", "rate": 0.048,  "qbid": True},
    "NE": {"type": "progressive", "rate": 0.0664, "qbid": True},
    "ND": {"type": "progressive", "rate": 0.025,  "qbid": True},
    "OK": {"type": "progressive", "rate": 0.0475, "qbid": True},
    "RI": {"type": "progressive", "rate": 0.0599, "qbid": True},
    "WV": {"type": "progressive", "rate": 0.065,  "qbid": True},
    "DE": {"type": "progressive", "rate": 0.066,  "qbid": True},
    "MD": {"type": "progressive", "rate": 0.0575, "qbid": True},
    "VA": {"type": "progressive", "rate": 0.0575, "qbid": True},
    "NM": {"type": "progressive", "rate": 0.059,  "qbid": True},
    "AZ": {"type": "flat",        "rate": 0.025,  "qbid": True},
    "WA": {"type": "none",        "qbid": True},  # no income, but 7% capital gains tax
}
```

---

## РАЗДЕЛ 5: OPEN-SOURCE ИНСТРУМЕНТЫ

### 5.1 ГЛАВНАЯ НАХОДКА: PolicyEngine US

**PolicyEngine US** (`policyengine-us`) — open-source, Congressional Budget Office использует.
Покрывает federal + все 50 штатов. Версионированные YAML-параметры.

```python
# uv add policyengine-us

import policyengine_us as pe

sim = pe.Simulator(period=2026)
sim.set_input("self_employment_income", 75_000)
sim.set_input("employment_income", 50_000)   # W-2 доход
sim.set_input("state_code", "CA")
sim.set_input("filing_status", "single")

# Все расчёты детерминированные и верные
federal_income_tax = sim.calculate("income_tax")
state_income_tax   = sim.calculate("state_income_tax")
se_tax             = sim.calculate("self_employment_tax")
qbi_deduction      = sim.calculate("qualified_business_income_deduction")
standard_deduction = sim.calculate("standard_deduction")
taxable_income     = sim.calculate("taxable_income")
```

**Заменяет** наш ошибочный `_apply_brackets()` + `STATE_TAX_CONFIG` + `calculate_state_tax()`.

**Альтернативный нод через PolicyEngine** (Phase 1, рекомендуется):

```python
@observe(name="tax_calculate_policyengine")
async def calculate_tax_policyengine(state: TaxReportState) -> TaxReportState:
    """Replace manual bracket calculations with PolicyEngine US."""
    import policyengine_us as pe

    sim = pe.Simulator(period=state["year"])
    sim.set_input("self_employment_income", state.get("gross_income", 0))
    sim.set_input("employment_income", state.get("w2_income", 0))
    sim.set_input("state_code", state.get("state", "TX"))
    sim.set_input("filing_status", state.get("filing_status", "single"))

    se_tax   = float(sim.calculate("self_employment_tax"))
    se_ded   = float(sim.calculate("self_employment_tax_deduction"))
    qbi_ded  = float(sim.calculate("qualified_business_income_deduction"))
    std_ded  = float(sim.calculate("standard_deduction"))
    taxable  = float(sim.calculate("taxable_income"))
    inc_tax  = float(sim.calculate("income_tax"))
    st_tax   = float(sim.calculate("state_income_tax"))

    gross = state.get("gross_income", 0)
    total_federal = se_tax + inc_tax
    effective_rate = (total_federal / gross * 100) if gross > 0 else 0.0

    return {
        **state,
        "se_tax":           se_tax,
        "se_deduction":     se_ded,
        "qbi_deduction":    qbi_ded,
        "standard_deduction": std_ded,
        "taxable_income":   taxable,
        "income_tax":       inc_tax,
        "state_income_tax": st_tax,
        "total_federal_tax": total_federal,
        "effective_rate":   effective_rate,
        "quarterly_payment": total_federal / 4,
    }
```

### 5.2 Налоговые библиотеки

| Библиотека | PyPI | Применение |
|-----------|------|-----------|
| **PolicyEngine US** | `policyengine-us` | Federal + 50 штатов (ГЛАВНАЯ) |
| **Tax-Calculator (PSL)** | `taxcalc` | Microsimulation, Congressional Budget Office |
| `python-taxjar` | `taxjar` | Sales tax по ZIP (`api.taxjar.com/v2/rates/{zip}`) |

### 5.3 PDF-генерация

| Библиотека | Применение |
|-----------|-----------|
| `weasyprint` | HTML → PDF (уже используем) |
| `pypdf` | Заполнение fillable IRS PDFs (Schedule C, 1040-ES) |
| `reportlab` | Точное позиционирование полей (IRS-формат) |

**Fillable IRS PDFs** — лучший подход для Schedule C, 1040-ES:

```python
import pypdf, io

def fill_schedule_c(data: dict) -> bytes:
    reader = pypdf.PdfReader("forms/f1040sc.pdf")  # Official IRS form
    writer = pypdf.PdfWriter()
    writer.append(reader)
    writer.update_page_form_field_values(
        writer.pages[0],
        {
            "f1_1":  data["business_name"],
            "f1_2":  str(data["gross_receipts"]),
            # ... поля из MeF XSD schema
        },
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
```

### 5.4 RAG Infrastructure (Phase 3)

| Инструмент | GitHub | Роль |
|-----------|--------|------|
| **Qdrant** | qdrant/qdrant | Векторный поиск для IRS Publications |
| **Unstructured** | Unstructured-IO/unstructured | Парсинг IRS PDF → chunks для RAG |
| **Ragas** | vibrantlabsai/ragas | RAG evaluation (faithfulness, relevance) |

**IRS Publications для RAG**:
```
Pub 334 — Schedule C guide (самый важный)
Pub 505 — Estimated Tax (quarterly payments)
Pub 463 — Travel, Vehicle, Meals
Pub 946 — Depreciation (Section 179)
Pub 587 — Home Office (Form 8829)
```

### 5.5 Mileage Tracking (опциональные интеграции)

| Сервис | API | Применение |
|--------|-----|-----------|
| MileIQ | REST | GPS mileage log import |
| Everlance | REST | Mileage + expense tracking |
| Google Maps | REST | Distance calculation для trips |

---

## РАЗДЕЛ 6: РОЛИ LLM (ТОЛЬКО ИНТЕГРИРОВАННЫЕ МОДЕЛИ)

### 6.1 Принцип TurboTax GenOS

**LLM НИКОГДА не выполняет расчёты. Python-only для всей математики.**

```
Пользователь
    │
    ▼
[Gemini Flash Lite] ── Intent detection: "tax_report" vs "tax_estimate"
    │
    ▼
[TaxReportOrchestrator]
    ├── [SQL]                  ── Сбор данных (доходы, расходы, mileage)
    ├── [Gemini Flash Lite]    ── OCR: W-2, 1099, Schedule C (vision)
    ├── [Grok 4.20, опц.]      ── Веб-поиск актуальных IRS ставок
    ├── [Python deterministic] ── ВСЯ налоговая математика
    ├── [Claude Haiku 4.5]     ── Missed deductions + IRS citations
    ├── [Gemini 3 Pro, опц.]   ── Deep analysis доход > $100K
    ├── [Claude Opus 4.6]      ── AMT/NOL/multi-state + extended thinking
    └── [Claude Sonnet 4.6]    ── Финальный нарратив (объясняет, не считает)
```

### 6.2 Таблица ролей

| Модель | ID | Нод | Задача |
|--------|----|-----|--------|
| `gemini-3.1-flash-lite-preview` | Gemini Flash Lite | `collect_documents` | OCR W-2, 1099 (vision) |
| `gemini-3.1-flash-lite-preview` | Gemini Flash Lite | `src/core/intent.py` | Intent detection (уже работает) |
| `claude-haiku-4-5` | Claude Haiku 4.5 | `analyze_deductions` | Missed deductions + whitelist |
| `gemini-3-pro-preview` | Gemini 3 Pro | `deep_deduction_analysis` | Deep analysis (>$100K, опц.) |
| `claude-opus-4-6` | Claude Opus 4.6 | `analyze_complex_scenarios` | AMT/NOL/multi-state + thinking |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | `generate_narrative` | Нарратив (не считает!) |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | `collect_documents` fallback | OCR fallback если Gemini упал |
| `grok-4.20-experimental-beta-0304-reasoning` | Grok 4.20 | `collect_rate_updates` | Web search IRS ставок (опц.) |

**GPT-5.2 не используется в tax pipeline** — только Claude/Gemini/Grok.

### 6.3 LLM routing dict

```python
# src/orchestrators/tax_report/routing.py
TAX_LLM_ROUTING = {
    "ocr_w2":                    "gemini-3.1-flash-lite-preview",
    "ocr_1099":                  "gemini-3.1-flash-lite-preview",
    "ocr_schedule_c":            "gemini-3.1-flash-lite-preview",
    "ocr_fallback":              "claude-sonnet-4-6",

    "missed_deductions_simple":  "claude-haiku-4-5",
    "missed_deductions_complex": "gemini-3-pro-preview",   # >$100K
    "nol_analysis":              "claude-opus-4-6",
    "amt_check":                 "claude-opus-4-6",
    "s_corp_analysis":           "claude-opus-4-6",
    "multi_state":               "claude-opus-4-6",

    "narrative_generation":      "claude-sonnet-4-6",
    "planning_explanation":      "claude-sonnet-4-6",

    "rate_lookup_web":           "grok-4.20-experimental-beta-0304-reasoning",

    # ALL MATH: no LLM!
    "se_tax_calculation":        "python_deterministic",
    "bracket_application":       "python_deterministic",
    "qbi_calculation":           "python_deterministic",
    "state_tax_calculation":     "python_deterministic",
    "standard_deduction":        "python_deterministic",
    "obbba_adjustments":         "python_deterministic",
    "retirement_optimizer":      "python_deterministic",
}
```

### 6.4 Context window планирование

| Модель | Контекст | Использование в tax |
|--------|----------|---------------------|
| Gemini Flash Lite | 1M tokens | OCR до 20 страниц документов |
| Claude Haiku 4.5 | 200K | Expense list + deduction analysis |
| Claude Sonnet 4.6 | 200K | Narrative + числа из state (~500 токенов) |
| Claude Opus 4.6 | 200K | Complex analysis + 5K thinking budget |
| Gemini 3 Pro | 2M tokens | Deep analysis, полная история транзакций |
| Grok 4.20 | 128K | Только query (не вся история) |

### 6.5 Стоимость на запрос (оценка)

| Нод | Модель | In tokens | Out | $/запрос |
|-----|--------|-----------|-----|----------|
| collect_documents (1 doc) | Gemini Flash Lite | ~1,000 | ~200 | ~$0.001 |
| analyze_deductions | Claude Haiku 4.5 | ~500 | ~300 | ~$0.0003 |
| analyze_complex | Claude Opus 4.6 | ~800 + 5K thinking | ~500 | ~$0.05 |
| deep_deduction | Gemini 3 Pro | ~1,200 | ~800 | ~$0.01 |
| generate_narrative | Claude Sonnet 4.6 | ~500 | ~400 | ~$0.003 |
| collect_rate_updates | Grok 4.20 | ~100 | ~200 | ~$0.002 |
| **Итого типичный** | mix | ~3,100 | ~2,400 | **$0.02–0.08** |

Opus — только при сложных сценариях (~20% запросов) → средняя $0.02–0.03.

---

## РАЗДЕЛ 7: OCR НАЛОГОВЫХ ДОКУМЕНТОВ (GEMINI FLASH LITE)

### 7.1 Паттерн (идентичен scan_receipt)

`scan_receipt` уже использует `gemini-3.1-flash-lite-preview` через `_ocr_gemini()`. Тот же механизм для налоговых форм.

### 7.2 PII Tokenization — обязательно перед LLM (IRS IRM 10.24.1)

```python
# src/orchestrators/tax_report/pii_tokenizer.py

class PiiTokenizer:
    """Tokenize PII before LLM context. Required by IRS IRM 10.24.1."""

    def __init__(self):
        self._map: dict[str, str] = {}
        self._counter = 0

    def tokenize(self, value: str, pii_type: str) -> str:
        token = f"[{pii_type.upper()}_{self._counter}]"
        self._map[token] = value
        self._counter += 1
        return token

    def detokenize(self, text: str) -> str:
        for token, value in self._map.items():
            text = text.replace(token, value)
        return text

# Использование в collect_documents:
tokenizer = PiiTokenizer()
safe_ssn = tokenizer.tokenize(ssn_last4, "ssn")     # → "[SSN_0]"
safe_ein = tokenizer.tokenize(employer_ein, "ein")   # → "[EIN_1]"
# Передаём safe_* в Gemini, детокенизируем только для БД
```

### 7.3 JSON-схемы форм

```python
W2_SCHEMA = """\
Извлеки данные из W-2 в JSON:
{
  "form_type": "W-2",
  "employer_name": "string",
  "employer_ein": "[EIN_0]",
  "employee_ssn_last4": "[SSN_0]",
  "tax_year": 2025,
  "box_1_wages": 0.00,
  "box_2_federal_withheld": 0.00,
  "box_3_ss_wages": 0.00,
  "box_4_ss_tax_withheld": 0.00,
  "box_5_medicare_wages": 0.00,
  "box_6_medicare_withheld": 0.00,
  "box_12_codes": [{"code": "D", "amount": 0.00}],
  "box_13_retirement_plan": false,
  "box_16_state_wages": 0.00,
  "box_17_state_tax": 0.00,
  "state": "XX"
}
Ответь ТОЛЬКО валидным JSON. Неизвестные поля ставь null."""

NEC_1099_SCHEMA = """\
Извлеки данные из 1099-NEC в JSON:
{
  "form_type": "1099-NEC",
  "payer_name": "string",
  "payer_tin": "[EIN_0]",
  "recipient_tin_last4": "[SSN_0]",
  "tax_year": 2025,
  "box_1_nonemployee_compensation": 0.00,
  "box_4_federal_withheld": 0.00,
  "box_5_state_income": 0.00,
  "box_6_state_withheld": 0.00,
  "state": "XX"
}
Ответь ТОЛЬКО валидным JSON."""
```

### 7.4 Нод `collect_documents`

```python
# src/orchestrators/tax_report/nodes.py

from google.genai import types as genai_types
from src.core.llm.clients import google_client

_FORM_SYSTEM_PROMPT = (
    "You are a tax document OCR specialist. Extract all fields accurately. "
    "Return ONLY valid JSON, no markdown, no explanations."
)


async def _extract_tax_document_gemini(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """OCR via Gemini Flash Lite (same pattern as scan_receipt)."""
    client = google_client()

    # Step 1: detect form type
    detect_resp = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            "What type of US tax document is this? Answer ONLY: W-2, 1099-NEC, 1099-MISC, 1099-K, Schedule-C, or Other.",
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_FORM_SYSTEM_PROMPT,
            max_output_tokens=20,
        ),
    )
    form_type = detect_resp.text.strip().upper()

    schema = {"W-2": W2_SCHEMA, "1099-NEC": NEC_1099_SCHEMA}.get(form_type, NEC_1099_SCHEMA)

    # Step 2: extract fields
    extract_resp = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            schema,
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_FORM_SYSTEM_PROMPT,
            max_output_tokens=512,
        ),
    )

    import json
    text = extract_resp.text.strip().lstrip("```json").lstrip("```").rstrip("```")
    return json.loads(text)


async def _extract_tax_document_claude_fallback(image_bytes: bytes, mime_type: str) -> dict:
    """Fallback OCR via Claude Sonnet vision."""
    import base64, json
    from src.core.llm.clients import anthropic_client

    client = anthropic_client()
    b64 = base64.standard_b64encode(image_bytes).decode()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
            {"type": "text", "text": "Extract all fields from this US tax document as JSON. Include form_type, all dollar amounts, year, payer info. ONLY valid JSON."},
        ]}],
    )
    return json.loads(resp.content[0].text)


@with_timeout(15)
@observe(name="tax_collect_documents")
async def collect_documents(state: TaxReportState) -> TaxReportState:
    """OCR uploaded tax documents using Gemini Flash Lite + PII tokenization."""
    pending_docs = state.get("pending_documents", [])
    if not pending_docs:
        return {**state, "documents_extracted": []}

    extracted = []
    for doc in pending_docs:
        try:
            data = await _extract_tax_document_gemini(doc["bytes"], doc.get("mime_type", "application/pdf"))
        except Exception as e:
            logger.warning("Gemini OCR failed, trying Claude fallback: %s", e)
            try:
                data = await _extract_tax_document_claude_fallback(doc["bytes"], doc.get("mime_type", "application/pdf"))
            except Exception as e2:
                logger.error("Both OCR failed: %s", e2)
                continue
        extracted.append(data)

    w2_income    = sum(d.get("box_1_wages", 0.0) for d in extracted if d.get("form_type") == "W-2")
    w2_withheld  = sum(d.get("box_2_federal_withheld", 0.0) for d in extracted if d.get("form_type") == "W-2")
    nec_income   = sum(d.get("box_1_nonemployee_compensation", 0.0) for d in extracted if d.get("form_type") == "1099-NEC")

    return {
        **state,
        "documents_extracted": extracted,
        "w2_income": float(w2_income),
        "w2_federal_withheld": float(w2_withheld),
        "extra_1099_income": float(nec_income),
    }
```

---

## РАЗДЕЛ 8: ПОЛНЫЙ ГРАФ ОРКЕСТРАТОРА

### 8.1 TaxReportState (обновлённый)

```python
# src/orchestrators/tax_report/state.py

class TaxReportState(TypedDict):
    # === Input ===
    user_id: str
    family_id: str
    language: str
    currency: str
    business_type: str | None
    state: str | None           # US state code (CA, NY, TX...)
    filing_status: str          # single/mfj/hoh/mfs
    year: int
    quarter: int | None
    home_office_sqft: float
    home_office_total_sqft: float

    # === Collected data ===
    gross_income: float
    w2_income: float
    w2_federal_withheld: float
    extra_1099_income: float
    expenses_by_category: list[dict]
    recurring_payments: list[dict]
    mileage_miles: float        # прямой ввод (не proxy!)
    prior_year_tax: float
    documents_extracted: list[dict]
    pending_documents: list[dict]

    # === OBBBA adjustments ===
    tips_income: float
    overtime_pay: float
    auto_loan_interest: float
    is_senior: bool

    # === Deductions ===
    total_deductible: float
    deduction_breakdown: list[dict]
    mileage_deduction: float
    home_office_deduction: float
    retirement_deduction: float
    obbba_deductions: float
    obbba_breakdown: list[dict]
    additional_deductions: list[str]
    mileage_rate_override: float | None  # от Grok web search

    # === Federal tax ===
    net_profit: float
    se_tax: float
    se_deduction: float
    qbi_deduction: float
    standard_deduction: float
    taxable_income: float
    income_tax: float
    total_federal_tax: float
    effective_rate: float
    quarterly_payment: float

    # === State tax ===
    state_income_tax: float
    state_rate_used: float
    state_qbid_applies: bool
    additional_state_taxes: list[dict]
    quarterly_schedule: list[float]    # CA = [0.30,0.40,0.00,0.30]

    # === Retirement ===
    sep_ira_max: float
    solo_401k_max: float
    retirement_tax_savings: float

    # === Complex analysis ===
    complex_notes: list[str]
    optimization_notes: list[str]
    needs_cpa: bool

    # === Output ===
    schedule_c_lines: dict
    quarterly_vouchers: list[dict]
    narrative: str
    pdf_bytes: bytes | None
    response_text: str
```

### 8.2 Полный граф с моделями

```
START
  ├── collect_income [SQL]
  ├── collect_expenses [SQL]
  ├── collect_recurring [SQL]
  ├── collect_mileage [SQL]
  ├── collect_prior_year [SQL]
  ├── collect_documents [Gemini Flash Lite + PII tokenizer]
  │   └─ fallback: [Claude Sonnet 4.6 vision]
  └── collect_rate_updates [Grok 4.20 web search, OPTIONAL]
                │
                ▼ (fan-in: merge_state)
      analyze_deductions [Claude Haiku 4.5]
      + whitelist + IRS citations + (Phase 3: RAG)
                │
                ▼
      calculate_obbba_adjustments [Python]
      (Tips $25K, Overtime $12.5K, Auto $10K, Senior $6K)
                │
                ▼
      calculate_tax_policyengine [PolicyEngine US — Python]
      (SE tax + QBI + standard deduction + brackets + state)
      OR (Phase 1 quick-fix): calculate_federal_tax + calculate_state_tax [Python]
                │
                ▼
      metamorphic_consistency_check [Python]
      (monotonicity: income+$10 → tax must increase)
       FAIL ─── flag+log                PASS ───┐
                │                               │
                └──── calculate_retirement ─────┘
                      [Python: SEP-IRA / Solo 401k]
                │
                ├── если needs_cpa или gross > $100K:
                │   analyze_complex_scenarios [Claude Opus 4.6 + 5K thinking]
                │   (AMT, NOL, dual-income, multi-state)
                │
                ├── если gross > $100K:
                │   deep_deduction_analysis [Gemini 3 Pro + thinking]
                │   (Section 179, S-Corp, industry-specific)
                │
                ▼
      ┌─── HITL: review_deductions ──────────────────┐
      │  interrupt() → кнопки Telegram               │
      │  Approve / Edit deductions                    │
      │  (только для full annual report)              │
      └──────────────────────────────────────────────┘
                │ approved
                ▼
      generate_narrative [Claude Sonnet 4.6]
      + FIRE EOL notice (если бизнес + year==2026)
                │
                ▼
      generate_schedule_c_worksheet [Python]
      (line-by-line: 8=Advertising, 9=Car, 24=Meals 50%...)
                │
                ▼
      generate_quarterly_vouchers [Python]
      (1040-ES: 4 vouchers, CA=30/40/0/30)
                │
                ▼
      generate_pdf [WeasyPrint / pypdf fillable]
      + audit_log (prompt_hash, model_snapshot, policyengine_version)
                │
                ▼
               END
```

### 8.3 Исправленный `calculate_federal_tax` (manual fallback)

```python
@observe(name="tax_calculate_federal")
async def calculate_federal_tax(state: TaxReportState) -> TaxReportState:
    """Deterministic federal tax — NO LLM. Fixes: standard_deduction + OBBBA + filing_status."""
    gross_income     = state.get("gross_income", 0.0)
    total_deductible = state.get("total_deductible", 0.0)
    obbba_deductions = state.get("obbba_deductions", 0.0)
    filing_status    = state.get("filing_status", "single")

    # 1. Net profit (Schedule C)
    net_profit = max(gross_income - total_deductible, 0.0)

    # 2. SE health insurance — cap at net_profit
    health_ded = min(state.get("health_insurance_expenses", 0.0), net_profit)

    # 3. SE tax
    se_base      = net_profit * SE_NET_FACTOR
    se_tax       = se_base * SE_TAX_RATE
    se_deduction = se_tax * SE_DEDUCTION_FACTOR

    # 4. AGI adjustments
    adjusted_income = net_profit - se_deduction - health_ded - obbba_deductions

    # 5. QBI §199A (permanent per OBBBA)
    qbi_deduction = _calculate_qbi(adjusted_income, filing_status)

    # 6. Standard deduction — WAS MISSING, now fixed!
    standard_ded = STANDARD_DEDUCTION_2026.get(filing_status, 16_100)

    # 7. Taxable income
    taxable = max(adjusted_income - qbi_deduction - standard_ded, 0.0)

    # 8. Income tax from OBBBA-updated brackets
    brackets = {
        "single": BRACKETS_2026_SINGLE,
        "mfj":    BRACKETS_2026_MFJ,
        "hoh":    BRACKETS_2026_HOH,
        "mfs":    BRACKETS_2026_SINGLE,
    }.get(filing_status, BRACKETS_2026_SINGLE)

    income_tax     = _apply_brackets(taxable, brackets)
    total_federal  = se_tax + income_tax
    effective_rate = (total_federal / gross_income * 100) if gross_income > 0 else 0.0

    return {
        **state,
        "net_profit":       net_profit,
        "se_tax":           se_tax,
        "se_deduction":     se_deduction,
        "qbi_deduction":    qbi_deduction,
        "standard_deduction": standard_ded,
        "taxable_income":   taxable,
        "income_tax":       income_tax,
        "total_federal_tax": total_federal,
        "effective_rate":   effective_rate,
        "quarterly_payment": total_federal / 4,
    }
```

### 8.4 Нод `calculate_state_tax`

```python
@observe(name="tax_calculate_state")
async def calculate_state_tax(state: TaxReportState) -> TaxReportState:
    user_state = state.get("state") or "TX"
    config = STATE_TAX_CONFIG.get(user_state, {"type": "none"})

    state_tax = 0.0
    state_qbid_applies = config.get("qbid", True)

    if config["type"] == "none":
        state_tax = 0.0
    elif config["type"] in ("flat", "progressive"):
        base = state.get("net_profit", 0)
        if not state_qbid_applies:
            # Штат не принимает QBID — берём более высокую базу
            base = base + state.get("qbi_deduction", 0)
        state_tax = base * config["rate"]

    # Дополнительные налоги (MCTMT, SDI, etc.)
    additional = []
    for extra in config.get("extras", []):
        if extra.get("threshold") and base < extra["threshold"]:
            continue
        if extra.get("optional"):
            continue  # SDI опциональный
        extra_tax = base * extra["rate"]
        additional.append({"name": extra["name"], "amount": extra_tax})
        state_tax += extra_tax

    quarterly_schedule = config.get("quarterly", [0.25, 0.25, 0.25, 0.25])

    return {
        **state,
        "state_income_tax":      state_tax,
        "state_rate_used":       config.get("rate", 0.0),
        "state_qbid_applies":    state_qbid_applies,
        "additional_state_taxes": additional,
        "quarterly_schedule":    quarterly_schedule,
    }
```

### 8.5 Metamorphic Consistency Check

```python
# Synedrion pattern — проверяем монотонность расчёта
def metamorphic_consistency_check(state: TaxReportState) -> TaxReportState:
    """Post-calculation monotonicity test: income+$10 → tax must increase."""
    base_tax = state.get("total_federal_tax", 0)
    base_income = state.get("gross_income", 0)

    # Быстрый синхронный расчёт для проверки
    delta_tax = _calculate_tax_sync(base_income + 10) - base_tax

    if delta_tax < 0:
        logger.error("METAMORPHIC FAIL: income+$10 → tax decreased by $%.2f", abs(delta_tax))
        # Флаг, но не блокируем — продолжаем с логом
        return {**state, "metamorphic_flag": True}
    if delta_tax > 10:
        logger.error("METAMORPHIC FAIL: tax increased by $%.2f on $10 income", delta_tax)
        return {**state, "metamorphic_flag": True}

    return {**state, "metamorphic_flag": False}
```

### 8.6 Analyze Complex Scenarios (Claude Opus 4.6 + thinking)

```python
@with_timeout(60)
@observe(name="tax_analyze_complex")
async def analyze_complex_scenarios(state: TaxReportState) -> TaxReportState:
    """Complex tax analysis using Claude Opus with extended thinking."""
    from src.core.llm.clients import generate_text

    net_profit = state.get("net_profit", 0)
    complexity_flags = []

    if net_profit < 0:
        complexity_flags.append("potential_nol")
    if state.get("w2_income", 0) > 0 and state.get("gross_income", 0) > 0:
        complexity_flags.append("dual_income_w2_plus_se")
    if state.get("state_income_tax", 0) > 5_000:
        complexity_flags.append("high_state_tax_impact")

    if not complexity_flags:
        return {**state, "complex_notes": [], "needs_cpa": False}

    prompt = f"""
Tax situation analysis:
- Gross SE income: ${state.get('gross_income', 0):,.0f}
- W-2 income: ${state.get('w2_income', 0):,.0f}
- Net SE profit: ${net_profit:,.0f}
- State: {state.get('state', 'unknown')}
- Flags: {', '.join(complexity_flags)}
- Federal tax: ${state.get('total_federal_tax', 0):,.0f} ({state.get('effective_rate', 0):.1f}%)

Analyze:
1. Any AMT risk? (list specific preference items)
2. If net_profit < 0: NOL carryforward strategy?
3. Optimal SE deduction sequencing for dual income?
4. Top 2 tax planning moves before year-end?

Cite IRS sections. Flag if CPA review required.
"""

    response = await generate_text(
        model="claude-opus-4-6",
        system=(
            "You are a senior US tax advisor. Analyze complex self-employed tax scenarios. "
            "Always cite IRS code sections. Flag CPA-required situations explicitly."
        ),
        prompt=prompt,
        max_tokens=1000,
        thinking={"type": "enabled", "budget_tokens": 5000},
    )

    needs_cpa = any(kw in response.lower() for kw in [
        "cpa review required", "consult a cpa", "nol carryforward",
        "passive activity", "alternative minimum tax"
    ])

    notes = [
        line.lstrip("- •*1234567890.").strip()
        for line in response.splitlines()
        if line.strip() and len(line.strip()) > 20
    ][:6]

    return {**state, "complex_notes": notes, "needs_cpa": needs_cpa}
```

### 8.7 Generate Narrative (Claude Sonnet 4.6 — только объясняет)

```python
@with_timeout(30)
@observe(name="tax_generate_narrative")
async def generate_narrative(state: TaxReportState) -> TaxReportState:
    """Human-readable narrative. Sonnet NEVER recalculates — only explains."""
    from src.core.llm.clients import generate_text

    lang = state.get("language", "en")
    gross = state.get("gross_income", 0)
    total_fed = state.get("total_federal_tax", 0)
    total_st  = state.get("state_income_tax", 0)
    sep_savings = state.get("retirement_tax_savings", 0)
    needs_cpa   = state.get("needs_cpa", False)
    year = state.get("year", 2025)
    business_type = state.get("business_type", "")

    # FIRE EOL notice для бизнесов в 2026
    fire_note = ""
    if business_type and year == 2026:
        fire_note = (
            "\n\n⚠️ <b>FIRE System EOL:</b> The IRS FIRE system for 1099 filing ends Dec 31, 2026. "
            "You must switch to IRIS REST API before 2027 or face penalties."
        )

    system = f"""\
You are a financial advisor explaining a tax report summary.
RULES:
1. NEVER recalculate — use ONLY the numbers provided
2. Lead with: what to pay and when
3. Mention SEP-IRA opportunity if savings > $2,000
4. If needs_cpa=True: strongly recommend CPA
5. Tone: smart capable friend, not corporate
6. Language: {lang}
7. Format: Telegram HTML (<b>, <i>)
8. Max 6 sentences + 2-3 bullets
ALWAYS append: "⚠️ AI estimate only — not tax advice. Consult a CPA before filing."
"""

    data = f"""
Tax Report (DO NOT RECALCULATE — explain only):
- Gross SE: ${gross:,.0f}
- Federal tax: ${total_fed:,.0f} ({state.get('effective_rate', 0):.1f}% effective)
- State ({state.get('state', '')}): ${total_st:,.0f}
- Total: ${total_fed + total_st:,.0f}
- Quarterly payment: ${state.get('quarterly_payment', 0):,.0f}
- SEP-IRA potential savings: ${sep_savings:,.0f}
- Complex flags: {state.get('complex_notes', [])[:2]}
- Needs CPA: {needs_cpa}
"""

    narrative = await generate_text(
        model="claude-sonnet-4-6",
        system=system,
        prompt=data,
        max_tokens=600,
    )

    return {**state, "narrative": narrative + fire_note}
```

### 8.8 1040-ES Quarterly Vouchers

```python
def build_quarterly_vouchers(state: TaxReportState) -> list[dict]:
    """Generate 4 quarterly payment vouchers with safe harbor calculation."""
    total_federal = state.get("total_federal_tax", 0)
    total_state   = state.get("state_income_tax", 0)
    prior_year    = state.get("prior_year_tax", 0)
    user_state    = state.get("state", "")

    # Safe harbor: min(90% current, 100% prior year)
    safe_harbor = min(total_federal * 0.90, prior_year) if prior_year > 0 else total_federal * 0.90
    recommended = max(safe_harbor, total_federal * 0.90)

    schedule = state.get("quarterly_schedule", [0.25, 0.25, 0.25, 0.25])
    deadlines = [
        ("Q1", "April 15, 2026"),
        ("Q2", "June 15, 2026"),
        ("Q3", "September 15, 2026"),
        ("Q4", "January 15, 2027"),
    ]

    vouchers = []
    for i, (qname, deadline) in enumerate(deadlines):
        pct = schedule[i]
        if pct == 0:
            continue  # CA пропускает Q3
        vouchers.append({
            "quarter": qname,
            "deadline": deadline,
            "federal_amount": recommended / 4,
            "state_amount": total_state * pct,
            "total_amount": recommended / 4 + total_state * pct,
            "state": user_state,
            "form": "1040-ES",
        })

    return vouchers
```

### 8.9 Schedule C Line Mapping

```python
CATEGORY_TO_SCHEDULE_C_LINE = {
    "Связь/Интернет":     "25",   # Utilities
    "Подписки":           "18",   # Office expense
    "Образование":        "27",   # Other expenses
    "Транспорт":          "9",    # Car and truck
    "Такси":              "24",   # Travel
    "Питание/Рестораны":  "24",   # Meals (50% only)
    "Электроника":        "13",   # Depreciation/Section 179
    "Медицина":           "15",   # Insurance (health)
    "Аренда":             "20b",  # Rent - property
    "Коммунальные":       "25",   # Utilities
    "Реклама":            "8",    # Advertising
    "Юридические":        "17",   # Legal/professional
    "Банк":               "27",   # Other (bank fees)
}

SCHEDULE_C_LINES_DESCRIPTION = {
    "8":  "Advertising",
    "9":  "Car and truck expenses (mileage)",
    "10": "Commissions and fees",
    "11": "Contract labor",
    "13": "Depreciation and section 179",
    "15": "Insurance (other than health)",
    "17": "Legal and professional services",
    "18": "Office expense",
    "20": "Rent or lease",
    "24": "Travel and meals (50% meals)",
    "25": "Utilities",
    "27": "Other expenses",
    "28": "Total expenses",
    "30": "Home office deduction (Form 8829)",
    "31": "Net profit or (loss)",
}
```

---

## РАЗДЕЛ 9: ANALYSE ВЫЧЕТОВ — CLAUDE HAIKU 4.5

### 9.1 Улучшенный системный промпт с whitelist

```python
DEDUCTION_ANALYSIS_SYSTEM = """\
You are a US tax deduction specialist for self-employed individuals.
RULES:
1. Only suggest deductions from this IRS-approved list:
   - Home office (§280A, Form 8829): regular & exclusive use
   - Vehicle mileage (§162): $0.70/mile, requires mileage log
   - SEP-IRA (§404): up to 25% net SE income, max $70,000
   - Solo 401(k) (§401): employee $23,500 + employer 25%
   - Health insurance (§162(l)): 100% if no employer coverage
   - Professional development (§162): courses, books, subscriptions
   - Business meals (§274): 50%, documented business purpose
   - De minimis safe harbor ($2,500 per item): equipment/supplies
2. For each suggestion: cite IRS section (e.g., "§162", "Pub 334 p.45")
3. If you cannot cite a source — DO NOT suggest the deduction
4. Max 4 suggestions. Specific to provided expense data.
5. Format: bullet points. Language: {lang}"""
```

### 9.2 RAG на IRS Publications (Phase 3)

```
PDF → Unstructured (parse) → chunks → embeddings → Qdrant
Query → similarity search → Claude Haiku (answer + citation)

Публикации для RAG:
- Pub 334 (Schedule C) — ежегодно обновляется (январь)
- Pub 505 (Estimated Tax)
- Pub 463 (Travel, Vehicle, Meals)
- Pub 946 (Depreciation, Section 179)
- Pub 587 (Home Office, Form 8829)
```

---

## РАЗДЕЛ 10: ДЕЛОВЫЕ ДЕДЛАЙНЫ И КОНСТАНТЫ

### 10.1 Налоговые дедлайны 2026

```python
TAX_DEADLINES_2026 = {
    "w2_1099_send":          "February 2, 2026",
    "partnership_1065":      "March 16, 2026",
    "s_corp_1120s":          "March 16, 2026",
    "individual_1040":       "April 15, 2026",
    "q1_estimated":          "April 15, 2026",
    "q2_estimated":          "June 15, 2026",
    "q3_estimated":          "September 15, 2026",
    "extension_deadline":    "October 15, 2026",
    "q4_estimated":          "January 15, 2027",
    "sep_ira_contribution":  "October 15, 2026",   # с extension
    "solo_401k_establish":   "December 31, 2026",  # plan creation deadline
    "fire_system_eol":       "December 31, 2026",  # FIRE → IRIS
}
```

### 10.2 Retirement limits 2026

```python
SEP_IRA_PCT = 0.25          # 25% net SE income
SEP_IRA_MAX = 70_000        # 2025: $69K, 2026 est: $70K
SOLO_401K_EMPLOYEE_2026 = 23_500
SOLO_401K_CATCHUP_2026  = 7_500    # 50+
SOLO_401K_EMPLOYEE_MAX  = 31_000   # с catch-up
SS_WAGE_BASE_2026 = 176_100
```

### 10.3 SE tax constants

```python
SE_TAX_RATE       = 0.153
SE_NET_FACTOR     = 0.9235
SE_DEDUCTION_FACTOR = 0.50

HOME_OFFICE_SIMPLIFIED_RATE    = 5.0    # $5/sq ft
HOME_OFFICE_SIMPLIFIED_MAX_SQFT = 300
HOME_OFFICE_SIMPLIFIED_MAX     = 1_500  # $5 * 300
```

---

## РАЗДЕЛ 11: COMPLIANCE И DISCLAIMERS

### 11.1 Обязательный disclaimer (Circular 230 + IRS IRM)

```python
TAX_AI_DISCLAIMERS = {
    "en": (
        "⚠️ This report was generated using AI and deterministic tax calculations. "
        "It is for informational purposes only and does not constitute professional "
        "tax advice. Please review with a licensed CPA before filing. "
        "Calculations based on IRS publications and PolicyEngine US model."
    ),
    "ru": (
        "⚠️ Этот отчёт создан с помощью AI и детерминированных налоговых расчётов. "
        "Носит информационный характер и не является профессиональной налоговой консультацией. "
        "Проверьте с лицензированным CPA перед подачей декларации."
    ),
    "es": (
        "⚠️ Este informe fue generado con IA y cálculos determinísticos de impuestos. "
        "Solo con fines informativos — no constituye asesoramiento fiscal profesional. "
        "Consulte a un CPA licenciado antes de presentar su declaración."
    ),
}
```

### 11.2 Audit Log (IRS IRM 10.24.1 — prompt logs 1 год)

```python
AUDIT_LOG_FIELDS = {
    "timestamp":           "ISO-8601",
    "user_id":             "hashed (SHA-256)",
    "family_id":           "hashed",
    "model_snapshot":      "claude-haiku-4-5 / claude-sonnet-4-6",
    "prompt_hash":         "SHA-256 of system prompt",
    "policyengine_version": "pe.__version__",
    "report_hash":         "SHA-256 of output PDF",
    "hitl_approved_by":    "user_id or 'auto'",
    "langfuse_trace_id":   "UUID via @observe",
}
# Хранить в Langfuse — уже интегрирован через @observe
```

### 11.3 CPA-эскалация — обязательные триггеры

```python
CPA_ESCALATION_TRIGGERS = [
    lambda s: s.get("total_federal_tax", 0) > 10_000,
    lambda s: s.get("net_profit", 0) < 0,            # potential NOL
    lambda s: len(s.get("documents_extracted", [])) > 5,
    lambda s: s.get("w2_income", 0) > 0 and s.get("gross_income", 0) > 0,
    lambda s: s.get("state_income_tax", 0) > 5_000,
]

def check_cpa_escalation(state: TaxReportState) -> bool:
    return any(trigger(state) for trigger in CPA_ESCALATION_TRIGGERS)
```

### 11.4 State chatbot best practices

| Штат | Паттерн | Применяем |
|------|---------|----------|
| Missouri DORA | 24/7, первое сообщение = disclaimer | ✓ |
| Ohio | "This is a chatbot, not a human" | ✓ в tax_report intro |
| California FTB | General (без аккаунта) vs MyFTB (с аккаунтом) | Наш bot = general |

---

## РАЗДЕЛ 12: ПРИОРИТИЗИРОВАННЫЙ ROADMAP

### Матрица приоритетов (20 задач)

| # | Задача | Источник | Приоритет | Сложность | Файл |
|---|--------|---------|-----------|----------|------|
| 1 | **PolicyEngine US** вместо ручных brackets | taxdeep2 | 🔴 P0 | Средняя | `nodes.py`, `state.py` |
| 2 | Standard deduction $16,100 (критический баг) | анализ | 🔴 P0 | Низкая | `deductions.py`, `nodes.py` |
| 3 | Brackets 2026 (OBBBA) — исправить | анализ | 🔴 P0 | Низкая | `deductions.py` |
| 4 | Mileage deduction применить к расчёту | анализ | 🔴 P0 | Низкая | `nodes.py` |
| 5 | PII tokenization перед LLM (SSN/EIN) | IRS IRM | 🔴 P1 | Средняя | новый `pii_tokenizer.py` |
| 6 | Metamorphic consistency check | taxdeep2 | 🟡 P1 | Низкая | `nodes.py` |
| 7 | State tax engine (50 штатов, PolicyEngine) | оба | 🔴 P1 | Средняя | `nodes.py`, `deductions.py` |
| 8 | Filing status (single/MFJ/HoH/MFS) | анализ | 🔴 P1 | Средняя | `state.py`, `nodes.py` |
| 9 | FIRE EOL notice в narrative | taxdeep2 | 🟡 P2 | Низкая | `nodes.py` |
| 10 | CA quarterly 30/40/0/30 | анализ | 🟡 P2 | Низкая | `deductions.py` |
| 11 | OBBBA Tips/Overtime/Auto/Senior | анализ | 🟡 P2 | Низкая | `nodes.py` |
| 12 | SEP-IRA / Solo 401k optimizer | анализ | 🟡 P2 | Средняя | `nodes.py` |
| 13 | Audit logging (Langfuse: prompt hash, model snapshot) | IRS IRM | 🟡 P2 | Низкая | `nodes.py` |
| 14 | OCR документов (Gemini Flash Lite + PII tokenizer) | наш план | 🟢 P3 | Средняя | `nodes.py` |
| 15 | HITL review checkpoint (interrupt → кнопки) | наш план | 🟢 P3 | Средняя | `graph.py` |
| 16 | Schedule C line-by-line PDF worksheet | наш план | 🟢 P3 | Высокая | `nodes.py` |
| 17 | 1040-ES vouchers (4 квартала) | наш план | 🟢 P3 | Средняя | `nodes.py` |
| 18 | RAG на IRS Publications (Pub 334, 505, 463) | IRS/taxdeep1 | ⚪ P4 | Высокая | новый модуль |
| 19 | Ragas eval для RAG | taxdeep1 | ⚪ P4 | Средняя | тесты |
| 20 | DSPy prompt optimization | taxdeep2 | ⚪ P4 | Высокая | будущее |

### Phase Timeline

| Фаза | Недели | Задачи | Результат |
|------|--------|--------|---------|
| **Phase 1** | 1 | 1–4, 8 | Правильная математика (исправить 4 критических бага) |
| **Phase 2** | 2–3 | 5–8, 10 | State tax engine + PII + filing status |
| **Phase 3** | 3–4 | 9, 11–13 | OBBBA + retirement + audit |
| **Phase 4** | 4–5 | 14 | OCR документов (Gemini) |
| **Phase 5** | 5–6 | 15–17 | HITL + Schedule C PDF + 1040-ES |
| **Phase 6** | 7+ | 18–20 | RAG, eval, optimization |

---

## РАЗДЕЛ 13: ТЕСТИРОВАНИЕ

### 13.1 Unit tests — минимальный набор (Phase 1)

```python
# tests/test_orchestrators/test_tax_calculations.py

async def test_standard_deduction_applied():
    """Regression: standard deduction must be subtracted."""
    state = await calculate_federal_tax({
        "gross_income": 60_000,
        "total_deductible": 0,
        "obbba_deductions": 0,
        "filing_status": "single",
        "year": 2026,
    })
    # Without std_ded: taxable = ~$55K → tax ~$7.5K
    # With std_ded $16,100: taxable = ~$39K → tax ~$4K
    assert state["income_tax"] < 5_000, "Standard deduction not applied!"
    assert state["standard_deduction"] == 16_100

async def test_mfj_brackets():
    """MFJ income should use MFJ brackets."""
    state = await calculate_federal_tax({
        "gross_income": 120_000,
        "total_deductible": 0,
        "obbba_deductions": 0,
        "filing_status": "mfj",
        "year": 2026,
    })
    single_state = await calculate_federal_tax({
        "gross_income": 120_000,
        "total_deductible": 0,
        "obbba_deductions": 0,
        "filing_status": "single",
        "year": 2026,
    })
    assert state["income_tax"] < single_state["income_tax"]  # MFJ pays less

async def test_ca_quarterly_schedule():
    """CA must use 30/40/0/30 quarterly schedule."""
    state = await calculate_state_tax({"state": "CA", "net_profit": 100_000, ...})
    assert state["quarterly_schedule"] == [0.30, 0.40, 0.00, 0.30]
    vouchers = build_quarterly_vouchers(state)
    assert len(vouchers) == 3  # Q3 skipped!

def test_metamorphic_monotonicity():
    """Tax must increase when income increases."""
    tax_100 = _calculate_tax_sync(100_000)
    tax_110 = _calculate_tax_sync(100_010)
    assert tax_110 > tax_100
    assert tax_110 - tax_100 <= 10  # can't exceed 100% rate
```

### 13.2 Regression checklist

- [ ] `single` $60K: income_tax < $5K (standard deduction applied)
- [ ] `mfj` $120K: income_tax < single $120K
- [ ] CA $100K: quarterly = [30%, 40%, skip, 30%]
- [ ] Mileage 1000 miles at $0.70: deduction = $700 added to total_deductible
- [ ] SE health insurance > net_profit: capped at net_profit
- [ ] OBBBA tips $30K: capped at $25K
- [ ] Metamorphic: income+$10 → tax+$1 to $10

---

## РАЗДЕЛ 14: КЛЮЧЕВЫЕ ПРАВИЛА

### Что ЗАПРЕЩЕНО для LLM

```python
# ❌ НИКОГДА не делать в LLM:
"Рассчитай SE tax для дохода $X"
"Сколько мне нужно платить налогов?"
"Какой процент QBI вычета для $Y дохода?"

# ✅ ПРАВИЛЬНО: LLM только объясняет готовые детерминированные числа:
"Вот результат расчёта: SE tax = $X, QBI = $Y. Объясни что это значит пользователю."
```

### Разграничение ответственности

| Компонент | Реализация | Никогда |
|-----------|-----------|---------|
| SE tax | Python | LLM |
| Standard deduction | Python | LLM |
| Bracket application | Python | LLM |
| QBI §199A | Python | LLM |
| State tax | Python + PolicyEngine | LLM |
| Mileage deduction | Python | LLM |
| Объяснение вычета | LLM + RAG + citation | Hardcode |
| Missed deductions | LLM с whitelist | LLM без whitelist |
| Planning scenarios | LLM + deterministic calc | LLM alone |
| AMT/NOL analysis | Opus + thinking | Без thinking |

### Fine-tuning — недоступен (2026-03-10)

- GPT-5.2: `Fine-tuning: Not supported`
- Claude 4.6: no self-serve fine-tuning

**Стратегия**: RAG + prompt engineering + structured outputs + deterministic engine.

---

## РАЗДЕЛ 15: DEPLOYMENT NOTES

### Новые зависимости

```toml
# pyproject.toml
[project.dependencies]
policyengine-us = ">=2.0.0"   # Federal + 50 штатов
pypdf = ">=4.0.0"              # Fillable IRS PDFs (уже есть в document agent?)
qdrant-client = ">=1.9.0"     # Vector store для RAG (Phase 3)
unstructured = ">=0.12.0"     # PDF parsing для RAG (Phase 3)
```

### Env vars (новые)

```bash
# Нет новых внешних API! Только PolicyEngine (local library)
# FIRE→IRIS: если будем реализовывать actual 1099 filing:
# IRIS_CLIENT_ID=...
# IRIS_CLIENT_SECRET=...
```

### Feature flags

```python
# config/profiles/_family_defaults.yaml
# Добавить:
ff_tax_policyengine: false    # Phase 1: включить после тестов
ff_tax_ocr_documents: false   # Phase 4: OCR W-2/1099
ff_tax_hitl_review: false     # Phase 5: interrupt перед PDF
ff_tax_rag_deductions: false  # Phase 6: RAG на IRS Publications
```

---

## РАЗДЕЛ 16: QUICK REFERENCE — КРИТИЧЕСКИЕ ЧИСЛА 2026

```python
# Все константы для src/orchestrators/tax_report/deductions.py

# Standard Deduction
STANDARD_DEDUCTION = {"single": 16_100, "mfj": 32_200, "hoh": 24_150, "mfs": 16_100}

# SE Tax
SE_TAX_RATE = 0.153; SE_NET_FACTOR = 0.9235; SS_WAGE_BASE = 176_100

# Mileage
MILEAGE_RATE_2025 = 0.700  # IRS официально $0.70/mile
MILEAGE_RATE_2026 = 0.725  # оценка (объявит IRS декабрь 2025)

# QBI
QBI_RATE = 0.20
QBI_PHASEOUT_START = {"single": 203_000, "mfj": 406_000}
QBI_PHASEOUT_END   = {"single": 272_300, "mfj": 544_600}

# OBBBA
OBBBA = {
    "tips_max": 25_000, "tips_phaseout_single": 150_000,
    "overtime_single": 12_500, "overtime_mfj": 25_000,
    "auto_loan": 10_000, "senior_65plus": 6_000,
}
SALT_CAP = 40_400

# Retirement
SEP_IRA = {"pct": 0.25, "max": 70_000}
SOLO_401K = {"employee": 23_500, "catchup_50plus": 7_500}

# Home Office (simplified)
HOME_OFFICE = {"rate_per_sqft": 5.0, "max_sqft": 300, "max_total": 1_500}

# Deadlines 2026
Q1 = "April 15"; Q2 = "June 15"; Q3 = "September 15"; Q4 = "January 15, 2027"
FIRE_EOL = "December 31, 2026"
```

---

*Составлен: 2026-03-10*
*Источники: IRS.gov, Tax Foundation 2025, OBBBA July 4 2025, IRS IRM 10.24.1 Feb 10 2026,
PolicyEngine US docs, taxdeep1.md + taxdeep2.md (проектные исследования),
TurboTax GenOS architecture, Synedrion framework, PSL Tax-Calculator.*

*Этот документ объединяет:*
- *`2026-03-10-tax-report-orchestrator-full-integration-plan.md`*
- *`2026-03-10-tax-llm-integration-plan.md`*
- *`2026-03-10-taxdeep-synthesis.md`*
