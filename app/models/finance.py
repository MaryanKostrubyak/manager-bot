from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TransactionType(str, enum.Enum):
    EXPENSE = "expense"
    INCOME = "income"


class BudgetPeriod(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Kyiv")
    language: Mapped[str] = mapped_column(String(8), default="uk")
    theme: Mapped[str] = mapped_column(String(16), default="dark")
    onboarding_completed: Mapped[bool] = mapped_column(default=False)

    wallets: Mapped[list["Wallet"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Wallet(TimestampMixin, Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    is_default: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User] = relationship(back_populates="wallets")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="wallet")


class CategoryType(str, enum.Enum):
    EXPENSE = "expense"
    INCOME = "income"


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str | None] = mapped_column(String(8))
    type: Mapped[CategoryType] = mapped_column(Enum(CategoryType), default=CategoryType.EXPENSE)
    is_default: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User | None] = relationship(back_populates="categories")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    limits: Mapped[list["BudgetLimit"]] = relationship(back_populates="category")


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    direction: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    description: Mapped[str | None] = mapped_column(Text())
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    occurred_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    wallet: Mapped[Wallet] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(back_populates="transactions")


class BudgetLimit(TimestampMixin, Base):
    __tablename__ = "budget_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    period: Mapped[BudgetPeriod] = mapped_column(Enum(BudgetPeriod))
    alert_threshold: Mapped[float] = mapped_column(default=0.9)
    is_active: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User] = relationship()
    category: Mapped[Category] = relationship(back_populates="limits")


class ReportSnapshot(TimestampMixin, Base):
    __tablename__ = "report_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class AssistantFeedback(TimestampMixin, Base):
    __tablename__ = "assistant_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text())
    answer: Mapped[str] = mapped_column(Text())
    tone: Mapped[str | None] = mapped_column(String(16))
    rating: Mapped[str] = mapped_column(String(16), default="wrong")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
