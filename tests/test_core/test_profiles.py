"""Tests for ProfileLoader."""


def test_profiles_loaded(profile_loader):
    profiles = profile_loader.all_profiles()
    assert len(profiles) == 7


def test_match_trucker(profile_loader):
    match = profile_loader.match("я дальнобойщик")
    assert match is not None
    assert match.name == "Трак-овнер"


def test_match_taxi(profile_loader):
    match = profile_loader.match("работаю в uber")
    assert match is not None
    assert match.name == "Таксист"


def test_match_household(profile_loader):
    match = profile_loader.match("просто расходы")
    assert match is not None
    assert match.name == "Домохозяйство"


def test_match_no_match(profile_loader):
    match = profile_loader.match("something random")
    assert match is None


def test_get_by_name(profile_loader):
    profile = profile_loader.get("trucker")
    assert profile is not None
    assert profile.currency == "USD"


def test_trucker_has_special_features(profile_loader):
    profile = profile_loader.get("trucker")
    assert profile.special_features.get("ifta") is True
    assert profile.special_features.get("loads_tracking") is True


def test_household_no_business_categories(profile_loader):
    profile = profile_loader.get("household")
    assert profile.categories.get("business") == []


def test_match_delivery(profile_loader):
    match = profile_loader.match("я курьер доставка")
    assert match is not None
    assert match.name == "Доставка"


def test_match_flowers(profile_loader):
    match = profile_loader.match("цветочный магазин")
    assert match is not None
    assert match.name == "Цветочный бизнес"


def test_match_manicure(profile_loader):
    match = profile_loader.match("делаю маникюр")
    assert match is not None
    assert match.name == "Маникюр / Салон красоты"


def test_match_construction(profile_loader):
    match = profile_loader.match("занимаюсь строительство")
    assert match is not None
    assert match.name == "Строительство"
