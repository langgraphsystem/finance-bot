# Document Agent — Comprehensive Implementation Plan

**Date**: 2026-02-28
**Status**: ✅ DONE (2026-03-10) — 19/19 skills реализованы, document versioning + pgvector hybrid search
**Agent name**: `document`
**Model**: `claude-sonnet-4-6`

---

## 1. Executive Summary

Создаём 13-й агент `document`, объединяющий и расширяющий все возможности работы с документами. Агент станет единой точкой входа для: OCR/сканирования, конвертации форматов, генерации документов из шаблонов, работы с таблицами, хранилища документов, и AI-анализа содержимого.

**Текущее состояние**: документы размазаны по 3 агентам (receipt, writing, finance_specialist) без единой точки входа, без хранилища, без шаблонов, без работы с таблицами.

**Целевое состояние**: выделенный агент с 16 скиллами, LangGraph-оркестратор для сложных пайплайнов, data_tools для доступа к Document таблице, Code Execution (E2B) для точных вычислений и генерации файлов, 8 новых Python-библиотек.

---

## 2. What We Have Today (AS-IS)

### Agents touching documents

| Agent | Skills | What it does |
|-------|--------|-------------|
| receipt | scan_receipt, scan_document | OCR через Gemini + Claude fallback, сохранение в Document/Transaction |
| writing | convert_document + 8 others | Конвертация форматов (LibreOffice, Pandoc, Calibre, Pillow) |
| finance_specialist | generate_invoice + 3 others | Генерация инвойсов (текст, без PDF) |

### Infrastructure already in place

- `src/tools/conversion_service.py` — 57 format pairs (LibreOffice, Pandoc, Calibre, Pillow, pypdfium2)
- `src/core/reports.py` — PDF generation via WeasyPrint + Jinja2
- `src/core/visual_cards.py` — HTML → PNG rendering
- `src/core/models/document.py` — Document model (family_id, type, ocr_*, storage_path)
- `src/core/schemas/document_scan.py` — InvoiceData, GenericDocumentData
- `src/core/schemas/receipt.py` — ReceiptData, ReceiptItem
- Docker: LibreOffice, Pandoc, Calibre installed
- Python: WeasyPrint, pypdfium2, Pillow, Jinja2

### Known bugs & gaps

1. **Auto-save broken**: confidence always 0.9, threshold > 0.95 → never triggers
2. **storage_path = "pending"**: no actual upload to Supabase
3. **Dual pending storage**: scan_receipt uses in-memory, scan_document uses Redis
4. **PDF→image first page only**: multi-page PDFs lose data
5. **No document listing/search**: users can't find previously scanned docs
6. **No template system**: no DOCX/Excel templates
7. **No table extraction**: can't parse tables from images or PDFs
8. **Invoice = text only**: no actual PDF generation for invoices

---

## 3. Claude Sonnet 4.6 — Native Document Capabilities

### 3.1 Input Format Support

| Format | How Sonnet processes it | Notes |
|--------|------------------------|-------|
| **PDF** | Страницы конвертируются в изображения и передаются через vision API | Постранично. Нативный текст + layout understanding. |
| **Images** (JPEG/PNG/WebP/GIF) | Vision API напрямую | Включая сканы документов, фото чеков, скриншоты |
| **TXT/MD/HTML/CSV** | Как текст в контексте | Без ограничений |
| **Excel (.xlsx)** | Только через конвертацию в CSV/текст | openpyxl → текст → Sonnet |
| **Word (.docx)** | Только через конвертацию в текст | python-docx → текст → Sonnet |

### 3.2 PDF & Document Intelligence (OfficeQA benchmark — флагманский уровень)

| Capability | Описание | Архитектурное решение |
|-----------|----------|----------------------|
| **Data extraction** | Извлечение структурированных данных из любого документа | Instructor + Pydantic-схема → данные сразу в БД |
| **Summarization** | Резюме с сохранением ключевых цифр и фактов | Прямой вызов Sonnet с документом |
| **Content search** | Поиск конкретной информации в документе | "Найди срок оплаты в этом контракте" |
| **Multi-doc comparison** | Сравнение нескольких документов, поиск противоречий | 200K контекст = ~50 страниц за 1 запрос |
| **Cited conclusions** | Выводы со ссылками на конкретные страницы/секции | Ответ с citation markers |
| **Handwriting recognition** | Рукописные заметки через vision | Gemini Flash primary, Sonnet fallback |

### 3.3 Table & Data Analysis

| Capability | Описание | Как используем |
|-----------|----------|---------------|
| **Anomaly detection** | Выбросы, пропуски, нетипичные значения | analyze_document + extract_table |
| **Correlation analysis** | Связи между колонками, тренды | Code Execution (pandas) для точных результатов |
| **Aggregation** | SUM/AVG/COUNT/PIVOT | Code Execution — не угадывает, а вычисляет |
| **Financial modeling** | Бюджетирование, сценарный анализ, прогнозы | Code Execution (pandas + numpy) |
| **Pattern interpretation** | Человекочитаемые выводы из данных | Sonnet анализирует результаты Code Execution |

### 3.4 Code Execution (E2B Sandbox — уже в проекте)

**Ключевое**: Sonnet пишет Python-код, E2B выполняет его, возвращает точный результат.

```
User: "Посчитай рентабельность по этой таблице"
                    ↓
Sonnet: пишет pandas-скрипт для анализа
                    ↓
E2B sandbox: выполняет код, возвращает числа + графики
                    ↓
Sonnet: интерпретирует результаты на человеческом языке
```

**Что уже есть**: `src/core/sandbox/e2b_runner.py` — полноценный async runner с dependency installation, timeout, web app support.

**Что нужно для document agent**: расширить runner для возврата файлов (xlsx, pdf, pptx) из sandbox, не только stdout.

**Библиотеки доступные в E2B sandbox** (ставятся через pip install):
- `pandas`, `numpy` — анализ данных
- `openpyxl`, `xlsxwriter` — генерация Excel с формулами и чартами
- `python-pptx` — генерация презентаций
- `matplotlib`, `plotly` — графики
- `reportlab`, `fpdf2` — генерация PDF
- `python-docx` — генерация Word

**Преимущество**: не загружаем тяжёлые библиотеки (pandas ~150MB, matplotlib ~50MB) в основной Docker-образ. Они живут в E2B sandbox.

### 3.5 Structured Extraction (Instructor — уже в проекте)

```python
# Задаёшь JSON-схему — получаешь данные строго в формате
class InvoiceExtract(BaseModel):
    vendor: str
    date: date
    total: Decimal
    items: list[LineItem]
    payment_terms: str | None

# Sonnet + Instructor → типизированные данные, сразу в БД
result = await instructor_client.messages.create(
    model="claude-sonnet-4-6",
    response_model=InvoiceExtract,
    messages=[{"role": "user", "content": [image_block, text_prompt]}]
)
```

**Что уже есть**: `src/core/llm/clients.py` — `get_instructor_anthropic()` singleton.

### 3.6 Document Generation via Code Execution

| Формат | Как генерируем | Где исполняется |
|--------|---------------|-----------------|
| **PDF-отчёты** | WeasyPrint (HTML→PDF) | In-process (WeasyPrint уже в Docker) |
| **Excel с формулами и чартами** | Sonnet пишет openpyxl/xlsxwriter код | E2B sandbox |
| **Презентации (PPTX)** | Sonnet пишет python-pptx код | E2B sandbox |
| **Word (DOCX)** | docxtpl для шаблонов / python-docx для генерации | In-process (лёгкие либы) |
| **LaTeX → PDF** | Sonnet пишет LaTeX, pdflatex компилирует | E2B sandbox (texlive) |

