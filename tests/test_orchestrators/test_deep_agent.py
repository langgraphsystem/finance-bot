"""Tests for the Deep Agent orchestrator — graph construction, nodes, routing."""

import json
from unittest.mock import AsyncMock, patch

from src.core.deep_agent.classifier import (
    ComplexityLevel,
    classify_program_complexity,
    classify_tax_complexity,
)
from src.orchestrators.deep_agent.graph import build_deep_agent_graph
from src.orchestrators.deep_agent.nodes import (
    _parse_plan,
    _strip_fences,
    advance_step,
    route_after_fix,
    route_after_validate,
)
from src.orchestrators.deep_agent.state import DeepAgentState

# --- Classifier tests ---


class TestProgramClassifier:
    def test_simple_hello_world(self):
        assert classify_program_complexity("hello world script") == ComplexityLevel.simple

    def test_simple_calculator(self):
        assert classify_program_complexity("калькулятор калорий") == ComplexityLevel.simple

    def test_simple_converter(self):
        assert classify_program_complexity("temperature converter") == ComplexityLevel.simple

    def test_complex_crm_with_auth(self):
        assert (
            classify_program_complexity(
                "CRM system with authentication and user management dashboard"
            )
            == ComplexityLevel.complex
        )

    def test_complex_ecommerce(self):
        assert (
            classify_program_complexity("e-commerce marketplace with shopping cart and database")
            == ComplexityLevel.complex
        )

    def test_complex_fullstack(self):
        assert (
            classify_program_complexity("full-stack application with REST API and admin panel")
            == ComplexityLevel.complex
        )

    def test_complex_russian(self):
        assert (
            classify_program_complexity("интернет-магазин с авторизацией и базой данных")
            == ComplexityLevel.complex
        )

    def test_complex_long_description(self):
        desc = (
            "Build a project management tool with user roles, "
            "task assignment, Gantt chart, notifications, "
            "file uploads, comments, and reporting dashboard. "
            "Include authentication with OAuth, REST API endpoints, "
            "and a responsive frontend."
        )
        assert classify_program_complexity(desc) == ComplexityLevel.complex

    def test_simple_landing_page(self):
        assert classify_program_complexity("landing page") == ComplexityLevel.simple

    def test_ambiguous_defaults_to_simple(self):
        assert classify_program_complexity("some program") == ComplexityLevel.simple


class TestTaxClassifier:
    def test_simple_estimate(self):
        assert classify_tax_complexity("сколько налогов?") == ComplexityLevel.simple

    def test_simple_current_quarter(self):
        assert classify_tax_complexity("tax estimate this quarter") == ComplexityLevel.simple

    def test_complex_annual_report(self):
        assert (
            classify_tax_complexity("annual tax report with deduction analysis")
            == ComplexityLevel.complex
        )

    def test_complex_schedule_c(self):
        assert (
            classify_tax_complexity("detailed Schedule C self-employment tax planning")
            == ComplexityLevel.complex
        )

    def test_complex_year_comparison(self):
        assert (
            classify_tax_complexity("full tax report comparison all quarters with optimization")
            == ComplexityLevel.complex
        )

    def test_simple_quick(self):
        assert classify_tax_complexity("quick tax estimate") == ComplexityLevel.simple


# --- Plan parsing tests ---


class TestParsePlan:
    def test_parse_json_array(self):
        raw = '["Step 1: Setup Flask", "Step 2: Add routes", "Step 3: Tests"]'
        steps = _parse_plan(raw)
        assert len(steps) == 3
        assert "Setup Flask" in steps[0]

    def test_parse_numbered_list(self):
        raw = "1. Setup Flask app\n2. Add database\n3. Add auth\n4. Deploy"
        steps = _parse_plan(raw)
        assert len(steps) == 4

    def test_parse_bullet_list(self):
        raw = "- Create base template\n- Add user model\n- Build API"
        steps = _parse_plan(raw)
        assert len(steps) == 3

    def test_caps_at_8_steps(self):
        raw = json.dumps([f"Step {i}" for i in range(15)])
        steps = _parse_plan(raw)
        assert len(steps) <= 8

    def test_fallback_on_garbage(self):
        raw = "Just do the thing"
        steps = _parse_plan(raw)
        assert len(steps) == 1
        assert steps[0] == "Execute the complete task"

    def test_strip_fences_python(self):
        raw = '```python\nprint("hello")\n```'
        assert _strip_fences(raw) == 'print("hello")'

    def test_strip_fences_none(self):
        raw = 'print("hello")'
        assert _strip_fences(raw) == 'print("hello")'


