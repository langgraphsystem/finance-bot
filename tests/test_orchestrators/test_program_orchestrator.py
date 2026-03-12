"""Tests for ProgramOrchestrator — deep-agent code generation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.complexity_router import classify_complexity
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType


def _make_context(**kwargs):
    defaults = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "role": "owner",
        "language": "en",
        "currency": "USD",
        "business_type": None,
        "categories": [],
        "merchant_mappings": [],
    }
    defaults.update(kwargs)
    return SessionContext(**defaults)


def _make_message(text="write a python script"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


# ─────────────────────────── complexity router ───────────────────────────


def test_simple_request_not_complex():
    assert classify_complexity("write a hello world script", "generate_program") is False


def test_short_request_not_complex():
    assert classify_complexity("напиши калькулятор калорий", "generate_program") is False


def test_long_request_is_complex():
    long_msg = " ".join(["word"] * 85)
    assert classify_complexity(long_msg, "generate_program") is True


def test_multi_component_long_is_complex():
    msg = " ".join(["word"] * 45) + " и " + " ".join(["word"] * 5)
    assert classify_complexity(msg, "generate_program") is True


def test_architectural_keyword_is_complex():
    assert classify_complexity("create a full stack app", "generate_program") is True
    assert classify_complexity("архитектура микросервисов", "generate_program") is True
    assert classify_complexity("rest api with database", "generate_program") is True


def test_wrong_intent_never_complex():
    assert classify_complexity("полный налоговый отчёт", "tax_estimate") is False
    assert classify_complexity(" ".join(["word"] * 100), "draft_message") is False


# ─────────────────────────── orchestrator routing ──────────────────────────


async def test_simple_request_uses_skill_path():
    """Short request → ProgramOrchestrator delegates to GenerateProgramSkill."""
    from src.orchestrators.program import graph as program_graph
    from src.orchestrators.program.graph import ProgramOrchestrator

    orch = ProgramOrchestrator()
    ctx = _make_context()
    msg = _make_message("напиши калькулятор")

    mock_result = MagicMock()
    mock_result.response_text = "✅ calculator.py"
    mock_result.buttons = None

    original_cc = program_graph.classify_complexity
    program_graph.classify_complexity = lambda msg, intent: False
    try:
        with patch(
            "src.skills.generate_program.handler.skill"
        ) as mock_skill:
            mock_skill.execute = AsyncMock(return_value=mock_result)
            result = await orch.invoke("generate_program", msg, ctx, {})

        mock_skill.execute.assert_awaited_once()
        assert result.response_text == "✅ calculator.py"
    finally:
        program_graph.classify_complexity = original_cc


async def test_complex_request_uses_orchestrator():
    """Complex request → ProgramOrchestrator runs the LangGraph graph."""
    from src.orchestrators.program import graph as program_graph
    from src.orchestrators.program.graph import ProgramOrchestrator

    orch = ProgramOrchestrator()
    ctx = _make_context()
    msg = _make_message("create a full stack SaaS app with authentication and database")

    fake_graph_result = {
        "response_text": "✅ saas_app.py\n🌐 Open app",
        "_prog_id": "abc12345",
        "code": "# saas app",
        "filename": "saas_app.py",
    }

    original_cc = program_graph.classify_complexity
    program_graph.classify_complexity = lambda m, i: True
    try:
        with patch(
            "src.orchestrators.program.graph._get_program_graph"
        ) as mock_get_graph:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=fake_graph_result)
            mock_get_graph.return_value = mock_graph

            with patch("asyncio.create_task"):
                result = await orch.invoke("generate_program", msg, ctx, {})

        assert "saas_app.py" in result.response_text
        assert result.buttons is not None
    finally:
        program_graph.classify_complexity = original_cc


# ─────────────────────────── planner node ──────────────────────────────────


async def test_planner_node_extracts_language():
    """planner node extracts language and requirements from LLM response."""
    from src.orchestrators.program.nodes import planner
    from src.orchestrators.program.state import ProgramState

    state: ProgramState = {
        "message_text": "create a Python web scraper for product prices",
        "program_language": "",
    }

    planner_response = (
        "LANGUAGE: python\n"
        "ARCHITECTURE: Flask app with requests + BeautifulSoup\n"
        "REQUIREMENTS:\n"
        "- Parse product prices from HTML\n"
        "- Return JSON results\n"
    )

    with patch(
        "src.orchestrators.program.nodes.generate_text",
        new_callable=AsyncMock,
        return_value=planner_response,
    ):
        result = await planner(state)

    assert result["program_language"] == "python"
    assert "Parse product prices" in result["requirements"]


async def test_planner_node_fallback_language():
    """planner defaults to python when LLM returns no language."""
    from src.orchestrators.program.nodes import planner
    from src.orchestrators.program.state import ProgramState

    state: ProgramState = {"message_text": "make a utility", "program_language": ""}

    with patch(
        "src.orchestrators.program.nodes.generate_text",
        new_callable=AsyncMock,
        return_value="REQUIREMENTS:\n- Do something",
    ):
        result = await planner(state)

    assert result["program_language"] == "python"


# ─────────────────────────── revision loop ────────────────────────────────


def test_revision_loop_max_2():
    """route_after_review returns 'finalize' after 2 revisions even with error."""
    from src.orchestrators.program.nodes import route_after_review

    state_at_limit = {
        "exec_result": {"error": "SyntaxError: invalid syntax"},
        "revision_count": 2,
    }
    assert route_after_review(state_at_limit) == "finalize"


def test_revision_loop_triggers_on_error():
    """route_after_review returns 'generate_code' when error and under limit."""
    from src.orchestrators.program.nodes import route_after_review

    state = {
        "exec_result": {"error": "ModuleNotFoundError: No module named 'foo'"},
        "revision_count": 0,
    }
    assert route_after_review(state) == "generate_code"


def test_revision_loop_skips_timeout():
    """Timed-out sandbox does not trigger revision — go straight to finalize."""
    from src.orchestrators.program.nodes import route_after_review

    state = {
        "exec_result": {"error": "timeout", "timed_out": True},
        "revision_count": 0,
    }
    assert route_after_review(state) == "finalize"


def test_revision_loop_no_error_goes_to_finalize():
    """No error → finalize."""
    from src.orchestrators.program.nodes import route_after_review

    assert (
        route_after_review(
            {"exec_result": {"url": "http://localhost"}, "revision_count": 0}
        )
        == "finalize"
    )
    assert route_after_review({"exec_result": None, "revision_count": 0}) == "finalize"


# ─────────────────────────── DLQ on fatal error ───────────────────────────


async def test_dlq_on_fatal_error():
    """ProgramOrchestrator saves to DLQ on fatal graph exception."""
    from src.orchestrators.program import graph as program_graph
    from src.orchestrators.program.graph import ProgramOrchestrator

    orch = ProgramOrchestrator()
    ctx = _make_context()
    msg = _make_message("create a full application with auth and database and REST API")

    original_cc = program_graph.classify_complexity
    program_graph.classify_complexity = lambda m, i: True
    try:
        with patch(
            "src.orchestrators.program.graph._get_program_graph"
        ) as mock_get_graph:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("Fatal graph error"))
            mock_get_graph.return_value = mock_graph

            with patch(
                "src.orchestrators.program.graph.save_to_dlq",
                new_callable=AsyncMock,
            ) as mock_dlq:
                result = await orch.invoke("generate_program", msg, ctx, {})

        mock_dlq.assert_awaited_once()
        call_kwargs = mock_dlq.call_args
        assert call_kwargs.kwargs.get("graph_name") == "program" or call_kwargs.args[0] == "program"
        assert "Failed" in result.response_text
    finally:
        program_graph.classify_complexity = original_cc
