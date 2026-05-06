from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.models import TransactionType
from app.schemas import AnalyticsSummary, BudgetProgress, Schema


class WebChartSeries(Schema):
    label: str
    data: list[float]


class WebChartResponse(Schema):
    type: str
    labels: list[str]
    series: list[WebChartSeries]
    currency: str


class WebSessionRequest(Schema):
    init_data: str | None = None
    login_data: str | None = None


class WebSessionResponse(Schema):
    user_id: int
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    currency: str
    language: str
    theme: str
    token: str | None = None
    token_expires_at: datetime | None = None


class WebTransactionCreate(Schema):
    amount: Decimal
    category_id: int | None = None
    direction: TransactionType
    description: str | None = None
    occurred_at: datetime | None = None


class WebTransactionUpdate(Schema):
    amount: Decimal | None = None
    category_id: int | None = None
    direction: TransactionType | None = None
    description: str | None = None
    occurred_at: datetime | None = None
    must: bool | None = None
    tags: list[str] | None = None


class WebTransactionListItem(Schema):
    id: int
    amount: Decimal
    currency: str
    direction: TransactionType
    category_id: int | None = None
    category: str | None = None
    merchant: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    must: bool = False
    source: str = "manual"
    occurred_at: datetime | None = None


class WebCategory(Schema):
    id: int
    name: str


class WebOverviewResponse(Schema):
    summary: AnalyticsSummary
    budgets: list[BudgetProgress]
    recent_transactions: list[WebTransactionListItem]
    available_months: list[str] | None = None
    all_time_summary: AnalyticsSummary | None = None


class WebAssistantRequest(Schema):
    question: str
    tone: str | None = None
    period: str | None = None
    month: str | None = None
    start: str | None = None
    end: str | None = None
    source: str | None = None


class WebAssistantResponse(Schema):
    answer: str


class WebAssistantFeedbackRequest(Schema):
    question: str
    answer: str
    tone: str | None = None
    period: str | None = None
    month: str | None = None
    start: str | None = None
    end: str | None = None
    rating: str | None = None
    context: dict[str, Any] | None = None


class WebAssistantFeedbackResponse(Schema):
    status: str


class WebReceiptRequest(Schema):
    image_base64: str


class WebReceiptResponse(Schema):
    amount: Decimal | None
    currency: str | None
    merchant: str | None
    category_hint: str | None
    description: str
    occurred_at: datetime | None


class WebStatementImportRequest(Schema):
    file_base64: str
    filename: str | None = None


class WebStatementImportResponse(Schema):
    imported: int
    skipped: int
    total_expense: Decimal
    total_income: Decimal
    currency: str
    confidence: float
    notes: str | None = None
    mapping: dict[str, str | None]



class WebHeatmapCell(Schema):
    weekday: int
    hour: int
    total: Decimal
    count: int


class WebMerchantGroup(Schema):
    merchant: str
    total: Decimal
    count: int


class WebInsightsResponse(Schema):
    heatmap: list[WebHeatmapCell]
    merchants: list[WebMerchantGroup]
    currency: str

class WebPreferencesUpdate(Schema):
    currency: str | None = None
    language: str | None = None
    theme: str | None = None


class WebPreferencesResponse(Schema):
    currency: str
    language: str
    theme: str


class WebConfigResponse(Schema):
    telegram_bot_username: str | None = None
