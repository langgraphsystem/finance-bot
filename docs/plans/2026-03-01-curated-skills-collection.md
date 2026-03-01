# Curated Skills Collection for Finance Bot

**Date:** 2026-03-01
**Source:** 15+ repositories, 270K+ ecosystem, 1200+ skills reviewed
**Result:** 214 skills selected, mapped to 13 agents + 6 planned specialists + dev workflow

---

## How to Use This File

Each section maps to either an **existing agent**, a **planned specialist** (Wave 2-4), or a **development workflow**.
Every skill has: source repo, direct URL pattern, and relevance to our architecture.

**Install pattern (Claude Code):**
```bash
# From marketplace
/plugin marketplace add <org>/<repo>
/plugin install <skill-name>@<marketplace>

# Direct (copy SKILL.md to project)
curl -sL https://raw.githubusercontent.com/<org>/<repo>/main/skills/<name>/SKILL.md > skills/<name>/SKILL.md
```

---

## 1. Development Workflow (для нашего процесса разработки)

> Приоритет: **P0** — внедрить сразу для ускорения разработки Deep Agents и Wave 2-4.

### 1.1 TDD & Testing (obra/superpowers)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **test-driven-development** | `obra/superpowers` | RED-GREEN-REFACTOR. Никакого кода без падающего теста. Включает таблицу рационализаций для закрытия лазеек. | Обязателен для Deep Agents (generate_program, tax_estimate). У нас 1516 тестов — TDD усилит паттерн |
| **verification-before-completion** | `obra/superpowers` | 5-шаговая верификация перед claim of completion. Предыдущие прогоны не считаются. | Для всех PR — особенно критично для finance_specialist (деньги!) |
| **systematic-debugging** | `obra/superpowers` | 4-фазный root-cause анализ: исследование → паттерны → гипотеза → фикс. Если 3+ попытки — пересмотр архитектуры | Для отладки LangGraph orchestrators (email, booking FSM) |

### 1.2 Planning & Dispatch (obra/superpowers)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **brainstorming** | `obra/superpowers` | Socratic design — 5 фаз ДО написания кода. Документ → docs/plans/ | Уже используем паттерн (13 PRDs). Формализуем через этот skill |
| **writing-plans** | `obra/superpowers` | Декомпозиция в задачи по 2-5 мин с точными путями, кодом, командами. TDD цикл на каждый таск | Для Wave 2-4 — каждый специалист как план из 10-15 задач |
| **executing-plans** | `obra/superpowers` | Batch execution по 3 задачи + пауза для feedback. Git worktrees для изоляции | Для параллельной разработки: Claude Code + Codex worktrees |
| **subagent-driven-development** | `obra/superpowers` | Один субагент на задачу + двухэтапный review (spec compliance → code quality) | Для Deep Agent Tier 3 задач — субагенты для шагов |
| **dispatching-parallel-agents** | `obra/superpowers` | Параллельные субагенты для независимых доменов. Проверка конфликтов после | Для Brief orchestrator (уже fan-out) — паттерн для новых orchestrators |

### 1.3 Git & Code Review (obra/superpowers)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **using-git-worktrees** | `obra/superpowers` | Изолированные worktrees + baseline тесты + auto-detect проекта | Уже в multi-agent workflow (docs/plans/2026-02-24). Формализуем |
| **finishing-a-development-branch** | `obra/superpowers` | 4 варианта: merge, PR, keep, discard. Никогда не merge с failing tests | Стандартизируем для всех веток |
| **requesting-code-review** | `obra/superpowers` | Dispatch code-reviewer субагента. Severity: Critical→fix, Important→resolve, Minor→document | Для PR review перед push |
| **receiving-code-review** | `obra/superpowers` | Техническая верификация > performative agreement. Push back с обоснованием | Для code review feedback loop |

### 1.4 Meta-Skills (obra/superpowers)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **writing-skills** | `obra/superpowers` | TDD для документации процессов. RED=pressure-сценарии, GREEN=минимальная доку, REFACTOR=bulletproof | Для создания новых specialist configs |
| **using-superpowers** | `obra/superpowers` | "Invoke skills BEFORE any action." Даже 1% вероятности — загрузи skill | Как philosophy для нашего skill routing |

**Итого obra/superpowers: 14 skills → все 14 релевантны для dev workflow**

---

## 2. Security (для нашей production системы)

> Приоритет: **P1** — у нас multi-tenant с деньгами, нужен hardening.

