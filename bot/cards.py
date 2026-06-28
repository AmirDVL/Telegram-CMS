"""Draft-card rendering + inline keyboards for the editor supergroup."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.markdown import html_decoration as hd

from shared.config import get_settings
from shared.enums import PostState
from shared.models import Post, SourceChannel, Tag

CAPTION_LIMIT = 1024
PREVIEW_LIMIT = 900


async def render_draft_text(post: Post, channel: SourceChannel, tags: list[Tag]) -> str:
    label = channel.source_label or channel.username or channel.title
    state_badge = {
        PostState.pending: "⏳ PENDING",
        PostState.approved: "✅ APPROVED",
        PostState.scheduled: "🗓 SCHEDULED",
        PostState.published: "☑️ PUBLISHED",
        PostState.rejected: "🗑 REJECTED",
        PostState.publish_failed: "⚠️ FAILED",
    }.get(post.state, post.state.value.upper())

    media_note = ""
    media_refs = post.raw_media_refs or []
    if media_refs:
        kinds = sorted({m.get("type", "media") for m in media_refs})
        omitted = any(m.get("omitted") for m in media_refs)
        media_note = f"\n📎 media: {', '.join(kinds)}" + (" (omitted: too large)" if omitted else "")

    body = post.normalized_text or post.raw_text or "(empty)"
    if len(body) > PREVIEW_LIMIT:
        body = body[:PREVIEW_LIMIT] + "…"

    tag_str = ", ".join(t.label for t in tags) or "—"
    lines = [
        f"<b>{state_badge}</b>  ·  <b>{hd.quote(label)}</b>",
        f"<i>post #{post.id}</i>  ·  src msg {post.source_message_id}",
        f"tags: {hd.quote(tag_str)}{media_note}",
        "—",
        hd.quote(body),
    ]
    if post.scheduled_for:
        lines.append(f"\n🗓 scheduled for {hd.quote(post.scheduled_for.strftime('%Y-%m-%d %H:%M UTC'))}")
    return "\n".join(lines)


def draft_keyboard(post: Post) -> InlineKeyboardMarkup:
    settings = get_settings()
    web_url = f"{settings.public_web_url}/queue/{post.id}"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"ap:{post.id}"),
            InlineKeyboardButton(text="🗑 Reject", callback_data=f"rj:{post.id}"),
        ],
        [
            InlineKeyboardButton(text="🏷 Edit tags", url=web_url),
            InlineKeyboardButton(text="🗓 Schedule", url=web_url),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def published_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="☑️ Published ✓", callback_data="noop")]])


async def build_draft_payload(post: Post, channel: SourceChannel, session) -> tuple[str, InlineKeyboardMarkup]:
    """Render the draft card text + keyboard for the post's *current* state.

    Because `render_draft_text` reads `post.state` live, calling this again after
    the publish worker flips the state to `published` yields the "published ✓" card.
    """
    tags: list[Tag] = []
    if post.tag_ids:
        from sqlalchemy import select

        result = await session.execute(select(Tag).where(Tag.id.in_(post.tag_ids)))
        tags = list(result.scalars().all())
    text = await render_draft_text(post, channel, tags)
    if post.state == PostState.published:
        return text, published_keyboard()
    if post.state in (PostState.rejected, PostState.publish_failed):
        return text, InlineKeyboardMarkup(inline_keyboard=[])
    return text, draft_keyboard(post)
