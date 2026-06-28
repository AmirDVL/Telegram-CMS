"""Tests for local vs cloud Bot API mode selection (bot/client.py).

When ``BOT_API_SERVER_URL`` is set the bot talks to the local telegram-bot-api
server (the ``largemedia`` deployment profile); when empty it falls back to
Telegram's cloud API. These are hermetic — constructing an aiogram ``Bot`` opens
no network connection.
"""

from __future__ import annotations

import pytest

from bot.client import _build_bot
from shared.config import reload_settings

_DUMMY_TOKEN = "123456:test-token-abc"  # format-valid; never used against the network


@pytest.fixture
def restore_settings():
    """Ensure the global settings cache is reset after each test mutates env."""
    yield
    reload_settings()


def test_use_local_bot_api_true_when_url_set(monkeypatch, restore_settings):
    monkeypatch.setenv("BOT_API_SERVER_URL", "http://botapi:8081")
    settings = reload_settings()
    assert settings.use_local_bot_api is True


def test_use_local_bot_api_false_when_url_empty(monkeypatch, restore_settings):
    monkeypatch.setenv("BOT_API_SERVER_URL", "")
    settings = reload_settings()
    assert settings.use_local_bot_api is False


def test_build_bot_local_mode_uses_configured_server(monkeypatch, restore_settings):
    monkeypatch.setenv("BOT_API_SERVER_URL", "http://botapi:8081")
    reload_settings()
    bot = _build_bot(_DUMMY_TOKEN)
    # The session points at the local server, not Telegram's cloud.
    assert "botapi" in str(bot.session.api.base)
    assert "api.telegram.org" not in str(bot.session.api.base)


def test_build_bot_cloud_mode_falls_back_to_telegram(monkeypatch, restore_settings):
    monkeypatch.setenv("BOT_API_SERVER_URL", "")
    reload_settings()
    bot = _build_bot(_DUMMY_TOKEN)
    # Default aiogram session targets the cloud API.
    assert "api.telegram.org" in str(bot.session.api.base)
