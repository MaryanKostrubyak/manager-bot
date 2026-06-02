from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_settings_dep
from app.core.config import Settings, get_settings
from app.models import AssistantFeedback, Category, CategoryType, Transaction, TransactionType, User
from app.schemas import (
    BudgetLimitCreate,
    BudgetProgress,
    TransactionCreate,
    WebAssistantFeedbackRequest,
    WebAssistantFeedbackResponse,
    WebAssistantRequest,
    WebAssistantResponse,
    WebCategory,
    WebChartResponse,
    WebChartSeries,
    WebConfigResponse,
    WebInsightsResponse,
    WebOverviewResponse,
    WebPreferencesResponse,
    WebPreferencesUpdate,
    WebReceiptRequest,
    WebReceiptResponse,
    WebSessionRequest,
    WebSessionResponse,
    WebStatementImportRequest,
    WebStatementImportResponse,
    WebTransactionCreate,
    WebTransactionListItem,
    WebTransactionUpdate,
)
from app.services.assistant import AIAdvisor
from app.services.budgets import BudgetService
from app.services.receipt_ai import GPTReceiptParser
from app.services.statement_import import StatementImportService
from app.services.transactions import TransactionService
from app.services.users import UserService
from app.utils.categories import localize_category_name
from app.utils.merchants import canonicalize_merchant
from app.utils.subscriptions import is_subscription
from app.utils.telegram_webapp import (
    InvalidInitDataError,
    InvalidTelegramLoginError,
    parse_telegram_login_data,
    parse_webapp_init_data,
)
from app.utils.text import repair_text
from app.utils.web_session import (
    InvalidWebSessionToken,
    create_web_session_token,
    verify_web_session_token,
)

CACHE_TTL_SECONDS = 60
_ANALYTICS_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str):
    item = _ANALYTICS_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < datetime.utcnow().timestamp():
        _ANALYTICS_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    _ANALYTICS_CACHE[key] = (datetime.utcnow().timestamp() + CACHE_TTL_SECONDS, payload)


def _invalidate_cache(user_id: int) -> None:
    prefix = f"user:{user_id}:"
    for key in list(_ANALYTICS_CACHE.keys()):
        if key.startswith(prefix):
            _ANALYTICS_CACHE.pop(key, None)

router = APIRouter(prefix="/web", tags=["web"])
settings_snapshot = get_settings()
ai_advisor = AIAdvisor(settings_snapshot)
receipt_parser = GPTReceiptParser(settings_snapshot)
statement_importer = StatementImportService(settings_snapshot)


@dataclass
class WebAppContext:
    user: User
    telegram: dict[str, Any]
    session: AsyncSession

PROFILE_FIELDS = ("id", "first_name", "last_name", "username", "photo_url")


def _extract_profile(source: dict[str, Any] | None) -> dict[str, Any]:
    if not source:
        return {}
    profile: dict[str, Any] = {}
    for key in PROFILE_FIELDS:
        value = source.get(key)
        if value is not None:
            profile[key] = value
    return profile


def _resolve_session_secret(settings: Settings) -> str:
    secret = (
        settings.web_session_secret
        or settings.telegram_webhook_secret
        or settings.admin_api_key
        or settings.telegram_bot_token
    )
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web session secret is not configured.",
        )
    return secret


def _build_session_response(
    user: User,
    profile: dict[str, Any],
    *,
    token: str | None = None,
    expires_at: int | None = None,
) -> WebSessionResponse:
    expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc) if expires_at else None
    return WebSessionResponse(
        user_id=user.id,
        telegram_id=user.telegram_id,
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
        username=profile.get("username") or user.username,
        photo_url=profile.get("photo_url"),
        currency=user.currency,
        language=user.language,
        theme=user.theme,
        token=token,
        token_expires_at=expires_dt,
    )


