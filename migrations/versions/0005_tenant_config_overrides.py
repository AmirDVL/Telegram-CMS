"""Per-tenant config override columns on tenants table.

Adds six nullable columns to ``tenants`` (NULL = fall back to the global
``Settings`` value).  When ``MULTI_TENANCY_ENABLED=false`` (the default) these
columns exist but are never read, so single-tenant behaviour is unchanged.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-29 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All columns are nullable — NULL means "use the global setting".
    op.add_column("tenants", sa.Column("ai_model", sa.String(128), nullable=True))
    op.add_column("tenants", sa.Column("ai_max_tokens", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("ai_timeout_seconds", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("dedupe_lookback_days", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("publish_spacing_seconds", sa.Float(), nullable=True))
    op.add_column("tenants", sa.Column("media_max_size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "media_max_size_bytes")
    op.drop_column("tenants", "publish_spacing_seconds")
    op.drop_column("tenants", "dedupe_lookback_days")
    op.drop_column("tenants", "ai_timeout_seconds")
    op.drop_column("tenants", "ai_max_tokens")
    op.drop_column("tenants", "ai_model")