### 2.1 Static Analysis (Trail of Bits)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **static-analysis** | `trailofbits/skills` | CodeQL + Semgrep + SARIF. Security queries для Python, JS. Агенты: semgrep-scanner (параллель), semgrep-triager (true/false positive) | Запускать на каждом PR. Python security queries для FastAPI + SQLAlchemy |
| **semgrep-rule-creator** | `trailofbits/skills` | Test-driven разработка Semgrep правил. AST анализ, taint mode, pattern matching | Кастомные правила: missing filter_query() для tenant isolation, unprotected endpoints |
| **variant-analysis** | `trailofbits/skills` | Нашёл одну уязвимость → ищи паттерн по всем 93 skill handlers. 5-фаз: analyze → build patterns → generalize → expand → document | После аудита — поиск по 93 handlers |
| **differential-review** | `trailofbits/skills` | Security-focused PR review. Risk-first: auth, crypto, value transfer, external calls. Blast radius analysis | Критично для multi-tenant — каждый PR с family_id изменениями |

### 2.2 Configuration & Defaults (Trail of Bits)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **insecure-defaults** | `trailofbits/skills` | Hardcoded secrets, default credentials, weak crypto, permissive CORS, fail-open patterns | Проверить: JWT config, CORS в api/main.py, Railway env vars, Docker config |
| **sharp-edges** | `trailofbits/skills` | 3 линзы: Scoundrel (bypass), Lazy Developer (copy-paste), Confused Developer (ambiguity). 6 категорий детекции | Проверить: data_tools (SQL injection через LLM), browser auth cookies, Telegram callback handler |
| **supply-chain-risk-auditor** | `trailofbits/skills` | Аудит зависимостей: popularity, maintainer count, CVE history, security contacts | Проверить: 260 packages в uv.lock. Критичные: WeasyPrint, E2B, nemoguardrails |
| **modern-python** | `trailofbits/skills` | uv + ruff + ty + pip-audit + detect-secrets. Совпадает с нашим стеком | Добавить pip-audit и detect-secrets в CI |

### 2.3 Application Security (Trail of Bits)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **property-based-testing** | `trailofbits/skills` | Hypothesis для Python. Property-based тесты для parsers, validators, data structures | Для data_tools: property tests на query_data, create_record с fuzzy inputs |
| **agentic-actions-auditor** | `trailofbits/skills` | Аудит GitHub Actions для AI agent уязвимостей | Проверить .github/workflows/ci.yml — Railway deploy step |

### 2.4 Community Security

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **VibeSec-Skill** | `BehiSecc` | Secure code writing и prevention | Общие guidelines для skill handlers |
| **owasp-security** | `BehiSecc` | OWASP Top 10:2025, ASVS 5.0, agentic AI security | Чеклист для нашего agentic architecture |

**Итого Security: 12 skills → 10 для CI/review, 2 для guidelines**

---

## 3. Finance & Analytics (усиление наших агентов)

> Приоритет: **P1** — прямое усиление finance_specialist + analytics агентов.

### 3.1 Financial Data & Analysis

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **edgartools** | `K-Dense-AI` | SEC 10-K, 10-Q, 8-K, 13F, Form 4, XBRL, insider trading | Для research agent — финансовый анализ компаний для бизнес-пользователей |
| **usfiscaldata** | `K-Dense-AI` | National debt, Treasury Statements, auctions | Контекст для tax_estimate и cash_flow_forecast |
| **alpha-vantage** | `K-Dense-AI` | Real-time stocks, options, forex, crypto, commodities | Для price_alert skill — расширение на финансовые инструменты |
| **charlie-cfo-skill** | `EveryInc` (VoltAgent) | CFO-level financial management | Паттерн для усиления finance_specialist промпта |
| **Financial Analyst** | `alirezarezvani` | DCF valuation, budget analysis, financial modeling, ratio analysis, scenario planning | Расширение financial_summary skill |

### 3.2 Business Analytics Patterns

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **analytics-tracking** | `sickn33/antigravity` | Measurement Readiness Index (0-100). Event taxonomy, conversion discipline | Паттерн для analytics agent — структурированная оценка данных |
| **data-storytelling** | `sickn33/antigravity` | Данные → нарратив. Setup-Conflict-Resolution arc. Nussbaumer Knaflic методология | Для query_report skill — превращать числа в историю |
| **startup-metrics-framework** | `sickn33/antigravity` | SaaS метрики и unit economics | Для business users — MRR, churn, LTV/CAC |
| **startup-financial-modeling** | `sickn33/antigravity` | 3-5 year projections | Усиление cash_flow_forecast skill |
| **market-sizing-analysis** | `sickn33/antigravity` | TAM/SAM/SOM calculations | Для research agent — market analysis skill (будущее) |

**Итого Finance: 10 skills → 5 для data sources, 5 для analytics patterns**

---

## 4. Marketing & Growth (Wave 2 — Content Creator, Email Marketer, Ads, SEO)

> Приоритет: **P2** — основа для Wave 2 specialists (June-July 2026).

