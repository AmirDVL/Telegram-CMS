"""aiogram Bot construction, wired to the local telegram-bot-api server.

Using the local Bot API server bypasses the 50 MB cloud upload limit (≤2 GB),
which is required because the bot re-uploads media the userbot downloaded
(it cannot forward/copy media from third-party channels).
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from shared.config import get_settings

_bot: Bot | None = None


def build_bot() -> Bot:
    s = get_settings()
    if not s.bot_token:
        raise RuntimeError("BOT_TOKEN is required for the bot service")
    # Local telegram-bot-api server: bypasses the 50 MB cloud upload limit (≤2 GB).
    server = TelegramAPIServer.from_base(s.bot_api_server_url, is_local=True)
    session = AiohttpSession(api=server)
    return Bot(
        token=s.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def get_bot() -> Bot:
    """Lazy process-wide singleton Bot (shared by polling + the ARQ publish worker)."""
    global _bot
    if _bot is None:
        _bot = build_bot()
    return _bot
