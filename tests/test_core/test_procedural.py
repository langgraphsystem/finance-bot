"""Tests for Procedural Memory (Phase 3.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.procedural import (
    INTENT_PROCEDURE_DOMAIN,
    MAX_PROCEDURES_PER_DOMAIN,
    MAX_TOTAL_PROCEDURES,
    PROCEDURAL_DOMAINS,
    PROCEDURAL_INTENTS,
    detect_workflow,
    extract_procedures,
    format_procedures_block,
    get_domain_for_intent,
    get_procedures,
    learn_from_correction,
    save_procedures,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_procedural_domains(self):
        assert "finance" in PROCEDURAL_DOMAINS
        assert "life" in PROCEDURAL_DOMAINS
        assert "writing" in PROCEDURAL_DOMAINS
        assert "email" in PROCEDURAL_DOMAINS
        assert "tasks" in PROCEDURAL_DOMAINS
        assert "booking" in PROCEDURAL_DOMAINS
        assert "calendar" in PROCEDURAL_DOMAINS

    def test_procedural_intents_non_empty(self):
        assert len(PROCEDURAL_INTENTS) > 0
        assert "add_expense" in PROCEDURAL_INTENTS
        assert "draft_message" in PROCEDURAL_INTENTS
        assert "send_email" in PROCEDURAL_INTENTS

    def test_intent_procedure_domain_mapping(self):
        assert INTENT_PROCEDURE_DOMAIN["add_expense"] == "finance"
        assert INTENT_PROCEDURE_DOMAIN["draft_message"] == "writing"
        assert INTENT_PROCEDURE_DOMAIN["send_email"] == "email"
        assert INTENT_PROCEDURE_DOMAIN["create_task"] == "tasks"
        assert INTENT_PROCEDURE_DOMAIN["create_booking"] == "booking"
        assert INTENT_PROCEDURE_DOMAIN["create_event"] == "calendar"
        assert INTENT_PROCEDURE_DOMAIN["track_food"] == "life"

    def test_max_procedures(self):
        assert MAX_PROCEDURES_PER_DOMAIN == 10
        assert MAX_TOTAL_PROCEDURES == 30

    def test_get_domain_for_intent(self):
        assert get_domain_for_intent("add_expense") == "finance"
        assert get_domain_for_intent("unknown_intent") is None


def _mock_db_session(profile_obj):
    """Helper: build async context manager mock for DB session with profile."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile_obj
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = False
    return mock_ctx, mock_session