### 3.7 Context Window & Multi-Document

| Tier | Контекст | Что помещается | Использование |
|------|---------|----------------|---------------|
| **Standard** | 200K tokens | ~50 страниц PDF, ~150K слов | По умолчанию для всех скиллов |
| **Extended (beta)** | 1M tokens | ~250 страниц, десятки PDF | Для `compare_documents` (много файлов), `analyze_document` (длинные контракты) |

**Архитектурное решение**: использовать standard (200K) по умолчанию. Extended (1M) — только для explicitly multi-doc operations (compare 5+ documents, analyze 100+ page contracts), gated by feature flag `ff_extended_context`.

### 3.8 Model Routing Strategy

| Task | Model | Why |
|------|-------|-----|
| **OCR / image classification** | Gemini 3 Flash | Дешевле, быстрее, отличное качество OCR |
| **Document understanding / analysis** | Claude Sonnet 4.6 | OfficeQA лидер, cited conclusions |
| **Table extraction from images** | Gemini 3 Flash → Sonnet fallback | Flash для простых таблиц, Sonnet для сложных |
| **Structured data extraction** | Claude Sonnet 4.6 + Instructor | Гарантированный typed output |
| **Code generation for files** | Claude Sonnet 4.6 → E2B | Sonnet пишет код, E2B исполняет |
| **Simple format conversion** | In-process (LibreOffice/Pandoc) | Не нужен LLM |
| **Template filling** | In-process (docxtpl/pypdf) | Не нужен LLM для подстановки |
| **Financial analysis** | Sonnet 4.6 + E2B (pandas) | Sonnet рассуждает, pandas считает |

---

## 4. New Libraries to Add

### Must-have (Phase 1-2)

| Library | Purpose | Size | License | Why |
|---------|---------|------|---------|-----|
| **pdfplumber** | PDF text + table extraction | ~2MB | MIT | Best Python lib for extracting tables from native PDFs. Handles complex layouts, merged cells. Pure Python (uses pdfminer.six). No system deps. |
| **pypdf** | PDF merge/split/forms/watermark | ~1MB | BSD | Successor to PyPDF2 (deprecated). Pure Python, zero deps. Merge/split pages, fill PDF forms, flatten, encrypt. Swiss army knife for PDF manipulation. |
| **python-docx** | DOCX read/write | ~1MB | MIT | Create/modify Word documents. Insert tables, images, headers. Mature (10+ years). Standard for DOCX in Python. |
| **docxtpl** | DOCX Jinja2 templates | ~50KB | LGPL | Jinja2 syntax inside Word documents: `{{client_name}}`, `{% for item in items %}`. Built on python-docx + Jinja2 (both already common). Perfect for contracts, invoices, proposals. |
| **openpyxl** | Excel read/write | ~4MB | MIT | Read/write .xlsx files. Formatting, charts, formulas, conditional formatting. Can read existing files as templates. |
| **qrcode** | QR code generation | ~100KB | BSD | QR-коды на инвойсах (ссылка на оплату), визитках, документах. Tiny, zero deps (uses Pillow for rendering, already installed). |
| **python-barcode** | Barcode generation | ~50KB | MIT | Штрих-коды для документов (EAN, Code128, ISBN). Используется с Pillow writer. |

### Should-have (Phase 3)

> **Note**: `python-pptx` (~3MB) и тяжёлые аналитические библиотеки (`pandas`, `numpy`, `matplotlib`, `xlsxwriter`) НЕ ставим в основной Docker-образ. Они устанавливаются в E2B sandbox через `pip install` при генерации файлов. Это экономит ~200MB в Docker image.

| Library | Purpose | Size | License | Why |
|---------|---------|------|---------|-----|
| **xlsxwriter** | Excel generation with charts | ~2MB | BSD | 16 chart types, sparklines, streaming writes for large datasets. Write-only but best formatting of any Excel lib. |
| **camelot-py[base]** | PDF table extraction (advanced) | ~3MB | MIT | Better than pdfplumber for complex bordered tables (Lattice mode with OpenCV). Requires ghostscript system dep. |
| **img2table** | Table extraction from images | ~1MB | MIT | Detect/extract tables from photos. Supports 8 OCR backends. Handles merged cells, skew correction up to 45°. |

### Nice-to-have (Phase 4+)

| Library | Purpose | Why defer |
|---------|---------|----------|
| **marker** | PDF → Markdown with layout | Heavy (ML models, torch, ~2GB). Use Gemini vision instead for now. Best quality when needed. |
| **docling** (IBM) | AI document understanding | 97.9% accuracy on complex tables, no GPU needed. Defer until extract_table needs advanced parsing. |
| **pyhanko** | PDF digital signatures (PAdES) | Only needed when e-signature feature is requested. Only serious Python lib for PDF signing. |
| **deepdiff** | Structured comparison | Can use built-in `difflib` for text comparison initially. Add for JSON/structured diffs later. |
| **MarkItDown** (Microsoft) | Universal doc → Markdown | Swiss army knife for LLM data prep. 86k GitHub stars. Defer until AI analysis needs richer Markdown input. |

### Libraries NOT recommended

| Library | Why skip |
|---------|---------|
| **PyMuPDF (fitz)** | AGPL-3.0 license — must open-source entire app or buy commercial license. Use pypdf + pdfplumber instead. |
| **tabula-py** | Requires JRE (Java) — heavy system dep, subprocess overhead. Use pdfplumber/camelot instead. |
| **pandas** | ~150MB. Overkill for document processing. Use openpyxl directly. |
| **EasyOCR** | PyTorch ~2GB. Struggles with numbers/currency. Already have Gemini 3 Flash for OCR. |
| **PaddleOCR** | Best accuracy but needs PaddlePaddle framework. Heavy dep. Gemini 3 Flash covers our OCR needs. |
| **LlamaParse** | Cloud-only, standalone lib deprecated May 2026. |
| **mammoth** | DOCX → HTML already covered by LibreOffice. |
| **tablib** | openpyxl + xlsxwriter cover our needs. |

---

## 5. Skill Architecture (TO-BE)

### Document Agent — 16 Skills

| # | Skill | Intent | Priority | Source |
|---|-------|--------|----------|--------|
| 1 | scan_document | `scan_document` | P0 | **Move** from receipt agent + enhance |
| 2 | convert_document | `convert_document` | P0 | **Move** from writing agent + enhance (split/rotate/encrypt/watermark) |
| 3 | generate_invoice_pdf | `generate_invoice_pdf` | P1 | **New** (extends existing generate_invoice + QR code) |
| 4 | list_documents | `list_documents` | P1 | **New** |
| 5 | search_documents | `search_documents` | P1 | **New** |
| 6 | extract_table | `extract_table` | P1 | **New** (pdfplumber + Gemini + Code Execution for analysis) |
| 7 | fill_template | `fill_template` | P2 | **New** (DOCX/XLSX + template library) |
| 8 | analyze_document | `analyze_document` | P2 | **New** (Sonnet vision + cited conclusions + Q&A) |
| 9 | merge_documents | `merge_documents` | P2 | **New** |
| 10 | fill_pdf_form | `fill_pdf_form` | P2 | **New** |
| 11 | generate_spreadsheet | `generate_spreadsheet` | P3 | **New** (Sonnet → E2B: openpyxl + charts + formulas) |
| 12 | compare_documents | `compare_documents` | P3 | **New** (multi-doc, cited diffs) |
| 13 | summarize_document | `summarize_document` | P3 | **New** |
| 14 | generate_document | `generate_document` | P3 | **New** (contracts, NDAs, proposals, price lists) |
| 15 | generate_presentation | `generate_presentation` | P3 | **New** (Sonnet → E2B: python-pptx) |
| 16 | pdf_operations | `pdf_operations` | P2 | **New** (split/rotate/encrypt/decrypt/watermark/extract pages) |

