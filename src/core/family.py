"""Family management — creation, invite codes, joining."""

import secrets
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.category import Category
from src.core.models.enums import ConversationState, Scope, UserRole
from src.core.models.family import Family
from src.core.models.merchant_mapping import MerchantMapping
from src.core.models.user import User
from src.core.models.user_context import UserContext
from src.core.models.user_profile import UserProfile


def generate_invite_code() -> str:
    """Generate a unique 8-character invite code."""
    return secrets.token_urlsafe(6)[:8].upper()


async def get_invite_code(session: AsyncSession, family_id: str) -> str | None:
    """Retrieve the invite code for a family by its ID."""
    result = await session.execute(
        select(Family.invite_code).where(Family.id == uuid.UUID(family_id))
    )
    return result.scalar_one_or_none()


async def create_family(
    session: AsyncSession,
    owner_telegram_id: int,
    owner_name: str,
    business_type: str | None,
    language: str = "ru",
    currency: str = "USD",
) -> tuple[Family, User]:
    """Create a new family with owner and default categories.

    If a user with this telegram_id already exists, returns their existing family+user.
    """
    # Check if user already exists (prevents UniqueViolationError)
    existing = await session.execute(select(User).where(User.telegram_id == owner_telegram_id))
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        family_result = await session.execute(
            select(Family).where(Family.id == existing_user.family_id)
        )
        existing_family = family_result.scalar_one_or_none()
        if existing_family:
            return existing_family, existing_user

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

    # Create user profile (required for city, timezone, learned_patterns)
    profile = UserProfile(
        user_id=user.id,
        family_id=family.id,
        display_name=owner_name,
        timezone="America/New_York",
        preferred_language=language,
    )
    session.add(profile)

    # Create default family categories
    await _create_family_categories(session, family.id)

    # Create business categories from profile
    if business_type:
        await _create_business_categories(session, family.id, business_type)

    await session.commit()
    return family, user


async def create_family_for_channel(
    session: AsyncSession,
    channel: str,
    channel_user_id: str,
    owner_name: str,
    business_type: str | None,
    language: str = "en",
    currency: str = "USD",
) -> tuple[Family, User]:
    """Create a new family for a user from any channel (Slack, WhatsApp, SMS, Telegram).

    For Telegram, delegates to create_family(). For other channels, creates a User
    with telegram_id=None and auto-creates a ChannelLink entry.
    """
    if channel == "telegram":
        return await create_family(
            session,
            owner_telegram_id=int(channel_user_id),
            owner_name=owner_name,
            business_type=business_type,
            language=language,
            currency=currency,
        )

    # Check if this channel user is already linked
    from src.core.models.channel_link import ChannelLink
    from src.core.models.enums import ChannelType

    ch_type = ChannelType(channel)
    existing_link = await session.execute(
        select(ChannelLink).where(
            ChannelLink.channel == ch_type,
            ChannelLink.channel_user_id == channel_user_id,
        )
    )
    link = existing_link.scalar_one_or_none()
    if link:
        user_result = await session.execute(select(User).where(User.id == link.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            family_result = await session.execute(
                select(Family).where(Family.id == user.family_id)
            )
            family = family_result.scalar_one_or_none()
            if family:
                return family, user

    family = Family(
        name=f"Family {owner_name}",
        invite_code=generate_invite_code(),
        currency=currency,
    )
    session.add(family)
    await session.flush()

    user = User(
        family_id=family.id,
        telegram_id=None,
        name=owner_name,
        role=UserRole.owner,
        business_type=business_type,
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

    profile = UserProfile(
        user_id=user.id,
        family_id=family.id,
        display_name=owner_name,
        timezone="America/New_York",
        preferred_language=language,
    )
    session.add(profile)

    # Create channel link
    channel_link = ChannelLink(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family.id,
        channel=ch_type,
        channel_user_id=channel_user_id,
        is_primary=True,
    )
    session.add(channel_link)

    await _create_family_categories(session, family.id)
    if business_type:
        await _create_business_categories(session, family.id, business_type)

    await session.commit()
    return family, user


async def join_family_for_channel(
    session: AsyncSession,
    invite_code: str,
    channel: str,
    channel_user_id: str,
    name: str,
    language: str = "en",
) -> tuple[Family, User] | None:
    """Join existing family by invite code from any channel."""
    if channel == "telegram":
        return await join_family(
            session,
            invite_code=invite_code,
            telegram_id=int(channel_user_id),
            name=name,
            language=language,
        )

    result = await session.execute(select(Family).where(Family.invite_code == invite_code))
    family = result.scalar_one_or_none()
    if not family:
        return None

    from src.core.models.channel_link import ChannelLink
    from src.core.models.enums import ChannelType

    ch_type = ChannelType(channel)

    # Check if already linked
    existing_link = await session.execute(
        select(ChannelLink).where(
            ChannelLink.channel == ch_type,
            ChannelLink.channel_user_id == channel_user_id,
        )
    )
    if existing_link.scalar_one_or_none():
        return None

    user = User(
        family_id=family.id,
        telegram_id=None,
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

    profile = UserProfile(
        user_id=user.id,
        family_id=family.id,
        display_name=name,
        timezone="America/New_York",
        preferred_language=language,
    )
    session.add(profile)

    channel_link = ChannelLink(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family.id,
        channel=ch_type,
        channel_user_id=channel_user_id,
        is_primary=True,
    )
    session.add(channel_link)

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

    # Create user profile
    profile = UserProfile(
        user_id=user.id,
        family_id=family.id,
        display_name=name,
        timezone="America/New_York",
        preferred_language=language,
    )
    session.add(profile)

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
    """Create business categories and merchant mappings from profile YAML."""
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
        await session.flush()

        # Auto-create merchant mappings from profile YAML
        for merchant in cat_data.get("merchants", []):
            mapping = MerchantMapping(
                family_id=family_id,
                merchant_pattern=merchant.lower(),
                category_id=cat.id,
                scope=Scope.business,
                confidence=0.9,
            )
            session.add(mapping)