# --- Routing function tests ---


class TestRouteAfterValidate:
    def test_routes_to_fix_on_error(self):
        state: DeepAgentState = {
            "error": "SyntaxError",
            "retry_count": 0,
            "max_retries": 2,
            "plan": [{"step": "s", "status": "done", "output": ""}],
            "current_step_index": 0,
        }
        assert route_after_validate(state) == "review_and_fix"

    def test_routes_to_advance_on_success(self):
        state: DeepAgentState = {
            "error": "",
            "retry_count": 0,
            "max_retries": 2,
            "plan": [
                {"step": "s1", "status": "done", "output": ""},
                {"step": "s2", "status": "pending", "output": ""},
            ],
            "current_step_index": 0,
        }
        assert route_after_validate(state) == "advance_step"

    def test_routes_to_finalize_on_last_step(self):
        state: DeepAgentState = {
            "error": "",
            "retry_count": 0,
            "max_retries": 2,
            "plan": [{"step": "s1", "status": "done", "output": ""}],
            "current_step_index": 0,
        }
        assert route_after_validate(state) == "finalize"


class TestRouteAfterFix:
    def test_revalidate_after_fix(self):
        state: DeepAgentState = {
            "error": "",
            "retry_count": 1,
            "max_retries": 2,
            "plan": [{"step": "s", "status": "done", "output": ""}],
            "current_step_index": 0,
        }
        assert route_after_fix(state) == "validate_step"

    def test_execute_next_step_after_exhausted(self):
        state: DeepAgentState = {
            "error": "",
            "retry_count": 0,
            "max_retries": 2,
            "plan": [
                {"step": "s1", "status": "failed", "output": ""},
                {"step": "s2", "status": "pending", "output": ""},
            ],
            "current_step_index": 1,
        }
        assert route_after_fix(state) == "execute_step"


class TestAdvanceStep:
    def test_increments_index(self):
        state: DeepAgentState = {"current_step_index": 2, "retry_count": 1, "error": "old"}
        result = advance_step(state)
        assert result["current_step_index"] == 3
        assert result["retry_count"] == 0
        assert result["error"] == ""


# --- Graph construction test ---


class TestGraphConstruction:
    def test_graph_builds_without_error(self):
        graph = build_deep_agent_graph()
        assert graph is not None

    def test_graph_compiles(self):
        from langgraph.checkpoint.memory import MemorySaver

        graph = build_deep_agent_graph()
        compiled = graph.compile(checkpointer=MemorySaver())
        assert compiled is not None


# --- Node unit tests ---


class TestPlanTaskNode:
    async def test_plan_task_returns_plan(self):
        state: DeepAgentState = {
            "task_description": "Build a CRM with auth",
            "skill_type": "generate_program",
            "program_language": "python",
            "files": {},
        }

        plan_json = '["Setup Flask skeleton", "Add user model", "Add auth routes"]'
        with patch(
            "src.orchestrators.deep_agent.nodes.generate_text",
            new_callable=AsyncMock,
            return_value=plan_json,
        ):
            from src.orchestrators.deep_agent.nodes import plan_task

            result = await plan_task(state)

        assert len(result["plan"]) == 3
        assert result["current_step_index"] == 0
        assert all(s["status"] == "pending" for s in result["plan"])

    async def test_plan_task_tax(self):
        state: DeepAgentState = {
            "task_description": "Annual tax report",
            "skill_type": "tax_report",
            "financial_data": {"year": 2026},
        }

        plan_json = '["Review income", "Categorize deductions", "Calculate tax"]'
        with patch(
            "src.orchestrators.deep_agent.nodes.generate_text",
            new_callable=AsyncMock,
            return_value=plan_json,
        ):
            from src.orchestrators.deep_agent.nodes import plan_task

            result = await plan_task(state)

        assert len(result["plan"]) == 3


