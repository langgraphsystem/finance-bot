"""Live bot testing harness — sends messages, captures responses, analyzes quality.

Usage:
    python scripts/test_bot_live.py --chat-id 7314014306
    python scripts/test_bot_live.py --chat-id 7314014306 --test finance general
    python scripts/test_bot_live.py --chat-id 7314014306 --no-scoring
    python scripts/test_bot_live.py --chat-id 7314014306 --telegram
    python scripts/test_bot_live.py --chat-id 7314014306 --webhook-sim
    python scripts/test_bot_live.py --golden-file scripts/test_results/golden_dialogues.jsonl
    python scripts/test_bot_live.py --list

Modes:
    Default (direct): Call internal handle_message() directly, capture OutgoingMessage.
                      Requires DATABASE_URL in .env (connects to Supabase).
    --telegram:       Send real messages via Telethon (MTProto), read bot replies.
                      Requires TELEGRAM_API_ID, TELEGRAM_API_HASH in .env.
                      First run will prompt for phone + auth code.
    --webhook-sim:    POST simulated webhooks to Railway (no response capture).

Features:
    - Basic metrics: response time (ms), response length, pass/timeout/error
    - LLM quality scoring via Gemini Flash (relevance, correctness, tone, completeness)
    - Rich ANSI console output with colored scores
    - JSON persistence in scripts/test_results/

Requires:
    TELEGRAM_BOT_TOKEN, DATABASE_URL, GOOGLE_AI_API_KEY in .env
    For --telegram mode: TELEGRAM_API_ID, TELEGRAM_API_HASH in .env
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel

# Load .env BEFORE importing src modules
ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT) / ".env", override=True)

# Force non-development mode to suppress SQLAlchemy echo
os.environ["APP_ENV"] = "testing"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = "https://finance-bot-api-production-10eb.up.railway.app/webhook"

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Silence noisy loggers
for _name in (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool",
    "opentelemetry",
    "opentelemetry.exporter",
    "opentelemetry.sdk",
    "urllib3",
    "urllib3.connectionpool",
    "httpx",
    "httpcore",
    "langfuse",
    "mem0",
    "taskiq",
    "asyncio",
    "aiohttp",
    "google.genai",
    "anthropic",
    "src",
):
    logging.getLogger(_name).setLevel(logging.CRITICAL)

# Suppress Python-level warnings (deprecation, etc.)
warnings.filterwarnings("ignore")

# Re-configure our own logger to only show CRITICAL
logger.setLevel(logging.CRITICAL)

# ────────────────────────────────────────────────────────────────────────
# ANSI colors
# ────────────────────────────────────────────────────────────────────────

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Enable ANSI on Windows
if sys.platform == "win32":
    os.system("")

# ────────────────────────────────────────────────────────────────────────
# Pydantic data models
# ────────────────────────────────────────────────────────────────────────


class LLMScores(BaseModel):
    """Quality scores from Gemini Flash analysis."""

    relevance: int  # 1-5
    correctness: int  # 1-5
    tone: int  # 1-5
    completeness: int  # 1-5
    reasoning: str
    average: float


class ReferenceRubric(BaseModel):
    """Deterministic comparison against a reviewed golden response."""

    coverage: float
    overlap: float
    matched_terms: list[str]
    missing_terms: list[str]
    verdict: str
    passed: bool


class TestResult(BaseModel):
    """Single test case result."""

    category: str
    description: str
    expected_intent: str
    message_sent: str
    response_text: str | None = None
    response_time_ms: int = 0
    response_length: int = 0
    has_response: bool = False
    has_buttons: bool = False
    has_chart: bool = False
    has_document: bool = False
    status: str = "pending"  # pass, timeout, error
    llm_scores: LLMScores | None = None
    error: str | None = None
    expected_response_text: str | None = None
    reference_rubric: ReferenceRubric | None = None
    source: str = "builtin"
    trace_key: str | None = None
    review_candidate_enqueued: bool = False
    review_candidate_trace_key: str | None = None
    review_candidate_error: str | None = None


class RunMetadata(BaseModel):
    """Top-level run info."""

    timestamp: str
    chat_id: int
    mode: str
    categories: list[str]
    total_tests: int
    total_time_seconds: float
    bot_token_hint: str


class AggregateStats(BaseModel):
    """Summary statistics across all tests."""

    total: int = 0
    passed: int = 0
    timed_out: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    avg_relevance: float = 0.0
    avg_correctness: float = 0.0
    avg_tone: float = 0.0
    avg_completeness: float = 0.0
    avg_overall: float = 0.0
    reference_evaluated: int = 0
    reference_passed: int = 0
    avg_reference_coverage: float = 0.0
    avg_reference_overlap: float = 0.0


class TestRunReport(BaseModel):
    """Complete JSON output."""

    metadata: RunMetadata
    results: list[TestResult]
    stats: AggregateStats


@dataclass(slots=True)
class ScenarioCase:
    """Normalized scenario definition for built-in and golden-dialogue tests."""

    category: str
    text: str
    description: str
    expected_intent: str
    expected_response: str | None = None
    source: str = "builtin"
    trace_key: str | None = None


# ────────────────────────────────────────────────────────────────────────
# Test scenarios by category
# ────────────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, list[tuple[str, str]]] = {
    "finance": [
        ("100 кофе", "add_expense — simple expense"),
        ("зарплата 5000", "add_income — income entry"),
        ("сколько я потратил за неделю?", "query_stats — spending query"),
        ("установи бюджет 1000 на еду", "set_budget — budget setting"),
        ("отмени последнее", "undo_last — undo"),
    ],
    "life": [
        ("выпил кофе", "track_drink — coffee"),
        ("съел пиццу 500 калорий", "track_food — food tracking"),
        ("настроение 7 из 10", "mood_checkin — mood"),
        ("план на день", "day_plan — planning"),
        ("итоги дня", "day_reflection — reflection"),
    ],
    "research": [
        ("что такое биткоин?", "quick_answer — quick question"),
        ("найди лучшие рестораны в Нью-Йорке", "web_search — web search"),
        ("сравни iPhone 16 и Samsung S25", "compare_options — comparison"),
    ],
    "tasks": [
        ("напомни купить молоко завтра", "create_task — task creation"),
        ("мои задачи", "list_tasks — task listing"),
    ],
    "shopping": [
        ("добавь в список молоко и хлеб", "shopping_list_add — add items"),
        ("покажи список покупок", "shopping_list_view — view list"),
    ],
    "writing": [
        ("переведи на английский: привет мир", "translate_text — translation"),
        ("напиши пост про AI для Instagram", "write_post — social media post"),
    ],
    "email": [
        ("прочитай почту", "read_inbox — inbox check"),
    ],
    "calendar": [
        ("мои события на неделю", "list_events — events listing"),
        ("какое сегодня число?", "general_chat — date question"),
    ],
    "booking": [
        ("запиши клиента на стрижку завтра в 14:00", "create_booking — booking"),
        ("покажи записи на завтра", "list_bookings — booking list"),
    ],
    "general": [
        ("привет", "general_chat — greeting"),
        ("спасибо!", "general_chat — thanks"),
        ("помощь", "general_chat — help request"),
    ],
    # NOTE: memory tests are stateful — run in order.
    # Steps 1-2 set bot name, steps 3-4 set user name, steps 5-6 test rules,
    # steps 7-8 test memory_vault, step 9 tests forget.
    "memory": [
        ("Тебя зовут Хюррем", "set_identity — set bot name"),
        ("как тебя зовут?", "general_chat — recall bot name → should say Хюррем"),
        ("Меня зовут Манас", "set_identity — set user name"),
        ("как меня зовут?", "general_chat — recall user name → should say Манас"),
        ("всегда отвечай без эмодзи", "set_rule — add formatting rule"),
        ("привет!", "general_chat — rule check: response must have no emoji"),
        ("запомни: я предпочитаю краткие ответы", "memory_save — explicit memory"),
        ("покажи мои воспоминания", "memory_show — list stored memories"),
        ("забудь моё имя", "memory_forget — delete user name from memory"),
        ("как меня зовут?", "general_chat — after forget: should not know name"),
        ("удали все правила", "memory_forget — clear all rules"),
    ],
    "dialog_history": [
        ("о чём мы говорили сегодня?", "dialog_history — today"),
        ("что обсуждали на этой неделе?", "dialog_history — week"),
        ("покажи историю разговоров за вчера", "dialog_history — yesterday"),
    ],
}


def build_builtin_scenario_map(
    categories: list[str] | None = None,
) -> dict[str, list[ScenarioCase]]:
    """Build normalized scenario cases from the static scenario catalog."""
    selected_categories = categories or list(SCENARIOS.keys())
    scenario_map: dict[str, list[ScenarioCase]] = {}
    for category in selected_categories:
        cases: list[ScenarioCase] = []
        for text, description in SCENARIOS.get(category, []):
            cases.append(
                ScenarioCase(
                    category=category,
                    text=text,
                    description=description,
                    expected_intent=parse_expected_intent(description),
                )
            )
        scenario_map[category] = cases
    return scenario_map


def load_golden_scenario_map(
    golden_file: str | Path,
    *,
    categories: list[str] | None = None,
) -> dict[str, list[ScenarioCase]]:
    """Load reviewed production traces exported as golden-dialogue JSONL."""
    path = Path(golden_file)
    if not path.exists():
        raise ValueError(f"Golden dialogue file not found: {path}")

    selected = set(categories or [])
    scenario_map: dict[str, list[ScenarioCase]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid golden dialogue JSON on line {line_number}: {exc}") from exc

        category = str(payload.get("scenario") or "golden")
        if selected and category not in selected:
            continue

        input_text = str(payload.get("input_text") or "").strip()
        if not input_text:
            raise ValueError(f"Golden dialogue line {line_number} is missing input_text")

        trace_key = str(payload.get("trace_key") or "").strip() or None
        description = f"golden dialogue — {category}"
        if trace_key:
            description = f"{description} ({trace_key})"

        scenario_map.setdefault(category, []).append(
            ScenarioCase(
                category=category,
                text=input_text,
                description=description,
                expected_intent=category,
                expected_response=str(payload.get("assistant_response") or "").strip() or None,
                source="golden",
                trace_key=trace_key,
            )
        )

    if not scenario_map:
        scope = f" for categories: {', '.join(categories or [])}" if categories else ""
        raise ValueError(f"No golden dialogues loaded from {path}{scope}")

    return scenario_map


def resolve_scenario_map(
    *,
    categories: list[str] | None = None,
    golden_file: str | None = None,
) -> tuple[list[str], dict[str, list[ScenarioCase]]]:
    """Resolve the scenario set for the current run."""
    if golden_file:
        scenario_map = load_golden_scenario_map(golden_file, categories=categories)
        return list(scenario_map.keys()), scenario_map

    resolved_categories = categories or list(SCENARIOS.keys())
    return resolved_categories, build_builtin_scenario_map(resolved_categories)


# ────────────────────────────────────────────────────────────────────────
# Webhook simulation helpers
# ────────────────────────────────────────────────────────────────────────

_update_counter = int(time.time())


def make_telegram_update(chat_id: int, text: str, user_id: int = 0) -> dict:
    """Create a simulated Telegram webhook update payload."""
    global _update_counter
    _update_counter += 1
    return {
        "update_id": _update_counter,
        "message": {
            "message_id": _update_counter,
            "from": {
                "id": user_id or chat_id,
                "is_bot": False,
                "first_name": "Mega",
                "last_name": "Agent",
                "language_code": "ru",
            },
            "chat": {
                "id": chat_id,
                "type": "private",
            },
            "date": int(time.time()),
            "text": text,
        },
    }


async def send_webhook_payload(
    client: httpx.AsyncClient, chat_id: int, text: str
) -> int:
    """Send a simulated webhook payload to the bot endpoint."""
    payload = make_telegram_update(chat_id, text)
    resp = await client.post(WEBHOOK_URL, json=payload, timeout=30)
    return resp.status_code


# ────────────────────────────────────────────────────────────────────────
# LLM quality scorer
# ────────────────────────────────────────────────────────────────────────

SCORING_PROMPT = """You are evaluating a Telegram bot response. The bot is an AI life assistant
that handles finance, tasks, calendar, email, shopping, research, and more.
The bot primarily communicates in Russian.

