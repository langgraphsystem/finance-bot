# TaxReportOrchestrator — LLM Integration Plan (только наши модели)

> Полный план использования ТОЛЬКО интегрированных моделей:
> Claude (Opus/Sonnet/Haiku), GPT-5.2, Gemini (Flash Lite / Pro), Grok 4.20

---

## 1. РОЛИ МОДЕЛЕЙ В НАЛОГОВОМ ПАЙПЛАЙНЕ

### Принцип TurboTax GenOS (адаптировано для нас)

```
Пользователь
    │
    ▼
[Gemini Flash Lite] ── Intent detection: "tax_report" vs "tax_estimate"
    │
    ▼
[TaxReportOrchestrator]
    ├── [Gemini Flash Lite]  ── OCR: W-2, 1099, Schedule C (vision)
    ├── [Grok 4.20]          ── Поиск актуальных ставок IRS (если нужно)
    ├── [Python deterministic] ── ВСЯ налоговая математика
    ├── [Claude Haiku 4.5]   ── Анализ упущенных вычетов
    ├── [Claude Opus 4.6]    ── AMT, NOL, сложные сценарии + extended thinking
    └── [Claude Sonnet 4.6]  ── Финальный нарратив + PDF текст
```

### Таблица ролей

| Модель | Роль в налоговом пайплайне | Нод/задача |
|--------|---------------------------|-----------|
| `gemini-3.1-flash-lite-preview` | OCR налоговых документов (W-2, 1099, Schedule C) | `collect_documents` |
| `gemini-3.1-flash-lite-preview` | Intent detection (уже работает) | `src/core/intent.py` |
| `gemini-3-pro-preview` | Deep reasoning: сложный анализ вычетов с thinking | `analyze_complex_deductions` |
| `claude-haiku-4-5` | Быстрый анализ упущенных вычетов (уже есть) | `analyze_deductions` |
| `claude-sonnet-4-6` | Нарратив отчёта, объяснение вычетов, PDF текст | `generate_pdf` |
| `claude-opus-4-6` | AMT detection, NOL, сложные multi-state сценарии | `analyze_complex` |
| `gpt-5.2` | Не используется в tax pipeline | — |
| `grok-4.20-experimental-beta-0304-reasoning` | Веб-поиск актуальных ставок IRS | `collect_rate_updates` (опц.) |

**Математика ВСЕГДА deterministic Python** — ни одна модель не делает расчёты.

---

## 2. OCR НАЛОГОВЫХ ДОКУМЕНТОВ — GEMINI 3.1 FLASH LITE

### Паттерн (такой же как scan_receipt)

`scan_receipt` уже использует `gemini-3.1-flash-lite-preview` для OCR фото через `_ocr_gemini()`. Тот же механизм применяем для налоговых документов.

### Новый нод: `collect_documents`

