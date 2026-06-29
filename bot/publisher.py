"""The `publish` ARQ job (function name == job name), consumed by the bot.

Re-uploads media (via the local Bot API server) + sends normalized text to the
destination channel. Idempotent: skips if already published. Spaced to respect
Telegram rate limits.

Double-publish guard
--------------------
A ``publishing`` intermediate state is set before the Telegram send so any
concurrent or retried ARQ job sees the state in ``_SKIP_STATES`` and aborts.

Additionally a ``PublishedDedupe`` row is pre-inserted *before* ``_send_post``:

* If the send fails the reservation is removed (``_release_dedupe``) so the
  next retry can try again.
* If the send succeeds but ``_mark_published`` fails (rare DB blip) the dedupe
  row persists.  On retry ``_dedupe_exists`` returns ``True``, the job calls
  ``_mark_duplicate`` and exits without re-sending.  The audit log records the
  duplicate event so operators can identify and manually reconcile the DB state.

On success records ``published_dedupe`` and edits the draft card to
"published ✓"; on failure marks ``publish_failed`` and alerts the editor group
(the job re-raises so ARQ retries with backoff).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaDocument, InputMediaPhoto, InputMediaVideo
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.cards import CAPTION_LIMIT, build_draft_payload
from bot.client import get_bot, get_bot_for_tenant
from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import EventAction, PostState
from shared.logging import get_logger
from shared.models import Post, PostEvent, PublishedDedupe, SourceChannel
from shared.tenant import effective, get_tenant_for_channel

log = get_logger("bot.publish")

# Serialize sends so the spaced-queue contract holds even if the worker's
# max_jobs is raised above 1.
_send_lock = asyncio.Lock()

# Terminal/non-publishable states.
# `publishing` is included: a concurrent job or ARQ retry must not re-send
# while this job is already in the Telegram send path.
# `publish_failed` is intentionally excluded so ARQ retries are allowed.
_SKIP_STATES = {PostState.rejected, PostState.published, PostState.publishing}


async def _send_post(bot: Bot, chat_id: int, text: str, media_refs: list[dict]) -> int | None:
    """Send text (+ re-uploaded media) to chat_id. Returns the message_id of the
    text/primary message (None if nothing was sent)."""
    files = [m for m in media_refs if m.get("file") and not m.get("omitted")]

    # Defensive size cap (belt-and-suspenders for cloud mode, where the cap is
    # 50 MB): userbot/ingest.py already omits oversized media at download time,
    # but a file on disk from before a tier downgrade could still slip through and
    # trigger a cryptic Telegram 413. Drop anything over the configured limit.
    max_size = get_settings().media_max_size_default
    for m in files:
        if m.get("size") and m["size"] > max_size:
            log.warning(
                "media-oversize-skip-at-send",
                file=m.get("file"),
                size=m.get("size"),
                limit=max_size,
            )
    files = [m for m in files if not m.get("size") or m["size"] <= max_size]

    if not files:
        msg = await bot.send_message(chat_id, text or " ")
        return msg.message_id

    primary = files[0]
    path = Path(primary["file"])
    if not path.exists():
        log.warning("media-file-missing", path=str(path))
        msg = await bot.send_message(chat_id, text or " ")
        return msg.message_id

    file_input = FSInputFile(str(path))
    mtype = primary.get("type")
    caption = text if text and len(text) <= CAPTION_LIMIT else None

    if mtype == "photo":
        msg = await bot.send_photo(chat_id, photo=file_input, caption=caption)
    elif mtype == "video":
        msg = await bot.send_video(chat_id, video=file_input, caption=caption)
    elif mtype == "animation":
        msg = await bot.send_animation(chat_id, animation=file_input, caption=caption)
    elif mtype == "audio":
        msg = await bot.send_audio(chat_id, audio=file_input, caption=caption)
    elif mtype == "voice":
        msg = await bot.send_voice(chat_id, voice=file_input)
    elif mtype == "video_note":
        msg = await bot.send_video_note(chat_id, video_note=file_input)
    else:
        msg = await bot.send_document(chat_id, document=file_input, caption=caption)

    # If there are extra media items, send them as a media group (best-effort).
    extra = files[1:]
    if extra:
        group = []
        for m in extra[:9]:
            p = Path(m["file"])
            if not p.exists():
                continue
            fi = FSInputFile(str(p))
            if m.get("type") == "photo":
                group.append(InputMediaPhoto(media=fi))
            elif m.get("type") == "video":
                group.append(InputMediaVideo(media=fi))
            else:
                group.append(InputMediaDocument(media=fi))
        if group:
            await bot.send_media_group(chat_id, media=group)

    # Caption was omitted because it was too long → send text as its own message.
    if caption is None and text:
        await bot.send_message(chat_id, text)
    return msg.message_id


async def _dedupe_exists(dedupe_hash: str) -> bool:
    async with SessionLocal() as session:
        found = await session.scalar(
            select(PublishedDedupe.dedupe_hash).where(PublishedDedupe.dedupe_hash == dedupe_hash)
        )
        return found is not None


async def _reserve_dedupe(dedupe_hash: str | None, tenant_id: int | None = None) -> bool:
    """Pre-insert a PublishedDedupe row as a send reservation before the Telegram send.

    Returns True if the reservation was newly created (safe to proceed).
    Returns False if the row already existed — another job won the race.
    When dedupe_hash is None, returns True unconditionally (nothing to reserve).

    ``tenant_id`` is stamped onto the row so that per-tenant dedupe queries
    (in normalize._is_duplicate) can filter by tenant.  When multi-tenancy is
    off tenant_id is None and the column stays NULL — unchanged behaviour.
    """
    if not dedupe_hash:
        return True
    async with SessionLocal() as session:
        values: dict = {"dedupe_hash": dedupe_hash}
        if tenant_id is not None:
            values["tenant_id"] = tenant_id
        result = await session.execute(
            pg_insert(PublishedDedupe)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_hash"])
            .returning(PublishedDedupe.dedupe_hash)
        )
        await session.commit()
        return result.fetchone() is not None


async def _release_dedupe(dedupe_hash: str | None) -> None:
    """Remove a pre-inserted dedupe reservation after a failed send so the next
    retry can attempt the publish again."""
    if not dedupe_hash:
        return
    async with SessionLocal() as session:
        await session.execute(
            delete(PublishedDedupe).where(PublishedDedupe.dedupe_hash == dedupe_hash)
        )
        await session.commit()


async def _mark_duplicate(post_id: int, dedupe_hash: str) -> None:
    """A concurrent publish of identical content already won — skip + record."""
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return
        post.state = PostState.rejected
        session.add(
            PostEvent(
                post_id=post_id,
                action=EventAction.duplicate,
                payload={"dedupe_hash": dedupe_hash, "reason": "race_at_publish"},
            )
        )
        await session.commit()


async def _mark_published(post_id: int, message_id: int, dedupe_hash: str | None) -> None:
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return
        post.state = PostState.published
        post.published_message_id = message_id
        post.published_at = datetime.now(UTC)
        session.add(
            PostEvent(
                post_id=post_id,
                action=EventAction.published,
                payload={
                    "published_message_id": message_id,
                    "chat_id": get_settings().destination_channel_id,
                },
            )
        )
        if dedupe_hash:
            # Idempotent: the reservation row already exists from _reserve_dedupe;
            # ON CONFLICT DO NOTHING is a no-op here but keeps _mark_published
            # safe to call in isolation (e.g. from tests).
            session.add(
                pg_insert(PublishedDedupe)
                .values(dedupe_hash=dedupe_hash)
                .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_hash"])
            )
        await session.commit()


async def _edit_draft_card(post: Post, channel: SourceChannel) -> None:
    if not post.draft_message_id:
        return
    bot = get_bot()
    async with SessionLocal() as session:
        text, keyboard = await build_draft_payload(post, channel, session)
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=get_settings().editor_group_id,
            message_id=post.draft_message_id,
            reply_markup=keyboard,
        )
    except TelegramAPIError as e:
        log.warning("edit-draft-card-failed", post_id=post.id, error=str(e))


async def _alert_failure(post: Post, error: str) -> None:
    bot = get_bot()
    group_id = get_settings().editor_group_id
    if not group_id:
        return
    try:
        await bot.send_message(
            group_id,
            f"⚠️ <b>Publish failed</b> for post #{post.id}\n<code>{error[:300]}</code>",
        )
    except TelegramAPIError:
        pass


async def _publish_core(ctx: dict, post_id: int) -> str:
    settings = get_settings()
    bot = get_bot()

    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            log.warning("post-not-found", post_id=post_id)
            return "not_found"
        if post.published_message_id is not None:
            log.info("skip-already-published", post_id=post_id)
            return "already_published"
        if post.state in _SKIP_STATES:
            log.info("skip-state", post_id=post_id, state=post.state.value)
            return f"skip:{post.state.value}"

        # Transition to `publishing` — any concurrent job or ARQ retry that loads
        # this post after this commit will see the state in _SKIP_STATES and exit
        # early, preventing a double-send while this job is in-flight.
        post.state = PostState.publishing
        await session.commit()

        channel = await session.get(SourceChannel, post.source_channel_id)
        media_refs = list(post.raw_media_refs or [])
        normalized_text = post.ai_transformed_text or post.normalized_text or post.raw_text or ""
        dedupe_hash = post.dedupe_hash
        tenant_id = post.tenant_id

    if channel is None:
        log.error("channel-missing", post_id=post_id)
        return "no_channel"

    # Resolve tenant-specific settings (destination channel, bot token).
    dest_channel_id = settings.destination_channel_id
    bot = get_bot()
    async with SessionLocal() as session:
        tenant = await get_tenant_for_channel(session, post.source_channel_id) if tenant_id else None
    if tenant is not None:
        # Defensive sanity check: the tenant we resolved must match the post's
        # own tenant_id.  A mismatch would only occur if channel.tenant_id was
        # updated between ingest and publish — treat it as a data-integrity
        # warning rather than a hard failure so the post is not silently dropped.
        if tenant_id is not None and tenant.id != tenant_id:
            log.warning(
                "tenant-mismatch",
                post_id=post_id,
                post_tenant_id=tenant_id,
                channel_tenant_id=tenant.id,
            )
        if tenant.destination_channel_id:
            dest_channel_id = tenant.destination_channel_id
        bot = get_bot_for_tenant(tenant.id, tenant.bot_token)

    # Resolve publish spacing — per-tenant override takes priority over global.
    spacing = effective("publish_spacing_seconds", tenant)

    # Pre-send dedupe re-check: a concurrent publish of identical content may
    # have already won (the lookback row now exists). Skip instead of double-posting.
    if dedupe_hash and await _dedupe_exists(dedupe_hash):
        log.info("duplicate-at-publish", post_id=post_id)
        await _mark_duplicate(post_id, dedupe_hash)
        return "duplicate"

    # Pre-insert a dedupe reservation before touching Telegram. If _mark_published
    # later fails, the row persists so any ARQ retry will find _dedupe_exists() True
    # and mark the post duplicate rather than re-sending it. If the Telegram send
    # itself fails, we remove the reservation so the next retry can try again.
    # Stamp tenant_id on the reservation so per-tenant dedupe queries work correctly.
    if dedupe_hash and not await _reserve_dedupe(dedupe_hash, tenant_id):
        log.info("duplicate-at-publish-race", post_id=post_id)
        await _mark_duplicate(post_id, dedupe_hash)
        return "duplicate"

    # Spaced send — capture the exception so we can cleanly release the dedupe
    # reservation before re-raising, keeping the two failure paths separated.
    send_error: BaseException | None = None
    message_id: int | None = None
    try:
        async with _send_lock:
            await asyncio.sleep(spacing)
            try:
                message_id = await _send_post(
                    bot, dest_channel_id, normalized_text, media_refs
                )
            except TelegramRetryAfter as e:
                log.warning("retry-after", seconds=e.retry_after)
                await asyncio.sleep(e.retry_after + 1)
                message_id = await _send_post(
                    bot, dest_channel_id, normalized_text, media_refs
                )
    except Exception as exc:
        send_error = exc

    if send_error is not None:
        # Telegram send failed — release the reservation so the retry can try again.
        await _release_dedupe(dedupe_hash)
        raise send_error

    if not message_id:
        # _send_post returned None/0 — treat as a send failure and allow retry.
        await _release_dedupe(dedupe_hash)
        raise RuntimeError(f"_send_post returned no message_id for post {post_id}")

    # Send succeeded. The dedupe row already exists from _reserve_dedupe; the
    # ON CONFLICT DO NOTHING in _mark_published is a harmless no-op.
    await _mark_published(post_id, message_id, dedupe_hash)

    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is not None:
            await _edit_draft_card(post, channel)
    log.info("published", post_id=post_id, message_id=message_id)
    return "published"


async def _on_publish_failure(post_id: int, error: str) -> None:
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return
        post.state = PostState.publish_failed
        session.add(
            PostEvent(
                post_id=post_id, action=EventAction.publish_failed, payload={"error": error[:500]}
            )
        )
        await session.commit()
        await _alert_failure(post, error)


async def publish(ctx: dict, post_id: int) -> str:
    """ARQ `publish` job. On transient failure, flip state + alert, then re-raise
    so ARQ retries with backoff."""
    try:
        return await _publish_core(ctx, post_id)
    except Exception as exc:
        log.exception("publish-error", post_id=post_id)
        await _on_publish_failure(post_id, str(exc))
        raise
