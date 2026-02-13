from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.core.request_context import get_current_family_id

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.app_env == "development",
    pool_size=10,
    max_overflow=20,
    connect_args={"statement_cache_size": 0},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a session, automatically applying RLS if a family context is set.

    When ``set_family_context(family_id)`` has been called in the current
    async context (e.g. by the message router), the session will execute
    ``SELECT set_config('app.current_family_id', ..., true)`` so that
    PostgreSQL RLS policies can reference ``current_setting('app.current_family_id')``.

    If no family context is active the session is returned as-is, which is
    correct for non-family-scoped operations (health checks, onboarding, etc.).
    """
    async with async_session() as session:
        family_id = get_current_family_id()
        if family_id:
            await session.execute(
                text("SELECT set_config('app.current_family_id', :fid, true)"),
                {"fid": family_id},
            )
        yield session


@asynccontextmanager
async def rls_session(family_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session with RLS context set for family isolation.

    Use this when you need to explicitly bind a session to a specific family
    regardless of the current request context (e.g. in background tasks that
    iterate over multiple families).

    Usage::

        async with rls_session(family_id) as session:
            result = await session.execute(select(Transaction))
    """
    async with async_session() as session:
        await session.execute(
            text("SELECT set_config('app.current_family_id', :fid, true)"),
            {"fid": family_id},
        )
        yield session
