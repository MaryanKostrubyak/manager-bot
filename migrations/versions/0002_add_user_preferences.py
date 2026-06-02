"""Add language and theme columns to users

Revision ID: 0002
Revises: 0001
Create Date: 2025-12-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=8), nullable=False, server_default="uk"),
    )
    op.add_column(
        "users",
        sa.Column("theme", sa.String(length=16), nullable=False, server_default="dark"),
    )
    op.execute("UPDATE users SET language = COALESCE(language, 'uk')")
    op.execute("UPDATE users SET theme = COALESCE(theme, 'dark')")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column("users", "language", server_default=None)
        op.alter_column("users", "theme", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "theme")
    op.drop_column("users", "language")