```python
# src/orchestrators/tax_report/nodes.py

from google.genai import types as genai_types
from src.core.llm.clients import google_client

# ── JSON-схемы для каждого типа формы ──────────────────────────────────────

W2_SCHEMA = """\
Извлеки данные из W-2 в JSON:
{
  "form_type": "W-2",
  "employer_name": "string",
  "employer_ein": "XX-XXXXXXX",
  "employee_ssn_last4": "XXXX",
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
  "payer_tin": "XX-XXXXXXX",
  "recipient_tin_last4": "XXXX",
  "tax_year": 2025,
  "box_1_nonemployee_compensation": 0.00,
  "box_4_federal_withheld": 0.00,
  "box_5_state_income": 0.00,
  "box_6_state_withheld": 0.00,
  "state": "XX"
}
Ответь ТОЛЬКО валидным JSON."""

MISC_1099_SCHEMA = """\
Извлеки данные из 1099-MISC или 1099-K в JSON:
{
  "form_type": "1099-MISC",
  "payer_name": "string",
  "tax_year": 2025,
  "box_3_other_income": 0.00,
  "box_7_nonemployee_compensation": 0.00,
  "box_1_rents": 0.00,
  "box_4_federal_withheld": 0.00,
  "gross_amount_1099k": 0.00
}
Ответь ТОЛЬКО валидным JSON."""

_FORM_SYSTEM_PROMPT = (
    "You are a tax document OCR specialist. Extract all fields accurately. "
    "Return ONLY valid JSON, no markdown, no explanations."
)


async def _extract_tax_document_gemini(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> dict:
    """Extract tax form data using Gemini Flash Lite vision (same pattern as scan_receipt)."""
    client = google_client()

    # Сначала определяем тип формы
    detect_prompt = (
        "What type of US tax document is this? Answer with one of: "
        "W-2, 1099-NEC, 1099-MISC, 1099-K, 1099-INT, 1099-DIV, Schedule-C, Other. "
        "Answer ONLY the form type, nothing else."
    )
    detect_resp = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            detect_prompt,
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_FORM_SYSTEM_PROMPT,
            max_output_tokens=20,
        ),
    )
    form_type = detect_resp.text.strip().upper()

    # Выбираем схему по типу формы
    schema_map = {
        "W-2": W2_SCHEMA,
        "1099-NEC": NEC_1099_SCHEMA,
        "1099-MISC": MISC_1099_SCHEMA,
        "1099-K": MISC_1099_SCHEMA,
    }
    schema = schema_map.get(form_type, MISC_1099_SCHEMA)

    # Основная экстракция
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
    text = extract_resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


@with_timeout(15)
@observe(name="tax_collect_documents")
async def collect_documents(state: TaxReportState) -> TaxReportState:
    """OCR uploaded tax documents (W-2, 1099) using Gemini Flash Lite."""
    # Документы приходят из state["pending_documents"] (загружены в Redis)
    pending_docs = state.get("pending_documents", [])
    if not pending_docs:
        return {**state, "documents_extracted": []}

    extracted = []
    for doc in pending_docs:
        try:
            data = await _extract_tax_document_gemini(
                image_bytes=doc["bytes"],
                mime_type=doc.get("mime_type", "application/pdf"),
            )
            extracted.append(data)
            logger.info("Extracted %s: %s", data.get("form_type"), data)
        except Exception as e:
            logger.warning("Document OCR failed: %s", e)

    # Суммируем W-2 доход и withholding
    w2_income = sum(
        d.get("box_1_wages", 0.0)
        for d in extracted
        if d.get("form_type") == "W-2"
    )
    w2_withheld = sum(
        d.get("box_2_federal_withheld", 0.0)
        for d in extracted
        if d.get("form_type") == "W-2"
    )
    nec_income = sum(
        d.get("box_1_nonemployee_compensation", 0.0)
        for d in extracted
        if d.get("form_type") == "1099-NEC"
    )

    return {
        **state,
        "documents_extracted": extracted,
        "w2_income": float(w2_income),
        "w2_federal_withheld": float(w2_withheld),
        "extra_1099_income": float(nec_income),
    }
```

### Fallback: Claude Sonnet (если Gemini не справился)

```python
async def _extract_tax_document_claude_fallback(
    image_bytes: bytes,
    mime_type: str,
) -> dict:
    """Fallback OCR via Claude Sonnet vision."""
    import base64
    from src.core.llm.clients import anthropic_client

    client = anthropic_client()
    b64 = base64.standard_b64encode(image_bytes).decode()

    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Extract all fields from this US tax document as JSON. "
                        "Include form_type (W-2/1099-NEC/etc), all dollar amounts, "
                        "year, payer/employer info. Return ONLY valid JSON."
                    ),
                },
            ],
        }],
    )
    import json
    return json.loads(resp.content[0].text)
```

---

## 3. АНАЛИЗ ВЫЧЕТОВ — CLAUDE HAIKU 4.5 (УЛУЧШЕННЫЙ)

### Текущее использование (уже в `analyze_deductions`)

Уже работает. Нужно улучшить: добавить whitelist + цитаты IRS.

