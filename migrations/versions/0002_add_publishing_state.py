"""Add 'publishing' to poststate enum.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12+ supports ADD VALUE inside a transaction.
    # IF NOT EXISTS avoids errors when re-running after a failed migration.
    op.execute("ALTER TYPE poststate ADD VALUE IF NOT EXISTS 'publishing'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without a full type rebuild.
    # Operators who need to roll back should ensure no rows use 'publishing' first,
    # then recreate the type manually.
    pass
