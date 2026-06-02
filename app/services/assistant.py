from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

try:
    from openai import AsyncOpenAI, OpenAIError
except Exception:  # pragma: no cover - optional dependency
    AsyncOpenAI = None
    OpenAIError = Exception

from app.core.config import Settings
from app.models import Transaction, TransactionType, User
from app.services.transactions import TransactionService
from app.utils.categories import localize_category_name


class AIAdvisor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.openai_api_key and AsyncOpenAI:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            self._client = None
        self.model = settings.openai_model

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def advise(
        self,
        user: User,
        question: str,
        tx_service: TransactionService,
        tone: str | None = None,
        period: str | None = None,
        month: str | None = None,
        start: str | None = None,
        end: str | None = None,
        source: str | None = None,
    ) -> str:
        if not self.enabled:
            return "AI-помічник недоступний. Додайте OPENAI_API_KEY у .env і перезапустіть."

        if self._needs_clarification(question):
            return self._build_clarification_response(question, user.language)

        source_filter = source if source not in (None, "", "all") else None
        start_local, end_local, start_utc, end_utc = self._resolve_period_range(user, month, period, start, end)
        period_label = self._format_period_label(start_local, end_local, user.language)
        recent_transactions = await tx_service.get_recent_transactions(
            user,
            limit=15,
            start=start_utc,
            end=end_utc,
            source=source_filter,
        )
        period_summary = await tx_service.summary_for_period(user, start_local, end_local, source=source_filter)
        all_time_summary = await tx_service.all_time_summary(user)
        summary = self._format_transactions(recent_transactions)
        insights = self._build_insights(recent_transactions, period_summary, all_time_summary, period_label)
        tone_instruction = self._tone_instruction(tone, user.language)
        style_rules = (
            "Формат відповіді: короткі абзаци й маркери '-'. "
            "Не використовуй markdown (#, *, ```), таблиці чи код. "
            "Не перелічуй всі транзакції й не пиши довгих розрахунків через '+'. "
            "Не більше 5 пунктів у списку. Якщо треба — узагальни. "
            "Обов'язково вказуй період (діапазон дат) у відповіді. "
            "Використовуй лише надані підсумки та топ-категорії. "
            "Якщо даних мало — коротко поясни і задай 1-2 уточнення."
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Ти фінансовий асистент. Відповідай практично, українською. "
                    "Спирайся на контекст користувача нижче, шукай тренди, ризики, повторювані витрати. "
                    "Давай конкретні поради й наступні кроки. Якщо бракує даних — попроси уточнення. "
                    "Не вигадуй цифри й не припускай фактів поза даними. "
                    f"{tone_instruction} {style_rules}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Контекст по фінансах:\n{insights}\n\nТранзакції за період:\n{summary}\n\nПитання: {question.strip()}"
                ),
            },
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=700,
            )
        except OpenAIError as exc:  # pragma: no cover - network dependency
            logger.warning("AIAdvisor error: {}", exc)
            return "AI тимчасово недоступний. Спробуйте пізніше."

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            return "AI не зміг підготувати відповідь. Спробуйте ще раз."
        answer = content.strip()
        if choice.finish_reason == "length":
            try:
                follow_messages = messages + [
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": "Продовж коротко і завершуй відповідь. Не повторюй уже сказане."},
                ]
                follow = await self._client.chat.completions.create(
                    model=self.model,
                    messages=follow_messages,
                    temperature=0.2,
                    max_tokens=220,
                )
                follow_choice = follow.choices[0] if follow.choices else None
                follow_text = follow_choice.message.content.strip() if follow_choice and follow_choice.message else ""
                if follow_text:
                    answer = f"{answer}\n{follow_text}"
            except OpenAIError as exc:  # pragma: no cover - network dependency
                logger.warning("AIAdvisor continuation error: {}", exc)
        return answer

    def _tone_instruction(self, tone: str | None, language: str | None) -> str:
        normalized = (tone or "short").lower()
        is_english = (language or "").lower().startswith("en")
        if normalized == "detailed":
            return (
                "Provide a detailed answer with clear sections and concrete steps. Keep it concise."
                if is_english
                else "Дай детальну відповідь зі структурою та конкретними кроками, але лаконічно."
            )
        if normalized == "numbers":
            return (
                "Answer with numbers only: totals, percentages, and concise bullet points. No extra commentary."
                if is_english
                else "Відповідай лише цифрами: суми, відсотки та короткі маркери без зайвих пояснень."
            )
        return "Be concise and practical." if is_english else "Будь коротким і практичним."

    def _needs_clarification(self, question: str) -> bool:
        cleaned = (question or "").strip().lower()
        if not cleaned:
            return True
        words = cleaned.split()
        if len(words) < 4:
            return True
        if not self._contains_finance_keywords(cleaned):
            return True
        return False

    def _contains_finance_keywords(self, cleaned: str) -> bool:
        keywords = [
            "витрат", "дохід", "баланс", "категор", "бюджет", "ліміт", "підписк", "транзак",
            "місяц", "тижд", "квартал", "день", "період", "заощад",
            "spend", "spent", "income", "balance", "category", "budget", "limit", "subscription", "transaction", "month",
            "week", "quarter", "period", "save",
        ]
        return any(keyword in cleaned for keyword in keywords)

    def _build_clarification_response(self, question: str, language: str | None) -> str:
        is_english = (language or "").lower().startswith("en")
        suggestions = []
        cleaned = (question or "").lower()
        if not self._mentions_period(cleaned):
            suggestions.append(
                "За який період потрібно підсумок? (тиждень, місяць, квартал)" if not is_english else
                "Which time period should I use? (week, month, quarter)"
            )
        suggestions.append(
            "Про що саме: витрати, дохід, баланс чи категорії?" if not is_english else
            "What should I focus on: spending, income, balance, or categories?"
        )
        suggestions.append(
            "Чи потрібне порівняння з попереднім періодом?" if not is_english else
            "Should I compare with a previous period?"
        )
        suggestions = suggestions[:3]
        header = "Щоб відповісти точніше, уточніть:" if not is_english else "To answer precisely, please clarify:"
        bullets = "\n".join(f"- {item}" for item in suggestions)
        return f"{header}\n{bullets}"

    def _mentions_period(self, cleaned: str) -> bool:
        markers = [
            "місяц", "тижд", "квартал", "день", "сьогодні", "вчора", "рік", "період",
            "month", "week", "quarter", "day", "today", "yesterday", "year", "period",
        ]
        return any(marker in cleaned for marker in markers)

    def _format_transactions(self, transactions: list[Transaction]) -> str:
        if not transactions:
            return "Немає транзакцій за останній період."
        lines = []
        preview = transactions[:5]
        for tx in preview:
            direction = "витрата" if tx.direction == TransactionType.EXPENSE else "дохід"
            category = localize_category_name(tx.category.name if tx.category else None, default="без категорії")
            description = tx.description or "-"
            lines.append(f"- {direction}: {float(tx.amount):.2f} {tx.currency} ({category}) — {description}")
        remaining = max(0, len(transactions) - len(preview))
        if remaining:
            lines.append(f"- …ще {remaining} транзакцій")
        return "\n".join(lines)

    def _build_insights(self, transactions, period_summary, all_time_summary, period_label: str) -> str:
        if not transactions:
            return f"Період {period_label}: транзакцій немає — даних для аналізу поки немає."

        expense_total = float(period_summary.total_expense or 0)
        income_total = float(period_summary.total_income or 0)
        net = float(period_summary.net or 0)
        top_categories = period_summary.top_categories or []
        top_lines = [
            f"- {item.category}: {float(item.total):.2f} {period_summary.currency}"
            for item in top_categories[:5]
        ]

        recurring = self._find_recurring_merchants(transactions)
        recurring_line = ", ".join(recurring[:5]) if recurring else "немає явних повторів"

        return (
            f"Період {period_label}: витрати {expense_total:.2f} {period_summary.currency}, "
            f"дохід {income_total:.2f} {period_summary.currency}, баланс {net:.2f} {period_summary.currency}.\n"
            f"Топ категорії: {'; '.join(top_lines) if top_lines else 'немає'}.\n"
            f"Повторювані витрати/мерчанти: {recurring_line}.\n"
            f"Усього за весь час: витрати {float(all_time_summary.total_expense or 0):.2f} {all_time_summary.currency}, "
            f"дохід {float(all_time_summary.total_income or 0):.2f} {all_time_summary.currency}."
        )

    def _find_recurring_merchants(self, transactions: list[Transaction]) -> list[str]:
        counts: dict[str, int] = {}
        for tx in transactions:
            if tx.direction != TransactionType.EXPENSE:
                continue
            if not tx.description:
                continue
            key = self._normalize_merchant(tx.description)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
        ranked = sorted((k for k, v in counts.items() if v >= 2), key=lambda k: counts[k], reverse=True)
        return ranked

    def _normalize_merchant(self, text: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
        cleaned = " ".join(cleaned.split())
        return cleaned[:40]

    def _parse_month(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m")
        except ValueError:
            return None
        return date(parsed.year, parsed.month, 1)

    def _resolve_period_range(
        self,
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
            target = self._parse_month(month_value) or now_local.date()
            quarter = (target.month - 1) // 3
            start_month = quarter * 3 + 1
            start_local = datetime(target.year, start_month, 1, tzinfo=tz)
            if start_month == 10:
                end_local = datetime(target.year + 1, 1, 1, tzinfo=tz)
            else:
                end_local = datetime(target.year, start_month + 3, 1, tzinfo=tz)
        else:
            target = self._parse_month(month_value) or now_local.date()
            start_local = datetime(target.year, target.month, 1, tzinfo=tz)
            if target.month == 12:
                end_local = datetime(target.year + 1, 1, 1, tzinfo=tz)
            else:
                end_local = datetime(target.year, target.month + 1, 1, tzinfo=tz)

        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        return start_local, end_local, start_utc, end_utc

    def _format_period_label(self, start_local: datetime, end_local: datetime, language: str | None) -> str:
        start_date = start_local.date()
        end_date = end_local.date()
        if end_local.time() == time(0, 0) and end_local > start_local:
            end_date = (end_local - timedelta(days=1)).date()
        return f"{start_date:%Y-%m-%d} — {end_date:%Y-%m-%d}"
