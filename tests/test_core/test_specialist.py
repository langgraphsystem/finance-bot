"""Tests for Specialist Config Engine."""

from src.core.specialist import (
    SpecialistConfig,
    SpecialistService,
    SpecialistStaff,
    WorkingHours,
    build_specialist_system_block,
)


def _sample_specialist() -> SpecialistConfig:
    return SpecialistConfig(
        greeting={"ru": "Привет! Салон красоты.", "en": "Hi! Beauty salon."},
        services=[
            SpecialistService(name="Маникюр", duration_min=60, price=2000, currency="RUB"),
            SpecialistService(name="Педикюр", duration_min=90, price=2500),
        ],
        staff=[
            SpecialistStaff(name="Анна", specialties=["маникюр", "гель-лак"]),
            SpecialistStaff(name="Мария", specialties=["педикюр"], schedule="Mon-Fri 10-18"),
        ],
        working_hours=WorkingHours(default="10:00-20:00", sat="10:00-18:00", sun="closed"),
        capabilities=["booking", "price_inquiry", "faq"],
        faq=[{"q": "Сколько стоит?", "a": "2000 руб"}],
        system_prompt_extra="Будь вежлива.",
    )


# --- SpecialistConfig ---


def test_specialist_config_from_dict():
    data = {
        "greeting": {"en": "Hello!"},
        "services": [{"name": "Cut", "duration_min": 30, "price": 50}],
    }
    cfg = SpecialistConfig(**data)
    assert cfg.services[0].name == "Cut"
    assert cfg.services[0].price == 50


def test_specialist_config_defaults():
    cfg = SpecialistConfig()
    assert cfg.services == []
    assert cfg.staff == []
    assert cfg.capabilities == ["booking", "price_inquiry", "faq", "reminder"]
    assert cfg.working_hours.default is None


def test_get_greeting_exact_language():
    cfg = _sample_specialist()
    assert cfg.get_greeting("ru") == "Привет! Салон красоты."
    assert cfg.get_greeting("en") == "Hi! Beauty salon."


def test_get_greeting_fallback():
    cfg = SpecialistConfig(greeting={"ru": "Привет!"})
    assert cfg.get_greeting("es") == "Привет!"


def test_get_greeting_empty():
    cfg = SpecialistConfig()
    assert cfg.get_greeting("en") is None


# --- WorkingHours ---


def test_working_hours_default():
    wh = WorkingHours(default="09:00-18:00")
    assert wh.for_day(0) == "09:00-18:00"  # Monday
    assert wh.for_day(3) == "09:00-18:00"  # Thursday


def test_working_hours_specific_day():
    wh = WorkingHours(default="09:00-18:00", sat="10:00-15:00", sun="closed")
    assert wh.for_day(5) == "10:00-15:00"  # Saturday
    assert wh.for_day(6) is None  # Sunday = closed


def test_working_hours_closed():
    wh = WorkingHours(default="09:00-18:00", mon="closed")
    assert wh.for_day(0) is None


# --- build_knowledge_context ---


def test_build_knowledge_context_services():
    cfg = _sample_specialist()
    ctx = cfg.build_knowledge_context()
    assert "Маникюр" in ctx
    assert "60 min" in ctx
    assert "2000" in ctx
    assert "Педикюр" in ctx


def test_build_knowledge_context_staff():
    cfg = _sample_specialist()
    ctx = cfg.build_knowledge_context()
    assert "Анна" in ctx
    assert "маникюр" in ctx
    assert "Мария" in ctx
    assert "Mon-Fri 10-18" in ctx


def test_build_knowledge_context_faq():
    cfg = _sample_specialist()
    ctx = cfg.build_knowledge_context()
    assert "Сколько стоит?" in ctx
    assert "2000 руб" in ctx


def test_build_knowledge_context_extra_prompt():
    cfg = _sample_specialist()
    ctx = cfg.build_knowledge_context()
    assert "Будь вежлива." in ctx


def test_build_knowledge_context_empty():
    cfg = SpecialistConfig()
    ctx = cfg.build_knowledge_context()
    assert ctx == ""


# --- build_specialist_system_block ---


def test_build_system_block_full():
    cfg = _sample_specialist()
    block = build_specialist_system_block(cfg, language="ru", business_name="Элегант")
    assert "SPECIALIST KNOWLEDGE" in block
    assert "Элегант" in block
    assert "Привет! Салон красоты." in block
    assert "Маникюр" in block
    assert "booking" in block
    assert "END SPECIALIST KNOWLEDGE" in block


def test_build_system_block_no_business_name():
    cfg = _sample_specialist()
    block = build_specialist_system_block(cfg, language="en")
    assert "SPECIALIST KNOWLEDGE ---" in block
    assert "Hi! Beauty salon." in block


def test_build_system_block_minimal():
    cfg = SpecialistConfig(greeting={"en": "Hello"})
    block = build_specialist_system_block(cfg, language="en")
    assert "Hello" in block
    assert "SPECIALIST KNOWLEDGE" in block


# --- ProfileConfig integration ---


def test_profile_config_with_specialist():
    from src.core.profiles import ProfileConfig

    data = {
        "name": "Test Salon",
        "aliases": ["salon"],
        "specialist": {
            "greeting": {"en": "Welcome!"},
            "services": [{"name": "Haircut", "duration_min": 30}],
        },
    }
    profile = ProfileConfig(**data)
    assert profile.specialist is not None
    assert profile.specialist.services[0].name == "Haircut"
    assert profile.specialist.get_greeting("en") == "Welcome!"


def test_profile_config_without_specialist():
    from src.core.profiles import ProfileConfig

    data = {"name": "Old Profile", "aliases": ["old"]}
    profile = ProfileConfig(**data)
    assert profile.specialist is None


# --- YAML profile loading ---


def test_manicure_profile_has_specialist(profile_loader):
    profile = profile_loader.get("manicure")
    assert profile is not None
    assert profile.specialist is not None
    assert len(profile.specialist.services) > 0
    assert profile.specialist.get_greeting("ru") is not None


def test_flowers_profile_has_specialist(profile_loader):
    profile = profile_loader.get("flowers")
    assert profile is not None
    assert profile.specialist is not None
    assert len(profile.specialist.services) > 0


def test_trucker_profile_no_specialist(profile_loader):
    profile = profile_loader.get("trucker")
    assert profile is not None
    assert profile.specialist is None


def test_specialist_services_have_price(profile_loader):
    profile = profile_loader.get("manicure")
    priced = [s for s in profile.specialist.services if s.price is not None]
    assert len(priced) >= 3


def test_specialist_staff_loaded(profile_loader):
    profile = profile_loader.get("manicure")
    assert len(profile.specialist.staff) >= 2
    assert all(len(s.specialties) > 0 for s in profile.specialist.staff)


def test_specialist_working_hours_loaded(profile_loader):
    profile = profile_loader.get("manicure")
    wh = profile.specialist.working_hours
    assert wh.default == "10:00-20:00"
    assert wh.sat == "10:00-18:00"
    assert wh.sun == "closed"


def test_specialist_faq_loaded(profile_loader):
    profile = profile_loader.get("manicure")
    assert len(profile.specialist.faq) >= 2
    assert "q" in profile.specialist.faq[0]
    assert "a" in profile.specialist.faq[0]
