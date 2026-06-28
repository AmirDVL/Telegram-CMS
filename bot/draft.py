"""The `post_draft` ARQ job (function name == job name), consumed by the bot.

Posts (or refreshes) a draft card in the editor supergroup for a `queue`-policy
post that has just been normalized. The card's inline buttons let an editor
approve/reject inline (edit-tags/schedule are offered via the web back-office,
which mirrors the same queue). The card's message id is stored on the post so
the publish worker can later edit it to "published ✓".
"""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from bot.cards import build_draft_payload
from bot.client import get_bot
from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import EventAction
from shared.logging import get_logger
from shared.models import Post, PostEvent, SourceChannel

log = get_logger("bot.draft")


async def post_draft(ctx: dict, post_id: int) -> str:
    settings = get_settings()
    bot = get_bot()
    group_id = settings.editor_group_id
    if not group_id:
        log.error("editor-group-not-configured")
        return "no_editor_group"

    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return "not_found"
        channel = await session.get(SourceChannel, post.source_channel_id)
        if channel is None:
            return "no_channel"
        text, keyboard = await build_draft_payload(post, channel, session)

    if post.normalized_text is None:
        log.warning("draft-before-normalize", post_id=post_id)
        return "not_normalized"

    try:
        if post.draft_message_id:
            await bot.edit_message_text(
                text=text,
                chat_id=group_id,
                message_id=post.draft_message_id,
                reply_markup=keyboard,
            )
            action = "refreshed"
        else:
            msg = await bot.send_message(chat_id=group_id, text=text, reply_markup=keyboard)
            async with SessionLocal() as session:
                p = await session.get(Post, post_id)
                if p is not None:
                    p.draft_message_id = msg.message_id
                    session.add(
                        PostEvent(
                            post_id=post_id,
                            action=EventAction.draft_posted,
                            payload={"chat_id": group_id, "message_id": msg.message_id},
                        )
                    )
                    await session.commit()
            action = "posted"
        log.info("draft-card", post_id=post_id, action=action)
        return action
    except TelegramAPIError as e:
        log.exception("draft-card-failed", post_id=post_id)
        return f"error:{e}"
