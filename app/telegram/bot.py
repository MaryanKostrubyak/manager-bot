from __future__ import annotations





from collections import defaultdict

from contextlib import asynccontextmanager

from datetime import date, datetime, timedelta, timezone

from decimal import Decimal, InvalidOperation

from io import BytesIO

from zoneinfo import ZoneInfo



from loguru import logger

from sqlalchemy import func, select

from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo

from telegram.error import TelegramError

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters



from app.core.config import Settings

from app.db.session import AsyncSessionLocal

from app.models import BudgetPeriod, Category, CategoryType, Transaction, TransactionType, User

from app.schemas import AnalyticsSummary, BudgetLimitCreate, TransactionCreate

from app.services.assistant import AIAdvisor
from app.services.budgets import BudgetService

from app.services.receipt_ai import GPTReceiptParser

from app.services.reports import ReportService

from app.services.transactions import TransactionService

from app.services.users import UserService
from app.utils.categories import localize_category_name
from app.utils.text import repair_text
from app.utils.subscriptions import is_subscription

"""Telegram bot entrypoint: handlers wiring and business services for finance assistant."""

from app.telegram.keyboards import (
    budget_menu_keyboard,
    budget_period_keyboard,
    chart_type_keyboard,
    category_keyboard,
    entry_date_keyboard,
    main_menu_keyboard,
    quick_confirm_keyboard,
    receipt_confirmation_keyboard,
    settings_keyboard,
    timezone_keyboard,
)




TIMEZONE_STATE_KEY = "awaiting_timezone"
CAPTURE_STATE_KEY = "capture"
REPORT_DATE_STATE_KEY = "awaiting_report_date"
BUDGET_STATE_KEY = "budget_state"
RECEIPT_STATE_KEY = "receipt_draft"
RECEIPT_EDIT_STATE_KEY = "receipt_edit"
AI_ASSIST_STATE_KEY = "ai_assist"

DATE_INPUT_FORMAT = "%Y-%m-%d"

DATE_OUTPUT_FORMAT = "%d.%m.%Y"

MONTH_PICKER_MONTHS = 6

HISTORY_PAGE_SIZE = 7




MONTH_NAMES = {
    1: "січень",
    2: "лютий",
    3: "березень",
    4: "квітень",
    5: "травень",
    6: "червень",
    7: "липень",
    8: "серпень",
    9: "вересень",
    10: "жовтень",
    11: "листопад",
    12: "грудень",
}







