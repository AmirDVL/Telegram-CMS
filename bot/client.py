"""Shared aiogram Bot instance, wired to the local telegram-bot-api server."""

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
    """Construct a Bot instance.

    When ``bot_api_server_url`` is configured (the ``largemedia`` deployment
    profile), the bot talks to the local telegram-bot-api server (≤2 GB uploads).
    When it is empty (profile off), the bot falls back to Telegram's cloud API at
    api.telegram.org, which caps uploads at 50 MB — enforced upstream by
    ``media_max_size_default`` (see bot/publisher.py and userbot/ingest.py).
    """
    s = get_settings()
    if s.bot_api_server_url:
        server = TelegramAPIServer.from_base(s.bot_api_server_url, is_local=True)
        session = AiohttpSession(api=server)
        return Bot(token=token, session=session, default=_PROPS)
    return Bot(token=token, default=_PROPS)


def get_bot() -> Bot:
    """Return the global Bot instance."""
    global _bot
    if _bot is None:
        s = get_settings()
        if not s.bot_token:
            raise RuntimeError("BOT_TOKEN is required for the bot service")
        _bot = _build_bot(s.bot_token)
    return _bot
