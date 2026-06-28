"""Add tg_user_id to admins for bot callback authorization.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_unique_constraint("uq_admins_tg_user_id", "admins", ["tg_user_id"])
    op.create_index("ix_admins_tg_user_id", "admins", ["tg_user_id"])


def downgrade() -> None:
    op.drop_index("ix_admins_tg_user_id", table_name="admins")
    op.drop_constraint("uq_admins_tg_user_id", "admins", type_="unique")
    op.drop_column("admins", "tg_user_id")