### 4.1 SEO Specialist (planned Wave 2)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **seo-audit** | `sickn33/antigravity` | Weighted scoring (0-100): Crawlability 30%, Technical 25%, On-Page 20%, Content/E-E-A-T 15%, Authority 10% | Ядро будущего SEO specialist agent |
| **seo-keyword-strategist** | `sickn33/antigravity` | Keyword density, entity mapping, 20-30 LSI variations, voice search, featured snippets | Skill: keyword_research |
| **seo-content-writer** | `sickn33/antigravity` | E-E-A-T, 0.5-1.5% density, Grade 8-10, title variations, meta descriptions | Skill: seo_content |
| **seo-content-planner** | `sickn33/antigravity` | Topic clusters, gap analysis, 30-60 day calendars, internal linking blueprints | Skill: content_calendar |
| **seo-content-auditor** | `sickn33/antigravity` | Content depth, originality, E-E-A-T signals, readability scores | Skill: content_audit |
| **seo-content-refresher** | `sickn33/antigravity` | Refresh Priority Matrix, detect stale content (2+ years), expired links | Skill: content_refresh |
| **seo-meta-optimizer** | `sickn33/antigravity` | URLs (60 chars), titles (50-60), descriptions (150-160). 3-5 вариаций, A/B рекомендации | Skill: meta_optimize |
| **seo-snippet-hunter** | `sickn33/antigravity` | Position zero targeting. Paragraph/list/table formats, FAQPage/HowTo schema | Skill: snippet_optimize |
| **seo-authority-builder** | `sickn33/antigravity` | E-E-A-T scorecards, author bios, trust signals, topical authority maps | Skill: authority_build |
| **seo-structure-architect** | `sickn33/antigravity` | Header hierarchy, siloing, JSON-LD, internal linking matrices, breadcrumbs | Skill: site_structure |
| **seo-cannibalization-detector** | `sickn33/antigravity` | Keyword conflicts, overlap analysis, 301 redirect recommendations | Skill: cannibalization_check |
| **programmatic-seo** | `sickn33/antigravity` | Scalable page generation. Feasibility Index (0-100), quality gates | Skill: programmatic_pages |
| **claude-seo** | `AgriciDaniel` (VoltAgent) | Universal SEO analysis | Дополнение к seo-audit |
| **seo-aeo-best-practices** | `sanity-io` (VoltAgent) | SEO + answer engine optimization | Паттерн для AI-optimized content |

### 4.2 Content Creator Specialist (planned Wave 2)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **content-creator** | `sickn33/antigravity` | Brand voice analyzer, SEO optimizer (0-100), blog optimization (1500-2500 words), social media strategy (40/25/25/10 ratio), content calendars | Ядро Content Creator specialist |
| **copywriting** | `sickn33/antigravity` | 5-фаз: context → brief → principles → structure → delivery. 2-3 headline/CTA альтернативы | Skill: write_copy |
| **Content Creator** | `alirezarezvani` | Brand voice, SEO, platform-specific frameworks for blogs, emails, social, video | Усиление системного промпта |
| **content-research-writer** | `ComposioHQ` (BehiSecc) | Research-backed content writing с citations | Skill: research_content |
| **creative-director-skill** | `smixs` (VoltAgent) | AI creative direction, 20+ methodologies | Pattern для creative brief |
| **integrated-campaign-architect** | `aj-geddes` | Multi-channel campaigns, budget allocation, 1000+ MQLs target | Skill: campaign_plan |

### 4.3 Email Marketer Specialist (planned Wave 2)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **email-marketing-bible** | `CosmoBlk` (VoltAgent) | 55,000-word email marketing guide | Системный промпт для Email Marketer specialist |
| **sales-automator** | `sickn33/antigravity` | Cold email sequences (3-5 touchpoints), cadence planning, A/B testing subject lines | Skill: email_sequence |
| **Marketing Demand & Acquisition** | `alirezarezvani` | Demand gen, paid media, SEO, partnerships, full-funnel | Усиление email marketing стратегии |

### 4.4 Ads Manager Specialist (planned Wave 2)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **competitive-ads-extractor** | `ComposioHQ` (VoltAgent) | Competitor ad analysis | Skill: analyze_competitor_ads |
| **marketing-ideas** | `sickn33/antigravity` | SaaS marketing decision filter, MFS score (-7 to +13), max 5 recommendations | Skill: marketing_ideas |
| **marketing-psychology** | `sickn33/antigravity` | PLFS score, cognitive biases → funnel stages, ethical guardrails | Skill: psychology_insights |
| **Campaign Analytics** | `alirezarezvani` | Multi-touch attribution, funnel conversion, ROI measurement | Skill: campaign_analytics |
| **Social Media Analyzer** | `alirezarezvani` | Engagement metrics, trend detection, ROI tracking | Skill: social_analytics |