```python
# УЛУЧШЕНИЕ: системный промпт с whitelisted deductions
DEDUCTION_ANALYSIS_SYSTEM = """\
You are a US tax deduction specialist for self-employed individuals.
RULES:
1. Only suggest deductions from this IRS-approved list:
   - Home office (§280A, Form 8829): regular & exclusive business use only
   - Vehicle mileage (§162): standard rate $0.70/mile, requires mileage log
   - SEP-IRA contributions (§404): up to 25% net SE income, max $70,000
   - Solo 401(k) contributions (§401): employee $23,500 + employer 25%
   - Health insurance premiums (§162(l)): 100% if no employer coverage
   - Professional development (§162): courses, books, subscriptions for current trade
   - Business meals (§274): 50% for documented business purpose
   - Retirement plan administrative fees (§162): 100%
   - Safe harbor de minimis ($2,500 per item): equipment/supplies under threshold
2. For each suggestion: cite the IRS section (e.g., "§162", "Pub 334 p.45")
3. If you cannot cite a source — DO NOT suggest the deduction
4. Max 4 suggestions. Be specific to the expense data provided.
5. Format: bullet points only. Language: {lang}"""

DEDUCTION_ANALYSIS_PROMPT = """\
Gross income: ${gross:.0f}
Net profit after Schedule C deductions: ${net:.0f}
Expenses (top categories):
{expenses}
Recurring payments:
{recurring}
Already identified deductions: {identified}
State: {state}
Business type: {business_type}

Which commonly missed deductions apply here? Only suggest if clearly applicable."""
```

---

## 4. СЛОЖНЫЕ СЦЕНАРИИ — CLAUDE OPUS 4.6 + EXTENDED THINKING

### Когда использовать Opus

| Сценарий | Триггер | Модель |
|---------|---------|--------|
| AMT detection | income_tax low но большие preference items | Opus + thinking |
| NOL carryforward | net_profit < 0 | Opus |
| Multi-state | state_count > 1 | Opus |
| SSTB QBI phaseout | SSTB business + income near threshold | Opus |
| S-Corp K-1 income | documents contain K-1 | Opus |
| Passive losses | rental + business combined | Opus |

```python
@with_timeout(60)
@observe(name="tax_analyze_complex")
async def analyze_complex_scenarios(state: TaxReportState) -> TaxReportState:
    """Deep analysis for complex tax situations using Claude Opus with extended thinking."""
    from src.core.llm.clients import generate_text

    complexity_flags = []
    net_profit = state.get("net_profit", 0)

    if net_profit < 0:
        complexity_flags.append("potential_nol")
    if state.get("w2_income", 0) > 0 and state.get("gross_income", 0) > 0:
        complexity_flags.append("dual_income_w2_plus_se")
    if state.get("state_income_tax", 0) > 5_000:
        complexity_flags.append("high_state_tax_impact")

    if not complexity_flags:
        return {**state, "complex_notes": [], "needs_cpa": False}

    prompt = f"""
Tax situation analysis needed:
- Gross SE income: ${state.get('gross_income', 0):,.0f}
- W-2 income: ${state.get('w2_income', 0):,.0f}
- Net SE profit: ${net_profit:,.0f}
- State: {state.get('state', 'unknown')}
- Flags: {', '.join(complexity_flags)}
- Total federal tax: ${state.get('total_federal_tax', 0):,.0f}
- Effective rate: {state.get('effective_rate', 0):.1f}%

Analyze:
1. Any AMT risk? (List specific preference items if present)
2. If net_profit < 0: NOL carryforward strategy?
3. For dual W-2+SE income: optimal SE deduction sequencing?
4. Top 2 tax planning moves before year-end?

Be specific. Cite IRS sections. Flag if CPA review is required.
"""

    response = await generate_text(
        model="claude-opus-4-6",
        system=(
            "You are a senior US tax advisor. Analyze complex self-employed tax scenarios. "
            "Always cite IRS code sections. Flag situations requiring CPA review explicitly."
        ),
        prompt=prompt,
        max_tokens=1000,
        thinking={"type": "enabled", "budget_tokens": 5000},
    )

    needs_cpa = any(kw in response.lower() for kw in [
        "cpa review required", "consult a cpa", "professional advice required",
        "nol carryforward", "passive activity", "alternative minimum tax"
    ])

    # Extract bullet points
    notes = [
        line.lstrip("- •*1234567890.").strip()
        for line in response.splitlines()
        if line.strip() and len(line.strip()) > 20
    ][:6]

    return {**state, "complex_notes": notes, "needs_cpa": needs_cpa}
```

---

## 5. ГЛУБОКИЙ АНАЛИЗ ВЫЧЕТОВ — GEMINI 3 PRO + THINKING

### Когда использовать Gemini Pro

Для пользователей с доходом >$100K или бизнес-типом construction/flowers — более глубокий анализ через Gemini 3 Pro с thinking.