@router.get("/config", response_model=WebConfigResponse, include_in_schema=False)
async def get_public_config(settings: Settings = Depends(get_settings_dep)) -> WebConfigResponse:
    """Public config for the web client (currently bot username only)."""
    return WebConfigResponse(telegram_bot_username=settings.telegram_bot_username or None)


def _parse_init_or_400(init_data: str, settings: Settings) -> dict[str, Any]:
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token is not configured.",
        )
    try:
        return parse_webapp_init_data(init_data, settings.telegram_bot_token)
    except InvalidInitDataError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _parse_login_or_400(login_data: str, settings: Settings) -> dict[str, Any]:
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token is not configured.",
        )
    try:
        return parse_telegram_login_data(login_data, settings.telegram_bot_token)
    except InvalidTelegramLoginError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def get_web_context(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    init_data: str | None = Header(default=None, alias="X-Telegram-Init"),
    authorization: str | None = Header(default=None),
) -> WebAppContext:
    """Resolve web context strictly via Telegram init data; optionally validate an attached Bearer token."""
    user_service = UserService(session)
    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram init data is required. Please open the bot WebApp again.",
        )

    init_payload = _parse_init_or_400(init_data, settings)
    init_user = init_payload.get("user") or {}
    init_tid = init_user.get("id")
    if not init_tid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user id missing in init data")

    if authorization:
        scheme, _, token_value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token_value:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
        secret = _resolve_session_secret(settings)
        try:
            payload = verify_web_session_token(token_value.strip(), secret)
        except InvalidWebSessionToken as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        token_tid = payload.get("tid")
        if token_tid and token_tid != init_tid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Telegram account mismatch. Please re-open the bot WebApp to refresh session.",
            )

    user = await user_service.ensure_user(int(init_tid), init_user.get("username") if init_user else None)
    await session.commit()
    return WebAppContext(user=user, telegram=init_user, session=session)


def _parse_month(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month must be YYYY-MM")
    return date(parsed.year, parsed.month, 1)


def _parse_category_ids(value: str | None) -> list[int] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return None
    parsed: list[int] = []
    for part in parts:
        if not part.isdigit():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="category_ids must contain integers")
        parsed.append(int(part))
    return parsed


def _map_transaction(tx) -> WebTransactionListItem:
    tags = list(tx.tags or [])
    source = "statement" if "statement_import" in tags else "manual"
    repaired_description = repair_text(tx.description)
    merchant = canonicalize_merchant(repaired_description)
    return WebTransactionListItem(
        id=tx.id,
        amount=tx.amount,
        currency=tx.currency,
        direction=tx.direction,
        category_id=tx.category_id,
        category=localize_category_name(tx.category.name if tx.category else None),
        merchant=merchant,
        description=repaired_description,
        tags=tags,
        must="must" in tags,
        source=source,
        occurred_at=tx.occurred_at,
    )


