from __future__ import annotations

"""Inline keyboard factories for the Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def main_menu_keyboard(web_app_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("➖ Витрата", callback_data="add:expense"),
            InlineKeyboardButton("➕ Дохід", callback_data="add:income"),
        ],
        [
            InlineKeyboardButton("🧾 Чек", callback_data="receipt:help"),
            InlineKeyboardButton("🕓 Останні", callback_data="history:menu"),
        ],
        [
            InlineKeyboardButton("⚙️ Налаштування", callback_data="settings:menu"),
        ],
    ]
    if web_app_url and web_app_url.startswith("https://"):
        rows.append([InlineKeyboardButton("🌐 Відкрити мініапку", web_app=WebAppInfo(url=web_app_url))])
    return InlineKeyboardMarkup(rows)


def settings_keyboard(language: str, currency: str, theme: str) -> InlineKeyboardMarkup:
    def _format(label: str, active: bool) -> str:
        return f"{'[x] ' if active else ''}{label}"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_format("🇺🇦 Українська", language == "uk"), callback_data="settings:language:uk"),
                InlineKeyboardButton(_format("🇬🇧 English", language == "en"), callback_data="settings:language:en"),
            ],
            [
                InlineKeyboardButton(_format("₴ UAH", currency == "UAH"), callback_data="settings:currency:UAH"),
                InlineKeyboardButton(_format("$ USD", currency == "USD"), callback_data="settings:currency:USD"),
            ],
            [
                InlineKeyboardButton("🌍 Часовий пояс", callback_data="timezone:menu"),
            ],
            [
                InlineKeyboardButton("⬇️ CSV (30 днів)", callback_data="export:month"),
                InlineKeyboardButton("↩️ Закрити", callback_data="settings:close"),
            ],
        ]
    )


def category_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(title, callback_data=f"category:{category_id}") for category_id, title in items]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("✍️ Ввести вручну", callback_data="category:manual")])
    return InlineKeyboardMarkup(rows)


def timezone_keyboard() -> InlineKeyboardMarkup:
    options = [
        ("Europe/Kyiv", "🇺🇦 Європа / Київ"),
        ("Europe/Warsaw", "🇵🇱 Європа / Варшава"),
        ("Europe/Berlin", "🇩🇪 Європа / Берлін"),
        ("Europe/London", "🇬🇧 Європа / Лондон"),
        ("America/New_York", "🇺🇸 Америка / Нью-Йорк"),
        ("Asia/Dubai", "🇦🇪 Азія / Дубай"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"timezone:{value}")] for value, label in options]
    rows.append([InlineKeyboardButton("✍️ Вказати вручну", callback_data="timezone:manual")])
    return InlineKeyboardMarkup(rows)


def entry_date_keyboard(current_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"📌 Сьогодні ({current_label})", callback_data="date:today"),
                InlineKeyboardButton("📅 Учора", callback_data="date:yesterday"),
            ],
            [InlineKeyboardButton("✍️ Ввести дату", callback_data="date:manual")],
        ]
    )


def chart_type_keyboard(month_value: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Категорії (стовпчики)", callback_data=f"chart:type:{month_value}:category_bar")],
            [InlineKeyboardButton("🍩 Категорії (діаграма)", callback_data=f"chart:type:{month_value}:category_pie")],
            [InlineKeyboardButton("📈 Динаміка (лінія)", callback_data=f"chart:type:{month_value}:trend_line")],
        ]
    )


def budget_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🆕 Створити ліміт", callback_data="budget:create")],
            [InlineKeyboardButton("🔁 Оновити дані", callback_data="budget:refresh")],
        ]
    )


def budget_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📅 Щодня", callback_data="budget:period:daily"),
                InlineKeyboardButton("🗓️ Щотижня", callback_data="budget:period:weekly"),
            ],
            [InlineKeyboardButton("📆 Щомісяця", callback_data="budget:period:monthly")],
        ]
    )


def receipt_confirmation_keyboard(web_app_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("✅ Додати", callback_data="receipt:confirm"),
            InlineKeyboardButton("🗑 Скасувати", callback_data="receipt:cancel"),
        ],
        [
            InlineKeyboardButton("✏️ Сума", callback_data="receipt:amount"),
            InlineKeyboardButton("✏️ Категорія", callback_data="receipt:category"),
        ],
    ]
    if web_app_url and web_app_url.startswith("https://"):
        rows.append([InlineKeyboardButton("🌐 Відкрити мініапку", web_app=WebAppInfo(url=web_app_url))])
    return InlineKeyboardMarkup(rows)


def quick_confirm_keyboard(web_app_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("✅ Підтвердити", callback_data="quick:confirm"),
            InlineKeyboardButton("🗑 Скасувати", callback_data="quick:cancel"),
        ],
        [
            InlineKeyboardButton("✏️ Категорія", callback_data="quick:category"),
            InlineKeyboardButton("📅 Дата", callback_data="quick:date"),
        ],
    ]
    if web_app_url and web_app_url.startswith("https://"):
        rows.append([InlineKeyboardButton("🌐 Відкрити мініапку", web_app=WebAppInfo(url=web_app_url))])
    return InlineKeyboardMarkup(rows)
