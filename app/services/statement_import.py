from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from typing import Any

import pandas as pd
from loguru import logger

try:
    from openai import AsyncOpenAI, OpenAIError
except Exception:  # pragma: no cover - optional dependency
    AsyncOpenAI = None
    OpenAIError = Exception

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Category, CategoryType, Transaction, TransactionType, User
from app.schemas import TransactionCreate
from app.services.transactions import TransactionService
from app.utils.categories import localize_category_name
from app.utils.merchants import canonicalize_merchant
from app.utils.subscriptions import is_subscription
from app.utils.text import repair_text

TARGET_FIELDS = ("date", "amount", "currency", "description", "category", "balance", "card")

TRANSFER_HINTS = (
    "p2p",
    "c2c",
    "c2a",
    "card to card",
    "internal transfer",
    "own account",
    "iban",
    "перевод",
    "переказ",
    "поповнення",
    "зняття",
    "withdrawal",
    "cash withdrawal",
    "cash in",
    "atm",
    "між своїми",
    "на картку",
    "на карту",
)

MERCHANT_HINTS = (
    "pos",
    "merchant",
    "магазин",
    "magazin",
    "market",
    "supermarket",
    "shop",
    "store",
    "cafe",
    "restaurant",
    "coffee",
    "terminal",
    "mcc",
)

SUMMARY_KEYWORDS = (
    "total",
    "итог",
    "підсумок",
    "залишок",
    "остаток",
    "всього",
    "разом",
    "balance",
    "opening",
    "closing",
    "початковий",
    "кінцевий",
    "summary",
)

CURRENCY_SYNONYMS: dict[str, str] = {
    "uah": "UAH",
    "грн": "UAH",
    "uah.": "UAH",
    "₴": "UAH",
    "eur": "EUR",
    "€": "EUR",
    "usd": "USD",
    "$": "USD",
    "gbp": "GBP",
    "pln": "PLN",
}

STANDARD_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "name": "Продукти / Супермаркети",
        "type": "expense",
        "aliases": ("grocery", "market", "supermarket", "store", "food", "продукт", "супермаркет", "маркет"),
        "keywords": (
            "атб",
            "silpo",
            "сільпо",
            "novus",
            "novus",
            "metro",
            "eko",
            "wog market",
            "varus",
            "billa",
        ),
    },
    {
        "name": "Кафе / Ресторани",
        "type": "expense",
        "aliases": ("cafe", "restaurant", "food court", "coffee", "coffee shop", "піца", "бургер"),
        "keywords": ("mcdonald", "kfc", "starbucks", "піцца", "суші", "sushi", "бургер", "pizza"),
    },
    {
        "name": "Транспорт / Таксі / Пальне",
        "type": "expense",
        "aliases": ("uber", "bolt", "taxi", "тaксі", "fuel", "gas", "petrol", "пальне", "азс"),
        "keywords": ("uklon", "wayforpay taxi", "parking", "паркінг", "fuel", "shell", "okko", "wog"),
    },
    {
        "name": "Комунальні / Зв’язок / Інтернет",
        "type": "expense",
        "aliases": ("utility", "комуналь", "інтернет", "internet", "телефон", "mobile", "зв'язок", "зв’язок"),
        "keywords": ("kyivstar", "vodafone", "lifecell", "electricity", "gas", "water", "тепло", "обл"),
    },
    {
        "name": "Підписки / Онлайн-сервіси",
        "type": "expense",
        "aliases": ("subscription", "підписка", "online service", "apps", "appstore", "play store"),
        "keywords": ("netflix", "spotify", "youtube", "google", "apple", "patreon", "icloud", "microsoft"),
    },
    {
        "name": "Одяг / Товари",
        "type": "expense",
        "aliases": ("shop", "clothes", "одяг", "товари", "retail"),
        "keywords": ("zara", "h&m", "nike", "adidas", "магазин", "розетка", "rozetka", "amazon"),
    },
    {
        "name": "Аптека / Здоров’я",
        "type": "expense",
        "aliases": ("аптека", "pharmacy", "health", "здоров", "ліки", "med"),
        "keywords": ("apteka", "антика", "аптечн", "medicine", "laboratory", "synlab", "invitro"),
    },
    {
        "name": "Розваги",
        "type": "expense",
        "aliases": ("entertainment", "fun", "games", "ігри", "розваг", "cinema", "кіно"),
        "keywords": ("steam", "playstation", "cinema", "theatre", "spotify"),
    },
    {
        "name": "Дім / Ремонт",
        "type": "expense",
        "aliases": ("home", "ремонт", "house", "будинок", "будівель", "construction", "furniture"),
        "keywords": ("epicentr", "leroy", "ikea", "дом", "буд", "remont"),
    },
    {
        "name": "Освіта",
        "type": "expense",
        "aliases": ("education", "course", "навчання", "освіта", "training"),
        "keywords": ("udemy", "coursera", "школ", "університет", "university", "course"),
    },
    {
        "name": "Перекази",
        "type": "transfer",
        "aliases": ("transfer", "переказ", "p2p", "card to card", "поповнення", "зняття", "cash", "atm"),
        "keywords": ("p2p", "c2c", "c2a", "own account", "internal transfer", "cash withdrawal", "cash in"),
    },
    {
        "name": "Комісії банку",
        "type": "expense",
        "aliases": ("fee", "commission", "коміс", "fee"),
        "keywords": ("service fee", "processing fee", "bank fee"),
    },
    {
        "name": "Зарплата / Дохід",
        "type": "income",
        "aliases": ("salary", "income", "доход", "зарплата", "зарп", "wage", "payroll"),
        "keywords": ("payroll", "salary", "income", "виплата", "переказ від роботодавця"),
    },
    {
        "name": "Інше",
        "type": "neutral",
        "aliases": ("misc", "other", "інше"),
        "keywords": (),
    },
)

