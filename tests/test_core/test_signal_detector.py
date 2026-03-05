"""Tests for dual-search signal detector."""

import pytest

from src.core.research.signal_detector import DualSearchSignals, detect_signals


class TestLocationDetection:
    def test_english_city(self):
        signals = detect_signals("restaurant in Almaty")
        assert signals.has_location is True

    def test_russian_city(self):
        signals = detect_signals("кафе в Берлине")
        assert signals.has_location is True

    def test_spanish_city(self):
        signals = detect_signals("hotel en Bangkok")
        assert signals.has_location is True

    def test_russian_city_name(self):
        signals = detect_signals("ресторан в Москве")
        assert signals.has_location is True

    def test_country_name_english(self):
        signals = detect_signals("visa requirements for Thailand")
        assert signals.has_location is True

    def test_country_name_russian(self):
        signals = detect_signals("виза в Казахстан")
        assert signals.has_location is True

    def test_country_name_spanish(self):
        signals = detect_signals("vuelos a España")
        assert signals.has_location is True

    def test_multiple_cities(self):
        signals = detect_signals("flights from New York to London")
        assert signals.has_location is True


class TestPriceDateDetection:
    def test_english_how_much(self):
        signals = detect_signals("how much does a Tesla cost")
        assert signals.has_price_or_date is True

    def test_russian_price(self):
        signals = detect_signals("сколько стоит iPhone 16")
        assert signals.has_price_or_date is True

    def test_spanish_price(self):
        signals = detect_signals("cuánto cuesta un vuelo")
        assert signals.has_price_or_date is True

    def test_year_reference(self):
        signals = detect_signals("best laptops 2026")
        assert signals.has_price_or_date is True

    def test_budget_keyword(self):
        signals = detect_signals("budget hotel options")
        assert signals.has_price_or_date is True

    def test_russian_now(self):
        signals = detect_signals("цены сейчас на бензин")
        assert signals.has_price_or_date is True


class TestBusinessContextDetection:
    def test_english_buy(self):
        signals = detect_signals("buy a new laptop")
        assert signals.has_business_context is True

    def test_russian_rent(self):
        signals = detect_signals("арендовать квартиру")
        assert signals.has_business_context is True

    def test_spanish_compare(self):
        signals = detect_signals("comparar precios de teléfonos")
        assert signals.has_business_context is True

    def test_english_reserve(self):
        signals = detect_signals("reserve a table")
        assert signals.has_business_context is True

    def test_russian_buy(self):
        signals = detect_signals("где купить кофе")
        assert signals.has_business_context is True


class TestNegativeCases:
    def test_generic_question(self):
        signals = detect_signals("what is python?")
        assert signals.should_dual_search is False

    def test_greeting(self):
        signals = detect_signals("hello")
        assert signals.should_dual_search is False

    def test_empty_string(self):
        signals = detect_signals("")
        assert signals.should_dual_search is False

    def test_none_like(self):
        signals = detect_signals("   ")
        assert signals.should_dual_search is False

    def test_simple_factual(self):
        signals = detect_signals("who wrote Romeo and Juliet")
        assert signals.should_dual_search is False


class TestMultilingualLocation:
    """Location detection across many languages."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Hotel in München", True),           # German
            ("restaurant à Paris", True),          # French
            ("hotel em Lisboa", True),             # Portuguese — lisbon
            ("ristorante a Roma", True),           # Italian
            ("otel Istanbul", True),               # Turkish
            ("готель у Києві", True),               # Ukrainian
            ("қонақүй Алматы", True),              # Kazakh
            ("hotel w Warszawie", True),            # Polish — warsaw
            ("東京のレストラン", True),               # Japanese
            ("서울 호텔", True),                      # Korean
            ("โรงแรมกรุงเทพ", True),                # Thai
            ("khách sạn Hanoi", True),              # Vietnamese
            ("فندق في دبي", True),                   # Arabic
            ("hotel di Jakarta", True),             # Indonesian
            ("北京的餐厅", True),                     # Chinese
        ],
    )
    def test_location_in_language(self, text: str, expected: bool):
        signals = detect_signals(text)
        assert signals.has_location is expected, f"Failed for: {text}"


class TestMultilingualPrice:
    """Price/date detection across many languages."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("wie viel kostet ein Auto", True),      # German
            ("combien coûte un billet", True),        # French
            ("quanto custa um voo", True),            # Portuguese
            ("quanto costa la pizza", True),          # Italian
            ("bu ne kadar", True),                    # Turkish
            ("скільки коштує квиток", True),           # Ukrainian
            ("бағасы қанша", True),                    # Kazakh
            ("ile kosztuje bilet", True),             # Polish
            ("いくらですか", True),                     # Japanese
            ("가격 얼마예요", True),                     # Korean
            ("ราคาเท่าไหร่", True),                    # Thai
            ("giá bao nhiêu", True),                  # Vietnamese
            ("كم سعر", True),                          # Arabic
            ("harga berapa", True),                   # Indonesian
            ("多少钱", True),                           # Chinese
            ("heute beste Angebote", True),           # German today
        ],
    )
    def test_price_in_language(self, text: str, expected: bool):
        signals = detect_signals(text)
        assert signals.has_price_or_date is expected, f"Failed for: {text}"


class TestMultilingualBusiness:
    """Business context detection across many languages."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Wohnung mieten", True),                # German rent
            ("acheter une maison", True),             # French buy
            ("alugar apartamento", True),             # Portuguese rent
            ("comprare biglietto", True),             # Italian buy
            ("kirala", True),                         # Turkish rent
            ("купити квартиру", True),                 # Ukrainian buy
            ("сатып алу", True),                       # Kazakh buy
            ("kupić mieszkanie", True),               # Polish buy
            ("予約する", True),                         # Japanese reserve
            ("구매하다", True),                          # Korean purchase
            ("จองโรงแรม", True),                       # Thai book
            ("mua nhà", True),                        # Vietnamese buy
            ("شراء سيارة", True),                       # Arabic buy
            ("beli tiket", True),                     # Indonesian buy
            ("购买机票", True),                          # Chinese purchase
        ],
    )
    def test_business_in_language(self, text: str, expected: bool):
        signals = detect_signals(text)
        assert signals.has_business_context is expected, f"Failed for: {text}"


class TestMixedSignals:
    def test_all_three_signals(self):
        signals = detect_signals("buy apartment in Berlin 2026")
        assert signals.has_location is True
        assert signals.has_price_or_date is True
        assert signals.has_business_context is True
        assert signals.should_dual_search is True

    def test_location_and_price(self):
        signals = detect_signals("how much is a coffee in Tokyo")
        assert signals.has_location is True
        assert signals.has_price_or_date is True
        assert signals.should_dual_search is True

    def test_location_only_triggers(self):
        signals = detect_signals("weather in Dubai")
        assert signals.has_location is True
        assert signals.should_dual_search is True


class TestDualSearchSignalsDataclass:
    def test_frozen(self):
        signals = DualSearchSignals(
            has_location=True,
            has_price_or_date=False,
            has_business_context=False,
        )
        with pytest.raises(AttributeError):
            signals.has_location = False  # type: ignore[misc]

    def test_should_dual_search_all_false(self):
        signals = DualSearchSignals(False, False, False)
        assert signals.should_dual_search is False

    def test_should_dual_search_any_true(self):
        assert DualSearchSignals(True, False, False).should_dual_search is True
        assert DualSearchSignals(False, True, False).should_dual_search is True
        assert DualSearchSignals(False, False, True).should_dual_search is True