### Skill Details

#### 1. `scan_document` (P0 — move + enhance)
**Move from**: receipt agent → document agent
**Enhancements**:
- **Sonnet 4.6 Structured Extraction**: Instructor + Pydantic schema → typed data directly to DB
- **Auto-classification**: Sonnet определяет тип документа (invoice, contract, form, report) и подбирает schema
- Per-field confidence scoring (not hardcoded 0.9)
- Document quality checker before OCR (blur detection via Pillow)
- Multi-page support: PDF страницы → images → Sonnet vision (постранично)
- Multi-language prompts based on `context.language`
- Actual Supabase upload (fix storage_path = "pending")
- Duplicate detection (SHA-256 content_hash)
- **Cross-agent chain**: scan → auto-suggest "Add as expense?" → chain to chat agent
- **Full-text indexing**: extracted text → `extracted_text` column → PostgreSQL GIN search

**Note**: `scan_receipt` stays in receipt agent (financial-specific, creates Transaction).

#### 2. `convert_document` (P0 — move + enhance)
**Move from**: writing agent → document agent
**Enhancements**:
- Format synonym resolution: "word" → docx, "excel" → xlsx, "powerpoint" → pptx
- Multi-page PDF → images (ZIP or numbered files)
- Batch conversion (multiple files in one message)
- Progress indication for long conversions
- Quality/compression presets
- **Smart conversion via Sonnet**: для сложных конвертаций (PDF→XLSX с данными из таблиц), Sonnet анализирует контент и генерирует код в E2B

#### 3. `generate_invoice_pdf` (P1 — new)
**What**: Generate professional PDF invoices from data
**How**:
- Claude Sonnet generates HTML invoice from user's business profile + contact + line items
- WeasyPrint renders to PDF
- Support for business logo/letterhead from profile config
- Multiple templates: simple, professional, detailed
- Auto-populate from recent transactions (reuse generate_invoice data fetch)
- **QR code**: qrcode lib генерирует QR со ссылкой на оплату (Stripe, PayPal, или custom URL)
- **Auto-numbering**: sequential invoice numbers per family_id
- **Cross-agent chain**: "Отправь этот инвойс клиенту" → chain to email agent
**Output**: SkillResult with document=pdf_bytes, document_name="invoice_001.pdf"

#### 4. `list_documents` (P1 — new)
**What**: List user's stored documents with filters
**How**:
- Query Document table via data_tools (agent has data_tools_enabled=True)
- Filters: type (receipt, invoice, etc.), date range, search in ocr_parsed
- Pagination via buttons ("← Previous | Next →")
- Format: type icon + date + merchant/title + amount
**Output**: Formatted list with inline buttons for detailed view

#### 5. `search_documents` (P1 — new)
**What**: Full-text search across scanned documents
**How**:
- Search `ocr_parsed` JSONB via PostgreSQL `@>` or full-text search
- Search by: merchant name, amounts, dates, keywords in extracted_text
- Ranked by relevance (priority: exact match > partial > fuzzy)
- Show context snippet around match
**Output**: Search results with document details and view buttons

#### 6. `extract_table` (P1 — new)
**What**: Extract tables from PDF/images/documents + optional analysis
**How**:
- **From native PDF**: pdfplumber (primary) → camelot-py (fallback for complex tables)
- **From images**: Gemini 3 Flash vision → structured table JSON
- **From DOCX/XLSX**: python-docx tables / openpyxl sheets (direct parsing)
- **Output formats**: structured JSON, CSV, or render as formatted text
- Claude Sonnet post-processes: cleans headers, normalizes data types, fixes OCR errors
- **Optional analysis via Code Execution**: если пользователь просит "проанализируй эту таблицу":
  - Sonnet пишет pandas-скрипт → E2B выполняет → точные агрегаты, аномалии, корреляции
  - Sonnet интерпретирует результаты на человеческом языке
  - Не угадывает цифры, а вычисляет
**Output**: Table as formatted text + optional CSV/XLSX file + optional analysis summary

#### 7. `fill_template` (P2 — new)
**What**: Fill DOCX/Excel templates with user data + template library
**How**:
- User uploads template (DOCX with `{{placeholders}}` or Excel with `{placeholders}`)
- Claude Sonnet extracts placeholder list from template
- Matches placeholders to: conversation context, DB data (contacts, transactions), user-provided values
- For missing values: asks user via buttons/text
- **DOCX**: docxtpl renders with Jinja2
- **XLSX**: openpyxl finds and replaces placeholders
- **PDF output**: optional post-conversion via LibreOffice
- **Template Library**: сохранённые шаблоны пользователя в Document (type=template)
  - "Покажи мои шаблоны" → list_documents с filter type=template
  - "Заполни шаблон контракта для Иванова" → автоматически ищет template по имени
  - Первый upload → предлагает "Сохранить как шаблон?"
**Output**: Filled document (DOCX/XLSX/PDF)

#### 8. `analyze_document` (P2 — new)
**What**: Deep AI analysis of any document — Q&A, risk detection, cited conclusions
**How**:
- **PDF native path**: страницы → images → Sonnet vision (лучшее понимание layout)
- **Text path**: pdfplumber/python-docx → текст → Sonnet (для длинных документов)
- **Hybrid**: первые 20 страниц как images (для layout), остальное как текст
- Claude Sonnet analyzes with user's question/prompt
- **Capabilities**:
  - Document Q&A: "Какой срок оплаты?", "Кто подписант?"
  - Risk detection: "Какие риски в этом контракте?"
  - Cited conclusions: ответы со ссылками на страницу/секцию
  - Key terms extraction: даты, суммы, имена, условия
  - Regulatory compliance check: "Соответствует ли GDPR?"
- **Multi-doc mode**: до 200K tokens (~50 страниц) в одном запросе
- **Extended context** (ff_extended_context): до 1M tokens для больших контрактов/отчётов
- **Financial analysis via Code Execution**: если документ содержит числовые данные:
  - Sonnet извлекает данные → пишет pandas-скрипт → E2B → точные расчёты
  - Сценарный анализ, прогнозы, моделирование
**Output**: Analysis text with structured findings + page citations

#### 9. `merge_documents` (P2 — new)
**What**: Combine multiple PDFs into one
**How**:
- User sends multiple PDFs (or references stored documents)
- pypdf merge pages in specified order (pure Python, BSD, zero deps)
- Optional: add page numbers, table of contents
- Limit: 20 files, 100MB total
**Output**: Merged PDF file

#### 10. `fill_pdf_form` (P2 — new)
**What**: Fill interactive PDF forms (W-9, contracts, applications)
**How**:
- User uploads PDF with form fields
- pypdf reads form field names/types (`get_fields()`)
- Claude Sonnet maps field names to: user profile data, contact data, conversation context
- For missing values: asks user via buttons/text
- pypdf fills fields + optional flatten (`update_page_form_field_values(flatten=True)`)
- Checkbox/radio support via pypdf
**Output**: Filled PDF (editable or flattened)

