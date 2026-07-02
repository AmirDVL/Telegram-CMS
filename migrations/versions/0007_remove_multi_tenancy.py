"""Remove multi-tenancy: drop tenants table + tenant_id columns.

Reverses the multi-tenancy schema (0004) and collapses the per-tenant dedupe
constraint (0006) back to a plain ``UNIQUE (dedupe_hash)``.

Because ``MULTI_TENANCY_ENABLED`` was always false, every ``tenant_id`` is NULL
and ``UNIQUE NULLS NOT DISTINCT (tenant_id, dedupe_hash)`` already behaves as a
global unique on ``dedupe_hash`` — so collapsing to ``UNIQUE (dedupe_hash)`` is
data-safe (no duplicate hashes can exist).

The ``ai_mode`` enum is left in place: ``source_channels`` still uses it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-01 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that carried a tenant_id FK + index (0004), in FK-safe drop order.
_TENANT_TABLES = ("post_events", "posts", "source_channels", "templates", "tags", "admins")


def upgrade() -> None:
    # ── published_dedupe: swap composite unique → plain unique(dedupe_hash) ──
    # Drop the constraint before the column it references. The standalone
    # ix_published_dedupe_tenant_id was already removed by 0006.
    op.execute("ALTER TABLE published_dedupe DROP CONSTRAINT uq_published_dedupe_tenant_hash")
    op.drop_constraint("fk_published_dedupe_tenant_id", "published_dedupe", type_="foreignkey")
    op.drop_column("published_dedupe", "tenant_id")
    op.create_unique_constraint("uq_published_dedupe_hash", "published_dedupe", ["dedupe_hash"])

    # ── Drop tenant_id from every other table (index + FK + column) ──────────
    for table in _TENANT_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    # ── Drop the tenants table (its 0005 override columns go with it) ────────
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")


def downgrade() -> None:
    # Reference the still-existing ai_mode enum without recreating it.
    ai_mode_enum = postgresql.ENUM(
        "off", "translate", "summarize", "retone", "custom",
        name="ai_mode",
        create_type=False,
    )

    # ── Recreate the tenants table (0004 shape + 0005 override columns) ──────
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("bot_token", sa.String(255), nullable=True),
        sa.Column("destination_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("editor_group_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_mode", ai_mode_enum, server_default="off", nullable=False),
        sa.Column("ai_target_language", sa.String(16), nullable=True),
        sa.Column("ai_tone_prompt", sa.Text(), nullable=True),
        sa.Column("ai_custom_system_prompt", sa.Text(), nullable=True),
        sa.Column("watermark_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("watermark_text", sa.Text(), nullable=True),
        sa.Column("strip_source_tags", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_model", sa.String(128), nullable=True),
        sa.Column("ai_max_tokens", sa.Integer(), nullable=True),
        sa.Column("ai_timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("dedupe_lookback_days", sa.Integer(), nullable=True),
        sa.Column("publish_spacing_seconds", sa.Float(), nullable=True),
        sa.Column("media_max_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # ── Re-add tenant_id (column + FK + index) to every table ───────────────
    for table in reversed(_TENANT_TABLES):
        op.add_column(table, sa.Column("tenant_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(f"fk_{table}_tenant_id", table, "tenants", ["tenant_id"], ["id"])
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # ── published_dedupe: restore composite UNIQUE NULLS NOT DISTINCT ────────
    # Mirrors the post-0006 state: tenant_id column + FK (no standalone index),
    # composite unique constraint.
    op.drop_constraint("uq_published_dedupe_hash", "published_dedupe", type_="unique")
    op.add_column("published_dedupe", sa.Column("tenant_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_published_dedupe_tenant_id", "published_dedupe", "tenants", ["tenant_id"], ["id"]
    )
    op.execute(
        """
        ALTER TABLE published_dedupe
        ADD CONSTRAINT uq_published_dedupe_tenant_hash
        UNIQUE NULLS NOT DISTINCT (tenant_id, dedupe_hash)
        """
    )