User message: "{user_message}"
Expected intent: {expected_intent}
Bot response: "{bot_response}"

Score the bot response on these dimensions (1=terrible, 5=excellent):

1. relevance: Does the response address what the user asked?
2. correctness: Is the action/information accurate for the intent?
3. tone: Is the tone friendly, concise, and appropriate (not robotic or chirpy)?
4. completeness: Does it fully handle the request without missing parts?

Return JSON with keys: relevance, correctness, tone, completeness (ints), reasoning (str)."""

_COMPARE_STOPWORDS = {
    "и",
    "или",
    "что",
    "это",
    "как",
    "для",
    "при",
    "без",
    "под",
    "над",
    "про",
    "мне",
    "мой",
    "моя",
    "моё",
    "мои",
    "твой",
    "твоя",
    "его",
    "ее",
    "её",
    "она",
    "они",
    "если",
    "чтобы",
    "нужно",
    "надо",
    "было",
    "будет",
    "уже",
    "ещё",
    "очень",
    "просто",
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "your",
    "have",
    "will",
    "just",
    "into",
    "about",
}


async def score_response(
    user_message: str,
    bot_response: str,
    expected_intent: str,
) -> LLMScores | None:
    """Use Gemini Flash to score a bot response on 4 quality dimensions."""
    try:
        from google.genai import types

        from src.core.llm.clients import google_client

        client = google_client()
        prompt = SCORING_PROMPT.format(
            user_message=user_message,
            expected_intent=expected_intent,
            bot_response=bot_response[:1000],
        )

        resp = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=256,
            ),
        )
        raw = resp.text
        if not raw:
            return None
        data = json.loads(raw)
        avg = (data["relevance"] + data["correctness"] + data["tone"] + data["completeness"]) / 4
        return LLMScores(
            relevance=data["relevance"],
            correctness=data["correctness"],
            tone=data["tone"],
            completeness=data["completeness"],
            reasoning=data.get("reasoning", ""),
            average=round(avg, 1),
        )
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def parse_expected_intent(description: str) -> str:
    """Extract expected intent from 'add_expense — desc' format."""
    return description.split("—")[0].strip().split(" ")[0].strip()


def _normalize_compare_text(text: str) -> str:
    """Normalize text for deterministic response/reference comparison."""
    normalized = strip_html(text).lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_compare_terms(text: str) -> list[str]:
    """Extract semantically relevant tokens from a reference answer."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in _normalize_compare_text(text).split():
        if token.isdigit() or len(token) < 3 or token in _COMPARE_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


