"""Tests for the AI transformation engine (shared/transform.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.enums import AIMode
from shared.transform import (
    AITransformError,
    TransformResult,
    _build_system_prompt,
    apply_watermark,
    transform_text,
)


# ── System prompt builder tests ──────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_translate_default_language(self):
        prompt = _build_system_prompt(AIMode.translate)
        assert "Persian" in prompt

    def test_translate_custom_language(self):
        prompt = _build_system_prompt(AIMode.translate, target_language="French")
        assert "French" in prompt
        assert "Persian" not in prompt

    def test_summarize(self):
        prompt = _build_system_prompt(AIMode.summarize)
        assert "bullet" in prompt.lower()

    def test_retone_default(self):
        prompt = _build_system_prompt(AIMode.retone)
        assert "professional" in prompt.lower()

    def test_retone_custom(self):
        prompt = _build_system_prompt(AIMode.retone, tone_prompt="casual and humorous")
        assert "casual and humorous" in prompt

    def test_custom_with_prompt(self):
        prompt = _build_system_prompt(
            AIMode.custom, custom_system_prompt="You are a pirate. Rewrite in pirate speak."
        )
        assert "pirate" in prompt

    def test_custom_fallback(self):
        prompt = _build_system_prompt(AIMode.custom)
        assert "helpful assistant" in prompt.lower()

    def test_off_returns_empty(self):
        prompt = _build_system_prompt(AIMode.off)
        assert prompt == ""


# ── Watermark tests ──────────────────────────────────────────────────────────


class TestApplyWatermark:
    def test_no_changes(self):
        text = "Hello world"
        result = apply_watermark(text)
        assert result == "Hello world"

    def test_append_watermark(self):
        result = apply_watermark("Hello world", watermark_text="🔗 Follow @mychannel")
        assert result.endswith("🔗 Follow @mychannel")
        assert "Hello world" in result

    def test_strip_hashtags(self):
        text = "Breaking news #crypto #news via @source_channel"
        result = apply_watermark(text, strip_source_tags=True)
        assert "#crypto" not in result
        assert "#news" not in result
        assert "@source_channel" not in result

    def test_strip_telegram_links(self):
        text = "Check out https://t.me/some_channel for more"
        result = apply_watermark(text, strip_source_tags=True)
        assert "https://t.me/some_channel" not in result

    def test_strip_and_watermark_combined(self):
        text = "News from #source @source_ch"
        result = apply_watermark(
            text,
            watermark_text="📌 Our Channel",
            strip_source_tags=True,
        )
        assert "#source" not in result
        assert "@source_ch" not in result
        assert "📌 Our Channel" in result

    def test_strip_cleans_extra_newlines(self):
        text = "Line 1\n\n\n\n\nLine 2"
        result = apply_watermark(text, strip_source_tags=True)
        assert "\n\n\n" not in result


# ── Transform text tests (with mocked OpenAI) ───────────────────────────────


class TestTransformText:
    @pytest.mark.asyncio
    async def test_off_mode_returns_unchanged(self):
        result = await transform_text("hello", mode=AIMode.off)
        assert result.text == "hello"
        assert result.model == "none"
        assert result.latency_ms == 0

    @pytest.mark.asyncio
    async def test_no_api_key_raises(self):
        with patch("shared.transform.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = ""
            with pytest.raises(AITransformError, match="AI_API_KEY"):
                await transform_text("hello", mode=AIMode.translate)

    @pytest.mark.asyncio
    async def test_successful_transform(self):
        mock_choice = MagicMock()
        mock_choice.message.content = "Translated text here"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 15

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o-mini"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("shared.transform.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test-key"
            mock_settings.return_value.ai_provider_url = "https://api.openai.com/v1"
            mock_settings.return_value.ai_timeout_seconds = 30
            mock_settings.return_value.ai_model = "gpt-4o-mini"
            mock_settings.return_value.ai_max_tokens = 2048

            with patch("shared.transform.AsyncOpenAI", return_value=mock_client):
                result = await transform_text(
                    "Hello world",
                    mode=AIMode.translate,
                    target_language="Persian",
                )

        assert result.text == "Translated text here"
        assert result.model == "gpt-4o-mini"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 15

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        mock_choice = MagicMock()
        mock_choice.message.content = ""

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("shared.transform.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test-key"
            mock_settings.return_value.ai_provider_url = "https://api.openai.com/v1"
            mock_settings.return_value.ai_timeout_seconds = 30
            mock_settings.return_value.ai_model = "gpt-4o-mini"
            mock_settings.return_value.ai_max_tokens = 2048

            with patch("shared.transform.AsyncOpenAI", return_value=mock_client):
                with pytest.raises(AITransformError, match="empty response"):
                    await transform_text("Hello", mode=AIMode.translate)

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        with patch("shared.transform.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test-key"
            mock_settings.return_value.ai_provider_url = "https://api.openai.com/v1"
            mock_settings.return_value.ai_timeout_seconds = 30
            mock_settings.return_value.ai_model = "gpt-4o-mini"
            mock_settings.return_value.ai_max_tokens = 2048

            with patch("shared.transform.AsyncOpenAI", return_value=mock_client):
                with pytest.raises(AITransformError, match="LLM API call failed"):
                    await transform_text("Hello", mode=AIMode.summarize)
