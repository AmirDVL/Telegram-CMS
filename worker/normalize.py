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
from shared.tenant import effective, get_tenant_for_channel
from shared.transform import AITransformError, apply_watermark, transform_text

log = get_logger("worker.normalize")


async def _is_duplicate(session, dedupe_hash: str, tenant=None) -> bool:
    """Check whether this hash was published recently, scoped to the tenant.

    When multi-tenancy is off (the default) ``tenant`` is always ``None`` and
    the query is unscoped — identical to the previous behaviour.
    """
    lookback_days = effective("dedupe_lookback_days", tenant)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    stmt = select(PublishedDedupe).where(
        PublishedDedupe.dedupe_hash == dedupe_hash,
        PublishedDedupe.published_at >= cutoff,
    )
    if tenant is not None:
        stmt = stmt.where(PublishedDedupe.tenant_id == tenant.id)
    existing = await session.scalar(stmt)
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

        # Resolve the tenant for this channel — None when multi-tenancy is off
        # or the channel has no tenant_id (single-tenant mode, always None).
        tenant = await get_tenant_for_channel(session, channel.id)

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
        # Channel-level settings take precedence; tenant defaults serve as a
        # fallback when channel hasn't explicitly overridden them (only relevant
        # when multi-tenancy is on; tenant is None otherwise so effective()
        # falls through to global Settings — unchanged behaviour).
        final_text = normalized
        if _should_ai_transform(channel):
            # Resolve per-tenant AI overrides (NULL tenant → global settings).
            ai_model = effective("ai_model", tenant)
            ai_max_tokens = effective("ai_max_tokens", tenant)
            ai_timeout = effective("ai_timeout_seconds", tenant)
            try:
                result = await transform_text(
                    normalized,
                    mode=channel.ai_mode,
                    target_language=channel.ai_target_language,
                    tone_prompt=channel.ai_tone_prompt,
                    custom_system_prompt=channel.ai_custom_system_prompt,
                    model=ai_model,
                    max_tokens=ai_max_tokens,
                    timeout=ai_timeout,
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
        # Prefer the channel's own watermark settings; when the channel has
        # watermark disabled but the tenant has one configured, apply the tenant
        # default.  When multi-tenancy is off tenant is None so effective()
        # falls through to Settings — the global watermark_text is never set
        # there, meaning this is a true no-op in single-tenant mode.
        wm_enabled = channel.watermark_enabled or (
            tenant is not None and tenant.watermark_enabled and not channel.watermark_enabled
        )
        wm_text = channel.watermark_text if channel.watermark_enabled else (
            tenant.watermark_text if (tenant is not None and tenant.watermark_enabled) else None
        )
        strip_tags = channel.strip_source_tags or (
            tenant is not None and tenant.strip_source_tags and not channel.strip_source_tags
        )
        final_text = apply_watermark(
            final_text,
            watermark_text=wm_text if wm_enabled else None,
            strip_source_tags=strip_tags,
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

        if await _is_duplicate(session, dedupe_hash, tenant):
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
