"""SQLAlchemy 2.0 declarative models (plan §4 schema)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shared.enums import AIMode, EventAction, Policy, PostState, Role


def _default_media_size() -> int:
    """Default max media size for a channel (read at call time so tests can patch)."""
    from shared.config import get_settings

    return get_settings().media_max_size_default


class Base(DeclarativeBase):
    pass


# ── Multi-tenancy ────────────────────────────────────────────────────────────


class Tenant(Base):
    """A tenant represents an isolated workspace in multi-tenant mode.

    When ``MULTI_TENANCY_ENABLED=false`` (the default), this table exists but is
    unused — all ``tenant_id`` FKs stay ``NULL`` and queries are unscoped.
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    # Per-tenant Telegram bot credentials (override the global ones).
    bot_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    editor_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Tenant-level AI defaults (channels can override).
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_mode: Mapped[AIMode] = mapped_column(
        Enum(AIMode, name="ai_mode", values_callable=lambda e: [m.value for m in e]),
        default=AIMode.off,
        server_default="off",
    )
    ai_target_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_tone_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_custom_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Watermark/branding defaults.
    watermark_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    watermark_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    strip_source_tags: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Per-tenant config overrides (NULL = use global setting from Settings).
    # These allow each tenant to override the system-wide defaults without
    # touching global environment variables.
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_lookback_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publish_spacing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_max_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Core models ──────────────────────────────────────────────────────────────


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [m.value for m in e]),
        default=Role.editor,
        server_default="editor",
    )
    # Telegram user id of the linked account.  Set this to allow the admin to
    # approve/reject posts via inline buttons in the editor group.
    tg_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, unique=True, index=True
    )
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceChannel(Base):
    __tablename__ = "source_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ingestion_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    policy: Mapped[Policy] = mapped_column(
        Enum(Policy, name="policy", values_callable=lambda e: [m.value for m in e]),
        default=Policy.queue,
        server_default="queue",
    )
    default_tag_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), default=list, server_default="{}"
    )
    normalization_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    max_media_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=_default_media_size, server_default="2147483648"
    )
    source_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    # ── AI Transformation (per-channel override) ─────────────────────────
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_mode: Mapped[AIMode] = mapped_column(
        Enum(AIMode, name="ai_mode", values_callable=lambda e: [m.value for m in e],
             create_constraint=False),
        default=AIMode.off,
        server_default="off",
    )
    ai_target_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_tone_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_custom_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── Watermark/branding ───────────────────────────────────────────────
    watermark_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    watermark_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    strip_source_tags: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    template: Mapped[Template | None] = relationship("Template", lazy="selectin")


class SourceChannelTag(Base):
    """Join table: per-channel default tags (mirrors source_channel.default_tag_ids
    for convenient joins and referential integrity)."""

    __tablename__ = "source_channel_tags"

    source_channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_channels.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("source_channel_id", "source_message_id", name="uq_post_source_msg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_channels.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_media_refs: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    state: Mapped[PostState] = mapped_column(
        Enum(PostState, name="post_state", values_callable=lambda e: [m.value for m in e]),
        default=PostState.pending,
        server_default="pending",
        index=True,
    )
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_transformed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_paths: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    tag_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list, server_default="{}")
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # The editor-supergroup message id of the draft card, so the bot can edit it
    # (e.g. mark "published ✓") when the post is published.
    draft_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admins.id"), nullable=True
    )
    handled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admins.id"), nullable=True
    )
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PostEvent(Base):
    __tablename__ = "post_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    actor_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("admins.id"), nullable=True
    )
    action: Mapped[EventAction] = mapped_column(
        Enum(EventAction, name="event_action", values_callable=lambda e: [m.value for m in e])
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublishedDedupe(Base):
    __tablename__ = "published_dedupe"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "dedupe_hash",
            name="uq_published_dedupe_tenant_hash",
            postgresql_nulls_not_distinct=True,
        ),
    )

    # Surrogate primary key: a PRIMARY KEY cannot include the nullable tenant_id
    # column, so dedupe uniqueness lives in the UNIQUE NULLS NOT DISTINCT constraint
    # above (single-tenant NULL tenant_ids dedupe globally; per-tenant rows are
    # isolated). This id exists only to satisfy SQLAlchemy's mapped-PK requirement.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True
    )
    dedupe_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


__all__ = [
    "Admin",
    "Base",
    "Post",
    "PostEvent",
    "PublishedDedupe",
    "SourceChannel",
    "SourceChannelTag",
    "Tag",
    "Template",
    "Tenant",
]
