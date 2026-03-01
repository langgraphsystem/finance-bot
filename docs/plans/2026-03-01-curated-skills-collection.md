# Curated Skills Collection for Finance Bot

**Date:** 2026-03-01
**Source:** 15+ repositories, 270K+ ecosystem, 1200+ skills reviewed
**Result:** 214 skills selected, mapped to 13 agents + 28 planned specialists (Wave 1-4) + dev workflow

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
| **claude-ally-health** | `huifer` (BehiSecc) | Medical report analysis, symptom tracking, medication management, drug interactions, specialist consultations (cardiology, endocrinology, neurology). Privacy-first, runs locally | Ядро Health specialist |
| **NeuroKit2** | `K-Dense-AI` | Physiological signal processing (ECG, EEG, PPG, EMG) | Для wearable/biometrics integration |
| **Clinical Decision Support** | `K-Dense-AI` | Treatment recommendation systems | Pattern для health advisor |
| **USDA Nutrition MCP** | GitHub (independent) | USDA nutrition data API — accurate macros, calories, ingredients | Ядро Nutritionist specialist |
| **Meal Planning Agent** | `thefalc` | Claude + Kafka: meal plans, grocery lists, family preferences | Skill: meal_plan |
| **Fitness App** | `dharmveer97` | Workout tracking (exercises, sets, reps, weights), nutrition insights, progress analytics, goal setting | Паттерн для Fitness specialist |
| **TrainingPeaks MCP** | GitHub (independent) | Query workouts, analyze data, track fitness trends | Для advanced fitness users |
| **HMDB** | `K-Dense-AI` | Human Metabolome Database — metabolites, nutritional metabolism | Для научного подхода к nutrition |
| **FDA Databases** | `K-Dense-AI` | Drugs, adverse events, food safety regulatory data | Для food safety compliance |

### 9.2 Legal (Wave 4 — Legal Assistant) **🟢 39 SKILLS НАЙДЕНО**

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **NDA Review** | `lawvable` (Jamie Tso) | Clause-by-clause issue log, preferred redlines, fallbacks, rationales, deadlines | Skill: review_nda |
| **Contract Review** | `lawvable` (Anthropic) | Reviews contracts against organizational playbooks | Skill: review_contract |
| **NDA Triage** | `lawvable` (Anthropic) | GREEN/YELLOW/RED risk classification for instant routing | Skill: triage_nda |
| **Tech Contract Negotiation** | `lawvable` (Patrick Munro) | Technology services, professional services, B2B contracts | Skill: negotiate_contract |
| **GDPR Breach Sentinel** | `lawvable` (Oliver Schmidt-Prietz) | Breach response under GDPR Articles 33-34 | Для EU compliance |
| **DPIA Sentinel** | `lawvable` (Oliver Schmidt-Prietz) | Data Protection Impact Assessments | Для EU privacy |
| **Privacy Notice / Policy** | `lawvable` (Malik Taiar) | GDPR-compliant privacy notices, cookie policies | Skill: generate_privacy_policy |
| **Vendor Due Diligence** | `lawvable` (Patrick Munro) | Third-party vendor risk assessment | Skill: vendor_audit |
| **Legal Risk Assessment** | `lawvable` (Anthropic) | Risk classification by severity and likelihood | Skill: assess_legal_risk |
| **claude-legal-skill** | `evolsb` (independent) | CUAD risk detection, market benchmarks, lawyer-ready redlines. Position-aware (customer/vendor/buyer/seller). NDAs, SaaS, M&A | Продвинутый contract review |
| **Claude-Legal** | `Kromer-Group` (independent) | Commands: /review-contract, /triage-nda, /vendor-check, /brief, /respond. MCP интеграция с Slack, Teams, Box, Microsoft 365 | Plugin для legal team |
| **Senior GDPR/DSGVO Expert** | `alirezarezvani` | EU GDPR + German DSGVO, DPIA, breach notification | RA/QM bundle (12 skills) |
| _+ 26 доп. skills в lawvable_ | `lawvable` | Employment law, corporate law, methodology, utilities | Полная legal suite |