#### 11. `generate_spreadsheet` (P3 — new)
**What**: Create Excel reports from data — через Code Execution для точных формул и чартов
**How**:
- Claude Sonnet designs spreadsheet structure based on user request
- **Code Execution pipeline** (Sonnet → E2B sandbox):
  - Sonnet пишет Python-скрипт с openpyxl/xlsxwriter
  - E2B sandbox выполняет скрипт, возвращает .xlsx файл
  - Формулы, conditional formatting, charts — всё программно
  - pandas для агрегации данных перед записью в Excel
- **Возможности**:
  - Formatted headers, data types, auto column widths
  - Real formulas (SUM, AVERAGE, VLOOKUP, IF), not hardcoded values
  - Conditional formatting (color scales, data bars, icon sets)
  - Charts: bar, pie, line, scatter, combo (до 16 типов через xlsxwriter)
  - Multiple sheets, pivot-style tables, sparklines
  - Frozen panes, print areas, page setup
- Data sources: transactions, bookings, contacts, life events (via data_tools)
**Output**: XLSX file (real file from E2B, not template)

#### 12. `compare_documents` (P3 — new)
**What**: Compare 2+ documents, find differences and contradictions
**How**:
- Extract text from all documents
- **Structural diff**: difflib generates unified diff (for versioned docs)
- **Semantic comparison**: Sonnet анализирует содержание, не только текст
  - "Что изменилось в новой версии контракта?"
  - "Есть ли противоречия между этими двумя документами?"
  - "Какие пункты в ТЗ не покрыты в договоре?"
- Cited conclusions: каждое различие со ссылкой на страницу/секцию
- **Multi-doc** (200K context): до 3-5 документов в одном запросе
- **Extended context** (ff_extended_context): десятки документов для cross-reference
**Output**: Formatted comparison with cited page references

#### 13. `summarize_document` (P3 — new)
**What**: Concise summary of any document with cited key facts
**How**:
- **PDF**: страницы → images → Sonnet vision (сохраняет layout context)
- **Other formats**: extract text → Sonnet
- Claude Sonnet generates structured summary:
  - Key points (bullet list) with page citations
  - Important dates/amounts/names
  - Action items (if any)
  - 1-paragraph executive summary
- Communication mode aware: receipt (1-line) vs coaching (detailed)
- **For financial documents**: Code Execution для точных итогов (pandas)
**Output**: Structured summary text with page references

#### 14. `generate_document` (P3 — new)
**What**: Generate a new document from scratch based on user description
**How**:
- User describes what they need: "create a NDA for my plumbing business", "make a price list for my salon"
- Claude Sonnet generates content in structured format (sections, clauses, tables)
- Rendering pipeline based on requested format:
  - **PDF**: HTML → WeasyPrint (professional layout with CSS)
  - **DOCX**: python-docx (editable Word document with proper headings/styles)
  - **XLSX**: openpyxl (structured spreadsheet with formatting)
- Business profile enrichment: auto-fills company name, address, phone from profile config
- Template awareness: if similar template exists in storage, uses as base
- **QR/barcode**: qrcode/python-barcode для документов с платёжными ссылками
- **Cross-agent chain**: "Отправь этот документ на email" → email agent
**Output**: Generated document in requested format
**Document types**: contracts, NDAs, proposals, price lists, reports, checklists, SOWs, letters

#### 15. `generate_presentation` (P3 — new)
**What**: Generate PPTX presentations from data or description
**How**:
- **Code Execution pipeline**: Sonnet пишет python-pptx код → E2B sandbox выполняет → .pptx файл
- **Data sources**: transactions (via data_tools), user description, document content
- **Capabilities**:
  - Title slides, content slides, table slides, chart slides
  - Business branding: colors, fonts from profile config
  - Data-driven: "Сделай презентацию расходов за квартал" → pandas агрегация → charts → slides
  - Content-driven: "Презентация для клиента о наших услугах" → Sonnet генерирует контент
- python-pptx запускается в E2B sandbox (не ставим в Docker)
**Output**: PPTX file

#### 16. `pdf_operations` (P2 — new)
**What**: PDF manipulation — split, rotate, encrypt, decrypt, watermark, extract pages
**How**:
- pypdf для всех операций (pure Python, zero deps)
- **Split**: "Раздели этот PDF на 3 части" → pypdf PdfWriter с выбранными страницами
- **Extract pages**: "Дай мне страницы 3-7" → reader.pages[2:7]
- **Rotate**: "Поверни страницу 5 на 90°" → page.rotate(90)
- **Encrypt**: "Защити паролем" → writer.encrypt("password")
- **Decrypt**: "Сними пароль" → reader.decrypt("password")
- **Watermark**: "Добавь водяной знак DRAFT" → merge_page with watermark
- **Add page numbers**: pypdf + WeasyPrint для генерации номеров
- **Reorder**: "Переставь страницы 5,3,1,2,4" → pypdf reorder
- Claude Sonnet парсит user intent → маппит на конкретную операцию
**Output**: Modified PDF file

---

## 6. Shared Utility: `src/tools/document_reader.py`

Universal text/image extraction used by analyze, summarize, compare, extract_table skills.

```python
# Core API (all async via asyncio.to_thread for blocking I/O)

async def extract_text(file_bytes: bytes, filename: str, mime_type: str) -> str:
    """Extract full text from any document. Routes by format."""

async def extract_pages_as_images(file_bytes: bytes, filename: str) -> list[bytes]:
    """Convert PDF/DOCX pages to images for Sonnet vision API."""

async def extract_tables(file_bytes: bytes, filename: str, mime_type: str) -> list[Table]:
    """Extract tables from PDF/DOCX/XLSX/image."""

async def get_page_count(file_bytes: bytes, filename: str) -> int:
    """Count pages in PDF/DOCX."""

async def extract_metadata(file_bytes: bytes, filename: str) -> dict:
    """Extract: title, author, creation date, page count, file size."""

async def compute_content_hash(file_bytes: bytes) -> str:
    """SHA-256 hash for duplicate detection."""
```

**Routing logic — dual path (text + vision)**:

| Format | Text extraction | Vision (for Sonnet) | Table extraction |
|--------|----------------|---------------------|-----------------|
| PDF (native text) | pdfplumber | pypdfium2 → page images | pdfplumber → camelot fallback |
| PDF (scanned/image) | Gemini 3 Flash OCR | pypdfium2 → page images | Gemini 3 Flash vision |
| DOCX | python-docx paragraphs | LibreOffice → PDF → images | python-docx tables |
| XLSX | openpyxl cell values | N/A (text only) | openpyxl sheets as tables |
| Images (JPG/PNG/WebP) | Gemini 3 Flash OCR | Direct pass-through | Gemini 3 Flash vision / img2table |
| TXT/MD/CSV | Direct read | N/A (text only) | CSV → list[list] |

**PDF type detection**: pdfplumber extracts text → if len(text) < 100 chars per page → classify as scanned → route to OCR.

**Vision vs Text decision**: Sonnet лучше анализирует документы через vision (сохраняет layout, таблицы, форматирование). Используем vision path для analyze_document и summarize_document. Text path — для search_documents и compare_documents (дешевле, быстрее).

### E2B File Transfer: `src/tools/e2b_file_utils.py`

