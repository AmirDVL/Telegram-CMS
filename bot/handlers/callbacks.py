"""Inline-button callbacks: Approve / Reject (edit-tags & schedule via the web)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select

from bot.cards import build_draft_payload
from bot.client import get_bot
from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import EventAction, PostState, Role, role_at_least
from shared.logging import get_logger
from shared.models import Admin, Post, PostEvent, SourceChannel
from shared.tasks import enqueue_publish

router = Router()
log = get_logger("bot.callbacks")


async def _authorized(callback: CallbackQuery) -> bool:
    """Return True only when the callback arrives from the editor supergroup
    AND the sender is a non-disabled admin with at least the `editor` role.

    Group-only check is not enough: anyone who has ever been in the group can
    forward a draft card to a private chat and trigger the buttons there.
    Admin role check prevents non-admin group members from approving posts.
    """
    chat = getattr(callback.message, "chat", None)
    if chat is None or chat.id != get_settings().editor_group_id:
        return False

    tg_user_id = callback.from_user.id
    async with SessionLocal() as session:
        admin = await session.scalar(
            select(Admin).where(
                Admin.tg_user_id == tg_user_id,
                Admin.disabled_at.is_(None),
            )
        )
    if admin is None:
        log.warning(
            "callback-unlinked-user",
            tg_user_id=tg_user_id,
            hint="set tg_user_id on the admin row to allow bot access",
        )
        return False
    return role_at_least(admin.role, Role.editor)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("ap:"))
async def cb_approve(callback: CallbackQuery) -> None:
    if not await _authorized(callback):
        await callback.answer("Not authorized", show_alert=True)
        return
    post_id = int(callback.data.split(":", 1)[1])
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            await callback.answer("post not found", show_alert=True)
            return
        channel = await session.get(SourceChannel, post.source_channel_id)
        if channel is None:
            await callback.answer("source channel missing", show_alert=True)
            return
        post.state = PostState.approved
        session.add(
            PostEvent(
                post_id=post_id,
                action=EventAction.approved,
                payload={"via": "inline", "tg_user_id": callback.from_user.id},
            )
        )
        await session.commit()
        text, keyboard = await build_draft_payload(post, channel, session)

    await callback.answer("Approved — publishing…")
    await enqueue_publish(post_id)
    if post.draft_message_id:
        try:
            await get_bot().edit_message_text(
                text=text,
                chat_id=callback.message.chat.id,
                message_id=post.draft_message_id,
                reply_markup=keyboard,
            )
        except TelegramAPIError as e:
            log.warning("approve-edit-failed", post_id=post_id, error=str(e))


@router.callback_query(F.data.startswith("rj:"))
async def cb_reject(callback: CallbackQuery) -> None:
    if not await _authorized(callback):
        await callback.answer("Not authorized", show_alert=True)
        return
    post_id = int(callback.data.split(":", 1)[1])
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            await callback.answer("post not found", show_alert=True)
            return
        channel = await session.get(SourceChannel, post.source_channel_id)
        if channel is None:
            await callback.answer("source channel missing", show_alert=True)
            return
        post.state = PostState.rejected
        session.add(
            PostEvent(
                post_id=post_id,
                action=EventAction.rejected,
                payload={"via": "inline", "tg_user_id": callback.from_user.id},
            )
        )
        await session.commit()
        text, keyboard = await build_draft_payload(post, channel, session)

    await callback.answer("Rejected")
    if post.draft_message_id:
        try:
            await get_bot().edit_message_text(
                text=text,
                chat_id=callback.message.chat.id,
                message_id=post.draft_message_id,
                reply_markup=keyboard,
            )
        except TelegramAPIError as e:
            log.warning("reject-edit-failed", post_id=post_id, error=str(e))
