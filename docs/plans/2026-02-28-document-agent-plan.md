# Document Agent — Comprehensive Implementation Plan

**Date**: 2026-02-28
**Status**: Draft for approval
**Agent name**: `document`
**Model**: `claude-sonnet-4-6`

---

## 1. Executive Summary

Создаём 13-й агент `document`, объединяющий и расширяющий все возможности работы с документами. Агент станет единой точкой входа для: OCR/сканирования, конвертации форматов, генерации документов из шаблонов, работы с таблицами, хранилища документов, и AI-анализа содержимого.

**Текущее состояние**: документы размазаны по 3 агентам (receipt, writing, finance_specialist) без единой точки входа, без хранилища, без шаблонов, без работы с таблицами.

**Целевое состояние**: выделенный агент с 12 скиллами, LangGraph-оркестратор для сложных пайплайнов, data_tools для доступа к Document таблице, 6 новых Python-библиотек.

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

## 3. What Claude Sonnet 4.6 Can Do Natively

| Capability | How it helps the document agent |
|-----------|-------------------------------|
| **Vision (images + PDF pages)** | Directly analyze document photos, screenshots, PDF pages |
| **Structured output** (via Instructor) | Extract typed data from documents into Pydantic models |
| **Long context (200K)** | Analyze large multi-page documents in full |
| **Tool use / function calling** | Multi-step document workflows (read → analyze → generate) |
| **Code generation** | Generate HTML/CSS for templates, Excel formulas |
| **Multi-language** | Process documents in any language |
| **Reasoning** | Understand document structure, compare versions, summarize |

### Key: Sonnet 4.6 + Gemini 3 Flash combo

- **Gemini 3 Flash**: fast OCR, image classification, table detection (cheaper, faster)
- **Sonnet 4.6**: document understanding, template generation, complex analysis, multi-step reasoning

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

### Should-have (Phase 3)

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

### Document Agent — 14 Skills

| # | Skill | Intent | Priority | Source |
|---|-------|--------|----------|--------|
| 1 | scan_document | `scan_document` | P0 | **Move** from receipt agent |
| 2 | convert_document | `convert_document` | P0 | **Move** from writing agent |
| 3 | generate_invoice_pdf | `generate_invoice_pdf` | P1 | **New** (extends existing generate_invoice) |
| 4 | list_documents | `list_documents` | P1 | **New** |
| 5 | search_documents | `search_documents` | P1 | **New** |
| 6 | extract_table | `extract_table` | P1 | **New** |
| 7 | fill_template | `fill_template` | P2 | **New** |
| 8 | analyze_document | `analyze_document` | P2 | **New** |
| 9 | merge_documents | `merge_documents` | P2 | **New** |
| 10 | fill_pdf_form | `fill_pdf_form` | P2 | **New** |
| 11 | generate_spreadsheet | `generate_spreadsheet` | P3 | **New** |
| 12 | compare_documents | `compare_documents` | P3 | **New** |
| 13 | summarize_document | `summarize_document` | P3 | **New** |
| 14 | generate_document | `generate_document` | P3 | **New** |

### Skill Details

#### 1. `scan_document` (P0 — move + enhance)
**Move from**: receipt agent → document agent
**Enhancements**:
- Per-field confidence scoring (not hardcoded 0.9)
- Document quality checker before OCR (blur detection via Pillow)
- Multi-language prompts based on `context.language`
- Actual Supabase upload (fix storage_path = "pending")
- Duplicate detection (hash of content)
- Support for multi-page documents (iterate pages)

**Note**: `scan_receipt` stays in receipt agent (financial-specific, creates Transaction).

#### 2. `convert_document` (P0 — move + enhance)
**Move from**: writing agent → document agent
**Enhancements**:
- Format synonym resolution: "word" → docx, "excel" → xlsx, "powerpoint" → pptx
- Multi-page PDF → images (ZIP or numbered files)
- Batch conversion (multiple files in one message)
- Progress indication for long conversions
- Quality/compression presets