Расширение E2B runner для возврата сгенерированных файлов из sandbox.

```python
async def execute_code_with_file(
    code: str,
    output_filename: str,
    language: str = "python",
    timeout: int = 60,
    install_deps: list[str] | None = None,
) -> tuple[bytes | None, str]:
    """Run code in E2B and return generated file bytes + stdout.

    E2B sandbox creates file → we download it → return bytes.
    Used by: generate_spreadsheet, generate_presentation.
    """
```

---

## 7. LangGraph Document Orchestrator (Phase 3)

For complex multi-step document workflows:

```
DocumentOrchestrator: planner → extractor → processor → generator → reviewer → END
```

### Use Cases

1. **"Возьми данные из этой таблицы и заполни шаблон договора"**
   - extractor: extract_table from uploaded file
   - processor: match table data to template placeholders
   - generator: fill_template with matched data
   - reviewer: Claude checks completeness

2. **"Сделай из этих 3 PDF один и добавь оглавление"**
   - extractor: parse each PDF structure
   - processor: build TOC from headings
   - generator: merge + insert TOC page
   - reviewer: verify page order

3. **"Проанализируй этот контракт и скажи что изменилось по сравнению с прошлой версией"**
   - extractor: extract text from both versions
   - processor: diff computation
   - generator: human-readable comparison
   - reviewer: highlight risks/concerns

4. **"Извлеки данные из этого PDF и создай Excel-отчёт с графиками"**
   - extractor: extract_table from PDF (pdfplumber)
   - processor: Sonnet анализирует и пишет pandas + openpyxl код
   - generator: E2B sandbox выполняет код → xlsx файл
   - reviewer: Sonnet проверяет результат

5. **"Сделай презентацию из этого отчёта"**
   - extractor: summarize_document → key points
   - processor: Sonnet пишет python-pptx код с контентом
   - generator: E2B sandbox → pptx файл
   - reviewer: Sonnet проверяет slides

6. **"Сгенерируй инвойс и отправь на email клиенту"**
   - generator: generate_invoice_pdf
   - approval: HITL interrupt — "Отправить инвойс на client@email.com?"
   - executor: → email agent (send_email with attachment)
   - END

### State

```python
class DocumentState(TypedDict):
    intent: str
    message_text: str
    user_id: str
    family_id: str
    language: str
    # Input
    input_files: list[dict]  # [{bytes, filename, mime_type}]
    template_file: dict | None
    # Processing
    extracted_text: str
    extracted_tables: list[dict]
    extracted_metadata: dict
    # Generation
    output_bytes: bytes | None
    output_filename: str | None
    output_format: str
    # Review
    quality_ok: bool
    revision_feedback: str
    revision_count: int
    # Result
    response_text: str
```

**Deferred to Phase 3** because simple skill-level handlers cover 80% of use cases. Orchestrator needed only for chained workflows.

---

## 8. Agent Configuration

### New agent in `src/agents/config.py`

```python
DOCUMENT_AGENT_PROMPT = """You are a document specialist — smart capable friend who handles all document work.

Your capabilities:
• Scan and OCR documents (invoices, contracts, forms — receipts go to receipt agent)
• Convert between formats (PDF, DOCX, XLSX, PPTX, images, e-books — 50+ format pairs)
• Extract tables and structured data from PDFs, images, spreadsheets
• Fill document and PDF form templates with user data
• Generate professional documents: invoices (with QR), spreadsheets, presentations, contracts
• Analyze documents: Q&A, risk detection, financial modeling — with page citations
• Compare multiple documents, find differences and contradictions
• PDF operations: split, merge, rotate, encrypt, watermark, extract pages
• Execute Python code in sandbox for precise calculations and file generation

You can use Code Execution (E2B sandbox) to:
• Run pandas/numpy for exact financial analysis — never guess numbers
• Generate Excel files with real formulas, charts, and formatting
• Create PowerPoint presentations with python-pptx
• Process data before generating documents

Rules:
• Always confirm before overwriting or deleting documents
• For templates, show placeholder list before filling
• For large files (>10MB), warn about processing time
• Output format: prefer PDF for sharing, XLSX for data, DOCX for editing, PPTX for presentations
• When citing document content, reference page numbers
• Lead with the result — no unnecessary preamble"""
```

```python
AgentConfig(
    name="document",
    system_prompt=DOCUMENT_AGENT_PROMPT,
    skills=[
        "scan_document",
        "convert_document",
        "generate_invoice_pdf",
        "list_documents",
        "search_documents",
        "extract_table",
        "fill_template",
        "analyze_document",
        "merge_documents",
        "fill_pdf_form",
        "pdf_operations",
        "generate_spreadsheet",
        "compare_documents",
        "summarize_document",
        "generate_document",
        "generate_presentation",
    ],
    default_model="claude-sonnet-4-6",
    context_config={
        "mem": "profile",   # User's business profile for templates/invoices
        "hist": 3,           # Recent context for follow-up questions
        "sql": False,        # Data access via data_tools
        "sum": False,
    },
    data_tools_enabled=True,   # Access to Document table + transactions for invoice data
    code_execution=True,       # E2B sandbox for spreadsheet/presentation generation
)
```

### Domain & routing

```python
# src/core/domains.py — new domain
class Domain(StrEnum):
    document = "document"  # NEW

# INTENT_DOMAIN_MAP additions
"scan_document": Domain.document,     # MOVE from finance
"convert_document": Domain.document,  # MOVE from writing
"generate_invoice_pdf": Domain.document,
"list_documents": Domain.document,
"search_documents": Domain.document,
"extract_table": Domain.document,
"fill_template": Domain.document,
"analyze_document": Domain.document,
"merge_documents": Domain.document,
"fill_pdf_form": Domain.document,
"generate_spreadsheet": Domain.document,
"compare_documents": Domain.document,
"summarize_document": Domain.document,
"generate_document": Domain.document,
"generate_presentation": Domain.document,
"pdf_operations": Domain.document,
```

### Skill catalog (YAML)

```yaml
document:
  description: "Work with documents: scan, convert, extract tables, fill templates, generate invoices/spreadsheets, analyze, merge, compare, summarize"
  triggers:
    - document
    - pdf
    - word
    - excel
    - таблиц
    - шаблон
    - template
    - invoice
    - инвойс
    - convert
    - конверт
    - merge
    - объедин
    - split
    - раздели
    - extract
    - извлечь
    - analyze
    - анализ
    - compare
    - сравни
    - summary
    - summarize
    - резюме
    - spreadsheet
    - docx
    - xlsx
    - pptx
    - презентац
    - presentation
    - скан
    - документ
    - encrypt
    - decrypt
    - пароль
    - password
    - watermark
    - водяной знак
    - rotate
    - повернуть
    - form
    - форма
    - w-9
    - заполни
  agent: document
  skills:
    - scan_document
    - convert_document
    - generate_invoice_pdf
    - list_documents
    - search_documents
    - extract_table
    - fill_template
    - analyze_document
    - merge_documents
    - generate_spreadsheet
    - compare_documents
    - summarize_document
    - fill_pdf_form
    - generate_document
    - generate_presentation
    - pdf_operations
```

---

## 9. Database Changes

### Add `documents` to data_tools whitelist

In `src/tools/data_tools.py`, add `"documents"` to `ALLOWED_TABLES` so the document agent can query stored documents via LLM function calling.

### Extend Document model