### 9.3 Construction & Contractor **🟢 221 SKILLS НАЙДЕНО**

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **estimate-builder** | `DDC Construction` | Generates estimates from historical data and templates | Skill: create_estimate |
| **semantic-search-cwicr** | `DDC Construction` | Search 55,719 work items in 31 languages for rate lookups | Skill: search_rates |
| **budget-tracker** | `DDC Construction` | Scheduled budget vs actual costs with alerts | Skill: track_budget |
| **cost-analysis** | `DDC Construction` | Project spending pattern analysis | Skill: analyze_costs |
| **cost-prediction** | `DDC Construction` | ML-based cost forecasting | Skill: predict_cost |
| **schedule-delay-analyzer** | `DDC Construction` | Statistical analysis of schedule variance | Skill: analyze_delays |
| **risk-assessment** | `DDC Construction` | Identifies project risks early | Skill: assess_risk |
| **specification-extractor** | `DDC Construction` | Extracts text/tables from PDF specs into structured data | Skill: extract_specs |
| **ifc-to-excel / rvt-to-excel** | `DDC Construction` | BIM models → Excel for quantity takeoff | Skill: convert_bim |
| **n8n-daily-report** | `DDC Construction` | Automated data collection and report generation | Skill: daily_report |
| **n8n-photo-report** | `DDC Construction` | AI classifies/tags site photos automatically | Skill: photo_report |
| _+ 210 доп. skills_ | `DDC Construction` | 5 категорий: Toolkit (85), Book (67), Insights (20), Curated (20), Innovative (29) | Полная construction suite |

### 9.4 E-commerce / Amazon

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **amazon-ads-mcp (PPC Prophet)** | `ppcprophet` | Amazon Advertising: campaign performance, ACOS, ROAS, CTR, CPC, natural language queries | Skill: amazon_ads |
| **amazon-product-api** | VoltAgent/OpenClaw | Extracts product listings: titles, ASINs, prices, ratings | Skill: amazon_products |
| **ecommerce-operations** | `skills.rest` | Cross-border ops: Inventory Adjuster, Ad Monitor, Daily Reports | Skill: ecommerce_ops |
| **Shopify Automation** | `ComposioHQ` | Products, orders, customers, inventory, GraphQL queries | Skill: shopify_manage |
| **Square Automation** | `ComposioHQ` | Payments, customers, catalog, orders, locations | Skill: square_pos |
| **Seller Labs Amazon MCP** | Seller Labs | Sales, advertising, profitability, inventory, keywords, margins | Skill: seller_analytics |

### 9.5 Travel Planner **🟢 7 ПРОЕКТОВ НАЙДЕНО**

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **travel-planner** | `ailabs-393` (claude-plugins.dev) | Weather, currency, timezone, day-by-day itineraries, budget breakdowns, packing checklists, cultural guides, safety, preference database | Ядро Travel Planner specialist |
| **TRAVEL-PLANNER MCP** | `GongRzhe` | Google Maps API integration for location-based planning | Maps integration |
| **Agentic Travel Planner** | `aakar-mutha` | 5 AI agents collaborating: Claude Haiku + Tavily real-time data | Multi-agent pattern |
| **Travel Consultant** | `jyoung10078` | React app: preferences → detailed itinerary | Frontend pattern |
| **Tripper** | `embabel` | Web search + mapping + Airbnb integration | Booking integration |

