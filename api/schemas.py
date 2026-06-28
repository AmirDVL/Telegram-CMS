"""Pydantic v2 request/response schemas for the back-office API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import EventAction, Policy, PostState, Role


# ── Auth ─────────────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: Role
    tg_user_id: int | None = None
    created_at: datetime
    disabled_at: datetime | None = None


class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.editor
    tg_user_id: int | None = None


class AdminUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Role | None = None
    disabled: bool | None = None
    # Set to the admin's Telegram user id to allow bot inline-button access.
    tg_user_id: int | None = None


# ── Tags ──────────────────────────────────────────────────────────────────────
class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    label: str
    color: str | None = None
    created_at: datetime


class TagCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)


class TagUpdate(BaseModel):
    label: str | None = None
    color: str | None = None


# ── Templates ────────────────────────────────────────────────────────────────
class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    body: str
    created_at: datetime


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    body: str


class TemplateUpdate(BaseModel):
    name: str | None = None
    body: str | None = None


# ── Source channels ───────────────────────────────────────────────────────────
class SourceChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    telegram_channel_id: int
    title: str
    username: str | None = None
    ingestion_enabled: bool
    policy: Policy
    default_tag_ids: list[int]
    normalization_template_id: int | None = None
    max_media_size_bytes: int
    source_label: str | None = None
    created_at: datetime


class SourceChannelCreate(BaseModel):
    telegram_channel_id: int
    title: str = Field(max_length=256)
    username: str | None = None
    ingestion_enabled: bool = True
    policy: Policy = Policy.queue
    default_tag_ids: list[int] = Field(default_factory=list)
    normalization_template_id: int | None = None
    max_media_size_bytes: int | None = None
    source_label: str | None = None


class SourceChannelUpdate(BaseModel):
    title: str | None = None
    username: str | None = None
    ingestion_enabled: bool | None = None
    policy: Policy | None = None
    default_tag_ids: list[int] | None = None
    normalization_template_id: int | None = None
    max_media_size_bytes: int | None = None
    source_label: str | None = None


# ── Posts / draft queue ──────────────────────────────────────────────────────
class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_channel_id: int
    source_message_id: int
    raw_text: str | None = None
    raw_media_refs: list[Any] = Field(default_factory=list)
    received_at: datetime
    state: PostState
    normalized_text: str | None = None
    media_paths: list[Any] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    scheduled_for: datetime | None = None
    published_message_id: int | None = None
    published_at: datetime | None = None
    dedupe_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class PostEditTags(BaseModel):
    tag_ids: list[int]


class PostSchedule(BaseModel):
    scheduled_for: datetime


class PostDecision(BaseModel):
    """Approve now, schedule, or reject — chosen by which field is set."""

    action: str = Field(description="'approve' | 'schedule' | 'reject'")
    tag_ids: list[int] | None = None
    scheduled_for: datetime | None = None


# ── Audit ─────────────────────────────────────────────────────────────────────
class PostEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    actor_admin_id: int | None = None
    action: EventAction
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Paginated(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class HealthOut(BaseModel):
    status: str = "ok"
    service: str
