"""Tests for adaptive personality — prompt injection + personality analysis."""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.agents.base import AgentRouter
from src.core.tasks.profile_tasks import _analyze_personality

# --- Helper: minimal SessionContext mock ---


@dataclass
class _MockContext:
    user_profile: dict
    profile_config: None = None
    language: str = "en"
    timezone: str = "America/New_York"


# --- _add_personality_instruction tests ---


def test_personality_no_profile():
    ctx = _MockContext(user_profile={})
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert result == "Base prompt."


def test_personality_no_personality_key():
    ctx = _MockContext(user_profile={"city": "Brooklyn", "tone_preference": "friendly"})
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert result == "Base prompt."


def test_personality_concise_casual():
    ctx = _MockContext(
        user_profile={
            "personality": {"verbosity": "concise", "formality": "casual", "emoji_usage": "light"},
        }
    )
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert "brief" in result
    assert "casual" in result
    assert "emoji" not in result.lower().split("casual")[1]  # light → no emoji instruction


def test_personality_detailed_formal():
    ctx = _MockContext(
        user_profile={
            "personality": {"verbosity": "detailed", "formality": "formal", "emoji_usage": "none"},
        }
    )
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert "detailed" in result
    assert "professional" in result
    assert "Avoid using emoji" in result


def test_personality_heavy_emoji():
    ctx = _MockContext(
        user_profile={
            "personality": {
                "verbosity": "moderate", "formality": "neutral", "emoji_usage": "heavy",
            },
        }
    )
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert "Feel free to use emoji" in result


def test_personality_with_occupation():
    ctx = _MockContext(
        user_profile={
            "occupation": "plumber",
            "personality": {"verbosity": "concise", "formality": "neutral", "emoji_usage": "none"},
        }
    )
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    assert "plumber" in result


def test_personality_moderate_neutral_no_injection():
    """Moderate verbosity + neutral formality + light emoji → only 'brief' cue."""
    ctx = _MockContext(
        user_profile={
            "personality": {
                "verbosity": "moderate",
                "formality": "neutral",
                "emoji_usage": "light",
            },
        }
    )
    result = AgentRouter._add_personality_instruction("Base prompt.", ctx)
    # No strong cues → prompt unchanged
    assert result == "Base prompt."


def test_personality_block_after_specialist():
    """Personality instruction appears in the prompt (not empty)."""
    ctx = _MockContext(
        user_profile={"personality": {"verbosity": "detailed", "formality": "casual"}},
    )
    result = AgentRouter._add_personality_instruction("System:\nYou are a helper.", ctx)
    assert result.startswith("System:\nYou are a helper.")
    assert "User personality:" in result


# --- _analyze_personality tests ---


def _make_msg(content: str, hour: int = 12):
    msg = MagicMock()
    msg.content = content
    msg.created_at = datetime(2026, 2, 27, hour, 0, 0, tzinfo=UTC)
    return msg


def test_analyze_personality_empty():
    assert _analyze_personality([]) == {}


def test_analyze_concise_messages():
    msgs = [_make_msg("100 кофе"), _make_msg("да"), _make_msg("ок"), _make_msg("напомни")]
    result = _analyze_personality(msgs)
    assert result["verbosity"] == "concise"


def test_analyze_detailed_messages():
    long = "This is a very long and detailed message about my expenses for the month " * 2
    msgs = [_make_msg(long) for _ in range(5)]
    result = _analyze_personality(msgs)
    assert result["verbosity"] == "detailed"


def test_analyze_formal_markers():
    msgs = [
        _make_msg("Could you please help me?"),
        _make_msg("Would you kindly check?"),
        _make_msg("Please send the report."),
        _make_msg("Будьте добры, пожалуйста проверьте."),
    ]
    result = _analyze_personality(msgs)
    assert result["formality"] == "formal"


def test_analyze_casual_markers():
    msgs = [
        _make_msg("ок"),
        _make_msg("ладно давай"),
        _make_msg("норм го"),
        _make_msg("круто щас"),
    ]
    result = _analyze_personality(msgs)
    assert result["formality"] == "casual"


def test_analyze_emoji_heavy():
    msgs = [_make_msg("Hello! 😊"), _make_msg("Thanks 🙏"), _make_msg("Great 🎉")]
    result = _analyze_personality(msgs)
    assert result["emoji_usage"] == "heavy"


def test_analyze_no_emoji():
    msgs = [_make_msg("Hello"), _make_msg("Thanks"), _make_msg("Great work")]
    result = _analyze_personality(msgs)
    assert result["emoji_usage"] == "none"


def test_analyze_language_mixing():
    msgs = [
        _make_msg("Привет, check my expenses"),
        _make_msg("Нужен report за неделю"),
        _make_msg("Покажи budget"),
    ]
    result = _analyze_personality(msgs)
    assert result["language_mixing"] == "mixed"


def test_analyze_no_language_mixing():
    msgs = [_make_msg("Привет"), _make_msg("Покажи расходы"), _make_msg("Спасибо")]
    result = _analyze_personality(msgs)
    assert result["language_mixing"] is None


def test_analyze_returns_all_keys():
    msgs = [_make_msg("Hello world") for _ in range(5)]
    result = _analyze_personality(msgs)
    assert "verbosity" in result
    assert "formality" in result
    assert "emoji_usage" in result
    assert "language_mixing" in result
    assert "avg_message_length" in result
    assert "analyzed_at" in result