```python
@with_timeout(45)
@observe(name="tax_deep_deduction_analysis")
async def deep_deduction_analysis(state: TaxReportState) -> TaxReportState:
    """Use Gemini 3 Pro with thinking for high-income users."""
    from src.core.llm.clients import generate_text

    gross = state.get("gross_income", 0)
    # Только для высокодоходных или сложных бизнесов
    if gross < 100_000 and state.get("business_type") not in ("construction", "flowers"):
        return state  # Skip — обычный Claude Haiku достаточно

    expenses_json = str(state.get("expenses_by_category", [])[:20])
    business_type = state.get("business_type", "general")

    prompt = f"""
Self-employed tax optimization analysis:

Business type: {business_type}
Gross income: ${gross:,.0f}
Expenses by category (JSON): {expenses_json}
State: {state.get('state', 'unknown')}
Year: {state.get('year', 2025)}

Perform deep analysis:
1. Section 179 / Bonus depreciation opportunities (list specific asset types)
2. Retirement account optimal strategy (SEP-IRA vs Solo 401k vs SIMPLE)
3. Business structure optimization (sole prop vs S-corp tax savings estimate)
4. Timing strategies (defer income to next year? accelerate deductions?)
5. Industry-specific deductions for {business_type}

For each recommendation provide:
- Estimated tax savings ($)
- IRS citation
- Required documentation
"""

    response = await generate_text(
        model="gemini-3-pro-preview",
        system=(
            "You are a senior US tax strategist specializing in self-employed optimization. "
            "Provide actionable recommendations with specific dollar estimates and IRS citations."
        ),
        prompt=prompt,
        max_tokens=1500,
        thinking_level="high",
    )

    optimization_notes = [
        line.lstrip("- •*1234567890.").strip()
        for line in response.splitlines()
        if line.strip() and len(line.strip()) > 30
    ][:8]

    return {**state, "optimization_notes": optimization_notes}
```

---

## 6. АКТУАЛЬНЫЕ СТАВКИ — GROK 4.20 (ОПЦИОНАЛЬНО)

### Когда использовать Grok

Grok 4.20 (`grok-4.20-experimental-beta-0304-reasoning`) имеет web search. Используем для:
- Проверки актуальных IRS mileage rates
- Проверки state tax изменений текущего года
- Новых IRS updates (Revenue Procedures, Notices)

Уже используется в `dual_search` для research. Тот же паттерн.

```python
@with_timeout(25)
@observe(name="tax_collect_rate_updates")
async def collect_rate_updates(state: TaxReportState) -> TaxReportState:
    """Optional: verify current IRS rates via Grok web search."""
    from src.core.research.dual_search import dual_search

    year = state.get("year", 2025)
    user_state = state.get("state", "")

    # Только если год текущий И у нас нет актуальных данных в кэше
    today_year = __import__("datetime").date.today().year
    if year != today_year:
        return state  # Прошлые годы — используем hardcoded

    try:
        query = f"IRS standard mileage rate {year} self-employed"
        result = await dual_search(query, max_results=2)

        # Простой парсинг ставки из результата
        import re
        match = re.search(r"\$?(0\.\d{2,3})\s*(?:per\s*)?mile", result, re.IGNORECASE)
        if match:
            rate = float(match.group(1))
            if 0.50 < rate < 1.00:  # sanity check
                logger.info("Grok rate update: mileage = $%.3f/mile", rate)
                return {**state, "mileage_rate_override": rate}
    except Exception as e:
        logger.warning("Grok rate update failed (non-critical): %s", e)

    return state
```

**Важно**: Grok — необязательный нод. Если упал — пайплайн продолжает с hardcoded значениями.

---

## 7. НАРРАТИВ ОТЧЁТА — CLAUDE SONNET 4.6

### Роль: объяснить результат пользователю

Sonnet **не считает** — только объясняет готовые числа из state.