class TelegramBot:
    """Main Telegram bot wrapper: registers handlers and coordinates services."""

    def __init__(self, settings: Settings) -> None:

        self.settings = settings

        self.receipt_parser = GPTReceiptParser(settings)

        self.ai_advisor = AIAdvisor(settings)

        self.receipt_usage: dict[int, list[datetime]] = defaultdict(list)

        self.web_app_url = settings.web_app_url



    def build_application(self) -> Application:
        """Configure and return telegram.ext Application with all handlers."""

        application = Application.builder().token(self.settings.telegram_bot_token).build()

        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("timezone", self.configure_timezone))
        application.add_handler(CommandHandler("history", self.command_history))
        application.add_handler(CommandHandler("web", self.command_web))
        application.add_handler(CommandHandler("settings", self.command_settings))

        application.add_handler(CallbackQueryHandler(self.handle_callback))

        application.add_handler(MessageHandler(filters.PHOTO, self.handle_receipt_photo))

        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_text))

        return application




    @asynccontextmanager


    async def _session(self):


        async with AsyncSessionLocal() as session:


            yield session





    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        if not telegram_user or not chat:


            return





        async with self._session() as session:


            service = UserService(session)


            user = await service.ensure_user(telegram_user.id, telegram_user.username)


            await session.commit()





        text = (
            "Привіт! Я допоможу швидко фіксувати витрати й доходи у чаті.\n"
            "Аналітика, графіки та повна історія — у мініапці."
        )


        await chat.send_message(text, reply_markup=main_menu_keyboard(self.web_app_url))




        if not user.onboarding_completed:


            await self._prompt_timezone_selection(chat, current=user.timezone)





    async def configure_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        if not chat:

            return

        await self._prompt_timezone_selection(chat)



    def update_web_app_url(self, url: str | None) -> None:
        # Accept http/https for local dev; Telegram web app links are not sensitive here.
        self.web_app_url = url
        if url:
            logger.info("Web app URL set to {}", url)




    async def prompt_report_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        if not chat:

            return

        await self._request_report_date(chat, context)



    async def command_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat
        telegram_user = update.effective_user

        if chat and telegram_user:

            user = await self._ensure_user_model(telegram_user)

            await self._prompt_month_selection(chat, "report", user)


    async def command_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat
        telegram_user = update.effective_user

        if chat and telegram_user:

            user = await self._ensure_user_model(telegram_user)

            await self._prompt_month_selection(chat, "chart", user)

    async def command_goals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat
        telegram_user = update.effective_user

        if chat and telegram_user:

            await self._show_budget_menu(chat, telegram_user)

    async def command_assistant(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        if chat:

            await self._prompt_ai_question(chat, context)



    async def command_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        telegram_user = update.effective_user

        if chat and telegram_user:

            await self._show_transaction_history(chat, telegram_user)



    async def command_web(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        if not chat:

            return

        if self.web_app_url:

            await chat.send_message(f"Веб-версія доступна за посиланням: {self.web_app_url}")

        else:

            await chat.send_message("Веб-версія поки недоступна. Спробуйте пізніше.")





    async def command_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

        chat = update.effective_chat

        telegram_user = update.effective_user

        if not chat or not telegram_user:

            return

        user = await self._ensure_user_model(telegram_user)

        await self._send_settings_menu(chat, user)



    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        telegram_user = update.effective_user
        if not query or not telegram_user:
            return

        await query.answer()
        data = query.data or ""

        if data.startswith("settings"):
            await self._handle_settings_callback(update, context, data)
            return

        if data == "export:month":
            await self._send_export(update)
            return

        if data == "receipt:help":
            if query.message:
                await query.message.reply_text("Надішліть фото чека, і я підготую запис для підтвердження.")
            return

        if data == "receipt:confirm":
            await self._handle_receipt_confirmation(update, context)
            return

        if data == "receipt:cancel":
            await self._handle_receipt_cancel(update, context)
            return

        if data == "receipt:amount":
            await self._prompt_receipt_amount(update, context)
            return

        if data == "receipt:category":
            await self._prompt_receipt_category(update, context)
            return

        if data.startswith("add:"):
            direction = TransactionType.EXPENSE if data.endswith("expense") else TransactionType.INCOME
            chat = query.message.chat if query.message else update.effective_chat
            if not chat:
                return
            await self._start_quick_entry(chat, telegram_user, context, direction)
            return

        if data == "quick:confirm":
            await self._confirm_quick_entry(update, context)
            return

        if data == "quick:cancel":
            await self._cancel_quick_entry(update, context)
            return

        if data == "quick:category":
            await self._prompt_quick_category(update, context)
            return

        if data == "quick:date":
            await self._prompt_quick_date(update, context)
            return

        if data == "history:menu":
            if query.message:
                await self._show_transaction_history(query.message.chat, telegram_user)
            return

        if data.startswith("history:del:"):
            payload = data.split(":", 2)[2]
            await self._handle_history_delete(update, context, payload)
            return

        if data.startswith("category:"):
            await self._select_category(update, context, data.split(":", 1)[1])
            return

        if data.startswith("timezone"):
            await self._handle_timezone_callback(update, context, data.split(":", 1)[1])
            return

        if data.startswith("date:"):
            await self._handle_date_callback(update, context, data.split(":", 1)[1])
            return

        if data.startswith("chart:") or data.startswith("report:") or data.startswith("budget:") or data.startswith("assistant:"):
            await self._send_web_app_hint(query.message)
            return

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text if update.message else ""

        if context.user_data.get(TIMEZONE_STATE_KEY):
            await self._handle_timezone_text(update, context, text)
            return

        receipt_edit = context.user_data.get(RECEIPT_EDIT_STATE_KEY)
        if receipt_edit:
            await self._handle_receipt_edit_text(update, context, text, receipt_edit)
            return

        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if capture_state:
            stage = capture_state.get("stage")
            if stage == "date_manual":
                await self._handle_manual_date_text(update, context, text)
                return
            if stage == "category_manual":
                await self._handle_manual_category_text(update, context, text)
                return
            if stage in {"await_input", "edit_amount"}:
                await self._handle_quick_entry_text(update, context, text, capture_state)
                return

        handled = await self._try_quick_entry_from_text(update, context, text)
        if handled:
            return

    async def _send_web_app_hint(self, message) -> None:
        if not message:
            return
        keyboard = None
        if self.web_app_url and self.web_app_url.startswith("https://"):
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Відкрити мініапку", web_app=WebAppInfo(url=self.web_app_url))]]
            )
        await message.reply_text("Ця дія доступна в мініапці.", reply_markup=keyboard)

    async def _start_quick_entry(self, chat, telegram_user, context, direction: TransactionType) -> None:
        existing_state = context.user_data.get(CAPTURE_STATE_KEY)
        if existing_state:
            await self._clear_category_prompt(context, existing_state)
        user = await self._ensure_user_model(telegram_user)
        context.user_data[CAPTURE_STATE_KEY] = {
            "direction": direction,
            "stage": "await_input",
            "timezone": user.timezone or "UTC",
            "chat_id": chat.id,
        }
        await chat.send_message(
            "Введіть суму та короткий опис. Наприклад: `150 кава` або `+2000 зарплата`.",
            parse_mode="Markdown",
        )

    async def _handle_quick_entry_text(self, update: Update, context, text: str, capture_state: dict) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        if not telegram_user or not chat:
            return
        try:
            tz = ZoneInfo(capture_state.get("timezone") or "UTC")
            amount, direction, description, entry_date, category_hint = self._parse_quick_entry(
                text, capture_state.get("direction"), tz
            )
        except (InvalidOperation, ValueError, IndexError):
            await chat.send_message("Не вдалося розпізнати суму. Приклад: `120 кава`.", parse_mode="Markdown")
            return

        user = await self._ensure_user_model(telegram_user)
        draft = await self._build_quick_draft(user, amount, direction, description, entry_date, category_hint)
        context.user_data[CAPTURE_STATE_KEY] = draft
        await self._send_quick_preview(chat, user, draft)

    async def _try_quick_entry_from_text(self, update: Update, context, text: str) -> bool:
        telegram_user = update.effective_user
        chat = update.effective_chat
        if not telegram_user or not chat:
            return False
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        user = await self._ensure_user_model(telegram_user)
        tz = ZoneInfo(user.timezone or "UTC")
        try:
            amount, direction, description, entry_date, category_hint = self._parse_quick_entry(cleaned, None, tz)
        except (InvalidOperation, ValueError, IndexError):
            return False
        draft = await self._build_quick_draft(user, amount, direction, description, entry_date, category_hint)
        context.user_data[CAPTURE_STATE_KEY] = draft
        await self._send_quick_preview(chat, user, draft)
        return True

    async def _build_quick_draft(
        self,
        user: User,
        amount: Decimal,
        direction: TransactionType,
        description: str,
        entry_date: date | None,
        category_hint: str | None,
    ) -> dict:
        draft = {
            "direction": direction,
            "amount": amount,
            "description": description or "",
            "date": entry_date,
            "stage": "confirm",
            "timezone": user.timezone or "UTC",
        }
        async with self._session() as session:
            category_id = None
            if category_hint:
                category_id = await self._resolve_category(session, user.id, category_hint, direction)
            if not category_id:
                category_id = await self._last_category_id(session, user, direction)
            if category_id:
                draft["category_id"] = category_id
        return draft

    async def _last_category_id(self, session, user: User, direction: TransactionType) -> int | None:
        tx_service = TransactionService(session)
        recent = await tx_service.get_recent_transactions(user, limit=1, direction=direction)
        if recent:
            return recent[0].category_id
        return None

    def _parse_quick_entry(
        self, text: str, default_direction: TransactionType | None, tz: ZoneInfo
    ) -> tuple[Decimal, TransactionType, str, date | None, str | None]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("empty")
        tokens = cleaned.split()
        amount_token = tokens[0]
        sign = None
        if amount_token[:1] in {"+", "-"}:
            sign = amount_token[0]
            amount_token = amount_token[1:]
        amount = Decimal(amount_token.replace(",", "."))
        direction = default_direction or TransactionType.EXPENSE
        if sign == "-":
            direction = TransactionType.EXPENSE
        elif sign == "+":
            direction = TransactionType.INCOME

        entry_date = None
        if len(tokens) > 1:
            date_token = tokens[-1].lower()
            today = datetime.now(tz).date()
            if date_token in {"today", "сьогодні", "сегодня"}:
                entry_date = today
            elif date_token in {"yesterday", "вчора", "учора", "вчера"}:
                entry_date = today - timedelta(days=1)
            else:
                parsed = self._parse_date_token(date_token, today)
                if parsed:
                    entry_date = parsed
            if entry_date:
                tokens = tokens[:-1]

        remainder = tokens[1:]
        description = " ".join(remainder).strip()
        category_hint = remainder[0] if remainder else None
        return amount, direction, description, entry_date, category_hint

    def _parse_date_token(self, token: str, today: date) -> date | None:
        if len(token) == 10 and token[4] == "-" and token[7] == "-":
            try:
                return datetime.strptime(token, "%Y-%m-%d").date()
            except ValueError:
                return None
        if "." in token:
            try:
                day_part, month_part = token.split(".", 1)
                day = int(day_part)
                month = int(month_part)
                return date(today.year, month, day)
            except (ValueError, TypeError):
                return None
        return None

    async def _send_quick_preview(self, chat, user: User, draft: dict) -> None:
        amount = draft.get("amount")
        direction = draft.get("direction")
        sign = "-" if direction == TransactionType.EXPENSE else "+"
        date_value = draft.get("date") or datetime.now(ZoneInfo(user.timezone or "UTC")).date()
        date_label = date_value.strftime(DATE_OUTPUT_FORMAT)
        description = draft.get("description") or "—"

        category_label = "Без категорії"
        category_id = draft.get("category_id")
        if category_id:
            async with self._session() as session:
                name = await session.scalar(select(Category.name).where(Category.id == category_id))
                category_label = self._category_label(name)

        text = (
            "Попередній запис:\n"
            f"{sign}{float(amount):.2f} {user.currency} · {category_label} · {date_label}"
        )
        if description and description != "—":
            text += f"\nОпис: {self._repair_text(description)}"

        await chat.send_message(text, reply_markup=quick_confirm_keyboard(self.web_app_url))

    async def _confirm_quick_entry(self, update: Update, context) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        draft = context.user_data.get(CAPTURE_STATE_KEY)
        if not telegram_user or not chat or not draft:
            return

        if draft.get("stage") != "confirm":
            await chat.send_message("Немає чернетки для підтвердження.")
            return

        async with self._session() as session:
            user_service = UserService(session)
            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)
            transaction_service = TransactionService(session)

            category_id = draft.get("category_id")
            description = draft.get("description") or "?"
            occurred_at = self._resolve_occurred_at(user, draft.get("date"))
            category_title = None
            if category_id:
                category_title = await session.scalar(select(Category.name).where(Category.id == category_id))
            tags = ["manual"]
            if is_subscription(description, category_title):
                tags.append("subscription")

            transaction = await transaction_service.add_transaction(
                user,
                TransactionCreate(
                    amount=draft.get("amount"),
                    currency=user.currency,
                    direction=draft.get("direction"),
                    category_id=category_id,
                    description=description,
                    tags=tags,
                    occurred_at=occurred_at,
                ),
            )
            await session.commit()
            await session.refresh(transaction, attribute_names=["category"])

        context.user_data.pop(CAPTURE_STATE_KEY, None)
        label = self._category_label(transaction.category.name if transaction.category else None)
        sign = "-" if transaction.direction == TransactionType.EXPENSE else "+"
        date_label = transaction.occurred_at.strftime(DATE_OUTPUT_FORMAT) if transaction.occurred_at else ""
        await chat.send_message(
            f"Збережено: {sign}{float(transaction.amount):.2f} {transaction.currency} · {label} · {date_label}",
            reply_markup=main_menu_keyboard(self.web_app_url),
        )

    async def _cancel_quick_entry(self, update: Update, context) -> None:
        chat = update.effective_chat
        context.user_data.pop(CAPTURE_STATE_KEY, None)
        if chat:
            await chat.send_message("Скасовано.", reply_markup=main_menu_keyboard(self.web_app_url))

    async def _prompt_quick_category(self, update: Update, context) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if not telegram_user or not chat or not capture_state:
            return
        user = await self._ensure_user_model(telegram_user)
        await self._prompt_category_selection(context, chat, user, capture_state)

    async def _prompt_quick_date(self, update: Update, context) -> None:
        chat = update.effective_chat
        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if not chat or not capture_state:
            return
        capture_state["stage"] = "date"
        await chat.send_message(
            "Оберіть дату операції:", reply_markup=entry_date_keyboard(self._format_date_hint(capture_state))
        )

    def _format_date_hint(self, capture_state: dict) -> str:
        tz = ZoneInfo(capture_state.get("timezone") or "UTC")
        return datetime.now(tz).date().strftime(DATE_OUTPUT_FORMAT)

    async def _prompt_receipt_amount(self, update: Update, context) -> None:
        chat = update.effective_chat
        if not context.user_data.get(RECEIPT_STATE_KEY) or not chat:
            return
        context.user_data[RECEIPT_EDIT_STATE_KEY] = "amount"
        await chat.send_message("Вкажіть суму чека (наприклад: 250.50).")

    async def _prompt_receipt_category(self, update: Update, context) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        if not telegram_user or not chat:
            return
        if not context.user_data.get(RECEIPT_STATE_KEY):
            await chat.send_message("Спочатку надішліть фото чека.")
            return
        user = await self._ensure_user_model(telegram_user)
        choices = await self._category_choices(user.id, TransactionType.EXPENSE)
        context.user_data[RECEIPT_EDIT_STATE_KEY] = "category"
        await chat.send_message("Оберіть категорію для чека:", reply_markup=category_keyboard(choices))

    async def _handle_receipt_edit_text(self, update: Update, context, text: str, edit_state: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        draft = context.user_data.get(RECEIPT_STATE_KEY)
        if not telegram_user or not chat or not draft:
            return

        if edit_state == "amount":
            try:
                value = Decimal(text.replace(",", "."))
            except (InvalidOperation, ValueError):
                await chat.send_message("Не вдалося розпізнати суму. Приклад: 250.50")
                return
            if value <= 0:
                await chat.send_message("Сума має бути більшою за нуль.")
                return
            draft["amount"] = str(value)
            context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)
            user = await self._ensure_user_model(telegram_user)
            await self._send_receipt_preview(chat, user, draft)
            return

        if edit_state == "category_manual":
            name = text.strip()
            if not name:
                await chat.send_message("Введіть назву категорії, будь ласка.")
                return
            async with self._session() as session:
                user_service = UserService(session)
                user = await user_service.ensure_user(telegram_user.id, telegram_user.username)
                category_id = await self._ensure_category(session, user, name, TransactionType.EXPENSE)
                await session.commit()
            draft["category_id"] = category_id
            draft["category_hint"] = name
            context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)
            user = await self._ensure_user_model(telegram_user)
            await self._send_receipt_preview(chat, user, draft)
            return

    async def _send_receipt_preview(self, chat, user: User, draft: dict) -> None:
        amount_value = draft.get("amount")
        try:
            amount_label = f"{float(Decimal(str(amount_value))):.2f}"
        except (InvalidOperation, ValueError, TypeError):
            amount_label = str(amount_value or "-")
        merchant = draft.get("merchant") or "Невідомо"
        category_hint = draft.get("category_hint") or "Без категорії"
        category_id = draft.get("category_id")
        if category_id:
            async with self._session() as session:
                name = await session.scalar(select(Category.name).where(Category.id == category_id))
                if name:
                    category_hint = self._category_label(name)
        date_str = draft.get("date")
        date_label = date_str or "без дати"
        text = (
            "AI розпізнав чек:\n"
            f"Сума: {amount_label} {draft.get('currency') or user.currency}\n"
            f"Магазин: {merchant}\n"
            f"Категорія: {category_hint}\n"
            f"Дата: {date_label}\n"
            "Підтвердити додавання?"
        )
        await chat.send_message(text, reply_markup=receipt_confirmation_keyboard(self.web_app_url))

    async def _handle_amount_entry(self, update: Update, context, text: str, capture_state: dict) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        if not telegram_user or not chat:


            return





        try:


            amount, description, category_name = self._parse_message(text)


        except (InvalidOperation, IndexError):


            await chat.send_message("Не вдалося розпізнати суму. Приклад: `120 витрата таксі`")


            return





        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)


            transaction_service = TransactionService(session)





            category_id = capture_state.get("category_id")


            if not category_id and category_name:


                category_id = await self._resolve_category(session, user.id, category_name, capture_state["direction"])





            if not category_id:


                await chat.send_message("Не знайшов таку категорію (назва має збігатися з варіантами на клавіатурі).")


                return





            occurred_at = self._resolve_occurred_at(user, capture_state.get("date"))
            category_title = await session.scalar(select(Category.name).where(Category.id == category_id))
            tags = ["manual"]
            if is_subscription(description, category_title):
                tags.append("subscription")





            transaction = await transaction_service.add_transaction(


                user,


                TransactionCreate(


                    amount=amount,


                    currency=user.currency,


                    direction=capture_state["direction"],


                    category_id=category_id,


                    description=description,


                    tags=tags,


                    occurred_at=occurred_at,


                ),


            )


            await session.commit()


            await session.refresh(transaction, attribute_names=["category"])





            await self._notify_budget_alerts(user.id, transaction.category_id, chat)





        await self._clear_category_prompt(context, capture_state)


        context.user_data.pop(CAPTURE_STATE_KEY, None)


        category_label = self._category_label(transaction.category.name if transaction.category else None)


        direction_label = "Витрата" if capture_state["direction"] == TransactionType.EXPENSE else "Дохід"


        date_label = (


            capture_state.get("date").strftime(DATE_OUTPUT_FORMAT)


            if capture_state.get("date")


            else "сьогодні"


        )


        description_suffix = f" - {description}" if description else ""


        await chat.send_message(


            f"Збережено {direction_label}: {float(transaction.amount):.2f} {transaction.currency}"


            f" ({category_label}) на {date_label}{description_suffix}"


        )





    async def _handle_manual_category_text(self, update: Update, context, text: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        receipt_state = context.user_data.get(RECEIPT_STATE_KEY)
        receipt_edit = context.user_data.get(RECEIPT_EDIT_STATE_KEY)

        if receipt_state and receipt_edit == "category_manual":
            name = text.strip()
            if not name:
                await chat.send_message("Введіть назву категорії, будь ласка.")
                return
            async with self._session() as session:
                user_service = UserService(session)
                user = await user_service.ensure_user(telegram_user.id, telegram_user.username)
                category_id = await self._ensure_category(session, user, name, TransactionType.EXPENSE)
                await session.commit()
            receipt_state["category_id"] = category_id
            receipt_state["category_hint"] = name
            context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)
            user = await self._ensure_user_model(telegram_user)
            await self._send_receipt_preview(chat, user, receipt_state)
            return

        if not telegram_user or not chat or not capture_state:
            return

        if capture_state.get("stage") != "category_manual":
            await chat.send_message("Зараз не очікую назву категорії. Скористайтесь кнопками нижче.")
            return

        name = text.strip()
        if not name:
            await chat.send_message("Введіть назву категорії, будь ласка.")
            return

        async with self._session() as session:
            user_service = UserService(session)
            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)
            category_id = await self._ensure_category(session, user, name, capture_state["direction"])
            await session.commit()

        capture_state["category_id"] = category_id
        capture_state["stage"] = "confirm"
        await self._send_quick_preview(chat, user, capture_state)

    async def _handle_date_callback(self, update: Update, context, value: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if not telegram_user or not chat or not capture_state:
            return

        user = await self._ensure_user_model(telegram_user)
        tz = ZoneInfo(capture_state.get("timezone") or user.timezone or "UTC")
        today = datetime.now(tz).date()

        if value == "manual":
            capture_state["stage"] = "date_manual"
            await chat.send_message("Введіть дату у форматі РРРР-ММ-ДД, наприклад 2025-11-18.")
            return

        capture_state["date"] = today if value == "today" else today - timedelta(days=1)
        capture_state["stage"] = "confirm"
        await self._send_quick_preview(chat, user, capture_state)

    async def _handle_manual_date_text(self, update: Update, context, text: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if not telegram_user or not chat or not capture_state:
            return

        try:
            parsed = datetime.strptime(text.strip(), DATE_INPUT_FORMAT).date()
        except ValueError:
            await chat.send_message("Не вдалося розпізнати дату. Формат: рік-місяць-день.")
            return

        capture_state["date"] = parsed
        capture_state["stage"] = "confirm"
        user = await self._ensure_user_model(telegram_user)
        await self._send_quick_preview(chat, user, capture_state)

    async def _show_budget_menu(self, chat, telegram_user) -> None:


        user = await self._ensure_user_model(telegram_user)


        async with self._session() as session:


            service = BudgetService(session)


            limits = await service.list_limits(user.id)


            if not limits:


                await chat.send_message(


                    "У вас поки немає бюджетів. Натисніть кнопку нижче й додайте перший ліміт.",


                    reply_markup=budget_menu_keyboard(),


                )


                return





            lines = []


            for limit in limits:


                progress = await service.progress(limit)


                lines.append(self._format_budget_progress(progress))





        text = "?? Поточні бюджети:\n" + "\n".join(lines)

        await chat.send_message(text, reply_markup=budget_menu_keyboard())




    async def _start_budget_flow(self, chat, context, telegram_user) -> None:


        user = await self._ensure_user_model(telegram_user)


        context.user_data.pop(BUDGET_STATE_KEY, None)


        context.user_data.pop(CAPTURE_STATE_KEY, None)





        choices = await self._category_choices(user.id, TransactionType.EXPENSE)


        if not choices:


            await chat.send_message("Створіть хоча б одну категорію витрат, щоб задати ліміт.")


            return





        keyboard = self._budget_category_keyboard(choices)


        context.user_data[BUDGET_STATE_KEY] = {"stage": "category", "user_id": user.id}


        await chat.send_message("Оберіть категорію, для якої створюємо ліміт:", reply_markup=keyboard)





    async def _handle_budget_category_callback(self, update: Update, context, value: str) -> None:


        state = context.user_data.get(BUDGET_STATE_KEY)


        chat = update.effective_chat


        if not state or state.get("stage") != "category" or not chat:


            await update.callback_query.message.reply_text("Цей вибір уже неактивний. Почніть налаштування бюджету заново.")


            return





        try:


            category_id = int(value)


        except ValueError:


            await update.callback_query.message.reply_text("Не вдалося обробити вибрану категорію.")


            return





        state["category_id"] = category_id


        state["stage"] = "amount"


        await update.callback_query.message.reply_text("Введіть суму ліміту в гривнях, наприклад `2500`.", parse_mode="Markdown")





    async def _handle_budget_period_callback(self, update: Update, context, value: str) -> None:


        state = context.user_data.get(BUDGET_STATE_KEY)


        chat = update.effective_chat


        if not state or state.get("stage") != "period" or not chat:


            await update.callback_query.message.reply_text("Налаштування бюджету неактивне. Спробуйте ще раз.")


            return





        mapping = {


            "daily": BudgetPeriod.DAILY,


            "weekly": BudgetPeriod.WEEKLY,


            "monthly": BudgetPeriod.MONTHLY,


        }


        period = mapping.get(value)


        if not period:


            await update.callback_query.message.reply_text("Невідомий період бюджету.")


            return





        state["period"] = period


        state["stage"] = "threshold"


        await update.callback_query.message.reply_text(


            "Який відсоток використання вважати критичним? Напишіть число (наприклад `80`) або `пропустити`.",


            parse_mode="Markdown",


        )





    async def _handle_budget_text(self, update: Update, context, text: str, budget_state: dict) -> None:


        chat = update.effective_chat


        telegram_user = update.effective_user


        if not chat or not telegram_user:


            return





        stage = budget_state.get("stage")


        if stage == "amount":


            try:


                amount = Decimal(text.replace(",", "."))


            except InvalidOperation:


                await chat.send_message("Будь ласка, введіть коректну суму. Приклад: `2500`.")


                return





            if amount <= 0:


                await chat.send_message("Сума має бути більшою за нуль.")


                return





            budget_state["amount"] = amount


            budget_state["stage"] = "period"


            await chat.send_message("Оберіть період ліміту:", reply_markup=budget_period_keyboard())


            return





        if stage == "threshold":


            threshold_text = text.strip().lower()


            if threshold_text in {"", "skip", "пропустити"}:


                threshold = 0.9


            else:


                try:


                    value = float(threshold_text.replace(",", "."))


                except ValueError:


                    await chat.send_message("Введіть значення від 10 до 100 або слово `пропустити`.", parse_mode="Markdown")


                    return


                if value > 1:


                    value = value / 100


                threshold = max(0.1, min(value, 1.0))





            await self._finalize_budget_limit(update, context, budget_state, threshold)


            return





        await chat.send_message("Щось пішло не так під час налаштування. Почніть знову.")





    async def _finalize_budget_limit(


        self, update: Update, context, budget_state: dict, threshold: float


    ) -> None:


        chat = update.effective_chat


        telegram_user = update.effective_user


        if not chat or not telegram_user:


            return





        required_keys = {"category_id", "amount", "period"}


        if not required_keys.issubset(budget_state):


            await chat.send_message("Не вистачає даних для створення ліміту. Спробуйте налаштувати бюджет з початку.")


            context.user_data.pop(BUDGET_STATE_KEY, None)


            return





        payload = BudgetLimitCreate(


            category_id=budget_state["category_id"],


            amount=budget_state["amount"],


            period=budget_state["period"],


            alert_threshold=threshold,


        )





        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)


            budget_service = BudgetService(session)


            limit = await budget_service.create_limit(user.id, payload)


            await session.commit()


            await session.refresh(limit, attribute_names=["category"])





        context.user_data.pop(BUDGET_STATE_KEY, None)


        category_name = self._category_label(limit.category.name if limit.category else None)
        await chat.send_message(
            f"Створено ліміт: {category_name} на {float(limit.amount):.2f} за {self._period_label(limit.period)}."
        )


        await self._show_budget_menu(chat, telegram_user)





    def _budget_category_keyboard(self, items: list[tuple[int, str]]) -> InlineKeyboardMarkup:


        buttons = [


            InlineKeyboardButton(title, callback_data=f"budget:category:{category_id}")


            for category_id, title in items


        ]


        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]


        return InlineKeyboardMarkup(rows)





    def _format_budget_progress(self, progress) -> str:


        limit = progress.limit


        category = self._category_label(limit.category_name)


        percent = min(progress.percent, 999)


        bar = self._render_progress_bar(percent)


        remaining = float(progress.remaining)


        amount = float(limit.amount)


        return (

            f"{category}: {float(progress.spent):.2f}/{amount:.2f} ({percent:.0f}%){bar}\n"

            f"Залишок: {remaining:.2f} за {self._period_label(limit.period)}"

        )




    def _render_progress_bar(self, percent: float) -> str:

        filled = min(10, int(round(percent / 10)))

        empty = 10 - filled

        return " [" + "#" * filled + "-" * empty + "]"





    def _period_label(self, period: BudgetPeriod) -> str:

        mapping = {
            BudgetPeriod.DAILY: 'день',
            BudgetPeriod.WEEKLY: 'тиждень',
            BudgetPeriod.MONTHLY: 'місяць',
        }

        return mapping.get(period, 'період')

    def _repair_text(self, value: str | None) -> str:
        return repair_text(value)

    def _category_label(self, value: str | None, default: str = "Без категорії") -> str:
        localized = localize_category_name(value, default=default)
        return self._repair_text(localized)

    async def _send_all_time_summary(self, update: Update) -> None:

        telegram_user = update.effective_user

        chat = update.effective_chat

        if not telegram_user or not chat:
            return

        async with self._session() as session:
            user_service = UserService(session)
            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)
            tx_service = TransactionService(session)
            summary = await tx_service.all_time_summary(user)

        header = "Звіт за весь час"
        await chat.send_message(self._format_summary_text(header, summary, recent_block=None, all_time_summary=summary))

    async def _send_monthly_summary(self, update: Update, month_value: str | None = None) -> None:

        telegram_user = update.effective_user

        chat = update.effective_chat

        if not telegram_user or not chat:

            return

        async with self._session() as session:

            user_service = UserService(session)

            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)

            tz = ZoneInfo(user.timezone or "UTC")

            target_month = self._parse_month_value(month_value) or datetime.now(tz).date()

            start_local, end_local = self._month_local_bounds(tz, target_month)

            tx_service = TransactionService(session)

            summary = await tx_service.monthly_summary(user, target_month)
            all_time = await tx_service.all_time_summary(user)

            recent_transactions = await tx_service.get_recent_transactions(user, limit=5, month=target_month)

            recent_block = self._recent_transactions_block(recent_transactions, tz)



        month_name = MONTH_NAMES[start_local.month].capitalize()

        display_end = (end_local - timedelta(days=1)).strftime(DATE_OUTPUT_FORMAT)

        period = f"{start_local.strftime(DATE_OUTPUT_FORMAT)} - {display_end}"

        header = f"Звіт за {month_name} {start_local.year} ({period})"

        await chat.send_message(self._format_summary_text(header, summary, recent_block, all_time))

    async def _send_custom_report(self, chat, user, target_date: datetime) -> None:


        tz = ZoneInfo(user.timezone or "UTC")


        start_local = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)


        end_local = start_local + timedelta(days=1)


        async with self._session() as session:


            tx_service = TransactionService(session)


            summary = await tx_service.summary_for_period(user, start_local, end_local)
            all_time = await tx_service.all_time_summary(user)


            transactions = await tx_service.transactions_between(


                user,


                start_local.astimezone(timezone.utc).replace(tzinfo=None),


                end_local.astimezone(timezone.utc).replace(tzinfo=None),


            )


            recent_block = self._recent_transactions_block(transactions, tz)


        header = f"Звіт за {start_local.strftime(DATE_OUTPUT_FORMAT)}"

        await chat.send_message(self._format_summary_text(header, summary, recent_block, all_time))
        await chat.send_message(self._format_summary_text(header, summary, recent_block))





    def _format_summary_text(
        self,
        header: str,
        summary: AnalyticsSummary,
        recent_block: str | None = None,
        all_time_summary: AnalyticsSummary | None = None,
    ) -> str:
        text = (
            f"{header}\n"
            f"Дохід: {summary.total_income} {summary.currency}\n"
            f"Витрати: {summary.total_expense} {summary.currency}\n"
            f"Баланс: {summary.net} {summary.currency}\n"
        )
        if all_time_summary:
            text += f"\nВитрати за весь час: {all_time_summary.total_expense} {all_time_summary.currency}\n"
        if summary.top_categories:
            text += "\nТоп категорії:\n"
            for item in summary.top_categories:
                text += f"- {item.category}: {item.total} ({item.direction})\n"
        if recent_block:
            text += f"\nОстанні операції:\n{recent_block}"
        return text




    def _recent_transactions_block(self, transactions: list[Transaction], tz: ZoneInfo) -> str:


        if not transactions:


            return ""


        lines = ["Останні транзакції:"]


        for tx in transactions:


            local_dt = (


                tx.occurred_at.replace(tzinfo=timezone.utc).astimezone(tz)


                if tx.occurred_at


                else None


            )


            date_label = local_dt.strftime("%d.%m") if local_dt else ""


            sign = "-" if tx.direction == TransactionType.EXPENSE else "+"


            category = self._category_label(tx.category.name if tx.category else None)


            desc = self._repair_text(tx.description) if tx.description else ""
            description = f" - {desc}" if desc else ""


            lines.append(f"- {date_label} {sign}{float(tx.amount):.2f} {tx.currency} ({category}){description}")


        return "\n".join(lines)


    async def _send_export(self, update: Update) -> None:


        query = update.callback_query


        telegram_user = update.effective_user


        if not query or not telegram_user:


            return





        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)


            report_service = ReportService(session)


            end = datetime.utcnow()


            start = end - timedelta(days=30)


            path = await report_service.export_csv(user.id, start, end)





        with path.open("rb") as csv_file:


            await query.message.reply_document(


                document=InputFile(csv_file, filename=path.name),


                caption="CSV зі всіма операціями за 30 днів",


            )





    async def _send_chart(self, update: Update, chart_type: str = "category_bar", month_value: str | None = None) -> None:

        query = update.callback_query

        telegram_user = update.effective_user

        if not query or not telegram_user:

            return



        user = await self._ensure_user_model(telegram_user)

        tz = ZoneInfo(user.timezone or "UTC")

        target_month = self._parse_month_value(month_value) or datetime.now(tz).date()

        start_local, end_local = self._month_local_bounds(tz, target_month)



        async with self._session() as session:

            report_service = ReportService(session)

            buffer = await report_service.category_chart(

                user.id,

                start_local.astimezone(timezone.utc).replace(tzinfo=None),

                end_local.astimezone(timezone.utc).replace(tzinfo=None),

                user.currency,

                chart_type,

            )



        if not buffer:

            await query.message.reply_text("Немає достатньо даних, щоб побудувати діаграму за цей період.")

            return



        month_name = MONTH_NAMES[start_local.month].capitalize()

        chart_titles = {

            "category_bar": "Категорії (стовпчики)",

            "category_pie": "Категорії (кругова)",

            "trend_line": "Щоденна динаміка",

        }

        chart_label = chart_titles.get(chart_type, "Діаграма")

        await query.message.reply_photo(

            photo=buffer,

            caption=f"{chart_label} за {month_name} {start_local.year}",

        )

    async def _prompt_category_selection(self, context, chat, user: User, capture_state: dict) -> None:
        await self._clear_category_prompt(context, capture_state)
        capture_state["stage"] = "category"
        capture_state["chat_id"] = chat.id
        choices = await self._category_choices(user.id, capture_state["direction"])
        instruction = "Оберіть категорію або введіть свою."
        message = await chat.send_message(instruction, reply_markup=category_keyboard(choices))
        capture_state["category_prompt_message_id"] = message.message_id

    async def _prompt_chart_type(self, chat, month_value: str) -> None:

        tz = ZoneInfo(self.settings.report_timezone or "UTC")

        month_label = self._format_month_label(self._parse_month_value(month_value) or datetime.now(tz).date())

        await chat.send_message(

            f"Оберіть тип графіка для {month_label}:",

            reply_markup=chart_type_keyboard(month_value),

        )

    async def _prompt_month_selection(self, chat, action: str, user: User) -> None:

        months = await self._month_options(user)

        keyboard = self._month_selection_keyboard(action, months)

        prompt = "Оберіть місяць для звіту:" if action == "report" else "Оберіть місяць для графіка:"

        await chat.send_message(prompt, reply_markup=keyboard)

    async def _clear_category_prompt(self, context, capture_state: dict) -> None:


        if not capture_state:


            return


        message_id = capture_state.pop("category_prompt_message_id", None)


        chat_id = capture_state.get("chat_id")


        if not message_id or not chat_id:


            return


        try:


            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)


        except TelegramError as error:


            logger.debug("Failed to delete category prompt: {}", error)





    async def _ask_entry_date(self, chat, user: User) -> None:


        tz = ZoneInfo(user.timezone or "UTC")


        today = datetime.now(tz).date()


        today_label = today.strftime(DATE_OUTPUT_FORMAT)


        text = f"Яку дату операції фіксуємо? За замовчуванням: {today_label}."


        await chat.send_message(text, reply_markup=entry_date_keyboard(today_label))





    async def _category_choices(self, telegram_user_id: int, direction: TransactionType) -> list[tuple[int, str]]:


        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user_id)


            stmt = (


                select(Category.id, Category.name)


                .where(Category.user_id == user.id)


                .where(


                    Category.type


                    == (CategoryType.EXPENSE if direction == TransactionType.EXPENSE else CategoryType.INCOME)


                )


                .limit(6)


            )


            rows = await session.execute(stmt)


            return [(row[0], self._category_label(row[1])) for row in rows.all()]





    async def _prompt_ai_question(self, chat, context) -> None:


        context.user_data[AI_ASSIST_STATE_KEY] = True


        await chat.send_message("Що б ви хотіли запитати? Напишіть конкретне питання про фінанси.")





    async def _handle_ai_text(self, update: Update, context, text: str) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        if not telegram_user or not chat:


            return





        question = text.strip()


        if not question:


            await chat.send_message("Питання виглядає порожнім. Напишіть текст повідомлення.")


            return





        context.user_data.pop(AI_ASSIST_STATE_KEY, None)





        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)


            tx_service = TransactionService(session)


            reply = await self.ai_advisor.advise(user, question, tx_service)





        await chat.send_message(reply)





    def _month_selection_keyboard(self, action: str, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:

        prefix = "report:month" if action == "report" else "chart:month"

        rows: list[list[InlineKeyboardButton]] = []

        for i in range(0, len(options), 2):

            row = []

            for label, value in options[i : i + 2]:

                row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{value}"))

            rows.append(row)

        if action == "report":
            rows.append([InlineKeyboardButton("Весь час", callback_data="report:alltime")])

        return InlineKeyboardMarkup(rows)

    async def _month_options(self, user: User) -> list[tuple[str, str]]:

        months: list[tuple[str, str]] = []

        async with self._session() as session:

            tx_service = TransactionService(session)

            available = await tx_service.available_months(user)

        if available:

            for value in available:

                parsed = self._parse_month_value(value)

                label = self._format_month_label(parsed) if parsed else value

                months.append((label, value))

            return months

        tz = ZoneInfo(self.settings.report_timezone or "UTC")

        current = datetime.now(tz).date().replace(day=1)

        for _ in range(MONTH_PICKER_MONTHS):

            months.append((self._format_month_label(current), f"{current.year}-{current.month:02d}"))

            current = self._shift_month(current, -1)

        return months


    def _format_month_label(self, month_date: date) -> str:

        name = MONTH_NAMES.get(month_date.month, str(month_date.month)).capitalize()

        return f"{name} {month_date.year}"



    def _shift_month(self, month_date: date, delta: int) -> date:

        year = month_date.year + ((month_date.month - 1 + delta) // 12)

        month = (month_date.month - 1 + delta) % 12 + 1

        return date(year, month, 1)

    async def _show_transaction_history(self, chat, telegram_user, page: int = 0) -> None:
        user = await self._ensure_user_model(telegram_user)
        limit = HISTORY_PAGE_SIZE
        async with self._session() as session:
            tx_service = TransactionService(session)
            transactions = await tx_service.get_recent_transactions(user, limit=limit)

        if not transactions:
            await chat.send_message("Поки що немає операцій.")
            return

        lines = []
        buttons: list[list[InlineKeyboardButton]] = []
        for idx, tx in enumerate(transactions, start=1):
            label = self._history_label(tx)
            lines.append(f"{idx}. {label}")
            buttons.append([InlineKeyboardButton(f"🗑 {idx}", callback_data=f"history:del:{tx.id}")])

        if self.web_app_url and self.web_app_url.startswith("https://"):
            buttons.append(
                [InlineKeyboardButton("Відкрити повну історію в мініапці", web_app=WebAppInfo(url=self.web_app_url))]
            )

        await chat.send_message("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))

    async def _handle_history_delete(self, update: Update, context, payload: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        if not telegram_user or not chat:
            return
        try:
            tx_id = int(payload.split(":", 1)[0])
        except ValueError:
            await update.callback_query.message.reply_text("Некоректний запит.")
            return

        user = await self._ensure_user_model(telegram_user)
        async with self._session() as session:
            tx_service = TransactionService(session)
            deleted = await tx_service.delete_transaction(user, tx_id)
            if deleted:
                await session.commit()
                await chat.send_message("Операцію видалено.")
            else:
                await chat.send_message("Операцію не знайдено.")
        await self._show_transaction_history(chat, telegram_user)

    def _history_label(self, tx: Transaction) -> str:

        sign = "-" if tx.direction == TransactionType.EXPENSE else "+"

        amount = f"{sign}{float(tx.amount):.2f} {tx.currency}"

        category = self._category_label(tx.category.name if tx.category else None)

        date_label = tx.occurred_at.strftime("%d.%m") if tx.occurred_at else ""

        label = f"{date_label} · {amount} ({category})"

        return self._repair_text(label)

    async def _resolve_category(


        self,


        session,


        user_id: int,


        name: str,


        direction: TransactionType,


    ) -> int | None:


        stmt = (


            select(Category.id)


            .where(Category.user_id == user_id)


            .where(func.lower(Category.name) == name.lower())


            .where(


                Category.type


                == (CategoryType.EXPENSE if direction == TransactionType.EXPENSE else CategoryType.INCOME)


            )


        )


        return await session.scalar(stmt)





    async def _ensure_category(


        self,


        session,


        user: User,


        name: str,


        direction: TransactionType,


    ) -> int:


        existing = await self._resolve_category(session, user.id, name, direction)


        if existing:


            return existing


        category = Category(


            user_id=user.id,


            name=name.strip().title(),


            emoji=None,


            type=CategoryType.EXPENSE if direction == TransactionType.EXPENSE else CategoryType.INCOME,


            is_default=False,


        )


        session.add(category)


        await session.flush()


        return category.id





    async def _select_category(self, update: Update, context, value: str) -> None:
        telegram_user = update.effective_user
        chat = update.effective_chat
        if not telegram_user or not chat:
            return

        receipt_state = context.user_data.get(RECEIPT_STATE_KEY)
        receipt_edit = context.user_data.get(RECEIPT_EDIT_STATE_KEY)
        if receipt_state and receipt_edit in {"category", "category_manual"}:
            if value == "manual":
                context.user_data[RECEIPT_EDIT_STATE_KEY] = "category_manual"
                await update.callback_query.message.reply_text("Введіть назву категорії вручну.")
                return
            try:
                receipt_state["category_id"] = int(value)
            except ValueError:
                logger.warning("Unknown category id from callback: {}", value)
                return
            context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)
            user = await self._ensure_user_model(telegram_user)
            await self._send_receipt_preview(chat, user, receipt_state)
            return

        capture_state = context.user_data.get(CAPTURE_STATE_KEY)
        if not capture_state:
            await update.callback_query.message.reply_text("Немає активного запису. Почніть з додавання.")
            return

        if value == "manual":
            await self._clear_category_prompt(context, capture_state)
            capture_state["stage"] = "category_manual"
            await update.callback_query.message.reply_text("Введіть назву категорії вручну.")
            return

        try:
            capture_state["category_id"] = int(value)
        except ValueError:
            logger.warning("Unknown category id from callback: {}", value)
            return

        await self._clear_category_prompt(context, capture_state)
        capture_state["stage"] = "confirm"
        user = await self._ensure_user_model(telegram_user)
        await self._send_quick_preview(chat, user, capture_state)

    async def handle_receipt_photo(self, update: Update, context) -> None:

        telegram_user = update.effective_user

        chat = update.effective_chat

        message = update.message

        if not telegram_user or not chat or not message or not message.photo:

            return



        if not self.receipt_parser.enabled:

            await chat.send_message("Розпізнавання чеків вимкнене: додайте OPENAI_API_KEY у налаштуваннях.")

            return



        if not self._check_receipt_quota(telegram_user.id):

            await chat.send_message("Обмеження — до 3 чеків на день. Спробуйте пізніше.")

            return



        photo = message.photo[-1]

        file = await photo.get_file()

        buffer = BytesIO()

        await file.download_to_memory(buffer)



        try:

            data = await self.receipt_parser.parse(buffer.getvalue())

        except RuntimeError as exc:

            await chat.send_message(str(exc))

            return



        if not data.amount:

            await chat.send_message("AI не знайшов суму на фото. Спробуйте інший кадр або введіть дані вручну.")

            return

        user = await self._ensure_user_model(telegram_user)



        context.user_data[RECEIPT_STATE_KEY] = {

            "amount": str(data.amount),

            "description": data.description,

            "category_hint": data.category_hint,

            "merchant": data.merchant,

            "currency": data.currency,

            "date": data.occurred_at.strftime("%Y-%m-%d") if data.occurred_at else None,
            "category_id": None,

        }
        context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)
        await self._send_receipt_preview(chat, user, context.user_data[RECEIPT_STATE_KEY])




    async def _handle_receipt_confirmation(self, update: Update, context) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        draft = context.user_data.get(RECEIPT_STATE_KEY)


        if not telegram_user or not chat:


            return


        if not draft:


            await update.callback_query.message.reply_text("Немає активного чеку для підтвердження. Завантажте фото знову.")


            return





        try:


            amount = Decimal(draft["amount"])


        except (InvalidOperation, TypeError):


            await chat.send_message("Не вдалося прочитати суму з чеку. Спробуйте ще раз або внесіть дані вручну.")


            context.user_data.pop(RECEIPT_STATE_KEY, None)


            return





        description = draft.get("description") or "без опису"
        currency_hint = draft.get("currency")
        category_hint = draft.get("category_hint")
        category_id = draft.get("category_id")
        date_str = draft.get("date")




        async with self._session() as session:


            user_service = UserService(session)


            user = await user_service.ensure_user(telegram_user.id, telegram_user.username)


            transaction_service = TransactionService(session)





            if not category_id and category_hint:
                category_id = await self._resolve_category(session, user.id, category_hint, TransactionType.EXPENSE)
                if not category_id:
                    category_id = await self._ensure_category(session, user, category_hint, TransactionType.EXPENSE)





            occurred_at = self._resolve_receipt_occurred_at(user, date_str)
            tags = ["manual"]
            if is_subscription(description, category_hint):
                tags.append("subscription")


            transaction = await transaction_service.add_transaction(

                user,

                TransactionCreate(

                    amount=amount,

                    currency=currency_hint or user.currency,

                    direction=TransactionType.EXPENSE,

                    category_id=category_id,

                    description=description,

                    tags=tags,


                    occurred_at=occurred_at,


                ),


            )


            await session.commit()


            await session.refresh(transaction, attribute_names=["category"])


            user_id = user.id





        context.user_data.pop(RECEIPT_STATE_KEY, None)
        context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)


        label = self._category_label(transaction.category.name if transaction.category else None)


        await chat.send_message(


            f"Запис із чека додано: {float(transaction.amount):.2f} {transaction.currency} ({label}). Дякую за чек!"


        )


        await self._notify_budget_alerts(user_id, transaction.category_id, chat)





    async def _handle_receipt_cancel(self, update: Update, context) -> None:


        chat = update.effective_chat


        context.user_data.pop(RECEIPT_STATE_KEY, None)
        context.user_data.pop(RECEIPT_EDIT_STATE_KEY, None)


        if chat and update.callback_query:


            await update.callback_query.message.reply_text("Скасовано, можна спробувати ще раз будь-коли.")





    def _parse_message(self, text: str) -> tuple[Decimal, str, str | None]:


        parts = text.replace(",", ".").split()


        amount = Decimal(parts[0])


        category_name = parts[1] if len(parts) > 1 else None


        description = " ".join(parts[2:]) if len(parts) > 2 else category_name or "—"


        return amount, description, category_name





    async def _handle_settings_callback(self, update: Update, context, data: str) -> None:

        query = update.callback_query

        telegram_user = update.effective_user

        chat = query.message.chat if (query.message) else update.effective_chat

        if not chat or not telegram_user:

            return

        parts = data.split(":")

        if len(parts) == 2 and parts[1] == "menu":

            user = await self._ensure_user_model(telegram_user)

            await self._send_settings_menu(chat, user, source_message=query.message)

            return

        if len(parts) == 2 and parts[1] == "close":

            if query.message:

                await query.message.edit_text("Налаштування закрито.")

            return

        if len(parts) < 3:

            return

        field = parts[1]

        value = parts[2]

        payload = {}

        if field == "language":

            payload["language"] = value

        elif field == "currency":

            payload["currency"] = value

        elif field == "theme":

            payload["theme"] = value

        else:

            return

        user = await self._update_user_preferences(telegram_user, **payload)

        await self._send_settings_menu(chat, user, source_message=query.message)


    async def _send_settings_menu(self, chat, user: User, source_message=None) -> None:

        language = user.language or self.settings.default_language or "uk"

        currency = user.currency or self.settings.default_currency

        theme = user.theme or self.settings.default_theme or "dark"

        text = self._format_settings_message(user)

        keyboard = settings_keyboard(language, currency, theme)

        if source_message:

            try:

                await source_message.edit_text(text, reply_markup=keyboard)

                return

            except TelegramError:

                pass

        await chat.send_message(text, reply_markup=keyboard)


    def _format_settings_message(self, user: User) -> str:
        language_label = "English" if (user.language or "uk") == "en" else "Українська"
        currency = user.currency or self.settings.default_currency
        timezone_label = user.timezone or "UTC"
        return (
            "Налаштування користувача:\n"
            f"- Мова: {language_label}\n"
            f"- Валюта: {currency}\n"
            f"- Часовий пояс: {timezone_label}\n"
            "\nЗміни застосуються після натискання кнопки."
        )

    async def _update_user_preferences(self, telegram_user, **payload) -> User:

        async with self._session() as session:

            service = UserService(session)

            user = await service.ensure_user(telegram_user.id, telegram_user.username)

            await service.update_preferences(user, **payload)

            await session.commit()

            await session.refresh(user)

            return user


    async def _handle_timezone_callback(self, update: Update, context, value: str) -> None:


        query = update.callback_query


        chat = update.effective_chat


        telegram_user = update.effective_user


        if not chat or not telegram_user:


            return





        if value == "menu":


            await query.message.reply_text("Оберіть часовий пояс зі списку:", reply_markup=timezone_keyboard())


            return


        if value == "manual":


            context.user_data[TIMEZONE_STATE_KEY] = True


            await query.message.reply_text("Не впізнав часовий пояс. Приклад правильного значення: Europe/Kyiv.")


            return


        await self._apply_timezone(chat, context, telegram_user, value)





    async def _handle_timezone_text(self, update: Update, context, text: str) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        if not telegram_user or not chat:


            return


        await self._apply_timezone(chat, context, telegram_user, text.strip())





    async def _handle_report_date_text(self, update: Update, context, text: str) -> None:


        telegram_user = update.effective_user


        chat = update.effective_chat


        if not telegram_user or not chat:


            return





        try:


            parsed = datetime.strptime(text.strip(), DATE_INPUT_FORMAT)


        except ValueError:


            await chat.send_message("Не вдалося розпізнати дату. Формат: рік-місяць-день.")


            return





        user = await self._ensure_user_model(telegram_user)


        await self._send_custom_report(chat, user, parsed)


        context.user_data.pop(REPORT_DATE_STATE_KEY, None)





    async def _apply_timezone(self, chat, context, telegram_user, tz_name: str) -> None:


        if not self._is_timezone_valid(tz_name):


            await chat.send_message("Не вдалося розпізнати часовий пояс. Приклад: Europe/Kyiv")


            return





        async with self._session() as session:


            service = UserService(session)


            user = await service.ensure_user(telegram_user.id, telegram_user.username)


            await service.update_timezone(user, tz_name)


            await service.mark_onboarding_completed(user)


            await session.commit()





        context.user_data.pop(TIMEZONE_STATE_KEY, None)


        await chat.send_message(f"Часовий пояс оновлено на: {tz_name}")





    async def _prompt_timezone_selection(self, chat, current: str | None = None) -> None:


        current_label = f" (поточний: {current})" if current else ""


        await chat.send_message(


            f"Оберіть часовий пояс{current_label}:",


            reply_markup=timezone_keyboard(),


        )





    async def _request_report_date(self, chat, context) -> None:


        context.user_data[REPORT_DATE_STATE_KEY] = True


        await chat.send_message("Введіть дату звіту у форматі рік-місяць-день, наприклад 2025-11-18.")





    def _is_timezone_valid(self, tz_name: str) -> bool:


        try:


            ZoneInfo(tz_name)


        except Exception:


            return False


        return True





    async def _ensure_user_model(self, telegram_user) -> User:


        async with self._session() as session:


            service = UserService(session)


            user = await service.ensure_user(telegram_user.id, telegram_user.username)


            await session.commit()


            return user





    def _parse_month_value(self, value: str | None) -> date | None:

        if not value:

            return None

        try:

            parsed = datetime.strptime(value, "%Y-%m")

        except ValueError:

            return None

        return date(parsed.year, parsed.month, 1)



    def _month_local_bounds(self, tz: ZoneInfo, month_date: date) -> tuple[datetime, datetime]:

        start_local = datetime(month_date.year, month_date.month, 1, tzinfo=tz)

        if month_date.month == 12:

            end_local = datetime(month_date.year + 1, 1, 1, tzinfo=tz)

        else:

            end_local = datetime(month_date.year, month_date.month + 1, 1, tzinfo=tz)

        return start_local, end_local

    def _resolve_occurred_at(self, user: User, entry_date: date | None) -> datetime:


        tz = ZoneInfo(user.timezone or "UTC")


        if entry_date:


            local_dt = datetime.combine(entry_date, datetime.now(tz).time(), tzinfo=tz)


        else:


            local_dt = datetime.now(tz)


        return local_dt.astimezone(timezone.utc).replace(tzinfo=None)





    def _resolve_receipt_occurred_at(self, user: User, date_str: str | None) -> datetime | None:


        if not date_str:


            return None


        try:


            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()


        except ValueError:


            return None


        return self._resolve_occurred_at(user, parsed_date)





    async def _notify_budget_alerts(self, user_id: int, category_id: int | None, chat) -> None:


        if not category_id:


            return





        async with self._session() as session:


            service = BudgetService(session)





            async def _callback(limit, spent, total):


                await self._send_budget_alert(chat, limit, spent, total)





            await service.check_limits_for_category(user_id, category_id, _callback)





    async def _send_budget_alert(self, chat, limit, spent: Decimal, total: Decimal) -> None:


        category = self._category_label(limit.category.name if limit.category else None)


        percent = float(spent / total * Decimal("100")) if total else 0.0


        await chat.send_message(

            f"?? Ліміт {category} використано на {percent:.0f}% ({float(spent):.2f}/{float(total):.2f})."

        )



    def _check_receipt_quota(self, telegram_id: int) -> bool:

        today = datetime.utcnow().date()

        entries = [ts for ts in self.receipt_usage[telegram_id] if ts.date() == today]

        if len(entries) >= 3:

            self.receipt_usage[telegram_id] = entries

            return False

        entries.append(datetime.utcnow())

        self.receipt_usage[telegram_id] = entries

        return True