```python
# New fields for src/core/models/document.py
class Document(Base, TimestampMixin):
    # ... existing fields ...

    # NEW fields
    original_filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    source_channel: Mapped[str | None] = mapped_column(String(20))  # telegram, slack, whatsapp
    content_hash: Mapped[str | None] = mapped_column(String(64))   # SHA-256 for dedup
    tags: Mapped[list | None] = mapped_column(JSONB)                # User-defined tags
    extracted_text: Mapped[str | None] = mapped_column(Text)        # Full text for search
```

### New Alembic migration

One migration adding the new columns + GIN index on `extracted_text` for full-text search + index on `content_hash` for dedup.

### Extend DocumentType enum

```python
class DocumentType(StrEnum):
    receipt = "receipt"
    invoice = "invoice"
    rate_confirmation = "rate_confirmation"
    fuel_receipt = "fuel_receipt"
    contract = "contract"       # NEW
    template = "template"       # NEW
    spreadsheet = "spreadsheet" # NEW
    report = "report"           # NEW
    other = "other"
```

---

## 10. New IntentData Fields

```python
# src/core/schemas/intent.py — additions
class IntentData(BaseModel):
    # ... existing fields ...

    # Document agent fields
    target_format: str | None = None         # already exists (convert_document)
    document_type_filter: str | None = None  # for list_documents: "invoice", "receipt"
    document_search_query: str | None = None # for search_documents
    template_name: str | None = None         # for fill_template
    output_format: str | None = None         # "pdf", "docx", "xlsx"
    merge_order: str | None = None           # for merge_documents: "as sent", "by date"
    analysis_question: str | None = None     # for analyze_document: specific question
    document_description: str | None = None  # for generate_document: what to create
    document_recipient: str | None = None    # for generate_document/invoice: who receives it
    pdf_operation: str | None = None         # for pdf_operations: "split", "rotate", "encrypt", etc.
    pdf_pages: str | None = None             # for pdf_operations: "3-7", "1,3,5", "all"
    pdf_password: str | None = None          # for pdf_operations: encrypt/decrypt password
    presentation_topic: str | None = None    # for generate_presentation: topic/content
```

---

## 11. Context Map Entries

```python
# src/core/memory/context.py — QUERY_CONTEXT_MAP additions
"scan_document": {"mem": "mappings", "hist": 1, "sql": False, "sum": False},  # existing, keep
"convert_document": {"mem": False, "hist": 0, "sql": False, "sum": False},    # existing, keep
"generate_invoice_pdf": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"list_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
"search_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
"extract_table": {"mem": False, "hist": 1, "sql": False, "sum": False},
"fill_template": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"analyze_document": {"mem": False, "hist": 2, "sql": False, "sum": False},
"merge_documents": {"mem": False, "hist": 1, "sql": False, "sum": False},
"generate_spreadsheet": {"mem": "profile", "hist": 2, "sql": False, "sum": False},
"fill_pdf_form": {"mem": "profile", "hist": 2, "sql": False, "sum": False},
"compare_documents": {"mem": False, "hist": 2, "sql": False, "sum": False},
"summarize_document": {"mem": False, "hist": 1, "sql": False, "sum": False},
"generate_document": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"generate_presentation": {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"pdf_operations": {"mem": False, "hist": 1, "sql": False, "sum": False},
```

---

## 12. Implementation Phases

### Phase 0: Foundation (prereqs + bug fixes)
**Effort**: 1 session

1. Fix auto-save confidence bug in `scan_receipt` (line ~92)
2. Standardize pending storage to Redis across all document skills
3. Add `documents` to data_tools ALLOWED_TABLES
4. Create Alembic migration for Document model extensions
5. Add new dependencies to `pyproject.toml`: `pdfplumber`, `pypdf`, `python-docx`, `openpyxl`, `docxtpl`, `qrcode`, `python-barcode`
6. Create `src/tools/e2b_file_utils.py` — extend E2B runner for file download from sandbox
7. Update Dockerfile if any system deps needed (ghostscript for camelot in Phase 3)

### Phase 1: Core Agent + Move Skills (P0+P1)
**Effort**: 2-3 sessions

1. Create `document` agent config in `src/agents/config.py` (with `code_execution=True`)
2. Add `Domain.document` to `src/core/domains.py`
3. Add domain to `config/skill_catalog.yaml` with full trigger list
4. **Move** `scan_document` skill: update agent assignment, enhance:
   - Instructor + Pydantic structured extraction
   - Auto-classification (invoice, contract, form, report)
   - Multi-page PDF support (pages → images → Sonnet vision)
   - Full-text indexing → extracted_text column
5. **Move** `convert_document` skill: update agent assignment, add format synonyms
6. **New** `list_documents` skill: Document table query via data_tools
7. **New** `search_documents` skill: text search on extracted_text (PostgreSQL GIN)
8. **New** `extract_table` skill: pdfplumber + Gemini vision + optional Code Execution analysis
9. **New** `generate_invoice_pdf` skill: HTML → PDF with WeasyPrint + QR code
10. Create `src/tools/document_reader.py` — dual path (text + vision) extraction utility
11. Add intents to `src/core/intent.py`
12. Add IntentData fields to `src/core/schemas/intent.py`
13. Add QUERY_CONTEXT_MAP entries
14. Register all skills in `src/skills/__init__.py`
15. Update receipt agent: remove scan_document from skills list
16. Update writing agent: remove convert_document from skills list
17. Update tests: registry count, new test files

### Phase 2: Advanced Skills (P2)
**Effort**: 2-3 sessions

1. **New** `fill_template` skill: docxtpl + openpyxl template filling + template library
2. **New** `fill_pdf_form` skill: pypdf form reading/filling/flattening
3. **New** `analyze_document` skill:
   - PDF vision path (pages → images → Sonnet) for layout understanding
   - Cited conclusions with page references
   - Financial analysis via Code Execution (pandas in E2B)
   - Document Q&A, risk detection
4. **New** `merge_documents` skill: pypdf merge
5. **New** `pdf_operations` skill: split/rotate/encrypt/decrypt/watermark/extract pages (pypdf)
6. Expand `document_reader.py`:
   - PDF → pdfplumber (text) + pypdfium2 (images for vision)
   - DOCX → python-docx (paragraphs + tables)
   - XLSX → openpyxl (sheets + data)
   - Images → Gemini Flash OCR / direct pass-through
   - PDF type detection (native text vs scanned)
7. Add Supabase document upload (fix storage_path)
8. Add duplicate detection (SHA-256 content_hash)
9. Tests for all new skills

### Phase 3: Generation + Orchestrator + Code Execution (P3)
**Effort**: 3-4 sessions

1. **New** `generate_spreadsheet` skill: Sonnet → E2B (openpyxl/xlsxwriter + pandas)
   - Real formulas, charts, conditional formatting
   - Data from transactions via data_tools → pandas aggregation → Excel
2. **New** `compare_documents` skill: structural diff + Sonnet semantic comparison
   - Multi-doc support (200K context, 3-5 docs)
   - Cited differences with page references
3. **New** `summarize_document` skill: vision path + cited key facts
4. **New** `generate_document` skill: contracts, NDAs, proposals, price lists
   - PDF (WeasyPrint), DOCX (python-docx), cross-agent chain to email
5. **New** `generate_presentation` skill: Sonnet → E2B (python-pptx)
   - Data-driven + content-driven presentations
6. Create `src/orchestrators/document/` LangGraph orchestrator
   - 6 use cases (see Section 7)
   - Cross-agent chains: document → email, document → chat (expense)
