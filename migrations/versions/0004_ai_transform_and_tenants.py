"""AI transformation layer + multi-tenancy schema

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-28 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── New enum: ai_mode ────────────────────────────────────────────────
    # Use raw SQL to create the type first, then reference it via
    # postgresql.ENUM(create_type=False) in column definitions so alembic
    # does not try to issue a second CREATE TYPE during table/column creation.
    op.execute("CREATE TYPE ai_mode AS ENUM ('off', 'translate', 'summarize', 'retone', 'custom')")
    # postgresql.ENUM with create_type=False is respected by op.create_table
    # and op.add_column — it tells SQLAlchemy to assume the type already exists.
    ai_mode_enum = postgresql.ENUM(
        "off", "translate", "summarize", "retone", "custom",
        name="ai_mode",
        create_type=False,
    )

    # ── Extend event_action enum with new values ─────────────────────────
    # PostgreSQL enums can be extended with ALTER TYPE ... ADD VALUE.
    op.execute("ALTER TYPE event_action ADD VALUE IF NOT EXISTS 'ai_transformed'")
    op.execute("ALTER TYPE event_action ADD VALUE IF NOT EXISTS 'ai_failed'")

    # ── tenants table ────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("bot_token", sa.String(255), nullable=True),
        sa.Column("destination_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("editor_group_id", sa.BigInteger(), nullable=True),
        # AI settings
        sa.Column("ai_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_mode", ai_mode_enum, server_default="off", nullable=False),
        sa.Column("ai_target_language", sa.String(16), nullable=True),
        sa.Column("ai_tone_prompt", sa.Text(), nullable=True),
        sa.Column("ai_custom_system_prompt", sa.Text(), nullable=True),
        # Watermark/branding
        sa.Column("watermark_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("watermark_text", sa.Text(), nullable=True),
        sa.Column("strip_source_tags", sa.Boolean(), server_default="false", nullable=False),
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

    # ── tenant_id foreign key on all existing tables ─────────────────────
    for table in ("admins", "tags", "templates", "source_channels", "posts", "post_events"):
        op.add_column(table, sa.Column("tenant_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # published_dedupe uses a composite primary key, so tenant_id is just a column.
    op.add_column("published_dedupe", sa.Column("tenant_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_published_dedupe_tenant_id",
        "published_dedupe",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_index("ix_published_dedupe_tenant_id", "published_dedupe", ["tenant_id"])

    # ── AI columns on source_channels ────────────────────────────────────
    op.add_column(
        "source_channels",
        sa.Column("ai_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "source_channels",
        sa.Column("ai_mode", ai_mode_enum, server_default="off", nullable=False),
    )
    op.add_column(
        "source_channels",
        sa.Column("ai_target_language", sa.String(16), nullable=True),
    )
    op.add_column(
        "source_channels",
        sa.Column("ai_tone_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_channels",
        sa.Column("ai_custom_system_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_channels",
        sa.Column("watermark_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "source_channels",
        sa.Column("watermark_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_channels",
        sa.Column("strip_source_tags", sa.Boolean(), server_default="false", nullable=False),
    )

    # ── AI column on posts ───────────────────────────────────────────────
    op.add_column("posts", sa.Column("ai_transformed_text", sa.Text(), nullable=True))


def downgrade() -> None:
    # ── posts ────────────────────────────────────────────────────────────
    op.drop_column("posts", "ai_transformed_text")

    # ── source_channels AI columns ───────────────────────────────────────
    for col in (
        "strip_source_tags",
        "watermark_text",
        "watermark_enabled",
        "ai_custom_system_prompt",
        "ai_tone_prompt",
        "ai_target_language",
        "ai_mode",
        "ai_enabled",
    ):
        op.drop_column("source_channels", col)

    # ── published_dedupe tenant ──────────────────────────────────────────
    op.drop_index("ix_published_dedupe_tenant_id", table_name="published_dedupe")
    op.drop_constraint("fk_published_dedupe_tenant_id", "published_dedupe", type_="foreignkey")
    op.drop_column("published_dedupe", "tenant_id")

    # ── tenant_id from all tables ────────────────────────────────────────
    for table in ("post_events", "posts", "source_channels", "templates", "tags", "admins"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    # ── tenants table ────────────────────────────────────────────────────
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

    # ── ai_mode enum ─────────────────────────────────────────────────────
    sa.Enum(name="ai_mode").drop(op.get_bind(), checkfirst=True)

    # Note: PostgreSQL does not support removing values from an existing enum
    # (ai_transformed, ai_failed from event_action). They are harmless to leave.
