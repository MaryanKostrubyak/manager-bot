from __future__ import annotations

from app.models import CategoryType
from app.utils.text import repair_text

DEFAULT_CATEGORIES: tuple[tuple[str, CategoryType, str | None], ...] = (
    ("Їжа", CategoryType.EXPENSE, "🍽"),
    ("Транспорт", CategoryType.EXPENSE, "🚌"),
    ("Покупки", CategoryType.EXPENSE, "🛍"),
    ("Розваги", CategoryType.EXPENSE, "🎉"),
    ("Зарплата", CategoryType.INCOME, "💸"),
    ("Фриланс", CategoryType.INCOME, "💻"),
)

LEGACY_CATEGORY_NAMES: dict[str, str] = {
    "Food": "Їжа",
    "Transport": "Транспорт",
    "Groceries": "Покупки",
    "Salary": "Зарплата",
    "Freelance": "Фриланс",
    "Entertainment": "Розваги",
}

LEGACY_CATEGORY_LOOKUP = {key.lower(): value for key, value in LEGACY_CATEGORY_NAMES.items()}


def localize_category_name(value: str | None, default: str = "") -> str:
    """Return a human-friendly category name with Ukrainian defaults."""
    if value is None:
        return default
    repaired = repair_text(value)
    normalized = repaired.strip()
    if not normalized:
        return default
    localized = LEGACY_CATEGORY_LOOKUP.get(normalized.lower())
    return localized or normalized


__all__ = [
    "DEFAULT_CATEGORIES",
    "LEGACY_CATEGORY_NAMES",
    "LEGACY_CATEGORY_LOOKUP",
    "localize_category_name",
]