### 4.5 Sales Outreach Specialist (planned Wave 2)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **sales-pipeline-optimizer** | `aj-geddes` | Pipeline diagnosis, MEDDIC qualification, deal acceleration, forecasting | Skill: pipeline_optimize |
| **linkedin-cli** | `sickn33/antigravity` | LinkedIn automation: search, messaging, InMail, Social Selling Index | Skill: linkedin_outreach |
| **Sales Engineer** | `alirezarezvani` | Solution design, RFP response, demo frameworks, POC management | Усиление sales промпта |
| **Revenue Operations** | `alirezarezvani` | Pipeline analytics, revenue forecasting, territory planning | Skill: revenue_ops |
| **Customer Success Manager** | `alirezarezvani` | Health scores, churn risk, onboarding playbooks, QBR templates | Skill: customer_success |
| **founder-skills** | `ognjengt` (VoltAgent) | Startup workflow packages | Паттерн для business owner users |

### 4.6 Marketing Strategy (cross-cutting)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Marketing Strategy & Product Marketing** | `alirezarezvani` | April Dunford positioning, GTM strategy, launch plans, competitive intel | Master strategy skill |
| **App Store Optimization (ASO)** | `alirezarezvani` | Apple + Google Play optimization, keywords, conversion | Для мобильных users |
| **pricing-strategy** | `sickn33/antigravity` | Van Westendorp, MaxDiff, 3-tier architecture (Good/Better/Best), freemium vs trial | Для SaaS pricing pages |
| **competitor-alternatives** | `sickn33/antigravity` | Comparison pages, alternative pages, honest positioning | SEO + sales content |
| **free-tool-strategy** | `sickn33/antigravity` | Free tools для lead gen. 8-factor scorecard, gating strategies, ROI calculation | Marketing growth tactics |
| **scroll-experience** | `sickn33/antigravity` | Cinematic scroll landing pages, GSAP, Framer Motion | Frontend landing pages |

### 4.7 Marketing Frameworks (wondelai/skills via BehiSecc)

Книжные фреймворки, адаптированные в skills — для системных промптов specialists:

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **storybrand-messaging** | `wondelai` | StoryBrand narrative framework — clear brand messaging | Шаблон для write_post skill |
| **one-page-marketing** | `wondelai` | 9-square marketing plan grid | Marketing planning skill |
| **contagious** | `wondelai` | STEPPS framework (Social currency, Triggers, Emotion, Public, Practical, Stories) для вирусности | Content strategy pattern |
| **made-to-stick** | `wondelai` | SUCCESs framework (Simple, Unexpected, Concrete, Credible, Emotional, Stories) | Copywriting foundation |
| **scorecard-marketing** | `wondelai` | Quiz/assessment lead generation funnels | Lead gen skill |
| **cro-methodology** | `wondelai` | Scientific conversion rate optimization | CRO skill для landing pages |
| **obviously-awesome** | `wondelai` | Product positioning framework (April Dunford) | GTM positioning |
| **predictable-revenue** | `wondelai` | Outbound sales, Cold Calling 2.0 | Sales outreach foundation |
| **hundred-million-offers** | `wondelai` | Grand Slam Offer creation: pricing, value stacking, guarantees | Pricing strategy |

### 4.8 Content & Social Media Distribution

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **content-engine** | `affaan-m` | Multi-platform content repurposing workflows | Skill: repurpose_content |
| **market-research** | `affaan-m` | Source-attributed market/competitor research | Усиление web_search для бизнеса |
| **investor-materials** | `affaan-m` | Pitch decks, financial models, one-pagers, memos | Для startup business_type users |
| **investor-outreach** | `affaan-m` | Personalized fundraising outreach and follow-up | Fundraising skill |
| **x-twitter-scraper** | `Xquik-dev` (VoltAgent) | X/Twitter data extraction and monitoring | Social listening |
| **Shpigford/screenshots** | VoltAgent | Marketing screenshot generation with Playwright | Visual assets для marketing |

**Итого Marketing & Growth: 53 skills → ядро для 5 Wave 2 specialists + marketing frameworks**

---

## 5. Business Strategy & Management (усиление C-suite функций)

> Приоритет: **P2** — для business users ($49-99/month).

### 5.1 C-Level Advisory

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **CEO Advisor** | `alirezarezvani` | Strategic decision-making, org development, stakeholder management, financial scenario modeling | Новый skill для onboarding/general_chat — бизнес-советы |
| **CTO Advisor** | `alirezarezvani` | Tech debt quantification, team scaling, architecture decisions | Для business_type=tech_startup |
| **Product Manager Toolkit** | `alirezarezvani` | RICE scoring, customer interview analysis, PRD templates, metrics | Расширение для Pro tier |
| **Product Strategist** | `alirezarezvani` | OKR cascade, alignment scoring, vision frameworks, roadmap | Strategic planning skill |

### 5.2 Product Discovery Frameworks (wondelai/skills)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **jobs-to-be-done** | `wondelai` | JTBD framework — why customers buy | Для onboarding — понимание бизнес-нужд пользователей |
| **lean-startup** | `wondelai` | Build-Measure-Learn methodology | Для startup business_type users |
| **continuous-discovery** | `wondelai` | Opportunity Solution Trees, weekly touchpoints | Product strategy skill |
| **mom-test** | `wondelai` | Customer interview framework (Rob Fitzpatrick) | Research skill для customer discovery |
| **design-sprint** | `wondelai` | 5-day prototyping and testing process | Sprint planning pattern |
| **hooked-ux** | `wondelai` | Habit-forming product design, Hook Model (Nir Eyal) | Retention strategy для SaaS users |
| **traction-eos** | `wondelai` | Entrepreneurial Operating System for running businesses | Business operations pattern |

