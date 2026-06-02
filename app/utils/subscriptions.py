from __future__ import annotations

from calendar import monthrange
from datetime import date

from app.utils.merchants import canonicalize_merchant

SUBSCRIPTION_CATEGORY_HINTS = (
    "підписк",
    "subscription",
    "онлайн-сервіс",
    "online service",
)

SUBSCRIPTION_KEYWORDS = (
    "subscription",
    "subscr",
    "membership",
    "recurring",
    "monthly",
    "plan",
    "netflix",
    "spotify",
    "youtube",
    "apple",
    "google",
    "icloud",
    "patreon",
    "microsoft",
    "adobe",
    "aws",
    "notion",
    "figma",
    "dropbox",
    "playstation",
    "xbox",
    "prime",
    "subscription fee",
    "підписка",
    "щомісяч",
    "сервіс",
)


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.lower().split())


def is_subscription(description: str | None, category_name: str | None = None) -> bool:
    category = _normalize_text(category_name)
    if category and any(hint in category for hint in SUBSCRIPTION_CATEGORY_HINTS):
        return True
    desc = _normalize_text(description)
    return any(keyword in desc for keyword in SUBSCRIPTION_KEYWORDS)


def next_month_same_day(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    last_day = monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def subscription_merchant_key(description: str | None) -> str:
    if not description:
        return ""
    normalized = canonicalize_merchant(description)
    return normalized or _normalize_text(description)[:40]
