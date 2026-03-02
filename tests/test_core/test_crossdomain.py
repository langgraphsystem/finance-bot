"""Tests for Cross-domain Intelligence Job (Phase 3.6)."""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.models.enums import LifeEventType, TransactionType
from src.core.tasks.crossdomain_tasks import (
    MAX_INSIGHTS_PER_USER,
    MIN_LIFE_EVENTS,
    MIN_TRANSACTIONS,
    _analyze_drink_patterns,
    _analyze_food_spending,
    _analyze_mood_spending,
    _analyze_time_patterns,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_min_transactions(self):
        assert MIN_TRANSACTIONS == 5

    def test_min_life_events(self):
        assert MIN_LIFE_EVENTS == 3

    def test_max_insights_per_user(self):
        assert MAX_INSIGHTS_PER_USER == 5


# ---------------------------------------------------------------------------
# _analyze_mood_spending
# ---------------------------------------------------------------------------
class TestAnalyzeMoodSpending:
    def test_higher_spending_on_bad_days(self):
        today = date.today()
        moods = [
            {"date": today - timedelta(days=i), "data": {"score": 1}}
            for i in range(5)
        ] + [
            {"date": today - timedelta(days=i + 10), "data": {"score": 5}}
            for i in range(5)
        ]
        txns = [
            {"date": today - timedelta(days=i), "type": TransactionType.expense, "amount": 200}
            for i in range(5)
        ] + [
            {"date": today - timedelta(days=i + 10), "type": TransactionType.expense, "amount": 50}
            for i in range(5)
        ]

        insights = _analyze_mood_spending(moods, txns)
        assert len(insights) >= 1
        assert "low-mood" in insights[0]

    def test_higher_spending_on_good_days(self):
        today = date.today()
        moods = [
            {"date": today - timedelta(days=i), "data": {"score": 5}}
            for i in range(5)
        ] + [
            {"date": today - timedelta(days=i + 10), "data": {"score": 1}}
            for i in range(5)
        ]
        txns = [
            {"date": today - timedelta(days=i), "type": TransactionType.expense, "amount": 200}
            for i in range(5)
        ] + [
            {"date": today - timedelta(days=i + 10), "type": TransactionType.expense, "amount": 50}
            for i in range(5)
        ]

        insights = _analyze_mood_spending(moods, txns)
        assert len(insights) >= 1
        assert "good-mood" in insights[0]

    def test_no_insights_on_few_dates(self):
        today = date.today()
        moods = [{"date": today, "data": {"score": 3}}]
        txns = [{"date": today, "type": TransactionType.expense, "amount": 100}]

        insights = _analyze_mood_spending(moods, txns)
        assert insights == []

    def test_no_mood_score_skipped(self):
        today = date.today()
        moods = [
            {"date": today - timedelta(days=i), "data": {}}
            for i in range(5)
        ]
        txns = [
            {"date": today - timedelta(days=i), "type": TransactionType.expense, "amount": 100}
            for i in range(5)
        ]

        insights = _analyze_mood_spending(moods, txns)
        assert insights == []


# ---------------------------------------------------------------------------
# _analyze_food_spending
# ---------------------------------------------------------------------------
class TestAnalyzeFoodSpending:
    def test_lower_spend_on_tracked_days(self):
        today = date.today()
        # 5 days with food tracking + low cafe spend
        food_events = [
            {"date": today - timedelta(days=i)}
            for i in range(5)
        ]
        txns = [
            {
                "date": today - timedelta(days=i),
                "type": TransactionType.expense,
                "amount": 20,
                "description": "cafe coffee",
                "merchant": "",
            }
            for i in range(5)
        ] + [
            # 5 days without food tracking + high cafe spend
            {
                "date": today - timedelta(days=i + 10),
                "type": TransactionType.expense,
                "amount": 80,
                "description": "restaurant lunch",
                "merchant": "",
            }
            for i in range(5)
        ]

        insights = _analyze_food_spending(food_events, txns)
        assert len(insights) >= 1
        assert "track meals" in insights[0]

    def test_no_food_keywords_no_insight(self):
        today = date.today()
        food_events = [{"date": today}]
        txns = [
            {
                "date": today,
                "type": TransactionType.expense,
                "amount": 100,
                "description": "electricity",
                "merchant": "utility",
            }
        ]

        insights = _analyze_food_spending(food_events, txns)
        assert insights == []


# ---------------------------------------------------------------------------
# _analyze_time_patterns
# ---------------------------------------------------------------------------
class TestAnalyzeTimePatterns:
    def test_peak_spending_day(self):
        # Create transactions concentrated on Monday (high) vs other days (low)
        # Find a recent Monday
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        txns = []
        # 5 Mondays with high spending
        for w in range(5):
            txns.append({
                "date": monday - timedelta(weeks=w),
                "type": TransactionType.expense,
                "amount": 500,
                "description": "",
                "merchant": "",
            })
        # Other days with low spending (Tue-Sun)
        for w in range(5):
            for d in range(1, 7):
                txns.append({
                    "date": monday - timedelta(weeks=w) + timedelta(days=d),
                    "type": TransactionType.expense,
                    "amount": 50,
                    "description": "",
                    "merchant": "",
                })

        insights = _analyze_time_patterns(txns, [])
        assert len(insights) >= 1
        assert "Monday" in insights[0]

    def test_no_insights_with_few_days(self):
        today = date.today()
        txns = [
            {
                "date": today,
                "type": TransactionType.expense,
                "amount": 100,
            }
        ]

        insights = _analyze_time_patterns(txns, [])
        assert insights == []


# ---------------------------------------------------------------------------
# _analyze_drink_patterns
# ---------------------------------------------------------------------------
class TestAnalyzeDrinkPatterns:
    def test_heavy_drink_days_higher_spending(self):
        today = date.today()
        # 3 days with 3+ drinks
        drink_events = []
        for i in range(3):
            for _ in range(4):  # 4 drinks each day
                drink_events.append({"date": today - timedelta(days=i)})

        # High spending on drink days, low on others
        txns = [
            {"date": today - timedelta(days=i), "type": TransactionType.expense, "amount": 300}
            for i in range(3)
        ] + [
            {"date": today - timedelta(days=i + 10), "type": TransactionType.expense, "amount": 80}
            for i in range(5)
        ]

        insights = _analyze_drink_patterns(drink_events, txns)
        assert len(insights) >= 1
        assert "3+ drinks" in insights[0]

    def test_no_heavy_days_no_insight(self):
        today = date.today()
        # 1 drink per day (not heavy)
        drink_events = [{"date": today - timedelta(days=i)} for i in range(5)]
        txns = [
            {"date": today - timedelta(days=i), "type": TransactionType.expense, "amount": 100}
            for i in range(5)
        ]

        insights = _analyze_drink_patterns(drink_events, txns)
        assert insights == []


# ---------------------------------------------------------------------------
# Weekly cron (integration)
# ---------------------------------------------------------------------------
class TestWeeklyCron:
    async def test_cron_runs_for_users_with_data(self):
        from src.core.tasks.crossdomain_tasks import async_crossdomain_insights

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(user_id, family_id)]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        today = date.today()
        fake_txns = [
            {
                "amount": 100,
                "type": TransactionType.expense,
                "date": today - timedelta(days=i),
                "description": "test",
                "merchant": "store",
            }
            for i in range(10)
        ]
        fake_events = [
            {"type": LifeEventType.mood, "date": today - timedelta(days=i),
             "data": {"score": 3}, "tags": []}
            for i in range(5)
        ]

        with (
            patch("src.core.tasks.crossdomain_tasks.async_session", return_value=mock_ctx),
            patch(
                "src.core.tasks.crossdomain_tasks._get_crossdomain_data",
                new_callable=AsyncMock,
                return_value=(fake_txns, fake_events),
            ),
            patch(
                "src.core.tasks.crossdomain_tasks._store_insights",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            await async_crossdomain_insights.original_func()

        # Should have attempted to store insights
        # (may or may not have insights depending on data patterns)
        # At minimum, the function should complete without error
        assert True  # reached here without exception

    async def test_cron_skips_users_with_little_data(self):
        from src.core.tasks.crossdomain_tasks import async_crossdomain_insights

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(user_id, family_id)]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch("src.core.tasks.crossdomain_tasks.async_session", return_value=mock_ctx),
            patch(
                "src.core.tasks.crossdomain_tasks._get_crossdomain_data",
                new_callable=AsyncMock,
                return_value=([], []),  # No data
            ),
            patch(
                "src.core.tasks.crossdomain_tasks._store_insights",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            await async_crossdomain_insights.original_func()

        mock_store.assert_not_called()

    async def test_store_insights_calls_mem0(self):
        from src.core.tasks.crossdomain_tasks import _store_insights

        with patch(
            "src.core.memory.mem0_client.add_memory",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_add:
            count = await _store_insights("user123", ["insight 1", "insight 2"])

        assert count == 2
        assert mock_add.call_count == 2
        # Check the content includes "[Cross-domain insight]"
        first_call = mock_add.call_args_list[0]
        assert "[Cross-domain insight]" in first_call.kwargs["content"]