### 5.3 Project Management

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Senior Project Management Expert** | `alirezarezvani` | Portfolio management, stakeholder alignment, risk management, Atlassian integration | Будущий PM specialist |
| **Scrum Master Expert** | `alirezarezvani` | Sprint planning, daily standups, retros, velocity tracking | Agile workflow skill |
| **kanban-skill** | `BehiSecc` | Markdown Kanban с YAML frontmatter | Простой Kanban для tasks agent |
| **linear-claude-skill** | `BehiSecc` | Linear issue and project management | Интеграция с Linear |
| **pm-skills** | `BehiSecc` | 24 product management skills across Triple Diamond lifecycle | PM framework |

### 5.3 Regulatory & Compliance

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Senior GDPR/DSGVO Expert** | `alirezarezvani` | EU GDPR + German DSGVO compliance, DPIA, breach notification | P3 — EU expansion. Критично для multi-tenant данных |
| **ISO 13485 Certification** | `K-Dense-AI` | Medical device standards | Для health vertical (Wave 4) |

**Итого Business Strategy: 11 skills**

---

## 6. Document & Presentation (усиление document agent)

> Приоритет: **P2** — у нас уже 20 document skills, это расширение.

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **xlsx** (official) | `anthropics/skills` | Formula-first, financial model standards (blue=inputs, black=formulas). Zero-errors mandatory | Усиление generate_spreadsheet — financial model standards |
| **pptx** (official) | `anthropics/skills` | 10 color palettes, QA via subagents, JPG conversion at 150 DPI, fix-and-verify cycles | Усиление generate_presentation — QA workflow |
| **doc-coauthoring** | `anthropics/skills` | 3-stage collaborative: context → refinement (5-20 options/section) → reader testing | Паттерн для generate_document — collaborative mode |
| **skill-creator** | `anthropics/skills` | Meta-skill для создания новых skills через Q&A | Для create_specialist meta-skill |
| **revealjs-skill** | `BehiSecc` | Reveal.js HTML presentations | Альтернатива python-pptx для web presentations |
| **frontend-slides** | `BehiSecc` | Animation-rich HTML presentations from scratch or PPTX conversion | Расширение generate_presentation |
| **PSPDFKit nutrient** | VoltAgent | Multi-format document processing с OCR, redaction, signatures | Расширение document agent capabilities |

**Итого Documents: 7 skills**

---

## 7. Communication & Channels (усиление gateways)

> Приоритет: **P2** — расширение multi-channel.

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **integrate-whatsapp** | `gokapso` (VoltAgent) | WhatsApp webhook integration | Усиление whatsapp_gw.py |
| **automate-whatsapp** | `gokapso` (VoltAgent) | WhatsApp workflow automation | Автоматизации для booking agent через WhatsApp |
| **observe-whatsapp** | `gokapso` (VoltAgent) | WhatsApp debugging and observability | Мониторинг WhatsApp канала |
| **whatsapp-automation** | `sickn33/antigravity` | WhatsApp Business API: templates, media, compliance | Meta-approved templates для send_to_client |
| **claudisms (SMS)** | `jeffersonwarrior` (VoltAgent) | SMS messaging integration | Усиление sms_gw.py |
| **elevenlabs** | `BehiSecc` | Text-to-speech and two-host podcast generation | Voice Receptionist (July roadmap) |
| **google-tts** | `BehiSecc` | Google Cloud text-to-speech | Альтернатива ElevenLabs для Voice Receptionist |
| **fal-audio** | `fal-ai` (VoltAgent) | Text-to-speech and speech-to-text | Ещё вариант для Voice |
| **typefully** | `typefully` (VoltAgent) | Social media content management | Для Content Creator specialist |
| **x-article-publisher-skill** | `wshuyi` (VoltAgent) | Article publishing to X/Twitter | Social media posting |

**Итого Communication: 10 skills**

---

## 8. Research & AI/ML (усиление research + будущие agents)

> Приоритет: **P3** — для Deep Agents и AI-powered features.

### 8.1 AI Agent Architecture

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **RAG Architect** | `alirezarezvani` | Chunking optimization, retrieval evaluation, architecture generation | Усиление Mem0 integration + semantic search |
| **Agent Designer** | `alirezarezvani` | Multi-agent architecture, tool schema generation, performance evaluation | Для scaling к 40+ agents |
| **model-hierarchy-skill** | `zscole` (VoltAgent) | Cost-optimized model routing | Усиление src/core/llm/router.py — 6-model routing |

