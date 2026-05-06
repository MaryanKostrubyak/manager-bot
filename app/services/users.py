from __future__ import annotations

from typing import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import BudgetLimit, Category, Transaction, User, Wallet
from app.utils.categories import DEFAULT_CATEGORIES, localize_category_name

settings = get_settings()

def _category_exists(names: Iterable[str], target: str) -> bool:
    return any(name.lower() == target.lower() for name in names)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _normalize_currency(self, currency: str | None) -> str | None:
        if not currency:
            return None
        normalized = currency.upper()
        allowed = {value.upper(): value for value in settings.supported_currencies}
        return allowed.get(normalized)

    def _normalize_language(self, language: str | None) -> str | None:
        if not language:
            return None
        normalized = language.lower()
        allowed = {value.lower(): value for value in settings.supported_languages}
        return allowed.get(normalized)

    def _normalize_theme(self, theme: str | None) -> str | None:
        if not theme:
            return None
        normalized = theme.lower()
        allowed = {value.lower(): value for value in settings.supported_themes}
        return allowed.get(normalized)

    async def get_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return await self.session.scalar(stmt)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self.session.scalar(stmt)

    async def ensure_user(self, telegram_id: int, username: str | None = None) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            if username and user.username != username:
                user.username = username
            await self._ensure_default_wallet(user)
            await self._ensure_default_categories(user)
            return user

        user = User(
            telegram_id=telegram_id,
            username=username,
            currency=settings.default_currency,
            language=settings.default_language,
            theme=settings.default_theme,
        )
        self.session.add(user)
        await self.session.flush()

        await self._ensure_default_wallet(user)
        await self._ensure_default_categories(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def _ensure_default_wallet(self, user: User) -> Wallet:
        stmt = select(Wallet).where(Wallet.user_id == user.id, Wallet.is_default.is_(True))
        wallet = await self.session.scalar(stmt)
        if wallet:
            return wallet

        wallet = Wallet(
            user_id=user.id,
            name="Основний",
            currency=user.currency,
            is_default=True,
        )
        self.session.add(wallet)
        await self.session.flush()
        return wallet

    async def _ensure_default_categories(self, user: User) -> None:
        stmt = select(Category).where(Category.user_id == user.id)
        result = await self.session.scalars(stmt)
        categories = await self._normalize_categories(user, list(result))
        existing = [category.name for category in categories]

        for name, cat_type, emoji in DEFAULT_CATEGORIES:
            if _category_exists(existing, name):
                continue
            self.session.add(
                Category(
                    user_id=user.id,
                    name=name,
                    type=cat_type,
                    emoji=emoji,
                    is_default=True,
                )
            )
        await self.session.flush()

    async def update_timezone(self, user: User, timezone: str) -> User:
        user.timezone = timezone
        await self.session.flush()
        return user

    async def update_preferences(
        self,
        user: User,
        *,
        currency: str | None = None,
        language: str | None = None,
        theme: str | None = None,
    ) -> User:
        updated = False

        normalized_currency = self._normalize_currency(currency)
        if normalized_currency and normalized_currency != user.currency:
            user.currency = normalized_currency
            updated = True

        normalized_language = self._normalize_language(language)
        if normalized_language and normalized_language != user.language:
            user.language = normalized_language
            updated = True

        normalized_theme = self._normalize_theme(theme)
        if normalized_theme and normalized_theme != user.theme:
            user.theme = normalized_theme
            updated = True

        if updated:
            await self.session.flush()
        return user

    async def mark_onboarding_completed(self, user: User) -> User:
        if not user.onboarding_completed:
            user.onboarding_completed = True
            await self.session.flush()
        return user

    async def _normalize_categories(self, user: User, categories: list[Category]) -> list[Category]:
        if not categories:
            return categories

        original_names = {category.id: (category.name or "") for category in categories}
        replacements: dict[int, int] = {}
        best_by_name: dict[str, Category] = {}
        default_names = {name for name, _, _ in DEFAULT_CATEGORIES}

        for category in categories:
            canonical = localize_category_name(original_names[category.id])
            if not canonical:
                continue

            preferred = best_by_name.get(canonical)
            if preferred:
                winner = self._prefer_category(preferred, category, canonical, original_names)
                loser = category if winner is preferred else preferred
                best_by_name[canonical] = winner
                replacements[loser.id] = winner.id
            else:
                best_by_name[canonical] = category

            if category.name != canonical:
                category.name = canonical
            if canonical in default_names:
                category.is_default = True

        if replacements:
            for source_id, target_id in replacements.items():
                await self._reassign_category_relations(source_id, target_id)
            await self.session.execute(delete(Category).where(Category.id.in_(replacements.keys())))
        await self.session.flush()

        stmt = select(Category).where(Category.user_id == user.id)
        result = await self.session.scalars(stmt)
        return list(result)

    @staticmethod
    def _prefer_category(
        current: Category,
        challenger: Category,
        canonical: str,
        original_names: dict[int, str],
    ) -> Category:
        def _score(category: Category) -> tuple[int, int]:
            score = 0
            if original_names.get(category.id, "").strip().lower() == canonical.lower():
                score += 2
            if category.name.strip().lower() == canonical.lower():
                score += 1
            if category.is_default:
                score += 1
            return score, -category.id

        return max((current, challenger), key=_score)

    async def _reassign_category_relations(self, source_id: int, target_id: int) -> None:
        await self.session.execute(
            update(Transaction).where(Transaction.category_id == source_id).values(category_id=target_id)
        )
        await self.session.execute(
            update(BudgetLimit).where(BudgetLimit.category_id == source_id).values(category_id=target_id)
        )


