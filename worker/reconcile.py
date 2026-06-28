"""Scheduled-publish reconcile + dedupe/media pruning.

- `reconcile_scheduled()`: run on worker boot — re-enqueue `publish` for any
  `scheduled` posts whose `scheduled_for` has passed but which lack a
  `published_message_id` (plan §6: "Scheduled job loss").
- `prune_dedupe(ctx)`: the ARQ housekeeping job — drops `published_dedupe` rows
  older than the lookback window and prunes orphaned media files older than the
  media-retention window.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import PostState
from shared.logging import get_logger
from shared.models import Post, PostEvent, PublishedDedupe
from shared.tasks import enqueue_publish

log = get_logger("worker.reconcile")

# Bound reconcile so a long outage doesn't enqueue a thundering herd of stale
# publishes at once. Posts overdue beyond the cutoff are left for manual review.
_RECONCILE_BATCH = 100
_RECONCILE_MAX_AGE_DAYS = 30

# Posts whose media can still be "in use" (referenced) — used to avoid deleting
# files that a non-terminal or recently-published post depends on.
_MEDIA_RELEVANT_STATES = {
    PostState.pending,
    PostState.approved,
    PostState.scheduled,
    PostState.published,
}


async def reconcile_scheduled() -> int:
    """Re-enqueue overdue scheduled posts. Returns count re-enqueued."""
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=_RECONCILE_MAX_AGE_DAYS)
    requeued = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(Post)
            .where(
                Post.state == PostState.scheduled,
                Post.scheduled_for.is_not(None),
                Post.scheduled_for <= now,
                Post.scheduled_for >= stale_cutoff,
                Post.published_message_id.is_(None),
            )
            .order_by(Post.scheduled_for.asc())
            .limit(_RECONCILE_BATCH)
        )
        posts = list(result.scalars().all())
        for post in posts:
            await enqueue_publish(post.id)
            requeued += 1
            log.info("requeued-overdue", post_id=post.id, scheduled_for=post.scheduled_for.isoformat())
    if requeued:
        log.info("reconcile-done", requeued=requeued)
    return requeued


async def _prune_dedupe_rows() -> int:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.dedupe_lookback_days)
    async with SessionLocal() as session:
        result = await session.execute(
            delete(PublishedDedupe).where(PublishedDedupe.published_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0


async def _prune_audit_events() -> int:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.audit_retention_days)
    async with SessionLocal() as session:
        result = await session.execute(
            delete(PostEvent).where(PostEvent.created_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0


async def _prune_media_files() -> int:
    settings = get_settings()
    media_dir = Path(settings.media_dir)
    if not media_dir.exists():
        return 0
    cutoff_ts = datetime.now(UTC).timestamp() - settings.media_retention_days * 86400
    # Only load media_paths for posts that can still reference media (bounded),
    # not the entire posts table.
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Post.media_paths).where(Post.state.in_(_MEDIA_RELEVANT_STATES))
            )
        ).all()
    referenced = {p for (mp,) in rows for p in (mp or [])}
    removed = 0
    for entry in media_dir.iterdir():
        try:
            if (
                entry.is_file()
                and entry.stat().st_mtime < cutoff_ts
                and str(entry) not in referenced
                and entry.name not in referenced
            ):
                os.remove(entry)
                removed += 1
        except OSError:
            continue
    return removed


async def prune_dedupe(ctx: dict) -> str:
    """ARQ housekeeping job: prune the dedupe lookback index, audit log, and
    orphaned media per the configured retention windows."""
    removed_hashes = await _prune_dedupe_rows()
    removed_events = await _prune_audit_events()
    removed_files = await _prune_media_files()
    log.info(
        "prune-done",
        removed_hashes=removed_hashes,
        removed_events=removed_events,
        removed_files=removed_files,
    )
    return "ok"