### 8.2 Context Engineering (muratcankoylan, VoltAgent)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **context-fundamentals** | `muratcankoylan` (VoltAgent) | Context system understanding | Theoretical foundation для 5-layer memory |
| **context-degradation** | `muratcankoylan` (VoltAgent) | Context failure pattern recognition | Диагностика когда memory layers деградируют |
| **context-compression** | `muratcankoylan` (VoltAgent) | Compression strategy design | Усиление progressive context disclosure |
| **context-optimization** | `muratcankoylan` (VoltAgent) | Caching and compression | Оптимизация 150K token budget |
| **multi-agent-patterns** | `muratcankoylan` (VoltAgent) | Multi-agent architectures | Паттерны для 3-level supervisor routing |
| **memory-systems** | `muratcankoylan` (VoltAgent) | Memory architecture design | Theoretical basis для нашей 5-layer memory |
| **data-structure-protocol** | `k-kolomeitsev` (VoltAgent) | Graph-based long-term memory | Для Mem0g graph memory (Infrastructure roadmap) |
| **claude-memory-skill** | `hanfang` (VoltAgent) | Hierarchical memory system | Паттерн для memory layer optimization |

### 8.3 Scientific & Research Tools

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Market Research Reports** | `K-Dense-AI` | Market analysis and trends | Для research agent — market research capability |
| **deep-research** | `BehiSecc` | Autonomous multi-step research using Gemini | Усиление web_search skill для deep research mode |
| **Perplexity Search** | `K-Dense-AI` | AI-powered search with real-time information | Альтернатива Gemini Search Grounding |

**Итого Research & AI: 14 skills**

---

## 9. Specialist Verticals (Wave 3-4)

> Приоритет: **P3** — подготовка к Wave 3 (August+) и Wave 4.

### 9.1 Health & Wellness (Wave 4 — Nutritionist, Fitness)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **claude-ally-health** | `BehiSecc` | Medical report analysis, personalized wellness tracking | Ядро Health specialist |
| **NeuroKit2** | `K-Dense-AI` | Physiological signal processing | Для wearable integration |
| **Clinical Decision Support** | `K-Dense-AI` | Treatment recommendation systems | Pattern для health advisor |

### 9.2 Legal (Wave 4 — Legal Assistant)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **awesome-legal-skills** | `lawvable` (VoltAgent) | Legal workflow automation | Ядро Legal specialist |
| **Senior GDPR/DSGVO Expert** | `alirezarezvani` | EU compliance | GDPR skill для legal agent |

### 9.3 Education (Wave 4 — Tutor)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **tutor-skills** | `RoundTable02` (VoltAgent) | Obsidian StudyVault generation | Паттерн для Tutor specialist |
| **Scientific Brainstorming** | `K-Dense-AI` | Ideation and concept generation | Для education/research |
| **Research Grants** | `K-Dense-AI` | Grant proposal writing | Для academic users |

### 9.4 Real Estate (Wave 3)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **local-legal-seo-audit** | `sickn33/antigravity` | Google Business Profile, location pages, reviews | Паттерн для Real Estate SEO |

### 9.5 Recruiting (Wave 4 — Recruiter)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Interview System Designer** | `alirezarezvani` | Interview loops, question banks, hiring calibration | Recruiter specialist skill |
| **ResumeSkills** | `Paramchoudhary` (VoltAgent) | Resume optimization and interview prep | Companion skill |

### 9.6 DevOps & Engineering (Wave 4 — для tech users)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Senior DevOps Engineer** | `alirezarezvani` | CI/CD automation, IaC scaffolding, deployment | Для tech_startup business_type |
| **Incident Commander** | `alirezarezvani` | Incident response, severity classification, post-incident review | Operational skill |
| **Observability Designer** | `alirezarezvani` | SLI/SLO framework, alert optimization, golden signals | Для мониторинга нашего Production |

**Итого Specialist Verticals: 14 skills**

---

## 10. Infrastructure & Quality (усиление CI/CD и deployment)

> Приоритет: **P3** — для production hardening.

### 10.1 Code Quality

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Tech Debt Tracker** | `alirezarezvani` | AST parsing, prioritization, trend tracking | Для tracking 390+ файлов |
| **API Design Reviewer** | `alirezarezvani` | REST/OpenAPI linting, breaking changes | Для api/main.py endpoints |
| **Dependency Auditor** | `alirezarezvani` | Multi-language scanning, license compliance | Для uv.lock — 260 packages |
| **Release Manager** | `alirezarezvani` | Changelog generation, semantic versioning | Стандартизация релизов |
| **Database Designer** | `alirezarezvani` | ERD generation, index optimization, migration generation | Для 30 tables, 15 Alembic migrations |
| **Migration Architect** | `alirezarezvani` | Zero-downtime migration, compatibility, automated rollback | Для Alembic migrations |

