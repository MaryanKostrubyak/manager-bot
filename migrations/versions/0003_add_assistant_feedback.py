"""Add assistant feedback table

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("tone", sa.String(length=16), nullable=True),
        sa.Column("rating", sa.String(length=16), nullable=False, server_default="wrong"),
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_feedback_user_id", "assistant_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_feedback_user_id", table_name="assistant_feedback")
    op.drop_table("assistant_feedback")