7. Register orchestrator in domain_router
8. Gate behind feature flag: `ff_langgraph_document`
9. Add camelot-py, img2table to deps (xlsxwriter runs in E2B, not Docker)
10. Tests for orchestrator + new skills

### Phase 4: Polish + Production
**Effort**: 1-2 sessions

1. Batch conversion support (multiple files in one message)
2. Progress indication for long operations (E2B sandbox status)
3. Document storage cleanup cron task (old documents, orphaned uploads)
4. Langfuse observability for all new skills (`@observe` decorators)
5. Multi-language support for prompts and responses
6. Performance testing (large files, concurrent E2B sandboxes)
7. Template library UX: save/list/delete templates, suggested templates by business type
8. Extended context (1M tokens) gated by `ff_extended_context` for heavy multi-doc analysis
9. Recurring document generation cron: "Каждый месяц генерируй инвойс для клиента X"
10. Document versioning: store versions of same document, auto-compare on update
11. Update CLAUDE.md with document agent documentation

---

## 13. Files to Create

```
src/skills/list_documents/__init__.py
src/skills/list_documents/handler.py
src/skills/search_documents/__init__.py
src/skills/search_documents/handler.py
src/skills/extract_table/__init__.py
src/skills/extract_table/handler.py
src/skills/generate_invoice_pdf/__init__.py
src/skills/generate_invoice_pdf/handler.py
src/skills/fill_template/__init__.py
src/skills/fill_template/handler.py
src/skills/analyze_document/__init__.py
src/skills/analyze_document/handler.py
src/skills/merge_documents/__init__.py
src/skills/merge_documents/handler.py
src/skills/generate_spreadsheet/__init__.py
src/skills/generate_spreadsheet/handler.py
src/skills/compare_documents/__init__.py
src/skills/compare_documents/handler.py
src/skills/summarize_document/__init__.py
src/skills/summarize_document/handler.py
src/skills/fill_pdf_form/__init__.py
src/skills/fill_pdf_form/handler.py
src/skills/generate_document/__init__.py
src/skills/generate_document/handler.py
src/skills/generate_presentation/__init__.py
src/skills/generate_presentation/handler.py
src/skills/pdf_operations/__init__.py
src/skills/pdf_operations/handler.py
src/tools/document_reader.py              # Reusable text/image extraction
src/tools/e2b_file_utils.py               # E2B file transfer (generate files in sandbox)
src/orchestrators/document/__init__.py
src/orchestrators/document/graph.py
src/orchestrators/document/state.py
src/orchestrators/document/nodes.py
tests/test_skills/test_list_documents.py
tests/test_skills/test_search_documents.py
tests/test_skills/test_extract_table.py
tests/test_skills/test_generate_invoice_pdf.py
tests/test_skills/test_fill_template.py
tests/test_skills/test_analyze_document.py
tests/test_skills/test_merge_documents.py
tests/test_skills/test_generate_spreadsheet.py
tests/test_skills/test_compare_documents.py
tests/test_skills/test_summarize_document.py
tests/test_skills/test_fill_pdf_form.py
tests/test_skills/test_generate_document.py
tests/test_skills/test_generate_presentation.py
tests/test_skills/test_pdf_operations.py
alembic/versions/xxxx_add_document_fields.py
```

## 14. Files to Modify

```
src/agents/config.py              — Add document agent config
src/skills/__init__.py             — Register 14 new skills, update 2 moved skills
src/core/domains.py                — Add Domain.document + INTENT_DOMAIN_MAP entries (16 intents)
src/core/intent.py                 — Add 14 new intents to INTENT_DETECTION_PROMPT
src/core/sandbox/e2b_runner.py     — Add file download support for generated files
src/core/schemas/intent.py         — Add new IntentData fields
src/core/memory/context.py         — Add QUERY_CONTEXT_MAP entries
src/core/domain_router.py          — Register document orchestrator (Phase 3)
src/core/models/document.py        — Extend Document model
src/tools/data_tools.py            — Add "documents" to ALLOWED_TABLES
config/skill_catalog.yaml          — Add document domain
pyproject.toml                     — Add new dependencies
Dockerfile                         — Add ghostscript (if camelot needed)
tests/test_skills/test_registry.py — Update count + intents list
```

---

## 15. Dependency Impact

### New Python packages (in Docker)

| Package | Version | Size | License | Transitive deps |
|---------|---------|------|---------|-----------------|
| pdfplumber | >=0.11.0 | ~2MB | MIT | pdfminer.six (already a WeasyPrint dep chain) |
| pypdf | >=4.0.0 | ~1MB | BSD | Zero external deps. Pure Python. |
| python-docx | >=1.1.0 | ~1MB | MIT | lxml (already installed) |
| openpyxl | >=3.1.0 | ~4MB | MIT | et_xmlfile (tiny) |
| docxtpl | >=0.18.0 | ~50KB | LGPL | python-docx, jinja2 (both already installed) |
| qrcode | >=7.4 | ~100KB | BSD | Pillow (already installed) |
| python-barcode | >=0.15.0 | ~50KB | MIT | Pillow (already installed) |

### Libraries in E2B sandbox ONLY (NOT in Docker — installed via pip at runtime)

| Package | Why in sandbox | Use case |
|---------|---------------|----------|
| pandas + numpy | ~150MB, overkill for main app | Financial analysis, data aggregation |
| xlsxwriter | ~2MB | Excel chart generation (16 chart types) |
| python-pptx | ~3MB | Presentation generation |
| matplotlib / plotly | ~50MB | Charts and graphs |
| reportlab | ~15MB | Advanced PDF generation |

**Savings**: ~220MB not added to Docker image by using E2B sandbox.

### System packages (Dockerfile)

- `ghostscript` — only if camelot-py is added in Phase 3 (~15MB)

### Impact on Docker image

~9MB additional Python packages (pdfplumber + pypdf + python-docx + openpyxl + docxtpl + qrcode + python-barcode). Heavy libraries (pandas, matplotlib, python-pptx) run in E2B sandbox.

---

## 16. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Moving scan_document breaks receipt flow | High | Keep scan_receipt in receipt agent; only move scan_document. Test callback handlers. |
| Moving convert_document breaks writing flow | Medium | Update routing in domains.py + skill_catalog.yaml. Verify no hardcoded agent references. |
| LibreOffice contention with more conversions | Medium | Already serialized via mutex. Monitor queue depth. Phase 4: consider connection pooling. |
| Large file processing OOM | Medium | Add file size limits per skill (20MB). Use streaming where possible. |
| Intent overlap (document vs receipt vs writing) | High | Clear intent descriptions: scan_receipt = "photo of receipt/check", scan_document = "photo/file of non-receipt document". Test with ambiguous inputs. |
| Document table grows large | Low | Add cleanup cron (Phase 4). Storage path + extracted_text indexed. |
| E2B sandbox latency (cold start) | Medium | E2B cold start ~3-5s. Mitigate: pre-warm sandbox pool, show "Generating..." progress. |
| E2B sandbox cost | Low | ~$0.01 per execution (30s avg). Budget: ~$50/month at 5000 executions. |
| Generated code fails in E2B | Medium | Sonnet retry: if execution fails, read stderr, fix code, retry once. Max 2 attempts. |
| Cross-agent chain breaks | Medium | Each chain step is idempotent. On failure: return partial result + error message. |
| Extended context (1M) cost | Low | Gated by ff_extended_context. Only for explicit multi-doc operations. Per-request cost ~2x. |

