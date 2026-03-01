"""Complexity classifier for Deep Agent routing.

Determines whether a request needs the deep agent (multi-step planning)
or the standard single-shot path. Uses keyword matching first (zero LLM cost).
"""

import re
from enum import StrEnum

# --- Complexity signals for generate_program ---

_COMPLEX_CODE_KEYWORDS = {
    # Multi-page / multi-component
    "dashboard",
    "admin panel",
    "admin page",
    "multi-page",
    "multiple pages",
    "several pages",
    "multi-route",
    "multiple routes",
    # Auth & users
    "authentication",
    "auth",
    "login",
    "signup",
    "sign up",
    "registration",
    "user management",
    "roles",
    "permissions",
    "oauth",
    # Database
    "database",
    "postgresql",
    "mysql",
    "sqlite",
    "mongodb",
    "crud",
    "data model",
    "schema",
    "migration",
    "orm",
    # API
    "rest api",
    "api endpoints",
    "graphql",
    "websocket",
    "microservice",
    # Complex patterns
    "full-stack",
    "fullstack",
    "e-commerce",
    "ecommerce",
    "marketplace",
    "social network",
    "chat app",
    "real-time",
    "realtime",
    "crm",
    "cms",
    "erp",
    "saas",
    "platform",
    # Deployment
    "docker",
    "kubernetes",
    "ci/cd",
    "deployment pipeline",
    # Testing
    "test suite",
    "unit tests",
    "integration tests",
    # Russian equivalents
    "дашборд",
    "админ панел",
    "многостранич",
    "авторизац",
    "регистрац",
    "база данных",
    "бд",
    "полноценн",
    "платформ",
    "интернет-магазин",
    "магазин",
    "маркетплейс",
    "социальн",
    "чат приложен",
}

_SIMPLE_CODE_KEYWORDS = {
    "hello world",
    "calculator",
    "калькулятор",
    "converter",
    "конвертер",
    "script",
    "скрипт",
    "function",
    "функци",
    "one page",
    "single page",
    "simple",
    "простой",
    "quick",
    "быстр",
    "basic",
    "базов",
    "print",
    "counter",
    "счётчик",
    "счетчик",
    "timer",
    "таймер",
    "todo list",
    "todo",
    "список дел",
    "form",
    "форм",
    "landing",
    "лендинг",
    "page",
    "страниц",
}

# --- Complexity signals for tax_estimate ---

_COMPLEX_TAX_KEYWORDS = {
    "annual",
    "годовой",
    "yearly",
    "за год",
    "full report",
    "полный отчёт",
    "полный отчет",
    "deduction analysis",
    "анализ вычетов",
    "schedule c",
    "schedule-c",
    "self-employment",
    "самозанят",
    "comparison",
    "сравнение",
    "year-over-year",
    "quarterly breakdown",
    "all quarters",
    "все кварталы",
    "tax planning",
    "налоговое планирован",
    "detailed report",
    "детальный отчёт",
    "detailed",
    "подробн",
    "optimization",
    "оптимизац",
    "tax strategy",
    "стратег",
    "multi-quarter",
    "несколько квартал",
}

_SIMPLE_TAX_KEYWORDS = {
    "estimate",
    "оценка",
    "оценк",
    "how much",
    "сколько",
    "this quarter",
    "этот квартал",
    "current",
    "текущ",
    "quick",
    "быстр",
    "rough",
    "примерн",
    "грубо",
}


class ComplexityLevel(StrEnum):
    simple = "simple"
    complex = "complex"


def classify_program_complexity(description: str) -> ComplexityLevel:
    """Classify whether a code generation request is simple or complex.

    Uses keyword matching only — no LLM cost.
    """
    text = description.lower()

    complex_score = 0
    simple_score = 0

    for kw in _COMPLEX_CODE_KEYWORDS:
        if kw in text:
            complex_score += 1

    for kw in _SIMPLE_CODE_KEYWORDS:
        if kw in text:
            simple_score += 1

    # Length heuristic: very long descriptions tend to be complex
    if len(description) > 200:
        complex_score += 1

    # Multiple requirements (bullet points, numbered lists, "and", commas)
    if text.count(",") >= 3 or text.count(" и ") >= 2 or text.count(" and ") >= 2:
        complex_score += 1

    # Numbered lists / bullet points
    if re.search(r"(?:^|\n)\s*(?:\d+[.)]|[-•])\s", text):
        complex_score += 1

    # Need 2+ complex signals to classify as complex
    if complex_score >= 2 and complex_score > simple_score:
        return ComplexityLevel.complex

    return ComplexityLevel.simple


def classify_tax_complexity(description: str) -> ComplexityLevel:
    """Classify whether a tax request is simple or complex.

    Uses keyword matching only — no LLM cost.
    """
    text = description.lower()

    complex_score = 0
    simple_score = 0

    for kw in _COMPLEX_TAX_KEYWORDS:
        if kw in text:
            complex_score += 1

    for kw in _SIMPLE_TAX_KEYWORDS:
        if kw in text:
            simple_score += 1

    if complex_score >= 2 and complex_score > simple_score:
        return ComplexityLevel.complex

    return ComplexityLevel.simple
