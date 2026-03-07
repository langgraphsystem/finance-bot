from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider: str  # "anthropic", "openai", "google", "xai"
    model_id: str
    fallback_provider: str | None = None
    fallback_model_id: str | None = None
    # OpenAI Responses API: "none" | "low" | "medium" | "high" | "xhigh"
    # Only applies to gpt-5.x models; ignored for Anthropic/Google
    reasoning_effort: str | None = None
    # OpenAI Responses API: "low" | "medium" | "high"
    verbosity: str | None = None


# Task → model mapping (from architecture doc section 2.2)
TASK_MODEL_MAP: dict[str, ModelConfig] = {
    "intent_detection": ModelConfig(
        provider="google",
        model_id="gemini-3.1-flash-lite-preview",
        fallback_provider="anthropic",
        fallback_model_id="claude-haiku-4-5",
    ),
    "ocr": ModelConfig(
        provider="google",
        model_id="gemini-3.1-flash-lite-preview",
        fallback_provider="openai",
        fallback_model_id="gpt-5.4-2026-03-05",
    ),
    "chat": ModelConfig(
        provider="openai",
        model_id="gpt-5.4-2026-03-05",
        fallback_provider="google",
        fallback_model_id="gemini-3.1-flash-lite-preview",
        reasoning_effort="low",   # fast, conversational
        verbosity="medium",
    ),
    "analytics": ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        fallback_provider="openai",
        fallback_model_id="gpt-5.4-2026-03-05",
    ),
    "complex": ModelConfig(
        provider="anthropic",
        model_id="claude-opus-4-6",
        fallback_provider="openai",
        fallback_model_id="gpt-5.4-2026-03-05",
    ),
    "summarization": ModelConfig(
        provider="google",
        model_id="gemini-3.1-flash-lite-preview",
        fallback_provider="anthropic",
        fallback_model_id="claude-haiku-4-5",
    ),
    "onboarding": ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
    ),
    "tasks": ModelConfig(
        provider="openai",
        model_id="gpt-5.4-2026-03-05",
        fallback_provider="google",
        fallback_model_id="gemini-3.1-flash-lite-preview",
        reasoning_effort="low",   # task parsing needs to be fast
        verbosity="low",
    ),
}


class ModelRouter:
    """Routes tasks to appropriate LLM models."""

    def get_model(self, task: str) -> ModelConfig:
        config = TASK_MODEL_MAP.get(task)
        if config is None:
            return TASK_MODEL_MAP["chat"]
        return config

    def get_fallback(self, task: str) -> ModelConfig | None:
        config = TASK_MODEL_MAP.get(task)
        if config and config.fallback_provider:
            return ModelConfig(
                provider=config.fallback_provider,
                model_id=config.fallback_model_id,
            )
        return None
