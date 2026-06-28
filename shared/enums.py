"""Enumerations shared across services."""

from __future__ import annotations

import enum


class Role(str, enum.Enum):
    editor = "editor"
    admin = "admin"
    super_admin = "super_admin"


class Policy(str, enum.Enum):
    auto = "auto"
    queue = "queue"


class PostState(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    scheduled = "scheduled"
    published = "published"
    rejected = "rejected"
    publishing = "publishing"
    publish_failed = "publish_failed"


class EventAction(str, enum.Enum):
    ingested = "ingested"
    edited = "edited"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    published = "published"
    publish_failed = "publish_failed"
    duplicate = "duplicate"
    media_omitted = "media_omitted"
    draft_posted = "draft_posted"


class MediaType(str, enum.Enum):
    photo = "photo"
    video = "video"
    document = "document"
    audio = "audio"
    animation = "animation"
    voice = "voice"
    video_note = "video_note"


# Ordered roles for permission checks: a role grants everything below it.
ROLE_RANK: dict[Role, int] = {
    Role.editor: 0,
    Role.admin: 1,
    Role.super_admin: 2,
}


def role_at_least(held: Role, required: Role) -> bool:
    """True if `held` rank >= `required` rank."""
    return ROLE_RANK[held] >= ROLE_RANK[required]