def evaluate_reference_response(
    expected_response: str,
    actual_response: str,
    *,
    min_coverage: float = 0.5,
) -> ReferenceRubric:
    """Compare an actual bot response against a reviewed golden response."""
    expected_normalized = _normalize_compare_text(expected_response)
    actual_normalized = _normalize_compare_text(actual_response)
    if not expected_normalized or not actual_normalized:
        return ReferenceRubric(
            coverage=0.0,
            overlap=0.0,
            matched_terms=[],
            missing_terms=[],
            verdict="missing_reference",
            passed=False,
        )

    expected_terms = _extract_compare_terms(expected_response)
    actual_terms = set(_extract_compare_terms(actual_response))
    substring_match = expected_normalized in actual_normalized

    if not expected_terms:
        passed = substring_match or expected_normalized == actual_normalized
        verdict = "strong_match" if passed else "no_match"
        coverage = 1.0 if passed else 0.0
        return ReferenceRubric(
            coverage=coverage,
            overlap=coverage,
            matched_terms=[],
            missing_terms=[] if passed else [expected_normalized],
            verdict=verdict,
            passed=passed,
        )

    matched_terms = [term for term in expected_terms if term in actual_terms]
    missing_terms = [term for term in expected_terms if term not in actual_terms]
    coverage = len(matched_terms) / len(expected_terms)
    union_terms = set(expected_terms) | actual_terms
    overlap = len(set(matched_terms)) / len(union_terms) if union_terms else 0.0

    min_term_matches = 1 if len(expected_terms) <= 2 else 2
    passed = substring_match or (
        coverage >= min_coverage and len(matched_terms) >= min_term_matches
    )
    if substring_match or coverage >= 0.8:
        verdict = "strong_match"
    elif passed:
        verdict = "partial_match"
    elif matched_terms:
        verdict = "weak_match"
    else:
        verdict = "no_match"

    return ReferenceRubric(
        coverage=round(coverage, 2),
        overlap=round(overlap, 2),
        matched_terms=matched_terms,
        missing_terms=missing_terms,
        verdict=verdict,
        passed=passed,
    )


def apply_reference_rubric(
    result: TestResult,
    *,
    min_coverage: float = 0.5,
) -> None:
    """Attach reference comparison results and fail golden cases on mismatch."""
    if not result.expected_response_text or not result.response_text:
        return

    rubric = evaluate_reference_response(
        result.expected_response_text,
        result.response_text,
        min_coverage=min_coverage,
    )
    result.reference_rubric = rubric
    if result.source == "golden" and result.status == "pass" and not rubric.passed:
        result.status = "error"
        result.error = (
            f"Reference mismatch ({rubric.verdict}, coverage={rubric.coverage:.2f})"
        )


def _score_color(val: int) -> str:
    if val >= 4:
        return f"{GREEN}{val}{RESET}"
    if val >= 3:
        return f"{YELLOW}{val}{RESET}"
    return f"{RED}{val}{RESET}"


def strip_html(text: str) -> str:
    """Remove HTML tags for console display."""
    return re.sub(r"<[^>]+>", "", text)


# ────────────────────────────────────────────────────────────────────────
# Console output
# ────────────────────────────────────────────────────────────────────────


def print_header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"  {BOLD}{text}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")