```python
@with_timeout(30)
@observe(name="tax_generate_narrative")
async def generate_narrative(state: TaxReportState) -> TaxReportState:
    """Generate human-readable tax report narrative using Claude Sonnet."""
    from src.core.llm.clients import generate_text

    lang = state.get("language", "en")
    gross = state.get("gross_income", 0)
    total_federal = state.get("total_federal_tax", 0)
    total_state = state.get("state_income_tax", 0)
    effective_federal = state.get("effective_rate", 0)
    sep_ira_max = state.get("sep_ira_max", 0)
    retirement_savings = state.get("retirement_tax_savings", 0)
    complex_notes = state.get("complex_notes", [])
    optimization_notes = state.get("optimization_notes", [])
    needs_cpa = state.get("needs_cpa", False)

    system = f"""\
You are a financial advisor explaining a tax report summary to a client.
Rules:
1. NEVER recalculate — use ONLY the numbers provided
2. Explain what the numbers mean in plain language
3. Lead with the key action item (what to pay, when)
4. Mention the biggest deduction opportunity if SEP-IRA savings > $2,000
5. If needs_cpa=True: strongly recommend consulting a CPA
6. Tone: smart capable friend, not corporate
7. Language: {lang}
8. Format: Telegram HTML (<b>, <i>, <code>)
9. Max 6 sentences + 2-3 bullet points

DISCLAIMER (always append): "⚠️ Estimate only — not tax advice. Consult a CPA."
"""

    data = f"""
Tax Report Data (DO NOT RECALCULATE — just explain):
- Gross SE income: ${gross:,.0f}
- Federal tax: ${total_federal:,.0f} ({effective_federal:.1f}% effective)
- State tax ({state.get('state', '')}): ${total_state:,.0f}
- Total combined: ${total_federal + total_state:,.0f}
- Quarterly payment: ${state.get('quarterly_payment', 0):,.0f}
- Biggest opportunity: SEP-IRA could save ${retirement_savings:,.0f} in taxes
- Complex notes: {complex_notes[:2]}
- Needs CPA review: {needs_cpa}
"""

    narrative = await generate_text(
        model="claude-sonnet-4-6",
        system=system,
        prompt=data,
        max_tokens=600,
    )

    return {**state, "narrative": narrative}
```

---

## 8. ИТОГОВЫЙ ГРАФ С МОДЕЛЯМИ

```python
# src/orchestrators/tax_report/graph.py (полная версия)

_COLLECTORS = [
    "collect_income",       # SQL, no LLM
    "collect_expenses",     # SQL, no LLM
    "collect_recurring",    # SQL, no LLM
    "collect_mileage",      # SQL, no LLM
    "collect_prior_year",   # SQL, no LLM
    "collect_documents",    # Gemini 3.1 Flash Lite (OCR W-2/1099)
    "collect_rate_updates", # Grok 4.20 (optional web search)
]

# После fan-in:
# analyze_deductions         → Claude Haiku 4.5
# analyze_complex_scenarios  → Claude Opus 4.6 + extended thinking (если нужно)
# deep_deduction_analysis    → Gemini 3 Pro + thinking (income > $100K)
# calculate_obbba_adjustments → deterministic Python
# calculate_federal_tax       → deterministic Python
# calculate_state_tax         → deterministic Python
# calculate_retirement_opportunity → deterministic Python
# HITL: review_deductions    → interrupt() → user confirms via Telegram buttons
# generate_narrative          → Claude Sonnet 4.6
# generate_schedule_c_worksheet → deterministic Python
# generate_quarterly_vouchers → deterministic Python
# generate_pdf                → WeasyPrint (deterministic)
```

### Визуализация

```
START ──┬── collect_income ─────────────────────────────────────────────┐
        ├── collect_expenses ──────────────────────────────────────────┤
        ├── collect_recurring ────────────────────────────────────────┤
        ├── collect_mileage ─────────────────────────────────────────┤
        ├── collect_prior_year ─────────────────────────────────────┤
        ├── collect_documents [Gemini Flash Lite OCR] ───────────────┤
        └── collect_rate_updates [Grok 4.20, опц.] ─────────────────┤
                                                                      ▼
                                          ┌── analyze_deductions [Claude Haiku 4.5]
                                          │
                                          ├── analyze_complex [Claude Opus 4.6+thinking]
                                          │   (только если: NOL/AMT/dual-income)
                                          │
                                          └── deep_deduction [Gemini 3 Pro+thinking]
                                              (только если: gross > $100K)
                                                         │
                                                         ▼
                                          calculate_obbba_adjustments [Python]
                                                         │
                                                         ▼
                                          calculate_federal_tax [Python]
                                                         │
                                                         ▼
                                          calculate_state_tax [Python]
                                                         │
                                                         ▼
                                          calculate_retirement_opportunity [Python]
                                                         │
                                                         ▼
                                          ┌─ HITL: review_deductions ──────────────┐
                                          │  interrupt() → кнопки Approve/Edit      │
                                          │  (только для full annual report)         │
                                          └─────────────────────────────────────────┘
                                                         │
                                                         ▼
                                          generate_narrative [Claude Sonnet 4.6]
                                                         │
                                                         ▼
                                          generate_schedule_c_worksheet [Python]
                                                         │
                                                         ▼
                                          generate_quarterly_vouchers [Python]
                                                         │
                                                         ▼
                                          generate_pdf [WeasyPrint]
                                                         │
                                                         ▼
                                                        END
```

