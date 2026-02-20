"""Tests for ModelRouter."""

from src.core.llm.router import ModelRouter


def test_intent_detection_uses_gemini():
    router = ModelRouter()
    model = router.get_model("intent_detection")
    assert model.provider == "google"
    assert "gemini" in model.model_id


def test_chat_uses_gpt():
    router = ModelRouter()
    model = router.get_model("chat")
    assert model.provider == "openai"
    assert model.model_id == "gpt-5.2"


def test_analytics_uses_claude_sonnet():
    router = ModelRouter()
    model = router.get_model("analytics")
    assert model.provider == "anthropic"
    assert "sonnet" in model.model_id


def test_unknown_task_falls_back_to_chat():
    router = ModelRouter()
    model = router.get_model("unknown_task")
    assert model.provider == "openai"
    assert model.model_id == "gpt-5.2"


def test_fallback_model():
    router = ModelRouter()
    fallback = router.get_fallback("intent_detection")
    assert fallback is not None
    assert fallback.provider == "anthropic"