def print_test_result(result: TestResult) -> None:
    """Print a single test result with colors and scores."""
    if result.status == "pass":
        icon, color = "+", GREEN
    elif result.status == "timeout":
        icon, color = "x", RED
    else:
        icon, color = "!", YELLOW

    print(f"\n  {color}{BOLD}[{icon}]{RESET} {result.description}")
    print(f"      {DIM}Sent:{RESET} {result.message_sent}")

    if result.has_response and result.response_text:
        clean = strip_html(result.response_text)
        truncated = clean[:150] + "..." if len(clean) > 150 else clean
        print(f"      {DIM}Response:{RESET} {truncated}")
        print(
            f"      {DIM}Time:{RESET} {result.response_time_ms}ms  "
            f"{DIM}Length:{RESET} {result.response_length} chars"
        )

        extras = []
        if result.has_buttons:
            extras.append("buttons")
        if result.has_chart:
            extras.append("chart")
        if result.has_document:
            extras.append("document")
        if extras:
            print(f"      {DIM}Extras:{RESET} {', '.join(extras)}")

        if result.llm_scores:
            s = result.llm_scores
            print(
                f"      {DIM}Scores:{RESET} "
                f"rel={_score_color(s.relevance)} "
                f"cor={_score_color(s.correctness)} "
                f"tone={_score_color(s.tone)} "
                f"comp={_score_color(s.completeness)} "
                f"{DIM}avg={s.average:.1f}{RESET}"
            )
        if result.reference_rubric:
            rubric = result.reference_rubric
            coverage_pct = int(rubric.coverage * 100)
            overlap_pct = int(rubric.overlap * 100)
            verdict_color = GREEN if rubric.passed else YELLOW if rubric.matched_terms else RED
            print(
                f"      {DIM}Reference:{RESET} "
                f"{verdict_color}{rubric.verdict}{RESET} "
                f"{DIM}coverage={coverage_pct}% overlap={overlap_pct}%{RESET}"
            )
            if rubric.missing_terms:
                missing = ", ".join(rubric.missing_terms[:5])
                print(f"      {DIM}Missing:{RESET} {missing}")
        if result.error and result.status == "error":
            print(f"      {RED}Error: {result.error}{RESET}")
    elif result.error:
        print(f"      {RED}Error: {result.error}{RESET}")
    else:
        print(f"      {RED}No response{RESET}")


def print_summary(stats: AggregateStats, results: list[TestResult]) -> None:
    """Print the final summary table."""
    print_header("RESULTS SUMMARY")

    # Pass rate
    pct = stats.pass_rate * 100
    color = GREEN if pct >= 80 else YELLOW if pct >= 50 else RED
    print(f"\n  {BOLD}Pass rate:{RESET} {color}{stats.passed}/{stats.total} ({pct:.0f}%){RESET}")
    if stats.timed_out:
        print(f"  {RED}Timed out:{RESET} {stats.timed_out}")
    if stats.errors:
        print(f"  {YELLOW}Errors:{RESET} {stats.errors}")
    if stats.reference_evaluated:
        print(
            f"  {BOLD}Reference checks:{RESET} "
            f"{stats.reference_passed}/{stats.reference_evaluated} passed "
            f"({stats.avg_reference_coverage:.0%} avg coverage)"
        )

    # Timing
    responded = [r for r in results if r.has_response and r.response_time_ms > 0]
    if responded:
        times = [r.response_time_ms for r in responded]
        print(
            f"\n  {BOLD}Response time:{RESET} "
            f"avg={stats.avg_response_time_ms:.0f}ms  "
            f"min={min(times)}ms  "
            f"max={max(times)}ms"
        )

    # Per-category breakdown
    categories: dict[str, dict[str, int]] = {}
    for r in results:
        cat = categories.setdefault(r.category, {"total": 0, "passed": 0})
        cat["total"] += 1
        if r.status == "pass":
            cat["passed"] += 1

    print(f"\n  {BOLD}By category:{RESET}")
    for cat, data in categories.items():
        p = data["passed"] / data["total"] * 100 if data["total"] else 0
        c = GREEN if p >= 80 else YELLOW if p >= 50 else RED
        print(f"    {cat:<12} {c}{data['passed']}/{data['total']} ({p:.0f}%){RESET}")

    # Score averages
    scored = [r for r in results if r.llm_scores]
    if scored:
        print(f"\n  {BOLD}Quality scores (avg):{RESET}")
        print(
            f"    Relevance:    {_score_color(round(stats.avg_relevance))}"
            f" ({stats.avg_relevance:.1f})"
        )
        print(
            f"    Correctness:  {_score_color(round(stats.avg_correctness))}"
            f" ({stats.avg_correctness:.1f})"
        )
        print(
            f"    Tone:         {_score_color(round(stats.avg_tone))}"
            f" ({stats.avg_tone:.1f})"
        )
        print(
            f"    Completeness: {_score_color(round(stats.avg_completeness))}"
            f" ({stats.avg_completeness:.1f})"
        )
        print(
            f"    {BOLD}Overall:      {_score_color(round(stats.avg_overall))}"
            f" ({stats.avg_overall:.1f}){RESET}"
        )

        # Bottom 3 worst scores
        worst = sorted(scored, key=lambda r: r.llm_scores.average)[:3]
        if worst and worst[0].llm_scores.average < 4.0:
            print(f"\n  {BOLD}Lowest scores:{RESET}")
            for r in worst:
                s = r.llm_scores
                print(
                    f"    {RED}{s.average:.1f}{RESET} {r.description}"
                    f" — {DIM}{s.reasoning[:80]}{RESET}"
                )

    if stats.reference_evaluated:
        print(f"\n  {BOLD}Golden reference rubric:{RESET}")
        print(f"    Coverage:    {stats.avg_reference_coverage:.2f}")
        print(f"    Overlap:     {stats.avg_reference_overlap:.2f}")

    print()


# ────────────────────────────────────────────────────────────────────────
# Stats computation
# ────────────────────────────────────────────────────────────────────────


def compute_stats(results: list[TestResult]) -> AggregateStats:
    total = len(results)
    if total == 0:
        return AggregateStats()

    passed = sum(1 for r in results if r.status == "pass")
    timed_out = sum(1 for r in results if r.status == "timeout")
    errors = sum(1 for r in results if r.status == "error")

    responded = [r for r in results if r.has_response and r.response_time_ms > 0]
    avg_time = sum(r.response_time_ms for r in responded) / len(responded) if responded else 0

    scored = [r for r in results if r.llm_scores]
    avg_rel = sum(r.llm_scores.relevance for r in scored) / len(scored) if scored else 0
    avg_cor = sum(r.llm_scores.correctness for r in scored) / len(scored) if scored else 0
    avg_tone = sum(r.llm_scores.tone for r in scored) / len(scored) if scored else 0
    avg_comp = sum(r.llm_scores.completeness for r in scored) / len(scored) if scored else 0
    avg_overall = sum(r.llm_scores.average for r in scored) / len(scored) if scored else 0
    reference_checked = [r for r in results if r.reference_rubric]
    reference_passed = sum(1 for r in reference_checked if r.reference_rubric.passed)
    avg_reference_coverage = (
        sum(r.reference_rubric.coverage for r in reference_checked) / len(reference_checked)
        if reference_checked
        else 0
    )
    avg_reference_overlap = (
        sum(r.reference_rubric.overlap for r in reference_checked) / len(reference_checked)
        if reference_checked
        else 0
    )

    return AggregateStats(
        total=total,
        passed=passed,
        timed_out=timed_out,
        errors=errors,
        pass_rate=round(passed / total, 3),
        avg_response_time_ms=round(avg_time, 0),
        avg_relevance=round(avg_rel, 1),
        avg_correctness=round(avg_cor, 1),
        avg_tone=round(avg_tone, 1),
        avg_completeness=round(avg_comp, 1),
        avg_overall=round(avg_overall, 1),
        reference_evaluated=len(reference_checked),
        reference_passed=reference_passed,
        avg_reference_coverage=round(avg_reference_coverage, 2),
        avg_reference_overlap=round(avg_reference_overlap, 2),
    )


