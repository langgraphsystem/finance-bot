"""Tax deduction category mapping for the US self-employed / freelancer context.

Keys match category names from config/profiles/_family_defaults.yaml.
Values are (deduction_type, default_deductible_fraction).

Fraction meanings:
- 1.0 = fully deductible
- 0.5 = half deductible (e.g., shared personal/business use)
- 0.7 = 70% deductible (conservative business-use estimate)
- 0.0 = requires separate calculation (home office Form 8829, etc.)
"""

DEDUCTIBLE_CATEGORIES: dict[str, tuple[str, float]] = {
    # 100% business
    "Связь/Интернет": ("business_expense", 1.0),
    "Подписки": ("business_expense", 1.0),
    "Образование": ("education", 1.0),
    "Медицина": ("health_insurance", 1.0),    # self-employed health insurance
    "Электроника": ("section_179", 1.0),

    # Partial deductibility
    "Транспорт": ("vehicle", 0.5),
    "Такси": ("travel", 0.7),
    "Питание/Рестораны": ("meals_50pct", 0.5),   # 50% rule for business meals

    # Home office — requires Form 8829 (set to 0 as marker, handled separately)
    "Аренда": ("home_office", 0.0),
    "Коммунальные": ("home_office", 0.0),

    # Not typically deductible for personal use (excluded from auto-deductions)
    # "Продукты", "Фастфуд", etc. → 0% unless proven business
}

# Human-readable labels for PDF report
DEDUCTION_TYPE_LABELS: dict[str, str] = {
    "business_expense": "Business Expense",
    "education": "Professional Development (Sch. C)",
    "health_insurance": "Self-Employed Health Insurance",
    "section_179": "Section 179 Equipment",
    "vehicle": "Vehicle/Transport (50% est.)",
    "travel": "Business Travel",
    "meals_50pct": "Business Meals (50%)",
    "home_office": "Home Office (Form 8829 req.)",
}

# 2026 tax parameters
SE_TAX_RATE = 0.153           # 15.3%
SE_NET_FACTOR = 0.9235        # multiply net profit before SE tax
SE_DEDUCTION_FACTOR = 0.50    # 50% of SE tax is deductible (above-the-line)
QBI_RATE = 0.20               # §199A QBI deduction (permanent as of July 4, 2025)
QBI_PHASEOUT_START_SINGLE = 203_000   # 2026 single filer
QBI_PHASEOUT_END_SINGLE = 272_300     # 2026 single filer
MILEAGE_RATE_2026 = 0.725     # $/mile (2026 IRS standard)

# 2026 federal brackets (single filer) — (upper_bound, rate)
BRACKETS_2026_SINGLE = [
    (11_925, 0.10),
    (48_475, 0.12),
    (103_350, 0.22),
    (197_300, 0.24),
    (250_525, 0.32),
    (626_350, 0.35),
    (float("inf"), 0.37),
]