FIELD_SYNONYMS = {
    "amount": [
        "amount",
        "total",
        "sum",
        "amount ua",
        "amount uah",
        "сума",
        "сума операції",
        "сума в валюті картки",
        "сума в валюті операції",
        "сума операції uah",
    ],
    "amount_in": ["credit", "income", "deposit", "поповнення", "прихід", "зарахування"],
    "amount_out": ["debit", "debet", "outflow", "withdrawal", "списання", "витрата", "розхід"],
    "balance": ["balance", "closing balance", "starting balance", "залишок", "баланс після операції", "баланс"],
    "card": ["card", "account", "iban", "рахунок", "номер картки", "card number"],
    "category": ["category", "class", "категорія", "тип операції"],
    "currency": ["currency", "curr", "iso", "валюта"],
    "date": [
        "date",
        "operation date",
        "transaction date",
        "booking",
        "trans date",
        "posted",
        "дата",
        "дата операції",
        "дата і час",
        "дата та час операції",
    ],
    "description": [
        "description",
        "details",
        "merchant",
        "note",
        "memo",
        "purpose",
        "деталі операції",
        "призначення",
        "коментар",
    ],
}


@dataclass
class ParsedStatementRow:
    amount: Decimal
    currency: str
    direction: TransactionType
    occurred_at: datetime
    description: str
    category_name: str | None = None
    bank_category: str | None = None
    short_description: str | None = None
    balance: Decimal | None = None
    card: str | None = None
    predicted_category: str | None = None
    category_confidence: float = 0.0
    category_reason: str | None = None


@dataclass
class MappingOutcome:
    mapping: dict[str, str | None]
    confidence: float
    notes: str | None = None
    income_column: str | None = None
    expense_column: str | None = None


@dataclass
class StatementImportStats:
    imported: int
    skipped: int
    total_expense: Decimal
    total_income: Decimal
    currency: str
    confidence: float
    notes: str | None
    mapping: dict[str, str | None]
    category_totals: dict[str, Decimal] | None = None
    summary_check: dict[str, Decimal] | None = None


