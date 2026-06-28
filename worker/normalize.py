"""The `normalize` ARQ job (function name == job name).

1. Load the post (idempotent: skip if already terminal).
2. Render the channel's template with raw text + source label + tags
   (per-channel defaults for `auto` channels; empty for `queue` channels).
3. Run AI transformation if enabled on the channel (translate/summarize/retone/custom).
4. Apply watermark/branding if configured.
5. Compute `dedupe_hash`; if it exists in `published_dedupe` within the
   lookback window, mark the post rejected/duplicate.
6. Write `normalized_text` + `tag_ids` + `dedupe_hash` + append `post_events`.
7. Route: `auto` → enqueue `publish`; `queue` → enqueue `post_draft` (the bot
   posts the draft card to the editor supergroup).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from shared.config import get_settings
from shared.db import SessionLocal
from shared.dedupe import compute_dedupe_hash
from shared.enums import AIMode, EventAction, Policy, PostState
from shared.logging import get_logger
from shared.models import Post, PostEvent, PublishedDedupe, SourceChannel, Template
from shared.normalize import DEFAULT_TEMPLATE_BODY, normalize_text
from shared.tasks import enqueue_post_draft, enqueue_publish
from shared.transform import AITransformError, apply_watermark, transform_text

log = get_logger("worker.normalize")


async def _is_duplicate(session, dedupe_hash: str) -> bool:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.dedupe_lookback_days)
    existing = await session.scalar(
        select(PublishedDedupe).where(
            PublishedDedupe.dedupe_hash == dedupe_hash,
            PublishedDedupe.published_at >= cutoff,
        )
    )
    return existing is not None


def decide_route(policy: Policy, is_duplicate: bool) -> str:
    """Pure routing decision: duplicate short-circuits to rejection; otherwise
    `auto` channels publish immediately and `queue` channels go to a draft card."""
    if is_duplicate:
        return "duplicate"
    return "publish" if policy == Policy.auto else "draft"


def _should_ai_transform(channel: SourceChannel) -> bool:
    """Check whether AI transformation should run for this channel."""
    settings = get_settings()
    if not settings.ai_enabled:
        return False
    return channel.ai_enabled and channel.ai_mode != AIMode.off


async def normalize(ctx: dict, post_id: int) -> str:
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            log.warning("post-not-found", post_id=post_id)
            return "not_found"
        if post.state in (PostState.published, PostState.rejected):
            log.info("skip-already-terminal", post_id=post_id, state=post.state.value)
            return f"skip:{post.state.value}"

        channel = await session.get(SourceChannel, post.source_channel_id)
        if channel is None:
            log.error("source-channel-missing", post_id=post_id)
            return "no_channel"

        template_body = DEFAULT_TEMPLATE_BODY
        if channel.normalization_template_id:
            tpl = await session.get(Template, channel.normalization_template_id)
            if tpl is not None:
                template_body = tpl.body

        tag_ids = list(channel.default_tag_ids) if channel.policy == Policy.auto else []
        source_label = channel.source_label or channel.username or channel.title

        normalized = await normalize_text(
            session,
            template_body=template_body,
            raw_text=post.raw_text or "",
            source_label=source_label,
            tag_ids=tag_ids,
        )

        # ── AI Transformation (toggle-controlled) ────────────────────────
        final_text = normalized
        if _should_ai_transform(channel):
            try:
                result = await transform_text(
                    normalized,
                    mode=channel.ai_mode,
                    target_language=channel.ai_target_language,
                    tone_prompt=channel.ai_tone_prompt,
                    custom_system_prompt=channel.ai_custom_system_prompt,
                )
                final_text = result.text
                post.ai_transformed_text = result.text
                session.add(
                    PostEvent(
                        post_id=post.id,
                        action=EventAction.ai_transformed,
                        payload={
                            "model": result.model,
                            "mode": channel.ai_mode.value,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "latency_ms": result.latency_ms,
                        },
                    )
                )
                log.info(
                    "ai-transformed",
                    post_id=post_id,
                    mode=channel.ai_mode.value,
                    latency_ms=result.latency_ms,
                )
            except (AITransformError, Exception) as exc:
                log.warning("ai-transform-failed", post_id=post_id, error=str(exc))
                session.add(
                    PostEvent(
                        post_id=post.id,
                        action=EventAction.ai_failed,
                        payload={"error": str(exc)[:500]},
                    )
                )
                # Fall back to un-transformed text — the post still flows through.

        # ── Watermark / branding (no LLM, always runs if configured) ─────
        final_text = apply_watermark(
            final_text,
            watermark_text=channel.watermark_text if channel.watermark_enabled else None,
            strip_source_tags=channel.strip_source_tags,
        )

        # Hash raw_text (not the rendered template) so that changing a template
        # does not invalidate the entire dedupe history for content that was
        # already published under a different template.
        dedupe_hash = compute_dedupe_hash(post.raw_text, post.raw_media_refs)

        post.normalized_text = final_text
        post.tag_ids = tag_ids
        post.dedupe_hash = dedupe_hash
        # Canonical list of media file paths to (re-)publish, drawn from the
        # userbot-downloaded refs. Omitted (oversize) media is excluded.
        post.media_paths = [
            m["file"] for m in (post.raw_media_refs or []) if m.get("file") and not m.get("omitted")
        ]

        if await _is_duplicate(session, dedupe_hash):
            post.state = PostState.rejected
            session.add(
                PostEvent(
                    post_id=post.id,
                    action=EventAction.duplicate,
                    payload={"dedupe_hash": dedupe_hash},
                )
            )
            await session.commit()
            log.info("duplicate-rejected", post_id=post_id)
            return "duplicate"

        session.add(
            PostEvent(post_id=post.id, action=EventAction.edited, payload={"normalized": True})
        )
        await session.commit()
        log.info("normalized", post_id=post_id, policy=channel.policy.value)

        route = decide_route(channel.policy, False)
        if route == "publish":
            await enqueue_publish(post.id)
            return "enqueued_publish"
        await enqueue_post_draft(post.id)
        return "enqueued_draft"