#### 3. `generate_invoice_pdf` (P1 — new)
**What**: Generate professional PDF invoices from data
**How**:
- Claude Sonnet generates HTML invoice from user's business profile + contact + line items
- WeasyPrint renders to PDF
- Support for business logo/letterhead from profile config
- Multiple templates: simple, professional, detailed
- Auto-populate from recent transactions (reuse generate_invoice data fetch)
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
**What**: Extract tables from PDF/images/documents
**How**:
- **From native PDF**: pdfplumber (primary) → camelot-py (fallback for complex tables)
- **From images**: Gemini 3 Flash vision → structured table JSON
- **From DOCX/XLSX**: python-docx tables / openpyxl sheets (direct parsing)
- **Output formats**: structured JSON, CSV, or render as formatted text
- Claude Sonnet post-processes: cleans headers, normalizes data types, fixes OCR errors
**Output**: Table as formatted text + optional CSV/XLSX file attachment

#### 7. `fill_template` (P2 — new)
**What**: Fill DOCX/Excel templates with user data
**How**:
- User uploads template (DOCX with `{{placeholders}}` or Excel with `{placeholders}`)
- Claude Sonnet extracts placeholder list from template
- Matches placeholders to: conversation context, DB data (contacts, transactions), user-provided values
- For missing values: asks user via buttons/text
- **DOCX**: docxtpl renders with Jinja2
- **XLSX**: openpyxl finds and replaces placeholders
- **PDF output**: optional post-conversion via LibreOffice
**Output**: Filled document (DOCX/XLSX/PDF)

#### 8. `analyze_document` (P2 — new)
**What**: Deep AI analysis of any document
**How**:
- Extract full text (pdfplumber for PDF, python-docx for DOCX, OCR for images)
- Claude Sonnet analyzes with user's question/prompt
- Capabilities: summarize, find key terms, extract dates/amounts, answer questions about content, identify risks/issues
- Support for multi-page analysis (chunked if > 100K tokens)
**Output**: Analysis text with structured findings

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
**What**: Create Excel reports from data
**How**:
- Claude Sonnet designs spreadsheet structure based on user request
- openpyxl/xlsxwriter creates .xlsx with:
  - Formatted headers, data types, column widths
  - Basic formulas (SUM, AVERAGE, COUNT)
  - Conditional formatting (color scales for amounts)
  - Optional charts (bar, pie, line)
- Data sources: transactions, bookings, contacts, life events (via data_tools)
**Output**: XLSX file

#### 11. `compare_documents` (P3 — new)
**What**: Compare two documents and show differences
**How**:
- Extract text from both documents
- difflib generates unified diff
- Claude Sonnet provides human-readable summary of changes
- Highlight: added/removed/modified sections
**Output**: Formatted comparison with diff highlights

#### 13. `summarize_document` (P3 — new)
**What**: Concise summary of any document
**How**:
- Extract full text (PDF/DOCX/image)
- Claude Sonnet generates structured summary:
  - Key points (bullet list)
  - Important dates/amounts/names
  - Action items (if any)
  - 1-paragraph executive summary
- Communication mode aware: receipt (1-line) vs coaching (detailed)
**Output**: Structured summary text

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
**Output**: Generated document in requested format
**Document types**: contracts, NDAs, proposals, price lists, reports, checklists, SOWs, letters

---

## 6. Shared Utility: `src/tools/document_reader.py`

Universal text/table extraction used by analyze, summarize, compare, extract_table skills.

```python
# Core API (all async via asyncio.to_thread)

async def extract_text(file_bytes: bytes, filename: str, mime_type: str) -> str:
    """Extract full text from any document. Routes by format."""

async def extract_tables(file_bytes: bytes, filename: str, mime_type: str) -> list[Table]:
    """Extract tables from PDF/DOCX/XLSX/image."""

async def get_page_count(file_bytes: bytes, filename: str) -> int:
    """Count pages in PDF/DOCX."""

async def extract_metadata(file_bytes: bytes, filename: str) -> dict:
    """Extract: title, author, creation date, page count, file size."""
```