### 9.6 Customer Support **🟢 ZENDESK/INTERCOM/FRESHDESK AUTOMATION**

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **claude-cs** | `nbashaw` (independent) | Meta-skill: auto-triage (Critical/High/Medium/Low), context gathering, templated responses, refunds/cancellations. Zendesk, Intercom, HelpScout, Stripe integration | Ядро Customer Support specialist |
| **Zendesk Automation** | `ComposioHQ` | Tickets, users, organizations, search, macros | Skill: zendesk_manage |
| **Intercom Automation** | `ComposioHQ` | Conversations, contacts, companies, tickets, articles | Skill: intercom_manage |
| **Freshdesk Automation** | `ComposioHQ` | Tickets, contacts, agents, groups, canned responses | Skill: freshdesk_manage |
| **Help Scout Automation** | `ComposioHQ` | Conversations, customers, mailboxes, tags | Skill: helpscout_manage |
| **Internal Comms** | `ComposioHQ` | Updates, newsletters, FAQs, status reports | Skill: internal_comms |

### 9.7 Voice & Call Center

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **voice-ai-engine-development** | `sickn33/antigravity` | Complete toolkit: OpenAI Realtime, Vapi, Deepgram, ElevenLabs | Ядро Voice Receptionist |
| **azure-communication-callautomation** | `sickn33/antigravity` | Azure: IVR systems, call routing, call recording | Enterprise voice |
| **azure-ai-voicelive** | `sickn33/antigravity` | Real-time voice AI applications | Realtime voice |
| **claude-code-voice-skill** | `abracadabra50` | Talk to Claude over phone — telephony receptionist | Phone receptionist паттерн |
| **voicemode** | `mbailey` | Offline: local Whisper STT + Kokoro TTS, smart silence detection | Offline voice |
| **elevenlabs** | `BehiSecc` | TTS + two-host podcast generation | Premium TTS |
| **google-tts** | `BehiSecc` | Google Cloud text-to-speech | Budget TTS |

### 9.8 HR & Recruiting

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Interview System Designer** | `alirezarezvani` | Interview loops, question banks, hiring calibration | Skill: design_interview |
| **ResumeSkills** | `Paramchoudhary` (VoltAgent) | 20 skills: resume optimization, ATS analysis, interview prep, career transitions | Skill: optimize_resume |
| **claude-code-job-tailor** | `javiera-vasquez` | AI resume optimization: job analysis, YAML profiles → tailored PDFs, /tailor command | Skill: tailor_resume |
| **employment-contract-templates** | `sickn33/antigravity` | Employment contracts, offer letters, HR policy documents | Skill: generate_contract |
| _aj-geddes HR prompts (18)_ | `aj-geddes` | talent-acquisition, job-description-writer, interview-question-designer, compensation-benchmarking, diversity-inclusion, onboarding-design, succession-planning | Промпт-паттерны для HR agent |

### 9.9 Coaching & Personal Growth

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| _aj-geddes personal-growth (8)_ | `aj-geddes` | confidence-building, emotional-intelligence, life-purpose-discovery, mindfulness-meditation, personal-values, resilience-building, self-awareness, self-discipline | Промпт-паттерны для Coach |
| _aj-geddes personal-productivity (13)_ | `aj-geddes` | goal-achievement-architect, habit-formation-strategist, focus-deep-work, procrastination-elimination, energy-management, peak-performance | Productivity coaching |
| _aj-geddes health-wellness (13)_ | `aj-geddes` | mindfulness-meditation, stress-reduction, mental-health, sleep-optimization, nutrition-planning, workout-routine-designer | Wellness coaching |
| **hooked-ux** | `wondelai` | Hook Model — habit-forming product/life design | Habit formation framework |
| **jobs-to-be-done** | `wondelai` | JTBD — understanding motivation | Self-discovery framework |

### 9.10 Education & Tutoring

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **tutor-skills** | `RoundTable02` (VoltAgent) | Obsidian StudyVault generation | Study material generation |
| **quiz-generator** | `dmccreary` | Quiz generation following Bloom's Taxonomy | Skill: generate_quiz |
| **learning-graph-generator** | `dmccreary` | Learning path visualization | Skill: learning_path |
| **course-description-analyzer** | `dmccreary` | Course analysis and improvement | Skill: analyze_course |
| **Scientific Brainstorming** | `K-Dense-AI` | Ideation and concept generation | Research-based teaching |
| **Research Grants** | `K-Dense-AI` | Grant proposal writing | Для academic users |