### 10.2 Agent Architecture Patterns

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **ln-1000-pipeline-orchestrator** | `levnikolaevich` | L0 meta-orchestrator: 4-stage pipeline (plan→validate→execute→quality) | Паттерн для 3-level supervisor routing (TARGET architecture) |
| **ln-200-scope-decomposer** | `levnikolaevich` | Epics → Stories декомпозиция в одну команду | Для create_specialist meta-skill |
| **ln-310-story-validator** | `levnikolaevich` | 20 criteria / 8 groups с penalty system | Quality gate для specialist configs |
| **cost-aware-llm-pipeline** | `affaan-m` | LLM cost optimization, model routing, budget tracking | Усиление src/core/llm/router.py |
| **quant-analyst** | `davepoon` | VaR, Sharpe ratios, portfolio optimization, options pricing | Для Pro tier users — financial analysis |
| **payment-integration** | `davepoon` | Stripe/PayPal/Square, PCI compliance, subscription billing, webhooks | Усиление нашего Stripe billing |
| **legal-advisor** | `davepoon` | Privacy policies, ToS, GDPR/CCPA/LGPD compliance | Для EU expansion + billing legal |

### 10.3 Platform Skills

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **postgres-best-practices** | `supabase` (VoltAgent) | PostgreSQL best practices для Supabase | Прямое применение — мы на Supabase |
| **stripe-best-practices** | `stripe` (VoltAgent) | Stripe integration patterns | Для нашего billing ($49/month) |
| **upgrade-stripe** | `stripe` (VoltAgent) | Stripe SDK/API version upgrades | Maintenance |
| **google-workspace-skills** | `BehiSecc` | Gmail, Calendar, Chat, Docs, Sheets, Slides, Drive | Усиление email/calendar agents + Google Sheets |

**Итого Infrastructure: 10 skills**

---

## 11. Booking, Scheduling & CRM (усиление booking agent)

> Приоритет: **P2** — прямое усиление существующего booking agent + receptionist.

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **calendly-automation** | `sickn33/antigravity` | Event management, invitee tracking, availability, scheduling links | Интеграция Calendly для booking agent |
| **meeting-insights-analyzer** | `ComposioHQ` (VoltAgent) | Meeting transcript analysis, communication patterns | Для follow-up после bookings |
| **apple-bridges** | `more-io` (VoltAgent) | macOS Calendar, Reminders, Contacts, Notes, Mail | Нативная macOS интеграция (low priority) |
| **Customer Success Manager** | `alirezarezvani` | Health scores, churn risk, onboarding playbooks | CRM enhancement для booking agent |
| **notion-knowledge-capture** | `openai` (VoltAgent) | Notion wiki entry creation | Для notes/knowledge base интеграция |

**Итого Booking & CRM: 5 skills**

---

## Сводная таблица по приоритетам

| Приоритет | Категория | Skills | Когда внедрять |
|-----------|-----------|--------|---------------|
| **P0** | Development Workflow (obra/superpowers) | 14 | Сразу — March 2026 |
| **P1** | Security (Trail of Bits) | 12 | March-April 2026 |
| **P1** | Finance & Analytics | 10 | March-April 2026 |
| **P2** | Marketing & Growth (Wave 2) | 53 | June-July 2026 |
| **P2** | Business Strategy + Product Discovery | 18 | April-May 2026 |
| **P2** | Documents | 7 | April 2026 |
| **P2** | Communication & Channels | 10 | April-May 2026 |
| **P2** | Booking & CRM | 5 | April 2026 |
| **P3** | Research & AI/ML | 14 | May-June 2026 |
| **P3** | Specialist Verticals | 14 | August+ 2026 |
| **P3** | Infrastructure + Architecture | 17 | Ongoing |
| | **TOTAL** | **214** | |

---

## Mapping к нашим агентам

### Существующие 13 агентов — какие skills усиливают каждый:

| Agent | Model | Текущие skills | Добавить из экосистемы |
|-------|-------|---------------|----------------------|
| **receipt** | gemini-3-flash | 1 (scan_receipt) | — (специализирован) |
| **analytics** | claude-sonnet-4-6 | 3 | analytics-tracking, data-storytelling, startup-metrics-framework |
| **chat** | gpt-5.2 | 8 | — (достаточно) |
| **onboarding** | claude-sonnet-4-6 | 2 | CEO Advisor pattern (для бизнес-пользователей) |
| **tasks** | gpt-5.2 | 8 | kanban-skill (если добавим visual kanban) |
| **research** | gemini-3-flash | 8 | deep-research, Market Research Reports, edgartools |
| **writing** | claude-sonnet-4-6 | 8 | copywriting, content-creator patterns |
| **email** | claude-sonnet-4-6 | 5 | email-marketing-bible patterns |
| **calendar** | gpt-5.2 | 5 | calendly-automation (integration) |
| **life** | gpt-5.2 | 14 | claude-ally-health (health tracking усиление) |
| **booking** | gpt-5.2 | 9 | Customer Success Manager, meeting-insights-analyzer |
| **document** | claude-sonnet-4-6 | 20 | xlsx financial standards, pptx QA workflow, doc-coauthoring |
| **finance_specialist** | claude-sonnet-4-6 | 4 | Financial Analyst, charlie-cfo-skill, alpha-vantage |

