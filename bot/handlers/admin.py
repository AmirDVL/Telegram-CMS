"""Admin commands in the editor supergroup: /queue, /stats, /health."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from bot.client import get_bot
from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import PostState
from shared.models import Post

router = Router()


def _authorized(message: Message) -> bool:
    """Only act inside the private editor supergroup (avoids leaking queue data
    to anyone who can DM the bot)."""
    return message.chat.id == get_settings().editor_group_id


@router.message(Command("queue"))
async def cmd_queue(message: Message) -> None:
    if not _authorized(message):
        return
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count(Post.id)).where(Post.state == PostState.pending)
        )
        recent = await session.execute(
            select(Post)
            .where(Post.state == PostState.pending)
            .order_by(Post.received_at.desc())
            .limit(5)
        )
        posts = list(recent.scalars().all())
    lines = [f"<b>Pending queue</b> ({int(total or 0)} total)"]
    for p in posts:
        preview = (p.normalized_text or p.raw_text or "(empty)")[:80].replace("\n", " ")
        lines.append(f"• #{p.id}: {preview}")
    await get_bot().send_message(message.chat.id, "\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _authorized(message):
        return
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Post.state, func.count(Post.id)).group_by(Post.state)
        )
        counts = {state.value: int(c or 0) for state, c in rows.all()}
    ordered = [s.value for s in PostState]
    lines = ["<b>Stats</b>"]
    for s in ordered:
        lines.append(f"{s}: {counts.get(s, 0)}")
    await get_bot().send_message(message.chat.id, "\n".join(lines))


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    if not _authorized(message):
        return
    await get_bot().send_message(message.chat.id, "✅ bot up")
