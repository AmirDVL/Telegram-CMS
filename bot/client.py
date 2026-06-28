"""Shared aiogram Bot instance(s), wired to the local telegram-bot-api server.

In single-tenant mode, a single global bot is used. In multi-tenant mode,
each tenant can have its own bot_token, so we cache per-tenant Bot instances.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from shared.config import get_settings

_PROPS = DefaultBotProperties(parse_mode=ParseMode.HTML)

# Process-wide singleton.
_bot: Bot | None = None


def _build_bot(token: str) -> Bot:
    """Construct a Bot instance connected to the local Bot API server."""
    s = get_settings()
    server = TelegramAPIServer.from_base(s.bot_api_server_url, is_local=True)
    session = AiohttpSession(api=server)
    return Bot(token=token, session=session, default=_PROPS)


def get_bot() -> Bot:
    """Return the global Bot instance (single-tenant or platform default)."""
    global _bot
    if _bot is None:
        s = get_settings()
        if not s.bot_token:
            raise RuntimeError("BOT_TOKEN is required for the bot service")
        _bot = _build_bot(s.bot_token)
    return _bot


# Per-tenant bots (keyed by tenant_id). Only used when multi-tenancy is on.
_tenant_bots: dict[int, Bot] = {}


def get_bot_for_tenant(tenant_id: int | None, tenant_bot_token: str | None = None) -> Bot:
    """Return a Bot for the given tenant.

    Falls back to the global bot if:
    - ``tenant_id`` is None (multi-tenancy off / platform admin)
    - ``tenant_bot_token`` is empty (tenant uses the platform bot)
    """
    if tenant_id is None or not tenant_bot_token:
        return get_bot()

    if tenant_id not in _tenant_bots:
        _tenant_bots[tenant_id] = _build_bot(tenant_bot_token)
    return _tenant_bots[tenant_id]
