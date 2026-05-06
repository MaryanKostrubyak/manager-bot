from __future__ import annotations

from decimal import Decimal

from app.schemas.base import Schema


class CategoryBreakdown(Schema):
    category: str
    total: Decimal
    direction: str


class AnalyticsSummary(Schema):
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    top_categories: list[CategoryBreakdown]
    currency: str