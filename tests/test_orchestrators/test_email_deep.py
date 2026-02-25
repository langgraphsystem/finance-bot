"""Tests for the deepagents email orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrators.deep.domains.email import EmailOrchestrator, email_orchestrator
from src.skills.base import SkillResult


async def test_email_orchestrator_compose_uses_subagents(sample_context, text_message):
    """Compose intents (send_email, draft_reply) use subagent-based flow."""
    text_message.text = "Send an email to John about the meeting"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {
        "messages": [MagicMock(content="Email drafted and ready to send.")]
    }

    with (
        patch(
            "src.orchestrators.deep.domains.email.create_deep_agent",
            return_value=mock_agent,
        ) as mock_create,
        patch("src.orchestrators.deep.domains.email.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.email.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await email_orchestrator.invoke(
            "send_email",
            text_message,
            sample_context,
            {"email_to": "john@example.com", "email_subject": "Meeting"},
        )

    assert isinstance(result, SkillResult)
    # Verify subagents were passed to create_deep_agent
    call_kwargs = mock_create.call_args
    assert "subagents" in call_kwargs.kwargs or (
        len(call_kwargs.args) > 0 and any("subagents" in str(a) for a in call_kwargs.args)
    )


async def test_email_orchestrator_simple_uses_base_flow(sample_context, text_message):
    """Simple intents (read_inbox) use the base DeepAgentOrchestrator flow."""
    text_message.text = "Show my inbox"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": [MagicMock(content="You have 3 unread emails.")]}

    with (
        patch(
            "src.orchestrators.deep.base.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.base.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.base.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await email_orchestrator.invoke(
            "read_inbox",
            text_message,
            sample_context,
            {},
        )

    assert isinstance(result, SkillResult)
    assert "3 unread" in result.response_text


async def test_email_orchestrator_handles_compose_failure(sample_context, text_message):
    """Email compose handles exceptions gracefully."""
    text_message.text = "Send email to Bob"

    mock_agent = AsyncMock()
    mock_agent.ainvoke.side_effect = RuntimeError("API error")

    with (
        patch(
            "src.orchestrators.deep.domains.email.create_deep_agent",
            return_value=mock_agent,
        ),
        patch("src.orchestrators.deep.domains.email.get_registry") as mock_get_reg,
        patch("src.orchestrators.deep.domains.email.build_skill_tools", return_value=[]),
    ):
        mock_get_reg.return_value = MagicMock()

        result = await email_orchestrator.invoke(
            "send_email",
            text_message,
            sample_context,
            {"email_to": "bob@example.com"},
        )

    assert isinstance(result, SkillResult)
    assert "couldn't" in result.response_text.lower() or "try again" in result.response_text.lower()


def test_email_orchestrator_config():
    """Email orchestrator has correct configuration."""
    assert email_orchestrator.model == "claude-sonnet-4-6"
    assert "send_email" in email_orchestrator.skill_names
    assert "draft_reply" in email_orchestrator.skill_names
    assert "read_inbox" in email_orchestrator.skill_names
    assert isinstance(email_orchestrator, EmailOrchestrator)