class TestExecuteStepNode:
    async def test_execute_step_code(self):
        state: DeepAgentState = {
            "task_description": "Build a CRM",
            "skill_type": "generate_program",
            "plan": [
                {"step": "Setup Flask", "status": "pending", "output": ""},
                {"step": "Add routes", "status": "pending", "output": ""},
            ],
            "current_step_index": 0,
            "files": {},
            "step_outputs": [],
            "model": "claude-sonnet-4-6",
            "filename": "app.py",
            "program_language": "python",
        }

        code = "from flask import Flask\napp = Flask(__name__)"
        with patch(
            "src.orchestrators.deep_agent.nodes.generate_text",
            new_callable=AsyncMock,
            return_value=code,
        ):
            from src.orchestrators.deep_agent.nodes import execute_step

            result = await execute_step(state)

        assert "app.py" in result["files"]
        assert "Flask" in result["files"]["app.py"]
        assert result["plan"][0]["status"] == "done"
        assert len(result["step_outputs"]) == 1

    async def test_execute_step_tax(self):
        state: DeepAgentState = {
            "task_description": "Annual tax report",
            "skill_type": "tax_report",
            "plan": [
                {"step": "Review income", "status": "pending", "output": ""},
            ],
            "current_step_index": 0,
            "files": {},
            "step_outputs": [],
            "model": "claude-sonnet-4-6",
            "financial_data": {"year": 2026, "annual": {"gross_income": 50000}},
        }

        section = "<b>Income Review</b>\nTotal income: $50,000"
        with patch(
            "src.orchestrators.deep_agent.nodes.generate_text",
            new_callable=AsyncMock,
            return_value=section,
        ):
            from src.orchestrators.deep_agent.nodes import execute_step

            result = await execute_step(state)

        assert len(result["step_outputs"]) == 1
        assert "Income Review" in result["step_outputs"][0]


class TestValidateStepNode:
    async def test_validate_no_e2b(self):
        state: DeepAgentState = {
            "skill_type": "generate_program",
            "files": {"app.py": "print('hello')"},
            "filename": "app.py",
            "ext": ".py",
        }

        with patch(
            "src.core.sandbox.e2b_runner.is_configured",
            return_value=False,
        ):
            from src.orchestrators.deep_agent.nodes import validate_step

            result = await validate_step(state)

        assert result["error"] == ""

    async def test_validate_tax_always_passes(self):
        state: DeepAgentState = {
            "skill_type": "tax_report",
            "step_outputs": ["Some report section"],
        }

        from src.orchestrators.deep_agent.nodes import validate_step

        result = await validate_step(state)
        assert result["error"] == ""


class TestFinalizeNode:
    async def test_finalize_code_no_e2b(self):
        state: DeepAgentState = {
            "skill_type": "generate_program",
            "files": {"app.py": "print('hello')"},
            "filename": "app.py",
            "ext": ".py",
            "user_id": "test_user",
            "plan": [{"step": "s", "status": "done", "output": "ok"}],
        }

        mock_redis = AsyncMock()
        with (
            patch("src.core.db.redis", mock_redis),
            patch(
                "src.core.sandbox.e2b_runner.is_configured",
                return_value=False,
            ),
        ):
            from src.orchestrators.deep_agent.nodes import finalize

            result = await finalize(state)

        assert "app.py" in result["response_text"]
        assert result["document"] is not None
        assert mock_redis.setex.call_count == 2

    def test_finalize_tax(self):
        state: DeepAgentState = {
            "skill_type": "tax_report",
            "step_outputs": ["<b>Section 1</b>", "<b>Section 2</b>"],
            "plan": [
                {"step": "s1", "status": "done", "output": ""},
                {"step": "s2", "status": "done", "output": ""},
            ],
        }

        from src.orchestrators.deep_agent.nodes import _finalize_tax

        result = _finalize_tax(state)
        assert "Section 1" in result["response_text"]
        assert "Section 2" in result["response_text"]
        assert "not professional tax advice" in result["response_text"]
        assert "2/2 sections" in result["response_text"]