---

## 9. КОНКРЕТНЫЕ ПРАВИЛА — КАКАЯ МОДЕЛЬ ЧТО ДЕЛАЕТ

### ЗАПРЕЩЕНО для LLM

```python
# ❌ НИКОГДА не делать в LLM:
"Сколько мне платить налогов? Посчитай."
"Какая ставка SE tax? Применяй к $X."
"Рассчитай QBI вычет для дохода $Y."

# ✅ Правильно: LLM только объясняет готовые числа:
"Вот результаты расчёта: SE tax $X, QBI вычет $Y. Объясни что это значит."
```

### Разграничение по типу задачи

```python
TAX_LLM_ROUTING = {
    # Task -> Model
    "ocr_w2": "gemini-3.1-flash-lite-preview",
    "ocr_1099": "gemini-3.1-flash-lite-preview",
    "ocr_schedule_c": "gemini-3.1-flash-lite-preview",
    "ocr_fallback": "claude-sonnet-4-6",          # если Gemini упал

    "missed_deductions_simple": "claude-haiku-4-5",      # доход < $100K
    "missed_deductions_complex": "gemini-3-pro-preview", # доход > $100K
    "nol_analysis": "claude-opus-4-6",
    "amt_check": "claude-opus-4-6",
    "s_corp_analysis": "claude-opus-4-6",

    "narrative_generation": "claude-sonnet-4-6",
    "planning_explanation": "claude-sonnet-4-6",

    "rate_lookup_web": "grok-4.20-experimental-beta-0304-reasoning",

    # ALL MATH: no LLM!
    "se_tax_calculation": "python_deterministic",
    "bracket_application": "python_deterministic",
    "qbi_calculation": "python_deterministic",
    "state_tax_calculation": "python_deterministic",
    "standard_deduction": "python_deterministic",
}
```

---

## 10. CONTEXT WINDOW ПЛАНИРОВАНИЕ

| Модель | Контекст | Использование в tax |
|--------|----------|---------------------|
| Gemini Flash Lite | 1M tokens | OCR до 20 страниц документов |
| Claude Haiku 4.5 | 200K | Expense list + deduction analysis |
| Claude Sonnet 4.6 | 200K | Narrative + full state context |
| Claude Opus 4.6 | 200K | Complex analysis + 5K thinking budget |
| Gemini 3 Pro | 2M tokens | Deep analysis с полной историей транзакций |
| Grok 4.20 | 128K | Веб поиск (только query, не вся история) |

**Для generate_narrative**: передаём только цифры из state (~500 токенов), не всю историю транзакций.

**Для analyze_deductions**: передаём топ-15 категорий расходов (~300 токенов).

**Для collect_documents**: PDF/изображение через Gemini multimodal — до 500MB.

---

## 11. ОБРАБОТКА ОШИБОК И FALLBACKS

```python
# Каждый LLM нод имеет fallback стратегию

# OCR:
#   Primary: Gemini Flash Lite
#   Fallback: Claude Sonnet vision
#   Если оба упали: пропустить documents_extracted = []

# Deduction analysis:
#   Primary: Claude Haiku
#   Если упал: вернуть [] (пустой список доп. вычетов, расчёт продолжится)

# Complex analysis:
#   Primary: Claude Opus
#   Если упал: пропустить, needs_cpa=False (не блокируем отчёт)

# Deep analysis Gemini Pro:
#   Primary: Gemini 3 Pro
#   Если упал: пропустить optimization_notes = []

# Narrative:
#   Primary: Claude Sonnet
#   Fallback: _build_response_text() — уже есть в nodes.py

# Rate update (Grok):
#   Primary: Grok web search
#   Если упал: использовать hardcoded MILEAGE_RATE_2026 = 0.725
```