---

## 17. Success Metrics

1. **Single entry point**: user says "работа с документами" → routes to document agent (not 3 different agents)
2. **14 new intents** detected correctly with >90% accuracy
3. **Table extraction** works for: native PDF tables, image tables, DOCX tables, XLSX sheets
4. **Template filling** supports DOCX, XLSX, and PDF forms with arbitrary placeholders
5. **Document search** returns relevant results within 2 seconds
6. **Document generation** produces professional PDFs, DOCXs, XLSXs, and PPTXs
7. **Code Execution**: spreadsheet and presentation generation via E2B produces real files with formulas/charts
8. **Financial analysis**: exact numbers (via pandas), not LLM guesses — verified on 10 test cases
9. **Cited conclusions**: analyze_document returns page references for every claim
10. **All existing tests pass** after skill migration
11. **New skills have 100% test coverage** (mocked external I/O)
12. **No regressions**: scan_receipt still works in receipt agent, writing agent still works without convert_document
13. **Docker image size**: <10MB increase (heavy libs in E2B only)

---

## 18. Cross-Agent Chains

Document agent → other agents через LangGraph orchestrator (Phase 3) или SkillResult.background_tasks.

| Trigger | Chain | How |
|---------|-------|-----|
| "Сгенерируй инвойс и отправь клиенту" | document → email | generate_invoice_pdf → approval interrupt → send_email with attachment |
| Scan document → found amount | document → chat | scan_document → "Добавить как расход $142?" → add_expense |
| "Сделай Excel-отчёт и поставь напоминание на 1-е число" | document → tasks | generate_spreadsheet → set_reminder (recurring monthly) |
| "Заполни контракт и создай встречу на подписание" | document → calendar | fill_template → create_event |
| "Каждый месяц генерируй инвойс для клиента X" | document → cron | Taskiq cron → generate_invoice_pdf → send_email |

**Implementation**: через `background_tasks` в SkillResult (Phase 2) или через LangGraph orchestrator nodes (Phase 3).

---

## 19. Maria & David Scenarios

### Maria (Brooklyn mom, personal finance)

**Scenario 1**: Maria photographs a stack of utility bills.
> Maria: [sends photo of ConEd bill]
> Bot: 📄 Invoice detected: ConEdison, $142.37, due Mar 15.
> [✅ Save | 📋 Extract table | ❌ Skip]

**Scenario 2**: Maria asks for a year-end expense report in Excel.
> Maria: "Make me a spreadsheet of all my expenses this year"
> Bot: [generates expenses_2026.xlsx with monthly tabs, charts, totals]

**Scenario 3**: Maria searches for an old receipt.
> Maria: "Find the receipt from Whole Foods last month"
> Bot: Found 2 documents:
> 📄 Whole Foods — $87.42 — Feb 3
> 📄 Whole Foods — $52.18 — Feb 17
> [View details]

### David (Queens plumber, business)

**Scenario 1**: David fills a contract template for a new client.
> David: [uploads contract_template.docx] "Fill this for Mike Chen, bathroom renovation, $4,500"
> Bot: Template has 8 fields. Filled 6 from your data:
> • {{client_name}} → Mike Chen
> • {{service}} → Bathroom renovation
> • {{amount}} → $4,500
> • {{date}} → Feb 28, 2026
> • {{contractor_name}} → David's Plumbing LLC
> • {{contractor_phone}} → (718) 555-0123
> Missing: {{address}}, {{payment_terms}}
> [Fill address] [Set "Net 30"]

**Scenario 2**: David needs to combine estimates into one PDF.
> David: [sends 3 PDFs] "Merge these into one"
> Bot: [merged_estimates.pdf — 7 pages, 3 documents]

**Scenario 3**: David extracts pricing from a supplier PDF.
> David: [sends supplier_catalog.pdf] "Extract the pricing table"
> Bot: Found 2 tables on pages 3-4:
> | Product | Unit Price | Min Order |
> |---------|-----------|-----------|
> | PVC Pipe 1" | $4.25/ft | 10ft |
> | Copper 3/4" | $8.90/ft | 5ft |
> [Download as CSV] [Download as Excel]

**Scenario 4**: David fills a W-9 PDF form.
> David: [sends w9_blank.pdf] "Fill this out for my company"
> Bot: Found 12 form fields. Filled 8 from your profile:
> • Name → David Rodriguez
> • Business name → David's Plumbing LLC
> • Address → 45-12 Queens Blvd, Queens, NY
> • TIN → ••••••7890
> Missing: Signature date, Federal tax classification
> [Set as Sole proprietor] [Set as LLC] [Set as S Corp]

**Scenario 5**: David generates a proposal from scratch.
> David: "Create a proposal for kitchen renovation for Sarah Johnson, $12,000"
> Bot: [generates proposal_sarah_johnson.pdf]
> 📄 Proposal — Kitchen Renovation
> Client: Sarah Johnson
> Scope: Full kitchen renovation (demolition, plumbing, fixtures, tiling)
> Total: $12,000 (50% deposit, 50% on completion)
> [Download PDF] [Download DOCX] [Edit details]

**Scenario 6**: Maria analyzes her lease agreement.
> Maria: [sends lease_renewal.pdf] "What changed from last year?"
> Bot: Comparing with your stored lease from Jan 2025:
> • Rent increased $150/month ($2,400 → $2,550) [p.2]
> • Pet deposit added: $500 [p.4]
> • Lease term changed: 1 year → 2 years [p.1]
> • New clause: Section 14b restricts subletting [p.7]
> ⚠️ Worth reviewing: the subletting clause is new.

### Code Execution Scenarios

**Scenario 7**: Maria asks for expense analytics in Excel (Code Execution).
> Maria: "Make a spreadsheet of my expenses with charts by category"
> Bot: [generates expenses_2026_q1.xlsx]
> 📊 Created spreadsheet with 3 sheets:
> • Summary — totals by category with pie chart
> • Monthly — month-by-month breakdown with line chart
> • Raw Data — all 142 transactions with filters
> Formulas auto-calculate totals. Charts update with new data.

**Scenario 8**: David creates a client presentation (Code Execution).
> David: "Make a presentation of my completed projects for the client meeting"
> Bot: [generates davids_plumbing_portfolio.pptx]
> 📊 Created 8-slide presentation:
> • Title: David's Plumbing LLC
> • About Us (company info from profile)
> • 5 Recent Projects (from booking history)
> • Pricing Overview (from services)
> • Contact slide with QR code
> [Download PPTX] [Convert to PDF]

**Scenario 9**: David needs financial analysis from a supplier spreadsheet.
> David: [sends supplier_prices.xlsx] "Compare with last quarter and find anomalies"
> Bot: Analyzed 340 rows across 12 categories:
> • Average price increase: 4.2% (vs 2.8% industry avg)
> • 🔴 Anomaly: Copper pipes up 23% ($8.90 → $10.95) — verify with supplier
> • 🟡 PVC fittings bulk discount removed (was -15% at 100+ units)
> • 🟢 Adhesives stable (±1%)
> [Download comparison Excel] [Show full analysis]

**Scenario 10**: Maria splits a PDF and protects it.
> Maria: "Extract pages 1-3 from this lease and add a password"
> Bot: [generates lease_pages_1-3_protected.pdf]
> Extracted 3 pages, encrypted with password.
> Password: ••••••• (sent separately for security)
> [Download]
