"""The `alert` ARQ job (function name == job name), consumed by the bot.

Sends a plain-text alert message to the editor supergroup.  Used by the
userbot's MTProto watchdog to notify operators on healthy→unhealthy and
unhealthy→healthy transitions.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from bot.client import get_bot
from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("bot.alerts")


async def alert(ctx: dict, text: str, tenant_id: int | None = None) -> str:
    """ARQ ``alert`` job.  Sends ``text`` to the editor group.

    Args:
        ctx: ARQ context (unused but required by the job interface).
        text: Message body to send.
        tenant_id: Accepted for backward compatibility with in-flight ARQ jobs;
            ignored (single-tenant deployment).

    Returns:
        A short status string: "sent", "no_editor_group", or "error:<msg>".
    """
    settings = get_settings()
    editor_group_id: int | None = settings.editor_group_id
    bot = get_bot()

    if not editor_group_id:
        log.error("alert-no-editor-group")
        return "no_editor_group"

    try:
        await bot.send_message(editor_group_id, text)
        log.info("alert-sent", editor_group_id=editor_group_id)
        return "sent"
    except TelegramAPIError as exc:
        log.exception("alert-send-failed", editor_group_id=editor_group_id)
        return f"error:{exc}"