@router.post("/session", response_model=WebSessionResponse)
async def create_session(
    payload: WebSessionRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> WebSessionResponse:
    """Create a web session token from Telegram init/login payload."""
    user_payload: dict[str, Any] | None = None
    if payload.init_data:
        data = _parse_init_or_400(payload.init_data, settings)
        user_payload = data.get("user") or {}
    elif payload.login_data:
        user_payload = _parse_login_or_400(payload.login_data, settings)
    if not user_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="init_data or login_data must be provided."
        )

    telegram_id = user_payload.get("id")
    if not telegram_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user id missing in init data")

    # Always require init/login payload even if a token was provided client-side, to avoid cross-account reuse.
    user_service = UserService(session)
    user = await user_service.ensure_user(telegram_id, user_payload.get("username"))
    await session.commit()
    profile = _extract_profile(user_payload)
    profile.setdefault("id", telegram_id)
    secret = _resolve_session_secret(settings)
    try:
        token, expires_at = create_web_session_token(
            user_id=user.id,
            telegram_id=telegram_id,
            profile=profile,
            secret=secret,
            lifetime_seconds=settings.web_session_ttl_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return _build_session_response(user, profile, token=token, expires_at=expires_at)


@router.get("/session", response_model=WebSessionResponse)
async def get_session_details(ctx: WebAppContext = Depends(get_web_context)) -> WebSessionResponse:
    """Return session details for the current user (from Bearer token or init header)."""
    profile = _extract_profile(ctx.telegram)
    profile.setdefault("id", ctx.user.telegram_id)
    return _build_session_response(ctx.user, profile)


@router.patch("/preferences", response_model=WebPreferencesResponse)
async def update_preferences(
    payload: WebPreferencesUpdate,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebPreferencesResponse:
    """Update language/currency/theme for the current user."""
    user_service = UserService(ctx.session)
    await user_service.update_preferences(
        ctx.user,
        currency=payload.currency,
        language=payload.language,
        theme=payload.theme,
    )
    await ctx.session.commit()
    return WebPreferencesResponse(currency=ctx.user.currency, language=ctx.user.language, theme=ctx.user.theme)



@router.get("/insights", response_model=WebInsightsResponse)
async def insights(
    month: str | None = Query(None),
    period: str | None = Query(None, pattern="^(month|7d|30d|quarter|custom)?$"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None, pattern="^(all|statement|manual)?$"),
    ctx: WebAppContext = Depends(get_web_context),
) -> WebInsightsResponse:
    cache_key = f"user:{ctx.user.id}:insights:{month}:{period}:{start}:{end}:{source}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    start_local, end_local, start_utc, end_utc = _resolve_period_range(ctx.user, month, period, start, end)
    stmt = (
        select(Transaction.occurred_at, Transaction.amount, Transaction.description, Transaction.direction)
        .where(Transaction.user_id == ctx.user.id)
        .where(Transaction.occurred_at >= start_utc, Transaction.occurred_at < end_utc)
    )
    stmt = _apply_source_filter(stmt, source if source != "all" else None)
    rows = (await ctx.session.execute(stmt)).all()

    heatmap: dict[tuple[int, int], dict[str, float]] = {}
    merchant_totals: dict[str, dict[str, float]] = {}
    tz = ZoneInfo(ctx.user.timezone or "UTC")

    for occurred_at, amount, description, direction in rows:
        if not occurred_at or direction != TransactionType.EXPENSE:
            continue
        local_dt = occurred_at.replace(tzinfo=timezone.utc).astimezone(tz)
        weekday = local_dt.weekday()
        hour = local_dt.hour
        bucket = heatmap.setdefault((weekday, hour), {"total": 0.0, "count": 0})
        bucket["total"] += float(amount or 0.0)
        bucket["count"] += 1

        if description:
            key = canonicalize_merchant(description)
            if key:
                entry = merchant_totals.setdefault(key, {"total": 0.0, "count": 0})
                entry["total"] += float(amount or 0.0)
                entry["count"] += 1

    heatmap_cells = [
        {"weekday": weekday, "hour": hour, "total": data["total"], "count": data["count"]}
        for (weekday, hour), data in heatmap.items()
    ]

    groups = [
        {"merchant": key, "total": data["total"], "count": data["count"]}
        for key, data in merchant_totals.items()
        if data["count"] >= 2
    ]
    groups.sort(key=lambda item: item["total"], reverse=True)
    groups = groups[:8]

    response = WebInsightsResponse(heatmap=heatmap_cells, merchants=groups, currency=ctx.user.currency)
    _cache_set(cache_key, response)
    return response

@router.get("/overview", response_model=WebOverviewResponse)
async def overview(
    month: str | None = Query(None),
    period: str | None = Query(None, pattern="^(month|7d|30d|quarter|custom)?$"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None, pattern="^(all|statement|manual)?$"),
    ctx: WebAppContext = Depends(get_web_context),
) -> WebOverviewResponse:
    """User overview: summary + budgets + recent transactions."""
    cache_key = f"user:{ctx.user.id}:overview:{month}:{period}:{start}:{end}:{source}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    tx_service = TransactionService(ctx.session)
    start_local, end_local, start_utc, end_utc = _resolve_period_range(ctx.user, month, period, start, end)
    summary = await tx_service.summary_for_period(
        ctx.user,
        start_local,
        end_local,
        source=source if source != "all" else None,
    )
    recent = await tx_service.get_recent_transactions(
        ctx.user,
        limit=5,
        start=start_utc,
        end=end_utc,
        source=source if source != "all" else None,
    )
    available_months = await tx_service.available_months(ctx.user)
    all_time = await tx_service.all_time_summary(ctx.user) if available_months else None
    budget_service = BudgetService(ctx.session)
    limits = await budget_service.list_limits(ctx.user.id)
    budgets = [await budget_service.progress(limit) for limit in limits] if limits else []
    transactions = [_map_transaction(tx) for tx in recent]
    response = WebOverviewResponse(
        summary=summary,
        budgets=budgets,
        recent_transactions=transactions,
        available_months=available_months,
        all_time_summary=all_time,
    )
    _cache_set(cache_key, response)
    return response


@router.get(
    "/charts",
    response_model=WebChartResponse,
)
async def charts(
    chart_type: str = Query("category_bar", pattern="^(category_bar|category_pie|trend_line|balance_line)$"),
    month: str | None = Query(None),
    period: str | None = Query(None, pattern="^(month|7d|30d|quarter|custom)?$"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None, pattern="^(all|statement|manual)?$"),
    ctx: WebAppContext = Depends(get_web_context),
) -> WebChartResponse:
    """Chart datasets for the web dashboard."""
    cache_key = f"user:{ctx.user.id}:charts:{chart_type}:{month}:{period}:{start}:{end}:{source}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    start_local, end_local, start_utc, end_utc = _resolve_period_range(ctx.user, month, period, start, end)

    source_filter = source if source != "all" else None
    if chart_type == "trend_line":
        labels, series = await _trend_chart_dataset(ctx, start_utc, end_utc, source_filter)
    elif chart_type == "balance_line":
        labels, series = await _balance_chart_dataset(ctx, start_local, end_local, start_utc, end_utc, source_filter)
    else:
        labels, series = await _category_chart_dataset(ctx, start_utc, end_utc, chart_type, source_filter)

    response = WebChartResponse(type=chart_type, labels=labels, series=series, currency=ctx.user.currency)
    _cache_set(cache_key, response)
    return response


@router.post("/budgets", response_model=BudgetProgress)
async def create_budget_limit(
    payload: BudgetLimitCreate,
    ctx: WebAppContext = Depends(get_web_context),
) -> BudgetProgress:
    budget_service = BudgetService(ctx.session)
    limit = await budget_service.create_limit(ctx.user.id, payload)
    await ctx.session.commit()
    _invalidate_cache(ctx.user.id)
    await ctx.session.refresh(limit, attribute_names=["category"])
    return await budget_service.progress(limit)


@router.delete("/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget_limit(
    budget_id: int,
    ctx: WebAppContext = Depends(get_web_context),
) -> None:
    budget_service = BudgetService(ctx.session)
    deleted = await budget_service.delete_limit(ctx.user.id, budget_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="limit not found")
    await ctx.session.commit()
    _invalidate_cache(ctx.user.id)


@router.get("/categories", response_model=list[WebCategory])
async def categories(
    direction: TransactionType = Query(TransactionType.EXPENSE),
    ctx: WebAppContext = Depends(get_web_context),
) -> list[WebCategory]:
    stmt = (
        select(Category.id, Category.name)
        .where(Category.user_id == ctx.user.id)
        .where(
            Category.type
            == (CategoryType.EXPENSE if direction == TransactionType.EXPENSE else CategoryType.INCOME)
        )
        .order_by(Category.name.asc())
    )
    rows = await ctx.session.execute(stmt)
    return [WebCategory(id=row[0], name=localize_category_name(row[1])) for row in rows.all()]


@router.post("/transactions", response_model=WebTransactionListItem)
async def create_transaction(
    payload: WebTransactionCreate,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebTransactionListItem:
    tx_service = TransactionService(ctx.session)
    category_name = None
    if payload.category_id:
        category_name = await ctx.session.scalar(
            select(Category.name).where(Category.id == payload.category_id, Category.user_id == ctx.user.id)
        )
    tags = ["manual"]
    if is_subscription(payload.description, category_name):
        tags.append("subscription")
    transaction = await tx_service.add_transaction(
        ctx.user,
        TransactionCreate(
            amount=payload.amount,
            currency=ctx.user.currency,
            direction=payload.direction,
            category_id=payload.category_id,
            description=payload.description,
            occurred_at=payload.occurred_at,
            tags=tags,
            wallet_id=None,
        ),
    )
    await ctx.session.commit()
    _invalidate_cache(ctx.user.id)
    await ctx.session.refresh(transaction, attribute_names=["category"])
    return _map_transaction(transaction)


@router.get("/transactions", response_model=list[WebTransactionListItem])
async def list_transactions(
    month: str | None = Query(None),
    period: str | None = Query(None, pattern="^(month|7d|30d|quarter|custom)?$"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None, pattern="^(all|statement|manual)?$"),
    q: str | None = Query(None, min_length=1, max_length=120),
    direction: TransactionType | None = Query(None),
    category_id: int | None = Query(None, ge=1),
    category_ids: str | None = Query(None),
    amount_min: Decimal | None = Query(None, ge=0),
    amount_max: Decimal | None = Query(None, ge=0),
    must: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: WebAppContext = Depends(get_web_context),
) -> list[WebTransactionListItem]:
    tx_service = TransactionService(ctx.session)
    _, _, start_utc, end_utc = _resolve_period_range(ctx.user, month, period, start, end)
    category_ids_parsed = _parse_category_ids(category_ids)
    transactions = await tx_service.get_recent_transactions(
        ctx.user,
        limit=limit,
        start=start_utc,
        end=end_utc,
        source=source if source != "all" else None,
        offset=offset,
        q=q,
        direction=direction,
        category_id=category_id,
        category_ids=category_ids_parsed,
        amount_min=amount_min,
        amount_max=amount_max,
        must_only=must,
    )
    return [_map_transaction(tx) for tx in transactions]


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: int,
    ctx: WebAppContext = Depends(get_web_context),
) -> None:
    tx_service = TransactionService(ctx.session)
    deleted = await tx_service.delete_transaction(ctx.user, transaction_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found")
    await ctx.session.commit()
    _invalidate_cache(ctx.user.id)


@router.patch("/transactions/{transaction_id}", response_model=WebTransactionListItem)
async def update_transaction(
    transaction_id: int,
    payload: WebTransactionUpdate,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebTransactionListItem:
    tx_service = TransactionService(ctx.session)
    transaction = await tx_service.get_transaction(ctx.user, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found")

    fields_set = set(payload.model_fields_set)
    if not fields_set:
        return _map_transaction(transaction)

    if "amount" in fields_set:
        if payload.amount is None or payload.amount <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="amount must be positive")
        transaction.amount = payload.amount

    if "direction" in fields_set and payload.direction is not None:
        transaction.direction = payload.direction

    category_name: str | None = None
    if "category_id" in fields_set:
        if payload.category_id is None:
            transaction.category_id = None
            category_name = None
        else:
            category_name = await ctx.session.scalar(
                select(Category.name).where(Category.id == payload.category_id, Category.user_id == ctx.user.id)
            )
            if category_name is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="category not found")
            transaction.category_id = payload.category_id

    if "description" in fields_set:
        transaction.description = payload.description

    if "occurred_at" in fields_set and payload.occurred_at is not None:
        transaction.occurred_at = payload.occurred_at

    if "tags" in fields_set and payload.tags is not None:
        tags = [str(tag).strip() for tag in payload.tags if str(tag).strip()]
    else:
        tags = list(transaction.tags or [])

    if "must" in fields_set and payload.must is not None:
        if payload.must and "must" not in tags:
            tags.append("must")
        if not payload.must:
            tags = [tag for tag in tags if tag != "must"]

    if "description" in fields_set or "category_id" in fields_set:
        if category_name is None and transaction.category is not None:
            category_name = transaction.category.name
        if is_subscription(transaction.description, category_name):
            if "subscription" not in tags:
                tags.append("subscription")
        else:
            tags = [tag for tag in tags if tag != "subscription"]

    transaction.tags = list(dict.fromkeys(tags))
    await ctx.session.flush()
    await ctx.session.commit()
    _invalidate_cache(ctx.user.id)
    await ctx.session.refresh(transaction, attribute_names=["category"])
    return _map_transaction(transaction)


@router.post("/assistant", response_model=WebAssistantResponse)
async def assistant(
    payload: WebAssistantRequest,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebAssistantResponse:
    if not payload.question.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")
    tx_service = TransactionService(ctx.session)
    answer = await ai_advisor.advise(
        ctx.user,
        payload.question,
        tx_service,
        tone=payload.tone,
        period=payload.period,
        month=payload.month,
        start=payload.start,
        end=payload.end,
        source=payload.source,
    )
    return WebAssistantResponse(answer=answer)


@router.post("/assistant-feedback", response_model=WebAssistantFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def assistant_feedback(
    payload: WebAssistantFeedbackRequest,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebAssistantFeedbackResponse:
    if not payload.question.strip() or not payload.answer.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question and answer are required")
    context: dict[str, Any] = payload.context or {}
    if payload.period:
        context.setdefault("period", payload.period)
    if payload.month:
        context.setdefault("month", payload.month)
    if payload.start:
        context.setdefault("start", payload.start)
    if payload.end:
        context.setdefault("end", payload.end)
    if payload.tone:
        context.setdefault("tone", payload.tone)

    feedback = AssistantFeedback(
        user_id=ctx.user.id,
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        tone=payload.tone,
        rating=payload.rating or "wrong",
        context=context,
    )
    ctx.session.add(feedback)
    await ctx.session.commit()
    return WebAssistantFeedbackResponse(status="ok")


@router.post("/receipt", response_model=WebReceiptResponse)
async def parse_receipt(
    payload: WebReceiptRequest,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebReceiptResponse:
    if not receipt_parser.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI receipt parser is not configured."
        )
    try:
        data_bytes = base64.b64decode(payload.image_base64.split(",", 1)[-1])
    except binascii.Error as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid image payload") from exc

    receipt = await receipt_parser.parse(data_bytes)
    return WebReceiptResponse(
        amount=receipt.amount,
        currency=receipt.currency or ctx.user.currency,
        merchant=receipt.merchant,
        category_hint=receipt.category_hint,
        description=receipt.description,
        occurred_at=receipt.occurred_at,
    )


@router.post("/statement", response_model=WebStatementImportResponse)
async def import_statement(
    payload: WebStatementImportRequest,
    ctx: WebAppContext = Depends(get_web_context),
) -> WebStatementImportResponse:
    if not payload.file_base64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_base64 is required")
    try:
        data_bytes = base64.b64decode(payload.file_base64.split(",", 1)[-1])
    except binascii.Error as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid file payload") from exc

    try:
        stats = await statement_importer.import_transactions(
            ctx.user,
            ctx.session,
            data_bytes,
            filename=payload.filename,
        )
        await ctx.session.commit()
        _invalidate_cache(ctx.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Import failed") from exc

    return WebStatementImportResponse(
        imported=stats.imported,
        skipped=stats.skipped,
        total_expense=stats.total_expense,
        total_income=stats.total_income,
        currency=stats.currency,
        confidence=stats.confidence,
        notes=stats.notes,
        mapping=stats.mapping,
    )



def _resolve_period_range(
    user: User,
    month_value: str | None,
    period: str | None,
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime, datetime, datetime]:
    tz = ZoneInfo(user.timezone or "UTC")
    now_local = datetime.now(tz)

    if period == "custom" and start and end:
        start_local = datetime.fromisoformat(start).replace(tzinfo=tz)
        end_local = datetime.fromisoformat(end).replace(tzinfo=tz)
        if end_local <= start_local:
            end_local = start_local + timedelta(days=1)
    elif period == "7d":
        end_local = now_local
        start_local = end_local - timedelta(days=7)
    elif period == "30d":
        end_local = now_local
        start_local = end_local - timedelta(days=30)
    elif period == "quarter":
        target = _parse_month(month_value) or now_local.date()
        quarter = (target.month - 1) // 3
        start_month = quarter * 3 + 1
        start_local = datetime(target.year, start_month, 1, tzinfo=tz)
        if start_month == 10:
            end_local = datetime(target.year + 1, 1, 1, tzinfo=tz)
        else:
            end_local = datetime(target.year, start_month + 3, 1, tzinfo=tz)
    else:
        start_local, end_local, _, _ = _resolve_period(user, month_value)

    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_local, end_local, start_utc, end_utc


def _apply_source_filter(stmt, source: str | None):
    if source == "statement":
        return stmt.where(Transaction.tags.contains(["statement_import"]))
    if source == "manual":
        return stmt.where(or_(Transaction.tags.is_(None), ~Transaction.tags.contains(["statement_import"])))
    return stmt


def _normalize_merchant(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    cleaned = " ".join(cleaned.split())
    return cleaned[:40]

def _resolve_period(user: User, month_value: str | None) -> tuple[datetime, datetime, datetime, datetime]:
    tz = ZoneInfo(user.timezone or "UTC")
    target = _parse_month(month_value)
    if not target:
        target = datetime.now(tz).date()
    start_local = datetime(target.year, target.month, 1, tzinfo=tz)
    if target.month == 12:
        end_local = datetime(target.year + 1, 1, 1, tzinfo=tz)
    else:
        end_local = datetime(target.year, target.month + 1, 1, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_local, end_local, start_utc, end_utc


async def _category_chart_dataset(
    ctx: WebAppContext,
    start: datetime,
    end: datetime,
    chart_type: str,
    source: str | None,
) -> tuple[list[str], list[WebChartSeries]]:
    stmt = (
        select(Category.name, Transaction.direction, func.sum(Transaction.amount))
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(Transaction.user_id == ctx.user.id)
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .group_by(Category.name, Transaction.direction)
    )
    stmt = _apply_source_filter(stmt, source)
    rows = (await ctx.session.execute(stmt)).all()
    if not rows:
        return [], []

    expenses: dict[str, float] = {}
    incomes: dict[str, float] = {}
    for name, direction, total in rows:
        label = localize_category_name(name or "Без категорії", default="Без категорії")
        if direction == TransactionType.EXPENSE:
            expenses[label] = float(total or 0.0)
        else:
            incomes[label] = float(total or 0.0)

    if chart_type == "category_pie":
        dataset = expenses if any(expenses.values()) else incomes
        labels = sorted(dataset, key=lambda key: dataset[key], reverse=True)
        if not labels:
            return [], []
        data = [dataset[label] for label in labels]
        label = "Витрати" if dataset is expenses else "Доходи"
        return labels, [WebChartSeries(label=label, data=data)]

    labels = list({*expenses.keys(), *incomes.keys()})
    labels.sort(key=lambda label: expenses.get(label, 0.0) + incomes.get(label, 0.0), reverse=True)
    expense_data = [expenses.get(label, 0.0) for label in labels]
    income_data = [incomes.get(label, 0.0) for label in labels]
    if not any(expense_data) and not any(income_data):
        return [], []
    return labels, [
        WebChartSeries(label="Витрати", data=expense_data),
        WebChartSeries(label="Доходи", data=income_data),
    ]



async def _balance_chart_dataset(
    ctx: WebAppContext,
    start_local: datetime,
    end_local: datetime,
    start_utc: datetime,
    end_utc: datetime,
    source: str | None,
) -> tuple[list[str], list[WebChartSeries]]:
    stmt = (
        select(Transaction.occurred_at, Transaction.amount, Transaction.direction)
        .where(Transaction.user_id == ctx.user.id)
        .where(Transaction.occurred_at >= start_utc, Transaction.occurred_at < end_utc)
        .order_by(Transaction.occurred_at)
    )
    stmt = _apply_source_filter(stmt, source)
    rows = (await ctx.session.execute(stmt)).all()
    if not rows:
        return [], []

    daily_net: dict[date, float] = {}
    for occurred_at, amount, direction in rows:
        if not occurred_at:
            continue
        day = occurred_at.date()
        sign = 1 if direction == TransactionType.INCOME else -1
        daily_net[day] = daily_net.get(day, 0.0) + sign * float(amount or 0.0)

    if not daily_net:
        return [], []

    start_day = start_local.date()
    last_actual_day = (end_local - timedelta(days=1)).date()
    if last_actual_day < start_day:
        last_actual_day = start_day

    # Build actual cumulative balance for the period.
    labels: list[str] = []
    actual: list[float | None] = []
    current = start_day
    running = 0.0
    while current <= last_actual_day:
        running += daily_net.get(current, 0.0)
        labels.append(current.strftime("%d.%m"))
        actual.append(running)
        current += timedelta(days=1)

    # Forecast to end of month based on average daily net.
    avg_daily = running / max(1, len(actual))
    month_end = (end_local.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    forecast: list[float | None] = [None] * len(actual)
    forecast_start_value = actual[-1] if actual else 0.0
    forecast_running = forecast_start_value
    current = last_actual_day + timedelta(days=1)
    while current <= month_end.date():
        forecast_running += avg_daily
        labels.append(current.strftime("%d.%m"))
        actual.append(None)
        forecast.append(forecast_running)
        current += timedelta(days=1)

    if not any(value is not None for value in actual) and not any(value is not None for value in forecast):
        return [], []

    return labels, [
        WebChartSeries(label="????", data=actual),
        WebChartSeries(label="???????", data=forecast),
    ]

async def _trend_chart_dataset(
    ctx: WebAppContext,
    start: datetime,
    end: datetime,
    source: str | None,
) -> tuple[list[str], list[WebChartSeries]]:
    stmt = (
        select(Transaction.occurred_at, Transaction.amount, Transaction.direction)
        .where(Transaction.user_id == ctx.user.id)
        .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
        .order_by(Transaction.occurred_at)
    )
    stmt = _apply_source_filter(stmt, source)
    rows = (await ctx.session.execute(stmt)).all()
    if not rows:
        return [], []

    daily_totals: dict[date, dict[TransactionType, float]] = {}
    for occurred_at, amount, direction in rows:
        if not occurred_at:
            continue
        day = occurred_at.date()
        bucket = daily_totals.setdefault(
            day,
            {TransactionType.EXPENSE: 0.0, TransactionType.INCOME: 0.0},
        )
        bucket[direction] = bucket.get(direction, 0.0) + float(amount or 0.0)

    if not daily_totals:
        return [], []

    labels: list[str] = []
    expense_values: list[float] = []
    income_values: list[float] = []
    current = min(daily_totals)
    last = max(daily_totals)
    while current <= last:
        labels.append(current.strftime("%d.%m"))
        expense_values.append(daily_totals.get(current, {}).get(TransactionType.EXPENSE, 0.0))
        income_values.append(daily_totals.get(current, {}).get(TransactionType.INCOME, 0.0))
        current += timedelta(days=1)

    if not any(expense_values) and not any(income_values):
        return [], []

    return labels, [
        WebChartSeries(label="Витрати", data=expense_values),
        WebChartSeries(label="Доходи", data=income_values),
    ]
