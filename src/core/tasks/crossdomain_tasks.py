"""Cross-domain intelligence — weekly cron discovering cross-domain patterns.

Analyzes correlations between life events and financial transactions to
surface actionable insights: mood × spending, food × budget, tasks ×
calendar patterns, etc. Stores insights in Mem0 life domain.
"""

import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.enums import LifeEventType, TransactionType
from src.core.models.life_event import LifeEvent
from src.core.models.transaction import Transaction
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

# Minimum data thresholds for meaningful analysis
MIN_TRANSACTIONS = 5
MIN_LIFE_EVENTS = 3

# Maximum insights per user per run
MAX_INSIGHTS_PER_USER = 5


def _analyze_mood_spending(
    moods: list[dict], transactions: list[dict],
) -> list[str]:
    """Correlate mood with daily spending."""
    insights: list[str] = []

    # Group spending by date
    daily_spend: dict[date, float] = defaultdict(float)
    for t in transactions:
        if t["type"] == TransactionType.expense:
            daily_spend[t["date"]] += float(t["amount"])

    # Group mood by date
    daily_mood: dict[date, list[int]] = defaultdict(list)
    for m in moods:
        score = (m.get("data") or {}).get("score")
        if score is not None:
            daily_mood[m["date"]].append(int(score))

    # Find dates with both mood and spending
    common_dates = set(daily_spend.keys()) & set(daily_mood.keys())
    if len(common_dates) < 3:
        return insights

    # Compare average spending on good vs bad mood days
    good_spend: list[float] = []
    bad_spend: list[float] = []
    for d in common_dates:
        avg_mood = sum(daily_mood[d]) / len(daily_mood[d])
        if avg_mood >= 4:
            good_spend.append(daily_spend[d])
        elif avg_mood <= 2:
            bad_spend.append(daily_spend[d])

    if good_spend and bad_spend:
        avg_good = sum(good_spend) / len(good_spend)
        avg_bad = sum(bad_spend) / len(bad_spend)
        if avg_bad > avg_good * 1.3:
            insights.append(
                f"Spending tends to increase on low-mood days "
                f"(avg {avg_bad:.0f} vs {avg_good:.0f} on good days)"
            )
        elif avg_good > avg_bad * 1.3:
            insights.append(
                f"Spending tends to increase on good-mood days "
                f"(avg {avg_good:.0f} vs {avg_bad:.0f} on low-mood days)"
            )

    return insights


def _analyze_food_spending(
    food_events: list[dict], transactions: list[dict],
) -> list[str]:
    """Correlate food tracking with food/cafe spending."""
    insights: list[str] = []

    # Count food events per day
    food_days = Counter(e["date"] for e in food_events)

    # Count cafe/restaurant spending per day
    food_keywords = {
        "cafe", "coffee", "restaurant", "food", "lunch", "dinner",
        "кофе", "кафе", "ресторан",
    }
    food_spend_days: dict[date, float] = defaultdict(float)
    for t in transactions:
        if t["type"] != TransactionType.expense:
            continue
        desc = (t.get("description") or "").lower()
        merchant = (t.get("merchant") or "").lower()
        if any(kw in desc or kw in merchant for kw in food_keywords):
            food_spend_days[t["date"]] += float(t["amount"])

    # Days with food tracking vs without
    tracked_dates = set(food_days.keys())
    spend_dates = set(food_spend_days.keys())

    tracked_and_spent = tracked_dates & spend_dates
    untracked_and_spent = spend_dates - tracked_dates

    if tracked_and_spent and untracked_and_spent:
        avg_tracked = sum(food_spend_days[d] for d in tracked_and_spent) / len(tracked_and_spent)
        avg_untracked = sum(food_spend_days[d] for d in untracked_and_spent) / len(
            untracked_and_spent
        )
        if avg_untracked > avg_tracked * 1.2 and len(untracked_and_spent) >= 2:
            insights.append(
                f"Food spending is lower on days you track meals "
                f"(avg {avg_tracked:.0f} vs {avg_untracked:.0f})"
            )

    return insights


def _analyze_time_patterns(
    transactions: list[dict], life_events: list[dict],
) -> list[str]:
    """Analyze day-of-week patterns across domains."""
    insights: list[str] = []

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Spending by day of week
    daily_totals: dict[int, list[float]] = defaultdict(list)
    for t in transactions:
        if t["type"] == TransactionType.expense:
            dow = t["date"].weekday()
            daily_totals[dow].append(float(t["amount"]))

    if daily_totals:
        avg_by_day = {dow: sum(v) / len(v) for dow, v in daily_totals.items() if v}
        if avg_by_day:
            peak_day = max(avg_by_day, key=avg_by_day.get)
            low_day = min(avg_by_day, key=avg_by_day.get)
            if avg_by_day[peak_day] > avg_by_day[low_day] * 1.5 and len(avg_by_day) >= 4:
                insights.append(
                    f"Highest spending on {day_names[peak_day]}s "
                    f"(avg {avg_by_day[peak_day]:.0f}), lowest on "
                    f"{day_names[low_day]}s ({avg_by_day[low_day]:.0f})"
                )

    # Life event frequency by day
    life_by_day: dict[int, int] = Counter()
    for e in life_events:
        life_by_day[e["date"].weekday()] += 1

    if life_by_day and len(life_by_day) >= 4:
        most_active = life_by_day.most_common(1)[0]
        least_active = life_by_day.most_common()[-1]
        if most_active[1] > least_active[1] * 2:
            insights.append(
                f"Most life-tracking activity on {day_names[most_active[0]]}s "
                f"({most_active[1]} events), least on "
                f"{day_names[least_active[0]]}s ({least_active[1]})"
            )

    return insights