**Routing logic**:

| Format | Text extraction | Table extraction |
|--------|----------------|-----------------|
| PDF (native text) | pdfplumber | pdfplumber → camelot fallback |
| PDF (scanned/image) | Gemini 3 Flash OCR | Gemini 3 Flash vision |
| DOCX | python-docx paragraphs | python-docx tables |
| XLSX | openpyxl cell values | openpyxl sheets as tables |
| Images (JPG/PNG) | Gemini 3 Flash OCR | Gemini 3 Flash vision / img2table |
| TXT/MD/CSV | Direct read | CSV → list[list] |

**PDF type detection**: pdfplumber extracts text → if empty/minimal → classify as scanned → route to OCR.

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
DOCUMENT_AGENT_PROMPT = """You are a document specialist.

Your capabilities:
• Scan and OCR documents (receipts handled by receipt agent — you handle invoices, contracts, forms, generic docs)
• Convert between formats (PDF, DOCX, XLSX, images, e-books)
• Extract tables and structured data
• Fill document templates with data
• Generate professional invoices, spreadsheets, reports
• Analyze, summarize, and compare documents
• Merge multiple PDFs

Rules:
• Always confirm before overwriting or deleting documents
• For templates, show placeholder list before filling
• For large files (>10MB), warn about processing time
• Output format: prefer PDF for sharing, XLSX for data, DOCX for editing
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
        "generate_spreadsheet",
        "compare_documents",
        "summarize_document",
        "generate_document",
    ],
    default_model="claude-sonnet-4-6",
    context_config={
        "mem": "profile",   # User's business profile for templates/invoices
        "hist": 3,           # Recent context for follow-up questions
        "sql": False,        # Data access via data_tools
        "sum": False,
    },
    data_tools_enabled=True,  # Access to Document table + transactions for invoice data
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
    - скан
    - документ
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
```

---

## 12. Implementation Phases

### Phase 0: Foundation (prereqs + bug fixes)
**Effort**: 1 session

1. Fix auto-save confidence bug in `scan_receipt` (line ~92)
2. Standardize pending storage to Redis across all document skills
3. Add `documents` to data_tools ALLOWED_TABLES
4. Create Alembic migration for Document model extensions
5. Add new dependencies to `pyproject.toml`: `pdfplumber`, `pypdf`, `python-docx`, `openpyxl`, `docxtpl`
6. Update Dockerfile if any system deps needed (ghostscript for camelot)

### Phase 1: Core Agent + Move Skills (P0+P1)
**Effort**: 2-3 sessions

1. Create `document` agent config in `src/agents/config.py`
2. Add `Domain.document` to `src/core/domains.py`
3. Add domain to `config/skill_catalog.yaml`
4. **Move** `scan_document` skill: update agent assignment, enhance with per-field confidence
5. **Move** `convert_document` skill: update agent assignment, add format synonyms
6. **New** `list_documents` skill: simple Document table query
7. **New** `search_documents` skill: text search on ocr_parsed/extracted_text
8. **New** `extract_table` skill: pdfplumber + Gemini vision
9. **New** `generate_invoice_pdf` skill: HTML → PDF invoice with WeasyPrint
10. Add intents to `src/core/intent.py`
11. Add IntentData fields to `src/core/schemas/intent.py`
12. Add QUERY_CONTEXT_MAP entries
13. Register all skills in `src/skills/__init__.py`
14. Update receipt agent: remove scan_document from skills list
15. Update writing agent: remove convert_document from skills list
16. Update tests: registry count, new test files

### Phase 2: Advanced Skills (P2)
**Effort**: 2 sessions

1. **New** `fill_template` skill: docxtpl + openpyxl template filling
2. **New** `fill_pdf_form` skill: pypdf form reading/filling/flattening
3. **New** `analyze_document` skill: text extraction + Claude analysis
4. **New** `merge_documents` skill: pypdf merge
4. Create reusable document text extraction utility: `src/tools/document_reader.py`
   - PDF → pdfplumber (text + tables)
   - DOCX → python-docx (paragraphs + tables)
   - XLSX → openpyxl (sheets + data)
   - Images → Gemini vision OCR
5. Add Supabase document upload (fix storage_path)
6. Add duplicate detection (content_hash)
7. Tests for all new skills

### Phase 3: Generation + Orchestrator (P3)
**Effort**: 2-3 sessions

1. **New** `generate_spreadsheet` skill: openpyxl/xlsxwriter generation
2. **New** `compare_documents` skill: difflib + Claude summary
3. **New** `summarize_document` skill: extraction + Claude summary
4. **New** `generate_document` skill: Claude + WeasyPrint/python-docx/openpyxl
5. Create `src/orchestrators/document/` LangGraph orchestrator
5. Register orchestrator in domain_router
6. Gate behind feature flag: `ff_langgraph_document`
7. Add camelot-py, xlsxwriter, img2table to deps
8. Tests for orchestrator + new skills

### Phase 4: Polish + Production
**Effort**: 1 session

1. Batch conversion support (multiple files)
2. Progress indication for long operations
3. Document storage cleanup cron task
4. Langfuse observability for all new skills
5. Multi-language support for prompts and responses
6. Performance testing (large files, concurrent conversions)
7. Update CLAUDE.md with document agent documentation

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
src/tools/document_reader.py              # Reusable text extraction
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
alembic/versions/xxxx_add_document_fields.py
```

## 14. Files to Modify

```
src/agents/config.py              — Add document agent config
src/skills/__init__.py             — Register 12 new skills, update 2 moved skills
src/core/domains.py                — Add Domain.document + INTENT_DOMAIN_MAP entries
src/core/intent.py                 — Add 12 new intents to INTENT_DETECTION_PROMPT
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

### New Python packages

| Package | Version | Size | License | Transitive deps |
|---------|---------|------|---------|-----------------|
| pdfplumber | >=0.11.0 | ~2MB | MIT | pdfminer.six (already a WeasyPrint dep chain) |
| pypdf | >=4.0.0 | ~1MB | BSD | Zero external deps. Pure Python. |
| python-docx | >=1.1.0 | ~1MB | MIT | lxml (already installed) |
| openpyxl | >=3.1.0 | ~4MB | MIT | et_xmlfile (tiny) |
| docxtpl | >=0.18.0 | ~50KB | LGPL | python-docx, jinja2 (both already installed) |

### System packages (Dockerfile)

- `ghostscript` — only if camelot-py is added in Phase 3 (~15MB)

### Impact on Docker image

~7MB additional Python packages. Minimal impact.

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

---

## 17. Success Metrics

1. **Single entry point**: user says "работа с документами" → routes to document agent (not 3 different agents)
2. **12 new intents** detected correctly with >90% accuracy
3. **Table extraction** works for: native PDF tables, image tables, DOCX tables, XLSX sheets
4. **Template filling** supports DOCX, XLSX, and PDF forms with arbitrary placeholders
5. **Document search** returns relevant results within 2 seconds
6. **Document generation** produces professional PDFs, DOCXs, and XLSXs from text description
7. **All existing tests pass** after skill migration
8. **New skills have 100% test coverage** (mocked external I/O)
9. **No regressions**: scan_receipt still works in receipt agent, writing agent still works without convert_document

---

## 18. Maria & David Scenarios

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
> • Rent increased $150/month ($2,400 → $2,550)
> • Pet deposit added: $500
> • Lease term changed: 1 year → 2 years
> • New clause: Section 14b restricts subletting
> ⚠️ Worth reviewing: the subletting clause is new.