### 9.11 DevOps & Engineering (для tech users)

| Skill | Source | Описание | Применение у нас |
|-------|--------|----------|-----------------|
| **Senior DevOps Engineer** | `alirezarezvani` | CI/CD automation, IaC scaffolding, deployment | Для tech_startup business_type |
| **Incident Commander** | `alirezarezvani` | Incident response, severity classification, post-incident review | Operational skill |
| **Observability Designer** | `alirezarezvani` | SLI/SLO framework, alert optimization, golden signals | Для мониторинга Production |

**Итого Specialist Verticals: 95+ skills (включая DDC 221 и lawvable 39)**

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

## 12. Full Specialist Mapping (все 28 специалистов → скиллы из экосистемы)

> Полный маппинг всех 28 запланированных специалистов (Wave 1-4) к доступным скиллам.
> Покрытие: 🟢 = прямые скиллы есть, 🟡 = есть паттерны/building blocks, 🔴 = нужно строить с нуля.

### Wave 1 — Financial (DONE, 4 специалиста)

| # | Specialist | Покрытие | Скиллы из экосистемы | Наш статус |
|---|-----------|----------|---------------------|-----------|
| 1 | **Bookkeeper** | 🟢 | Financial Analyst (alirezarezvani): DCF, budgeting, ratio analysis. analytics-tracking (antigravity): measurement index. charlie-cfo-skill (EveryInc): CFO-level finance | ✅ DONE — financial_summary skill |
| 2 | **Invoicing** | 🟡 | payment-integration (davepoon): Stripe/PayPal/Square, PCI. stripe-best-practices (VoltAgent): billing patterns. xlsx (anthropics): financial model standards | ✅ DONE — generate_invoice skill |
| 3 | **Tax Consultant** | 🟡 | usfiscaldata (K-Dense-AI): Treasury data, national debt, tax revenue. edgartools (K-Dense-AI): SEC filings. Senior GDPR/DSGVO Expert (alirezarezvani): EU tax compliance паттерн | ✅ DONE — tax_estimate skill |
| 4 | **Cash Flow Forecast** | 🟡 | startup-financial-modeling (antigravity): 3-5 year projections. data-storytelling (antigravity): данные → нарратив. alpha-vantage (K-Dense-AI): real-time market data | ✅ DONE — cash_flow_forecast skill |

### Wave 2 — Marketing & Sales (6 специалистов, June-July 2026)

