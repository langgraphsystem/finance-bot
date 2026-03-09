"""Tests for member management skills (invite, list, manage)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext


@pytest.fixture
def owner_context():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        permissions=["invite_members", "manage_members"],
    )


@pytest.fixture
def member_context():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="member",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        permissions=["view_finance"],
    )


@pytest.fixture
def text_message():
    from src.gateway.types import IncomingMessage, MessageType

    return IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="invite someone",
    )


# --- InviteMemberSkill ---


async def test_invite_member_shows_type_buttons(owner_context, text_message):
    from src.skills.invite_member.handler import skill

    result = await skill.execute(text_message, owner_context, {})
    assert "membership type" in result.response_text.lower() or "Invite" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    callbacks = [b["callback"] for b in result.buttons]
    assert "invite:type:family" in callbacks
    assert "invite:type:worker" in callbacks


async def test_invite_member_denied_without_permission(member_context, text_message):
    from src.skills.invite_member.handler import skill

    result = await skill.execute(text_message, member_context, {})
    assert "permission" in result.response_text.lower() or "denied" in result.response_text.lower()
    assert result.buttons is None or result.buttons == []


# --- ListMembersSkill ---


async def test_list_members_shows_members(owner_context, text_message):
    from src.skills.list_members.handler import skill

    mock_membership = MagicMock()
    mock_membership.role = MagicMock()
    mock_membership.role.value = "owner"
    mock_membership.membership_type = MagicMock()
    mock_membership.membership_type.value = "family"

    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_membership, "Test User")]

    with patch("src.skills.list_members.handler.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await skill.execute(text_message, owner_context, {})

    assert "Test User" in result.response_text
    assert "Owner" in result.response_text


async def test_list_members_empty(owner_context, text_message):
    from src.skills.list_members.handler import skill

    mock_result = MagicMock()
    mock_result.all.return_value = []

    with patch("src.skills.list_members.handler.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await skill.execute(text_message, owner_context, {})

    assert "no members" in result.response_text.lower() or "No members" in result.response_text


async def test_list_members_shows_manage_button_for_owner(owner_context, text_message):
    from src.skills.list_members.handler import skill

    mock_membership = MagicMock()
    mock_membership.role = MagicMock()
    mock_membership.role.value = "partner"
    mock_membership.membership_type = MagicMock()
    mock_membership.membership_type.value = "family"

    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_membership, "Partner")]

    with patch("src.skills.list_members.handler.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await skill.execute(text_message, owner_context, {})

    assert result.buttons is not None
    callbacks = [b["callback"] for b in result.buttons]
    assert "members:manage" in callbacks


# --- ManageMemberSkill ---


async def test_manage_member_denied_without_permission(member_context, text_message):
    from src.skills.manage_member.handler import skill

    result = await skill.execute(text_message, member_context, {})
    assert "permission" in result.response_text.lower() or "denied" in result.response_text.lower()


async def test_manage_member_shows_options_for_owner(owner_context, text_message):
    from src.skills.manage_member.handler import skill

    result = await skill.execute(text_message, owner_context, {})
    assert "management" in result.response_text.lower() or "manage" in result.response_text.lower()