@dataclass
class StatementAnalytics:
    income_total: Decimal
    expense_total: Decimal
    category_totals: dict[str, Decimal]
    summary_totals: dict[str, Decimal]
    discrepancy_note: str | None = None


class StatementImportService:
    """Parse bank statements (CSV/XLSX) with heuristic + AI mapping of columns."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.openai_api_key and AsyncOpenAI:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            self._client = None
        self.model = settings.openai_model
        self._ai_category_budget = 0

    @property
    def ai_enabled(self) -> bool:
        return self._client is not None

    async def import_transactions(
        self, user: User, session: AsyncSession, content: bytes, filename: str | None = None
    ) -> StatementImportStats:
        parsed = await self._parse(content, filename, default_currency=user.currency or "UAH")
        if not parsed.rows:
            raise RuntimeError("Не знайшов жодного рядка з сумою та датою у виписці.")

        tx_service = TransactionService(session)
        imported = 0
        duplicate_skipped = 0
        total_expense = Decimal("0")
        total_income = Decimal("0")

        for row in parsed.rows:
            if await self._transaction_exists(session, user.id, row):
                duplicate_skipped += 1
                continue
            category_id = await self._resolve_category(session, user.id, row.category_name, row.direction)
            normalized_desc = canonicalize_merchant(row.description) or row.description
            tags = ["statement_import"]
            if is_subscription(row.description, row.category_name):
                tags.append("subscription")
            transaction = await tx_service.add_transaction(
                user,
                TransactionCreate(
                    amount=abs(row.amount),
                    currency=row.currency or user.currency,
                    direction=row.direction,
                    category_id=category_id,
                    description=normalized_desc,
                    occurred_at=row.occurred_at,
                    tags=tags,
                    wallet_id=None,
                ),
            )
            imported += 1
            if row.direction == TransactionType.EXPENSE:
                total_expense += abs(transaction.amount)
            else:
                total_income += abs(transaction.amount)

        notes_parts = [parsed.mapping.notes]
        if parsed.analytics and parsed.analytics.discrepancy_note:
            notes_parts.append(parsed.analytics.discrepancy_note)
        joined_notes = " ".join([part for part in notes_parts if part])

        return StatementImportStats(
            imported=imported,
            skipped=parsed.skipped + duplicate_skipped,
            total_expense=total_expense,
            total_income=total_income,
            currency=user.currency,
            confidence=parsed.mapping.confidence,
            notes=joined_notes or None,
            mapping=parsed.mapping.mapping,
            category_totals=parsed.analytics.category_totals if parsed.analytics else None,
            summary_check=parsed.analytics.summary_totals if parsed.analytics else None,
        )

    async def _parse(
        self, content: bytes, filename: str | None, default_currency: str
    ) -> "StatementImportResult":
        tables = self._load_tables(content, filename)
        if not tables:
            raise RuntimeError("Не вдалося знайти табличні дані у файлі.")
        table = self._pick_best_table(tables)
        mapping = await self._resolve_mapping(table)
        rows, skipped, summary_rows = self._normalize_rows(table, mapping, default_currency)
        await self._annotate_categories(rows)
        analytics = self._build_analytics(rows, summary_rows)
        return StatementImportResult(rows=rows, skipped=skipped, mapping=mapping, analytics=analytics)

    def _load_tables(self, content: bytes, filename: str | None) -> list[pd.DataFrame]:
        tables: list[pd.DataFrame] = []
        buffer = BytesIO(content)
        name = (filename or "").lower()
        if name.endswith(".csv"):
            tables.extend(self._load_csv_tables(buffer))
        else:
            tables.extend(self._load_excel_tables(buffer))
            if not tables:  # fallback to CSV if Excel loader failed
                buffer.seek(0)
                tables.extend(self._load_csv_tables(buffer))
        decoded_text = self._decode_text(content)
        if decoded_text and self._looks_like_table_text(decoded_text):
            tables.extend(self._load_text_tables(decoded_text))
        normalized = [self._normalize_dataframe(df) for df in tables if not df.empty]
        return [df for df in normalized if not df.empty]

    def _load_csv_tables(self, buffer: BytesIO) -> list[pd.DataFrame]:
        tables: list[pd.DataFrame] = []
        for sep in (",", ";", "\t", "|"):
            buffer.seek(0)
            try:
                df = pd.read_csv(buffer, dtype=str, sep=sep)
            except Exception:
                continue
            if not df.empty:
                tables.append(df)
        return tables

    def _load_excel_tables(self, buffer: BytesIO) -> list[pd.DataFrame]:
        buffer.seek(0)
        try:
            sheets = pd.read_excel(buffer, dtype=str, sheet_name=None)
        except Exception:
            return []
        return list(sheets.values())

    def _decode_text(self, content: bytes) -> str | None:
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    def _looks_like_table_text(self, text: str) -> bool:
        if not text or text.count("\n") < 2:
            return False
        return any(sep in text for sep in (";", "\t", "|", ",")) or bool(re.search(r"\s{2,}", text))

    def _load_text_tables(self, text: str) -> list[pd.DataFrame]:
        tables: list[pd.DataFrame] = []
        for sep in (";", "\t", "|", ","):
            try:
                df = pd.read_csv(StringIO(text), dtype=str, sep=sep)
            except Exception:
                continue
            if not df.empty:
                tables.append(df)
        if not tables:
            try:
                df = pd.read_csv(StringIO(text), dtype=str, delim_whitespace=True)
                if not df.empty:
                    tables.append(df)
            except Exception:
                pass
        return tables

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.dropna(how="all")
        if df.empty:
            return df
        max_candidates = min(len(df), 50)
        best_idx = 0
        best_score = -1.0
        flat_synonyms = [self._normalize_header(s) for values in FIELD_SYNONYMS.values() for s in values]

        for idx in range(max_candidates):
            row = df.iloc[idx]
            non_empty = row.notna().sum()
            synonym_hits = 0
            textish = 0
            for value in row:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                normalized_value = self._normalize_header(str(value))
                if normalized_value and any(
                    normalized_value == syn or syn in normalized_value for syn in flat_synonyms
                ):
                    synonym_hits += 1
                if re.search(r"[A-Za-zА-Яа-яҐґІіЇїЄє]", str(value)):
                    textish += 1
            score = float(non_empty) + synonym_hits * 3 + textish * 0.1
            if score > best_score:
                best_score = score
                best_idx = idx

        header = [self._clean_header(value) for value in df.iloc[best_idx]]
        data = df.iloc[best_idx + 1 :].copy()
        data.columns = header
        data = data.loc[:, ~data.columns.duplicated()]
        data = data.dropna(how="all")
        return data.reset_index(drop=True)

    def _clean_header(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()[:80]

    def _normalize_header(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _pick_best_table(self, tables: list[pd.DataFrame]) -> pd.DataFrame:
        def score(df: pd.DataFrame) -> int:
            numeric_cols = sum(1 for col in df.columns if df[col].apply(self._parse_decimal).notna().sum() > 0)
            return len(df.columns) + numeric_cols

        tables_sorted = sorted(tables, key=score, reverse=True)
        return tables_sorted[0]

    async def _resolve_mapping(self, df: pd.DataFrame) -> MappingOutcome:
        heuristic = self._heuristic_mapping(df)
        if heuristic.confidence >= 0.75 or not self.ai_enabled:
            return heuristic

        ai_mapping = await self._ai_mapping(df)
        if not ai_mapping:
            return heuristic
        if ai_mapping.confidence >= heuristic.confidence:
            return ai_mapping
        return MappingOutcome(
            mapping={**heuristic.mapping},
            confidence=max(heuristic.confidence, ai_mapping.confidence),
            notes=heuristic.notes,
            income_column=heuristic.income_column or ai_mapping.income_column,
            expense_column=heuristic.expense_column or ai_mapping.expense_column,
        )

    def _heuristic_mapping(self, df: pd.DataFrame) -> MappingOutcome:
        mapping: dict[str, str | None] = {field: None for field in TARGET_FIELDS}
        income_col: str | None = None
        expense_col: str | None = None
        for column in df.columns:
            normalized = self._normalize_header(str(column))
            for field, synonyms in FIELD_SYNONYMS.items():
                for synonym in synonyms:
                    if normalized == synonym or synonym in normalized:
                        if field == "amount_in" and income_col is None:
                            income_col = column
                        elif field == "amount_out" and expense_col is None:
                            expense_col = column
                        elif field in TARGET_FIELDS and mapping[field] is None:
                            mapping[field] = column

        essential_hits = int(bool(mapping["date"])) + int(
            bool(mapping["amount"] or income_col or expense_col)
        )
        optional_hits = sum(1 for key in ("currency", "description", "category", "card") if mapping[key])
        confidence = min(1.0, 0.35 + 0.25 * essential_hits + 0.1 * optional_hits)
        notes = None if confidence >= 0.6 else "Низька впевненість у мапінгу колонок."
        return MappingOutcome(mapping=mapping, confidence=confidence, notes=notes, income_column=income_col, expense_column=expense_col)

    async def _ai_mapping(self, df: pd.DataFrame) -> MappingOutcome | None:
        if not self._client:
            return None
        headers = [str(col) for col in df.columns]
        sample_rows = self._build_samples(df, headers)
        prompt = (
            "\u0422\u0438 \u0434\u043e\u043f\u043e\u043c\u0456\u0436\u043d\u0438\u0439 \u0456\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442 \u0434\u043b\u044f \u043f\u0430\u0440\u0441\u0438\u043d\u0433\u0443 \u0431\u0430\u043d\u043a\u0456\u0432\u0441\u044c\u043a\u0438\u0445 \u0432\u0438\u043f\u0438\u0441\u043e\u043a. "
            "\u041f\u043e\u0432\u0435\u0440\u0442\u0430\u0454\u0448 \u0442\u0456\u043b\u044c\u043a\u0438 JSON \u0443 \u0444\u043e\u0440\u043c\u0430\u0442\u0456: {\"mapping\": {\"date\": \"...\"|null, \"amount\": \"...\"|null, "
            "\"currency\": \"...\"|null, \"description\": \"...\"|null, \"category\": \"...\"|null, "
            "\"balance\": \"...\"|null, \"card\": \"...\"|null}, \"confidence\": 0..1, \"notes\": \"...\"}. "
            "\u041d\u0435 \u0432\u0438\u0433\u0430\u0434\u0443\u0439 \u0437\u043d\u0430\u0447\u0435\u043d\u043d\u044f, \u0441\u0442\u0430\u0432 null \u044f\u043a\u0449\u043e \u043d\u0435 \u0432\u043f\u0435\u0432\u043d\u0435\u043d\u0438\u0439."
        )
        messages = [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"headers": headers, "sampleRows": sample_rows, "locale": "uk-UA"},
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=500,
            )
        except OpenAIError as exc:  # pragma: no cover - network dependency
            logger.warning("AI mapping failed: {}", exc)
            return None

        raw = response.choices[0].message.content if response.choices else None
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None

        mapping_payload = parsed.get("mapping") or {}
        mapping = {field: mapping_payload.get(field) for field in TARGET_FIELDS}
        confidence = float(parsed.get("confidence") or 0.0)
        notes = parsed.get("notes") or None
        return MappingOutcome(mapping=mapping, confidence=confidence, notes=notes)

    def _build_samples(self, df: pd.DataFrame, headers: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in df.head(5).itertuples(index=False, name=None):
            masked = []
            for value in row:
                text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
                masked.append(self._mask_sensitive(text))
            rows.append(masked)
        return rows

    def _mask_sensitive(self, value: str) -> str:
        if not value:
            return value
        masked_digits = re.sub(r"\d(?=\d{4})", "*", value)
        return masked_digits[:80]

    def _normalize_rows(
        self, df: pd.DataFrame, mapping: MappingOutcome, default_currency: str
    ) -> tuple[list[ParsedStatementRow], int, list[tuple[TransactionType, Decimal]]]:
        records = df.to_dict(orient="records")
        rows: list[ParsedStatementRow] = []
        skipped = 0
        summary_rows: list[tuple[TransactionType, Decimal]] = []

        for record in records[:1500]:  # safety limit
            amount_value, direction = self._extract_amount(record, mapping)
            if amount_value is None or direction is None:
                skipped += 1
                continue

            occurred_at = self._parse_date(record.get(mapping.mapping.get("date") or ""))
            if not occurred_at:
                skipped += 1
                continue

            currency_raw = self._string_value(record.get(mapping.mapping.get("currency") or ""))
            currency = self._normalize_currency(currency_raw, default_currency)
            description = self._string_value(record.get(mapping.mapping.get("description") or ""))
            if not description:
                description = self._fallback_description(record)
            bank_category = self._string_value(record.get(mapping.mapping.get("category") or ""))
            balance_value = self._parse_decimal(record.get(mapping.mapping.get("balance") or ""))
            card_value = self._string_value(record.get(mapping.mapping.get("card") or ""))

            if self._is_summary_row(description, bank_category):
                summary_rows.append((direction, amount_value))
                continue
            if amount_value == 0:
                skipped += 1
                continue

            rows.append(
                ParsedStatementRow(
                    amount=amount_value,
                    currency=currency,
                    direction=direction,
                    occurred_at=occurred_at,
                    description=repair_text(description),
                    short_description=self._clean_short_description(description),
                    category_name=repair_text(bank_category) if bank_category else None,
                    bank_category=repair_text(bank_category) if bank_category else None,
                    balance=balance_value,
                    card=card_value or None,
                )
            )

        return rows, skipped, summary_rows

    async def _annotate_categories(self, rows: list[ParsedStatementRow]) -> None:
        if not rows:
            return
        low_confidence: list[ParsedStatementRow] = []
        for row in rows:
            predicted, confidence, reason = self._predict_category(row)
            row.predicted_category = predicted
            row.category_confidence = confidence
            row.category_reason = reason
            if predicted:
                row.category_name = predicted
            if confidence < 0.5 and self.ai_enabled:
                low_confidence.append(row)
        if not low_confidence:
            return
        for row in low_confidence[:8]:  # safety cap for external calls
            ai_category, ai_reason = await self._ai_category(row)
            if not ai_category:
                continue
            row.predicted_category = ai_category
            row.category_name = ai_category
            row.category_confidence = max(row.category_confidence, 0.65)
            row.category_reason = ai_reason or row.category_reason

    def _predict_category(self, row: ParsedStatementRow) -> tuple[str | None, float, str | None]:
        haystack = self._build_keyword_haystack(row)
        bank_name = row.bank_category or ""
        mapped_bank = self._match_category_from_text(bank_name, direction=row.direction, source="category")
        if mapped_bank:
            return mapped_bank[0], 0.9, f"bank category hint: {bank_name}"

        if self._is_probable_transfer(haystack):
            transfer_match = self._match_category_from_text(haystack, direction=row.direction, force_key="Перекази")
            if transfer_match:
                return transfer_match[0], 0.82, f"transfer keyword: {transfer_match[1]}"

        keyword_match = self._match_category_from_text(haystack, direction=row.direction)
        if keyword_match:
            name, keyword = keyword_match
            base_conf = 0.8 if keyword else 0.65
            return name, base_conf, f"matched keyword: {keyword}" if keyword else "description-based classification"

        if row.direction == TransactionType.INCOME:
            return "Зарплата / Дохід", 0.55, "default income category"
        return "Інше", 0.35, "fallback category"

    def _match_category_from_text(
        self,
        text: str,
        *,
        direction: TransactionType | None = None,
        source: str = "description",
        force_key: str | None = None,
    ) -> tuple[str, str | None] | None:
        haystack = (text or "").lower()
        for category in STANDARD_CATEGORIES:
            if force_key and category["name"] != force_key:
                continue
            if direction == TransactionType.INCOME and category["type"] == "expense":
                continue
            if direction == TransactionType.EXPENSE and category["type"] == "income":
                continue
            for alias in category["aliases"]:
                if alias and alias.lower() in haystack:
                    return category["name"], alias
            for keyword in category["keywords"]:
                if keyword and keyword.lower() in haystack:
                    return category["name"], keyword
            if force_key and category["name"] == force_key:
                return category["name"], None
        return None

    async def _ai_category(self, row: ParsedStatementRow) -> tuple[str | None, str | None]:
        if not self._client:
            return None, None
        if self._ai_category_budget >= 8:
            return None, None
        self._ai_category_budget += 1
        categories = [category["name"] for category in STANDARD_CATEGORIES]
        prompt = {
            "description": row.short_description or row.description,
            "direction": "income" if row.direction == TransactionType.INCOME else "expense",
            "categories": categories,
            "bank_category": row.bank_category,
        }
        messages = [
            {
                "role": "system",
                "content": "Classify the transaction into a standard category. Return JSON {\"category\": \"...\", \"reason\": \"...\"}.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=200,
            )
        except OpenAIError as exc:  # pragma: no cover - network dependency
            logger.warning("AI category failed: {}", exc)
            return None, None
        raw = response.choices[0].message.content if response.choices else None
        if not raw:
            return None, None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, None
        category = parsed.get("category")
        if category not in categories:
            return None, None
        reason = parsed.get("reason") or "визначено AI"
        return category, reason

    def _build_keyword_haystack(self, row: ParsedStatementRow) -> str:
        parts = [row.description or "", row.short_description or "", row.bank_category or "", row.card or ""]
        return " ".join(part.lower() for part in parts if part)

    def _is_probable_transfer(self, text: str) -> bool:
        haystack = (text or "").lower()
        if not any(keyword in haystack for keyword in TRANSFER_HINTS):
            return False
        if any(keyword in haystack for keyword in MERCHANT_HINTS):
            return False
        return True

    async def _transaction_exists(self, session: AsyncSession, user_id: int, row: ParsedStatementRow) -> bool:
        start = row.occurred_at.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + pd.Timedelta(days=1)  # type: ignore[arg-type]
        stmt = (
            select(Transaction.id)
            .where(Transaction.user_id == user_id)
            .where(Transaction.direction == row.direction)
            .where(Transaction.currency == row.currency)
            .where(Transaction.amount == abs(row.amount))
            .where(Transaction.occurred_at >= start)
            .where(Transaction.occurred_at < end)
        )
        if row.description:
            stmt = stmt.where(func.lower(Transaction.description) == func.lower(row.description))
        existing = await session.scalar(stmt)
        return existing is not None

    def _extract_amount(self, record: dict[str, Any], mapping: MappingOutcome) -> tuple[Decimal | None, TransactionType | None]:
        def value_from(column: str | None) -> Decimal | None:
            if not column:
                return None
            return self._parse_decimal(record.get(column))

        amount = value_from(mapping.mapping.get("amount"))
        income_amount = value_from(mapping.income_column)
        expense_amount = value_from(mapping.expense_column)

        if amount is not None:
            direction = TransactionType.EXPENSE if amount < 0 else TransactionType.INCOME
            return abs(amount), direction

        if expense_amount is not None and expense_amount != 0:
            return abs(expense_amount), TransactionType.EXPENSE
        if income_amount is not None and income_amount != 0:
            return abs(income_amount), TransactionType.INCOME
        return None, None

    def _build_analytics(
        self, rows: list[ParsedStatementRow], summary_rows: list[tuple[TransactionType, Decimal]]
    ) -> StatementAnalytics:
        income_total = Decimal("0")
        expense_total = Decimal("0")
        category_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in rows:
            amount_abs = abs(row.amount)
            if row.direction == TransactionType.INCOME:
                income_total += amount_abs
            else:
                expense_total += amount_abs
            if row.category_name:
                category_totals[row.category_name] += amount_abs

        summary_totals = {
            "income": sum(abs(amount) for direction, amount in summary_rows if direction == TransactionType.INCOME),
            "expense": sum(abs(amount) for direction, amount in summary_rows if direction == TransactionType.EXPENSE),
        }
        discrepancy_note: str | None = None
        if summary_totals["income"] or summary_totals["expense"]:
            diff_income = income_total - summary_totals["income"]
            diff_expense = expense_total - summary_totals["expense"]
            if abs(diff_income) > Decimal("0.01") or abs(diff_expense) > Decimal("0.01"):
                discrepancy_note = (
                    f"Statement totals mismatch: income {diff_income:+.2f}, expense {diff_expense:+.2f}."
                )
        return StatementAnalytics(
            income_total=income_total,
            expense_total=expense_total,
            category_totals=dict(category_totals),
            summary_totals=summary_totals,
            discrepancy_note=discrepancy_note,
        )

    def _parse_decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace(" ", " ")
        text = re.sub(r"[^\d,.\-\(\)]", "", text)
        if not text:
            return None
        text = text.replace(" ", "")
        sign = -1 if text.startswith("(") and text.endswith(")") else 1
        text = text.strip("()")
        if text.endswith("-"):
            sign *= -1
            text = text[:-1]
        if text.count(",") and not text.count("."):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        try:
            return Decimal(text) * sign
        except (InvalidOperation, ValueError):
            return None

    def _parse_date(self, value: Any) -> datetime | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        parsed = pd.to_datetime(str(value), dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        dt = parsed.to_pydatetime()
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _string_value(self, value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip()

    def _fallback_description(self, record: dict[str, Any]) -> str:
        for key, value in record.items():
            if key and value and key != "amount":
                text = self._string_value(value)
                if text and not re.fullmatch(r"[\d\.,-]+", text):
                    return text
        return ""

    def _normalize_currency(self, value: str | None, default_currency: str) -> str:
        if not value:
            return default_currency
        normalized = value.strip().replace(".", "").upper()
        mapped = CURRENCY_SYNONYMS.get(normalized.lower())
        if mapped:
            return mapped
        return normalized or default_currency

    def _is_summary_row(self, description: str, bank_category: str | None) -> bool:
        haystack = f"{description or ''} {bank_category or ''}".lower()
        return any(keyword in haystack for keyword in SUMMARY_KEYWORDS)

    def _clean_short_description(self, value: str) -> str:
        if not value:
            return ""
        text = re.sub(r"\s+", " ", value).strip()
        text = re.sub(r"\b\d{4,}\b", "", text)  # remove long numeric tails (cards, refs)
        return text.strip(" -|")

    async def _resolve_category(
        self, session: AsyncSession, user_id: int, name: str | None, direction: TransactionType
    ) -> int | None:
        if not name:
            return None
        normalized = localize_category_name(name)
        stmt = select(Category.id).where(
            Category.user_id == user_id, func.lower(Category.name) == normalized.lower()
        )
        existing_id = await session.scalar(stmt)
        if existing_id:
            return existing_id
        category = Category(
            user_id=user_id,
            name=normalized,
            type=CategoryType.EXPENSE if direction == TransactionType.EXPENSE else CategoryType.INCOME,
            is_default=False,
        )
        session.add(category)
        await session.flush()
        return category.id


@dataclass
class StatementImportResult:
    rows: list[ParsedStatementRow]
    skipped: int
    mapping: MappingOutcome
    analytics: StatementAnalytics | None = None
