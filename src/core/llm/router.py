from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider: str  # "anthropic", "openai", "google"
    model_id: str
    fallback_provider: str | None = None
    fallback_model_id: str | None = None


# Task → model mapping (from architecture doc section 2.2)
TASK_MODEL_MAP: dict[str, ModelConfig] = {
    "intent_detection": ModelConfig(
        provider="google",
        model_id="gemini-3-flash-preview",
        fallback_provider="anthropic",
        fallback_model_id="claude-haiku-4-5",
    ),
    "ocr": ModelConfig(
        provider="google",
        model_id="gemini-3-flash-preview",
        fallback_provider="openai",
        fallback_model_id="gpt-5.2",
    ),
    "chat": ModelConfig(
        provider="anthropic",
        model_id="claude-haiku-4-5",
        fallback_provider="google",
        fallback_model_id="gemini-3-flash-preview",
    ),
    "analytics": ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        fallback_provider="openai",
        fallback_model_id="gpt-5.2",
    ),
    "complex": ModelConfig(
        provider="anthropic",
        model_id="claude-opus-4-6",
        fallback_provider="openai",
        fallback_model_id="gpt-5.2",
    ),
    "summarization": ModelConfig(
        provider="google",
        model_id="gemini-3-flash-preview",
        fallback_provider="anthropic",
        fallback_model_id="claude-haiku-4-5",
    ),
    "onboarding": ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
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