### Планируемые Wave 2 specialists — ядро из экосистемы:

| Specialist | Skills из экосистемы | Количество |
|-----------|---------------------|-----------|
| **Content Creator** | content-creator, copywriting, Content Creator (alirezarezvani), content-research-writer, creative-director-skill, integrated-campaign-architect | 6 |
| **Email Marketer** | email-marketing-bible, sales-automator, Marketing Demand & Acquisition | 3 |
| **Ads Manager** | competitive-ads-extractor, marketing-ideas, marketing-psychology, Campaign Analytics, Social Media Analyzer | 5 |
| **Sales Outreach** | sales-pipeline-optimizer, linkedin-cli, Sales Engineer, Revenue Operations, Customer Success Manager, founder-skills | 6 |
| **Customer Support** | Customer Success Manager patterns, meeting-insights-analyzer | 2 |
| **SEO Specialist** | seo-audit, seo-keyword-strategist, seo-content-writer, seo-content-planner, seo-content-auditor, seo-content-refresher, seo-meta-optimizer, seo-snippet-hunter, seo-authority-builder, seo-structure-architect, seo-cannibalization-detector, programmatic-seo, claude-seo, seo-aeo-best-practices | 14 |

---

## Источники (repositories)

| # | Repository | Stars | Skills | URL |
|---|-----------|-------|--------|-----|
| 1 | anthropics/skills | 79.7K | 16 | github.com/anthropics/skills |
| 2 | obra/superpowers | 53K+ | 14 | github.com/obra/superpowers |
| 3 | VoltAgent/awesome-agent-skills | 8.2K | 383+ | github.com/VoltAgent/awesome-agent-skills |
| 4 | trailofbits/skills | 1.3K | 34 | github.com/trailofbits/skills |
| 5 | sickn33/antigravity-awesome-skills | — | 954+ | github.com/sickn33/antigravity-awesome-skills |
| 6 | alirezarezvani/claude-skills | 1.5K | 53 | github.com/alirezarezvani/claude-skills |
| 7 | BehiSecc/awesome-claude-skills | 4.3K | 86 | github.com/BehiSecc/awesome-claude-skills |
| 8 | K-Dense-AI/claude-scientific-skills | 6.4K | 148+ | github.com/K-Dense-AI/claude-scientific-skills |
| 9 | aj-geddes/useful-ai-prompts | — | 260+ | github.com/aj-geddes/useful-ai-prompts |
| 10 | travisvn/awesome-claude-skills | 7.6K | 28 | github.com/travisvn/awesome-claude-skills |
| 11 | ComposioHQ/awesome-claude-skills | — | 50+ | github.com/ComposioHQ/awesome-claude-skills |
| 12 | hesreallyhim/awesome-claude-code | 23.5K | 100+ | github.com/hesreallyhim/awesome-claude-code |
| 13 | davepoon/buildwithclaude | — | 117 agents, 175 commands | github.com/davepoon/buildwithclaude |
| 14 | affaan-m/everything-claude-code | — | 50+ | github.com/affaan-m/everything-claude-code |
| 15 | levnikolaevich/claude-code-skills | — | 105 | github.com/levnikolaevich/claude-code-skills |
| 16 | Jeffallan/claude-skills | 3K | 66 | github.com/Jeffallan/claude-skills |
| 17 | wondelai/skills (via BehiSecc) | — | 44 | github.com/wondelai/skills |
| 18 | qdhenry/Claude-Command-Suite | — | 148 commands | github.com/qdhenry/Claude-Command-Suite |

---

## Ключевые выводы

1. **SEO — самая богатая категория в экосистеме** (14 skills из antigravity). Готовый фундамент для SEO Specialist агента.

2. **obra/superpowers — must-have для dev workflow**. 14 skills покрывают весь цикл: brainstorm → plan → implement → test → review → merge. Внедрить P0.

3. **Trail of Bits — единственный серьёзный security source**. 10 skills для Python web apps. semgrep-rule-creator позволит написать кастомные правила для нашего multi-tenant.

4. **Marketing skills ready for Wave 2**. 38 skills дают полный фундамент для 5 specialists (Content Creator, Email Marketer, Ads, Sales, SEO). Не нужно изобретать с нуля.

5. **Financial data skills** (K-Dense-AI) открывают SEC/Treasury/market data доступ для finance_specialist.

6. **Context engineering skills** (muratcankoylan) — теоретическая база для нашей 5-layer memory. Полезно для оптимизации token budget.

7. **Главный GAP в экосистеме**: нет Telegram bot skills, нет booking/scheduling skills, нет multi-channel orchestration. **Наши skills уникальны** — стоит публиковать.
