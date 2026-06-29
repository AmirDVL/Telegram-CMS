"""The `alert` ARQ job (function name == job name), consumed by the bot.

Sends a plain-text alert message to the editor supergroup.  Used by the
userbot's MTProto watchdog to notify operators on healthy→unhealthy and
unhealthy→healthy transitions.

Tenant resolution mirrors bot/draft.py: if ``tenant_id`` is provided and
multi-tenancy is enabled the tenant's own bot and editor_group_id are used;
otherwise the global defaults apply.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from bot.client import get_bot, get_bot_for_tenant
from shared.config import get_settings
from shared.db import SessionLocal
from shared.logging import get_logger
from shared.tenant import is_multi_tenant

log = get_logger("bot.alerts")


async def alert(ctx: dict, text: str, tenant_id: int | None = None) -> str:
    """ARQ ``alert`` job.  Sends ``text`` to the editor group.

    Args:
        ctx: ARQ context (unused but required by the job interface).
        text: Message body to send.
        tenant_id: When set and multi-tenancy is enabled, resolves the
            tenant-specific editor group and bot token.

    Returns:
        A short status string: "sent", "no_editor_group", or "error:<msg>".
    """
    settings = get_settings()
    editor_group_id: int | None = settings.editor_group_id
    bot = get_bot()

    # Resolve tenant-specific editor group and bot, mirroring bot/draft.py.
    if tenant_id is not None and is_multi_tenant():
        try:
            async with SessionLocal() as session:
                # get_tenant_for_channel requires a channel_id; here we have
                # only a tenant_id, so we load the Tenant row directly.
                from shared.models import Tenant

                tenant = await session.get(Tenant, tenant_id)
            if tenant is not None:
                if tenant.editor_group_id:
                    editor_group_id = tenant.editor_group_id
                bot = get_bot_for_tenant(tenant.id, tenant.bot_token)
        except Exception:
            log.exception("alert-tenant-resolve-failed", tenant_id=tenant_id)
            # Fall back to global settings on resolution failure.

    if not editor_group_id:
        log.error("alert-no-editor-group")
        return "no_editor_group"

    try:
        await bot.send_message(editor_group_id, text)
        log.info("alert-sent", editor_group_id=editor_group_id, tenant_id=tenant_id)
        return "sent"
    except TelegramAPIError as exc:
        log.exception("alert-send-failed", editor_group_id=editor_group_id)
        return f"error:{exc}"
