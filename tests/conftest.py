"""Test fixtures for Finance Bot."""

import os
import uuid

import pytest

# Set test environment before importing app modules
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "testing")

from src.core.context import SessionContext
from src.core.profiles import ProfileConfig, ProfileLoader
from src.gateway.mock import MockGateway
from src.gateway.types import IncomingMessage, MessageType
from src.skills.base import SkillRegistry


@pytest.fixture
def mock_gateway():
    """Mock gateway for testing."""
    return MockGateway()


@pytest.fixture
def sample_context():
    """Sample session context for a trucker owner."""
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[
            {"id": str(uuid.uuid4()), "name": "Дизель", "scope": "business", "icon": "⛽"},
            {"id": str(uuid.uuid4()), "name": "Ремонт", "scope": "business", "icon": "🔧"},
            {"id": str(uuid.uuid4()), "name": "Продукты", "scope": "family", "icon": "🛒"},
        ],
        merchant_mappings=[
            {"merchant_pattern": "Shell", "category_id": "cat-1", "scope": "business"},
            {"merchant_pattern": "Walmart", "category_id": "cat-3", "scope": "family"},
        ],
    )


@pytest.fixture
def member_context():
    """Sample session context for a family member."""
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="member",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[
            {"id": str(uuid.uuid4()), "name": "Продукты", "scope": "family", "icon": "🛒"},
        ],
        merchant_mappings=[],
    )


@pytest.fixture
def text_message():
    """Sample text incoming message."""
    return IncomingMessage(
        id="123",
        user_id="telegram_123",
        chat_id="chat_123",
        type=MessageType.text,
        text="заправился на 50",
    )


@pytest.fixture
def photo_message():
    """Sample photo incoming message."""
    return IncomingMessage(
        id="124",
        user_id="telegram_123",
        chat_id="chat_123",
        type=MessageType.photo,
        photo_bytes=b"fake_photo_data",
    )


@pytest.fixture
def callback_message():
    """Sample callback incoming message."""
    return IncomingMessage(
        id="125",
        user_id="telegram_123",
        chat_id="chat_123",
        type=MessageType.callback,
        callback_data="confirm:tx-123",
    )


@pytest.fixture
def profile_loader():
    """Profile loader with test profiles."""
    return ProfileLoader("config/profiles")


@pytest.fixture
def skill_registry():
    """Populated skill registry."""
    from src.skills import create_registry
    return create_registry()
