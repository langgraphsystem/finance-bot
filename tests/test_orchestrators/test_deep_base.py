"""Tests for the base DeepAgentOrchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.domains import Domain
from src.orchestrators.deep.base import DeepAgentOrchestrator, _build_user_message, _extract_result
from src.skills.base import SkillResult


async def test_orchestrator_invoke_success(sample_context, text_message):
    """DeepAgentOrchestrator.invoke creates agent and returns SkillResult."""
    orchestrator = DeepAgentOrchestrator(
        domain=Domain.finance,
        model="gpt-5.2",
        skill_names=["add_expense"],
        system_prompt="You are a finance agent.",
        context_config={"mem": False, "hist": 0, "sql": False, "sum": False},
    )

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": [MagicMock(content="Expense recorded.")]}

    with (
        patch("src.orchestrators.deep.base.create_deep_agent", return_value=mock_agent),
        patch("src.orchestrators.deep.base.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.base.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await orchestrator.invoke(
            "add_expense", text_message, sample_context, {"amount": 50}
        )

    assert isinstance(result, SkillResult)
    assert result.response_text == "Expense recorded."


async def test_orchestrator_invoke_uses_skill_result(sample_context, text_message):
    """When a skill tool is invoked, its SkillResult takes priority."""
    orchestrator = DeepAgentOrchestrator(
        domain=Domain.finance,
        model="gpt-5.2",
        skill_names=["add_expense"],
        system_prompt="You are a finance agent.",
    )

    # Create a mock tool with captured SkillResult
    mock_tool = MagicMock()
    expected = SkillResult(
        response_text="Recorded $50",
        buttons=[{"text": "Undo", "callback": "undo:123"}],
    )
    mock_tool.last_result = expected

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": [MagicMock(content="Agent text")]}

    with (
        patch("src.orchestrators.deep.base.create_deep_agent", return_value=mock_agent),
        patch("src.orchestrators.deep.base.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.base.build_skill_tools", return_value=[mock_tool]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await orchestrator.invoke(
            "add_expense", text_message, sample_context, {"amount": 50}
        )

    assert result is expected
    assert result.buttons == [{"text": "Undo", "callback": "undo:123"}]


async def test_orchestrator_invoke_handles_exception(sample_context, text_message):
    """DeepAgentOrchestrator handles agent exceptions gracefully."""
    orchestrator = DeepAgentOrchestrator(
        domain=Domain.general,
        model="gpt-5.2",
        skill_names=[],
        system_prompt="Test",
    )

    mock_agent = AsyncMock()
    mock_agent.ainvoke.side_effect = RuntimeError("LLM unavailable")

    with (
        patch("src.orchestrators.deep.base.create_deep_agent", return_value=mock_agent),
        patch("src.orchestrators.deep.base.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.base.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await orchestrator.invoke("general_chat", text_message, sample_context, {})

    assert isinstance(result, SkillResult)
    assert "wrong" in result.response_text.lower() or "try again" in result.response_text.lower()


def test_build_user_message_includes_intent(text_message):
    """_build_user_message includes intent and extracted data."""
    msg = _build_user_message(
        text_message,
        "add_expense",
        {"amount": 50, "merchant": "Shell", "_domain": "finance"},
    )

    assert "[Intent: add_expense]" in msg
    assert "Shell" in msg
    assert text_message.text in msg
    # _domain should be excluded
    assert '"_domain"' not in msg


def test_build_user_message_handles_empty_data(text_message):
    """_build_user_message works with empty intent_data."""
    msg = _build_user_message(text_message, "general_chat", {})

    assert "[Intent: general_chat]" in msg
    assert text_message.text in msg


def test_extract_result_prefers_skill_result():
    """_extract_result prefers captured SkillResult over agent text."""
    tool = MagicMock()
    tool.last_result = SkillResult(response_text="From skill")

    result = _extract_result({"messages": [MagicMock(content="From agent")]}, [tool])
    assert result.response_text == "From skill"


def test_extract_result_falls_back_to_agent_text():
    """_extract_result falls back to agent's last message."""
    tool = MagicMock()
    tool.last_result = None

    last_msg = MagicMock()
    last_msg.content = "Agent response"

    result = _extract_result({"messages": [last_msg]}, [tool])
    assert result.response_text == "Agent response"


def test_extract_result_returns_default_when_empty():
    """_extract_result returns 'Done.' when no messages."""
    result = _extract_result({"messages": []}, [])
    assert result.response_text == "Done."
