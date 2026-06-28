"""Telethon client construction + the session path."""

from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from shared.config import get_settings


def session_path() -> Path:
    settings = get_settings()
    path = Path(settings.session_dir) / f"{settings.telegram_session_name}.session"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_client() -> TelegramClient:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH are required for the userbot"
        )
    return TelegramClient(
        str(session_path()).removesuffix(".session"),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        connection_retries=5,
        retry_delay=2,
        request_retries=5,
        flood_sleep_threshold=60,
    )