def _analyze_drink_patterns(
    drink_events: list[dict], transactions: list[dict],
) -> list[str]:
    """Correlate drink tracking with cafe spending."""
    insights: list[str] = []

    # Count drinks per day
    drink_count: dict[date, int] = Counter(e["date"] for e in drink_events)
    heavy_drink_days = {d for d, c in drink_count.items() if c >= 3}

    if not heavy_drink_days:
        return insights

    # Check spending on heavy-drink days vs others
    spend_heavy: list[float] = []
    spend_normal: list[float] = []
    daily_spend: dict[date, float] = defaultdict(float)
    for t in transactions:
        if t["type"] == TransactionType.expense:
            daily_spend[t["date"]] += float(t["amount"])

    for d, total in daily_spend.items():
        if d in heavy_drink_days:
            spend_heavy.append(total)
        else:
            spend_normal.append(total)

    if spend_heavy and spend_normal:
        avg_heavy = sum(spend_heavy) / len(spend_heavy)
        avg_normal = sum(spend_normal) / len(spend_normal)
        if avg_heavy > avg_normal * 1.3:
            insights.append(
                f"Spending is higher on days with 3+ drinks "
                f"(avg {avg_heavy:.0f} vs {avg_normal:.0f})"
            )

    return insights


async def _get_crossdomain_data(
    user_id: str, family_id: str, lookback_days: int = 30,
) -> tuple[list[dict], list[dict]]:
    """Load transactions and life events for analysis."""
    import uuid

    uid = uuid.UUID(user_id)
    fid = uuid.UUID(family_id)
    cutoff = date.today() - timedelta(days=lookback_days)

    async with async_session() as session:
        # Transactions
        tx_result = await session.execute(
            select(
                Transaction.amount,
                Transaction.type,
                Transaction.date,
                Transaction.description,
                Transaction.merchant,
            )
            .where(Transaction.family_id == fid, Transaction.date >= cutoff)
            .order_by(Transaction.date)
        )
        transactions = [
            {
                "amount": row[0],
                "type": row[1],
                "date": row[2],
                "description": row[3],
                "merchant": row[4],
            }
            for row in tx_result.all()
        ]

        # Life events
        le_result = await session.execute(
            select(LifeEvent.type, LifeEvent.date, LifeEvent.data, LifeEvent.tags)
            .where(LifeEvent.user_id == uid, LifeEvent.date >= cutoff)
            .order_by(LifeEvent.date)
        )
        life_events = [
            {
                "type": row[0],
                "date": row[1],
                "data": row[2],
                "tags": row[3],
            }
            for row in le_result.all()
        ]

    return transactions, life_events


async def _store_insights(user_id: str, insights: list[str]) -> int:
    """Store cross-domain insights in Mem0 life domain."""
    stored = 0
    try:
        from src.core.memory.mem0_client import add_memory
        from src.core.memory.mem0_domains import MemoryDomain

        for insight in insights[:MAX_INSIGHTS_PER_USER]:
            await add_memory(
                content=f"[Cross-domain insight] {insight}",
                user_id=user_id,
                metadata={"category": "life_insights", "source": "crossdomain_cron"},
                domain=MemoryDomain.life,
            )
            stored += 1
    except Exception as e:
        logger.error("Failed to store cross-domain insights: %s", e)

    return stored


@broker.task(schedule=[{"cron": "0 5 * * 0"}])  # Sunday at 5am UTC
async def async_crossdomain_insights() -> None:
    """Weekly cron: discover cross-domain patterns for all users."""
    async with async_session() as session:
        result = await session.execute(select(User.id, User.family_id))
        users = result.all()

    total_insights = 0
    for user_id, family_id in users:
        try:
            transactions, life_events = await _get_crossdomain_data(
                str(user_id), str(family_id)
            )

            # Skip users with insufficient data
            if len(transactions) < MIN_TRANSACTIONS and len(life_events) < MIN_LIFE_EVENTS:
                continue

            insights: list[str] = []

            # Separate life events by type
            moods = [e for e in life_events if e["type"] == LifeEventType.mood]
            food_events = [e for e in life_events if e["type"] == LifeEventType.food]
            drink_events = [e for e in life_events if e["type"] == LifeEventType.drink]

            # Run analysis modules
            if moods and transactions:
                insights.extend(_analyze_mood_spending(moods, transactions))
            if food_events and transactions:
                insights.extend(_analyze_food_spending(food_events, transactions))
            if drink_events and transactions:
                insights.extend(_analyze_drink_patterns(drink_events, transactions))
            if transactions or life_events:
                insights.extend(_analyze_time_patterns(transactions, life_events))

            if insights:
                stored = await _store_insights(str(user_id), insights)
                total_insights += stored
                logger.info(
                    "Cross-domain: user %s — %d insights stored", user_id, stored
                )

        except Exception as e:
            logger.error("Cross-domain analysis failed for user %s: %s", user_id, e)

    logger.info("Cross-domain weekly job complete: %d total insights", total_insights)
