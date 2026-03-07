"""Tests for post-generation rule check (Phase 13)."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.post_gen_check import check_response_rules, regenerate_with_rule_reminder


class TestCheckResponseRules:
    async def test_returns_ok_when_flag_disabled(self):
        with patch("src.core.post_gen_check.settings") as mock_settings:
            mock_settings.ff_post_gen_check = False
            ok, violation = await check_response_rules("Hello! 😊", ["без эмодзи"])

        assert ok is True
        assert violation == ""

    async def test_returns_ok_when_no_rules(self):
        with patch("src.core.post_gen_check.settings") as mock_settings:
            mock_settings.ff_post_gen_check = True
            ok, violation = await check_response_rules("Hello!", [])

        assert ok is True
        assert violation == ""

    async def test_returns_ok_when_response_compliant(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="OK")]
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        with (
            patch("src.core.post_gen_check.settings") as mock_settings,
            patch("src.core.llm.clients.anthropic_client", return_value=mock_client),
        ):
            mock_settings.ff_post_gen_check = True
            ok, violation = await check_response_rules(
                "Записал расход.", ["без эмодзи", "коротко"]
            )

        assert ok is True
        assert violation == ""

    async def test_detects_violation(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="VIOLATION: Response contains emoji")]
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        with (
            patch("src.core.post_gen_check.settings") as mock_settings,
            patch("src.core.llm.clients.anthropic_client", return_value=mock_client),
        ):
            mock_settings.ff_post_gen_check = True
            ok, violation = await check_response_rules(
                "Записал расход! 😊", ["без эмодзи"]
            )

        assert ok is False
        assert "emoji" in violation.lower() or "violation" not in violation.lower()

    async def test_fail_open_on_llm_error(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("LLM down"))

        with (
            patch("src.core.post_gen_check.settings") as mock_settings,
            patch("src.core.llm.clients.anthropic_client", return_value=mock_client),
        ):
            mock_settings.ff_post_gen_check = True
            ok, violation = await check_response_rules(
                "Hello!", ["без эмодзи"]
            )

        # Fail-open: allow response through even if check crashes
        assert ok is True
        assert violation == ""

    async def test_truncates_long_response(self):
        """Response should be truncated to 2000 chars before sending to LLM."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="OK")]
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        long_response = "A" * 5000

        with (
            patch("src.core.post_gen_check.settings") as mock_settings,
            patch("src.core.llm.clients.anthropic_client", return_value=mock_client),
        ):
            mock_settings.ff_post_gen_check = True
            await check_response_rules(long_response, ["коротко"])

        # Check the prompt passed to LLM doesn't exceed 2000 response chars
        call_content = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "A" * 2001 not in call_content
        assert "A" * 2000 in call_content


class TestRegenerateWithRuleReminder:
    async def test_returns_regenerated_response(self):
        mock_response = MagicMock()
        mock_response.text = "Записал расход без эмодзи."
        mock_google = MagicMock()
        mock_google.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("src.core.llm.clients.google_client", return_value=mock_google):
            result = await regenerate_with_rule_reminder(
                original_response="Записал! 😊",
                violation="emoji not allowed",
                user_rules=["без эмодзи"],
                system_prompt="You are a finance bot.",
                user_message="записал 50 на кофе",
            )

        assert result == "Записал расход без эмодзи."

    async def test_falls_back_to_original_on_error(self):
        mock_google = MagicMock()
        mock_google.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Gemini down")
        )

        with patch("src.core.llm.clients.google_client", return_value=mock_google):
            result = await regenerate_with_rule_reminder(
                original_response="Original response 😊",
                violation="emoji not allowed",
                user_rules=["без эмодзи"],
                system_prompt="",
                user_message="test",
            )

        assert result == "Original response 😊"

    async def test_truncates_original_response_in_prompt(self):
        """Original response is truncated to 500 chars in the regeneration prompt."""
        long_original = "X" * 1000
        mock_response = MagicMock()
        mock_response.text = "short reply"
        mock_google = MagicMock()
        mock_google.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("src.core.llm.clients.google_client", return_value=mock_google):
            await regenerate_with_rule_reminder(
                original_response=long_original,
                violation="too long",
                user_rules=["коротко"],
                system_prompt="",
                user_message="test",
            )

        call_content = mock_google.aio.models.generate_content.call_args[1]["contents"]
        assert "X" * 501 not in call_content
        assert "X" * 500 in call_content