# ────────────────────────────────────────────────────────────────────────
# JSON persistence
# ────────────────────────────────────────────────────────────────────────


def save_results(report: TestRunReport) -> Path:
    """Save test run results as JSON to scripts/test_results/."""
    results_dir = Path(__file__).parent / "test_results"
    results_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = results_dir / f"test_run_{ts}.json"
    filepath.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return filepath


def infer_ops_base_url() -> str:
    """Infer the operator base URL from env when replay results should be uploaded."""
    explicit_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if explicit_base_url:
        return explicit_base_url.rstrip("/")

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if webhook_url:
        return webhook_url.rsplit("/", 1)[0].rstrip("/")

    return "http://localhost:8000"


def build_ops_headers(health_secret: str) -> dict[str, str]:
    """Build auth headers for protected ops endpoints."""
    if not health_secret:
        return {}
    return {"Authorization": f"Bearer {health_secret}"}


def _derive_golden_failure_outcome(result: TestResult) -> tuple[str, str]:
    """Map a failed golden replay result to analytics outcome and review label."""
    if result.status == "timeout":
        outcome = "no_reply"
    elif result.reference_rubric and not result.reference_rubric.passed:
        outcome = "wrong_route"
    else:
        outcome = "error"

    lowered_category = result.category.lower()
    if "memory" in lowered_category:
        review_label = "memory_failure"
    elif outcome == "wrong_route":
        review_label = "wrong_route"
    else:
        review_label = "tool_failure"
    return outcome, review_label


def build_golden_mismatch_candidates(
    results: list[TestResult],
    *,
    mode_key: str,
    run_timestamp: str,
) -> list[tuple[int, dict[str, object]]]:
    """Build review-queue payloads for failed golden replay results."""
    candidates: list[tuple[int, dict[str, object]]] = []
    run_stamp = re.sub(r"[^0-9A-Za-z]+", "", run_timestamp) or str(int(time.time()))

    for index, result in enumerate(results):
        if result.source != "golden" or result.status == "pass":
            continue

        outcome, review_label = _derive_golden_failure_outcome(result)
        source_trace_key = result.trace_key
        digest = hashlib.sha1(
            f"{source_trace_key or 'no-source'}:{result.message_sent}:{index}:{run_stamp}".encode()
        ).hexdigest()[:12]
        replay_trace_key = f"golden-replay:{mode_key}:{run_stamp}:{digest}"
        tags = [
            "golden_replay",
            f"scenario:{result.category}",
            f"mode:{mode_key}",
        ]
        if result.reference_rubric and not result.reference_rubric.passed:
            tags.append("reference_mismatch")
        if result.status == "timeout":
            tags.append("timeout")

        response_preview = result.response_text or result.error or ""
        payload = {
            "trace_key": replay_trace_key,
            "channel": "telegram",
            "chat_id": "",
            "user_id": "",
            "message_id": "",
            "intent": result.expected_intent,
            "outcome": outcome,
            "review_label": review_label,
            "tags": tags,
            "message_preview": result.message_sent[:500],
            "response_preview": response_preview[:1000],
            "response_has_text": bool(result.response_text),
            "response_length": len(response_preview),
            "queued_for_review": True,
            "source": "test_bot_live_golden_replay",
            "metadata": {
                "run_timestamp": run_timestamp,
                "mode": mode_key,
                "category": result.category,
                "description": result.description,
                "status": result.status,
                "error": result.error,
                "source_trace_key": source_trace_key,
                "expected_response_text": result.expected_response_text,
                "reference_rubric": (
                    result.reference_rubric.model_dump() if result.reference_rubric else None
                ),
            },
        }
        candidates.append((index, payload))

    return candidates


