from decimal import Decimal

from app.core.config import Settings
from app.telegram.bot import TelegramBot


def test_parse_message_extracts_category_and_description():
    bot = TelegramBot(Settings(telegram_bot_token="test"))
    amount, description, category = bot._parse_message("120 кафе обід з друзями")
    assert amount == Decimal("120")
    assert category == "кафе"
    assert description == "обід з друзями"


def test_parse_message_handles_only_amount():
    bot = TelegramBot(Settings(telegram_bot_token="test"))
    amount, description, category = bot._parse_message("99")
    assert amount == Decimal("99")
    assert category is None
    assert description == "—"
