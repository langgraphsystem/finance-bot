"""Family management — creation, invite codes, joining."""

import secrets
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.category import Category
from src.core.models.enums import ConversationState, Scope, UserRole
from src.core.models.family import Family
from src.core.models.user import User
from src.core.models.user_context import UserContext


def generate_invite_code() -> str:
    """Generate a unique 8-character invite code."""
    return secrets.token_urlsafe(6)[:8].upper()


async def create_family(
    session: AsyncSession,
    owner_telegram_id: int,
    owner_name: str,
    business_type: str | None,
    language: str = "ru",
    currency: str = "USD",
) -> tuple[Family, User]:
    """Create a new family with owner and default categories."""
    family = Family(
        name=f"Семья {owner_name}",
        invite_code=generate_invite_code(),
        currency=currency,
    )
    session.add(family)
    await session.flush()

    user = User(
        family_id=family.id,
        telegram_id=owner_telegram_id,
        name=owner_name,
        role=UserRole.owner,
        business_type=business_type,
        language=language,
        onboarded=True,
    )
    session.add(user)
    await session.flush()

    # Create user context
    ctx = UserContext(
        user_id=user.id,
        family_id=family.id,
        session_id=uuid.uuid4(),
        conversation_state=ConversationState.normal,
        message_count=0,
    )
    session.add(ctx)

    # Create default family categories
    await _create_family_categories(session, family.id)

    # Create business categories from profile
    if business_type:
        await _create_business_categories(session, family.id, business_type)

    await session.commit()
    return family, user


async def join_family(
    session: AsyncSession,
    invite_code: str,
    telegram_id: int,
    name: str,
    language: str = "ru",
) -> tuple[Family, User] | None:
    """Join existing family by invite code."""
    result = await session.execute(select(Family).where(Family.invite_code == invite_code))
    family = result.scalar_one_or_none()
    if not family:
        return None

    # Check if user already exists
    existing = await session.execute(select(User).where(User.telegram_id == telegram_id))
    if existing.scalar_one_or_none():
        return None

    user = User(
        family_id=family.id,
        telegram_id=telegram_id,
        name=name,
        role=UserRole.member,
        language=language,
        onboarded=True,
    )
    session.add(user)
    await session.flush()

    ctx = UserContext(
        user_id=user.id,
        family_id=family.id,
        session_id=uuid.uuid4(),
        conversation_state=ConversationState.normal,
        message_count=0,
    )
    session.add(ctx)
    await session.commit()

    return family, user


async def _create_family_categories(session: AsyncSession, family_id: uuid.UUID) -> None:
    """Create default family categories from _family_defaults.yaml."""
    try:
        with open("config/profiles/_family_defaults.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for cat_data in data.get("family_categories", []):
            cat = Category(
                family_id=family_id,
                name=cat_data["name"],
                scope=Scope.family,
                icon=cat_data.get("icon", "📦"),
                is_default=True,
            )
            session.add(cat)
    except FileNotFoundError:
        pass


async def _create_business_categories(
    session: AsyncSession,
    family_id: uuid.UUID,
    business_type: str,
) -> None:
    """Create business categories from profile YAML."""
    from src.core.profiles import ProfileLoader

    loader = ProfileLoader("config/profiles")
    profile = loader.get(business_type)
    if not profile:
        return

    for cat_data in profile.categories.get("business", []):
        cat = Category(
            family_id=family_id,
            name=cat_data["name"],
            scope=Scope.business,
            icon=cat_data.get("icon", "📦"),
            is_default=True,
            business_type=business_type,
        )
        session.add(cat)
