"""Tests for core identity layer (Phase 2.3 + upsert fix)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.identity import (
    _EMPTY_IDENTITY,
    _is_valid_rule,
    _parse_bot_identity_fact,
    _parse_identity_fact,
    clear_identity_fields,
    clear_user_rules,
    format_identity_block,
    format_rules_block,
    get_core_identity,
    immediate_identity_update,
    update_core_identity,
)

# Helper: patch _ensure_user_profile as no-op (DB-free tests)
_no_ensure = patch(
    "src.core.identity._ensure_user_profile", new_callable=AsyncMock
)


class TestGetCoreIdentity:
    async def test_returns_identity_dict(self):
        identity = {"name": "Maria", "preferred_currency": "USD"}
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = identity
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == identity

    async def test_returns_empty_when_no_row(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == _EMPTY_IDENTITY

    async def test_returns_empty_on_error(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == _EMPTY_IDENTITY


class TestUpdateCoreIdentity:
    async def test_merges_updates(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria", "preferred_currency": "USD"}

        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_session.commit.return_value = None

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_get = AsyncMock(return_value=current)
        with (
            patch("src.core.identity.get_core_identity", mock_get),
            patch("src.core.identity.async_session", return_value=mock_ctx),
            _no_ensure,
        ):
            result = await update_core_identity(uid, {"occupation": "plumber"})
        assert result["name"] == "Maria"
        assert result["occupation"] == "plumber"
        assert result["preferred_currency"] == "USD"

    async def test_removes_none_values(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria", "occupation": "teacher"}

        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_get = AsyncMock(return_value=current)
        with (
            patch("src.core.identity.get_core_identity", mock_get),
            patch("src.core.identity.async_session", return_value=mock_ctx),
            _no_ensure,
        ):
            result = await update_core_identity(uid, {"occupation": None})
        assert "occupation" not in result
        assert result["name"] == "Maria"

    async def test_returns_current_on_error(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria"}

        with (
            patch(
                "src.core.identity.get_core_identity",
                new_callable=AsyncMock,
                side_effect=[current, current],
            ),
            patch("src.core.identity.async_session", side_effect=Exception("DB down")),
        ):
            result = await update_core_identity(uid, {"name": "Mary"})
        assert result == current

    async def test_calls_ensure_user_profile(self):
        """update_core_identity must call _ensure_user_profile before UPDATE."""
        uid = str(uuid.uuid4())

        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_ensure = AsyncMock()
        mock_get = AsyncMock(return_value={})
        with (
            patch("src.core.identity.get_core_identity", mock_get),
            patch("src.core.identity.async_session", return_value=mock_ctx),
            patch("src.core.identity._ensure_user_profile", mock_ensure),
        ):
            await update_core_identity(uid, {"name": "Manas"})
        mock_ensure.assert_awaited_once_with(mock_session, uid)


class TestAddUserRule:
    async def test_calls_ensure_user_profile(self):
        """_add_user_rule must create profile if missing."""
        from src.core.identity import _add_user_rule

        uid = str(uuid.uuid4())

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = []
        mock_session.execute.return_value = mock_result
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_ensure = AsyncMock()
        with (
            patch("src.core.identity.async_session", return_value=mock_ctx),
            patch("src.core.identity._ensure_user_profile", mock_ensure),
            patch("src.core.identity.invalidate_identity_cache", new_callable=AsyncMock),
        ):
            await _add_user_rule(uid, "без эмодзи")
        mock_ensure.assert_awaited_once()


class TestImmediateIdentityUpdate:
    async def test_user_name_updates_identity(self):
        uid = str(uuid.uuid4())
        mock_update = AsyncMock(return_value={"name": "Манас"})
        with (
            patch("src.core.identity.update_core_identity", mock_update),
        ):
            await immediate_identity_update(uid, "user_identity", "меня зовут Манас")
        mock_update.assert_awaited_once()
        call_args = mock_update.call_args
        assert call_args[0][1].get("name") == "Манас"

    async def test_bot_name_updates_identity(self):
        uid = str(uuid.uuid4())
        mock_update = AsyncMock(return_value={"bot_name": "Хюррем"})
        with (
            patch("src.core.identity.update_core_identity", mock_update),
        ):
            await immediate_identity_update(uid, "bot_identity", "зови себя Хюррем")
        mock_update.assert_awaited_once()
        call_args = mock_update.call_args
        assert call_args[0][1].get("bot_name") == "Хюррем"

    async def test_user_rule_calls_add_rule(self):
        uid = str(uuid.uuid4())
        mock_add_rule = AsyncMock()
        with (
            patch("src.core.identity._add_user_rule", mock_add_rule),
        ):
            await immediate_identity_update(uid, "user_rule", "без эмодзи")
        mock_add_rule.assert_awaited_once_with(uid, "без эмодзи")

    async def test_ignores_non_identity_category(self):
        uid = str(uuid.uuid4())
        mock_update = AsyncMock()
        with (
            patch("src.core.identity.update_core_identity", mock_update),
        ):
            await immediate_identity_update(uid, "spending_pattern", "buys coffee daily")
        mock_update.assert_not_awaited()


class TestClearUserRules:
    async def test_clears_all_rules_and_returns_count(self):
        uid = str(uuid.uuid4())
        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch(
                "src.core.identity.get_user_rules",
                new_callable=AsyncMock,
                return_value=["без эмодзи", "отвечай коротко"],
            ),
            patch("src.core.identity.async_session", return_value=mock_ctx),
            patch("src.core.identity.invalidate_identity_cache", new_callable=AsyncMock),
        ):
            cleared = await clear_user_rules(uid)

        assert cleared == 2
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_returns_zero_when_no_rules(self):
        with patch(
            "src.core.identity.get_user_rules",
            new_callable=AsyncMock,
            return_value=[],
        ):
            cleared = await clear_user_rules(str(uuid.uuid4()))

        assert cleared == 0


class TestClearIdentityFields:
    async def test_removes_requested_existing_fields_only(self):
        uid = str(uuid.uuid4())
        with (
            patch(
                "src.core.identity.get_core_identity",
                new_callable=AsyncMock,
                return_value={"bot_name": "Хюррем", "name": "Манас"},
            ),
            patch("src.core.identity.update_core_identity", new_callable=AsyncMock) as mock_update,
        ):
            removed = await clear_identity_fields(uid, ["bot_name", "city"])

        assert removed == ["bot_name"]
        mock_update.assert_awaited_once_with(uid, {"bot_name": None})

    async def test_returns_empty_when_nothing_to_remove(self):
        with patch(
            "src.core.identity.get_core_identity",
            new_callable=AsyncMock,
            return_value={},
        ):
            removed = await clear_identity_fields(str(uuid.uuid4()), ["bot_name"])

        assert removed == []


class TestParseIdentityFact:
    def test_parse_name_russian(self):
        result = _parse_identity_fact("Меня зовут Манас")
        assert result["name"] == "Манас"

    def test_parse_name_english(self):
        result = _parse_identity_fact("my name is John")
        assert result["name"] == "John"

    def test_parse_city(self):
        result = _parse_identity_fact("живу в Бишкеке")
        assert result["city"] == "Бишкеке"

    def test_parse_occupation(self):
        result = _parse_identity_fact("работаю программистом")
        assert result["occupation"] == "программистом"

    def test_raw_identity_fallback(self):
        result = _parse_identity_fact("мне 25 лет")
        assert "_raw_identity" in result


class TestParseBotIdentityFact:
    def test_parse_bot_name_ru(self):
        result = _parse_bot_identity_fact("зови себя Хюррем")
        assert result["bot_name"] == "Хюррем"

    def test_parse_bot_name_en(self):
        result = _parse_bot_identity_fact("your name is Luna")
        assert result["bot_name"] == "Luna"


class TestFormatIdentityBlock:
    def test_empty_identity(self):
        assert format_identity_block({}) == ""

    def test_name_only(self):
        result = format_identity_block({"name": "Maria"})
        assert "<core_identity>" in result
        assert "Name: Maria" in result
        assert "</core_identity>" in result

    def test_full_identity(self):
        identity = {
            "name": "David",
            "occupation": "Plumber",
            "family_members": ["wife Sarah", "son Jake"],
            "preferred_currency": "USD",
            "business_type": "construction",
            "communication_preferences": "brief, no emojis",
        }
        result = format_identity_block(identity)
        assert "Name: David" in result
        assert "Occupation: Plumber" in result
        assert "Family: wife Sarah, son Jake" in result
        assert "Currency: USD" in result
        assert "Business: construction" in result
        assert "Communication: brief, no emojis" in result

    def test_family_as_string(self):
        result = format_identity_block({"family_members": "wife and 2 kids"})
        assert "Family: wife and 2 kids" in result

    def test_important_facts_list(self):
        result = format_identity_block({"important_facts": ["allergic to cats", "vegan"]})
        assert "- allergic to cats" in result
        assert "- vegan" in result

    def test_important_facts_string(self):
        result = format_identity_block({"important_facts": "has diabetes"})
        assert "- has diabetes" in result

    def test_empty_values_skipped(self):
        result = format_identity_block({"name": "", "occupation": None})
        assert result == ""

    def test_only_none_values_returns_empty(self):
        result = format_identity_block({"name": None, "occupation": None})
        assert result == ""

    def test_bot_name_included(self):
        result = format_identity_block({"bot_name": "Хюррем"})
        assert "Bot Name: Хюррем" in result

    def test_response_language_included(self):
        result = format_identity_block({"response_language": "ru"})
        assert "Response Language: ru" in result


class TestFormatRulesBlock:
    def test_empty_rules(self):
        assert format_rules_block([]) == ""

    def test_rules_formatted(self):
        result = format_rules_block(["без эмодзи", "отвечай коротко"])
        assert "<user_rules>" in result
        assert "- без эмодзи" in result
        assert "- отвечай коротко" in result


class TestIsValidRule:
    def test_valid_rules(self):
        assert _is_valid_rule("без эмодзи") is True
        assert _is_valid_rule("отвечай коротко") is True
        assert _is_valid_rule("пиши на русском") is True
        assert _is_valid_rule("always respond in English") is True
        assert _is_valid_rule("no emoji please") is True
        assert _is_valid_rule("зови себя Хюррем") is True
        assert _is_valid_rule("your name is Luna") is True
        assert _is_valid_rule("keep it brief") is True

    def test_rejects_garbage(self):
        assert _is_valid_rule("да") is False
        assert _is_valid_rule("ок") is False
        assert _is_valid_rule("да, всегда") is False
        assert _is_valid_rule("хорошо") is False
        assert _is_valid_rule("спасибо") is False
        assert _is_valid_rule("ok") is False

    def test_rejects_short(self):
        assert _is_valid_rule("да") is False
        assert _is_valid_rule("нет") is False
        assert _is_valid_rule("abc") is False

    def test_rejects_questions(self):
        assert _is_valid_rule("как тебя зовут?") is False
        assert _is_valid_rule("what is your name") is False

    def test_rejects_forget_commands(self):
        assert _is_valid_rule("забудь правило") is False
        assert _is_valid_rule("удали все") is False
        assert _is_valid_rule("forget my name") is False

    def test_rejects_no_keyword_match(self):
        assert _is_valid_rule("я тебя назвал Хюррем") is False
        assert _is_valid_rule("Мындан кийин сенин атын Хюррем болот") is False
        assert _is_valid_rule("Запомни тебя буду называть Хюррем ок?") is False


class TestFormatIdentityBlockInstructions:
    def test_bot_name_instruction(self):
        result = format_identity_block({"bot_name": "Хюррем"})
        assert "IMPORTANT:" in result
        assert "Your name is Хюррем" in result
        assert "introduce yourself as Хюррем" in result

    def test_user_name_instruction(self):
        result = format_identity_block({"name": "Манас"})
        assert "IMPORTANT:" in result
        assert "user's name is Манас" in result
        assert "Address them by name" in result

    def test_both_names_instruction(self):
        result = format_identity_block({"bot_name": "Хюррем", "name": "Манас"})
        assert "Your name is Хюррем" in result
        assert "user's name is Манас" in result

    def test_no_instruction_without_names(self):
        result = format_identity_block({"city": "Chicago"})
        assert "IMPORTANT:" not in result
        assert "City: Chicago" in result
