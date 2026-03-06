"""Tests for access filtering during SessionContext assembly."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import build_session_context


def _scalar_one_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _scalar_one_or_none_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars.return_value = values
    return result


def _profile_result(row):
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


async def test_build_session_context_filters_non_family_items_for_member():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.family_id = uuid.uuid4()
    user.telegram_id = 123456
    user.role = MagicMock()
    user.role.value = "member"
    user.language = "ru"
    user.business_type = "trucker"

    family = MagicMock()
    family.currency = "USD"

    category_family = MagicMock()
    category_family.id = uuid.uuid4()
    category_family.name = "Продукты"
    category_family.icon = "🛒"
    category_family.scope = MagicMock()
    category_family.scope.value = "family"

    category_business = MagicMock()
    category_business.id = uuid.uuid4()
    category_business.name = "Дизель"
    category_business.icon = "⛽"
    category_business.scope = MagicMock()
    category_business.scope.value = "business"

    mapping_family = MagicMock()
    mapping_family.merchant_pattern = "Walmart"
    mapping_family.category_id = uuid.uuid4()
    mapping_family.scope = MagicMock()
    mapping_family.scope.value = "family"

    mapping_business = MagicMock()
    mapping_business.merchant_pattern = "Shell"
    mapping_business.category_id = uuid.uuid4()
    mapping_business.scope = MagicMock()
    mapping_business.scope.value = "business"

    with (
        patch("api.main.async_session") as mock_session_maker,
        patch("api.main.profile_loader.get", return_value=None),
    ):
        mock_session = AsyncMock()
        mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(user),
                _scalar_one_result(family),
                _scalars_result([category_family, category_business]),
                _scalars_result([mapping_family, mapping_business]),
                _profile_result(None),
            ]
        )

        context = await build_session_context(str(user.telegram_id))

    assert context is not None
    assert [item["scope"] for item in context.categories] == ["family"]
    assert [item["scope"] for item in context.merchant_mappings] == ["family"]
