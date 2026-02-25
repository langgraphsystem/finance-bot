"""Smoke tests for all 13 domain orchestrator registrations."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator
from src.orchestrators.deep.domains import DOMAIN_ORCHESTRATORS, register_all_orchestrators
from src.orchestrators.deep.domains.brief import BriefOrchestrator, brief_orchestrator
from src.orchestrators.deep.domains.calendar import calendar_orchestrator
from src.orchestrators.deep.domains.email import EmailOrchestrator, email_orchestrator
from src.orchestrators.deep.domains.finance import finance_orchestrator
from src.orchestrators.deep.domains.general import general_orchestrator
from src.orchestrators.deep.domains.research import research_orchestrator
from src.orchestrators.deep.domains.tasks import tasks_orchestrator
from src.orchestrators.deep.domains.writing import writing_orchestrator
from src.skills.base import SkillResult


def test_all_13_domains_registered():
    """All 13 domains have orchestrators in DOMAIN_ORCHESTRATORS."""
    assert len(DOMAIN_ORCHESTRATORS) == 13
    for domain in Domain:
        assert domain in DOMAIN_ORCHESTRATORS, f"Missing orchestrator for {domain}"


def test_register_all_orchestrators_calls_register():
    """register_all_orchestrators registers all 13 domains."""
    mock_router = MagicMock()
    register_all_orchestrators(mock_router)
    assert mock_router.register_orchestrator.call_count == 13


def test_all_orchestrators_are_deep_agent_type():
    """All orchestrators inherit from DeepAgentOrchestrator."""
    for domain, orch in DOMAIN_ORCHESTRATORS.items():
        assert isinstance(orch, DeepAgentOrchestrator), (
            f"{domain} orchestrator is not a DeepAgentOrchestrator"
        )


def test_email_is_custom_orchestrator():
    """Email orchestrator uses custom EmailOrchestrator class."""
    assert isinstance(email_orchestrator, EmailOrchestrator)


def test_brief_is_custom_orchestrator():
    """Brief orchestrator uses custom BriefOrchestrator class."""
    assert isinstance(brief_orchestrator, BriefOrchestrator)


def test_model_assignments():
    """Verify model assignments match approved model IDs."""
    approved_models = {
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "gpt-5.2",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    }
    for domain, orch in DOMAIN_ORCHESTRATORS.items():
        assert orch.model in approved_models, f"{domain} uses unapproved model: {orch.model}"


def test_each_orchestrator_has_skills():
    """Every orchestrator has at least one skill registered."""
    for domain, orch in DOMAIN_ORCHESTRATORS.items():
        assert len(orch.skill_names) >= 1, f"{domain} has no skills"


def test_each_orchestrator_has_system_prompt():
    """Every orchestrator has a non-empty system prompt."""
    for domain, orch in DOMAIN_ORCHESTRATORS.items():
        assert orch.system_prompt, f"{domain} has empty system prompt"


def test_finance_orchestrator_config():
    """Finance orchestrator has correct skill set."""
    assert finance_orchestrator.model == "gpt-5.2"
    assert "add_expense" in finance_orchestrator.skill_names
    assert "query_stats" in finance_orchestrator.skill_names
    assert "scan_receipt" in finance_orchestrator.skill_names


def test_tasks_orchestrator_config():
    """Tasks orchestrator has correct skill set."""
    assert tasks_orchestrator.model == "gpt-5.2"
    assert "create_task" in tasks_orchestrator.skill_names
    assert "set_reminder" in tasks_orchestrator.skill_names


def test_research_orchestrator_config():
    """Research orchestrator uses Gemini Flash."""
    assert research_orchestrator.model == "gemini-3-flash-preview"
    assert "web_search" in research_orchestrator.skill_names
    assert "quick_answer" in research_orchestrator.skill_names


def test_writing_orchestrator_config():
    """Writing orchestrator uses Claude Sonnet."""
    assert writing_orchestrator.model == "claude-sonnet-4-6"
    assert "draft_message" in writing_orchestrator.skill_names
    assert "translate_text" in writing_orchestrator.skill_names


def test_general_orchestrator_has_life_skills():
    """General orchestrator includes life-tracking skills."""
    assert "track_food" in general_orchestrator.skill_names
    assert "track_drink" in general_orchestrator.skill_names
    assert "mood_checkin" in general_orchestrator.skill_names
    assert "general_chat" in general_orchestrator.skill_names


async def test_base_orchestrator_invoke_smoke(sample_context, text_message):
    """Smoke test: base orchestrator invoke returns SkillResult."""
    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": [MagicMock(content="Response")]}

    with (
        patch(
            "src.orchestrators.deep.base.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.base.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.base.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await calendar_orchestrator.invoke("list_events", text_message, sample_context, {})

    assert isinstance(result, SkillResult)