| # | Specialist | Покрытие | Скиллы из экосистемы | Кол-во |
|---|-----------|----------|---------------------|--------|
| 5 | **Content Creator** | 🟢 | content-creator (antigravity): brand voice, SEO optimizer, social strategy. copywriting (antigravity): 5-фаз brief→delivery. Content Creator (alirezarezvani): platform-specific frameworks. content-research-writer (ComposioHQ). creative-director-skill (smixs). storybrand-messaging (wondelai): StoryBrand framework. made-to-stick (wondelai): SUCCESs framework. contagious (wondelai): STEPPS вирусность. content-engine (affaan-m): repurposing workflows. typefully (VoltAgent): social management | **10** |
| 6 | **Email Marketer** | 🟢 | email-marketing-bible (CosmoBlk): 55K-word guide. sales-automator (antigravity): cold email sequences 3-5 touchpoints. Marketing Demand & Acquisition (alirezarezvani): demand gen, full-funnel. predictable-revenue (wondelai): Cold Calling 2.0, outbound. hundred-million-offers (wondelai): pricing, value stacking | **5** |
| 7 | **Google/Meta Ads** | 🟢 | competitive-ads-extractor (ComposioHQ): competitor ad analysis. marketing-ideas (antigravity): SaaS marketing MFS score. marketing-psychology (antigravity): cognitive biases → funnel. Campaign Analytics (alirezarezvani): multi-touch attribution, ROI. Social Media Analyzer (alirezarezvani): engagement metrics. scorecard-marketing (wondelai): quiz/assessment lead funnels. cro-methodology (wondelai): conversion rate optimization | **7** |
| 8 | **Sales Outreach** | 🟢 | sales-pipeline-optimizer (aj-geddes): MEDDIC qualification, forecasting. linkedin-cli (antigravity): LinkedIn automation, Social Selling Index. Sales Engineer (alirezarezvani): solution design, RFP, demo. Revenue Operations (alirezarezvani): pipeline analytics, territory. Customer Success Manager (alirezarezvani): health scores, churn risk. predictable-revenue (wondelai): outbound sales methodology. investor-outreach (affaan-m): personalized outreach | **7** |
| 9 | **Customer Support** | 🟢 | claude-cs (nbashaw): auto-triage + Zendesk/Intercom/HelpScout/Stripe. Zendesk Automation (ComposioHQ). Intercom Automation (ComposioHQ). Freshdesk Automation (ComposioHQ). Help Scout Automation (ComposioHQ). Internal Comms (ComposioHQ). Customer Success Manager (alirezarezvani): playbooks | **7** |
| 10 | **SEO Specialist** | 🟢 | seo-audit (antigravity): weighted scoring 0-100. seo-keyword-strategist: density, LSI, voice search. seo-content-writer: E-E-A-T, Grade 8-10. seo-content-planner: topic clusters, 30-60 day calendars. seo-content-auditor: depth, originality. seo-content-refresher: stale detection. seo-meta-optimizer: URLs/titles/descriptions. seo-snippet-hunter: position zero. seo-authority-builder: E-E-A-T scorecards. seo-structure-architect: siloing, JSON-LD. seo-cannibalization-detector: keyword conflicts. programmatic-seo: scalable page gen. claude-seo (AgriciDaniel). seo-aeo-best-practices (sanity-io) | **14** |

### Wave 3 — Verticals (6 специалистов, August+ 2026)

| # | Specialist | Покрытие | Скиллы из экосистемы | Что нужно строить |
|---|-----------|----------|---------------------|-------------------|
| 11 | **Real Estate Agent** | 🟡 | local-legal-seo-audit (antigravity): Google Business, location pages, reviews. Market Research Reports (K-Dense-AI): рыночный анализ. investor-materials (affaan-m): pitch decks. Content Creator patterns для описания объектов. CRM patterns из booking agent | Нужно: MLS интеграция, виртуальный staging, lead follow-up воронка. Паттерны CRM + content + SEO дают ~40% coverage |
| 12 | **Beauty Salon** | 🟡 | calendly-automation (antigravity): scheduling. Specialist Config Engine — УЖЕ ЕСТЬ manicure.yaml profile. Booking agent skills (9 штук). Customer Success Manager patterns для loyalty | Нужно: loyalty программы, product inventory, специфичные сервисы. Наш specialist engine + booking agent дают ~60% coverage |
| 13 | **Contractor/Plumber** | 🟢 | **DDC Construction (221 skills!)**: estimate-builder, semantic-search-cwicr (55K work items, 31 lang), budget-tracker, cost-analysis, cost-prediction, schedule-delay-analyzer, risk-assessment, specification-extractor, ifc-to-excel, n8n-daily-report, n8n-photo-report. Плюс наш construction.yaml profile + invoice + maps | DDC покрывает ~80% функционала. Нужно: plumber-specific (pipe sizing, drain inspection). Самый обеспеченный вертикальный специалист |
| 14 | **E-commerce/Amazon** | 🟡 | **amazon-ads-mcp (PPC Prophet)**: ACOS, ROAS, CTR, CPC queries. amazon-product-api: listings, ASINs. Shopify Automation (ComposioHQ). Square Automation (ComposioHQ). Seller Labs Amazon MCP. ecommerce-operations (skills.rest). seo-* (14): product page SEO. pricing-strategy (antigravity) | Нужно: unified Seller Central dashboard, inventory forecasting. Amazon MCP + Shopify + SEO дают ~55% coverage |
| 15 | **Voice Receptionist** | 🟡 | **voice-ai-engine-development** (antigravity): OpenAI Realtime + Vapi + Deepgram + ElevenLabs toolkit. azure-communication-callautomation: IVR, call routing, recording. claude-code-voice-skill (abracadabra50): phone receptionist. voicemode (mbailey): offline Whisper STT + Kokoro TTS. elevenlabs + google-tts (BehiSecc) | Нужно: Twilio/Vapi integration, hold music, voice-specific UX. Building blocks покрывают ~50% — pipeline нужно строить |
| 16 | **Restaurant/Food** | 🔴 | track_food skill (наш, life agent). pricing-strategy (antigravity): ценообразование. generate_spreadsheet skill: food cost расчёты. Booking agent для бронирования столов | Нужно: menu management, order processing, food cost percentage, inventory tracking, supplier orders. Самый большой gap — нет ничего в экосистеме |