async def enqueue_golden_review_candidates(
    candidates: list[tuple[int, dict[str, object]]],
    *,
    mode_key: str,
    ops_base_url: str,
    health_secret: str,
) -> list[tuple[int, bool, str | None, str | None]]:
    """Store golden replay failures back into the analytics review queue."""
    if not candidates:
        return []

    results: list[tuple[int, bool, str | None, str | None]] = []
    if mode_key == "direct":
        from src.core.conversation_analytics import ingest_review_trace

        for index, payload in candidates:
            try:
                stored = await ingest_review_trace(dict(payload))
                results.append((index, True, str(stored.get("trace_key") or ""), None))
            except Exception as exc:
                results.append((index, False, str(payload.get("trace_key") or ""), str(exc)))
        return results

    headers = build_ops_headers(health_secret)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=headers) as client:
        for index, payload in candidates:
            trace_key = str(payload.get("trace_key") or "")
            try:
                response = await client.post(
                    urljoin(f"{ops_base_url.rstrip('/')}/", "ops/analytics/review-candidates"),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                stored_trace = data.get("trace") or {}
                results.append((index, True, str(stored_trace.get("trace_key") or trace_key), None))
            except Exception as exc:
                results.append((index, False, trace_key, str(exc)))
    return results


# ────────────────────────────────────────────────────────────────────────
# Direct mode: call internal handler
# ────────────────────────────────────────────────────────────────────────


class _FakeRedis:
    """Minimal fake Redis for local testing (no real Redis required)."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._data[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if self._data.pop(k, None) is not None:
                count += 1
            if self._lists.pop(k, None) is not None:
                count += 1
        return count

    async def incr(self, key: str) -> int:
        val = int(self._data.get(key, "0")) + 1
        self._data[key] = str(val)
        return val

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return -1

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self._data or k in self._lists)

    async def keys(self, pattern: str = "*") -> list[str]:
        return list(self._data.keys())

    # List operations (for sliding window)
    async def rpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    async def lpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        lst = self._lists.get(key, [])
        if stop == -1:
            return lst[start:]
        return lst[start : stop + 1]

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        lst = self._lists.get(key, [])
        if stop == -1:
            self._lists[key] = lst[start:]
        else:
            self._lists[key] = lst[start : stop + 1]
        return True

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    """Minimal fake Redis pipeline."""

    def __init__(self, redis: _FakeRedis):
        self._redis = redis
        self._commands: list[tuple] = []

    def get(self, key: str):
        self._commands.append(("get", key))
        return self

    def set(self, key: str, value: str, **kwargs):
        self._commands.append(("set", key, value))
        return self

    def setex(self, key: str, ttl: int, value: str):
        self._commands.append(("setex", key, ttl, value))
        return self

    def delete(self, *keys: str):
        self._commands.append(("delete", *keys))
        return self

    def expire(self, key: str, ttl: int):
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results = []
        for cmd in self._commands:
            if cmd[0] == "get":
                results.append(self._redis._data.get(cmd[1]))
            elif cmd[0] == "set":
                self._redis._data[cmd[1]] = cmd[2]
                results.append(True)
            elif cmd[0] == "setex":
                self._redis._data[cmd[1]] = cmd[3]
                results.append(True)
            elif cmd[0] == "delete":
                deleted = sum(
                    1 for k in cmd[1:] if self._redis._data.pop(k, None) is not None
                )
                results.append(deleted)
            elif cmd[0] == "expire":
                results.append(True)
            else:
                results.append(None)
        self._commands.clear()
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def run_direct_test(
    chat_id: int,
    categories: list[str],
    *,
    scenario_map: dict[str, list[ScenarioCase]],
    golden_min_coverage: float = 0.5,
    skip_scoring: bool = False,
    delay: float = 2.0,
) -> list[TestResult]:
    """Call internal handle_message() directly and capture OutgoingMessage.

    Uses fake Redis for local testing. Connects to production Supabase for context.
    """
    # Patch Redis BEFORE importing handler
    import src.core.db as db_module

    fake_redis = _FakeRedis()
    db_module.redis = fake_redis

    # Also patch in router module (it imports redis at module level)
    import src.core.router as router_module

    if hasattr(router_module, "redis"):
        router_module.redis = fake_redis

    from api.main import build_session_context
    from src.core.router import handle_message
    from src.gateway.types import IncomingMessage, MessageType

    # Build session context once
    print(f"\n  {DIM}Building session context for telegram_id={chat_id}...{RESET}")
    context = await build_session_context(str(chat_id))
    if not context:
        print(f"  {RED}ERROR: User with telegram_id={chat_id} not found in database.{RESET}")
        print(f"  {DIM}Make sure the user has interacted with the bot at least once.{RESET}")
        return []
    print(f"  {GREEN}Context loaded: user_id={context.user_id}, lang={context.language}{RESET}")

    results: list[TestResult] = []

    for category in categories:
        scenarios = scenario_map.get(category, [])
        if not scenarios:
            print(f"{YELLOW}Unknown category: {category}{RESET}")
            continue

        print_header(f"Testing: {category.upper()}")

        for scenario in scenarios:
            result = TestResult(
                category=category,
                description=scenario.description,
                expected_intent=scenario.expected_intent,
                message_sent=scenario.text,
                expected_response_text=scenario.expected_response,
                source=scenario.source,
                trace_key=scenario.trace_key,
            )

            try:
                msg = IncomingMessage(
                    id=f"test-{int(time.time())}",
                    user_id=str(chat_id),
                    chat_id=str(chat_id),
                    type=MessageType.text,
                    text=scenario.text,
                    channel="telegram",
                    language="ru",
                )

                t0 = time.perf_counter()
                response = await handle_message(msg, context)
                t1 = time.perf_counter()

                result.response_time_ms = int((t1 - t0) * 1000)
                result.response_text = response.text
                result.response_length = len(response.text) if response.text else 0
                result.has_response = bool(response.text)
                result.has_buttons = bool(response.buttons)
                result.has_chart = bool(response.chart_url)
                result.has_document = bool(response.document)
                result.status = "pass" if response.text else "error"
                apply_reference_rubric(result, min_coverage=golden_min_coverage)

                # LLM quality scoring
                if result.has_response and not skip_scoring:
                    result.llm_scores = await score_response(
                        scenario.text,
                        response.text,
                        scenario.expected_intent,
                    )

            except Exception as e:
                result.status = "error"
                result.error = str(e)[:200]

            results.append(result)
            print_test_result(result)

            await asyncio.sleep(delay)

    return results


# ────────────────────────────────────────────────────────────────────────
# Webhook simulation mode
# ────────────────────────────────────────────────────────────────────────


async def run_webhook_test(
    chat_id: int,
    categories: list[str],
    *,
    scenario_map: dict[str, list[ScenarioCase]],
    delay: float = 2.0,
) -> list[TestResult]:
    """Send simulated webhook payloads to Railway (no response capture)."""
    results: list[TestResult] = []

    async with httpx.AsyncClient() as client:
        for category in categories:
            scenarios = scenario_map.get(category, [])
            if not scenarios:
                continue

            print_header(f"Webhook Simulation: {category.upper()}")

            for scenario in scenarios:
                result = TestResult(
                    category=category,
                    description=scenario.description,
                    expected_intent=scenario.expected_intent,
                    message_sent=scenario.text,
                    expected_response_text=scenario.expected_response,
                    source=scenario.source,
                    trace_key=scenario.trace_key,
                )

                t0 = time.perf_counter()
                try:
                    status_code = await send_webhook_payload(client, chat_id, scenario.text)
                    t1 = time.perf_counter()
                    result.response_time_ms = int((t1 - t0) * 1000)

                    if status_code == 200:
                        result.status = "pass"
                        result.has_response = True
                        result.response_text = f"HTTP 200 OK ({result.response_time_ms}ms)"
                    else:
                        result.status = "error"
                        result.error = f"HTTP {status_code}"
                except Exception as e:
                    result.status = "error"
                    result.error = str(e)

                results.append(result)

                icon = f"{GREEN}+{RESET}" if result.status == "pass" else f"{RED}x{RESET}"
                print(
                    f"  [{icon}] {scenario.description}  "
                    f"{DIM}{result.response_time_ms}ms{RESET}"
                )

                await asyncio.sleep(delay)

    return results


# ────────────────────────────────────────────────────────────────────────
# Telegram E2E mode: real messages via Telethon (MTProto)
# ────────────────────────────────────────────────────────────────────────


async def _get_bot_username() -> str | None:
    """Resolve bot username from token via Bot API getMe."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
            data = resp.json()
            return data["result"]["username"]
    except Exception:
        return None


async def run_telegram_test(
    chat_id: int,
    categories: list[str],
    *,
    scenario_map: dict[str, list[ScenarioCase]],
    golden_min_coverage: float = 0.5,
    skip_scoring: bool = False,
    delay: float = 3.0,
    timeout: int = 60,
) -> list[TestResult]:
    """Send real messages to bot via Telethon and read actual replies from Telegram.

    This is a true E2E test: message goes through Telegram servers → webhook →
    bot processes → sendMessage → we read the reply as a user.

    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in .env.
    First run will prompt for phone number and verification code.
    Session is saved to scripts/test_telegram.session for reuse.
    """
    from telethon import TelegramClient

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        print(f"\n  {RED}ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH required for telegram mode")
        print("  Get them from https://my.telegram.org/apps")
        print(f"  Add to .env:{RESET}")
        print("    TELEGRAM_API_ID=12345678")
        print("    TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890")
        return []

    # Resolve bot username
    bot_username = await _get_bot_username()
    if not bot_username:
        print(f"  {RED}ERROR: Could not resolve bot username from token{RESET}")
        return []
    print(f"  {GREEN}Bot: @{bot_username}{RESET}")

    # Create Telethon client with session file
    session_path = str(Path(__file__).parent / "test_telegram")
    session_file = Path(session_path + ".session")

    if not session_file.exists():
        print(f"\n  {RED}ERROR: No Telethon session found at {session_file}{RESET}")
        print(f"  Run first: {BOLD}python scripts/telegram_auth.py{RESET}")
        print(f"  {DIM}This will prompt for phone + auth code (one-time only).{RESET}")
        return []

    client = TelegramClient(session_path, int(api_id), api_hash)

    print(f"\n  {DIM}Connecting to Telegram...{RESET}")
    await client.connect()
    if not await client.is_user_authorized():
        print(f"  {RED}ERROR: Session expired. Re-run: python scripts/telegram_auth.py{RESET}")
        await client.disconnect()
        return []
    me = await client.get_me()
    print(f"  {GREEN}Logged in as: {me.first_name} (id={me.id}){RESET}")

    # Resolve bot entity
    bot_entity = await client.get_entity(f"@{bot_username}")
    print(f"  {GREEN}Bot resolved: @{bot_username} (id={bot_entity.id}){RESET}")

    results: list[TestResult] = []

    # Track the last bot message ID we've seen to avoid capturing stale replies
    last_seen_bot_id = 0
    # Seed with the latest bot message currently in chat
    recent = await client.get_messages(bot_entity, limit=1)
    if recent:
        last_seen_bot_id = recent[0].id

    for category in categories:
        scenarios = scenario_map.get(category, [])
        if not scenarios:
            print(f"{YELLOW}Unknown category: {category}{RESET}")
            continue

        print_header(f"Testing: {category.upper()}")

        for scenario in scenarios:
            result = TestResult(
                category=category,
                description=scenario.description,
                expected_intent=scenario.expected_intent,
                message_sent=scenario.text,
                expected_response_text=scenario.expected_response,
                source=scenario.source,
                trace_key=scenario.trace_key,
            )

            try:
                # Drain any late replies from previous test before sending
                await asyncio.sleep(0.5)
                drain = await client.get_messages(bot_entity, limit=5, min_id=last_seen_bot_id)
                for m in drain:
                    if not m.out and m.id > last_seen_bot_id:
                        last_seen_bot_id = m.id

                # Send message to bot
                t0 = time.perf_counter()
                sent = await client.send_message(bot_entity, scenario.text)

                # The anchor: only accept bot messages with id > both sent_id AND last_seen
                anchor_id = max(sent.id, last_seen_bot_id)

                # Wait for bot's reply
                reply = None
                poll_interval = 1.5
                max_polls = int(timeout / poll_interval)

                for _ in range(max_polls):
                    await asyncio.sleep(poll_interval)
                    messages = await client.get_messages(
                        bot_entity, limit=5, min_id=anchor_id
                    )
                    # Only messages FROM the bot (not our own), after anchor
                    bot_msgs = [m for m in messages if not m.out and m.id > anchor_id]
                    if bot_msgs:
                        reply = bot_msgs[0]
                        # Update last_seen to the latest bot message
                        last_seen_bot_id = max(m.id for m in bot_msgs)
                        break

                t1 = time.perf_counter()

                if reply:
                    result.response_time_ms = int((t1 - t0) * 1000)
                    result.response_text = reply.text or reply.message or ""
                    result.response_length = len(result.response_text)
                    result.has_response = bool(result.response_text)
                    result.has_buttons = bool(reply.buttons)
                    result.has_document = bool(reply.document)
                    result.has_chart = bool(reply.photo)
                    result.status = "pass" if result.has_response else "error"

                    # Check if bot sent multiple messages (collect all)
                    if len(bot_msgs) > 1:
                        extra_texts = []
                        for m in bot_msgs[1:]:
                            if m.text:
                                extra_texts.append(m.text)
                        if extra_texts:
                            result.response_text += "\n---\n" + "\n---\n".join(extra_texts)
                            result.response_length = len(result.response_text)
                    apply_reference_rubric(result, min_coverage=golden_min_coverage)
                else:
                    result.status = "timeout"
                    result.response_time_ms = int((t1 - t0) * 1000)
                    result.error = f"No reply within {timeout}s"
                    # Still update last_seen in case late reply arrives later
                    last_seen_bot_id = max(last_seen_bot_id, sent.id)

                # LLM quality scoring
                if result.has_response and not skip_scoring:
                    result.llm_scores = await score_response(
                        scenario.text,
                        result.response_text,
                        scenario.expected_intent,
                    )

            except Exception as e:
                result.status = "error"
                result.error = str(e)[:200]

            results.append(result)
            print_test_result(result)

            await asyncio.sleep(delay)

    await client.disconnect()
    return results


# ────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Live bot testing harness with response analysis"
    )
    parser.add_argument(
        "--chat-id", type=int, default=7314014306, help="Telegram chat_id (default: 7314014306)"
    )
    parser.add_argument(
        "--test",
        nargs="+",
        default=None,
        help="Categories to test (default: all built-in or all from --golden-file)",
    )
    parser.add_argument(
        "--golden-file",
        help="Replay scenarios from golden-dialogue JSONL export instead of built-in cases",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Telegram E2E mode — send real messages via Telethon, read bot replies",
    )
    parser.add_argument(
        "--webhook-sim",
        action="store_true",
        help="Webhook simulation mode — POST to Railway, no response capture",
    )
    parser.add_argument("--list", action="store_true", help="List available test categories")
    parser.add_argument("--no-scoring", action="store_true", help="Skip LLM quality scoring")
    parser.add_argument("--no-save", action="store_true", help="Skip saving results to JSON")
    parser.add_argument(
        "--delay", type=float, default=2.0, help="Seconds between test cases (default: 2.0)"
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="Max wait for bot reply in seconds (default: 60)"
    )
    parser.add_argument(
        "--golden-min-coverage",
        type=float,
        default=0.5,
        help="Minimum keyword coverage for golden reference checks (default: 0.5)",
    )
    parser.add_argument(
        "--enqueue-golden-mismatches",
        action="store_true",
        help="Push failed golden replay cases back into the analytics review queue",
    )
    parser.add_argument(
        "--ops-base-url",
        default=infer_ops_base_url(),
        help="Base URL for ops analytics ingestion (default: inferred from env)",
    )
    parser.add_argument(
        "--health-secret",
        default=os.getenv("HEALTH_SECRET", ""),
        help="Bearer token for protected ops analytics endpoints",
    )

    args = parser.parse_args()

    try:
        selected_categories, scenario_map = resolve_scenario_map(
            categories=args.test,
            golden_file=args.golden_file,
        )
    except ValueError as exc:
        print(f"{RED}ERROR: {exc}{RESET}")
        sys.exit(1)

    if args.list:
        total = 0
        for cat, scenarios in scenario_map.items():
            print(f"\n{BOLD}{cat}{RESET} ({len(scenarios)}):")
            for scenario in scenarios:
                print(
                    f"  {DIM}-{RESET} {scenario.description}: "
                    f"{CYAN}{scenario.text}{RESET}"
                )
                total += 1
        print(f"\n{BOLD}Total: {total} test scenarios{RESET}")
        return

    if not BOT_TOKEN:
        print(f"{RED}ERROR: TELEGRAM_BOT_TOKEN not found in .env{RESET}")
        sys.exit(1)

    # Determine mode
    if args.telegram:
        mode = "telegram (Telethon E2E)"
        mode_key = "telegram"
    elif args.webhook_sim:
        mode = "webhook simulation"
        mode_key = "webhook"
    else:
        mode = "direct (internal handler)"
        mode_key = "direct"

    # Header
    print_header("Bot Live Testing Harness")
    scoring = "OFF" if args.no_scoring else "Gemini Flash"
    print(f"  Token:      {BOT_TOKEN[:10]}...{BOT_TOKEN[-4:]}")
    print(f"  Chat ID:    {args.chat_id}")
    print(f"  Mode:       {mode}")
    print(f"  Scoring:    {scoring}")
    print(f"  Categories: {', '.join(selected_categories)}")
    if args.golden_file:
        print(f"  Scenario source: {args.golden_file}")
    print(f"  Delay:      {args.delay}s")
    if args.telegram:
        print(f"  Timeout:    {args.timeout}s")

    # Run tests
    run_start = time.perf_counter()

    if args.telegram:
        results = asyncio.run(
            run_telegram_test(
                args.chat_id,
                selected_categories,
                scenario_map=scenario_map,
                golden_min_coverage=max(0.1, min(args.golden_min_coverage, 1.0)),
                skip_scoring=args.no_scoring,
                delay=args.delay,
                timeout=args.timeout,
            )
        )
    elif args.webhook_sim:
        results = asyncio.run(
            run_webhook_test(
                args.chat_id,
                selected_categories,
                scenario_map=scenario_map,
                delay=args.delay,
            )
        )
    else:
        results = asyncio.run(
            run_direct_test(
                args.chat_id,
                selected_categories,
                scenario_map=scenario_map,
                golden_min_coverage=max(0.1, min(args.golden_min_coverage, 1.0)),
                skip_scoring=args.no_scoring,
                delay=args.delay,
            )
        )

    run_duration = time.perf_counter() - run_start

    if not results:
        print(f"\n{RED}No results collected.{RESET}")
        return

    # Compute stats and print summary
    stats = compute_stats(results)
    print_summary(stats, results)

    # Build report
    report = TestRunReport(
        metadata=RunMetadata(
            timestamp=datetime.now().isoformat(),
            chat_id=args.chat_id,
            mode=mode_key,
            categories=selected_categories,
            total_tests=len(results),
            total_time_seconds=round(run_duration, 1),
            bot_token_hint=f"{BOT_TOKEN[:10]}...{BOT_TOKEN[-4:]}",
        ),
        results=results,
        stats=stats,
    )

    if args.enqueue_golden_mismatches:
        candidates = build_golden_mismatch_candidates(
            results,
            mode_key=mode_key,
            run_timestamp=report.metadata.timestamp,
        )
        if candidates:
            enqueue_results = asyncio.run(
                enqueue_golden_review_candidates(
                    candidates,
                    mode_key=mode_key,
                    ops_base_url=args.ops_base_url,
                    health_secret=args.health_secret,
                )
            )
            enqueued = 0
            failed = 0
            for index, success, trace_key, error in enqueue_results:
                results[index].review_candidate_trace_key = trace_key
                results[index].review_candidate_enqueued = success
                results[index].review_candidate_error = error
                if success:
                    enqueued += 1
                else:
                    failed += 1
            print(
                f"  {BOLD}Golden mismatch enqueue:{RESET} "
                f"{GREEN}{enqueued} stored{RESET}, {YELLOW}{failed} failed{RESET}"
            )
        else:
            print(f"  {DIM}No failed golden replay cases to enqueue{RESET}")

    # Save
    if not args.no_save:
        filepath = save_results(report)
        print(f"  {GREEN}Results saved:{RESET} {filepath}")
    else:
        print(f"  {DIM}Results not saved (--no-save){RESET}")


if __name__ == "__main__":
    main()
