"""Keyword-based detector for dual-search signals (zero LLM cost).

Multilingual: EN, RU, ES, DE, FR, PT, IT, TR, AR, ZH, JA, KO, UK, KK, TH, VI, PL, ID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Location: city names (all lowercase, including common inflected forms)
# ---------------------------------------------------------------------------
_CITIES: set[str] = {
    # --- CIS & Central Asia ---
    "almaty", "алматы", "астана", "astana", "nur-sultan", "нур-султан",
    "moscow", "москва", "москве", "москву", "москвы",
    "saint petersburg", "санкт-петербург", "санкт-петербурге", "питер", "питере",
    "novosibirsk", "новосибирск", "новосибирске",
    "kazan", "казань", "казани", "sochi", "сочи",
    "kyiv", "kiev", "київ", "києві",
    "minsk", "минск", "минске", "мінск",
    "tbilisi", "тбилиси", "yerevan", "ереван", "ереване",
    "baku", "баку", "tashkent", "ташкент", "ташкенте",
    "bishkek", "бишкек", "бишкеке",
    "шымкент", "shymkent", "караганда", "karaganda", "атырау", "atyrau",
    # --- North America ---
    "new york", "los angeles", "chicago", "houston", "miami", "san francisco",
    "seattle", "boston", "denver", "atlanta", "las vegas", "portland",
    "toronto", "vancouver", "montreal", "ottawa",
    # --- Europe ---
    "london", "paris", "berlin", "amsterdam", "rome", "madrid", "barcelona",
    "lisbon", "vienna", "prague", "warsaw", "zurich", "munich", "brussels",
    "stockholm", "oslo", "copenhagen", "helsinki", "dublin", "edinburgh",
    "milan", "naples", "marseille", "lyon", "hamburg", "frankfurt",
    "budapest", "bucharest", "sofia", "athens", "zagreb", "belgrade",
    "lisbon", "warsaw",
    # --- Asia ---
    "bangkok", "tokyo", "seoul", "singapore", "hong kong", "shanghai",
    "beijing", "taipei", "osaka", "mumbai", "delhi", "bangalore",
    "dubai", "istanbul", "cairo", "tel aviv", "doha", "riyadh",
    "hanoi", "ho chi minh", "kuala lumpur", "jakarta", "manila",
    "phuket", "bali", "chiang mai", "pattaya",
    # --- Latin America ---
    "mexico city", "buenos aires", "sao paulo", "rio de janeiro", "lima",
    "bogota", "santiago", "medellin", "cancun",
    # --- Oceania ---
    "sydney", "melbourne", "auckland", "brisbane",
    # --- Russian forms (nominative + prepositional) ---
    "бангкок", "бангкоке", "токио", "сеул", "сеуле",
    "сингапур", "сингапуре", "гонконг", "гонконге",
    "шанхай", "шанхае", "пекин", "пекине",
    "дубай", "дубае", "стамбул", "стамбуле", "каир", "каире",
    "лондон", "лондоне", "париж", "париже", "берлин", "берлине",
    "амстердам", "амстердаме", "рим", "риме",
    "мадрид", "мадриде", "барселона", "барселоне", "вена", "вене",
    "прага", "праге", "варшава", "варшаве",
    "нью-йорк", "лос-анджелес", "чикаго", "майами", "сан-франциско",
    "сидней", "мельбурн", "торонто", "ванкувер", "монреаль",
    "мехико", "буэнос-айрес", "сан-паулу", "рио-де-жанейро", "лима",
    "богота", "сантьяго", "пхукет", "ханой",
    "куала-лумпур", "джакарта", "манила",
    "милан", "неаполь", "марсель", "гамбург", "франкфурт",
    "будапешт", "бухарест", "софия", "афины", "загреб", "белград",
    # --- Spanish forms ---
    "nueva york", "ciudad de méxico", "londres", "roma", "viena",
    "praga", "varsovia", "atenas", "belgrado",
    # --- German forms ---
    "mailand", "neapel", "lissabon", "warschau", "prag", "wien",
    "brüssel", "kopenhagen", "bukarest", "münchen",
    # --- Portuguese forms ---
    "lisboa",
    # --- French forms ---
    "londres", "moscou", "pékin", "le caire", "athènes",
    # --- Polish forms ---
    "warszawa", "warszawie", "kraków", "krakowie", "gdańsk", "gdańsku",
    "wrocław", "wrocławiu", "poznań", "poznaniu",
    # --- Turkish forms ---
    "londra", "roma", "viyana", "prag", "varşova", "atina",
    # --- Ukrainian forms ---
    "москва", "лондон", "париж", "берлін", "берліні",
    # --- Kazakh forms ---
    "алматы", "астана", "шымкент", "қарағанды", "атырау",
    # --- CJK city names ---
    "東京", "大阪", "ソウル", "서울", "부산", "北京", "上海",
    "香港", "台北", "曼谷", "新加坡", "吉隆坡",
    "杜拜", "迪拜", "伦敦", "巴黎", "柏林",
    "纽约", "洛杉矶", "旧金山",
    # --- Arabic city names ---
    "دبي", "القاهرة", "الرياض", "الدوحة", "إسطنبول",
    # --- Thai city names ---
    "กรุงเทพ", "เชียงใหม่", "ภูเก็ต", "พัทยา",
}

_COUNTRY_WORDS: set[str] = {
    # English
    "usa", "uk", "uae",
    # EN / RU / ES / DE / FR / TR / UK / KK
    "russia", "россия", "rusia", "russland", "russie",
    "kazakhstan", "казахстан", "kazajistán", "қазақстан",
    "thailand", "таиланд", "tailandia", "thaïlande",
    "japan", "япония", "japón", "japon",
    "germany", "германия", "alemania", "deutschland", "allemagne",
    "france", "франция", "francia", "frankreich",
    "spain", "испания", "españa", "spanien", "espagne",
    "italy", "италия", "italia", "italien", "italie",
    "turkey", "турция", "turquía", "türkei", "turquie", "türkiye",
    "china", "китай", "chine",
    "india", "индия", "inde", "indien",
    "korea", "корея", "corea", "corée",
    "brazil", "бразилия", "brasil", "brasilien", "brésil",
    "mexico", "мексика", "méxico", "mexiko", "mexique",
    "canada", "канада", "canadá", "kanada",
    "australia", "австралия", "australien", "australie",
    "georgia", "грузия", "géorgie", "georgien",
    "uzbekistan", "узбекистан", "uzbekistán", "өзбекстан",
    "ukraine", "украина", "ucrania",
    "poland", "польша", "polonia", "polen", "pologne",
    "portugal", "португалия",
    "indonesia", "индонезия",
    "vietnam", "вьетнам",
    "malaysia", "малайзия", "malasia",
    "philippines", "филиппины", "filipinas",
    "egypt", "египет", "egipto", "ägypten", "égypte",
    "argentina", "аргентина",
    "colombia", "колумбия",
    "singapore", "сингапур", "singapur",
    # CJK
    "日本", "中国", "韩国", "한국", "泰国", "印度",
    # Arabic
    "الإمارات", "مصر", "السعودية", "تركيا",
    # Thai
    "ไทย", "ญี่ปุ่น",
}

# ---------------------------------------------------------------------------
# Price / date keywords — multilingual
# ---------------------------------------------------------------------------
_PRICE_DATE_WORDS: set[str] = {
    # English
    "price", "cost", "how much", "pricing", "budget", "cheap", "expensive",
    "affordable", "fee", "rate", "tariff", "fare",
    # Russian
    "цена", "стоимость", "сколько стоит", "сколько", "бюджет", "дешев",
    "дорог", "тариф", "расценк",
    # Spanish
    "precio", "costo", "cuánto", "cuanto", "presupuesto", "barato", "caro",
    "tarifa",
    # German
    "preis", "kosten", "wie viel", "wieviel", "günstig", "billig", "teuer",
    # French
    "prix", "coût", "combien", "pas cher", "cher", "abordable",
    # Portuguese
    "preço", "custo", "quanto custa", "barato", "caro", "orçamento",
    # Italian
    "prezzo", "costo", "quanto costa", "economico", "costoso",
    # Turkish
    "fiyat", "ücret", "ne kadar", "ucuz", "pahalı", "bütçe",
    # Ukrainian
    "ціна", "вартість", "скільки коштує", "скільки", "бюджет", "дешев",
    # Kazakh
    "бағасы", "қанша тұрады", "қанша", "арзан", "қымбат",
    # Polish
    "cena", "koszt", "ile kosztuje", "tani", "drogi",
    # Arabic
    "سعر", "كم", "رخيص", "غالي", "ثمن",
    # Chinese
    "价格", "多少钱", "便宜", "贵",
    # Japanese
    "値段", "いくら", "価格", "安い", "高い",
    # Korean
    "가격", "얼마", "싼", "비싼",
    # Thai
    "ราคา", "เท่าไหร่", "ถูก", "แพง",
    # Vietnamese
    "giá", "bao nhiêu", "rẻ", "đắt",
    # Indonesian
    "harga", "berapa", "murah", "mahal",
}

_PRICE_DATE_PATTERNS = re.compile(
    r"\b("
    r"202[4-9]|2030"
    r"|сейчас|ahora|today|сегодня|hoy|current|актуальн"
    r"|heute|maintenant|aujourd'hui|oggi|bugün|сьогодні|бүгін|dzisiaj"
    r"|今日|今天|오늘|วันนี้|hôm nay|hari ini"
    r")\b",
    flags=re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Business context keywords — multilingual
# ---------------------------------------------------------------------------
_BUSINESS_WORDS: set[str] = {
    # English
    "buy", "rent", "lease", "hire", "open", "compare", "book", "reserve",
    "order", "subscribe", "purchase",
    # Russian
    "купить", "арендовать", "аренда", "снять", "открыть", "сравнить",
    "забронировать", "заказать", "подписаться", "покупка",
    # Spanish
    "comprar", "alquilar", "arrendar", "abrir", "comparar", "reservar",
    "pedir", "suscribir",
    # German
    "kaufen", "mieten", "vergleichen", "buchen", "reservieren", "bestellen",
    # French
    "acheter", "louer", "comparer", "réserver", "commander",
    # Portuguese
    "comprar", "alugar", "comparar", "reservar", "encomendar",
    # Italian
    "comprare", "affittare", "confrontare", "prenotare", "ordinare",
    # Turkish
    "satın almak", "kiralamak", "karşılaştırmak", "rezervasyon",
    "satın al", "kirala", "karşılaştır",
    # Ukrainian
    "купити", "орендувати", "оренда", "зняти", "порівняти", "забронювати",
    # Kazakh
    "сатып алу", "жалға алу", "салыстыру", "брондау",
    # Polish
    "kupić", "wynająć", "porównać", "zarezerwować", "zamówić",
    # Arabic
    "شراء", "استئجار", "حجز", "مقارنة", "طلب",
    # Chinese
    "买", "购买", "租", "比较", "预订", "预约",
    # Japanese
    "買う", "借りる", "比較", "予約",
    # Korean
    "사다", "구매", "임대", "비교", "예약",
    # Thai
    "ซื้อ", "เช่า", "เปรียบเทียบ", "จอง",
    # Vietnamese
    "mua", "thuê", "so sánh", "đặt",
    # Indonesian
    "beli", "sewa", "bandingkan", "pesan", "booking",
}

# ---------------------------------------------------------------------------
# Compiled helpers
# ---------------------------------------------------------------------------
_LOCATION_WORD_RE: re.Pattern[str] | None = None


def _normalize(text: str) -> str:
    return text.lower().strip()


def _get_location_re() -> re.Pattern[str]:
    """Build and cache a regex matching any city or country as a whole word."""
    global _LOCATION_WORD_RE  # noqa: PLW0603
    if _LOCATION_WORD_RE is None:
        all_names = sorted(_CITIES | _COUNTRY_WORDS, key=len, reverse=True)
        escaped = [re.escape(name) for name in all_names]
        # Use word boundary for latin/cyrillic; CJK/Arabic/Thai matched as-is
        _cyrillic = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґқңүұәөһ"
        latin_cyrillic = [
            e for e in escaped
            if e[0].isascii() or e[0] in _cyrillic
        ]
        other = [e for e in escaped if e not in latin_cyrillic]
        parts: list[str] = []
        if latin_cyrillic:
            parts.append(r"\b(?:" + "|".join(latin_cyrillic) + r")\b")
        if other:
            parts.append("(?:" + "|".join(other) + ")")
        _LOCATION_WORD_RE = re.compile("|".join(parts), flags=re.IGNORECASE)
    return _LOCATION_WORD_RE


def _has_location(text: str) -> bool:
    return bool(_get_location_re().search(text))


def _has_price_or_date(text: str) -> bool:
    low = _normalize(text)
    for word in _PRICE_DATE_WORDS:
        if word in low:
            return True
    return bool(_PRICE_DATE_PATTERNS.search(text))


def _has_business_context(text: str) -> bool:
    low = _normalize(text)
    for word in _BUSINESS_WORDS:
        if word in low:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DualSearchSignals:
    """Signals indicating whether a dual-search (Gemini + Grok) is beneficial."""

    has_location: bool
    has_price_or_date: bool
    has_business_context: bool

    @property
    def should_dual_search(self) -> bool:
        return self.has_location or self.has_price_or_date or self.has_business_context


def detect_signals(text: str) -> DualSearchSignals:
    """Detect dual-search signals from user query text (zero LLM cost)."""
    if not text or not text.strip():
        return DualSearchSignals(
            has_location=False,
            has_price_or_date=False,
            has_business_context=False,
        )
    return DualSearchSignals(
        has_location=_has_location(text),
        has_price_or_date=_has_price_or_date(text),
        has_business_context=_has_business_context(text),
    )