### Wave 4 — Lifestyle & Niche (12 специалистов, August+ 2026)

| # | Specialist | Покрытие | Скиллы из экосистемы | Что нужно строить |
|---|-----------|----------|---------------------|-------------------|
| 17 | **Nutritionist** | 🟡 | **USDA Nutrition MCP**: accurate macros, calories, ingredients API. **Meal Planning Agent** (thefalc): Claude + Kafka, meal plans, grocery lists, family preferences. claude-ally-health. HMDB (K-Dense-AI): metabolites. FDA Databases. track_food skill (наш) | Нужно: dietary restrictions engine, client meal tracking dashboard. USDA MCP + Meal Planner + наш track_food дают ~55% coverage |
| 18 | **Fitness Trainer** | 🟡 | **Fitness App** (dharmveer97): exercises, sets, reps, weights, nutrition insights, progress analytics, goal setting. **TrainingPeaks MCP**: query workouts, analyze data, track trends. claude-ally-health. Наш mood_checkin + day_plan | Нужно: exercise database API, progressive overload engine, client program builder. Fitness App + TrainingPeaks дают ~40% coverage |
| 19 | **Coach / Personal Growth** | 🟡 | **aj-geddes (34 prompts)**: confidence-building, emotional-intelligence, life-purpose-discovery, mindfulness-meditation, personal-values, resilience-building, self-awareness, self-discipline + 13 productivity (goal-achievement-architect, habit-formation-strategist, focus-deep-work, peak-performance) + 13 health-wellness (stress-reduction, mental-health, sleep-optimization). hooked-ux (wondelai): Hook Model. Наш life agent (mood_checkin, day_plan, day_reflection, quick_capture) | Нужно: goal tracking DB, habit streaks, journaling templates. aj-geddes + наш life agent дают ~55% coverage |
| 20 | **Tutor** | 🟡 | tutor-skills (RoundTable02): StudyVault. **dmccreary (4)**: quiz-generator (Bloom's Taxonomy), learning-graph-generator, course-description-analyzer, p5.js MicroSims. Scientific Brainstorming + Research Grants (K-Dense-AI) | Нужно: curriculum database, adaptive difficulty, spaced repetition, progress tracking. Education skills дают ~45% coverage |
| 21 | **Career Consultant** | 🟡 | **ResumeSkills** (Paramchoudhary): 20 skills — ATS analysis, interview prep, career transitions. **claude-code-job-tailor** (javiera-vasquez): YAML profiles → tailored PDFs, /tailor command. linkedin-cli (antigravity). Interview System Designer (alirezarezvani). **aj-geddes career (15 prompts)**: interview-prep, job-search-optimizer, salary-negotiation, personal-branding, networking | Нужно: LinkedIn profile optimizer, cover letter generator. Resume + Interview + LinkedIn дают ~60% coverage |
| 22 | **Legal Assistant** | 🟢 | **lawvable (39 skills!)**: NDA Review, Contract Review, NDA Triage, Tech Contract Negotiation, GDPR Breach Sentinel, DPIA, Privacy Notice/Policy, Vendor Due Diligence, Legal Risk Assessment + employment law + methodology + utilities. **claude-legal-skill** (evolsb): CUAD risk detection, position-aware analysis. **Claude-Legal** (Kromer-Group): /review-contract, /triage-nda, /vendor-check + MCP. Senior GDPR/DSGVO Expert (alirezarezvani, 12 RA/QM skills). Наш generate_document: contracts, NDAs | Самый обеспеченный Wave 4 specialist. lawvable (39) + alirezarezvani (12) + evolsb + Kromer дают ~75% coverage |
| 23 | **Recruiter** | 🟡 | **aj-geddes HR (18 prompts)**: talent-acquisition, job-description-writer, interview-question-designer, compensation-benchmarking, diversity-inclusion, employee-engagement, onboarding-design, succession-planning. Interview System Designer (alirezarezvani). ResumeSkills (VoltAgent). linkedin-cli (antigravity). **employment-contract-templates** (antigravity): contracts, offer letters, HR policies | Нужно: ATS pipeline, candidate scoring. aj-geddes HR + alirezarezvani + LinkedIn дают ~50% coverage |
| 24 | **Property Manager** | 🟡 | payment-integration (davepoon): rent collection, recurring billing. generate_invoice_pdf: monthly rent invoices. Booking agent: tenant scheduling. calendly-automation: maintenance scheduling. generate_spreadsheet: property P&L | Нужно: tenant screening, maintenance ticket system, lease management, property inspection checklists. Наши building blocks дают ~35% coverage |
| 25 | **Travel Planner** | 🟢 | **travel-planner** (ailabs-393): weather, currency, timezone, day-by-day itineraries, budget breakdowns, packing checklists, cultural guides, safety, preference DB. **TRAVEL-PLANNER MCP** (GongRzhe): Google Maps API. **Agentic Travel Planner** (aakar-mutha): 5 AI agents + Tavily. Tripper (embabel): Airbnb integration. Наш maps_search + web_search + price_check | 7 проектов + наш research agent. Нужно: booking API, visa requirements. Coverage ~65% |
| 26 | **Event Planner** | 🟡 | create_task + set_reminder skills (наш). calendly-automation: scheduling. generate_spreadsheet: budget tracking. send_to_client: vendor communications. Booking agent: venue/vendor scheduling | Нужно: timeline builder, vendor database, guest list management, floor plan tools. Наш tasks + booking agents дают ~35% coverage |
| 27 | **Pet Business** | 🔴 | Booking agent: appointment scheduling. add_contact + list_contacts: client management. set_reminder: vaccination reminders. generate_invoice_pdf: billing | Нужно: pet profile database, vaccination tracker, grooming schedule, breed-specific health alerts. Только наши generic skills, ничего в экосистеме. ~25% coverage |
| 28 | **Auto Repair** | 🔴 | Booking agent: appointment scheduling. generate_invoice_pdf: estimates. maps_search: parts suppliers. compare_options: parts pricing | Нужно: VIN decoder API, vehicle history tracker, parts inventory, labor rate calculator, diagnostic code database. Ничего в экосистеме. ~20% coverage |

---

### Сводка покрытия по Waves

| Wave | Специалисты | 🟢 Прямые | 🟡 Паттерны | 🔴 С нуля | Avg Coverage |
|------|------------|----------|------------|----------|-------------|
| **Wave 1** (DONE) | 4 | 1 | 3 | 0 | ~70% (уже реализованы) |
| **Wave 2** (Marketing) | 6 | **5** | 1 | 0 | **~75%** — богатейшее покрытие |
| **Wave 3** (Verticals) | 6 | **2** (Contractor, Travel) | **3** | 1 (Restaurant) | **~55%** ↑ DDC Construction + Travel |
| **Wave 4** (Niche) | 12 | **2** (Legal, Customer Support) | **8** | **2** (Pet, Auto Repair) | **~50%** ↑ lawvable + ComposioHQ |
| **TOTAL** | **28** | **10** | **15** | **3** | **~60%** ↑ (было ~50%) |

### Ключевой вывод по специалистам

**Wave 2 (Marketing & Sales) — jackpot.** 46 готовых скиллов покрывают ~75% функционала 6 специалистов. SEO Specialist — самый обеспеченный (14 прямых скиллов). Content Creator и Sales Outreach — по 10 и 7 скиллов.

**Wave 3 — лучше чем казалось.** DDC Construction (221 skill!) покрывает ~80% Contractor/Plumber. Travel Planner — 7 проектов, ~65% coverage. E-commerce — Amazon MCP + Shopify + Square + SEO дают ~55%.

**Wave 4 — два прорыва.** Legal Assistant: lawvable (39 skills) + alirezarezvani (12 RA/QM) + evolsb + Kromer = ~75% coverage — самый обеспеченный нишевый специалист. Customer Support: claude-cs + Zendesk/Intercom/Freshdesk/HelpScout automation = ~70%.

**Неожиданные находки:**
- **DDC Construction** — 221 skill, не в наших основных 18 repos. Estimate builder, cost prediction, BIM→Excel, site photo AI. Самый богатый вертикальный collection
- **lawvable** — 39 юридических skills. NDA review, contract review, GDPR sentinel, vendor due diligence
- **aj-geddes** — 73 промпта для coaching (34), HR (18), career (15), customer support (30). Не Claude Skills, но отличные system prompt foundations
- **ComposioHQ** — Zendesk, Intercom, Freshdesk, HelpScout, Shopify, Square автоматизации. Подключаемые интеграции

**Самые дефицитные вертикали (🔴, нет ничего в экосистеме):**
1. Restaurant/Food — нет food cost/menu/inventory скиллов
2. Pet Business — нет pet health/grooming скиллов
3. Auto Repair — нет VIN/diagnostic/parts скиллов

**Возможность:** Если мы создадим эти 3 вертикали + опубликуем — станем единственными в экосистеме 270K+ скиллов с реальными business vertical solutions.

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
| 19 | lawvable/awesome-legal-skills | — | 39 | github.com/lawvable/awesome-legal-skills |
| 20 | DDC Construction Skills | — | 221 | github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction |
| 21 | nbashaw/claude-cs | — | 1 (meta-skill) | github.com/nbashaw/claude-cs |
| 22 | evolsb/claude-legal-skill | — | 1 | github.com/evolsb/claude-legal-skill |
| 23 | Kromer-Group/Claude-Legal | — | 1 | github.com/Kromer-Group/Claude-Legal |

---

## Ключевые выводы

1. **SEO — самая богатая категория в экосистеме** (14 skills из antigravity). Готовый фундамент для SEO Specialist агента.

2. **obra/superpowers — must-have для dev workflow**. 14 skills покрывают весь цикл: brainstorm → plan → implement → test → review → merge. Внедрить P0.

3. **Trail of Bits — единственный серьёзный security source**. 10 skills для Python web apps. semgrep-rule-creator позволит написать кастомные правила для нашего multi-tenant.

4. **Marketing skills ready for Wave 2**. 38 skills дают полный фундамент для 5 specialists (Content Creator, Email Marketer, Ads, Sales, SEO). Не нужно изобретать с нуля.

5. **Financial data skills** (K-Dense-AI) открывают SEC/Treasury/market data доступ для finance_specialist.

6. **Context engineering skills** (muratcankoylan) — теоретическая база для нашей 5-layer memory. Полезно для оптимизации token budget.

7. **Главный GAP в экосистеме**: нет Telegram bot skills, нет booking/scheduling skills, нет multi-channel orchestration. **Наши skills уникальны** — стоит публиковать.
