import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.base import AgentConfig, AgentRouter
from src.skills.base import SkillResult


class _MockSkill:
    name = "memory_vault"
    intents = ["memory_save"]
    model = "gpt-5.2"

    def __init__(self):
        self.execute = AsyncMock(return_value=SkillResult(response_text="saved"))

    def get_system_prompt(self, context):  # noqa: ANN001, ARG002
        return ""


class _MockRegistry:
    def __init__(self, skill):
        self._skill = skill

    def get(self, intent):
        if intent == "memory_save":
            return self._skill
        return None



def _sample_context():
    from src.core.context import SessionContext

    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_agent_router_preserves_memory_intent_for_skill_handlers():
    skill = _MockSkill()
    registry = _MockRegistry(skill)
    agent = AgentConfig(
        name="life",
        system_prompt="life prompt",
        skills=["memory_save"],
        default_model="gpt-5.2",
        data_tools_enabled=True,
    )
    router = AgentRouter([agent], registry)
    message = MagicMock(text="запомни: чай")
    context = _sample_context()
    intent_data = {"memory_query": "чай"}
    assembled = MagicMock(system_prompt="prompt", messages=[])

    with patch("src.agents.base.assemble_context", new_callable=AsyncMock, return_value=assembled):
        result = await router.route("memory_save", message, context, intent_data)

    assert result.response_text == "saved"
    called_intent_data = skill.execute.await_args.args[2]
    assert called_intent_data["_intent"] == "memory_save"
    assert called_intent_data["memory_query"] == "чай"
