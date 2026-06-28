"""Ingestion: turn a Telethon message into a `posts` row + downloaded media.

Idempotent: the unique constraint on (source_channel_id, source_message_id)
prevents double-ingestion on restart/backfill. Handles FloodWait with backoff.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.message import Message

from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import EventAction, MediaType, PostState
from shared.logging import get_logger
from shared.models import Post, PostEvent, SourceChannel
from shared.tasks import enqueue_normalize

log = get_logger("userbot.ingest")

# Map Telethon media kinds to our MediaType.
_PHOTO = MediaType.photo
_VIDEO = MediaType.video
_DOC = MediaType.document
_AUDIO = MediaType.audio
_GIF = MediaType.animation
_VOICE = MediaType.voice
_VIDEONOTE = MediaType.video_note


def _media_kind(message: Message) -> MediaType | None:
    if message.photo is not None:
        return _PHOTO
    if message.video is not None:
        return _VIDEONOTE if message.video_note is not None else _VIDEO
    if message.voice is not None:
        return _VOICE
    if message.gif is not None:
        return _GIF
    if message.audio is not None:
        return _AUDIO
    if message.document is not None:
        return _DOC
    return None


async def _download_media(
    client: TelegramClient, message: Message, post_id: int, channel: SourceChannel
) -> dict | None:
    kind = _media_kind(message)
    if kind is None:
        return None
    size = 0
    if message.document is not None:
        size = getattr(message.document, "size", 0) or 0
    if size and size > channel.max_media_size_bytes:
        log.info(
            "media-oversize-skip", post_id=post_id, size=size, limit=channel.max_media_size_bytes
        )
        return {"type": kind.value, "file": "", "size": size, "mime": None, "omitted": True}

    settings = get_settings()
    ext = ""
    if message.document is not None and message.document.mime_type:
        ext = message.document.mime_type.split("/")[-1]
    base = Path(settings.media_dir)
    base.mkdir(parents=True, exist_ok=True)
    idx = 0
    target = base / f"{post_id}_{idx}_{kind.value}.{ext or 'bin'}"
    # Avoid collisions if a single post somehow has >1 media (albums are split
    # across messages in v1, so idx is normally 0).
    while target.exists():
        idx += 1
        target = base / f"{post_id}_{idx}_{kind.value}.{ext or 'bin'}"

    try:
        result = await client.download_media(message, file=str(target))
    except FloodWaitError as e:
        log.warning("floodwait-download", seconds=e.seconds)
        await asyncio.sleep(e.seconds + 1)
        result = await client.download_media(message, file=str(target))

    if not result:
        return None
    return {
        "type": kind.value,
        "file": str(target),
        "size": size,
        "mime": message.document.mime_type if message.document is not None else None,
    }


async def ingest_message(
    client: TelegramClient, message: Message, channel: SourceChannel
) -> Post | None:
    """Insert a posts row for `message` (idempotent) + download media + enqueue normalize.

    Insert first with empty media_refs to claim an id and enforce the unique
    constraint; download media afterwards and update the row. This keeps the
    transaction short and avoids relying on sequence-rollback semantics.
    """
    text = message.raw_text or message.message or None

    async with SessionLocal() as session:
        post = Post(
            source_channel_id=channel.id,
            source_message_id=message.id,
            raw_text=text,
            raw_media_refs=[],
        )
        session.add(post)
        session.add(
            PostEvent(
                post=post,
                action=EventAction.ingested,
                payload={"has_media": False},
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            log.debug("already-ingested", channel_id=channel.id, msg_id=message.id)
            return None
        await session.refresh(post)
        post_id = post.id

    # Download media (outside the short transaction), then update the row.
    media_ref = await _download_media(client, message, post_id, channel)
    media_refs: list[dict[str, Any]] = [media_ref] if media_ref is not None else []
    omitted = any(m.get("omitted") for m in media_refs)

    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:  # pragma: no cover - defensive
            return None
        post.raw_media_refs = media_refs
        session.add(
            PostEvent(
                post_id=post_id,
                action=EventAction.media_omitted if omitted else EventAction.edited,
                payload={"has_media": bool(media_refs), "omitted": omitted},
            )
        )
        await session.commit()

    await enqueue_normalize(post_id)
    log.info(
        "ingested",
        post_id=post_id,
        channel_id=channel.id,
        msg_id=message.id,
        has_media=bool(media_refs),
    )
    return post


# Posts stuck in pending with no media refs older than this are considered
# orphaned by a previous crash and are re-enqueued for normalization.
_ORPHAN_AGE_MINUTES = 5
_ORPHAN_BATCH = 200


async def reconcile_pending() -> int:
    """Re-enqueue normalize for posts stuck in `pending` with empty media refs.

    These are created by the two-phase ingest when the userbot crashed between
    the initial INSERT and the subsequent UPDATE + enqueue.  Safe to re-enqueue
    because `normalize` skips posts already in a terminal state.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=_ORPHAN_AGE_MINUTES)
    requeued = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(Post)
            .where(
                Post.state == PostState.pending,
                Post.raw_media_refs == [],
                Post.received_at <= cutoff,
            )
            .order_by(Post.received_at.asc())
            .limit(_ORPHAN_BATCH)
        )
        posts = list(result.scalars().all())

    for post in posts:
        await enqueue_normalize(post.id)
        requeued += 1
        log.info("requeued-orphan", post_id=post.id, received_at=post.received_at.isoformat())

    if requeued:
        log.info("reconcile-pending-done", requeued=requeued)
    return requeued


async def last_ingested_message_id(channel: SourceChannel) -> int:
    async with SessionLocal() as session:
        result = await session.scalar(
            select(Post.source_message_id)
            .where(Post.source_channel_id == channel.id)
            .order_by(Post.source_message_id.desc())
            .limit(1)
        )
    return int(result or 0)
