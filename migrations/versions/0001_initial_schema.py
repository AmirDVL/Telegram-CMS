"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("editor", "admin", "super_admin", name="role"),
            server_default="editor",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_admins_username"),
    )
    op.create_index("ix_admins_username", "admins", ["username"])

    op.create_table(
        "tags",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("color", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tags_slug"),
    )
    op.create_index("ix_tags_slug", "tags", ["slug"])

    op.create_table(
        "templates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "source_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("ingestion_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "policy",
            sa.Enum("auto", "queue", name="policy"),
            server_default="queue",
            nullable=False,
        ),
        sa.Column(
            "default_tag_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("normalization_template_id", sa.BigInteger(), nullable=True),
        sa.Column("max_media_size_bytes", sa.BigInteger(), server_default="2147483648", nullable=False),
        sa.Column("source_label", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["normalization_template_id"], ["templates.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("telegram_channel_id", name="uq_source_channels_tg_id"),
    )
    op.create_index("ix_source_channels_telegram_channel_id", "source_channels", ["telegram_channel_id"])

    op.create_table(
        "source_channel_tags",
        sa.Column("source_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_channel_id"], ["source_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_channel_id", "tag_id"),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_media_refs", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending", "approved", "scheduled", "published", "rejected", "publish_failed",
                name="post_state",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("media_paths", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column(
            "tag_ids", postgresql.ARRAY(sa.BigInteger()), server_default="{}", nullable=False
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_message_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_hash", sa.String(64), nullable=True),
        sa.Column("draft_message_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("handled_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_channel_id"], ["source_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["admins.id"]),
        sa.ForeignKeyConstraint(["handled_by"], ["admins.id"]),
        sa.UniqueConstraint("source_channel_id", "source_message_id", name="uq_post_source_msg"),
    )
    op.create_index("ix_posts_source_channel_id", "posts", ["source_channel_id"])
    op.create_index("ix_posts_state", "posts", ["state"])
    op.create_index("ix_posts_scheduled_for", "posts", ["scheduled_for"])
    op.create_index("ix_posts_dedupe_hash", "posts", ["dedupe_hash"])
    # Supports the queue listing (state-filtered, ordered by received_at desc).
    op.create_index("ix_posts_state_received_at", "posts", ["state", "received_at"])

    op.create_table(
        "post_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_admin_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "ingested", "edited", "approved", "rejected", "scheduled", "published",
                "publish_failed", "duplicate", "media_omitted", "draft_posted",
                name="event_action",
            ),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_admin_id"], ["admins.id"]),
    )
    op.create_index("ix_post_events_post_id", "post_events", ["post_id"])

    op.create_table(
        "published_dedupe",
        sa.Column("dedupe_hash", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("dedupe_hash"),
    )
    op.create_index("ix_published_dedupe_published_at", "published_dedupe", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_published_dedupe_published_at", table_name="published_dedupe")
    op.drop_table("published_dedupe")
    op.drop_index("ix_post_events_post_id", table_name="post_events")
    op.drop_table("post_events")
    op.drop_index("ix_posts_dedupe_hash", table_name="posts")
    op.drop_index("ix_posts_state_received_at", table_name="posts")
    op.drop_index("ix_posts_scheduled_for", table_name="posts")
    op.drop_index("ix_posts_state", table_name="posts")
    op.drop_index("ix_posts_source_channel_id", table_name="posts")
    op.drop_table("posts")
    op.drop_table("source_channel_tags")
    op.drop_index("ix_source_channels_telegram_channel_id", table_name="source_channels")
    op.drop_table("source_channels")
    op.drop_table("templates")
    op.drop_index("ix_tags_slug", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_admins_username", table_name="admins")
    op.drop_table("admins")

    sa.Enum(name="event_action").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="post_state").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="policy").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="role").drop(op.get_bind(), checkfirst=True)