---

## 12. ФАЗИРОВАННЫЙ ПЛАН РЕАЛИЗАЦИИ (только LLM часть)

### Phase 1 — Исправить текущие проблемы (неделя 1)

| Задача | Модель | Файл |
|--------|--------|------|
| Улучшить системный промпт `analyze_deductions` | Claude Haiku 4.5 | `nodes.py` |
| Добавить whitelist deductions + IRS citations | Claude Haiku 4.5 | `nodes.py` |
| Исправить brackets/standard deduction (deterministic) | Python | `deductions.py` |
| Добавить `filing_status` в state и calculate_tax | Python | `nodes.py`, `state.py` |

### Phase 2 — OCR документов (неделя 2-3)

| Задача | Модель | Файл |
|--------|--------|------|
| `collect_documents` нод | Gemini Flash Lite | `nodes.py` |
| W-2, 1099-NEC JSON схемы | Gemini Flash Lite | `nodes.py` |
| Claude vision fallback | Claude Sonnet | `nodes.py` |
| IntentData: `pending_documents` список | — | `schemas/intent.py` |
| Тесты с mock bytes | — | `tests/test_orchestrators/` |

### Phase 3 — State Tax + OBBBA (неделя 3)

| Задача | Модель | Файл |
|--------|--------|------|
| `STATE_TAX_CONFIG` для 50 штатов | Python | `deductions.py` |
| `calculate_state_tax` нод | Python | `nodes.py` |
| `calculate_obbba_adjustments` нод | Python | `nodes.py` |
| CA quarterly 30/40/0/30 | Python | `nodes.py` |

### Phase 4 — Narrative + Deep Analysis (неделя 4)

| Задача | Модель | Файл |
|--------|--------|------|
| `generate_narrative` нод (заменить `_build_response_text`) | Claude Sonnet 4.6 | `nodes.py` |
| `analyze_complex_scenarios` нод | Claude Opus 4.6 | `nodes.py` |
| `deep_deduction_analysis` нод | Gemini 3 Pro | `nodes.py` |
| Routing logic: когда Haiku vs Opus vs Gemini Pro | — | `graph.py` |

### Phase 5 — Retirement Optimizer + Grok (неделя 5)

| Задача | Модель | Файл |
|--------|--------|------|
| `calculate_retirement_opportunity` нод | Python | `nodes.py` |
| `collect_rate_updates` нод (опц.) | Grok 4.20 | `nodes.py` |
| Интеграция с `dual_search` паттерном | Grok 4.20 | `nodes.py` |

### Phase 6 — HITL + PDF (неделя 6)

| Задача | Модель | Файл |
|--------|--------|------|
| `interrupt()` перед generate_pdf | LangGraph | `graph.py` |
| Кнопки Approve/Edit deductions | — | `router.py` |
| Schedule C worksheet PDF | Python/WeasyPrint | `nodes.py` |
| 1040-ES vouchers PDF | Python/WeasyPrint | `nodes.py` |
| Multi-section PDF (federal + state + retirement) | WeasyPrint | `nodes.py` |

---

## 13. ТОКЕНЫ И СТОИМОСТЬ (оценка)

| Нод | Модель | Входных токенов | Выходных | Стоимость/запрос |
|-----|--------|----------------|----------|-----------------|
| collect_documents (1 doc) | Gemini Flash Lite | ~1,000 (image) | ~200 | ~$0.001 |
| analyze_deductions | Claude Haiku 4.5 | ~500 | ~300 | ~$0.0003 |
| analyze_complex | Claude Opus 4.6 | ~800 + 5K thinking | ~500 | ~$0.05 |
| deep_deduction | Gemini 3 Pro | ~1,200 | ~800 | ~$0.01 |
| generate_narrative | Claude Sonnet 4.6 | ~500 | ~400 | ~$0.003 |
| collect_rate_updates | Grok 4.20 | ~100 | ~200 | ~$0.002 |
| **Итого типичный запрос** | Mix | ~3,100 | ~2,400 | **~$0.02–0.08** |

Opus используется только при сложных сценариях (~20% запросов) → средняя стоимость $0.02–0.03.

---

*Документ: 2026-03-10. Только интегрированные модели. Нет Azure, нет внешних OCR сервисов.*