# ---------------------------------------------------------------------------
# learn_from_correction
# ---------------------------------------------------------------------------
class TestLearnFromCorrection:
    async def test_records_correction(self):
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {}
        mock_ctx, mock_session = _mock_db_session(mock_profile)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await learn_from_correction(
                uid, "correct_category", "Еда", "Кафе",
                context={"merchant": "Starbucks"},
            )

        corrections = mock_profile.learned_patterns["corrections"]
        assert len(corrections) == 1
        assert corrections[0]["intent"] == "correct_category"
        assert corrections[0]["original"] == "Еда"
        assert corrections[0]["corrected"] == "Кафе"
        assert corrections[0]["domain"] == "finance"
        assert corrections[0]["context"]["merchant"] == "Starbucks"
        mock_session.commit.assert_called_once()

    async def test_appends_to_existing_corrections(self):
        existing = [{"intent": "old", "original": "a", "corrected": "b"}]
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {"corrections": existing}
        mock_ctx, _ = _mock_db_session(mock_profile)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await learn_from_correction(uid, "add_expense", "Food", "Cafe")

        corrections = mock_profile.learned_patterns["corrections"]
        assert len(corrections) == 2

    async def test_caps_at_100_corrections(self):
        existing = [{"intent": f"i{i}"} for i in range(100)]
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {"corrections": existing}
        mock_ctx, _ = _mock_db_session(mock_profile)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await learn_from_correction(uid, "new", "a", "b")

        corrections = mock_profile.learned_patterns["corrections"]
        assert len(corrections) == 100

    async def test_no_profile_graceful(self):
        mock_ctx, mock_session = _mock_db_session(None)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await learn_from_correction(uid, "test", "a", "b")

        mock_session.commit.assert_not_called()

    async def test_db_failure_graceful(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await learn_from_correction(uid, "test", "a", "b")


# ---------------------------------------------------------------------------
# detect_workflow
# ---------------------------------------------------------------------------
class TestDetectWorkflow:
    async def test_detects_repeated_bigram(self):
        seq = ["add_expense", "query_stats", "add_expense", "query_stats", "scan_receipt"]
        result = await detect_workflow("uid", seq)
        assert len(result) >= 1
        found = any(
            w["sequence"] == ["add_expense", "query_stats"] and w["count"] >= 2
            for w in result
        )
        assert found

    async def test_too_short_sequence(self):
        result = await detect_workflow("uid", ["add_expense", "query_stats"])
        assert result == []

    async def test_no_repeats(self):
        seq = ["add_expense", "track_food", "create_task", "mood_checkin"]
        result = await detect_workflow("uid", seq)
        assert result == []

    async def test_caps_at_5(self):
        seq = []
        for i in range(20):
            seq.extend([f"a{i}", f"b{i}"] * 3)
        result = await detect_workflow("uid", seq)
        assert len(result) <= 5

    async def test_sorted_by_count(self):
        seq = (
            ["add_expense", "query_stats"] * 5
            + ["track_food", "life_search"] * 3
            + ["create_task", "set_reminder"] * 2
        )
        result = await detect_workflow("uid", seq)
        if len(result) >= 2:
            assert result[0]["count"] >= result[1]["count"]


# ---------------------------------------------------------------------------
# extract_procedures
# ---------------------------------------------------------------------------
class TestExtractProcedures:
    async def test_extracts_rules(self):
        mock_response = MagicMock()
        mock_response.text = (
            "1. КОГДА пользователь добавляет Starbucks, ТОГДА категория = Кафе\n"
            "2. КОГДА пользователь добавляет расход на бензин, ТОГДА scope = business\n"
        )
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        corrections = [
            {
                "intent": "correct_category",
                "original": "Еда",
                "corrected": "Кафе",
                "context": {"merchant": "Starbucks"},
            },
        ]

        with patch("src.core.llm.clients.google_client", return_value=mock_client):
            result = await extract_procedures("finance", corrections)

        assert len(result) == 2
        assert "КОГДА" in result[0]
        assert "ТОГДА" in result[0]

    async def test_empty_corrections(self):
        result = await extract_procedures("finance", [])
        assert result == []

    async def test_llm_failure_returns_empty(self):
        with patch("src.core.llm.clients.google_client", side_effect=Exception("API")):
            result = await extract_procedures("finance", [{"intent": "test"}])
        assert result == []

    async def test_caps_rules(self):
        mock_response = MagicMock()
        lines = "\n".join(
            f"{i}. КОГДА ситуация номер {i}, ТОГДА делай действие номер {i}"
            for i in range(20)
        )
        mock_response.text = lines
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch("src.core.llm.clients.google_client", return_value=mock_client):
            result = await extract_procedures("finance", [{"intent": "test"}])

        assert len(result) <= MAX_PROCEDURES_PER_DOMAIN


# ---------------------------------------------------------------------------
# _parse_procedures
# ---------------------------------------------------------------------------
class TestParseProcedures:
    def test_parses_when_then_format(self):
        from src.core.memory.procedural import _parse_procedures

        text = (
            "- КОГДА пользователь добавляет Starbucks, ТОГДА категория = Кафе\n"
            "- КОГДА пользователь пишет клиенту, ТОГДА тон = деловой\n"
        )
        result = _parse_procedures(text)
        assert len(result) == 2

    def test_skips_short_lines(self):
        from src.core.memory.procedural import _parse_procedures

        text = "short\nline\n- КОГДА условие длинное, ТОГДА выполни действие"
        result = _parse_procedures(text)
        assert len(result) == 1

    def test_accepts_arrow_format(self):
        from src.core.memory.procedural import _parse_procedures

        text = "- Starbucks → категория Кафе (а не Еда)"
        result = _parse_procedures(text)
        assert len(result) == 1

    def test_accepts_long_implicit_rules(self):
        from src.core.memory.procedural import _parse_procedures

        text = "- Пользователь предпочитает краткие ответы без эмодзи в деловой переписке"
        result = _parse_procedures(text)
        assert len(result) == 1

    def test_empty_text(self):
        from src.core.memory.procedural import _parse_procedures

        assert _parse_procedures("") == []
        assert _parse_procedures("   \n  \n") == []


# ---------------------------------------------------------------------------
# get_procedures / save_procedures
# ---------------------------------------------------------------------------
class TestGetSaveProcedures:
    async def test_get_by_domain(self):
        patterns = {
            "procedures": {
                "finance": ["rule1", "rule2"],
                "writing": ["rule3"],
            }
        }
        mock_ctx, _ = _mock_db_session(patterns)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_procedures(uid, domain="finance")

        assert result == ["rule1", "rule2"]

    async def test_get_all_domains(self):
        patterns = {
            "procedures": {
                "finance": ["r1", "r2"],
                "writing": ["r3"],
            }
        }
        mock_ctx, _ = _mock_db_session(patterns)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_procedures(uid)

        assert len(result) == 3

    async def test_get_no_profile(self):
        mock_ctx, _ = _mock_db_session(None)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_procedures(uid)

        assert result == []

    async def test_get_no_procedures_key(self):
        mock_ctx, _ = _mock_db_session({"personality": {}})

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_procedures(uid)

        assert result == []

    async def test_get_db_failure(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await get_procedures(uid)

        assert result == []

    async def test_save_creates_procedures(self):
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {}
        mock_ctx, mock_session = _mock_db_session(mock_profile)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await save_procedures(uid, "finance", ["rule1", "rule2"])

        procedures = mock_profile.learned_patterns["procedures"]
        assert procedures["finance"] == ["rule1", "rule2"]
        mock_session.commit.assert_called_once()

    async def test_save_no_profile(self):
        mock_ctx, mock_session = _mock_db_session(None)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await save_procedures(uid, "finance", ["rule1"])

        mock_session.commit.assert_not_called()

    async def test_save_preserves_other_domains(self):
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {
            "procedures": {"writing": ["old_rule"]},
        }
        mock_ctx, _ = _mock_db_session(mock_profile)

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.db.async_session", return_value=mock_ctx):
            await save_procedures(uid, "finance", ["new_rule"])

        procedures = mock_profile.learned_patterns["procedures"]
        assert procedures["writing"] == ["old_rule"]
        assert procedures["finance"] == ["new_rule"]


# ---------------------------------------------------------------------------
# format_procedures_block
# ---------------------------------------------------------------------------
class TestFormatProceduresBlock:
    def test_empty_returns_empty(self):
        assert format_procedures_block([]) == ""

    def test_formats_with_tags(self):
        rules = ["КОГДА Starbucks, ТОГДА Кафе", "КОГДА бензин, ТОГДА business"]
        result = format_procedures_block(rules)
        assert "<learned_procedures>" in result
        assert "</learned_procedures>" in result
        assert "Starbucks" in result
        assert "бензин" in result

    def test_caps_at_max(self):
        rules = [f"proc_{i} is a long procedure description" for i in range(20)]
        result = format_procedures_block(rules)
        assert result.count("proc_") == MAX_PROCEDURES_PER_DOMAIN


# ---------------------------------------------------------------------------
# Weekly cron integration
# ---------------------------------------------------------------------------
class TestWeeklyCron:
    async def test_cron_processes_users_with_corrections(self):
        """Verify async_procedural_update processes correction history."""
        from src.core.tasks.memory_tasks import async_procedural_update

        mock_user_data = [
            (
                MagicMock(),
                {
                    "corrections": [
                        {
                            "intent": "correct_category",
                            "domain": "finance",
                            "original": "Еда",
                            "corrected": "Кафе",
                        },
                        {
                            "intent": "correct_category",
                            "domain": "finance",
                            "original": "Еда",
                            "corrected": "Кафе",
                        },
                    ],
                    "observations": [],
                },
            )
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = mock_user_data
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.procedural.extract_procedures",
                new_callable=AsyncMock,
                return_value=["КОГДА X, ТОГДА Y"],
            ) as mock_extract,
            patch(
                "src.core.memory.procedural.save_procedures",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            await async_procedural_update.original_func()

        mock_extract.assert_called_once()
        mock_save.assert_called_once()

    async def test_cron_skips_users_without_corrections(self):
        from src.core.tasks.memory_tasks import async_procedural_update

        mock_user_data = [
            (MagicMock(), {"observations": ["some obs"]}),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = mock_user_data
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.procedural.extract_procedures",
                new_callable=AsyncMock,
            ) as mock_extract,
        ):
            await async_procedural_update.original_func()

        mock_extract.assert_not_called()

    async def test_cron_requires_min_2_corrections_per_domain(self):
        from src.core.tasks.memory_tasks import async_procedural_update

        mock_user_data = [
            (
                MagicMock(),
                {
                    "corrections": [
                        {"intent": "i1", "domain": "finance", "original": "a", "corrected": "b"},
                    ],
                },
            )
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = mock_user_data
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.procedural.extract_procedures",
                new_callable=AsyncMock,
            ) as mock_extract,
        ):
            await async_procedural_update.original_func()

        mock_extract.assert_not_called()
